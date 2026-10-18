import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK))
load_dotenv(ROOT / ".env")
from app.config import app_api_key

q = (
    "What sample FROM email address is visible in the admin settings screenshot "
    "in the HAR capture article?"
)
headers = {"X-API-Key": app_api_key(), "Content-Type": "application/json"}
with httpx.Client(timeout=90.0) as client:
    r = client.post("http://127.0.0.1:8000/query", headers=headers, json={"question": q})
print("status", r.status_code)
data = r.json()
print("evidence", data.get("evidence"))
print("sources", data.get("sources"))
print("answer", (data.get("answer") or data.get("error") or "")[:800])
print("matches", data.get("matches"))
