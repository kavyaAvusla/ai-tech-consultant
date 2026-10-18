from __future__ import annotations

import json
from pathlib import Path

from app.agents.estimation import estimate
from app.agents.feasibility import assess
from app.agents.proposal import write_proposal
from app.agents.scope import write_scope
from app.agents.transcript_analyst import analyze
from app.chunking import split_transcript
from app.config import MODEL_NAME, PROMPT_VERSION, TRANSCRIPTS_DIR, redact, require_secrets
from app.db import (
    finish_run,
    init_db,
    load_run_bundle,
    start_run,
    store_agent_output,
    store_feasibility,
    store_named,
    store_requirements,
    store_sections,
    store_singleton,
    store_transcript,
)
from app.report import print_bundle
from app.schemas import Transcript


def load_transcripts() -> list[Transcript]:
    paths = sorted(TRANSCRIPTS_DIR.glob("meeting_*.json"))
    if len(paths) < 3:
        raise RuntimeError("expected meeting_a, meeting_b, and meeting_c in transcripts/")
    return [Transcript.model_validate(json.loads(path.read_text(encoding="utf-8"))) for path in paths]


def assert_corpus(transcripts: list[Transcript]) -> None:
    by_id = {item.meeting_id: item for item in transcripts}
    meeting_a = next(item for item in transcripts if item.meeting_id == "mtg-a-search-mobile")
    meeting_c = next(item for item in transcripts if item.meeting_id == "mtg-c-search-followup")
    meeting_b = next(item for item in transcripts if item.meeting_id == "mtg-b-checkout")
    if meeting_c.project_id != meeting_a.project_id:
        raise RuntimeError("Meeting C must share project_id with Meeting A")
    if meeting_b.project_id == meeting_a.project_id:
        raise RuntimeError("Meeting B is a different project")
    if meeting_c.follows_meeting_id != meeting_a.meeting_id:
        raise RuntimeError("Meeting C must follow Meeting A")
    if len(by_id) != 3:
        raise RuntimeError("meeting ids must be unique")


def resolve_transcript(name: str, transcripts: list[Transcript]) -> Transcript:
    key = name.strip()
    path = Path(key)
    if path.is_file():
        return Transcript.model_validate(json.loads(path.read_text(encoding="utf-8")))
    aliases = {
        "meeting_a": "mtg-a-search-mobile",
        "a": "mtg-a-search-mobile",
        "meeting_b": "mtg-b-checkout",
        "b": "mtg-b-checkout",
        "meeting_c": "mtg-c-search-followup",
        "c": "mtg-c-search-followup",
    }
    meeting_id = aliases.get(key, key)
    for transcript in transcripts:
        if transcript.meeting_id == meeting_id:
            return transcript
    known = ", ".join(sorted(aliases))
    raise RuntimeError(f"Unknown meeting {name!r}. Use one of: {known}")


def run_meeting(name: str) -> dict:
    require_secrets()
    init_db()
    transcripts = load_transcripts()
    assert_corpus(transcripts)
    for transcript in transcripts:
        store_transcript(json.loads((TRANSCRIPTS_DIR / _file_for(transcript.meeting_id)).read_text(encoding="utf-8")))
    transcript = resolve_transcript(name, transcripts)
    sections = split_transcript(transcript)
    run_id = start_run(transcript.meeting_id, transcript.project_id, PROMPT_VERSION, MODEL_NAME)
    print(
        f"Run {run_id}: {transcript.meeting_id} ({len(transcript.turns)} turns, {len(sections)} overlapping sections)",
        flush=True,
    )
    try:
        store_sections(run_id, transcript.meeting_id, [section.model_dump() for section in sections])
        print("Transcript analyst", flush=True)
        analyst, analyst_steps = analyze(transcript, sections)
        _store_steps(run_id, transcript, analyst_steps)
        print("Product feasibility", flush=True)
        feasibility, requirements, feasibility_steps = assess(analyst.requirements)
        _store_steps(run_id, transcript, feasibility_steps)
        print("Scope", flush=True)
        scope, scope_steps = write_scope(requirements, analyst.open_questions, feasibility.items)
        _store_steps(run_id, transcript, scope_steps)
        print("Estimation", flush=True)
        estimate_output, requirements, estimate_steps = estimate(requirements, feasibility.items)
        _store_steps(run_id, transcript, estimate_steps)
        print("Proposal", flush=True)
        proposal, proposal_steps = write_proposal(
            requirements, analyst.open_questions, scope, estimate_output, feasibility.items
        )
        _store_steps(run_id, transcript, proposal_steps)
        store_requirements(run_id, transcript.project_id, [item.model_dump() for item in requirements])
        store_named("decisions", run_id, transcript.project_id, [item.model_dump() for item in analyst.decisions])
        store_named(
            "open_questions",
            run_id,
            transcript.project_id,
            [item.model_dump() for item in analyst.open_questions],
        )
        store_feasibility(run_id, [item.model_dump() for item in feasibility.items])
        store_singleton("scopes", run_id, scope.model_dump())
        store_singleton("estimates", run_id, estimate_output.model_dump())
        store_singleton("proposals", run_id, proposal.model_dump())
        finish_run(run_id, "ok")
    except Exception as exc:
        finish_run(run_id, "failed")
        raise RuntimeError(redact(str(exc))) from exc
    bundle = load_run_bundle(transcript.meeting_id)
    if bundle is None:
        raise RuntimeError("run completed but nothing was stored")
    print_bundle(bundle)
    return bundle


def _store_steps(run_id: int, transcript: Transcript, steps: list) -> None:
    for step in steps:
        store_agent_output(
            run_id,
            transcript.meeting_id,
            transcript.project_id,
            step.agent,
            step.step,
            step.prompt_version,
            step.model_input,
            step.model_output,
            step.validation,
        )


def _file_for(meeting_id: str) -> str:
    return {
        "mtg-a-search-mobile": "meeting_a.json",
        "mtg-b-checkout": "meeting_b.json",
        "mtg-c-search-followup": "meeting_c.json",
    }[meeting_id]
