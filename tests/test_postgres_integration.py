from __future__ import annotations

import os

import psycopg
import pytest
from dotenv import load_dotenv

from database import PostgresDatabase


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_TESTS") != "1",
    reason="set RUN_POSTGRES_TESTS=1 to run PostgreSQL integration tests",
)


@pytest.fixture(scope="module")
def postgres_database():
    load_dotenv()
    return PostgresDatabase(os.environ["DATABASE_URL"])


def test_ecommerce_schema_and_seed_counts(postgres_database):
    schema = postgres_database.schema()
    assert schema.count("TABLE ") == 7
    assert "BUSINESS RULES" in schema
    rows = postgres_database.execute(
        "SELECT (SELECT COUNT(*) FROM users) AS users, "
        "(SELECT COUNT(*) FROM products) AS products, "
        "(SELECT COUNT(*) FROM orders) AS orders"
    )
    assert rows == [{"users": 10_000, "products": 500, "orders": 50_000}]


def test_agent_role_cannot_write():
    load_dotenv()
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            connection.execute("DELETE FROM users WHERE id = -1")
