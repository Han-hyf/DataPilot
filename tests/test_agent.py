from __future__ import annotations

import pytest

from agent import DataPilot
from sql_guard import SQLValidationError


class FakeLLM:
    def generate_sql(self, question, schema):
        assert question == "有多少用户？"
        assert "users" in schema
        return "SELECT COUNT(*) AS count FROM users"

    def analyze(self, question, sql, rows):
        assert rows == [{"count": 2}]
        return "共有 2 位用户。"


def test_pipeline_uses_real_query_result(tmp_path, monkeypatch):
    import sqlite3

    path = tmp_path / "sample.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        connection.executemany("INSERT INTO users DEFAULT VALUES", [(), ()])

    monkeypatch.setattr("agent.DeepSeekLLM", FakeLLM)
    result = DataPilot(path).ask("有多少用户？")

    assert result.sql == "SELECT COUNT(*) AS count FROM users LIMIT 100"
    assert result.answer == "共有 2 位用户。"


def test_graph_has_explicit_v2_workflow(tmp_path, monkeypatch):
    import sqlite3

    path = tmp_path / "sample.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")

    monkeypatch.setattr("agent.DeepSeekLLM", FakeLLM)
    graph = DataPilot(path).graph.get_graph()

    assert {
        "get_schema",
        "generate_sql",
        "validate_sql",
        "execute_sql",
        "analyze_result",
        "reject",
    } <= set(graph.nodes)
    edges = {(edge.source, edge.target) for edge in graph.edges}
    assert ("get_schema", "generate_sql") in edges
    assert ("generate_sql", "validate_sql") in edges
    assert ("validate_sql", "execute_sql") in edges
    assert ("validate_sql", "reject") in edges
    assert ("execute_sql", "analyze_result") in edges


class UnsafeLLM(FakeLLM):
    def generate_sql(self, question, schema):
        return "DELETE FROM users"

    def analyze(self, question, sql, rows):
        raise AssertionError("被拒绝的 SQL 不应进入结果分析节点")


def test_guard_rejects_before_database_execution(tmp_path, monkeypatch):
    import sqlite3

    path = tmp_path / "sample.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")

    monkeypatch.setattr("agent.DeepSeekLLM", UnsafeLLM)
    pilot = DataPilot(path)
    monkeypatch.setattr(
        pilot.database,
        "execute",
        lambda sql: (_ for _ in ()).throw(AssertionError("不应执行危险 SQL")),
    )

    with pytest.raises(SQLValidationError, match="仅允许 SELECT"):
        pilot.ask("删除所有用户")
