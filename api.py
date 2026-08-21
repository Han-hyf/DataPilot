"""FastAPI HTTP and SSE interface for DataPilot V8."""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field

from agent import AgentState, DataPilot, QueryResult
from database import DatabaseError
from llm import LLMError
from sql_guard import SQLValidationError


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2_000)


class QueryResponse(BaseModel):
    question: str
    sql: str
    rows: list[dict[str, Any]]
    answer: str
    retry_count: int
    retrieved_tables: list[str]

    @classmethod
    def from_result(cls, result: QueryResult) -> "QueryResponse":
        return cls(
            question=result.question,
            sql=result.sql,
            rows=result.rows,
            answer=result.answer,
            retry_count=result.retry_count,
            retrieved_tables=list(result.retrieved_tables),
        )


class HealthResponse(BaseModel):
    status: str
    database: str


class SchemaResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    dialect: str
    schema_text: str = Field(alias="schema")


@lru_cache(maxsize=1)
def get_datapilot() -> DataPilot:
    return DataPilot()


app = FastAPI(
    title="DataPilot API",
    version="0.8.0",
    description="Natural-language analytics over a read-only database.",
)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (ValueError, SQLValidationError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, DatabaseError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, LLMError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail="DataPilot 执行失败。")


@app.get("/api/health", response_model=HealthResponse)
def health(pilot: DataPilot = Depends(get_datapilot)) -> HealthResponse:
    try:
        pilot.database.execute("SELECT 1 AS ok")
    except Exception as exc:
        raise _http_error(exc) from exc
    return HealthResponse(status="ok", database=pilot.database.dialect)


@app.get("/api/schema", response_model=SchemaResponse)
def schema(pilot: DataPilot = Depends(get_datapilot)) -> SchemaResponse:
    try:
        value = pilot.database.schema()
    except Exception as exc:
        raise _http_error(exc) from exc
    return SchemaResponse(dialect=pilot.database.dialect, schema_text=value)


def _query(request: QueryRequest, pilot: DataPilot) -> QueryResponse:
    try:
        return QueryResponse.from_result(pilot.ask(request.question))
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post("/api/query", response_model=QueryResponse)
def query(
    request: QueryRequest,
    pilot: DataPilot = Depends(get_datapilot),
) -> QueryResponse:
    return _query(request, pilot)


@app.post("/api/chat", response_model=QueryResponse)
def chat(
    request: QueryRequest,
    pilot: DataPilot = Depends(get_datapilot),
) -> QueryResponse:
    return _query(request, pilot)


NODE_MESSAGES = {
    "get_schema": "已读取数据库 Schema",
    "retrieve_schema": "已检索相关 Schema",
    "generate_sql": "已生成 SQL",
    "validate_sql": "SQL 安全校验完成",
    "execute_sql": "数据库查询完成",
    "repair_sql": "SQL 自动修复完成",
    "analyze_result": "数据分析完成",
}


def _stream_events(
    request: QueryRequest,
    pilot: DataPilot,
) -> Iterable[ServerSentEvent]:
    question = request.question.strip()
    if not question:
        yield ServerSentEvent(event="error", data={"message": "问题不能为空。"})
        return

    state: AgentState = {"question": question, "retry_count": 0}
    yield ServerSentEvent(event="progress", data={"stage": "start", "message": "开始分析问题"})

    try:
        for part in pilot.graph.stream(
            state,
            stream_mode="updates",
            version="v2",
        ):
            if part["type"] != "updates":
                continue
            for node_name, update in part["data"].items():
                state.update(update)
                if node_name == "reject":
                    yield ServerSentEvent(
                        event="error",
                        data={"stage": "reject", "message": state["answer"]},
                    )
                    return
                if node_name == "fail":
                    yield ServerSentEvent(
                        event="error",
                        data={"stage": "fail", "message": state["answer"]},
                    )
                    return
                message = NODE_MESSAGES.get(node_name)
                if message:
                    payload: dict[str, Any] = {"stage": node_name, "message": message}
                    if node_name == "repair_sql":
                        payload["retry_count"] = state["retry_count"]
                    if node_name == "execute_sql" and not state.get("execution_error"):
                        payload["row_count"] = len(state.get("rows", []))
                    yield ServerSentEvent(event="progress", data=payload)

        result = QueryResponse(
            question=state["question"],
            sql=state["sql"],
            rows=state["rows"],
            answer=state["answer"],
            retry_count=state["retry_count"],
            retrieved_tables=list(state["retrieved_tables"]),
        )
        yield ServerSentEvent(event="result", data=jsonable_encoder(result))
        yield ServerSentEvent(event="done", raw_data="[DONE]")
    except Exception as exc:
        error = _http_error(exc)
        yield ServerSentEvent(
            event="error",
            data={"stage": "exception", "message": error.detail},
        )


@app.post("/api/chat/stream", response_class=EventSourceResponse)
def stream_chat(
    request: QueryRequest,
    pilot: DataPilot = Depends(get_datapilot),
) -> Iterable[ServerSentEvent]:
    return _stream_events(request, pilot)
