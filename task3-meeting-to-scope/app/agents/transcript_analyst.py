from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agents.common import StepRecord, run_prompt
from app.llm import LLMError
from app.merge import merge_extracts
from app.schemas import AnalystOutput, Decision, ExtractedRequirement, Section, Transcript, ValidationReport
from app.validate import check_extracts, repair_extract_attribution

AGENT = "transcript_analyst"


class _RawRequirement(BaseModel):
    topic_key: str
    description: str
    polarity: str
    source_quote: str
    source_timestamp: str
    speaker: str
    status: str
    priority: str
    explicitness: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    supersedes: bool = False


class _RawDecision(BaseModel):
    description: str
    source_quote: str
    source_timestamp: str
    speaker: str
    status: str = "confirmed"


class _SectionExtract(BaseModel):
    requirements: list[_RawRequirement] = Field(default_factory=list)
    decisions: list[_RawDecision] = Field(default_factory=list)


def analyze(transcript: Transcript, sections: list[Section]) -> tuple[AnalystOutput, list[StepRecord]]:
    """Input: original transcript plus overlapping sections. Output: project-level records."""
    steps: list[StepRecord] = []
    extracted: list[ExtractedRequirement] = []
    decisions: list[Decision] = []
    for section in sections:
        section_items, section_decisions, step = _extract_section(transcript, section)
        steps.append(step)
        extracted.extend(section_items)
        decisions.extend(section_decisions)
    requirements, merged_decisions, questions = merge_extracts(extracted, decisions)
    output = AnalystOutput(requirements=requirements, decisions=merged_decisions, open_questions=questions)
    steps.append(
        StepRecord(
            agent=AGENT,
            step="merge",
            prompt_version=steps[-1].prompt_version if steps else "v1",
            model_input={"extracted_requirement_count": len(extracted), "decision_count": len(decisions)},
            model_output=output.model_dump(),
            validation={"ok": True, "errors": [], "repairs": ["merged in code from validated section quotes"]},
        )
    )
    return output, steps


def _extract_section(
    transcript: Transcript, section: Section
) -> tuple[list[ExtractedRequirement], list[Decision], StepRecord]:
    user = (
        f"MEETING {transcript.meeting_id} DATE {transcript.meeting_date}\n"
        f"SECTION {section.section_index} TURNS {section.turn_start}-{section.turn_end - 1}\n\n"
        f"{section.text}"
    )
    errors: list[str] = []
    repairs: list[str] = []
    version = "v1"
    parsed: Any = {"requirements": [], "decisions": []}
    kept_requirements: list[ExtractedRequirement] = []
    kept_decisions: list[Decision] = []
    for attempt in range(2):
        prompt_user = user if attempt == 0 else user + "\n\nFIX THESE ERRORS:\n- " + "\n- ".join(errors)
        try:
            version, parsed, _result = run_prompt("transcript_analyst", prompt_user, max_tokens=3500)
            raw = _SectionExtract.model_validate(parsed)
        except (LLMError, ValidationError, TypeError) as exc:
            errors = [str(exc)[:400]]
            continue
        candidates = []
        for index, item in enumerate(raw.requirements, start=1):
            try:
                candidates.append(
                    ExtractedRequirement(
                        temp_id=f"S{section.section_index}-R{index}",
                        meeting_id=transcript.meeting_id,
                        meeting_date=transcript.meeting_date,
                        section_index=section.section_index,
                        topic_key=item.topic_key.strip().lower().replace(" ", "_"),
                        description=item.description.strip(),
                        polarity=item.polarity,  # type: ignore[arg-type]
                        source_quote=item.source_quote.strip(),
                        source_timestamp=item.source_timestamp.strip(),
                        speaker=item.speaker.strip(),
                        status=item.status,  # type: ignore[arg-type]
                        priority=item.priority,  # type: ignore[arg-type]
                        explicitness=item.explicitness,  # type: ignore[arg-type]
                        acceptance_criteria=[value.strip() for value in item.acceptance_criteria if value.strip()],
                        dependencies=[value.strip() for value in item.dependencies if value.strip()],
                        supersedes=item.supersedes,
                    )
                )
            except ValidationError as exc:
                errors.append(str(exc)[:240])
        candidates = repair_extract_attribution(candidates, transcript)
        errors = check_extracts(candidates, section.text, transcript)
        valid_ids = {error.split(" ", 1)[0] for error in errors}
        kept_requirements = [item for item in candidates if item.temp_id not in valid_ids]
        if len(kept_requirements) != len(candidates):
            repairs.append(
                f"section {section.section_index} dropped {len(candidates) - len(kept_requirements)} quotes that were not in the source"
            )
        kept_decisions = []
        for index, item in enumerate(raw.decisions, start=1):
            if item.source_quote.strip() and _quote_ok(item.source_quote, section.text):
                found = repair_extract_attribution(
                    [
                        ExtractedRequirement(
                            temp_id=f"S{section.section_index}-D{index}",
                            meeting_id=transcript.meeting_id,
                            meeting_date=transcript.meeting_date,
                            section_index=section.section_index,
                            topic_key="decision",
                            description=item.description,
                            polarity="include",
                            source_quote=item.source_quote,
                            source_timestamp=item.source_timestamp,
                            speaker=item.speaker,
                            status="confirmed",
                            priority="medium",
                            explicitness="explicit",
                        )
                    ],
                    transcript,
                )[0]
                kept_decisions.append(
                    Decision(
                        id="",
                        meeting_id=transcript.meeting_id,
                        description=item.description.strip(),
                        source_quote=found.source_quote.strip(),
                        source_timestamp=found.source_timestamp,
                        speaker=found.speaker,
                        status="confirmed" if item.status == "confirmed" else "unclear",
                    )
                )
        if kept_requirements or attempt == 1:
            break
    report = ValidationReport(ok=not errors, errors=errors, repairs=repairs)
    step = StepRecord(
        agent=AGENT,
        step=f"section:{section.section_index}",
        prompt_version=version,
        model_input={"section_index": section.section_index, "text": section.text},
        model_output=parsed if isinstance(parsed, dict) else {"raw": parsed},
        validation=report.model_dump(),
    )
    return kept_requirements, kept_decisions, step


def _quote_ok(quote: str, source: str) -> bool:
    from app.validate import quote_in_text

    return quote_in_text(quote, source)


def dumps(output: AnalystOutput) -> str:
    return json.dumps(output.model_dump(), ensure_ascii=True)
