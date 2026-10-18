from __future__ import annotations

import json
import re

from app.agents.estimation import estimate
from app.agents.scope import write_scope
from app.agents.transcript_analyst import analyze
from app.chunking import split_transcript
from app.config import MODEL_NAME, PROMPT_VERSION, redact
from app.db import (
    finish_run,
    get_baseline,
    init_db,
    insert_version,
    next_version_number,
    start_run,
    store_agent_output,
    store_named,
    store_requirements,
    store_sections,
    store_singleton,
    store_transcript,
    utc_now,
)
from app.pipeline import assert_corpus, load_transcripts, resolve_transcript
from app.schemas import FeasibilityItem, OpenQuestion, Requirement

_DATE = re.compile(
    r"\b(january|february|march|april|june|july|august|september|october|november|december)\b|\bmay\s+\d{1,2}\b",
    re.IGNORECASE,
)


def compare_to_baseline(
    baseline: list[dict],
    followup: list[Requirement],
    decisions: list,
    questions: list[OpenQuestion],
) -> dict:
    """Match on topic_key and keep the approved requirement ids."""
    by_topic = {row["topic_key"]: row for row in baseline}
    used: set[str] = set()
    added: list[dict] = []
    removed: list[dict] = []
    modified: list[dict] = []
    unresolved: list[dict] = []
    unchanged: list[dict] = []
    next_num = _next_requirement_number(baseline)

    for item in followup:
        current = by_topic.get(item.topic_key)
        if current is None:
            if item.polarity != "include":
                continue
            stable_id = f"REQ-{next_num:03d}"
            next_num += 1
            added.append(
                {
                    "id": stable_id,
                    "topic_key": item.topic_key,
                    "description": item.description,
                    "source_quote": item.source_quote,
                    "source_timestamp": item.source_timestamp,
                    "speaker": item.speaker,
                    "status": item.status,
                    "priority": item.priority,
                    "explicitness": item.explicitness,
                    "extra_quotation": True,
                    "reason": "New work is outside the approved baseline and needs its own quotation.",
                }
            )
            continue
        used.add(item.topic_key)
        if item.polarity == "exclude":
            removed.append(
                {
                    "id": current["id"],
                    "topic_key": item.topic_key,
                    "description": current["description"],
                    "source_quote": item.source_quote,
                    "reason": "The follow-up removes this from the approved baseline.",
                }
            )
            continue
        if item.status == "disputed" or current["status"] == "disputed":
            unresolved.append(
                {
                    "id": current["id"],
                    "topic_key": item.topic_key,
                    "description": current["description"],
                    "source_quote": item.source_quote,
                    "reason": "Still unresolved against the approved baseline.",
                }
            )
            continue
        if current["status"] != item.status or current["priority"] != item.priority:
            modified.append(
                {
                    "id": current["id"],
                    "topic_key": item.topic_key,
                    "before": {"status": current["status"], "priority": current["priority"], "description": current["description"]},
                    "after": {"status": item.status, "priority": item.priority, "description": item.description},
                }
            )
        else:
            unchanged.append({"id": current["id"], "topic_key": item.topic_key, "description": current["description"]})

    for row in baseline:
        if row["topic_key"] in used or row["polarity"] == "exclude":
            continue
        if row["status"] == "disputed":
            unresolved.append(
                {
                    "id": row["id"],
                    "topic_key": row["topic_key"],
                    "description": row["description"],
                    "source_quote": row["source_quote"],
                    "reason": "The follow-up did not resolve this approved open conflict.",
                }
            )

    assumptions = []
    for decision in decisions:
        if _DATE.search(decision.description) or _DATE.search(decision.source_quote):
            assumptions.append(
                "The client changed the event they have in mind. That is their expectation, not a delivery commitment."
            )
            break
    open_questions = [question.question for question in questions if question.reason in {"contradiction", "unclear"}]
    for row in unresolved:
        open_questions.append(f"{row['id']} remains unresolved: {row['description']}")

    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "unresolved": unresolved,
        "unchanged": unchanged,
        "assumptions": assumptions,
        "open_questions": open_questions,
        "extra_quotation": [row for row in added if row["extra_quotation"]],
    }


