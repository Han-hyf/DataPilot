"""LangGraph workflow for the DataPilot Text2SQL pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from database import SQLiteDatabase
from llm import DeepSeekLLM


@dataclass(frozen=True)
class QueryResult:
    question: str
    sql: str
    rows: list[dict[str, Any]]
    answer: str


class AgentState(TypedDict):
    """Shared state passed between the V1 workflow nodes."""

    question: str
    schema: str
    sql: str
    rows: list[dict[str, Any]]
    answer: str


class DataPilot:
    def __init__(self, database_path: str | Path) -> None:
        self.database = SQLiteDatabase(database_path)
        self.llm = DeepSeekLLM()
        self.graph = self._build_graph()

    def _get_schema(self, state: AgentState) -> dict[str, str]:
        return {"schema": self.database.schema()}

    def _generate_sql(self, state: AgentState) -> dict[str, str]:
        return {"sql": self.llm.generate_sql(state["question"], state["schema"])}

    def _execute_sql(self, state: AgentState) -> dict[str, list[dict[str, Any]]]:
        return {"rows": self.database.execute(state["sql"])}

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
        builder.add_node("execute_sql", self._execute_sql)
        builder.add_node("analyze_result", self._analyze_result)

        builder.add_edge(START, "get_schema")
        builder.add_edge("get_schema", "generate_sql")
        builder.add_edge("generate_sql", "execute_sql")
        builder.add_edge("execute_sql", "analyze_result")
        builder.add_edge("analyze_result", END)
        return builder.compile()

    def ask(self, question: str) -> QueryResult:
        question = question.strip()
        if not question:
            raise ValueError("问题不能为空。")
        state = self.graph.invoke({"question": question})
        return QueryResult(
            question=state["question"],
            sql=state["sql"],
            rows=state["rows"],
            answer=state["answer"],
        )
