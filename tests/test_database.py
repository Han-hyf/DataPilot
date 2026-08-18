from __future__ import annotations

import sqlite3

import pytest

from database import DatabaseError, SQLiteDatabase


@pytest.fixture()
def sample_database(tmp_path):
    path = tmp_path / "sample.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        connection.executemany("INSERT INTO users(name) VALUES (?)", [("Ada",), ("Lin",)])
    return SQLiteDatabase(path)


def test_schema_contains_table(sample_database):
    assert "CREATE TABLE users" in sample_database.schema()


def test_execute_returns_dict_rows(sample_database):
    assert sample_database.execute("SELECT name FROM users ORDER BY id") == [
        {"name": "Ada"},
        {"name": "Lin"},
    ]


def test_database_is_read_only(sample_database):
    with pytest.raises(DatabaseError, match="SQL 执行失败"):
        sample_database.execute("DELETE FROM users")


def test_multiple_statements_are_rejected(sample_database):
    with pytest.raises(DatabaseError, match="一条 SQL"):
        sample_database.execute("SELECT 1; SELECT 2")


def test_long_running_query_is_interrupted(sample_database):
    sql = """
    WITH RECURSIVE counter(value) AS (
        VALUES (1)
        UNION ALL
        SELECT value + 1 FROM counter
    )
    SELECT SUM(value) FROM counter
    """
    with pytest.raises(DatabaseError, match="已终止"):
        sample_database.execute(sql, timeout_seconds=0.001)
