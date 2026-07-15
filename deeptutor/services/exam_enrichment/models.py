"""Data models for AI-assisted exam-question enrichment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

PROMPT_VERSION = "exam-enrichment/v1"


class EnrichmentPayload(BaseModel):
    """The strictly validated structured response requested from the LLM."""

    model_config = ConfigDict(extra="forbid")

    suggested_answer: str | None = Field(
        ..., description="Candidate answer only when an answer was requested; otherwise null."
    )
    answer_confidence: float | None = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in suggested_answer on a 0 to 1 scale; otherwise null.",
    )
    explanation: str | None = Field(
        ...,
        description="Concise learner-facing explanation only when requested; otherwise null.",
    )


@dataclass(frozen=True)
class ExamQuestion:
    """A question read from the exam-practice SQLite table."""

    id: int | str
    stem: str
    options: dict[str, Any] | list[Any] | None
    answer: str
    explanation: str
    enrichment: dict[str, Any]

    @property
    def has_ai_answer_suggestion(self) -> bool:
        return self.enrichment.get("answer", {}).get("status") == "ai_suggested"

    @property
    def has_ai_explanation(self) -> bool:
        return self.enrichment.get("explanation", {}).get("status") == "ai_generated"

    @property
    def needs_answer(self) -> bool:
        return not self.answer.strip() and not self.has_ai_answer_suggestion

    @property
    def needs_explanation(self) -> bool:
        return not self.explanation.strip() and not self.has_ai_explanation


@dataclass(frozen=True)
class EnrichmentResult:
    """Validated result and provenance for one question."""

    question_id: int | str
    payload: EnrichmentPayload
    provider: str
    model: str
    generated_at: str
    prompt_version: str = PROMPT_VERSION


@dataclass
class EnrichmentSummary:
    """Counts returned by an enrichment run."""

    selected: int = 0
    skipped: int = 0
    dry_run: int = 0
    completed: int = 0
    suggested_answers: int = 0
    generated_explanations: int = 0
    failed: int = 0
