from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    canonical_url TEXT,
    title TEXT,
    sitemap_lastmod TEXT,
    ingested_lastmod TEXT,
    content_hash TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    http_status INTEGER,
    error TEXT,
    image_count INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    fetch_attempts INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT,
    parsed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    page_id INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    chunk_type TEXT NOT NULL,
    heading TEXT,
    text TEXT NOT NULL,
    image_url TEXT,
    image_alt TEXT,
    vision_unsure INTEGER NOT NULL DEFAULT 0,
    vision_status TEXT,
    content_hash TEXT NOT NULL,
    embedded_hash TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(page_id) REFERENCES pages(id),
    UNIQUE(page_id, content_hash)
);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    limit_n INTEGER,
    added INTEGER DEFAULT 0,
    updated INTEGER DEFAULT 0,
    removed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    vision_described INTEGER DEFAULT 0,
    indexed INTEGER DEFAULT 0,
    deleted_from_index INTEGER DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY,
    purpose TEXT NOT NULL,
    model TEXT NOT NULL,
    latency_ms INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS escalations (
    id INTEGER PRIMARY KEY,
    question TEXT NOT NULL,
    reason TEXT,
    sources_json TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution_note TEXT
);

CREATE TABLE IF NOT EXISTS knowledge_records (
    id INTEGER PRIMARY KEY,
    escalation_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    sources_json TEXT,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(escalation_id, version),
    FOREIGN KEY(escalation_id) REFERENCES escalations(id)
);

CREATE TABLE IF NOT EXISTS eval_cases (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    question TEXT NOT NULL,
    expected_type TEXT,
    expected_answer TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(status);
CREATE INDEX IF NOT EXISTS idx_pages_active ON pages(active);
CREATE INDEX IF NOT EXISTS idx_chunks_page ON chunks(page_id, active);
CREATE INDEX IF NOT EXISTS idx_escalations_status ON escalations(status);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in _column_names(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def migrate(conn: sqlite3.Connection) -> None:
    _ensure_column(conn, "chunks", "embedded_hash", "TEXT")
    _ensure_column(conn, "chunks", "vision_status", "TEXT")
    _ensure_column(conn, "ingest_runs", "indexed", "INTEGER DEFAULT 0")
    _ensure_column(conn, "ingest_runs", "deleted_from_index", "INTEGER DEFAULT 0")


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=60, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    migrate(conn)
    return conn


@contextmanager
def get_conn():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def db_path() -> Path:
    return DB_PATH


def log_llm_call(
    conn: sqlite3.Connection,
    purpose: str,
    model: str,
    latency_ms: int,
    input_tokens: int | None,
    output_tokens: int | None,
    error: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO llm_calls
            (purpose, model, latency_ms, input_tokens, output_tokens, error, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (purpose, model, latency_ms, input_tokens, output_tokens, error, utcnow()),
    )
