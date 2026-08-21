from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from mcp import Client

from database import DatabaseError, SQLiteDatabase
from mcp_client import MCPDatabase
from mcp_server import create_mcp_server


@pytest.fixture()
def sqlite_path(tmp_path: Path) -> Path:
    path = tmp_path / "mcp.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            INSERT INTO users (name) VALUES ('Ada'), ('Linus');
            """
        )
    return path


@pytest.mark.anyio
async def test_server_exposes_three_readonly_tools(sqlite_path: Path) -> None:
    server = create_mcp_server(SQLiteDatabase(sqlite_path))
    async with Client(server) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        schema = await client.call_tool("get_schema", {})
        query = await client.call_tool(
            "execute_readonly_sql",
            {"sql": "SELECT name FROM users ORDER BY id"},
        )
        statistics = await client.call_tool(
            "get_table_statistics", {"table": "users"}
        )

    assert names == {
        "get_schema",
        "execute_readonly_sql",
        "get_table_statistics",
    }
    assert schema.structured_content["dialect"] == "sqlite"
    assert schema.structured_content["tables"] == ["users"]
    assert query.structured_content["rows"] == [
        {"name": "Ada"},
        {"name": "Linus"},
    ]
    assert "LIMIT 100" in query.structured_content["sql"]
    assert statistics.structured_content["row_count"] == 2


@pytest.mark.anyio
async def test_server_rejects_writes_and_table_injection(sqlite_path: Path) -> None:
    server = create_mcp_server(SQLiteDatabase(sqlite_path))
    async with Client(server) as client:
        write = await client.call_tool(
            "execute_readonly_sql", {"sql": "DELETE FROM users"}
        )
        injection = await client.call_tool(
            "get_table_statistics", {"table": "users; DROP TABLE users"}
        )

    assert write.is_error is True
    assert injection.is_error is True


def test_mcp_database_adapter(sqlite_path: Path) -> None:
    backend = SQLiteDatabase(sqlite_path)
    database = MCPDatabase(create_mcp_server(backend), backend.dialect)

    assert "CREATE TABLE users" in database.schema()
    assert database.execute("SELECT COUNT(*) AS total FROM users") == [{"total": 2}]
    assert database.table_statistics("users")["row_count"] == 2
    with pytest.raises(DatabaseError):
        database.execute("UPDATE users SET name = 'x'")
