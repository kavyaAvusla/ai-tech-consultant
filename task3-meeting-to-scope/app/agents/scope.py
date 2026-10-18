from __future__ import annotations

import json

from pydantic import ValidationError

from app.agents.common import StepRecord, run_prompt
from app.llm import LLMError
from app.schemas import (
    SCOPE_SECTIONS,
    FeasibilityItem,
    OpenQuestion,
    Requirement,
    ScopeDocument,
    ScopeSection,
    ValidationReport,
)
from app.validate import _DATE, _MONEY, check_scope

AGENT = "scope"


def write_scope(
    requirements: list[Requirement],
    questions: list[OpenQuestion],
    feasibility: list[FeasibilityItem],
) -> tuple[ScopeDocument, list[StepRecord]]:
    payload = {
        "requirements": [item.model_dump() for item in requirements],
        "open_questions": [item.model_dump() for item in questions],
        "feasibility": [item.model_dump() for item in feasibility],
    }
    user = json.dumps(payload, ensure_ascii=True)
    errors: list[str] = []
    version = "v1"
    document = _empty_scope()
    for _attempt in range(2):
        prompt_user = user if not errors else user + "\n\nFIX THESE ERRORS:\n- " + "\n- ".join(errors[:12])
        try:
            version, parsed, _result = run_prompt("scope", prompt_user, max_tokens=4000)
            document = ScopeDocument.model_validate(parsed)
        except (LLMError, ValidationError, TypeError) as exc:
            errors = [str(exc)[:400]]
            continue
        document = _strip(_align_headings(document))
        errors = check_scope(document, requirements, [item.id for item in questions])
        if not errors:
            break
    document = _strip(_cover(document, requirements, questions))
    errors = check_scope(document, requirements, [item.id for item in questions])
    step = StepRecord(
        agent=AGENT,
        step="document",
        prompt_version=version,
        model_input=payload,
        model_output=document.model_dump(),
        validation=ValidationReport(ok=not errors, errors=errors, repairs=[]).model_dump(),
    )
    if errors:
        raise LLMError("scope validation failed: " + "; ".join(errors[:8]))
    return document, [step]


def _strip(document: ScopeDocument) -> ScopeDocument:
    sections: list[ScopeSection] = []
    for section in document.sections:
        kept = []
        for line in section.body.splitlines():
            if _MONEY.search(line):
                continue
            if section.key == "approach" and _DATE.search(line):
                continue
            kept.append(line)
        body = "\n".join(kept).strip()
        if section.key == "approach" and not body:
            body = (
                "Review existing settings, apply configuration, and only then discuss custom work. "
                "No delivery date is offered."
            )
        sections.append(ScopeSection(key=section.key, heading=section.heading, body=body))
    return ScopeDocument(sections=sections)


def _empty_scope() -> ScopeDocument:
    return ScopeDocument(
        sections=[ScopeSection(key=key, heading=heading, body="") for key, heading in SCOPE_SECTIONS]
    )


def _align_headings(document: ScopeDocument) -> ScopeDocument:
    by_key = {section.key: section for section in document.sections}
    sections = []
    for key, heading in SCOPE_SECTIONS:
        current = by_key.get(key)
        body = current.body.strip() if current else ""
        sections.append(ScopeSection(key=key, heading=heading, body=body))
    return ScopeDocument(sections=sections)


def _cover(document: ScopeDocument, requirements: list[Requirement], questions: list[OpenQuestion]) -> ScopeDocument:
    bodies = {section.key: section.body for section in document.sections}
    in_lines = []
    out_lines = []
    question_lines = [bodies.get("open_questions", "").strip()]
    for requirement in requirements:
        if requirement.polarity == "include" and requirement.status != "disputed":
            if requirement.id not in bodies.get("in_scope", ""):
                in_lines.append(f"{requirement.id}: {requirement.description}")
        if requirement.polarity == "exclude" and requirement.id not in bodies.get("out_of_scope", ""):
            out_lines.append(f"{requirement.id}: {requirement.description}")
        if requirement.status == "disputed" and requirement.id not in bodies.get("open_questions", ""):
            question_lines.append(f"{requirement.id} is disputed and is not committed scope.")
    for question in questions:
        if question.id not in bodies.get("open_questions", ""):
            question_lines.append(f"{question.id}: {question.question}")
    if in_lines:
        bodies["in_scope"] = (bodies.get("in_scope", "") + "\n" + "\n".join(in_lines)).strip()
    if out_lines:
        bodies["out_of_scope"] = (bodies.get("out_of_scope", "") + "\n" + "\n".join(out_lines)).strip()
    bodies["open_questions"] = "\n".join(line for line in question_lines if line).strip()
    sections = [ScopeSection(key=key, heading=heading, body=bodies.get(key, "")) for key, heading in SCOPE_SECTIONS]
    return ScopeDocument(sections=sections)
