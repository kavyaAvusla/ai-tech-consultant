from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

TASK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TASK_ROOT.parent
DATA_DIR = TASK_ROOT / "data"
DB_PATH = DATA_DIR / "brain.sqlite"
CHROMA_DIR = DATA_DIR / "chroma"

load_dotenv(REPO_ROOT / ".env")
load_dotenv(TASK_ROOT / ".env", override=False)

SITEMAP_URL = "https://support.brilliantdirectories.com/support/sitemap.xml"
SITE_ORIGIN = "https://support.brilliantdirectories.com"
ARTICLE_PATH_PREFIX = "/support/solutions/articles/"
USER_AGENT = (
    "AITechConsultant-KnowledgeBrain/0.1 "
    "(capstone; polite crawler; contact=local-dev)"
)

MODEL_NAME = os.getenv("MODEL_NAME", "claude-haiku-5-5")
CRAWL_LIMIT = int(os.getenv("CRAWL_LIMIT", "20"))
CRAWL_DELAY_SECONDS = float(os.getenv("CRAWL_DELAY_SECONDS", "1.2"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "4"))
VISION_MAX_IMAGES = int(os.getenv("VISION_MAX_IMAGES", "40"))
VISION_MAX_PER_PAGE = int(os.getenv("VISION_MAX_PER_PAGE", "2"))
VISION_MAX_BYTES = int(os.getenv("VISION_MAX_BYTES", "4500000"))
VISION_MIN_SIDE = int(os.getenv("VISION_MIN_SIDE", "80"))
VISION_MIN_PIXELS = int(os.getenv("VISION_MIN_PIXELS", "8000"))
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.72"))
QUERY_TOP_K = int(os.getenv("QUERY_TOP_K", "5"))
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))

# USD per million tokens — editable for eval cost.
HAIKU_INPUT_PER_M = float(os.getenv("HAIKU_INPUT_PER_M", "0.10"))
HAIKU_OUTPUT_PER_M = float(os.getenv("HAIKU_OUTPUT_PER_M", "0.50"))
SONNET_INPUT_PER_M = float(os.getenv("SONNET_INPUT_PER_M", "2.00"))
SONNET_OUTPUT_PER_M = float(os.getenv("SONNET_OUTPUT_PER_M", "10.00"))


def token_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    name = (model or "").lower()
    if "sonnet" in name:
        inp, out = SONNET_INPUT_PER_M, SONNET_OUTPUT_PER_M
    else:
        inp, out = HAIKU_INPUT_PER_M, HAIKU_OUTPUT_PER_M
    return (input_tokens or 0) / 1_000_000 * inp + (output_tokens or 0) / 1_000_000 * out


def anthropic_api_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "").strip()


def app_api_key() -> str:
    return os.getenv("APP_API_KEY", "").strip()


def redact(text: str) -> str:
    key = anthropic_api_key()
    if key and key in text:
        return text.replace(key, "[redacted]")
    return text
