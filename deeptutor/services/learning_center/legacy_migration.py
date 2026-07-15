"""Read-only migration from legacy ``exam_practice.db`` into Learning Center v2.

This is a trusted local migration service, not an LLM tool.  It opens the
legacy database in SQLite read-only mode and writes only the independent v2
store through a versioned, idempotent mapping protocol.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import sqlite3
import time
from typing import Any

from .normalization import canonical_json, clean_text, stable_id
from .repository import LearningCenterRepository

MIGRATION_NAME = "exam_practice_to_learning_center/v1"


@dataclass(frozen=True)
class MigrationResult:
    report: dict[str, Any]
    migrated: bool


def _loads(value: str | None, fallback: Any) -> Any:
    try:
        decoded = json.loads(value or "")
    except (TypeError, ValueError):
        return fallback
    return decoded if isinstance(decoded, type(fallback)) else fallback


def _timestamp(value: Any, fallback: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return fallback


def _normalize_options(value: str | None) -> dict[str, str]:
    raw = _loads(value, {})
    if isinstance(raw, list):
        return {chr(ord("A") + index): clean_text(item) for index, item in enumerate(raw)}
    if isinstance(raw, dict):
        return {clean_text(key).rstrip("、."): clean_text(item) for key, item in raw.items() if clean_text(key)}
    return {}


def _json(value: Any) -> str:
    return canonical_json(value)


class LegacyExamPracticeMigrator:
    """Migrate one immutable legacy DB into one Learning Center target DB."""

    def __init__(self, source_db: Path, target_db: Path, *, resume: bool = False):
        self.source_db = Path(source_db)
        self.target_db = Path(target_db)
        self.resume = resume

    def _source(self) -> sqlite3.Connection:
        if not self.source_db.is_file():
            raise FileNotFoundError(f"Legacy exam-practice database not found: {self.source_db}")
        conn = sqlite3.connect(f"file:{self.source_db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _target(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            conn = sqlite3.connect(f"file:{self.target_db}?mode=ro", uri=True)
        else:
            # This performs only target-schema migrations; it never opens the
            # legacy DB for writing.
            LearningCenterRepository(self.target_db)
            conn = sqlite3.connect(self.target_db, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @staticmethod
    def _id(kind: str, *parts: Any) -> str:
        return stable_id(f"legacy_{kind}", *parts)

    @staticmethod
    def _mapping(
        target: sqlite3.Connection, legacy_table: str, legacy_id: Any, target_table: str, target_id: str, now: float
    ) -> None:
        target.execute(
            """INSERT OR IGNORE INTO migration_mappings
               (id, migration_name, legacy_table, legacy_id, target_table, target_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                stable_id("migration_map", MIGRATION_NAME, legacy_table, legacy_id, target_table, target_id),
                MIGRATION_NAME,
                legacy_table,
                str(legacy_id),
                target_table,
                target_id,
                now,
            ),
        )

    def source_audit(self) -> dict[str, Any]:
        with self._source() as source:
            return self._source_audit(source)

    def _source_audit(self, source: sqlite3.Connection) -> dict[str, Any]:
        banks = [
            dict(row)
            for row in source.execute(
                """SELECT b.id, b.name, b.version, COUNT(q.id) AS questions
                   FROM exam_banks b LEFT JOIN exam_questions q ON q.bank_id = b.id
                  GROUP BY b.id ORDER BY b.id"""
            )
        ]
        question_types = [dict(row) for row in source.execute(
            "SELECT question_type, COUNT(*) AS count FROM exam_questions GROUP BY question_type ORDER BY question_type"
        )]
        return {
            "integrity_check": source.execute("PRAGMA integrity_check").fetchone()[0],
            "user_version": source.execute("PRAGMA user_version").fetchone()[0],
            "banks": banks,
            "bank_count": len(banks),
            "subjects": source.execute("SELECT COUNT(*) FROM exam_subjects").fetchone()[0],
            "chapters": source.execute("SELECT COUNT(*) FROM exam_chapters").fetchone()[0],
            "questions": source.execute("SELECT COUNT(*) FROM exam_questions").fetchone()[0],
            "question_types": question_types,
            "source_answers": source.execute("SELECT COUNT(*) FROM exam_questions WHERE TRIM(source_answer) <> ''").fetchone()[0],
            "source_explanations": source.execute("SELECT COUNT(*) FROM exam_questions WHERE TRIM(source_explanation) <> ''").fetchone()[0],
            "ai_explanations": source.execute("SELECT COUNT(*) FROM exam_questions WHERE TRIM(ai_explanation) <> ''").fetchone()[0],
            "missing_explanations": source.execute("SELECT COUNT(*) FROM exam_questions WHERE TRIM(source_explanation) = '' AND TRIM(ai_explanation) = ''").fetchone()[0],
            "ai_suggested_answers": source.execute("SELECT COUNT(*) FROM exam_questions WHERE answer_status = 'ai_suggested'").fetchone()[0],
            "practice_sessions": source.execute("SELECT COUNT(*) FROM practice_sessions").fetchone()[0],
            "practice_session_items": source.execute("SELECT COUNT(*) FROM practice_session_questions").fetchone()[0],
            "attempts": source.execute("SELECT COUNT(*) FROM practice_attempts").fetchone()[0],
            "wrong_questions": source.execute("SELECT COUNT(*) FROM wrong_questions").fetchone()[0],
            "manual_mastery_states": source.execute("SELECT COUNT(*) FROM wrong_questions WHERE mastery_status = 'mastered'").fetchone()[0],
            "persisted_question_discussions": 0,
            "persisted_question_discussion_messages": 0,
        }

    def _target_audit(self, target: sqlite3.Connection) -> dict[str, Any]:
        mappings = {
            str(row["legacy_table"]): int(row["count"])
            for row in target.execute(
                """SELECT legacy_table, COUNT(*) AS count FROM migration_mappings
                   WHERE migration_name = ? GROUP BY legacy_table""",
                (MIGRATION_NAME,),
            )
        }
        question_ids = [
            row[0]
            for row in target.execute(
                """SELECT target_id FROM migration_mappings
                   WHERE migration_name = ? AND legacy_table = 'exam_questions'""",
                (MIGRATION_NAME,),
            )
        ]
        condition, values = self._in_clause("id", question_ids)
        question_counts: dict[str, Any] = {
            "questions": len(question_ids), "source_answers": 0, "source_explanations": 0,
            "ai_explanations": 0, "missing_explanations": 0, "ai_suggested_answers": 0,
            "question_types": [],
        }
        if condition:
            question_counts.update(dict(target.execute(
                f"""SELECT
                    COUNT(*) AS questions,
                    SUM(CASE WHEN TRIM(source_answer) <> '' THEN 1 ELSE 0 END) AS source_answers,
                    SUM(CASE WHEN TRIM(source_explanation) <> '' THEN 1 ELSE 0 END) AS source_explanations,
                    SUM(CASE WHEN TRIM(source_explanation) = '' THEN 1 ELSE 0 END) AS missing_explanations
                  FROM questions WHERE {condition}""",
                values,
            ).fetchone()))
            question_counts["ai_explanations"] = target.execute(
                f"""SELECT COUNT(*) FROM ai_derivations
                    WHERE derivation_type = 'explanation' AND question_id IN ({','.join('?' for _ in question_ids)})""",
                question_ids,
            ).fetchone()[0]
            question_counts["missing_explanations"] = max(
                0, int(question_counts["missing_explanations"] or 0) - int(question_counts["ai_explanations"] or 0)
            )
            question_counts["question_types"] = [dict(row) for row in target.execute(
                f"SELECT question_type, COUNT(*) AS count FROM questions WHERE {condition} GROUP BY question_type ORDER BY question_type",
                values,
            )]
        return {
            "integrity_check": target.execute("PRAGMA integrity_check").fetchone()[0],
            "user_version": target.execute("PRAGMA user_version").fetchone()[0],
            "mappings": mappings,
            "bank_count": mappings.get("exam_banks", 0),
            "subjects": mappings.get("exam_subjects", 0),
            "chapters": mappings.get("exam_chapters", 0),
            "questions": question_counts["questions"],
            "question_types": question_counts["question_types"],
            "source_answers": int(question_counts["source_answers"] or 0),
            "source_explanations": int(question_counts["source_explanations"] or 0),
            "ai_explanations": int(question_counts["ai_explanations"] or 0),
            "missing_explanations": int(question_counts["missing_explanations"] or 0),
            "ai_suggested_answers": int(question_counts["ai_suggested_answers"] or 0),
            "practice_sessions": mappings.get("practice_sessions", 0),
            "practice_session_items": mappings.get("practice_session_questions", 0),
            "attempts": mappings.get("practice_attempts", 0),
            "wrong_questions": mappings.get("wrong_questions", 0),
            "manual_mastery_states": mappings.get("wrong_questions_manual_mastery", 0),
            "persisted_question_discussions": 0,
            "persisted_question_discussion_messages": 0,
        }

    @staticmethod
    def _in_clause(column: str, values: list[str]) -> tuple[str, list[str]]:
        if not values:
            return "", []
        return f"{column} IN ({','.join('?' for _ in values)})", values

    def dry_run(self) -> MigrationResult:
        source = self.source_audit()
        report = {
            "migration_name": MIGRATION_NAME,
            "mode": "dry-run",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "projected_target": {
                **source,
                "bank_count": source["bank_count"],
                "projects": source["bank_count"],
                "knowledge_points": 0,
                "persisted_question_discussions": 0,
                "persisted_question_discussion_messages": 0,
            },
            "writes_performed": False,
        }
        return MigrationResult(report=report, migrated=False)

    def migrate(self) -> MigrationResult:
        now = time.time()
        with self._source() as source, self._target() as target:
            source_audit = self._source_audit(source)
            target.execute("BEGIN IMMEDIATE")
            try:
                self._migrate_content(source, target, now)
                self._migrate_practice(source, target, now)
                target.commit()
            except Exception:
                target.rollback()
                raise
            target_audit = self._target_audit(target)
            comparison = self._verify(source, target, source_audit, target_audit)
        report = {
            "migration_name": MIGRATION_NAME,
            "mode": "resume" if self.resume else "migrate",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": source_audit,
            "target": target_audit,
            "comparison": comparison,
            "writes_performed": True,
        }
        return MigrationResult(report=report, migrated=True)

    def verify(self) -> MigrationResult:
        with self._source() as source, self._target(readonly=True) as target:
            source_audit = self._source_audit(source)
            target_audit = self._target_audit(target)
            comparison = self._verify(source, target, source_audit, target_audit)
        return MigrationResult(
            report={
                "migration_name": MIGRATION_NAME,
                "mode": "verify-only",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": source_audit,
                "target": target_audit,
                "comparison": comparison,
                "writes_performed": False,
            },
            migrated=False,
        )

    def _migrate_content(self, source: sqlite3.Connection, target: sqlite3.Connection, now: float) -> None:
        bank_rows = source.execute("SELECT * FROM exam_banks ORDER BY id").fetchall()
        project_by_bank: dict[str, str] = {}
        source_by_bank: dict[str, str] = {}
        bank_by_bank: dict[str, str] = {}
        version_by_bank: dict[str, str] = {}
        for bank in bank_rows:
            project_id = self._id("project", bank["id"])
            source_id = self._id("source", bank["id"])
            bank_id = self._id("bank", bank["id"])
            version_id = self._id("bank_version", bank["id"], bank["version"] or "legacy-v1")
            project_by_bank[bank["id"]] = project_id
            source_by_bank[bank["id"]] = source_id
            bank_by_bank[bank["id"]] = bank_id
            version_by_bank[bank["id"]] = version_id
            created = float(bank["created_at"] or now)
            updated = float(bank["updated_at"] or created)
            target.execute(
                """INSERT OR IGNORE INTO learning_projects
                   (id, external_id, name, kind, aliases_json, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, 'exam', '[]', ?, ?, ?)""",
                (project_id, f"legacy:exam_banks:{bank['id']}", bank["name"], _json({"legacy": {"table": "exam_banks", "id": bank["id"]}}), created, updated),
            )
            target.execute(
                """INSERT OR IGNORE INTO content_sources
                   (id, project_id, source_type, locator, external_id, revision, checksum, metadata_json, created_at, updated_at)
                   VALUES (?, ?, 'legacy_sqlite', ?, ?, ?, '', ?, ?, ?)""",
                (source_id, project_id, str(self.source_db), bank["id"], bank["version"] or "", _json({"legacy": {"source": bank["source"], "metadata": _loads(bank["metadata_json"], {})}}), created, updated),
            )
            target.execute(
                """INSERT OR IGNORE INTO question_banks
                   (id, project_id, source_id, external_id, name, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (bank_id, project_id, source_id, bank["id"], bank["name"], _json(_loads(bank["metadata_json"], {})), created, updated),
            )
            target.execute(
                """INSERT OR IGNORE INTO question_bank_versions
                   (id, bank_id, source_id, version, content_hash, status, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, '', 'active', ?, ?, ?)""",
                (version_id, bank_id, source_id, bank["version"] or "legacy-v1", _json({"legacy_bank_id": bank["id"]}), created, updated),
            )
            self._mapping(target, "exam_banks", bank["id"], "learning_projects", project_id, now)
            self._mapping(target, "exam_banks_sources", bank["id"], "content_sources", source_id, now)
            self._mapping(target, "exam_banks_question_banks", bank["id"], "question_banks", bank_id, now)
            self._mapping(target, "exam_banks_versions", bank["id"], "question_bank_versions", version_id, now)

        subject_modules: dict[str, str] = {}
        for subject in source.execute("SELECT * FROM exam_subjects ORDER BY bank_id, sort_order, id"):
            project_id = project_by_bank[subject["bank_id"]]
            module_id = self._id("module_subject", subject["id"])
            subject_modules[subject["id"]] = module_id
            created = float(subject["created_at"] or now)
            updated = float(subject["updated_at"] or created)
            path = f"subject/{subject['external_id'] or subject['id']}"
            target.execute(
                """INSERT OR IGNORE INTO content_modules
                   (id, project_id, parent_id, external_id, name, path, depth, sort_order, metadata_json, created_at, updated_at)
                   VALUES (?, ?, NULL, ?, ?, ?, 0, ?, '{}', ?, ?)""",
                (module_id, project_id, subject["external_id"] or subject["id"], subject["name"], path, subject["sort_order"], created, updated),
            )
            self._mapping(target, "exam_subjects", subject["id"], "content_modules", module_id, now)

        chapter_modules: dict[str, str] = {}
        chapters = source.execute("SELECT * FROM exam_chapters ORDER BY subject_id, path, sort_order, id").fetchall()
        # Legacy audit confirms current data has no nested chapter parents; this
        # loop still resolves any future parent chain deterministically.
        unresolved = list(chapters)
        while unresolved:
            next_round: list[sqlite3.Row] = []
            progressed = False
            for chapter in unresolved:
                parent_id = chapter["parent_id"]
                if parent_id and parent_id not in chapter_modules:
                    next_round.append(chapter)
                    continue
                module_id = self._id("module_chapter", chapter["id"])
                chapter_modules[chapter["id"]] = module_id
                subject_module = subject_modules[chapter["subject_id"]]
                parent_module = chapter_modules.get(parent_id) if parent_id else subject_module
                project = target.execute("SELECT project_id FROM content_modules WHERE id = ?", (subject_module,)).fetchone()
                assert project is not None
                subject_path = target.execute("SELECT path, depth FROM content_modules WHERE id = ?", (subject_module,)).fetchone()
                assert subject_path is not None
                raw_path = clean_text(chapter["path"]).strip("/") or clean_text(chapter["name"])
                path = f"{subject_path['path']}/{raw_path}" if not parent_id else f"{target.execute('SELECT path FROM content_modules WHERE id = ?', (parent_module,)).fetchone()[0]}/{clean_text(chapter['name'])}"
                parent_depth = target.execute("SELECT depth FROM content_modules WHERE id = ?", (parent_module,)).fetchone()[0]
                created = float(chapter["created_at"] or now)
                updated = float(chapter["updated_at"] or created)
                target.execute(
                    """INSERT OR IGNORE INTO content_modules
                       (id, project_id, parent_id, external_id, name, path, depth, sort_order, metadata_json, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (module_id, project["project_id"], parent_module, chapter["external_id"] or chapter["id"], chapter["name"], path, int(parent_depth) + 1, chapter["sort_order"], _json({"legacy_path": chapter["path"]}), created, updated),
                )
                self._mapping(target, "exam_chapters", chapter["id"], "content_modules", module_id, now)
                progressed = True
            if not progressed:
                raise RuntimeError("Legacy chapter hierarchy has a cycle or dangling parent")
            unresolved = next_round

        for question in source.execute("SELECT * FROM exam_questions ORDER BY id"):
            project_id = project_by_bank[question["bank_id"]]
            question_id = self._id("question", question["id"])
            source_id = source_by_bank[question["bank_id"]]
            options = _normalize_options(question["options_json"])
            created = float(question["created_at"] or now)
            updated = float(question["updated_at"] or created)
            module_id = chapter_modules.get(question["chapter_id"]) or subject_modules[question["subject_id"]]
            target.execute(
                """INSERT OR IGNORE INTO questions
                   (id, project_id, bank_id, bank_version_id, module_id, source_id, external_id, fingerprint,
                    question_type, stem, source_answer, source_explanation, difficulty, language, metadata_json,
                    provenance_type, review_status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?, 'source_original', 'accepted', ?, ?)""",
                (
                    question_id, project_id, bank_by_bank[question["bank_id"]], version_by_bank[question["bank_id"]], module_id, source_id,
                    question["external_id"] or question["id"], f"legacy:{question['fingerprint']}", question["question_type"], question["stem"],
                    question["source_answer"], question["source_explanation"], _json({"legacy": {"answer_status": question["answer_status"], "source": question["source"], "metadata": _loads(question["metadata_json"], {})}}), created, updated,
                ),
            )
            for position, (key, value) in enumerate(options.items()):
                target.execute(
                    """INSERT OR IGNORE INTO question_options
                       (id, question_id, option_key, content, sort_order, metadata_json, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, '{}', ?, ?)""",
                    (self._id("option", question["id"], key), question_id, key, value, position, created, updated),
                )
            source_revision_id = self._id("revision_source", question["id"])
            target.execute(
                """INSERT OR IGNORE INTO content_revisions
                   (id, project_id, question_id, source_id, field_name, value_json, provenance_type, review_status, supersedes_id, created_at)
                   VALUES (?, ?, ?, ?, 'source_content', ?, 'source_original', 'accepted', NULL, ?)""",
                (source_revision_id, project_id, question_id, source_id, _json({"stem": question["stem"], "options": options, "source_answer": question["source_answer"], "source_explanation": question["source_explanation"], "question_type": question["question_type"]}), created),
            )
            self._mapping(target, "exam_questions", question["id"], "questions", question_id, now)
            self._mapping(target, "exam_questions_source_revision", question["id"], "content_revisions", source_revision_id, now)
            if clean_text(question["ai_explanation"]):
                meta = _loads(question["metadata_json"], {})
                ai_meta = meta.get("ai_enrichment", {}).get("explanation", {}) if isinstance(meta, dict) else {}
                generated_at = _timestamp(ai_meta.get("generated_at"), updated) if isinstance(ai_meta, dict) else updated
                revision_id = self._id("revision_ai_explanation", question["id"])
                derivation_id = self._id("derivation_ai_explanation", question["id"])
                target.execute(
                    """INSERT OR IGNORE INTO content_revisions
                       (id, project_id, question_id, source_id, field_name, value_json, provenance_type, review_status, supersedes_id, created_at)
                       VALUES (?, ?, ?, NULL, 'explanation', ?, 'ai_generated', 'unreviewed', ?, ?)""",
                    (revision_id, project_id, question_id, _json({"text": question["ai_explanation"]}), source_revision_id, generated_at),
                )
                target.execute(
                    """INSERT OR IGNORE INTO ai_derivations
                       (id, project_id, question_id, revision_id, derivation_type, output_json, provider, model,
                        prompt_version, input_references_json, confidence, review_status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 'explanation', ?, ?, ?, ?, ?, NULL, 'unreviewed', ?, ?)""",
                    (
                        derivation_id, project_id, question_id, revision_id, _json({"text": question["ai_explanation"]}),
                        clean_text(ai_meta.get("provider") if isinstance(ai_meta, dict) else "") or "legacy_unknown",
                        clean_text(ai_meta.get("model") if isinstance(ai_meta, dict) else "") or "legacy_unknown",
                        clean_text(ai_meta.get("prompt_version") if isinstance(ai_meta, dict) else "") or "legacy-exam-enrichment/v1",
                        _json([f"legacy:exam_questions:{question['id']}"]), generated_at, generated_at,
                    ),
                )
                self._mapping(target, "exam_questions_ai_explanation", question["id"], "ai_derivations", derivation_id, now)

    def _migrate_practice(self, source: sqlite3.Connection, target: sqlite3.Connection, now: float) -> None:
        question_rows = target.execute(
            """SELECT m.legacy_id, m.target_id AS question_id, q.project_id, q.bank_version_id
                 FROM migration_mappings m JOIN questions q ON q.id = m.target_id
                WHERE m.migration_name = ? AND m.legacy_table = 'exam_questions'""",
            (MIGRATION_NAME,),
        ).fetchall()
        questions = {row["legacy_id"]: dict(row) for row in question_rows}
        session_targets: dict[str, str] = {}
        for session in source.execute("SELECT * FROM practice_sessions ORDER BY id"):
            items = source.execute(
                """SELECT psq.*, q.bank_id FROM practice_session_questions psq
                    JOIN exam_questions q ON q.id = psq.question_id WHERE psq.session_id = ? ORDER BY psq.position""",
                (session["id"],),
            ).fetchall()
            if not items:
                raise RuntimeError(f"Cannot determine project for legacy session without items: {session['id']}")
            first = questions[str(items[0]["question_id"])]
            project_id, bank_version_id = first["project_id"], first["bank_version_id"]
            if any(questions[str(item["question_id"])]["project_id"] != project_id for item in items):
                raise RuntimeError(f"Legacy session spans multiple projects: {session['id']}")
            target_id = self._id("practice_session", session["id"])
            session_targets[str(session["id"])] = target_id
            created = float(session["created_at"] or now)
            updated = float(session["updated_at"] or created)
            target.execute(
                """INSERT OR IGNORE INTO practice_sessions
                   (id, project_id, bank_version_id, mode, title, status, filters_json, proposal_json,
                    started_at, completed_at, created_at, updated_at)
                   VALUES (?, ?, ?, 'learning', ?, ?, ?, '{}', ?, ?, ?, ?)""",
                (target_id, project_id, bank_version_id, session["title"], session["status"], session["filters_json"] or "{}", created, session["completed_at"], created, updated),
            )
            self._mapping(target, "practice_sessions", session["id"], "practice_sessions", target_id, now)
            for item in items:
                question = questions[str(item["question_id"])]
                item_id = self._id("practice_session_item", session["id"], item["question_id"])
                target.execute(
                    """INSERT OR IGNORE INTO practice_session_items
                       (id, session_id, question_id, position, user_answer, confidence, marked_for_review, is_correct,
                        elapsed_seconds, submitted_at, updated_at, judgment_json)
                       VALUES (?, ?, ?, ?, ?, '', 0, ?, NULL, ?, ?, ?)""",
                    (item_id, target_id, question["question_id"], item["position"], item["user_answer"], item["is_correct"], item["submitted_at"], item["updated_at"], _json({"legacy_judgment": item["judgment"]})),
                )
                self._mapping(target, "practice_session_questions", f"{session['id']}:{item['question_id']}", "practice_session_items", item_id, now)

        for attempt in source.execute("SELECT * FROM practice_attempts ORDER BY id"):
            question = questions[str(attempt["question_id"])]
            session_id = session_targets[str(attempt["session_id"])]
            session_item_id = self._id("practice_session_item", attempt["session_id"], attempt["question_id"])
            target_id = self._id("attempt", attempt["id"])
            submitted = float(attempt["submitted_at"] or now)
            target.execute(
                """INSERT OR IGNORE INTO attempts
                   (id, session_id, session_item_id, question_id, user_answer, is_correct, confidence,
                    judgment_json, elapsed_seconds, submitted_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, '', ?, NULL, ?, ?)""",
                (target_id, session_id, session_item_id, question["question_id"], attempt["user_answer"], attempt["is_correct"], _json({"legacy_judgment": attempt["judgment"]}), submitted, submitted),
            )
            self._mapping(target, "practice_attempts", attempt["id"], "attempts", target_id, now)

        for wrong in source.execute("SELECT * FROM wrong_questions ORDER BY question_id"):
            question = questions[str(wrong["question_id"])]
            state = "manual_mastered" if wrong["mastery_status"] == "mastered" else "review_due"
            target.execute(
                """INSERT OR IGNORE INTO wrong_question_states
                   (question_id, project_id, state, wrong_count, correct_after_error_count, first_wrong_at,
                    last_wrong_at, last_attempt_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (question["question_id"], question["project_id"], state, wrong["wrong_count"], wrong["correct_count"], wrong["first_wrong_at"], wrong["last_wrong_at"], wrong["last_answer_at"], wrong["updated_at"]),
            )
            target.execute(
                """INSERT OR IGNORE INTO question_mastery
                   (question_id, project_id, system_mastery_score, system_mastery_level, algorithm_version, updated_at)
                   VALUES (?, ?, 0, ?, 'legacy-import/v1', ?)""",
                (question["question_id"], question["project_id"], "learning" if wrong["mastery_status"] == "learning" else "stable", wrong["updated_at"]),
            )
            self._mapping(target, "wrong_questions", wrong["question_id"], "wrong_question_states", question["question_id"], now)
            if wrong["mastery_status"] == "mastered":
                override_id = self._id("manual_mastery", wrong["question_id"])
                target.execute(
                    """INSERT OR IGNORE INTO manual_mastery_overrides
                       (id, project_id, question_id, knowledge_point_id, status, note, created_at, updated_at)
                       VALUES (?, ?, ?, NULL, 'mastered', 'Migrated legacy manual mastery status', ?, ?)""",
                    (override_id, question["project_id"], question["question_id"], wrong["updated_at"], wrong["updated_at"]),
                )
                self._mapping(target, "wrong_questions_manual_mastery", wrong["question_id"], "manual_mastery_overrides", override_id, now)

    def _verify(
        self,
        source: sqlite3.Connection,
        target: sqlite3.Connection,
        source_audit: dict[str, Any],
        target_audit: dict[str, Any],
    ) -> dict[str, Any]:
        count_keys = (
            "bank_count", "subjects", "chapters", "questions", "source_answers", "source_explanations",
            "ai_explanations", "missing_explanations", "ai_suggested_answers", "practice_sessions",
            "practice_session_items", "attempts", "wrong_questions", "manual_mastery_states",
            "persisted_question_discussions", "persisted_question_discussion_messages",
        )
        count_mismatches = {
            key: {"source": source_audit[key], "target": target_audit[key]}
            for key in count_keys if source_audit[key] != target_audit[key]
        }
        source_types = {row["question_type"]: row["count"] for row in source_audit["question_types"]}
        target_types = {row["question_type"]: row["count"] for row in target_audit["question_types"]}
        if source_types != target_types:
            count_mismatches["question_types"] = {"source": source_types, "target": target_types}

        question_rows = source.execute("SELECT * FROM exam_questions ORDER BY id").fetchall()
        sample_size = min(100, len(question_rows))
        rng = random.Random(20260714)
        sample = rng.sample(question_rows, sample_size) if len(question_rows) > sample_size else question_rows
        question_differences: list[dict[str, Any]] = []
        for legacy in sample:
            target_id = self._id("question", legacy["id"])
            migrated = target.execute("SELECT * FROM questions WHERE id = ?", (target_id,)).fetchone()
            if migrated is None:
                question_differences.append({"legacy_id": legacy["id"], "error": "missing target question"})
                continue
            legacy_options = _normalize_options(legacy["options_json"])
            target_options = {
                row["option_key"]: row["content"]
                for row in target.execute("SELECT option_key, content FROM question_options WHERE question_id = ? ORDER BY sort_order", (target_id,))
            }
            checks = {
                "stem": legacy["stem"] == migrated["stem"],
                "question_type": legacy["question_type"] == migrated["question_type"],
                "source_answer": legacy["source_answer"] == migrated["source_answer"],
                "source_explanation": legacy["source_explanation"] == migrated["source_explanation"],
                "options": legacy_options == target_options,
            }
            if clean_text(legacy["ai_explanation"]):
                derived = target.execute(
                    "SELECT output_json FROM ai_derivations WHERE id = ?", (self._id("derivation_ai_explanation", legacy["id"]),)
                ).fetchone()
                checks["ai_explanation"] = bool(derived) and _loads(derived["output_json"], {}).get("text") == legacy["ai_explanation"]
            if not all(checks.values()):
                question_differences.append({"legacy_id": legacy["id"], "checks": checks})

        session_rows = source.execute("SELECT * FROM practice_sessions ORDER BY id").fetchall()
        session_sample = session_rows[:20]
        session_differences: list[dict[str, Any]] = []
        for legacy in session_sample:
            target_id = self._id("practice_session", legacy["id"])
            migrated = target.execute("SELECT * FROM practice_sessions WHERE id = ?", (target_id,)).fetchone()
            source_items = source.execute("SELECT COUNT(*) FROM practice_session_questions WHERE session_id = ?", (legacy["id"],)).fetchone()[0]
            target_items = target.execute("SELECT COUNT(*) FROM practice_session_items WHERE session_id = ?", (target_id,)).fetchone()[0]
            if migrated is None or source_items != target_items or migrated["status"] != legacy["status"]:
                session_differences.append({"legacy_id": legacy["id"], "source_items": source_items, "target_items": target_items})

        wrong_differences: list[dict[str, Any]] = []
        for legacy in source.execute("SELECT * FROM wrong_questions ORDER BY question_id"):
            question_id = self._id("question", legacy["question_id"])
            migrated = target.execute("SELECT * FROM wrong_question_states WHERE question_id = ?", (question_id,)).fetchone()
            expected_state = "manual_mastered" if legacy["mastery_status"] == "mastered" else "review_due"
            if migrated is None or migrated["wrong_count"] != legacy["wrong_count"] or migrated["correct_after_error_count"] != legacy["correct_count"] or migrated["state"] != expected_state:
                wrong_differences.append({"legacy_question_id": legacy["question_id"], "expected_state": expected_state})

        passed = not count_mismatches and not question_differences and not session_differences and not wrong_differences and target_audit["integrity_check"] == "ok"
        return {
            "passed": passed,
            "count_mismatches": count_mismatches,
            "question_sample": {"size": sample_size, "differences": question_differences},
            "session_sample": {"size": len(session_sample), "differences": session_differences},
            "wrong_question_differences": wrong_differences,
            "legacy_source_read_only": True,
        }
