from __future__ import annotations

from agent import DataPilot


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

    assert result.sql == "SELECT COUNT(*) AS count FROM users"
    assert result.answer == "共有 2 位用户。"
