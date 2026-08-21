"""Database adapter backed by an MCP Client transport."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp import Client
from mcp.server import MCPServer

from database import DatabaseError


class MCPDatabase:
    """Expose MCP database tools through DataPilot's synchronous Database protocol."""

    def __init__(self, server: MCPServer, dialect: str) -> None:
        self.server = server
        self.dialect = dialect

    async def _call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        async with Client(self.server, raise_exceptions=False) as client:
            result = await client.call_tool(name, arguments or {})
        if result.is_error:
            message = "MCP 工具调用失败。"
            if result.content and hasattr(result.content[0], "text"):
                message = result.content[0].text
            raise DatabaseError(message)
        if result.structured_content is None:
            raise DatabaseError(f"MCP 工具 {name} 未返回结构化结果。")
        return result.structured_content

    def _call_sync(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._call(name, arguments))
        raise DatabaseError("同步 MCPDatabase 不能在正在运行的事件循环中调用。")

    def schema(self) -> str:
        result = self._call_sync("get_schema")
        return str(result["schema"])

    def execute(self, sql: str, max_rows: int = 100) -> list[dict[str, Any]]:
        if max_rows > 100:
            raise DatabaseError("MCP 数据库工具最多返回 100 行。")
        result = self._call_sync("execute_readonly_sql", {"sql": sql})
        return list(result["rows"])

    def table_statistics(self, table: str) -> dict[str, Any]:
        return dict(self._call_sync("get_table_statistics", {"table": table}))
