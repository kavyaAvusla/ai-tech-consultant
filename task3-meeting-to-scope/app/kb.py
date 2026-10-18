from __future__ import annotations

import httpx

from app.config import KB_API_URL, KB_TIMEOUT_SECONDS, kb_api_key, redact
from app.db import cache_kb, cached_kb
from app.schemas import EvidenceLevel, KbQueryRecord


def query_knowledge(requirement_id: str, question: str) -> KbQueryRecord:
    cached = cached_kb(question)
    if cached is not None:
        return KbQueryRecord.model_validate(cached)
    record = _query_live(requirement_id, question)
    if record.failure is None:
        cache_kb(question, record.model_dump())
    return record


def _query_live(requirement_id: str, question: str) -> KbQueryRecord:
    key = kb_api_key()
    url = f"{KB_API_URL}/query"
    last_failure = "network"
    for _attempt in range(2):
        try:
            response = httpx.post(
                url,
                json={"question": question},
                headers={"X-API-Key": key, "Content-Type": "application/json"},
                timeout=KB_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException:
            last_failure = "timeout"
            continue
        except httpx.HTTPError as exc:
            last_failure = "network"
            _ = redact(str(exc))
            continue
        return _from_response(requirement_id, question, response)
    return KbQueryRecord(
        requirement_id=requirement_id,
        question=question,
        evidence="unavailable",
        answer="",
        sources=[],
        failure=last_failure,
    )


def _from_response(requirement_id: str, question: str, response: httpx.Response) -> KbQueryRecord:
    if response.status_code == 401:
        return _unavailable(requirement_id, question, "unauthorized")
    if response.status_code == 402:
        return _unavailable(requirement_id, question, "billing")
    try:
        payload = response.json()
    except ValueError:
        return _unavailable(requirement_id, question, "invalid_response")
    if response.status_code >= 400:
        return _unavailable(requirement_id, question, "http_error")
    if not isinstance(payload, dict):
        return _unavailable(requirement_id, question, "invalid_response")
    answer = payload.get("answer")
    answer_text = answer.strip() if isinstance(answer, str) else ""
    sources = [item for item in payload.get("sources") or [] if isinstance(item, str)]
    evidence_raw = payload.get("evidence")
    evidence: EvidenceLevel
    if evidence_raw == "strong" and answer_text and answer_text.lower() != "not enough evidence":
        evidence = "strong"
    elif answer_text:
        evidence = "weak"
    else:
        evidence = "unavailable"
    failure = None if evidence == "strong" else (payload.get("code") if isinstance(payload.get("code"), str) else None)
    if evidence != "strong" and failure is None and answer_text.lower() == "not enough evidence":
        failure = "not_enough_evidence"
    return KbQueryRecord(
        requirement_id=requirement_id,
        question=question,
        evidence=evidence,
        answer=answer_text[:2000],
        sources=sources,
        failure=None if evidence == "strong" else (failure or "weak_evidence"),
    )


def _unavailable(requirement_id: str, question: str, failure: str) -> KbQueryRecord:
    return KbQueryRecord(
        requirement_id=requirement_id,
        question=question,
        evidence="unavailable",
        answer="",
        sources=[],
        failure=failure,
    )
