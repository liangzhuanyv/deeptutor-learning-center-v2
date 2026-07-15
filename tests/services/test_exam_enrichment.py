"""Tests for conservative, catalog-selected exam enrichment."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.exam_enrichment import (
    ExamEnrichmentClient,
    ExamEnrichmentService,
    ExamPracticeSQLiteStore,
)
from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.exceptions import LLMRateLimitError


def _create_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE exam_questions (
                id TEXT PRIMARY KEY,
                stem TEXT NOT NULL,
                options_json TEXT NOT NULL DEFAULT '{}',
                source_answer TEXT NOT NULL DEFAULT '',
                answer_status TEXT NOT NULL DEFAULT '',
                source_explanation TEXT NOT NULL DEFAULT '',
                ai_explanation TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO exam_questions
                (id, stem, options_json, source_answer, source_explanation, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("q1", "2 + 2 = ?", '{"A":"3","B":"4"}', "", "", '{"import":"keep"}'),
                ("q2", "Earth is a planet?", '{"A":"Yes","B":"No"}', "A", "", "{}"),
                ("q3", "Already complete", "{}", "A", "Existing explanation", "{}"),
            ],
        )


def _catalog(path: Path) -> ModelCatalogService:
    service = ModelCatalogService(path=path)
    service.save(
        {
            "version": 1,
            "services": {
                "llm": {
                    "active_profile_id": "unrelated-active-profile",
                    "active_model_id": "unrelated-active-model",
                    "profiles": [
                        {
                            "id": "unrelated-active-profile",
                            "name": "Other",
                            "binding": "openai",
                            "base_url": "https://other.invalid/v1",
                            "api_key": "other-secret",
                            "models": [{"id": "unrelated-active-model", "model": "other-model"}],
                        },
                        {
                            "id": "llm-profile-pie-xian",
                            "name": "Pie Xian",
                            "binding": "openai",
                            "base_url": "https://api.pie-xian.com/v1",
                            "api_key": "catalog-secret-not-to-log",
                            "models": [
                                {
                                    "id": "llm-model-gemini-3-5-flash",
                                    "model": "gemini-3.5-flash",
                                }
                            ],
                        },
                    ],
                }
            },
        }
    )
    return service


@pytest.mark.asyncio
async def test_profile_selected_over_unrelated_active_profile(tmp_path: Path) -> None:
    received: dict[str, Any] = {}

    async def fake_completion(**kwargs: Any) -> str:
        received.update(kwargs)
        return '{"suggested_answer":"A","answer_confidence":0.9,"explanation":"Because."}'

    client = ExamEnrichmentClient(
        profile_id="llm-profile-pie-xian",
        model="gemini-3.5-flash",
        catalog_service=_catalog(tmp_path / "model_catalog.json"),
        completion=fake_completion,
    )

    payload = await client.enrich("question")

    assert payload.suggested_answer == "A"
    assert client.resolved_provider_and_model() == ("openai", "gemini-3.5-flash")
    assert received["model"] == "gemini-3.5-flash"
    assert received["binding"] == "openai"
    assert received["response_format"]["json_schema"]["strict"] is True
    assert "api_key" not in received
    assert "catalog-secret-not-to-log" not in repr(received)


@pytest.mark.asyncio
async def test_service_preserves_answers_and_records_provenance(tmp_path: Path) -> None:
    db_path = tmp_path / "exam_practice.db"
    _create_db(db_path)

    async def fake_completion(**kwargs: Any) -> str:
        prompt = kwargs["prompt"]
        if "2 + 2" in prompt:
            return '{"suggested_answer":"B","answer_confidence":0.98,"explanation":"2 plus 2 equals 4."}'
        return '{"suggested_answer":null,"answer_confidence":null,"explanation":"Earth orbits the Sun."}'

    client = ExamEnrichmentClient(completion=fake_completion)
    # Avoid relying on the environment's active LLM configuration in this unit test.
    client._config = LLMConfig(  # type: ignore[attr-defined]
        model="test-model", api_key="", provider_name="test-provider", binding="openai"
    )
    store = ExamPracticeSQLiteStore(db_path)
    service = ExamEnrichmentService(store, client, requests_per_minute=80, concurrency=2)

    summary = await service.run()

    assert summary.selected == 2
    assert summary.completed == 2
    assert summary.suggested_answers == 1
    assert summary.generated_explanations == 2
    with sqlite3.connect(db_path) as conn:
        one = conn.execute(
            """SELECT source_answer, answer_status, source_explanation,
                      ai_explanation, metadata_json
                 FROM exam_questions WHERE id = 'q1'"""
        ).fetchone()
        two = conn.execute(
            """SELECT source_answer, answer_status, source_explanation,
                      ai_explanation, metadata_json
                 FROM exam_questions WHERE id = 'q2'"""
        ).fetchone()
    assert one[0] == ""  # Source answer must never be overwritten.
    assert one[1] == "ai_suggested"
    assert one[2] == ""  # Imported/source explanation remains untouched.
    assert one[3] == "2 plus 2 equals 4."
    persisted_metadata = json.loads(one[4])
    assert persisted_metadata["import"] == "keep"
    one_meta = persisted_metadata["ai_enrichment"]
    assert one_meta["answer"]["status"] == "ai_suggested"
    assert one_meta["answer"]["needs_review"] is True
    assert one_meta["answer"]["confidence"] == 0.98
    assert one_meta["explanation"]["status"] == "ai_generated"
    assert one_meta["explanation"]["model"] == "test-model"
    assert two[0] == "A"
    assert two[2] == ""
    assert two[3] == "Earth orbits the Sun."

    # A resume sees no unfinished missing fields and makes no extra LLM calls.
    assert store.iter_candidates(resume=True) == []


@pytest.mark.asyncio
async def test_rate_limit_failure_is_retried(tmp_path: Path) -> None:
    db_path = tmp_path / "exam_practice.db"
    _create_db(db_path)
    calls = 0

    async def fake_completion(**_kwargs: Any) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise LLMRateLimitError(retry_after=0.0)
        return '{"suggested_answer":"B","answer_confidence":0.8,"explanation":"Explanation."}'

    client = ExamEnrichmentClient(completion=fake_completion)
    client._config = LLMConfig(  # type: ignore[attr-defined]
        model="test-model", api_key="", provider_name="test-provider", binding="openai"
    )
    service = ExamEnrichmentService(
        ExamPracticeSQLiteStore(db_path), client, requests_per_minute=80, max_attempts=2
    )
    service._limiter.acquire = _no_wait  # type: ignore[method-assign]

    summary = await service.run(limit=1)

    assert calls == 2
    assert summary.completed == 1
    assert summary.failed == 0


async def _no_wait() -> None:
    return None
