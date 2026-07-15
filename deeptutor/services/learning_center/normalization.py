"""Small deterministic normalization helpers for Learning Center data."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).replace("\u00a0", " ").strip()


def canonical_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_id(prefix: str, *parts: Any) -> str:
    payload = "\x1f".join(clean_text(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def normalize_stem(stem: str) -> str:
    return re.sub(r"\s+", "", clean_text(stem))


def question_fingerprint(stem: str, options: dict[str, str], source_answer: str, external_id: str = "") -> str:
    if clean_text(external_id):
        return f"external:{clean_text(external_id)}"
    payload = "\x1f".join((normalize_stem(stem), canonical_json(options), clean_text(source_answer).upper()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
