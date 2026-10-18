"""Hit local API routes. Prints statuses only; never prints secrets."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK))
load_dotenv(ROOT / ".env")
load_dotenv(TASK / ".env", override=False)

from app.config import app_api_key  # noqa: E402

BASE = "http://127.0.0.1:8000"


def main() -> None:
    key = app_api_key()
    headers = {"X-API-Key": key, "Content-Type": "application/json"}
    with httpx.Client(timeout=60.0) as client:
        health = client.get(f"{BASE}/health")
        print("GET /health", health.status_code, health.json())

        unauth = client.get(f"{BASE}/ingestion/status")
        print("GET /ingestion/status no-key", unauth.status_code)

        status = client.get(f"{BASE}/ingestion/status", headers=headers)
        body = status.json()
        print(
            "GET /ingestion/status",
            status.status_code,
            {
                "chroma_vectors": body.get("chroma_vectors"),
                "active_chunks": body.get("active_chunks"),
                "pages_ok": (body.get("pages") or {}).get("ok"),
            },
        )

        weak = client.post(
            f"{BASE}/query",
            headers=headers,
            json={"question": "How do I teleport members to Mars from the admin dashboard?"},
        )
        weak_json = weak.json()
        print(
            "POST /query weak",
            weak.status_code,
            {
                "answer": weak_json.get("answer"),
                "evidence": weak_json.get("evidence"),
                "escalation_id": weak_json.get("escalation_id"),
                "code": weak_json.get("code"),
            },
        )

        strong = client.post(
            f"{BASE}/query",
            headers=headers,
            json={"question": "How do I upload a social media sharing image to the site?"},
        )
        strong_json = strong.json()
        print(
            "POST /query strong",
            strong.status_code,
            {
                "evidence": strong_json.get("evidence") or (strong_json.get("detail") or {}).get("evidence")
                if isinstance(strong_json.get("detail"), dict)
                else strong_json.get("evidence"),
                "code": strong_json.get("code")
                or (
                    (strong_json.get("detail") or {}).get("code")
                    if isinstance(strong_json.get("detail"), dict)
                    else None
                ),
                "error": bool(strong_json.get("error") or strong_json.get("detail")),
                "sources": strong_json.get("sources")
                or (
                    (strong_json.get("detail") or {}).get("sources")
                    if isinstance(strong_json.get("detail"), dict)
                    else None
                ),
            },
        )

        created = client.post(
            f"{BASE}/escalations",
            headers=headers,
            json={"question": "Does BD support quantum faxing?", "reason": "manual"},
        )
        print("POST /escalations", created.status_code, created.json())
        esc_id = created.json().get("id")
        resolved = client.post(
            f"{BASE}/escalations/{esc_id}/resolve",
            headers=headers,
            json={"note": "Not a Brilliant Directories feature. Versioned knowledge for eval."},
        )
        print("POST /escalations/{id}/resolve", resolved.status_code, resolved.json())


if __name__ == "__main__":
    main()
