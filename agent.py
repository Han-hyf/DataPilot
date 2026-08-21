"""LangGraph workflow for the DataPilot Text2SQL and Schema RAG pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from dotenv import load_dotenv

from database import Database, DatabaseError, create_database
from llm import DeepSeekLLM
from mcp_client import MCPDatabase
from mcp_server import create_mcp_server
from schema_retriever import SchemaRetriever
from sql_guard import SQLGuard, SQLValidationError


@dataclass(frozen=True)
class QueryResult:
    question: str
    sql: str
    rows: list[dict[str, Any]]
    answer: str
    retry_count: int
    retrieved_tables: tuple[str, ...]


class AgentState(TypedDict):
    """Shared state passed between the V7 workflow nodes."""

    question: str
    full_schema: NotRequired[str]
    schema: NotRequired[str]
    retrieved_tables: NotRequired[tuple[str, ...]]
    retrieval_fallback: NotRequired[bool]
    sql: NotRequired[str]
    rows: NotRequired[list[dict[str, Any]]]
    answer: NotRequired[str]
    validation_error: NotRequired[str]
    execution_error: NotRequired[str]
    retry_count: int


class DataPilot:
    def __init__(
        self,
        database_target: str | Path | None = None,
        max_retries: int = 3,
        use_mcp: bool | None = None,
        use_schema_rag: bool = True,
        llm: Any | None = None,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries 不能小于 0。")
        load_dotenv()
        backend = create_database(database_target)
        if use_mcp is None:
            use_mcp = os.getenv("DATAPILOT_USE_MCP", "true").strip().lower() not in {
                "0",
                "false",
                "no",
                "off",
            }
        self.database: Database = (
            MCPDatabase(create_mcp_server(backend), backend.dialect)
            if use_mcp
            else backend
        )
        self.llm = llm or DeepSeekLLM()
        self.schema_retriever = SchemaRetriever(top_k=3)
        self.use_schema_rag = use_schema_rag
        self.sql_guard = SQLGuard(max_rows=100, dialect=self.database.dialect)
        self.max_retries = max_retries
        self.graph = self._build_graph()

    def _get_schema(self, state: AgentState) -> dict[str, str]:
        return {"full_schema": self.database.schema()}

    def _retrieve_schema(self, state: AgentState) -> dict[str, Any]:
        if not self.use_schema_rag:
            return {
                "schema": state["full_schema"],
                "retrieved_tables": (),
                "retrieval_fallback": True,
            }
        result = self.schema_retriever.retrieve(
            question=state["question"],
            schema=state["full_schema"],
            dialect=self.database.dialect,
        )
        return {
            "schema": result.context,
            "retrieved_tables": result.selected_tables,
            "retrieval_fallback": result.used_fallback,
        }

    def _generate_sql(self, state: AgentState) -> dict[str, str]:
        return {
            "sql": self.llm.generate_sql(
                state["question"], state["schema"], self.database.dialect
            )
        }

    def _validate_sql(self, state: AgentState) -> dict[str, str]:
        result = self.sql_guard.validate(state["sql"])
        if result.is_valid:
            return {"sql": result.sql, "validation_error": ""}
        return {"validation_error": result.error}

    @staticmethod
    def _route_after_validation(state: AgentState) -> Literal["execute_sql", "reject"]:
        return "reject" if state.get("validation_error") else "execute_sql"

    @staticmethod
    def _reject(state: AgentState) -> dict[str, str]:
        return {"answer": f"查询已被 SQL Guard 拒绝：{state['validation_error']}"}

    def _execute_sql(self, state: AgentState) -> dict[str, Any]:
        try:
            rows = self.database.execute(state["sql"])
        except DatabaseError as exc:
            return {"execution_error": str(exc)}
        return {"rows": rows, "execution_error": ""}

    def _route_after_execution(
        self, state: AgentState
    ) -> Literal["analyze_result", "repair_sql", "fail"]:
        if not state.get("execution_error"):
            return "analyze_result"
        if state["retry_count"] < self.max_retries:
            return "repair_sql"
        return "fail"

    def _repair_sql(self, state: AgentState) -> dict[str, Any]:
        repaired_sql = self.llm.repair_sql(
            question=state["question"],
            schema=state["schema"],
            sql=state["sql"],
            error=state["execution_error"],
            dialect=self.database.dialect,
        )
        return {
            "sql": repaired_sql,
            "retry_count": state["retry_count"] + 1,
            "execution_error": "",
        }

    @staticmethod
    def _fail(state: AgentState) -> dict[str, str]:
        return {
            "answer": (
                f"SQL 在 {state['retry_count']} 次修复后仍执行失败："
                f"{state['execution_error']}"
            )
        }

    def _analyze_result(self, state: AgentState) -> dict[str, str]:
        return {
            "answer": self.llm.analyze(
                state["question"],
                state["sql"],
                state["rows"],
            )
        }

    def _build_graph(self) -> CompiledStateGraph:
        builder = StateGraph(AgentState)
        builder.add_node("get_schema", self._get_schema)
        builder.add_node("retrieve_schema", self._retrieve_schema)
        builder.add_node("generate_sql", self._generate_sql)
        builder.add_node("validate_sql", self._validate_sql)
        builder.add_node("execute_sql", self._execute_sql)
        builder.add_node("repair_sql", self._repair_sql)
        builder.add_node("analyze_result", self._analyze_result)
        builder.add_node("reject", self._reject)
        builder.add_node("fail", self._fail)

        builder.add_edge(START, "get_schema")
        builder.add_edge("get_schema", "retrieve_schema")
        builder.add_edge("retrieve_schema", "generate_sql")
        builder.add_edge("generate_sql", "validate_sql")
        builder.add_conditional_edges(
            "validate_sql",
            self._route_after_validation,
            {"execute_sql": "execute_sql", "reject": "reject"},
        )
        builder.add_conditional_edges(
            "execute_sql",
            self._route_after_execution,
            {
                "analyze_result": "analyze_result",
                "repair_sql": "repair_sql",
                "fail": "fail",
            },
        )
        builder.add_edge("repair_sql", "validate_sql")
        builder.add_edge("analyze_result", END)
        builder.add_edge("reject", END)
        builder.add_edge("fail", END)
        return builder.compile()

    def ask(self, question: str) -> QueryResult:
        question = question.strip()
        if not question:
            raise ValueError("问题不能为空。")
        state = self.graph.invoke({"question": question, "retry_count": 0})
        if state.get("validation_error"):
            raise SQLValidationError(state["validation_error"])
        if state.get("execution_error"):
            raise DatabaseError(state["answer"])
        return QueryResult(
            question=state["question"],
            sql=state["sql"],
            rows=state["rows"],
            answer=state["answer"],
            retry_count=state["retry_count"],
            retrieved_tables=state["retrieved_tables"],
        )
