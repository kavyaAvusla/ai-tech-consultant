from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from app.config import DATA_DIR, DB_PATH


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
              id INTEGER PRIMARY KEY,
              meeting_id TEXT NOT NULL,
              project_id TEXT NOT NULL,
              prompt_version TEXT NOT NULL,
              model_name TEXT NOT NULL,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS transcripts (
              meeting_id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              meeting_date TEXT NOT NULL,
              consent_note TEXT NOT NULL,
              title TEXT NOT NULL,
              raw_json TEXT NOT NULL,
              stored_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS transcript_sections (
              run_id INTEGER NOT NULL,
              meeting_id TEXT NOT NULL,
              section_index INTEGER NOT NULL,
              start_timestamp TEXT NOT NULL,
              end_timestamp TEXT NOT NULL,
              turn_start INTEGER NOT NULL,
              turn_end INTEGER NOT NULL,
              text TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agent_outputs (
              id INTEGER PRIMARY KEY,
              run_id INTEGER NOT NULL,
              meeting_id TEXT NOT NULL,
              project_id TEXT NOT NULL,
              agent TEXT NOT NULL,
              step TEXT NOT NULL,
              prompt_version TEXT NOT NULL,
              input_json TEXT NOT NULL,
              output_json TEXT NOT NULL,
              validation_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS requirements (
              run_id INTEGER NOT NULL,
              project_id TEXT NOT NULL,
              requirement_id TEXT NOT NULL,
              payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS decisions (
              run_id INTEGER NOT NULL,
              project_id TEXT NOT NULL,
              payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS open_questions (
              run_id INTEGER NOT NULL,
              project_id TEXT NOT NULL,
              payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feasibility (
              run_id INTEGER NOT NULL,
              requirement_id TEXT NOT NULL,
              payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scopes (
              run_id INTEGER PRIMARY KEY,
              payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS estimates (
              run_id INTEGER PRIMARY KEY,
              payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS proposals (
              run_id INTEGER PRIMARY KEY,
              payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS kb_cache (
              question TEXT PRIMARY KEY,
              payload_json TEXT NOT NULL,
              stored_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS document_versions (
              id INTEGER PRIMARY KEY,
              project_id TEXT NOT NULL,
              meeting_id TEXT NOT NULL,
              run_id INTEGER,
              version_number INTEGER NOT NULL,
              status TEXT NOT NULL,
              reviewer_name TEXT,
              reviewed_at TEXT,
              created_at TEXT NOT NULL,
              scope_json TEXT NOT NULL,
              proposal_json TEXT NOT NULL,
              requirements_json TEXT NOT NULL,
              estimate_json TEXT NOT NULL,
              change_report_json TEXT,
              is_baseline INTEGER NOT NULL DEFAULT 0
            );
            """
        )


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def start_run(meeting_id: str, project_id: str, prompt_version: str, model_name: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO runs (meeting_id, project_id, prompt_version, model_name, started_at, status)
            VALUES (?, ?, ?, ?, ?, 'running')
            """,
            (meeting_id, project_id, prompt_version, model_name, utc_now()),
        )
        return int(cur.lastrowid)


def finish_run(run_id: int, status: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE runs SET finished_at = ?, status = ? WHERE id = ?",
            (utc_now(), status, run_id),
        )


def store_transcript(transcript_json: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO transcripts (
              meeting_id, project_id, meeting_date, consent_note, title, raw_json, stored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(meeting_id) DO UPDATE SET
              project_id = excluded.project_id,
              meeting_date = excluded.meeting_date,
              consent_note = excluded.consent_note,
              title = excluded.title,
              raw_json = excluded.raw_json,
              stored_at = excluded.stored_at
            """,
            (
                transcript_json["meeting_id"],
                transcript_json["project_id"],
                transcript_json["meeting_date"],
                transcript_json["consent_note"],
                transcript_json["title"],
                json.dumps(transcript_json, ensure_ascii=True),
                utc_now(),
            ),
        )


def store_sections(run_id: int, meeting_id: str, sections: list[dict[str, Any]]) -> None:
    with connect() as conn:
        conn.executemany(
            """
            INSERT INTO transcript_sections (
              run_id, meeting_id, section_index, start_timestamp, end_timestamp,
              turn_start, turn_end, text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    meeting_id,
                    section["section_index"],
                    section["start_timestamp"],
                    section["end_timestamp"],
                    section["turn_start"],
                    section["turn_end"],
                    section["text"],
                )
                for section in sections
            ],
        )


def store_agent_output(
    run_id: int,
    meeting_id: str,
    project_id: str,
    agent: str,
    step: str,
    prompt_version: str,
    payload_input: Any,
    payload_output: Any,
    validation: Any,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_outputs (
              run_id, meeting_id, project_id, agent, step, prompt_version,
              input_json, output_json, validation_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                meeting_id,
                project_id,
                agent,
                step,
                prompt_version,
                json.dumps(payload_input, ensure_ascii=True),
                json.dumps(payload_output, ensure_ascii=True),
                json.dumps(validation, ensure_ascii=True),
                utc_now(),
            ),
        )


def store_requirements(run_id: int, project_id: str, rows: list[dict[str, Any]]) -> None:
    with connect() as conn:
        conn.executemany(
            "INSERT INTO requirements (run_id, project_id, requirement_id, payload_json) VALUES (?, ?, ?, ?)",
            [(run_id, project_id, row["id"], json.dumps(row, ensure_ascii=True)) for row in rows],
        )


def store_named(table: str, run_id: int, project_id: str, rows: list[dict[str, Any]]) -> None:
    with connect() as conn:
        conn.executemany(
            f"INSERT INTO {table} (run_id, project_id, payload_json) VALUES (?, ?, ?)",
            [(run_id, project_id, json.dumps(row, ensure_ascii=True)) for row in rows],
        )


def store_singleton(table: str, run_id: int, payload: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            f"INSERT INTO {table} (run_id, payload_json) VALUES (?, ?)",
            (run_id, json.dumps(payload, ensure_ascii=True)),
        )


def store_feasibility(run_id: int, rows: list[dict[str, Any]]) -> None:
    with connect() as conn:
        conn.executemany(
            "INSERT INTO feasibility (run_id, requirement_id, payload_json) VALUES (?, ?, ?)",
            [(run_id, row["requirement_id"], json.dumps(row, ensure_ascii=True)) for row in rows],
        )


def cached_kb(question: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT payload_json FROM kb_cache WHERE question = ?", (question,)).fetchone()
    if row is None:
        return None
    return json.loads(row["payload_json"])


def cache_kb(question: str, payload: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO kb_cache (question, payload_json, stored_at) VALUES (?, ?, ?)
            ON CONFLICT(question) DO UPDATE SET payload_json = excluded.payload_json, stored_at = excluded.stored_at
            """,
            (question, json.dumps(payload, ensure_ascii=True), utc_now()),
        )


def load_run_bundle(meeting_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        run = conn.execute(
            """
            SELECT * FROM runs
            WHERE meeting_id = ? AND status = 'ok'
            ORDER BY id DESC LIMIT 1
            """,
            (meeting_id,),
        ).fetchone()
        if run is None:
            return None
        run_id = run["id"]

        def payloads(sql: str, args: tuple[Any, ...]) -> list[dict[str, Any]]:
            return [json.loads(row["payload_json"]) for row in conn.execute(sql, args)]

        scope = conn.execute("SELECT payload_json FROM scopes WHERE run_id = ?", (run_id,)).fetchone()
        estimate = conn.execute("SELECT payload_json FROM estimates WHERE run_id = ?", (run_id,)).fetchone()
        proposal = conn.execute("SELECT payload_json FROM proposals WHERE run_id = ?", (run_id,)).fetchone()
        return {
            "run": dict(run),
            "requirements": payloads(
                "SELECT payload_json FROM requirements WHERE run_id = ? ORDER BY requirement_id",
                (run_id,),
            ),
            "feasibility": payloads(
                "SELECT payload_json FROM feasibility WHERE run_id = ? ORDER BY requirement_id",
                (run_id,),
            ),
            "open_questions": payloads(
                "SELECT payload_json FROM open_questions WHERE run_id = ?",
                (run_id,),
            ),
            "scope": json.loads(scope["payload_json"]) if scope else None,
            "estimate": json.loads(estimate["payload_json"]) if estimate else None,
            "proposal": json.loads(proposal["payload_json"]) if proposal else None,
        }


def next_version_number(project_id: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) AS n FROM document_versions WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    return int(row["n"]) + 1


def insert_version(row: dict[str, Any]) -> int:
    with connect() as conn:
        if row.get("is_baseline"):
            conn.execute(
                "UPDATE document_versions SET is_baseline = 0 WHERE project_id = ?",
                (row["project_id"],),
            )
        cur = conn.execute(
            """
            INSERT INTO document_versions (
              project_id, meeting_id, run_id, version_number, status, reviewer_name,
              reviewed_at, created_at, scope_json, proposal_json, requirements_json,
              estimate_json, change_report_json, is_baseline
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["project_id"],
                row["meeting_id"],
                row.get("run_id"),
                row["version_number"],
                row["status"],
                row.get("reviewer_name"),
                row.get("reviewed_at"),
                row["created_at"],
                json.dumps(row["scope"], ensure_ascii=True),
                json.dumps(row["proposal"], ensure_ascii=True),
                json.dumps(row["requirements"], ensure_ascii=True),
                json.dumps(row["estimate"], ensure_ascii=True),
                json.dumps(row.get("change_report"), ensure_ascii=True) if row.get("change_report") else None,
                1 if row.get("is_baseline") else 0,
            ),
        )
        return int(cur.lastrowid)


def list_versions(project_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, project_id, meeting_id, run_id, version_number, status,
                   reviewer_name, reviewed_at, created_at, is_baseline, change_report_json
            FROM document_versions
            WHERE project_id = ?
            ORDER BY version_number
            """,
            (project_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        raw = item.pop("change_report_json")
        item["change_report"] = json.loads(raw) if raw else None
        result.append(item)
    return result


def get_version(version_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM document_versions WHERE id = ?", (version_id,)).fetchone()
    if row is None:
        return None
    return _unpack_version(row)


def get_baseline(project_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM document_versions
            WHERE project_id = ? AND is_baseline = 1 AND status = 'approved'
            ORDER BY version_number DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()
    if row is None:
        return None
    return _unpack_version(row)


def latest_version(project_id: str, meeting_id: str | None = None) -> dict[str, Any] | None:
    with connect() as conn:
        if meeting_id:
            row = conn.execute(
                """
                SELECT * FROM document_versions
                WHERE project_id = ? AND meeting_id = ?
                ORDER BY version_number DESC LIMIT 1
                """,
                (project_id, meeting_id),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM document_versions
                WHERE project_id = ?
                ORDER BY version_number DESC LIMIT 1
                """,
                (project_id,),
            ).fetchone()
    if row is None:
        return None
    return _unpack_version(row)


def set_version_status(version_id: int, status: str, reviewer_name: str | None, reviewed_at: str | None) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE document_versions
            SET status = ?, reviewer_name = COALESCE(?, reviewer_name),
                reviewed_at = COALESCE(?, reviewed_at)
            WHERE id = ?
            """,
            (status, reviewer_name, reviewed_at, version_id),
        )


def _unpack_version(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["scope"] = json.loads(item.pop("scope_json"))
    item["proposal"] = json.loads(item.pop("proposal_json"))
    item["requirements"] = json.loads(item.pop("requirements_json"))
    item["estimate"] = json.loads(item.pop("estimate_json"))
    raw = item.pop("change_report_json")
    item["change_report"] = json.loads(raw) if raw else None
    return item
