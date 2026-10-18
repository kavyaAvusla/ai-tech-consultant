from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

RequirementStatus = Literal["confirmed", "unclear", "disputed"]
Priority = Literal["low", "medium", "high"]
Explicitness = Literal["explicit", "inferred"]
Polarity = Literal["include", "exclude"]
EstimateStatus = Literal["not_estimated", "estimated", "blocked"]
FeasibilityClass = Literal[
    "existing_configuration",
    "existing_feature_with_limitation",
    "potential_custom_development",
    "needs_clarification",
]
EvidenceLevel = Literal["strong", "weak", "unavailable"]
Verification = Literal["verified", "unverified"]

SCOPE_SECTIONS: list[tuple[str, str]] = [
    ("context", "Context"),
    ("goals", "Goals"),
    ("in_scope", "In scope"),
    ("out_of_scope", "Out of scope"),
    ("assumptions", "Assumptions"),
    ("dependencies", "Dependencies"),
    ("risks", "Risks"),
    ("open_questions", "Open questions"),
    ("approach", "Approach"),
    ("acceptance_criteria", "Acceptance criteria"),
]

PROPOSAL_SECTIONS: list[tuple[str, str]] = [
    ("summary", "Summary"),
    ("what_we_heard", "What we heard"),
    ("scope_of_work", "Scope of work"),
    ("out_of_scope", "Out of scope"),
    ("approach", "Approach"),
    ("effort", "Effort estimate"),
    ("assumptions", "Assumptions"),
    ("dependencies", "Dependencies and unverified items"),
    ("open_questions", "Open questions"),
    ("next_review", "Review before any commitment"),
]

FEASIBILITY_LABELS = {
    "existing_configuration": "existing configuration",
    "existing_feature_with_limitation": "existing feature with limitation",
    "potential_custom_development": "potential custom development",
    "needs_clarification": "needs clarification",
}


class Speaker(BaseModel):
    id: str
    name: str
    role: str
    title: str = ""


class Turn(BaseModel):
    timestamp: str
    speaker_id: str
    text: str

    @field_validator("timestamp")
    @classmethod
    def clock(cls, value: str) -> str:
        parts = value.split(":")
        if len(parts) != 3 or any(len(part) != 2 or not part.isdigit() for part in parts):
            raise ValueError("timestamp must be HH:MM:SS")
        return value


class Transcript(BaseModel):
    project_id: str
    meeting_id: str
    meeting_date: str
    consent_note: str
    title: str
    client: str
    platform: str
    speakers: list[Speaker]
    turns: list[Turn] = Field(min_length=1)
    follows_meeting_id: str | None = None

    @field_validator("meeting_date")
    @classmethod
    def iso_date(cls, value: str) -> str:
        year, month, day = value.split("-")
        if len(year) != 4 or len(month) != 2 or len(day) != 2:
            raise ValueError("meeting_date must be YYYY-MM-DD")
        return value

    @field_validator("consent_note")
    @classmethod
    def roleplay(cls, value: str) -> str:
        lowered = value.lower()
        if "role-played" not in lowered and "role played" not in lowered:
            raise ValueError("consent note must say the transcript is role-played")
        if "no real clients" not in lowered:
            raise ValueError("consent note must say there are no real clients")
        return value

    def speaker_name(self, speaker_id: str) -> str:
        for speaker in self.speakers:
            if speaker.id == speaker_id:
                return speaker.name
        raise KeyError(speaker_id)


class Section(BaseModel):
    section_index: int
    turn_start: int
    turn_end: int
    start_timestamp: str
    end_timestamp: str
    text: str


class ExtractedRequirement(BaseModel):
    temp_id: str
    meeting_id: str
    meeting_date: str
    section_index: int
    topic_key: str
    description: str
    polarity: Polarity
    source_quote: str
    source_timestamp: str
    speaker: str
    status: RequirementStatus
    priority: Priority
    explicitness: Explicitness
    acceptance_criteria: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    supersedes: bool = False


class Decision(BaseModel):
    id: str
    meeting_id: str
    description: str
    source_quote: str
    source_timestamp: str
    speaker: str
    status: RequirementStatus


class OpenQuestion(BaseModel):
    id: str
    question: str
    requirement_ids: list[str] = Field(default_factory=list)
    reason: Literal["contradiction", "unclear", "missing_information"]
    source_quotes: list[str] = Field(default_factory=list)


class Requirement(BaseModel):
    id: str
    description: str
    source_quote: str
    source_timestamp: str
    speaker: str
    status: RequirementStatus
    priority: Priority
    explicitness: Explicitness
    existing_solution: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    estimate_status: EstimateStatus = "not_estimated"
    topic_key: str
    polarity: Polarity
    meeting_id: str
    meeting_date: str


class AnalystOutput(BaseModel):
    requirements: list[Requirement]
    decisions: list[Decision]
    open_questions: list[OpenQuestion]


class KbQueryRecord(BaseModel):
    requirement_id: str
    question: str
    evidence: EvidenceLevel
    answer: str
    sources: list[str]
    failure: str | None = None


class FeasibilityItem(BaseModel):
    requirement_id: str
    classification: FeasibilityClass
    kb_evidence: EvidenceLevel
    kb_answer: str
    sources: list[str] = Field(default_factory=list)
    limitation: str = ""
    verification_status: Verification
    feature_absence_claimed: bool = False
    rationale: str
    existing_solution: str


class FeasibilityOutput(BaseModel):
    items: list[FeasibilityItem]


class ScopeSection(BaseModel):
    key: str
    heading: str
    body: str


class ScopeDocument(BaseModel):
    sections: list[ScopeSection]


class EstimateTask(BaseModel):
    id: str
    requirement_id: str
    title: str
    low_hours: float | None = None
    likely_hours: float | None = None
    high_hours: float | None = None
    reasoning: str
    assumptions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    blocked: bool = False


class EstimateOutput(BaseModel):
    tasks: list[EstimateTask]
    hourly_rate: float | None = None
    likely_hours_total: float = 0


class ProposalSection(BaseModel):
    key: str
    heading: str
    body: str


class ProposalDocument(BaseModel):
    sections: list[ProposalSection]


class ValidationReport(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    repairs: list[str] = Field(default_factory=list)
