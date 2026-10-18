from __future__ import annotations

import json
import re

from pydantic import ValidationError

from app.agents.common import StepRecord, run_prompt
from app.llm import LLMError
from app.schemas import (
    PROPOSAL_SECTIONS,
    EstimateOutput,
    FeasibilityItem,
    OpenQuestion,
    ProposalDocument,
    ProposalSection,
    Requirement,
    ScopeDocument,
    ValidationReport,
)
from app.validate import check_proposal

AGENT = "proposal"
_MONEY = re.compile(r"(\$\s*\d|\bUSD\b|\bEUR\b|\bdollars?\b)", re.IGNORECASE)
_DATE = re.compile(
    r"\b(20\d{2})\b|"
    r"\b(january|february|march|april|june|july|august|september|october|november|december)\b|"
    r"\bmay\s+\d{1,2}\b",
    re.IGNORECASE,
)
_PROMISE = re.compile(r"\bwe will integrate\b|\bincludes the integration\b|\bwe promise\b", re.IGNORECASE)


def write_proposal(
    requirements: list[Requirement],
    questions: list[OpenQuestion],
    scope: ScopeDocument,
    estimate: EstimateOutput,
    feasibility: list[FeasibilityItem],
) -> tuple[ProposalDocument, list[StepRecord]]:
    payload = {
        "hourly_rate": estimate.hourly_rate,
        "likely_hours_total": estimate.likely_hours_total,
        "requirements": [item.model_dump() for item in requirements],
        "open_questions": [item.model_dump() for item in questions],
        "scope": scope.model_dump(),
        "estimate": estimate.model_dump(),
        "feasibility": [item.model_dump() for item in feasibility],
    }
    user = json.dumps(payload, ensure_ascii=True)
    errors: list[str] = []
    repairs: list[str] = []
    version = "v1"
    document = _empty()
    for _attempt in range(2):
        prompt_user = user if not errors else user + "\n\nFIX THESE ERRORS:\n- " + "\n- ".join(errors[:12])
        try:
            version, parsed, _result = run_prompt("proposal", prompt_user, max_tokens=4000)
            document = ProposalDocument.model_validate(parsed)
        except (LLMError, ValidationError, TypeError) as exc:
            errors = [str(exc)[:400]]
            continue
        document, step_repairs = _sanitize(document, requirements, questions, estimate, feasibility)
        repairs.extend(step_repairs)
        errors = check_proposal(
            document,
            requirements,
            feasibility,
            estimate.likely_hours_total,
            estimate.hourly_rate,
        )
        if not errors:
            break
    document, cover_repairs = _cover(document, requirements, questions, estimate, feasibility)
    repairs.extend(cover_repairs)
    errors = check_proposal(
        document,
        requirements,
        feasibility,
        estimate.likely_hours_total,
        estimate.hourly_rate,
    )
    step = StepRecord(
        agent=AGENT,
        step="proposal",
        prompt_version=version,
        model_input=payload,
        model_output=document.model_dump(),
        validation=ValidationReport(ok=not errors, errors=errors, repairs=repairs).model_dump(),
    )
    if errors:
        raise LLMError("proposal validation failed: " + "; ".join(errors[:8]))
    return document, [step]


def _empty() -> ProposalDocument:
    return ProposalDocument(
        sections=[ProposalSection(key=key, heading=heading, body="") for key, heading in PROPOSAL_SECTIONS]
    )


def _align(document: ProposalDocument) -> ProposalDocument:
    by_key = {section.key: section.body.strip() for section in document.sections}
    return ProposalDocument(
        sections=[ProposalSection(key=key, heading=heading, body=by_key.get(key, "")) for key, heading in PROPOSAL_SECTIONS]
    )


def _sanitize(
    document: ProposalDocument,
    requirements: list[Requirement],
    questions: list[OpenQuestion],
    estimate: EstimateOutput,
    feasibility: list[FeasibilityItem],
) -> tuple[ProposalDocument, list[str]]:
    repairs: list[str] = []
    sections: list[ProposalSection] = []
    for section in _align(document).sections:
        body = section.body
        if _DATE.search(body) or _MONEY.search(body) or _PROMISE.search(body):
            kept = []
            for line in body.splitlines():
                if _DATE.search(line) or _MONEY.search(line) or _PROMISE.search(line):
                    repairs.append(f"removed an unsafe sentence from {section.heading}")
                    continue
                kept.append(line)
            body = "\n".join(kept).strip()
        sections.append(ProposalSection(key=section.key, heading=section.heading, body=body))
    document, cover_repairs = _cover(
        ProposalDocument(sections=sections), requirements, questions, estimate, feasibility
    )
    return document, repairs + cover_repairs


def _cover(
    document: ProposalDocument,
    requirements: list[Requirement],
    questions: list[OpenQuestion],
    estimate: EstimateOutput,
    feasibility: list[FeasibilityItem],
) -> tuple[ProposalDocument, list[str]]:
    repairs: list[str] = []
    bodies = {section.key: section.body for section in _align(document).sections}
    scope_lines = [bodies.get("scope_of_work", "").strip()]
    for requirement in requirements:
        if requirement.polarity == "include" and requirement.status != "disputed":
            if requirement.id not in bodies.get("scope_of_work", ""):
                scope_lines.append(f"{requirement.id}: {requirement.description}")
                repairs.append(f"added {requirement.id} to the proposal scope")
    bodies["scope_of_work"] = "\n".join(line for line in scope_lines if line).strip()
    effort = bodies.get("effort", "").strip()
    total = estimate.likely_hours_total
    if f"{total:g}" not in effort and f"{total:.1f}" not in effort:
        effort = (effort + f"\nLikely hours total: {total:g}.").strip()
        repairs.append("added the likely hour total")
    if estimate.hourly_rate is None and "No price is quoted because the hourly rate is not set." not in effort:
        effort = (effort + "\nNo price is quoted because the hourly rate is not set.").strip()
        repairs.append("added the empty-rate sentence")
    bodies["effort"] = effort
    unverified = [item.requirement_id for item in feasibility if item.verification_status == "unverified"]
    dependency = bodies.get("dependencies", "").strip()
    for requirement_id in unverified:
        if requirement_id not in dependency:
            dependency = (dependency + f"\n{requirement_id} is unverified and is not a commitment.").strip()
            repairs.append(f"labeled {requirement_id} unverified")
    if unverified and "not a commitment" not in dependency.lower():
        dependency = (dependency + "\nUnverified items are not a commitment.").strip()
    bodies["dependencies"] = dependency
    questions_body = bodies.get("open_questions", "").strip()
    for question in questions:
        if question.id not in questions_body:
            questions_body = (questions_body + f"\n{question.id}: {question.question}").strip()
    bodies["open_questions"] = questions_body
    sections = [ProposalSection(key=key, heading=heading, body=bodies.get(key, "")) for key, heading in PROPOSAL_SECTIONS]
    return ProposalDocument(sections=sections), repairs
