"""Minimal natural-language-to-SQL pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from database import SQLiteDatabase
from llm import DeepSeekLLM


@dataclass(frozen=True)
class QueryResult:
    question: str
    sql: str
    rows: list[dict[str, Any]]
    answer: str


class DataPilot:
    def __init__(self, database_path: str | Path) -> None:
        self.database = SQLiteDatabase(database_path)
        self.llm = DeepSeekLLM()

    def ask(self, question: str) -> QueryResult:
        question = question.strip()
        if not question:
            raise ValueError("问题不能为空。")
        schema = self.database.schema()
        sql = self.llm.generate_sql(question, schema)
        rows = self.database.execute(sql)
        answer = self.llm.analyze(question, sql, rows)
        return QueryResult(question=question, sql=sql, rows=rows, answer=answer)
