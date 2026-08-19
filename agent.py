"""LangGraph workflow for the DataPilot Text2SQL pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from database import DatabaseError, SQLiteDatabase
from llm import DeepSeekLLM
from sql_guard import SQLGuard, SQLValidationError


@dataclass(frozen=True)
class QueryResult:
    question: str
    sql: str
    rows: list[dict[str, Any]]
    answer: str
    retry_count: int


class AgentState(TypedDict):
    """Shared state passed between the V3 workflow nodes."""

    question: str
    schema: NotRequired[str]
    sql: NotRequired[str]
    rows: NotRequired[list[dict[str, Any]]]
    answer: NotRequired[str]
    validation_error: NotRequired[str]
    execution_error: NotRequired[str]
    retry_count: int


class DataPilot:
    def __init__(self, database_path: str | Path, max_retries: int = 3) -> None:
        if max_retries < 0:
            raise ValueError("max_retries 不能小于 0。")
        self.database = SQLiteDatabase(database_path)
        self.llm = DeepSeekLLM()
        self.sql_guard = SQLGuard(max_rows=100)
        self.max_retries = max_retries
        self.graph = self._build_graph()

    def _get_schema(self, state: AgentState) -> dict[str, str]:
        return {"schema": self.database.schema()}

    def _generate_sql(self, state: AgentState) -> dict[str, str]:
        return {"sql": self.llm.generate_sql(state["question"], state["schema"])}

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
        builder.add_node("generate_sql", self._generate_sql)
        builder.add_node("validate_sql", self._validate_sql)
        builder.add_node("execute_sql", self._execute_sql)
        builder.add_node("repair_sql", self._repair_sql)
        builder.add_node("analyze_result", self._analyze_result)
        builder.add_node("reject", self._reject)
        builder.add_node("fail", self._fail)

        builder.add_edge(START, "get_schema")
        builder.add_edge("get_schema", "generate_sql")
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
        )
