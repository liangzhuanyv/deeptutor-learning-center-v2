"""Versioned, strict canonical import protocol for Learning Center v2."""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

QuestionType = Literal['single_choice', 'multiple_choice', 'true_false', 'short_answer', 'other']
ProjectKind = Literal['exam', 'course', 'book', 'skill', 'other']


class _StrictImportModel(BaseModel):
    """Reject accidental contract drift; extension data belongs in metadata."""

    model_config = ConfigDict(extra='forbid')


class ImportProject(_StrictImportModel):
    external_id: str = Field(..., min_length=1, max_length=512)
    name: str = Field(..., min_length=1, max_length=500)
    kind: ProjectKind = 'other'
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def metadata_is_bounded_json(self) -> 'ImportProject':
        if len(json.dumps(self.metadata, ensure_ascii=False)) > 65_536:
            raise ValueError('Project metadata must not exceed 64 KiB')
        return self


class ImportBank(_StrictImportModel):
    external_id: str = Field(..., min_length=1, max_length=512)
    name: str = Field(..., min_length=1, max_length=500)
    version: str = Field(..., min_length=1, max_length=256)
    source: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def source_is_bounded_json(self) -> 'ImportBank':
        if len(json.dumps(self.source, ensure_ascii=False)) > 65_536:
            raise ValueError('Bank source metadata must not exceed 64 KiB')
        return self


class ImportItem(_StrictImportModel):
    external_id: str = Field(..., min_length=1, max_length=512)
    module_path: list[str] = Field(default_factory=list, max_length=20)
    knowledge_points: list[str] = Field(default_factory=list, max_length=50)
    question_type: QuestionType
    stem: str = Field(..., min_length=1, max_length=20_000)
    options: dict[str, str] = Field(default_factory=dict, max_length=20)
    source_answer: str = Field(default='', max_length=10_000)
    source_explanation: str = Field(default='', max_length=50_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def fields_are_structurally_safe(self) -> 'ImportItem':
        if any(not value.strip() or len(value) > 512 for value in self.module_path):
            raise ValueError('Module path values must be non-empty and at most 512 characters')
        if any(not value.strip() or len(value) > 512 for value in self.knowledge_points):
            raise ValueError('Knowledge point values must be non-empty and at most 512 characters')
        normalized_keys = [key.strip() for key in self.options]
        if any(not key or not value.strip() for key, value in self.options.items()):
            raise ValueError('Options must use non-empty keys and values')
        if len(set(normalized_keys)) != len(normalized_keys):
            raise ValueError('Option keys must remain unique after normalization')
        if len(json.dumps(self.metadata, ensure_ascii=False)) > 65_536:
            raise ValueError('Item metadata must not exceed 64 KiB')
        return self


class LearningImportRequest(_StrictImportModel):
    schema_version: Literal['learning-import/v1'] = 'learning-import/v1'
    project: ImportProject
    bank: ImportBank
    items: list[ImportItem] = Field(..., min_length=1, max_length=10_000)


class ImportEnrichmentRequest(_StrictImportModel):
    profile_id: str | None = Field(default=None, max_length=256)
    provider: str | None = Field(default=None, max_length=256)
    model: str | None = Field(default=None, max_length=256)
    prompt_version: str = Field(default='learning-import/v1', max_length=128)
    limit: int = Field(default=100, ge=1, le=1000)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=600)


class ImportApprovalRequest(_StrictImportModel):
    mode: Literal['all_valid', 'high_confidence', 'selected'] = 'all_valid'
    selected_item_ids: list[str] = Field(default_factory=list, max_length=10_000)
    minimum_confidence: float = Field(default=0.8, ge=0, le=1)

    @model_validator(mode='after')
    def selected_mode_requires_items(self) -> 'ImportApprovalRequest':
        if self.mode == 'selected' and not self.selected_item_ids:
            raise ValueError('selected_item_ids is required when approval mode is selected')
        return self
