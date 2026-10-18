from __future__ import annotations

from app.db import (
    get_version,
    init_db,
    insert_version,
    list_versions,
    load_run_bundle,
    next_version_number,
    set_version_status,
    utc_now,
)
from app.pipeline import load_transcripts, resolve_transcript


def approve_baseline(meeting_id: str, reviewer: str) -> dict:
    """Snapshot the latest successful run as the approved baseline."""
    init_db()
    meeting_id = resolve_transcript(meeting_id, load_transcripts()).meeting_id
    bundle = load_run_bundle(meeting_id)
    if bundle is None:
        raise RuntimeError(f"No successful run to approve for {meeting_id}")
    project_id = bundle["run"]["project_id"]
    version_number = next_version_number(project_id)
    now = utc_now()
    version_id = insert_version(
        {
            "project_id": project_id,
            "meeting_id": meeting_id,
            "run_id": bundle["run"]["id"],
            "version_number": version_number,
            "status": "approved",
            "reviewer_name": reviewer,
            "reviewed_at": now,
            "created_at": now,
            "scope": bundle["scope"],
            "proposal": bundle["proposal"],
            "requirements": bundle["requirements"],
            "estimate": bundle["estimate"],
            "change_report": None,
            "is_baseline": True,
        }
    )
    return {"id": version_id, "version_number": version_number, "status": "approved", "project_id": project_id}


def mark_sent(version_id: int) -> dict:
    """Simulated send. Refuses any version that is not already approved."""
    init_db()
    version = get_version(version_id)
    if version is None:
        raise RuntimeError(f"Version {version_id} was not found")
    if version["status"] != "approved":
        raise RuntimeError(
            f"Version {version['version_number']} is {version['status']}. "
            "An unapproved version cannot be marked sent."
        )
    set_version_status(version_id, "sent", version.get("reviewer_name"), utc_now())
    return {"id": version_id, "version_number": version["version_number"], "status": "sent"}


def history(project_id: str) -> list[dict]:
    init_db()
    return list_versions(project_id)
