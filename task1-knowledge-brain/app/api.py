from __future__ import annotations

import hmac
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import jobs, store
from app.config import CRAWL_LIMIT, MODEL_NAME, app_api_key
from app.db import get_conn
from app.rag import answer_question, create_escalation, resolve_escalation

app = FastAPI(
    title="Knowledge Brain API",
    description=(
        "Crawl Brilliant Directories support articles, search them locally, "
        "and answer with Claude. Send header `X-API-Key` on every route except /health. "
        "Interactive docs: /docs"
    ),
    version="0.2.0",
)


class QueryBody(BaseModel):
    question: str = Field(..., min_length=3)


class IngestBody(BaseModel):
    limit: int | None = Field(default=None, ge=0, le=200)


class EscalationBody(BaseModel):
    question: str = Field(..., min_length=3)
    reason: str = Field(default="manual")


class ResolveBody(BaseModel):
    note: str = Field(..., min_length=3)


def require_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    expected = app_api_key()
    provided = x_api_key or ""
    if not expected or len(provided) != len(expected) or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


@app.get("/health", tags=["ops"])
def health() -> dict[str, Any]:
    db_ok = False
    chroma_ok = False
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1")
            db_ok = True
    except Exception:
        db_ok = False
    try:
        store.count()
        chroma_ok = True
    except Exception:
        chroma_ok = False
    status = "ok" if db_ok else "degraded"
    return {"status": status, "db": db_ok, "chroma": chroma_ok, "model": MODEL_NAME}


@app.post("/query", tags=["qa"], dependencies=[Depends(require_key)])
def query(body: QueryBody) -> dict[str, Any]:
    result = answer_question(body.question.strip())
    if result.get("code") == "billing":
        return JSONResponse(status_code=402, content=result)
    return result


@app.post("/ingestion/run", tags=["ingest"], dependencies=[Depends(require_key)])
def ingestion_run(body: IngestBody | None = None) -> dict[str, Any]:
    limit = CRAWL_LIMIT if body is None or body.limit is None else body.limit
    return jobs.start(limit)


@app.get("/ingestion/status", tags=["ingest"], dependencies=[Depends(require_key)])
def ingestion_status() -> dict[str, Any]:
    with get_conn() as conn:
        pages = conn.execute(
            """
            SELECT
              SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS active,
              SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) AS ok,
              SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
              SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error
            FROM pages
            """
        ).fetchone()
        chunks = conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE active = 1"
        ).fetchone()
        last = conn.execute(
            "SELECT * FROM ingest_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        open_esc = conn.execute(
            "SELECT COUNT(*) AS n FROM escalations WHERE status = 'open'"
        ).fetchone()
    return {
        "job": jobs.snapshot(),
        "pages": dict(pages) if pages else {},
        "active_chunks": chunks["n"] if chunks else 0,
        "chroma_vectors": store.count(),
        "open_escalations": open_esc["n"] if open_esc else 0,
        "last_run": dict(last) if last else None,
    }


@app.post("/escalations", tags=["escalations"], dependencies=[Depends(require_key)])
def escalations_create(body: EscalationBody) -> dict[str, Any]:
    escalation_id = create_escalation(body.question.strip(), body.reason.strip(), [])
    return {"id": escalation_id, "status": "open"}


@app.post(
    "/escalations/{escalation_id}/resolve",
    tags=["escalations"],
    dependencies=[Depends(require_key)],
)
def escalations_resolve(escalation_id: int, body: ResolveBody) -> dict[str, Any]:
    try:
        return resolve_escalation(escalation_id, body.note.strip())
    except KeyError:
        raise HTTPException(status_code=404, detail="escalation not found")
