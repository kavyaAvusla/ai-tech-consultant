from __future__ import annotations

import json

from pydantic import BaseModel, Field, ValidationError

from app.agents.common import StepRecord, run_prompt
from app.config import hourly_rate
from app.llm import LLMError
from app.schemas import EstimateOutput, EstimateTask, FeasibilityItem, Requirement, ValidationReport
from app.validate import _DATE, _MONEY, check_estimate

AGENT = "estimation"


class _RawTask(BaseModel):
    requirement_id: str
    title: str = ""
    low_hours: float | None = None
    likely_hours: float | None = None
    high_hours: float | None = None
    reasoning: str = ""
    assumptions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    blocked: bool = False


class _RawEstimate(BaseModel):
    tasks: list[_RawTask] = Field(default_factory=list)


def estimate(
    requirements: list[Requirement], feasibility: list[FeasibilityItem]
) -> tuple[EstimateOutput, list[Requirement], list[StepRecord]]:
    rate = hourly_rate()
    payload = {
        "hourly_rate": rate,
        "requirements": [item.model_dump() for item in requirements],
        "feasibility": [
            {
                "requirement_id": item.requirement_id,
                "classification": item.classification,
                "verification_status": item.verification_status,
            }
            for item in feasibility
        ],
    }
    user = json.dumps(payload, ensure_ascii=True)
    errors: list[str] = []
    version = "v1"
    raw = _RawEstimate()
    for _attempt in range(2):
        prompt_user = user if not errors else user + "\n\nFIX THESE ERRORS:\n- " + "\n- ".join(errors[:12])
        try:
            version, parsed, _result = run_prompt("estimation", prompt_user, max_tokens=3500)
            raw = _RawEstimate.model_validate(parsed)
        except (LLMError, ValidationError, TypeError) as exc:
            errors = [str(exc)[:400]]
            continue
        output = _build(requirements, raw, rate)
        errors = check_estimate(output, requirements, rate)
        if not errors:
            updated = _apply(requirements, output)
            step = _step(version, payload, output, errors)
            return output, updated, [step]
    raise LLMError("estimate validation failed: " + "; ".join(errors[:8]))


def _build(requirements: list[Requirement], raw: _RawEstimate, rate: float | None) -> EstimateOutput:
    by_id = {task.requirement_id: task for task in raw.tasks}
    tasks: list[EstimateTask] = []
    total = 0.0
    for index, requirement in enumerate(requirements, start=1):
        source = by_id.get(requirement.id)
        blocked = requirement.status == "disputed" or requirement.polarity == "exclude"
        title = _safe_text((source.title if source and source.title else requirement.topic_key).strip())
        if title == "No date or price is part of this estimate.":
            title = requirement.topic_key
        reasoning = _safe_text(
            (source.reasoning if source else "") or "Range follows the requirement status and the feasibility class."
        )
        assumptions = [_safe_text(item) for item in (source.assumptions if source else []) if item.strip()]
        dependencies = [_safe_text(item) for item in (source.dependencies if source else []) if item.strip()]
        if not dependencies:
            dependencies = [_safe_text(item) for item in requirement.dependencies]
        if blocked:
            tasks.append(
                EstimateTask(
                    id=f"EST-{index:03d}",
                    requirement_id=requirement.id,
                    title=title,
                    low_hours=None,
                    likely_hours=None,
                    high_hours=None,
                    reasoning=(
                        "No hours. This item is disputed."
                        if requirement.status == "disputed"
                        else "No hours. This item is out of scope."
                    ),
                    assumptions=assumptions,
                    dependencies=dependencies or requirement.dependencies,
                    blocked=True,
                )
            )
            continue
        low = _hours(source.low_hours if source else None)
        likely = _hours(source.likely_hours if source else None)
        high = _hours(source.high_hours if source else None)
        tasks.append(
            EstimateTask(
                id=f"EST-{index:03d}",
                requirement_id=requirement.id,
                title=title,
                low_hours=low,
                likely_hours=likely,
                high_hours=high,
                reasoning=reasoning,
                assumptions=assumptions,
                dependencies=dependencies or requirement.dependencies,
                blocked=False,
            )
        )
        if likely is not None:
            total += likely
    return EstimateOutput(tasks=tasks, hourly_rate=rate, likely_hours_total=round(total, 2))


def _safe_text(value: str) -> str:
    if _DATE.search(value) or _MONEY.search(value):
        return "No date or price is part of this estimate."
    return value.strip()


def _hours(value: float | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _apply(requirements: list[Requirement], output: EstimateOutput) -> list[Requirement]:
    by_id = {task.requirement_id: task for task in output.tasks}
    updated: list[Requirement] = []
    for requirement in requirements:
        task = by_id[requirement.id]
        if task.blocked:
            status = "blocked" if requirement.status == "disputed" else "not_estimated"
        else:
            status = "estimated"
        updated.append(requirement.model_copy(update={"estimate_status": status}))
    return updated


def _step(version: str, payload: dict, output: EstimateOutput, errors: list[str]) -> StepRecord:
    return StepRecord(
        agent=AGENT,
        step="estimate",
        prompt_version=version,
        model_input=payload,
        model_output=output.model_dump(),
        validation=ValidationReport(ok=not errors, errors=errors, repairs=[]).model_dump(),
    )
