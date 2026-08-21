"""Read-only database tools exposed through the official MCP Python SDK."""

from __future__ import annotations

import re
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from dotenv import load_dotenv

from database import Database, DatabaseError, create_database
from sql_guard import SQLGuard


def _table_names(schema: str) -> set[str]:
    patterns = (
        r"(?im)^TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        r"(?im)^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`\[]?([A-Za-z_][A-Za-z0-9_]*)",
    )
    names: set[str] = set()
    for pattern in patterns:
        names.update(re.findall(pattern, schema))
    return names


def _quote_identifier(identifier: str, dialect: str) -> str:
    quote = "`" if dialect == "mysql" else '"'
    return f"{quote}{identifier}{quote}"


def create_mcp_server(database: Database | None = None) -> MCPServer:
    """Build an injectable MCP server; production defaults to DATABASE_URL."""
    backend = database or create_database()
    guard = SQLGuard(max_rows=100, dialect=backend.dialect)
    server = MCPServer(
        "DataPilot Database",
        description="Read-only schema inspection and SQL execution for DataPilot.",
        version="0.7.0",
    )
    readonly = ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )

    @server.tool(structured_output=True, annotations=readonly)
    def get_schema() -> dict[str, Any]:
        """Return the database dialect and complete schema metadata."""
        schema = backend.schema()
        return {
            "dialect": backend.dialect,
            "schema": schema,
            "tables": sorted(_table_names(schema)),
        }

    @server.tool(structured_output=True, annotations=readonly)
    def execute_readonly_sql(sql: str) -> dict[str, Any]:
        """Validate and execute exactly one read-only SELECT/WITH query."""
        validated_sql = guard.require_valid(sql)
        rows = backend.execute(validated_sql, max_rows=100)
        return {
            "sql": validated_sql,
            "rows": rows,
            "row_count": len(rows),
        }

    @server.tool(structured_output=True, annotations=readonly)
    def get_table_statistics(table: str) -> dict[str, Any]:
        """Return the exact row count for one schema-approved table."""
        schema = backend.schema()
        available = _table_names(schema)
        if table not in available:
            raise DatabaseError(f"未知数据表：{table}")
        identifier = _quote_identifier(table, backend.dialect)
        rows = backend.execute(f"SELECT COUNT(*) AS row_count FROM {identifier}")
        return {
            "table": table,
            "row_count": int(rows[0]["row_count"]),
            "dialect": backend.dialect,
        }

    return server


if __name__ == "__main__":
    load_dotenv()
    create_mcp_server().run(transport="stdio")
