from __future__ import annotations

import pytest

from sql_guard import SQLGuard, SQLValidationError


@pytest.fixture()
def guard():
    return SQLGuard(max_rows=100)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM users",
        "UPDATE users SET name = 'x'",
        "INSERT INTO users(name) VALUES ('x')",
        "DROP TABLE users",
        "ALTER TABLE users ADD COLUMN email TEXT",
        "CREATE TABLE secrets(id INTEGER)",
        "PRAGMA table_info(users)",
        "SELECT 1; SELECT 2",
    ],
)
def test_rejects_unsafe_or_multiple_statements(guard, sql):
    result = guard.validate(sql)
    assert result.is_valid is False
    assert result.error


def test_allows_cte_query_and_adds_limit(guard):
    result = guard.validate(
        "WITH totals AS (SELECT COUNT(*) AS count FROM users) SELECT * FROM totals"
    )
    assert result.is_valid is True
    assert result.sql.endswith("LIMIT 100")


def test_preserves_smaller_limit(guard):
    assert guard.require_valid("SELECT * FROM users LIMIT 5").endswith("LIMIT 5")


def test_clamps_large_limit(guard):
    assert guard.require_valid("SELECT * FROM users LIMIT 1000").endswith("LIMIT 100")


def test_rejects_extension_loading(guard):
    with pytest.raises(SQLValidationError, match="load_extension"):
        guard.require_valid("SELECT load_extension('unsafe')")


def test_postgres_dialect_preserves_postgres_syntax():
    guard = SQLGuard(max_rows=100, dialect="postgres")
    sql = guard.require_valid(
        "SELECT DATE_TRUNC('month', created_at) AS month FROM orders"
    )
    assert "DATE_TRUNC('MONTH', created_at)" in sql
    assert sql.endswith("LIMIT 100")
