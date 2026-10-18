from __future__ import annotations

import os
from pathlib import Path

TASK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TASK_ROOT.parent
TRANSCRIPTS_DIR = TASK_ROOT / "transcripts"
PROMPTS_DIR = TASK_ROOT / "prompts"
DATA_DIR = TASK_ROOT / "data"
DB_PATH = DATA_DIR / "meeting_scope.sqlite"
SECTION_WINDOW = 10
SECTION_OVERLAP = 3
KB_TIMEOUT_SECONDS = float(os.getenv("KB_TIMEOUT_SECONDS", "90"))


def _parse_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value.strip()
    return values


_LOCAL = _parse_env(TASK_ROOT / ".env")
_ROOT = _parse_env(REPO_ROOT / ".env")


def _pick(*names: str, default: str = "") -> str:
    for source in (_LOCAL, _ROOT):
        for name in names:
            value = source.get(name, "").strip()
            if value:
                return value
    return default


PROMPT_VERSION = _pick("PROMPT_VERSION", default="v1")
MODEL_NAME = _pick("MODEL_NAME", default="claude-haiku-5-5")
KB_API_URL = _pick("KB_API_URL", default="http://127.0.0.1:8000").rstrip("/")


def kb_api_key() -> str:
    return _pick("KB_API_KEY", "APP_API_KEY")


def anthropic_api_key() -> str:
    return _pick("ANTHROPIC_API_KEY")


def hourly_rate() -> float | None:
    raw = _pick("HOURLY_RATE")
    if not raw:
        return None
    value = float(raw)
    if value <= 0:
        return None
    return value


def require_secrets() -> None:
    missing = []
    if not kb_api_key():
        missing.append("KB_API_KEY (copy the repo-root APP_API_KEY value)")
    if not anthropic_api_key():
        missing.append("ANTHROPIC_API_KEY (copy the repo-root ANTHROPIC_API_KEY value)")
    if missing:
        raise RuntimeError(
            "Copy these into task3-meeting-to-scope/.env by hand, then re-run: "
            + "; ".join(missing)
            + ". Do not paste the values into chat."
        )


def redact(text: str) -> str:
    out = text
    for secret in (kb_api_key(), anthropic_api_key(), _pick("APP_API_KEY")):
        if secret:
            out = out.replace(secret, "[redacted]")
    return out
