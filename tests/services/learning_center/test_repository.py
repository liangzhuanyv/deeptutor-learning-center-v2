from __future__ import annotations

import concurrent.futures
import sqlite3
from pathlib import Path

import pytest

from deeptutor.services.learning_center import (
    ImmutableSourceContentError,
    LearningCenterRepository,
    SCHEMA_VERSION,
)


def _repo(tmp_path: Path) -> LearningCenterRepository:
    return LearningCenterRepository(tmp_path / "learning_center.db")


def _content_fixture(repo: LearningCenterRepository) -> tuple[dict, dict, dict, dict, dict, dict]:
    project = repo.create_project(name="Python data structures", kind="course", external_id="python-ds")
    module = repo.create_module(project_id=project["id"], name="Lists", path="01/lists", external_id="lists")
    knowledge = repo.create_knowledge_point(
        project_id=project["id"], module_id=module["id"], name="List mutation", external_id="list-mutation"
    )
    source = repo.create_content_source(
        project_id=project["id"], source_type="json", locator="fixture://python-ds.json", revision="v1"
    )
    bank = repo.create_bank(project_id=project["id"], source_id=source["id"], name="Practice bank")
    version = repo.create_bank_version(bank_id=bank["id"], source_id=source["id"], version="v1")
    return project, module, knowledge, source, bank, version


def test_fresh_schema_includes_required_tables_indexes_and_settings(tmp_path: Path) -> None:
    db_path = tmp_path / "learning_center.db"
    repo = LearningCenterRepository(db_path)
    assert repo.schema_version == SCHEMA_VERSION == 3

    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        required = {
            "learning_projects", "content_modules", "knowledge_points", "knowledge_point_relations",
            "question_banks", "question_bank_versions", "questions", "question_options",
            "question_knowledge_points", "content_sources", "content_revisions", "ai_derivations",
            "quality_issues", "review_decisions", "import_batches", "import_items", "practice_sessions",
            "practice_session_items", "attempts", "attempt_option_eliminations", "bookmarks",
            "wrong_question_states", "question_mastery", "knowledge_mastery", "mastery_evidence",
            "manual_mastery_overrides", "review_schedule", "ai_recommendations",
            "ai_recommendation_actions", "question_discussions", "question_discussion_messages", "learning_reports",
            "migration_mappings",
        }
        assert required <= tables
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    with repo._connect() as conn:  # noqa: SLF001 - verifies required connection settings
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_incremental_migration_from_v0_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "learning_center.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA user_version = 0")
    first = LearningCenterRepository(db_path)
    assert first.schema_version == 3
    second = LearningCenterRepository(db_path)
    assert second.schema_version == 3
    assert second.list_projects() == []




def test_incremental_migration_from_v1_adds_phase2_session_judgment_column(tmp_path: Path) -> None:
    db_path = tmp_path / "learning_center-v1.db"
    from deeptutor.services.learning_center import schema

    original = schema.SCHEMA_VERSION
    try:
        schema.SCHEMA_VERSION = 1
        LearningCenterRepository(db_path)
    finally:
        schema.SCHEMA_VERSION = original
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        columns = {row[1] for row in conn.execute("PRAGMA table_info(practice_session_items)")}
        assert "judgment_json" not in columns
    LearningCenterRepository(db_path)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        columns = {row[1] for row in conn.execute("PRAGMA table_info(practice_session_items)")}
        assert "judgment_json" in columns
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='import_batch_events'").fetchone()[0] == 1


def test_failed_migration_rolls_back_without_advancing_version(tmp_path: Path, monkeypatch) -> None:
    from deeptutor.services.learning_center import schema

    db_path = tmp_path / "failed-migration.db"
    monkeypatch.setitem(schema.MIGRATIONS, 1, "CREATE TABLE should_rollback (id INTEGER); THIS IS INVALID SQL;")
    with pytest.raises(sqlite3.OperationalError):
        LearningCenterRepository(db_path)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'should_rollback'"
        ).fetchone()[0] == 0

