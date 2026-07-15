"""Typed public values shared by the Learning Center service and API."""

from __future__ import annotations

from typing import Literal, TypedDict

ProjectKind = Literal["exam", "course", "book", "skill", "other"]
ReviewStatus = Literal["unreviewed", "accepted", "rejected", "superseded"]
ProvenanceType = Literal[
    "source_original", "official", "user_edited", "ai_generated", "ai_inferred", "ai_suggested"
]


class ProjectInput(TypedDict, total=False):
    id: str
    external_id: str
    name: str
    kind: ProjectKind
    aliases: list[str]
    metadata: dict[str, object]