def apply_changes(baseline: list[dict], report: dict) -> list[dict]:
    removed_ids = {row["id"] for row in report["removed"]}
    modified = {row["id"]: row for row in report["modified"]}
    revised: list[dict] = []
    for row in baseline:
        if row["id"] in removed_ids:
            continue
        if row["id"] in modified:
            updated = dict(row)
            updated["status"] = modified[row["id"]]["after"]["status"]
            updated["priority"] = modified[row["id"]]["after"]["priority"]
            updated["description"] = modified[row["id"]]["after"]["description"]
            revised.append(updated)
        else:
            revised.append(dict(row))
    for row in report["added"]:
        revised.append(
            {
                "id": row["id"],
                "description": row["description"],
                "source_quote": row["source_quote"],
                "source_timestamp": row["source_timestamp"],
                "speaker": row["speaker"],
                "status": row["status"],
                "priority": row["priority"],
                "explicitness": row["explicitness"],
                "existing_solution": "Not established. A missing knowledge result is not proof of absence.",
                "acceptance_criteria": [],
                "dependencies": [],
                "estimate_status": "not_estimated",
                "topic_key": row["topic_key"],
                "polarity": "include",
                "meeting_id": "mtg-c-search-followup",
                "meeting_date": "2026-10-18",
                "extra_quotation": True,
            }
        )
    return revised


def run_followup(name: str) -> dict:
    init_db()
    transcripts = load_transcripts()
    assert_corpus(transcripts)
    transcript = resolve_transcript(name, transcripts)
    baseline = get_baseline(transcript.project_id)
    if baseline is None:
        raise RuntimeError("Approve Meeting A before comparing a follow-up. There is no approved baseline.")
    for item in transcripts:
        if item.meeting_id == transcript.meeting_id:
            store_transcript(json.loads(_raw(item.meeting_id)))
    sections = split_transcript(transcript)
    run_id = start_run(transcript.meeting_id, transcript.project_id, PROMPT_VERSION, MODEL_NAME)
    print(f"Follow-up {run_id}: {transcript.meeting_id} against approved baseline v{baseline['version_number']}", flush=True)
    try:
        store_sections(run_id, transcript.meeting_id, [section.model_dump() for section in sections])
        analyst, steps = analyze(transcript, sections)
        for step in steps:
            store_agent_output(
                run_id, transcript.meeting_id, transcript.project_id,
                step.agent, step.step, step.prompt_version,
                step.model_input, step.model_output, step.validation,
            )
        report = compare_to_baseline(baseline["requirements"], analyst.requirements, analyst.decisions, analyst.open_questions)
        revised_rows = apply_changes(baseline["requirements"], report)
        affected_ids = {row["id"] for row in report["added"] + report["modified"]}
        affected = [Requirement.model_validate(row) for row in revised_rows if row["id"] in affected_ids]
        stubs = [_stub(row["id"]) for row in revised_rows]
        if affected:
            print(f"Re-estimating {len(affected)} affected requirement(s)", flush=True)
            partial, updated_affected, estimate_steps = estimate(affected, [_stub(item.id) for item in affected])
            for step in estimate_steps:
                store_agent_output(
                    run_id, transcript.meeting_id, transcript.project_id,
                    step.agent, step.step, step.prompt_version,
                    step.model_input, step.model_output, step.validation,
                )
            by_id = {item.id: item.model_dump() for item in updated_affected}
        else:
            partial = None
            by_id = {}
        for index, row in enumerate(revised_rows):
            if row["id"] in by_id:
                revised_rows[index] = by_id[row["id"]]
        revised_estimate = _merge_estimate(baseline["estimate"], partial, report)
        questions = [
            OpenQuestion(id=f"OQ-C{i}", question=text, reason="unclear", requirement_ids=[])
            for i, text in enumerate(report["open_questions"], start=1)
        ]
        print("Revised scope", flush=True)
        scope, scope_steps = write_scope(
            [Requirement.model_validate(row) for row in revised_rows],
            questions,
            stubs,
        )
        for step in scope_steps:
            store_agent_output(
                run_id, transcript.meeting_id, transcript.project_id,
                step.agent, step.step, step.prompt_version,
                step.model_input, step.model_output, step.validation,
            )
        proposal = _draft_proposal(scope, revised_estimate, report)
        store_requirements(run_id, transcript.project_id, revised_rows)
        store_named("decisions", run_id, transcript.project_id, [item.model_dump() for item in analyst.decisions])
        store_named("open_questions", run_id, transcript.project_id, [item.model_dump() for item in questions])
        store_singleton("scopes", run_id, scope.model_dump())
        store_singleton("estimates", run_id, revised_estimate)
        store_singleton("proposals", run_id, proposal)
        version_number = next_version_number(transcript.project_id)
        version_id = insert_version(
            {
                "project_id": transcript.project_id,
                "meeting_id": transcript.meeting_id,
                "run_id": run_id,
                "version_number": version_number,
                "status": "draft",
                "reviewer_name": None,
                "reviewed_at": None,
                "created_at": utc_now(),
                "scope": scope.model_dump(),
                "proposal": proposal,
                "requirements": revised_rows,
                "estimate": revised_estimate,
                "change_report": report,
                "is_baseline": False,
            }
        )
        finish_run(run_id, "ok")
    except Exception as exc:
        finish_run(run_id, "failed")
        raise RuntimeError(redact(str(exc))) from exc
    print_change_report(report, version_number, version_id)
    return {"version_id": version_id, "version_number": version_number, "report": report, "status": "draft"}