def test_foreign_key_behavior_and_generic_content_crud(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    project, module, knowledge, source, bank, version = _content_fixture(repo)
    question = repo.create_question(
        project_id=project["id"], bank_id=bank["id"], bank_version_id=version["id"], module_id=module["id"],
        source_id=source["id"], external_id="list-1", question_type="single_choice",
        stem="Which list method appends one item?", options={"A": "append", "B": "extend"},
        source_answer="A", source_explanation="append adds exactly one object.",
        knowledge_point_ids=[knowledge["id"]],
    )
    assert [option["key"] for option in question["options"]] == ["A", "B"]
    assert question["knowledge_points"] == [{"id": knowledge["id"], "name": "List mutation", "relation_type": "primary", "confidence": None}]
    assert repo.get_project(project["id"])["question_count"] == 1
    assert repo.list_modules(project["id"])[0]["path"] == "01/lists"
    assert repo.list_knowledge_points(project["id"])[0]["id"] == knowledge["id"]

    with pytest.raises(sqlite3.IntegrityError):
        with repo._connect() as conn:  # noqa: SLF001 - direct FK assertion
            conn.execute(
                "INSERT INTO question_options (id, question_id, option_key, content, sort_order, metadata_json, created_at, updated_at) VALUES ('bad', 'missing', 'A', 'nope', 0, '{}', 0, 0)"
            )


def test_source_is_immutable_and_ai_derivations_keep_full_provenance(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    project, module, knowledge, source, bank, version = _content_fixture(repo)
    question = repo.create_question(
        project_id=project["id"], bank_id=bank["id"], bank_version_id=version["id"], module_id=module["id"],
        source_id=source["id"], stem="A tuple is immutable.", source_answer="true", source_explanation="Tuples cannot be changed after creation.",
        question_type="true_false", knowledge_point_ids=[knowledge["id"]],
    )
    with pytest.raises(ImmutableSourceContentError):
        repo.replace_source_content(question["id"], source_answer="false")

    revision = repo.add_content_revision(
        project_id=project["id"], question_id=question["id"], source_id=source["id"],
        field_name="explanation", value={"text": "A learner clarified the wording."}, provenance_type="user_edited", review_status="accepted",
    )
    derivation = repo.add_ai_derivation(
        project_id=project["id"], question_id=question["id"], revision_id=revision["id"], derivation_type="explanation",
        output={"text": "AI supplement."}, provider="test-provider", model="test-model", prompt_version="learning-center/v1",
        input_references=[source["id"], revision["id"]], confidence=0.91,
    )
    review = repo.record_review_decision(
        project_id=project["id"], derivation_id=derivation["id"], decision="accepted", note="Useful supplement"
    )
    issue = repo.record_quality_issue(
        project_id=project["id"], question_id=question["id"], issue_type="missing_option_explanation", severity="warning"
    )
    provenance = repo.get_question_provenance(question["id"])
    assert repo.get_question(question["id"])["source_answer"] == "true"
    assert provenance["source"]["id"] == source["id"]
    assert {item["provenance_type"] for item in provenance["revisions"]} == {"source_original", "user_edited"}
    assert provenance["revisions"][0]["id"] == revision["id"]
    assert provenance["ai_derivations"][0]["id"] == derivation["id"]
    assert provenance["ai_derivations"][0]["provider"] == "test-provider"
    assert provenance["ai_derivations"][0]["prompt_version"] == "learning-center/v1"
    assert provenance["ai_derivations"][0]["review_status"] == "accepted"
    assert provenance["review_decisions"][0]["id"] == review["id"]
    assert issue["status"] == "open"


def test_concurrent_read_write_smoke(tmp_path: Path) -> None:
    db_path = tmp_path / "learning_center.db"
    LearningCenterRepository(db_path)

    def writer(index: int) -> str:
        return LearningCenterRepository(db_path).create_project(
            project_id=f"project-{index}", name=f"Course {index}", kind="course"
        )["id"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(writer, range(12)))
    assert len(result) == 12
    assert len(LearningCenterRepository(db_path).list_projects()) == 12
