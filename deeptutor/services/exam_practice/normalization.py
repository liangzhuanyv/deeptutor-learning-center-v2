"""Normalization helpers shared by Exam Practice imports and answer judging.

The rules intentionally follow the tolerant JSON normalization used by
``scripts/import_exam_question_banks.py``.  This domain layer has no download
code: callers can feed downloaded data into :class:`ExamPracticeStore`.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def clean_text(value: Any) -> str:
    """Convert common import values to clean display text."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).replace("\u00a0", " ").strip()


def normalize_stem(value: str) -> str:
    """Return a whitespace-insensitive representation for de-duplication."""
    return re.sub(r"\s+", "", clean_text(value))


def normalize_options(value: Any) -> dict[str, str]:
    """Accept either mapping or list-form options and produce a text mapping."""
    if isinstance(value, dict):
        options: dict[str, str] = {}
        for key, text in value.items():
            normalized_key = clean_text(key).rstrip("、.")
            if normalized_key:
                options[normalized_key] = clean_text(text)
        return options
    if isinstance(value, list):
        return {chr(ord("A") + index): clean_text(text) for index, text in enumerate(value)}
    return {}


def normalize_answer(value: Any) -> str:
    """Canonicalize a selected answer without destroying free-text answers."""
    answer = clean_text(value).replace("答案：", "").replace("答案:", "").upper()
    answer = re.sub(r"\s+", "", answer)
    # Multiple-choice sources commonly use any of ``A,C`` / ``A、C`` / ``AC``.
    choice_letters = re.sub(r"[^A-Z]", "", answer)
    if choice_letters and re.fullmatch(r"[A-D]+", choice_letters):
        return "".join(sorted(set(choice_letters)))
    return answer


def inferred_question_type(raw_type: Any, source_answer: Any) -> str:
    raw = clean_text(raw_type).lower()
    answer = normalize_answer(source_answer)
    if "多" in raw or (re.fullmatch(r"[A-D]+", answer or "") and len(answer) > 1):
        return "多选"
    if "判断" in raw or raw in {"tf", "judge", "j", "true_false"}:
        return "判断"
    if "不定" in raw or raw in {"u", "uncertain"}:
        return "不定项"
    return clean_text(raw_type) or "单选"


def stable_id(prefix: str, *parts: Any) -> str:
    """Create stable, opaque IDs from importer-owned identifiers."""
    text = "\x1f".join(clean_text(part) for part in parts)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def question_fingerprint(
    stem: str, options: dict[str, str], source_answer: str, external_id: str = ""
) -> str:
    """Generate a stable deduplication key for a question inside one bank."""
    if external_id.strip():
        return f"external:{external_id.strip()}"
    canonical = json.dumps(options, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    source = "\x1f".join((normalize_stem(stem), canonical, normalize_answer(source_answer)))
    return hashlib.sha256(source.encode("utf-8")).hexdigest()
