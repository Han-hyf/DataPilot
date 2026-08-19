from __future__ import annotations

import pytest

from agent import DataPilot
from database import DatabaseError
from sql_guard import SQLValidationError


class FakeLLM:
    def generate_sql(self, question, schema, dialect):
        assert question == "有多少用户？"
        assert "users" in schema
        assert dialect == "sqlite"
        return "SELECT COUNT(*) AS count FROM users"

    def analyze(self, question, sql, rows):
        assert rows == [{"count": 2}]
        return "共有 2 位用户。"

    def repair_sql(self, question, schema, sql, error, dialect):
        raise AssertionError("正确 SQL 不应进入修复节点")


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
    assert result.retry_count == 0


def test_graph_has_explicit_v3_workflow(tmp_path, monkeypatch):
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
        "repair_sql",
        "analyze_result",
        "reject",
        "fail",
    } <= set(graph.nodes)
    edges = {(edge.source, edge.target) for edge in graph.edges}
    assert ("get_schema", "generate_sql") in edges
    assert ("generate_sql", "validate_sql") in edges
    assert ("validate_sql", "execute_sql") in edges
    assert ("validate_sql", "reject") in edges
    assert ("execute_sql", "analyze_result") in edges
    assert ("execute_sql", "repair_sql") in edges
    assert ("execute_sql", "fail") in edges
    assert ("repair_sql", "validate_sql") in edges


class UnsafeLLM(FakeLLM):
    def generate_sql(self, question, schema, dialect):
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


class RepairingLLM(FakeLLM):
    def generate_sql(self, question, schema, dialect):
        return "SELECT username FROM users"

    def repair_sql(self, question, schema, sql, error, dialect):
        assert "no such column: username" in error
        return "SELECT name FROM users ORDER BY id"

    def analyze(self, question, sql, rows):
        assert rows == [{"name": "Ada"}, {"name": "Lin"}]
        return "用户是 Ada 和 Lin。"


def test_execution_error_is_repaired_and_revalidated(tmp_path, monkeypatch):
    import sqlite3

    path = tmp_path / "sample.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        connection.executemany("INSERT INTO users(name) VALUES (?)", [("Ada",), ("Lin",)])

    monkeypatch.setattr("agent.DeepSeekLLM", RepairingLLM)
    result = DataPilot(path).ask("有哪些用户？")

    assert result.sql == "SELECT name FROM users ORDER BY id LIMIT 100"
    assert result.retry_count == 1
    assert result.answer == "用户是 Ada 和 Lin。"


class NeverRepairingLLM(RepairingLLM):
    repair_calls = 0

    def repair_sql(self, question, schema, sql, error, dialect):
        self.repair_calls += 1
        return "SELECT still_missing FROM users"

    def analyze(self, question, sql, rows):
        raise AssertionError("最终失败不应进入分析节点")


def test_reflection_stops_at_retry_limit(tmp_path, monkeypatch):
    import sqlite3

    path = tmp_path / "sample.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")

    monkeypatch.setattr("agent.DeepSeekLLM", NeverRepairingLLM)
    pilot = DataPilot(path, max_retries=2)

    with pytest.raises(DatabaseError, match="2 次修复后仍执行失败"):
        pilot.ask("有哪些用户？")
    assert pilot.llm.repair_calls == 2


class UnsafeRepairLLM(RepairingLLM):
    def repair_sql(self, question, schema, sql, error, dialect):
        return "DROP TABLE users"


def test_repaired_sql_cannot_bypass_guard(tmp_path, monkeypatch):
    import sqlite3

    path = tmp_path / "sample.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")

    monkeypatch.setattr("agent.DeepSeekLLM", UnsafeRepairLLM)
    with pytest.raises(SQLValidationError, match="仅允许 SELECT"):
        DataPilot(path).ask("有哪些用户？")

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'users'"
        ).fetchone()[0] == 1
