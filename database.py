"""Database adapters for SQLite demos and the PostgreSQL ecommerce database."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row


class DatabaseError(RuntimeError):
    """Raised when a database cannot be inspected or queried safely."""


class Database(Protocol):
    dialect: str

    def schema(self) -> str: ...

    def execute(self, sql: str, max_rows: int = 100) -> list[dict[str, Any]]: ...


def create_database(target: str | Path | None = None) -> Database:
    """Create the configured database adapter without coupling it to the Agent."""
    resolved = target or os.getenv("DATABASE_URL")
    if resolved is None:
        resolved = Path(__file__).parent / "data" / "Chinook_Sqlite.sqlite"
    if str(resolved).startswith(("postgresql://", "postgres://")):
        return PostgresDatabase(str(resolved))
    return SQLiteDatabase(resolved)


class SQLiteDatabase:
    dialect = "sqlite"

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

    def execute(
        self,
        sql: str,
        max_rows: int = 100,
        timeout_seconds: float = 3.0,
    ) -> list[dict[str, Any]]:
        statement = sql.strip().rstrip(";").strip()
        if not statement:
            raise DatabaseError("模型没有生成 SQL。")
        if ";" in statement:
            raise DatabaseError("仅允许执行一条 SQL 语句。")

        with self._connect() as connection:
            deadline = time.monotonic() + timeout_seconds
            connection.set_progress_handler(
                lambda: int(time.monotonic() >= deadline),
                1_000,
            )
            try:
                cursor = connection.execute(statement)
                if cursor.description is None:
                    raise DatabaseError("只允许执行返回结果的只读查询。")
                rows = cursor.fetchmany(max_rows + 1)
            except sqlite3.Error as exc:
                if "interrupted" in str(exc).lower():
                    raise DatabaseError(
                        f"SQL 执行超过 {timeout_seconds:g} 秒，已终止。"
                    ) from exc
                raise DatabaseError(f"SQL 执行失败：{exc}") from exc

        if len(rows) > max_rows:
            raise DatabaseError(f"查询结果超过 {max_rows} 行，请缩小查询范围。")
        return [dict(row) for row in rows]


class PostgresDatabase:
    dialect = "postgres"

    def __init__(self, url: str, timeout_seconds: float = 3.0) -> None:
        if not url.startswith(("postgresql://", "postgres://")):
            raise DatabaseError("PostgreSQL URL 必须以 postgresql:// 或 postgres:// 开头。")
        self.url = url
        self.timeout_seconds = timeout_seconds

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        try:
            return psycopg.connect(
                self.url,
                row_factory=dict_row,
                connect_timeout=5,
            )
        except psycopg.Error as exc:
            raise DatabaseError(f"PostgreSQL 连接失败：{exc}") from exc

    def schema(self) -> str:
        columns_sql = """
            SELECT table_name, column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
        """
        foreign_keys_sql = """
            SELECT tc.table_name, kcu.column_name,
                   ccu.table_name AS foreign_table_name,
                   ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.constraint_schema = kcu.constraint_schema
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.constraint_schema = tc.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
            ORDER BY tc.table_name, kcu.column_name
        """
        try:
            with self._connect() as connection:
                columns = connection.execute(columns_sql).fetchall()
                foreign_keys = connection.execute(foreign_keys_sql).fetchall()
        except psycopg.Error as exc:
            raise DatabaseError(f"读取 PostgreSQL Schema 失败：{exc}") from exc

        if not columns:
            raise DatabaseError("PostgreSQL public schema 中没有可用数据表。")

        tables: dict[str, list[str]] = {}
        for column in columns:
            details = f"  {column['column_name']} {column['data_type']}"
            if column["is_nullable"] == "NO":
                details += " NOT NULL"
            if column["column_default"]:
                details += f" DEFAULT {column['column_default']}"
            tables.setdefault(column["table_name"], []).append(details)

        relationships: dict[str, list[str]] = {}
        for key in foreign_keys:
            relationships.setdefault(key["table_name"], []).append(
                "  FOREIGN KEY "
                f"({key['column_name']}) REFERENCES "
                f"{key['foreign_table_name']}({key['foreign_column_name']})"
            )

        blocks = []
        for table_name, table_columns in tables.items():
            lines = table_columns + relationships.get(table_name, [])
            blocks.append(f"TABLE {table_name} (\n" + ",\n".join(lines) + "\n)")
        business_rules = """
BUSINESS RULES:
- GMV: SUM(orders.total_amount) for status IN ('PAID', 'SHIPPED', 'COMPLETED', 'REFUNDED').
- Paid order count uses the same four paid statuses; CANCELLED and PENDING are excluded.
- Refund rate: refunded order count / paid order count. Use refunds.order_id to identify refunded orders.
- Net revenue: GMV minus SUM(refunds.refund_amount).
- Customer unit price (客单价): GMV / paid order count.
- PostgreSQL timestamps are stored as TIMESTAMPTZ; use PostgreSQL date functions such as DATE_TRUNC.
""".strip()
        return "\n\n".join(blocks + [business_rules])

    def execute(self, sql: str, max_rows: int = 100) -> list[dict[str, Any]]:
        try:
            with self._connect() as connection:
                with connection.transaction():
                    connection.execute("SET TRANSACTION READ ONLY")
                    connection.execute(
                        "SELECT set_config('statement_timeout', %s, true)",
                        (f"{int(self.timeout_seconds * 1000)}ms",),
                    )
                    cursor = connection.execute(sql)
                    if cursor.description is None:
                        raise DatabaseError("只允许执行返回结果的只读查询。")
                    rows = cursor.fetchmany(max_rows + 1)
        except psycopg.errors.QueryCanceled as exc:
            raise DatabaseError(
                f"SQL 执行超过 {self.timeout_seconds:g} 秒，已终止。"
            ) from exc
        except psycopg.Error as exc:
            raise DatabaseError(f"SQL 执行失败：{exc}") from exc

        if len(rows) > max_rows:
            raise DatabaseError(f"查询结果超过 {max_rows} 行，请缩小查询范围。")
        return [dict(row) for row in rows]
