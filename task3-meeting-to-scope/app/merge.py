from __future__ import annotations

from collections import defaultdict

from app.schemas import (
    Decision,
    ExtractedRequirement,
    OpenQuestion,
    Requirement,
    RequirementStatus,
)

_PRIORITY = {"low": 0, "medium": 1, "high": 2}


def merge_extracts(items: list[ExtractedRequirement], decisions: list[Decision]) -> tuple[list[Requirement], list[Decision], list[OpenQuestion]]:
    grouped: dict[str, list[ExtractedRequirement]] = defaultdict(list)
    for item in items:
        grouped[item.topic_key.strip().lower()].append(item)

    requirements: list[Requirement] = []
    questions: list[OpenQuestion] = []
    ordered = sorted(grouped.items(), key=lambda pair: _earliest(pair[1]))
    for index, (topic_key, group) in enumerate(ordered, start=1):
        requirement, question = _merge_group(f"REQ-{index:03d}", topic_key, _dedupe(group))
        requirements.append(requirement)
        if question is not None:
            questions.append(question)

    unique_decisions: list[Decision] = []
    seen_quotes: set[str] = set()
    for decision in sorted(decisions, key=lambda item: item.source_timestamp):
        key = " ".join(decision.source_quote.lower().split())
        if key in seen_quotes:
            continue
        seen_quotes.add(key)
        unique_decisions.append(decision.model_copy(update={"id": f"DEC-{len(unique_decisions) + 1:03d}"}))

    for requirement in requirements:
        if requirement.status == "unclear":
            questions.append(
                OpenQuestion(
                    id="",
                    question=f"Is {requirement.topic_key.replace('_', ' ')} in scope? {requirement.description}",
                    requirement_ids=[requirement.id],
                    reason="unclear",
                    source_quotes=[requirement.source_quote],
                )
            )
    for index, question in enumerate(questions, start=1):
        question.id = f"OQ-{index:03d}"
    return requirements, unique_decisions, questions


def _dedupe(group: list[ExtractedRequirement]) -> list[ExtractedRequirement]:
    kept: list[ExtractedRequirement] = []
    seen: set[tuple[str, str]] = set()
    for item in group:
        key = (" ".join(item.source_quote.lower().split()), item.polarity)
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def _earliest(group: list[ExtractedRequirement]) -> str:
    return min(item.source_timestamp for item in group)


def _merge_group(
    requirement_id: str, topic_key: str, group: list[ExtractedRequirement]
) -> tuple[Requirement, OpenQuestion | None]:
    includes = [item for item in group if item.polarity == "include"]
    excludes = [item for item in group if item.polarity == "exclude"]
    question: OpenQuestion | None = None
    chosen = group
    status: RequirementStatus
    polarity = group[0].polarity

    if includes and excludes:
        superseding = _supersession(includes, excludes)
        include_firm = _firm(includes)
        exclude_firm = _firm(excludes)
        if superseding is not None:
            polarity = superseding.polarity
            status = "confirmed"
            chosen = [superseding]
        elif include_firm and exclude_firm:
            status = "disputed"
            polarity = "include"
            chosen = include_firm + exclude_firm
            question = OpenQuestion(
                id="",
                question=(
                    f"Speakers disagree about {topic_key.replace('_', ' ')}. "
                    "This stays an open question until the client resolves it."
                ),
                requirement_ids=[requirement_id],
                reason="contradiction",
                source_quotes=[item.source_quote for item in chosen],
            )
        elif exclude_firm:
            polarity = "exclude"
            status = "confirmed"
            chosen = exclude_firm
        elif include_firm:
            polarity = "include"
            status = _combined_status(include_firm)
            chosen = include_firm
        else:
            polarity = "include"
            status = "unclear"
            chosen = includes
    else:
        status = _combined_status(group)
        polarity = group[0].polarity

    primary = _primary(chosen)
    explicitness = primary.explicitness
    priority = primary.priority
    criteria: list[str] = []
    dependencies: list[str] = []
    for item in chosen:
        for criterion in item.acceptance_criteria:
            if criterion and criterion not in criteria:
                criteria.append(criterion)
        for dependency in item.dependencies:
            if dependency and dependency not in dependencies:
                dependencies.append(dependency)
    description = primary.description
    if status == "disputed":
        estimate_status = "blocked"
    else:
        estimate_status = "not_estimated"
    requirement = Requirement(
        id=requirement_id,
        description=description,
        source_quote=primary.source_quote,
        source_timestamp=primary.source_timestamp,
        speaker=primary.speaker,
        status=status,
        priority=priority,
        explicitness=explicitness,
        existing_solution="",
        acceptance_criteria=criteria,
        dependencies=dependencies,
        estimate_status=estimate_status,
        topic_key=topic_key,
        polarity=polarity,
        meeting_id=primary.meeting_id,
        meeting_date=primary.meeting_date,
    )
    return requirement, question


def _supersession(
    includes: list[ExtractedRequirement], excludes: list[ExtractedRequirement]
) -> ExtractedRequirement | None:
    """A later meeting can replace an earlier one. The same meeting cannot."""
    candidates = [item for item in includes + excludes if item.supersedes]
    if not candidates:
        return None
    latest = max(candidates, key=lambda item: (item.meeting_date, item.source_timestamp))
    others = [item for item in includes + excludes if item.meeting_id != latest.meeting_id]
    if not others:
        return None
    if any(item.meeting_date > latest.meeting_date for item in others):
        return None
    opposing = [item for item in others if item.polarity != latest.polarity]
    if not opposing:
        return None
    return latest


def _firm(group: list[ExtractedRequirement]) -> list[ExtractedRequirement]:
    return [item for item in group if item.status in {"confirmed", "disputed"}]


def _combined_status(group: list[ExtractedRequirement]) -> RequirementStatus:
    statuses = {item.status for item in group}
    if "disputed" in statuses:
        return "disputed"
    if "confirmed" in statuses and "unclear" not in statuses:
        return "confirmed"
    if "confirmed" in statuses and "unclear" in statuses:
        return "confirmed"
    return "unclear"


def _primary(group: list[ExtractedRequirement]) -> ExtractedRequirement:
    confirmed = [item for item in group if item.status == "confirmed" and item.explicitness == "explicit"]
    pool = confirmed or group
    return min(pool, key=lambda item: item.source_timestamp)
