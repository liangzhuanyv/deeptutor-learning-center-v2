"""Versioned prompts and JSON Schema for exam-question enrichment."""

from __future__ import annotations

import json
from typing import Any

from .models import PROMPT_VERSION, EnrichmentPayload, ExamQuestion

SYSTEM_PROMPT = """You are a careful exam-question editor. Return only data that conforms to the supplied JSON Schema.
Do not claim certainty when the question lacks enough information. Never invent source citations.
For multiple-choice questions, use the option label(s) as the suggested answer whenever possible."""


def response_format() -> dict[str, Any]:
    """Return an OpenAI-compatible strict JSON Schema response format."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "exam_question_enrichment",
            "strict": True,
            "schema": EnrichmentPayload.model_json_schema(),
        },
    }


def build_prompt(question: ExamQuestion) -> str:
    """Build a bounded, single-question prompt with explicit null requirements."""
    options = question.options or {}
    encoded_options = json.dumps(options, ensure_ascii=False, separators=(",", ":"))
    if len(encoded_options) > 12_000:
        encoded_options = encoded_options[:12_000] + "…"
    stem = question.stem.strip()
    if len(stem) > 12_000:
        stem = stem[:12_000] + "…"

    answer_instruction = (
        "Infer a candidate answer and a calibrated confidence from 0 to 1. "
        "This is an AI suggestion and will require human review."
        if question.needs_answer
        else "Do not propose an answer: set suggested_answer and answer_confidence to null."
    )
    explanation_instruction = (
        "Write a clear, concise explanation for a learner."
        if question.needs_explanation
        else "Do not write an explanation: set explanation to null."
    )
    known_answer = question.answer.strip()
    if not known_answer and question.has_ai_answer_suggestion:
        suggested = question.enrichment.get("answer", {}).get("suggested_answer")
        known_answer = f"AI suggestion pending review: {suggested}" if suggested else "(missing)"
    if not known_answer:
        known_answer = "(missing)"

    return f"""Prompt version: {PROMPT_VERSION}
Task: enrich exactly one exam question.

Question:
{stem}

Options (JSON):
{encoded_options}

Existing answer: {known_answer}

Answer requirement: {answer_instruction}
Explanation requirement: {explanation_instruction}

Return all three schema fields. If an answer is not requested, its two fields must be null. If an explanation is not requested, explanation must be null."""
