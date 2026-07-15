from __future__ import annotations

import hashlib
from pathlib import Path

from deeptutor.services.exam_practice import ExamPracticeStore
from deeptutor.services.learning_center.legacy_migration import LegacyExamPracticeMigrator


def _legacy_fixture(path: Path) -> ExamPracticeStore:
    store = ExamPracticeStore(path)
    summary = store.import_bank(
        {"id": "legacy-bank", "name": "Legacy finance", "source": "fixture", "version": "v1"},
        [
            {
                "external_id": "q-1", "subject": "Law", "subject_external_id": "law",
                "chapter": "Disclosure", "chapter_external_id": "disclosure", "question_type": "single_choice",
                "stem": "Disclosure must be truthful?", "options": {"A": "No", "B": "Yes"},
                "source_answer": "B", "source_explanation": "The source says so.",
            },
            {
                "external_id": "q-2", "subject": "Law", "subject_external_id": "law",
                "chapter": "Disclosure", "chapter_external_id": "disclosure", "question_type": "single_choice",
                "stem": "An AI-only explanation example", "options": {"A": "No", "B": "Yes"},
                "source_answer": "B", "ai_explanation": "Generated explanation.",
                "metadata": {"ai_enrichment": {"explanation": {"provider": "custom", "model": "test-model", "prompt_version": "legacy/v1"}}},
            },
        ],
    )
    assert summary["created"] == 2
    subject_id = store.list_subjects(bank_id="legacy-bank")[0]["id"]
    chapter_id = store.list_chapters(subject_id=subject_id)[0]["id"]
    session = store.start_session(subject_id=subject_id, chapter_id=chapter_id, limit=1)
    question = session["questions"][0]
    store.submit_answers(session["id"], [{"question_id": question["id"], "user_answer": "A"}])
    return store


def test_dry_run_is_read_only_and_full_migration_is_idempotent(tmp_path: Path) -> None:
    source_path = tmp_path / "exam_practice.db"
    _legacy_fixture(source_path)
    target_path = tmp_path / "learning_center.db"
    source_before = hashlib.sha256(source_path.read_bytes()).hexdigest()

    dry = LegacyExamPracticeMigrator(source_path, target_path).dry_run()
    assert dry.report["writes_performed"] is False
    assert dry.report["source"]["questions"] == 2
    assert not target_path.exists()

    first = LegacyExamPracticeMigrator(source_path, target_path).migrate()
    assert first.report["comparison"]["passed"] is True
    assert first.report["target"]["questions"] == 2
    assert first.report["target"]["ai_explanations"] == 1
    assert first.report["target"]["practice_sessions"] == 1
    assert first.report["target"]["attempts"] == 1
    assert first.report["target"]["wrong_questions"] == 1
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_before

    second = LegacyExamPracticeMigrator(source_path, target_path, resume=True).migrate()
    assert second.report["comparison"]["passed"] is True
    assert second.report["target"] == first.report["target"]

    verified = LegacyExamPracticeMigrator(source_path, target_path).verify()
    assert verified.report["writes_performed"] is False
    assert verified.report["comparison"]["passed"] is True
