from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from agent import QueryResult
from api import app, get_datapilot


class FakeDatabase:
    dialect = "postgres"

    def execute(self, sql):
        assert sql == "SELECT 1 AS ok"
        return [{"ok": 1}]

    def schema(self):
        return "TABLE users (id bigint)"


class FakeGraph:
    def stream(self, state, stream_mode, version):
        assert stream_mode == "updates"
        assert version == "v2"
        updates = [
            {"get_schema": {"full_schema": "TABLE users (id bigint)"}},
            {
                "retrieve_schema": {
                    "schema": "TABLE users (id bigint)",
                    "retrieved_tables": ("users",),
                    "retrieval_fallback": False,
                }
            },
            {"generate_sql": {"sql": "SELECT COUNT(*) AS count FROM users"}},
            {"validate_sql": {"sql": "SELECT COUNT(*) AS count FROM users LIMIT 100"}},
            {"execute_sql": {"rows": [{"count": 2}], "execution_error": ""}},
            {"analyze_result": {"answer": "共有 2 位用户。"}},
        ]
        for update in updates:
            yield {"type": "updates", "ns": (), "data": update}


class FakePilot:
    database = FakeDatabase()
    graph = FakeGraph()

    def ask(self, question):
        return QueryResult(
            question=question,
            sql="SELECT COUNT(*) AS count FROM users LIMIT 100",
            rows=[{"count": 2}],
            answer="共有 2 位用户。",
            retry_count=0,
            retrieved_tables=("users",),
        )


@pytest.fixture()
def client():
    app.dependency_overrides[get_datapilot] = lambda: FakePilot()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "postgres"}


def test_web_ui_and_assets(client):
    page = client.get("/")
    script = client.get("/assets/app.js")
    stylesheet = client.get("/assets/styles.css")

    assert page.status_code == 200
    assert "DataPilot" in page.text
    assert 'id="queryForm"' in page.text
    assert script.status_code == 200
    assert "consumeSse" in script.text
    assert stylesheet.status_code == 200
    assert "--accent" in stylesheet.text


def test_schema(client):
    response = client.get("/api/schema")
    assert response.status_code == 200
    assert response.json() == {
        "dialect": "postgres",
        "schema": "TABLE users (id bigint)",
    }


@pytest.mark.parametrize("path", ["/api/query", "/api/chat"])
def test_query_endpoints(client, path):
    response = client.post(path, json={"question": "有多少用户？"})
    assert response.status_code == 200
    assert response.json()["answer"] == "共有 2 位用户。"
    assert response.json()["rows"] == [{"count": 2}]
    assert response.json()["retrieved_tables"] == ["users"]


def test_question_validation(client):
    response = client.post("/api/query", json={"question": ""})
    assert response.status_code == 422


def test_sse_stream_contains_progress_result_and_done(client):
    response = client.post(
        "/api/chat/stream",
        json={"question": "有多少用户？"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: progress" in response.text
    assert '"stage": "get_schema"' in response.text
    assert '"stage": "retrieve_schema"' in response.text
    assert "event: result" in response.text
    assert '"answer":' in response.text
    assert "event: done" in response.text
    assert "data: [DONE]" in response.text