def print_change_report(report: dict, version_number: int, version_id: int) -> None:
    print(f"\nCHANGE REPORT (draft version {version_number}, id {version_id})")
    print("Sending is blocked until a reviewer approves this version.")
    for label in ("added", "removed", "modified", "unresolved"):
        print(f"\n{label.upper()}")
        rows = report[label]
        if not rows:
            print("(none)")
        for row in rows:
            extra = " extra quotation" if row.get("extra_quotation") else ""
            print(f"- {row.get('id')} {row.get('topic_key')}{extra}: {row.get('description') or row.get('reason')}")
    print("\nASSUMPTIONS")
    for line in report["assumptions"] or ["(none)"]:
        print(f"- {line}")
    print("\nOPEN QUESTIONS")
    for line in report["open_questions"] or ["(none)"]:
        print(f"- {line}")


def _next_requirement_number(rows: list[dict]) -> int:
    numbers = []
    for row in rows:
        match = re.search(r"(\d+)$", row["id"])
        if match:
            numbers.append(int(match.group(1)))
    return (max(numbers) if numbers else 0) + 1


def _stub(requirement_id: str) -> FeasibilityItem:
    return FeasibilityItem(
        requirement_id=requirement_id,
        classification="needs_clarification",
        kb_evidence="unavailable",
        kb_answer="",
        sources=[],
        verification_status="unverified",
        feature_absence_claimed=False,
        rationale="Not re-checked against the knowledge service in this follow-up.",
        existing_solution="Not established. A missing knowledge result is not proof of absence.",
    )


def _merge_estimate(baseline: dict, partial, report: dict) -> dict:
    removed = {row["id"] for row in report["removed"]}
    replaced = {}
    if partial is not None:
        replaced = {task.requirement_id: task.model_dump() for task in partial.tasks}
    tasks = []
    for task in baseline["tasks"]:
        if task["requirement_id"] in removed:
            continue
        if task["requirement_id"] in replaced:
            tasks.append(replaced.pop(task["requirement_id"]))
            continue
        tasks.append(task)
    tasks.extend(replaced.values())
    total = sum(task["likely_hours"] or 0 for task in tasks if not task.get("blocked"))
    return {"tasks": tasks, "hourly_rate": baseline.get("hourly_rate"), "likely_hours_total": round(total, 2)}


def _draft_proposal(scope, estimate: dict, report: dict) -> dict:
    extra = ", ".join(row["id"] for row in report["extra_quotation"]) or "none"
    sections = []
    for section in scope.sections:
        body = section.body
        if section.key == "assumptions":
            body = (body + "\n" + "\n".join(report["assumptions"])).strip()
        if section.key == "open_questions":
            body = (body + "\n" + "\n".join(report["open_questions"])).strip()
        sections.append({"key": section.key, "heading": section.heading, "body": body})
    sections.append(
        {
            "key": "effort_note",
            "heading": "Effort note",
            "body": (
                f"Likely hours total after the follow-up: {estimate['likely_hours_total']:g}. "
                f"Items needing extra quotation: {extra}. "
                "No price is quoted because the hourly rate is not set. "
                "This draft is not a commitment and cannot be sent until a reviewer approves it."
            ),
        }
    )
    return {"sections": sections}


def _raw(meeting_id: str) -> str:
    from app.config import TRANSCRIPTS_DIR

    name = {
        "mtg-a-search-mobile": "meeting_a.json",
        "mtg-b-checkout": "meeting_b.json",
        "mtg-c-search-followup": "meeting_c.json",
    }[meeting_id]
    return (TRANSCRIPTS_DIR / name).read_text(encoding="utf-8")
