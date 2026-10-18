from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agents.common import StepRecord, run_prompt
from app.kb import query_knowledge
from app.llm import LLMError
from app.schemas import (
    FeasibilityItem,
    FeasibilityOutput,
    KbQueryRecord,
    Requirement,
    ValidationReport,
)
from app.validate import claims_absence, check_feasibility

AGENT = "product_feasibility"


class _RawItem(BaseModel):
    requirement_id: str = ""
    classification: str = ""
    limitation: str = ""
    rationale: str = ""

    @classmethod
    def model_validate(cls, obj, **kwargs):  # type: ignore[override]
        if isinstance(obj, dict):
            obj = dict(obj)
            if not obj.get("requirement_id"):
                obj["requirement_id"] = str(obj.get("id") or obj.get("requirement") or "")
            label = str(obj.get("classification") or obj.get("class") or obj.get("label") or "")
            obj["classification"] = label.strip().lower().replace(" ", "_").replace("-", "_")
        return super().model_validate(obj, **kwargs)


class _RawOutput(BaseModel):
    items: list[_RawItem] = Field(default_factory=list)


_EXISTING = {
    "existing_configuration": "Knowledge articles describe an existing configuration.",
    "existing_feature_with_limitation": "Knowledge articles describe an existing feature with a limitation.",
    "potential_custom_development": "Possible custom development. This is not proof the product lacks a related feature.",
    "needs_clarification": "Not established. A missing or weak knowledge result is not proof of absence.",
}


def assess(requirements: list[Requirement]) -> tuple[FeasibilityOutput, list[Requirement], list[StepRecord]]:
    """Input: requirements. Calls Task 1 over HTTP. Output: one classification per requirement."""
    kb_rows: list[KbQueryRecord] = []
    for requirement in requirements:
        question = feasibility_question(requirement)
        print(f"  knowledge query {requirement.id}", flush=True)
        kb_rows.append(query_knowledge(requirement.id, question))
    payload = {
        "requirements": [
            {
                "id": requirement.id,
                "description": requirement.description,
                "status": requirement.status,
                "polarity": requirement.polarity,
            }
            for requirement in requirements
        ],
        "knowledge": [
            {
                "requirement_id": row.requirement_id,
                "evidence": row.evidence,
                "sources": row.sources[:3],
                "answer": (row.answer or "")[:700],
                "failure": row.failure,
            }
            for row in kb_rows
        ],
    }
    user = json_user(payload)
    version = "v1"
    parsed: Any = {"items": []}
    errors: list[str] = []
    for attempt in range(2):
        prompt_user = user if not errors else user + "\n\nFIX THESE ERRORS:\n- " + "\n- ".join(errors)
        try:
            version, parsed, _result = run_prompt("product_feasibility", prompt_user, max_tokens=2500)
            if isinstance(parsed, list):
                parsed = {"items": parsed}
            raw = _RawOutput.model_validate(parsed)
            raw = _align_ids(requirements, raw)
        except (LLMError, ValidationError, TypeError) as exc:
            errors = [str(exc)[:400]]
            raw = _RawOutput()
            if attempt == 1:
                break
            continue
        output = _coerce(requirements, kb_rows, raw)
        errors = check_feasibility(output, [requirement.id for requirement in requirements])
        if not errors:
            updated = _apply(requirements, output)
            step = StepRecord(
                agent=AGENT,
                step="classify",
                prompt_version=version,
                model_input=payload,
                model_output=output.model_dump(),
                validation=ValidationReport(ok=True, errors=[], repairs=[]).model_dump(),
            )
            return output, updated, [step]
    output = _coerce(requirements, kb_rows, _RawOutput())
    updated = _apply(requirements, output)
    step = StepRecord(
        agent=AGENT,
        step="classify",
        prompt_version=version,
        model_input=payload,
        model_output=output.model_dump(),
        validation=ValidationReport(
            ok=True,
            errors=errors,
            repairs=["classification fell back to the knowledge evidence rule"],
        ).model_dump(),
    )
    return output, updated, [step]


def _align_ids(requirements: list[Requirement], raw: _RawOutput) -> _RawOutput:
    ids = {requirement.id for requirement in requirements}
    matched = [item for item in raw.items if item.requirement_id in ids]
    if len(matched) == len(requirements):
        return _RawOutput(items=matched)
    if len(raw.items) == len(requirements):
        zipped = []
        for requirement, item in zip(requirements, raw.items):
            zipped.append(item.model_copy(update={"requirement_id": requirement.id}))
        return _RawOutput(items=zipped)
    return _RawOutput(items=matched)


def feasibility_question(requirement: Requirement) -> str:
    return (
        "On a Brilliant Directories membership directory website, what existing admin settings "
        f"or product features relate to this request: {requirement.description} "
        "If the articles mention a limitation, say what it is. "
        "If the articles do not cover the request, say the evidence is missing. "
        "Missing articles are not proof that the feature does not exist."
    )


def _coerce(
    requirements: list[Requirement], kb_rows: list[KbQueryRecord], raw: _RawOutput
) -> FeasibilityOutput:
    by_id = {item.requirement_id: item for item in raw.items}
    items: list[FeasibilityItem] = []
    for requirement, kb in zip(requirements, kb_rows):
        proposal = by_id.get(requirement.id)
        classification = proposal.classification if proposal else "needs_clarification"
        limitation = (proposal.limitation if proposal else "") or ""
        rationale = (proposal.rationale if proposal else "") or "The returned articles do not settle this requirement."
        if classification not in _EXISTING:
            classification = "needs_clarification"
        if kb.evidence != "strong" or not kb.sources:
            classification = "needs_clarification"
            verification = "unverified"
        elif classification in {"existing_configuration", "existing_feature_with_limitation"}:
            verification = "verified"
        else:
            if classification != "potential_custom_development":
                classification = "needs_clarification"
            verification = "unverified"
        if classification == "existing_feature_with_limitation" and not limitation.strip():
            limitation = "The knowledge answer describes a limit on the existing feature."
        if claims_absence(limitation):
            limitation = "The articles are not proof of absence."
        if claims_absence(rationale) or claims_absence(limitation):
            rationale = "The knowledge result is not proof of absence."
            if kb.evidence != "strong" or not kb.sources:
                classification = "needs_clarification"
                verification = "unverified"
        existing = _EXISTING[classification]
        if classification == "needs_clarification" and kb.evidence == "strong":
            existing = (
                "Knowledge articles were found, but they do not settle this request. "
                "That is not proof of absence."
            )
        if limitation.strip() and classification == "existing_feature_with_limitation":
            existing = f"{existing} {limitation.strip()}"
        items.append(
            FeasibilityItem(
                requirement_id=requirement.id,
                classification=classification,  # type: ignore[arg-type]
                kb_evidence=kb.evidence,
                kb_answer=kb.answer[:500],
                sources=kb.sources,
                limitation=limitation.strip(),
                verification_status=verification,  # type: ignore[arg-type]
                feature_absence_claimed=False,
                rationale=rationale.strip(),
                existing_solution=existing,
            )
        )
    return FeasibilityOutput(items=items)


def _apply(requirements: list[Requirement], output: FeasibilityOutput) -> list[Requirement]:
    by_id = {item.requirement_id: item for item in output.items}
    updated: list[Requirement] = []
    for requirement in requirements:
        item = by_id[requirement.id]
        updated.append(requirement.model_copy(update={"existing_solution": item.existing_solution}))
    return updated


def json_user(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=True)
