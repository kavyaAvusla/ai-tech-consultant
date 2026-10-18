from __future__ import annotations

import threading
from typing import Any

from app.config import CRAWL_LIMIT, redact
from app.ingest import run_ingest

_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "counts": None,
    "error": None,
}


def snapshot() -> dict[str, Any]:
    return dict(_state)


def _run(limit: int) -> None:
    from app.db import utcnow

    try:
        counts = run_ingest(limit)
        _state["counts"] = counts
        _state["error"] = None
    except Exception as exc:
        _state["error"] = redact(f"{type(exc).__name__}: {exc}")
    finally:
        _state["running"] = False
        _state["finished_at"] = utcnow()
        if _lock.locked():
            _lock.release()


def start(limit: int | None = None) -> dict[str, Any]:
    from app.db import utcnow

    if not _lock.acquire(blocking=False):
        return {"accepted": False, "message": "ingestion already running", **snapshot()}
    _state.update(
        {
            "running": True,
            "started_at": utcnow(),
            "finished_at": None,
            "error": None,
        }
    )
    thread = threading.Thread(
        target=_run, args=(limit if limit is not None else CRAWL_LIMIT,), daemon=True
    )
    thread.start()
    return {"accepted": True, "message": "ingestion started", **snapshot()}
