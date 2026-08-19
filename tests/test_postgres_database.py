from __future__ import annotations

import pytest

from database import DatabaseError, PostgresDatabase


def test_postgres_database_validates_url():
    with pytest.raises(DatabaseError, match="PostgreSQL URL"):
        PostgresDatabase("sqlite:///data.db")


def test_postgres_database_exposes_postgres_dialect():
    database = PostgresDatabase("postgresql://reader:secret@localhost/datapilot")
    assert database.dialect == "postgres"
    assert database.timeout_seconds == 3.0
