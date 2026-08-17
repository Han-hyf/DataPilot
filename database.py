"""Read-only SQLite access and schema inspection for DataPilot V0."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class DatabaseError(RuntimeError):
    """Raised when the local database cannot be queried safely."""


class SQLiteDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise DatabaseError(
                f"数据库不存在：{self.path}。请先运行 python scripts/download_chinook.py"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    def schema(self) -> str:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sql
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                  AND sql IS NOT NULL
                ORDER BY name
                """
            ).fetchall()
        if not rows:
            raise DatabaseError("数据库中没有可用的数据表。")
        return "\n\n".join(row["sql"] for row in rows)

    def execute(self, sql: str, max_rows: int = 100) -> list[dict[str, Any]]:
        statement = sql.strip().rstrip(";").strip()
        if not statement:
            raise DatabaseError("模型没有生成 SQL。")
        if ";" in statement:
            raise DatabaseError("V0 仅允许执行一条 SQL 语句。")

        with self._connect() as connection:
            try:
                cursor = connection.execute(statement)
                if cursor.description is None:
                    raise DatabaseError("只允许执行返回结果的只读查询。")
                rows = cursor.fetchmany(max_rows + 1)
            except sqlite3.Error as exc:
                raise DatabaseError(f"SQL 执行失败：{exc}") from exc

        if len(rows) > max_rows:
            raise DatabaseError(f"查询结果超过 {max_rows} 行，请缩小查询范围。")
        return [dict(row) for row in rows]
