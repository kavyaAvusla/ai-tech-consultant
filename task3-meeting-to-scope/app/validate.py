from __future__ import annotations

import re

from app.schemas import (
    PROPOSAL_SECTIONS,
    SCOPE_SECTIONS,
    EstimateOutput,
    ExtractedRequirement,
    FeasibilityItem,
    FeasibilityOutput,
    ProposalDocument,
    Requirement,
    ScopeDocument,
    Transcript,
)

_WS = re.compile(r"\s+")
_ABSENCE = re.compile(
    r"\b(does not exist|doesn't exist|do not exist|is not a feature|isn't a feature|"
    r"no such feature|feature is absent|not available in the product)\b",
    re.IGNORECASE,
)
_MONEY = re.compile(r"(\$\s*\d|\bUSD\b|\bEUR\b|\bdollars?\b|\bprice is\b|\bflat fee\b)", re.IGNORECASE)
_DATE = re.compile(
    r"\b(20\d{2})\b|"
    r"\b(january|february|march|april|june|july|august|september|october|november|december)\b|"
    r"\bmay\s+\d{1,2}\b",
    re.IGNORECASE,
)
_PROMISE = re.compile(r"\bwe will integrate\b|\bincludes the integration\b|\bwe promise\b", re.IGNORECASE)


def normalize(text: str) -> str:
    cleaned = (
        text.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2014", "-")
        .replace("\u2013", "-")
    )
    return _WS.sub(" ", cleaned).strip().lower()


def quote_in_text(quote: str, source: str) -> bool:
    if len(normalize(quote)) < 12:
        return False
    return normalize(quote) in normalize(source)


def locate_quote(transcript: Transcript, quote: str) -> tuple[str, str] | None:
    """Return speaker name and timestamp for the turn that contains the quote."""
    wanted = normalize(quote)
    if len(wanted) < 12:
        return None
    for turn in transcript.turns:
        if wanted in normalize(turn.text):
            return transcript.speaker_name(turn.speaker_id), turn.timestamp
    return None


def check_extracts(items: list[ExtractedRequirement], section_text: str, transcript: Transcript) -> list[str]:
    errors: list[str] = []
    known = {speaker.name for speaker in transcript.speakers}
    timestamps = {turn.timestamp for turn in transcript.turns}
    for item in items:
        if not quote_in_text(item.source_quote, section_text):
            errors.append(f"{item.temp_id} quote is not in the section")
        if item.speaker not in known:
            errors.append(f"{item.temp_id} speaker is not in the transcript")
        if item.source_timestamp not in timestamps:
            errors.append(f"{item.temp_id} timestamp is not in the transcript")
        if item.polarity == "exclude" and item.status == "disputed":
            continue
    return errors


def repair_extract_attribution(
    items: list[ExtractedRequirement], transcript: Transcript
) -> list[ExtractedRequirement]:
    repaired: list[ExtractedRequirement] = []
    for item in items:
        found = locate_quote(transcript, item.source_quote)
        if found is None:
            repaired.append(item)
            continue
        speaker, timestamp = found
        repaired.append(item.model_copy(update={"speaker": speaker, "source_timestamp": timestamp}))
    return repaired


def claims_absence(text: str) -> bool:
    for sentence in re.split(r"[.!?]", text):
        if re.search(r"not proof|does not prove|do not prove|cannot prove", sentence, re.IGNORECASE):
            continue
        if _ABSENCE.search(sentence):
            return True
    return False


def check_feasibility(output: FeasibilityOutput, requirement_ids: list[str]) -> list[str]:
    errors: list[str] = []
    seen = [item.requirement_id for item in output.items]
    if seen != requirement_ids and set(seen) != set(requirement_ids):
        errors.append("feasibility did not cover every requirement")
    for item in output.items:
        errors.extend(_one_feasibility(item))
    return errors


def _one_feasibility(item: FeasibilityItem) -> list[str]:
    errors: list[str] = []
    if item.feature_absence_claimed:
        errors.append(f"{item.requirement_id} claims a feature is absent")
    if item.kb_evidence != "strong" or not item.sources:
        if item.classification != "needs_clarification":
            errors.append(f"{item.requirement_id} used a weak result as if it were proof")
        if item.verification_status != "unverified":
            errors.append(f"{item.requirement_id} is verified without strong evidence")
    if item.classification == "existing_configuration" and item.kb_evidence != "strong":
        errors.append(f"{item.requirement_id} existing configuration needs strong evidence")
    if item.classification == "existing_feature_with_limitation" and not item.limitation:
        errors.append(f"{item.requirement_id} limitation is empty")
    if claims_absence(item.rationale) or claims_absence(item.existing_solution):
        errors.append(f"{item.requirement_id} wording treats a gap as absence")
    if item.classification == "potential_custom_development" and item.verification_status != "unverified":
        errors.append(f"{item.requirement_id} custom work must stay unverified")
    return errors


def check_scope(document: ScopeDocument, requirements: list[Requirement], open_question_ids: list[str]) -> list[str]:
    errors: list[str] = []
    keys = [section.key for section in document.sections]
    expected = [key for key, _heading in SCOPE_SECTIONS]
    if keys != expected:
        errors.append("scope sections are missing or out of order")
    joined = "\n".join(section.body for section in document.sections)
    approach = next((section.body for section in document.sections if section.key == "approach"), "")
    if _DATE.search(approach):
        errors.append("approach names a calendar date")
    if _MONEY.search(joined):
        errors.append("scope names a price")
    in_scope = next((section.body for section in document.sections if section.key == "in_scope"), "")
    out_scope = next((section.body for section in document.sections if section.key == "out_of_scope"), "")
    questions = next((section.body for section in document.sections if section.key == "open_questions"), "")
    for requirement in requirements:
        if requirement.polarity == "include" and requirement.status != "disputed":
            if requirement.id not in in_scope:
                errors.append(f"in scope omits {requirement.id}")
        if requirement.polarity == "exclude" or requirement.status == "disputed":
            target = out_scope if requirement.polarity == "exclude" else questions
            if requirement.id not in target and requirement.id not in questions:
                errors.append(f"scope omits disputed or excluded {requirement.id}")
    for question_id in open_question_ids:
        if question_id not in questions:
            errors.append(f"open questions omit {question_id}")
    return errors


def check_estimate(output: EstimateOutput, requirements: list[Requirement], rate: float | None) -> list[str]:
    errors: list[str] = []
    if output.hourly_rate != rate:
        errors.append("estimate hourly rate does not match configuration")
    by_id = {task.requirement_id: task for task in output.tasks}
    total = 0.0
    for requirement in requirements:
        task = by_id.get(requirement.id)
        if task is None:
            errors.append(f"estimate omits {requirement.id}")
            continue
        blob = " ".join([task.reasoning, task.title, *task.assumptions, *task.dependencies])
        if _MONEY.search(blob) or _DATE.search(blob):
            errors.append(f"{requirement.id} estimate invents a price or a date")
        if requirement.status == "disputed" or requirement.polarity == "exclude":
            if not task.blocked or task.low_hours is not None:
                errors.append(f"{requirement.id} should not have committed hours")
            continue
        if task.low_hours is None or task.likely_hours is None or task.high_hours is None:
            errors.append(f"{requirement.id} is missing an hour range")
            continue
        if not (task.low_hours <= task.likely_hours <= task.high_hours):
            errors.append(f"{requirement.id} hour range is out of order")
        if task.low_hours <= 0:
            errors.append(f"{requirement.id} hours must be positive")
        total += task.likely_hours
    if abs(output.likely_hours_total - total) > 0.01:
        errors.append("likely hour total does not match the tasks")
    return errors


def check_proposal(
    document: ProposalDocument,
    requirements: list[Requirement],
    feasibility: list[FeasibilityItem],
    likely_total: float,
    rate: float | None,
) -> list[str]:
    errors: list[str] = []
    keys = [section.key for section in document.sections]
    expected = [key for key, _heading in PROPOSAL_SECTIONS]
    if keys != expected:
        errors.append("proposal headings are missing or out of order")
    joined = "\n".join(section.body for section in document.sections)
    if _DATE.search(joined):
        errors.append("proposal names a calendar date")
    if _PROMISE.search(joined):
        errors.append("proposal promises an integration or an outcome")
    if rate is None and _MONEY.search(joined.replace("No price is quoted because the hourly rate is not set.", "")):
        errors.append("proposal names a price while the hourly rate is empty")
    if rate is None and "No price is quoted because the hourly rate is not set." not in joined:
        errors.append("proposal does not say that no price is quoted")
    effort = next((section.body for section in document.sections if section.key == "effort"), "")
    if f"{likely_total:g}" not in effort and f"{likely_total:.1f}" not in effort:
        errors.append("effort section does not repeat the likely hour total")
    unverified = {
        item.requirement_id
        for item in feasibility
        if item.verification_status == "unverified"
    }
    dependencies = next((section.body for section in document.sections if section.key == "dependencies"), "")
    for requirement_id in sorted(unverified):
        if requirement_id not in dependencies:
            errors.append(f"proposal does not keep {requirement_id} unverified")
    if unverified and "not a commitment" not in joined.lower():
        errors.append("unverified items are not labeled as not a commitment")
    in_scope_ids = [
        requirement.id
        for requirement in requirements
        if requirement.polarity == "include" and requirement.status != "disputed"
    ]
    scope_body = next((section.body for section in document.sections if section.key == "scope_of_work"), "")
    for requirement_id in in_scope_ids:
        if requirement_id not in scope_body:
            errors.append(f"proposal scope omits {requirement_id}")
    return errors
