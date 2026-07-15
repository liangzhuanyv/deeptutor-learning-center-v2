"""Repository for the independent, generic Learning Center v2 database.

The repository intentionally exposes append-only provenance primitives.  It
has no operation that overwrites source answers or source explanations; a
correction is represented by a new content revision and optional review
record.  This boundary is what later import and AI pipelines must use instead
of writing SQLite directly.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from deeptutor.services.path_service import get_path_service

from .normalization import canonical_json, clean_text, question_fingerprint
from .schema import SCHEMA_VERSION, migrate


class LearningCenterError(Exception):
    """Base exception for Learning Center service errors."""


class LearningCenterNotFoundError(LearningCenterError):
    """Raised when a requested domain record does not exist."""


class LearningCenterValidationError(LearningCenterError):
    """Raised when a request is syntactically valid but violates domain rules."""


class ImmutableSourceContentError(LearningCenterError):
    """Raised when a caller attempts to mutate imported source content."""


_PROJECT_KINDS = {"exam", "course", "book", "skill", "other"}
_PROVENANCE_TYPES = {
    "source_original",
    "official",
    "user_edited",
    "ai_generated",
    "ai_inferred",
    "ai_suggested",
}
_REVIEW_STATUSES = {"unreviewed", "accepted", "rejected", "superseded"}


class LearningCenterRepository:
    """Owns a per-user ``learning_center.db`` with one connection per call."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or get_path_service().get_learning_center_db()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @staticmethod
    def _now() -> float:
        return time.time()

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    @staticmethod
    def _json(value: Any, fallback: Any) -> str:
        return canonical_json(fallback if value is None else value)

    @staticmethod
    def _loads(value: str | None, fallback: Any) -> Any:
        try:
            decoded = json.loads(value or "")
        except (TypeError, ValueError):
            return fallback
        return decoded if isinstance(decoded, type(fallback)) else fallback

    @staticmethod
    def _decode_json(value: str | None, fallback: Any = None) -> Any:
        try:
            return json.loads(value or "")
        except (TypeError, ValueError):
            return fallback

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        # WAL lets dashboard reads coexist with imports/practice writes.  It is
        # local to the new database and never touches legacy exam_practice.db.
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            migrate(conn)

    @property
    def schema_version(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])

    def _require_project(self, conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM learning_projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise LearningCenterNotFoundError(f"Learning project not found: {project_id}")
        return row

    def _require_question(self, conn: sqlite3.Connection, question_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
        if row is None:
            raise LearningCenterNotFoundError(f"Question not found: {question_id}")
        return row

    def _serialize_project(self, row: sqlite3.Row, *, counts: bool = False) -> dict[str, Any]:
        value = {
            "id": row["id"],
            "external_id": row["external_id"],
            "name": row["name"],
            "kind": row["kind"],
            "aliases": self._loads(row["aliases_json"], []),
            "metadata": self._loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if counts:
            value["module_count"] = row["module_count"]
            value["knowledge_point_count"] = row["knowledge_point_count"]
            value["question_count"] = row["question_count"]
        return value

    def _serialize_module(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "parent_id": row["parent_id"],
            "external_id": row["external_id"],
            "name": row["name"],
            "path": row["path"],
            "depth": row["depth"],
            "sort_order": row["sort_order"],
            "metadata": self._loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _serialize_knowledge_point(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "module_id": row["module_id"],
            "external_id": row["external_id"],
            "name": row["name"],
            "description": row["description"],
            "metadata": self._loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def create_project(
        self,
        *,
        name: str,
        kind: str = "other",
        external_id: str = "",
        aliases: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        name = clean_text(name)
        kind = clean_text(kind).lower() or "other"
        if not name:
            raise LearningCenterValidationError("Project name is required")
        if kind not in _PROJECT_KINDS:
            raise LearningCenterValidationError(f"Unsupported project kind: {kind}")
        now = self._now()
        identifier = clean_text(project_id) or self._new_id("project")
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO learning_projects
                   (id, external_id, name, kind, aliases_json, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    identifier,
                    clean_text(external_id),
                    name,
                    kind,
                    self._json(aliases, []),
                    self._json(metadata, {}),
                    now,
                    now,
                ),
            )
            return self._serialize_project(self._require_project(conn, identifier))

    def list_projects(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT p.*,
                         (SELECT COUNT(*) FROM content_modules m WHERE m.project_id = p.id) AS module_count,
                         (SELECT COUNT(*) FROM knowledge_points k WHERE k.project_id = p.id) AS knowledge_point_count,
                         (SELECT COUNT(*) FROM questions q WHERE q.project_id = p.id) AS question_count
                    FROM learning_projects p
                ORDER BY p.updated_at DESC, p.name COLLATE NOCASE"""
            ).fetchall()
            return [self._serialize_project(row, counts=True) for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            project = self._require_project(conn, project_id)
            counts = conn.execute(
                """SELECT
                     (SELECT COUNT(*) FROM content_modules WHERE project_id = ?) AS module_count,
                     (SELECT COUNT(*) FROM knowledge_points WHERE project_id = ?) AS knowledge_point_count,
                     (SELECT COUNT(*) FROM questions WHERE project_id = ?) AS question_count""",
                (project_id, project_id, project_id),
            ).fetchone()
            value = self._serialize_project(project)
            value.update(dict(counts))
            return value

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        kind: str | None = None,
        aliases: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            current = self._require_project(conn, project_id)
            next_name = clean_text(name) if name is not None else current["name"]
            next_kind = clean_text(kind).lower() if kind is not None else current["kind"]
            if not next_name:
                raise LearningCenterValidationError("Project name is required")
            if next_kind not in _PROJECT_KINDS:
                raise LearningCenterValidationError(f"Unsupported project kind: {next_kind}")
            conn.execute(
                """UPDATE learning_projects
                   SET name = ?, kind = ?, aliases_json = ?, metadata_json = ?, updated_at = ?
                 WHERE id = ?""",
                (
                    next_name,
                    next_kind,
                    self._json(aliases, self._loads(current["aliases_json"], [])) if aliases is not None else current["aliases_json"],
                    self._json(metadata, self._loads(current["metadata_json"], {})) if metadata is not None else current["metadata_json"],
                    self._now(),
                    project_id,
                ),
            )
            return self._serialize_project(self._require_project(conn, project_id))

    def create_module(
        self,
        *,
        project_id: str,
        name: str,
        path: str | None = None,
        parent_id: str | None = None,
        external_id: str = "",
        sort_order: int = 0,
        metadata: dict[str, Any] | None = None,
        module_id: str | None = None,
    ) -> dict[str, Any]:
        name = clean_text(name)
        if not name:
            raise LearningCenterValidationError("Module name is required")
        with self._connect() as conn:
            self._require_project(conn, project_id)
            parent_path = ""
            depth = 0
            if parent_id:
                parent = conn.execute(
                    "SELECT project_id, path, depth FROM content_modules WHERE id = ?", (parent_id,)
                ).fetchone()
                if parent is None or parent["project_id"] != project_id:
                    raise LearningCenterValidationError("Module parent must belong to the project")
                parent_path = parent["path"]
                depth = int(parent["depth"]) + 1
            normalized_path = clean_text(path).strip("/") or "/".join(
                part for part in (parent_path.strip("/"), name) if part
            )
            if not normalized_path:
                raise LearningCenterValidationError("Module path is required")
            now = self._now()
            identifier = clean_text(module_id) or self._new_id("module")
            conn.execute(
                """INSERT INTO content_modules
                   (id, project_id, parent_id, external_id, name, path, depth, sort_order,
                    metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    identifier, project_id, parent_id, clean_text(external_id), name,
                    normalized_path, depth, int(sort_order), self._json(metadata, {}), now, now,
                ),
            )
            row = conn.execute("SELECT * FROM content_modules WHERE id = ?", (identifier,)).fetchone()
            assert row is not None
            return self._serialize_module(row)

    def list_modules(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            self._require_project(conn, project_id)
            rows = conn.execute(
                "SELECT * FROM content_modules WHERE project_id = ? ORDER BY path, sort_order, name COLLATE NOCASE",
                (project_id,),
            ).fetchall()
            return [self._serialize_module(row) for row in rows]

    def create_knowledge_point(
        self,
        *,
        project_id: str,
        name: str,
        module_id: str | None = None,
        description: str = "",
        external_id: str = "",
        metadata: dict[str, Any] | None = None,
        knowledge_point_id: str | None = None,
    ) -> dict[str, Any]:
        name = clean_text(name)
        if not name:
            raise LearningCenterValidationError("Knowledge-point name is required")
        with self._connect() as conn:
            self._require_project(conn, project_id)
            if module_id:
                module = conn.execute("SELECT project_id FROM content_modules WHERE id = ?", (module_id,)).fetchone()
                if module is None or module["project_id"] != project_id:
                    raise LearningCenterValidationError("Knowledge point module must belong to the project")
            now = self._now()
            identifier = clean_text(knowledge_point_id) or self._new_id("knowledge")
            conn.execute(
                """INSERT INTO knowledge_points
                   (id, project_id, module_id, external_id, name, description, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (identifier, project_id, module_id, clean_text(external_id), name, clean_text(description), self._json(metadata, {}), now, now),
            )
            row = conn.execute("SELECT * FROM knowledge_points WHERE id = ?", (identifier,)).fetchone()
            assert row is not None
            return self._serialize_knowledge_point(row)

    def list_knowledge_points(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            self._require_project(conn, project_id)
            rows = conn.execute(
                "SELECT * FROM knowledge_points WHERE project_id = ? ORDER BY name COLLATE NOCASE", (project_id,)
            ).fetchall()
            return [self._serialize_knowledge_point(row) for row in rows]

    def create_content_source(
        self,
        *,
        source_type: str,
        locator: str = "",
        project_id: str | None = None,
        external_id: str = "",
        revision: str = "",
        checksum: str = "",
        metadata: dict[str, Any] | None = None,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        source_type = clean_text(source_type)
        if not source_type:
            raise LearningCenterValidationError("Source type is required")
        with self._connect() as conn:
            if project_id:
                self._require_project(conn, project_id)
            now = self._now()
            identifier = clean_text(source_id) or self._new_id("source")
            conn.execute(
                """INSERT INTO content_sources
                   (id, project_id, source_type, locator, external_id, revision, checksum,
                    metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (identifier, project_id, source_type, clean_text(locator), clean_text(external_id), clean_text(revision), clean_text(checksum), self._json(metadata, {}), now, now),
            )
            row = conn.execute("SELECT * FROM content_sources WHERE id = ?", (identifier,)).fetchone()
            assert row is not None
            return self._serialize_source(row)

    def _serialize_source(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "project_id": row["project_id"], "source_type": row["source_type"],
            "locator": row["locator"], "external_id": row["external_id"], "revision": row["revision"],
            "checksum": row["checksum"], "metadata": self._loads(row["metadata_json"], {}),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def create_bank(
        self,
        *,
        project_id: str,
        name: str,
        source_id: str | None = None,
        external_id: str = "",
        metadata: dict[str, Any] | None = None,
        bank_id: str | None = None,
    ) -> dict[str, Any]:
        name = clean_text(name)
        if not name:
            raise LearningCenterValidationError("Bank name is required")
        with self._connect() as conn:
            self._require_project(conn, project_id)
            if source_id and conn.execute("SELECT 1 FROM content_sources WHERE id = ?", (source_id,)).fetchone() is None:
                raise LearningCenterNotFoundError(f"Content source not found: {source_id}")
            identifier = clean_text(bank_id) or self._new_id("bank")
            now = self._now()
            conn.execute(
                """INSERT INTO question_banks
                   (id, project_id, source_id, external_id, name, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (identifier, project_id, source_id, clean_text(external_id), name, self._json(metadata, {}), now, now),
            )
            return self._serialize_bank(conn.execute("SELECT * FROM question_banks WHERE id = ?", (identifier,)).fetchone())

    def _serialize_bank(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            raise LearningCenterNotFoundError("Question bank not found")
        return {
            "id": row["id"], "project_id": row["project_id"], "source_id": row["source_id"],
            "external_id": row["external_id"], "name": row["name"],
            "metadata": self._loads(row["metadata_json"], {}), "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def create_bank_version(
        self,
        *,
        bank_id: str,
        version: str,
        source_id: str | None = None,
        content_hash: str = "",
        status: str = "active",
        metadata: dict[str, Any] | None = None,
        bank_version_id: str | None = None,
    ) -> dict[str, Any]:
        version = clean_text(version)
        if not version:
            raise LearningCenterValidationError("Bank version is required")
        with self._connect() as conn:
            bank = conn.execute("SELECT * FROM question_banks WHERE id = ?", (bank_id,)).fetchone()
            if bank is None:
                raise LearningCenterNotFoundError(f"Question bank not found: {bank_id}")
            if source_id and conn.execute("SELECT 1 FROM content_sources WHERE id = ?", (source_id,)).fetchone() is None:
                raise LearningCenterNotFoundError(f"Content source not found: {source_id}")
            identifier = clean_text(bank_version_id) or self._new_id("bank_version")
            now = self._now()
            conn.execute(
                """INSERT INTO question_bank_versions
                   (id, bank_id, source_id, version, content_hash, status, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (identifier, bank_id, source_id, version, clean_text(content_hash), clean_text(status) or "active", self._json(metadata, {}), now, now),
            )
            row = conn.execute("SELECT * FROM question_bank_versions WHERE id = ?", (identifier,)).fetchone()
            assert row is not None
            return self._serialize_bank_version(row)

    def _serialize_bank_version(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "bank_id": row["bank_id"], "source_id": row["source_id"],
            "version": row["version"], "content_hash": row["content_hash"], "status": row["status"],
            "metadata": self._loads(row["metadata_json"], {}), "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def create_question(
        self,
        *,
        project_id: str,
        bank_id: str,
        bank_version_id: str,
        stem: str,
        options: dict[str, str] | None = None,
        source_answer: str = "",
        source_explanation: str = "",
        question_type: str = "single_choice",
        module_id: str | None = None,
        source_id: str | None = None,
        external_id: str = "",
        fingerprint: str = "",
        difficulty: str = "",
        language: str = "",
        metadata: dict[str, Any] | None = None,
        knowledge_point_ids: Iterable[str] = (),
        question_id: str | None = None,
    ) -> dict[str, Any]:
        stem = clean_text(stem)
        normalized_options = {clean_text(key): clean_text(value) for key, value in (options or {}).items() if clean_text(key)}
        if not stem:
            raise LearningCenterValidationError("Question stem is required")
        if not clean_text(question_type):
            raise LearningCenterValidationError("Question type is required")
        fingerprint = clean_text(fingerprint) or question_fingerprint(stem, normalized_options, source_answer, external_id)
        with self._connect() as conn:
            self._require_project(conn, project_id)
            bank = conn.execute("SELECT project_id FROM question_banks WHERE id = ?", (bank_id,)).fetchone()
            version = conn.execute("SELECT bank_id FROM question_bank_versions WHERE id = ?", (bank_version_id,)).fetchone()
            if bank is None or bank["project_id"] != project_id:
                raise LearningCenterValidationError("Question bank must belong to the project")
            if version is None or version["bank_id"] != bank_id:
                raise LearningCenterValidationError("Bank version must belong to the question bank")
            if module_id:
                module = conn.execute("SELECT project_id FROM content_modules WHERE id = ?", (module_id,)).fetchone()
                if module is None or module["project_id"] != project_id:
                    raise LearningCenterValidationError("Question module must belong to the project")
            if source_id and conn.execute("SELECT 1 FROM content_sources WHERE id = ?", (source_id,)).fetchone() is None:
                raise LearningCenterNotFoundError(f"Content source not found: {source_id}")
            knowledge_ids = tuple(dict.fromkeys(clean_text(value) for value in knowledge_point_ids if clean_text(value)))
            for knowledge_id in knowledge_ids:
                record = conn.execute("SELECT project_id FROM knowledge_points WHERE id = ?", (knowledge_id,)).fetchone()
                if record is None or record["project_id"] != project_id:
                    raise LearningCenterValidationError("Question knowledge point must belong to the project")
            identifier = clean_text(question_id) or self._new_id("question")
            now = self._now()
            conn.execute(
                """INSERT INTO questions
                   (id, project_id, bank_id, bank_version_id, module_id, source_id, external_id, fingerprint,
                    question_type, stem, source_answer, source_explanation, difficulty, language, metadata_json,
                    provenance_type, review_status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'source_original', 'accepted', ?, ?)""",
                (identifier, project_id, bank_id, bank_version_id, module_id, source_id, clean_text(external_id), fingerprint,
                 clean_text(question_type), stem, clean_text(source_answer), clean_text(source_explanation), clean_text(difficulty),
                 clean_text(language), self._json(metadata, {}), now, now),
            )
            for position, (option_key, content) in enumerate(normalized_options.items()):
                conn.execute(
                    """INSERT INTO question_options
                       (id, question_id, option_key, content, sort_order, metadata_json, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, '{}', ?, ?)""",
                    (self._new_id("option"), identifier, option_key, content, position, now, now),
                )
            for knowledge_id in knowledge_ids:
                conn.execute(
                    """INSERT INTO question_knowledge_points
                       (question_id, knowledge_point_id, relation_type, confidence, created_at)
                       VALUES (?, ?, 'primary', NULL, ?)""",
                    (identifier, knowledge_id, now),
                )
            # Persist an append-only source snapshot at creation time.  The
            # identity row remains queryable for filters, while all later
            # corrections and AI suggestions are additive revisions.
            conn.execute(
                """INSERT INTO content_revisions
                   (id, project_id, question_id, source_id, field_name, value_json, provenance_type,
                    review_status, supersedes_id, created_at)
                   VALUES (?, ?, ?, ?, 'source_content', ?, 'source_original', 'accepted', NULL, ?)""",
                (
                    self._new_id("revision"), project_id, identifier, source_id,
                    canonical_json({
                        "stem": stem,
                        "options": normalized_options,
                        "source_answer": clean_text(source_answer),
                        "source_explanation": clean_text(source_explanation),
                        "question_type": clean_text(question_type),
                    }),
                    now,
                ),
            )
            return self._get_question(conn, identifier)

    def _get_question(self, conn: sqlite3.Connection, question_id: str) -> dict[str, Any]:
        row = self._require_question(conn, question_id)
        value = dict(row)
        value["metadata"] = self._loads(value.pop("metadata_json"), {})
        value["options"] = [
            {"id": option["id"], "key": option["option_key"], "content": option["content"], "sort_order": option["sort_order"], "metadata": self._loads(option["metadata_json"], {})}
            for option in conn.execute("SELECT * FROM question_options WHERE question_id = ? ORDER BY sort_order, option_key", (question_id,))
        ]
        value["knowledge_points"] = [
            {"id": record["id"], "name": record["name"], "relation_type": record["relation_type"], "confidence": record["confidence"]}
            for record in conn.execute(
                """SELECT k.id, k.name, qkp.relation_type, qkp.confidence
                   FROM question_knowledge_points qkp JOIN knowledge_points k ON k.id = qkp.knowledge_point_id
                  WHERE qkp.question_id = ? ORDER BY k.name""", (question_id,)
            )
        ]
        return value

    def get_question(self, question_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            return self._get_question(conn, question_id)

    def replace_source_content(self, question_id: str, **_values: Any) -> None:
        """Fail explicitly: imported source fields must be represented as revisions."""
        raise ImmutableSourceContentError(
            f"Question {question_id} source content is immutable; create a content revision instead"
        )

    def add_content_revision(
        self,
        *,
        project_id: str,
        field_name: str,
        value: Any,
        question_id: str | None = None,
        source_id: str | None = None,
        provenance_type: str = "user_edited",
        review_status: str = "unreviewed",
        supersedes_id: str | None = None,
        revision_id: str | None = None,
    ) -> dict[str, Any]:
        field_name = clean_text(field_name)
        provenance_type = clean_text(provenance_type)
        review_status = clean_text(review_status)
        if not field_name:
            raise LearningCenterValidationError("Revision field name is required")
        if provenance_type not in _PROVENANCE_TYPES:
            raise LearningCenterValidationError(f"Unknown provenance type: {provenance_type}")
        if review_status not in _REVIEW_STATUSES:
            raise LearningCenterValidationError(f"Unknown review status: {review_status}")
        with self._connect() as conn:
            self._require_project(conn, project_id)
            if question_id and self._require_question(conn, question_id)["project_id"] != project_id:
                raise LearningCenterValidationError("Revision question must belong to the project")
            if source_id and conn.execute("SELECT 1 FROM content_sources WHERE id = ?", (source_id,)).fetchone() is None:
                raise LearningCenterNotFoundError(f"Content source not found: {source_id}")
            if supersedes_id and conn.execute("SELECT 1 FROM content_revisions WHERE id = ?", (supersedes_id,)).fetchone() is None:
                raise LearningCenterNotFoundError(f"Superseded revision not found: {supersedes_id}")
            identifier = clean_text(revision_id) or self._new_id("revision")
            now = self._now()
            conn.execute(
                """INSERT INTO content_revisions
                   (id, project_id, question_id, source_id, field_name, value_json, provenance_type,
                    review_status, supersedes_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (identifier, project_id, question_id, source_id, field_name, canonical_json(value), provenance_type, review_status, supersedes_id, now),
            )
            return self._serialize_revision(conn.execute("SELECT * FROM content_revisions WHERE id = ?", (identifier,)).fetchone())

    def _serialize_revision(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            raise LearningCenterNotFoundError("Content revision not found")
        return {
            "id": row["id"], "project_id": row["project_id"], "question_id": row["question_id"],
            "source_id": row["source_id"], "field_name": row["field_name"], "value": self._decode_json(row["value_json"], {}),
            "provenance_type": row["provenance_type"], "review_status": row["review_status"],
            "supersedes_id": row["supersedes_id"], "created_at": row["created_at"],
        }

    def add_ai_derivation(
        self,
        *,
        project_id: str,
        derivation_type: str,
        output: Any,
        provider: str,
        model: str,
        prompt_version: str,
        question_id: str | None = None,
        revision_id: str | None = None,
        input_references: list[str] | None = None,
        confidence: float | None = None,
        review_status: str = "unreviewed",
        derivation_id: str | None = None,
    ) -> dict[str, Any]:
        derivation_type = clean_text(derivation_type)
        provider, model, prompt_version = clean_text(provider), clean_text(model), clean_text(prompt_version)
        review_status = clean_text(review_status)
        if not all((derivation_type, provider, model, prompt_version)):
            raise LearningCenterValidationError("AI derivation type, provider, model, and prompt version are required")
        if review_status not in _REVIEW_STATUSES:
            raise LearningCenterValidationError(f"Unknown review status: {review_status}")
        if confidence is not None and not 0 <= float(confidence) <= 1:
            raise LearningCenterValidationError("AI derivation confidence must be between 0 and 1")
        with self._connect() as conn:
            self._require_project(conn, project_id)
            if question_id and self._require_question(conn, question_id)["project_id"] != project_id:
                raise LearningCenterValidationError("AI derivation question must belong to the project")
            if revision_id:
                revision = conn.execute("SELECT project_id FROM content_revisions WHERE id = ?", (revision_id,)).fetchone()
                if revision is None or revision["project_id"] != project_id:
                    raise LearningCenterValidationError("AI derivation revision must belong to the project")
            identifier = clean_text(derivation_id) or self._new_id("derivation")
            now = self._now()
            conn.execute(
                """INSERT INTO ai_derivations
                   (id, project_id, question_id, revision_id, derivation_type, output_json, provider, model,
                    prompt_version, input_references_json, confidence, review_status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (identifier, project_id, question_id, revision_id, derivation_type, canonical_json(output), provider, model,
                 prompt_version, self._json(input_references, []), confidence, review_status, now, now),
            )
            return self._serialize_derivation(conn.execute("SELECT * FROM ai_derivations WHERE id = ?", (identifier,)).fetchone())

    def _serialize_derivation(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            raise LearningCenterNotFoundError("AI derivation not found")
        return {
            "id": row["id"], "project_id": row["project_id"], "question_id": row["question_id"],
            "revision_id": row["revision_id"], "derivation_type": row["derivation_type"],
            "output": self._decode_json(row["output_json"], {}), "provider": row["provider"], "model": row["model"],
            "prompt_version": row["prompt_version"], "input_references": self._loads(row["input_references_json"], []),
            "confidence": row["confidence"], "review_status": row["review_status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def record_review_decision(
        self,
        *,
        project_id: str,
        decision: str,
        revision_id: str | None = None,
        derivation_id: str | None = None,
        decided_by: str = "user",
        note: str = "",
        decision_id: str | None = None,
    ) -> dict[str, Any]:
        decision = clean_text(decision)
        if decision not in {"accepted", "rejected", "superseded"}:
            raise LearningCenterValidationError(f"Unknown review decision: {decision}")
        if not revision_id and not derivation_id:
            raise LearningCenterValidationError("A revision or AI derivation is required")
        with self._connect() as conn:
            self._require_project(conn, project_id)
            if revision_id:
                revision = conn.execute("SELECT project_id FROM content_revisions WHERE id = ?", (revision_id,)).fetchone()
                if revision is None or revision["project_id"] != project_id:
                    raise LearningCenterValidationError("Review revision must belong to the project")
            if derivation_id:
                derivation = conn.execute("SELECT project_id FROM ai_derivations WHERE id = ?", (derivation_id,)).fetchone()
                if derivation is None or derivation["project_id"] != project_id:
                    raise LearningCenterValidationError("Review derivation must belong to the project")
            identifier = clean_text(decision_id) or self._new_id("review")
            now = self._now()
            conn.execute(
                """INSERT INTO review_decisions
                   (id, project_id, revision_id, derivation_id, decision, decided_by, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (identifier, project_id, revision_id, derivation_id, decision, clean_text(decided_by) or "user", clean_text(note), now),
            )
            # This changes the review classification only; it never mutates a
            # source payload or replaces canonical source fields.
            if revision_id:
                conn.execute("UPDATE content_revisions SET review_status = ? WHERE id = ?", (decision, revision_id))
            if derivation_id:
                conn.execute("UPDATE ai_derivations SET review_status = ?, updated_at = ? WHERE id = ?", (decision, now, derivation_id))
            row = conn.execute("SELECT * FROM review_decisions WHERE id = ?", (identifier,)).fetchone()
            assert row is not None
            return self._serialize_review_decision(row)

    def _serialize_review_decision(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "project_id": row["project_id"], "revision_id": row["revision_id"],
            "derivation_id": row["derivation_id"], "decision": row["decision"], "decided_by": row["decided_by"],
            "note": row["note"], "created_at": row["created_at"],
        }

    def record_quality_issue(
        self,
        *,
        project_id: str,
        issue_type: str,
        question_id: str | None = None,
        severity: str = "warning",
        details: dict[str, Any] | None = None,
        issue_id: str | None = None,
    ) -> dict[str, Any]:
        issue_type = clean_text(issue_type)
        severity = clean_text(severity) or "warning"
        if not issue_type:
            raise LearningCenterValidationError("Quality issue type is required")
        if severity not in {"info", "warning", "error"}:
            raise LearningCenterValidationError(f"Unknown issue severity: {severity}")
        with self._connect() as conn:
            self._require_project(conn, project_id)
            if question_id and self._require_question(conn, question_id)["project_id"] != project_id:
                raise LearningCenterValidationError("Quality issue question must belong to the project")
            identifier = clean_text(issue_id) or self._new_id("issue")
            now = self._now()
            conn.execute(
                """INSERT INTO quality_issues
                   (id, project_id, question_id, import_item_id, issue_type, severity, status, details_json, created_at, updated_at)
                   VALUES (?, ?, ?, NULL, ?, ?, 'open', ?, ?, ?)""",
                (identifier, project_id, question_id, issue_type, severity, self._json(details, {}), now, now),
            )
            row = conn.execute("SELECT * FROM quality_issues WHERE id = ?", (identifier,)).fetchone()
            assert row is not None
            return {
                "id": row["id"], "project_id": row["project_id"], "question_id": row["question_id"],
                "issue_type": row["issue_type"], "severity": row["severity"], "status": row["status"],
                "details": self._loads(row["details_json"], {}), "created_at": row["created_at"], "updated_at": row["updated_at"],
            }

    def get_question_provenance(self, question_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            question = self._get_question(conn, question_id)
            source = None
            if question["source_id"]:
                row = conn.execute("SELECT * FROM content_sources WHERE id = ?", (question["source_id"],)).fetchone()
                source = self._serialize_source(row) if row is not None else None
            revisions = [self._serialize_revision(row) for row in conn.execute(
                "SELECT * FROM content_revisions WHERE question_id = ? ORDER BY created_at DESC", (question_id,)
            )]
            derivations = [self._serialize_derivation(row) for row in conn.execute(
                "SELECT * FROM ai_derivations WHERE question_id = ? ORDER BY created_at DESC", (question_id,)
            )]
            revision_ids = [item["id"] for item in revisions]
            derivation_ids = [item["id"] for item in derivations]
            conditions: list[str] = []
            values: list[str] = []
            if revision_ids:
                conditions.append("revision_id IN (" + ",".join("?" for _ in revision_ids) + ")")
                values.extend(revision_ids)
            if derivation_ids:
                conditions.append("derivation_id IN (" + ",".join("?" for _ in derivation_ids) + ")")
                values.extend(derivation_ids)
            decisions: list[dict[str, Any]] = []
            if conditions:
                rows = conn.execute(
                    "SELECT * FROM review_decisions WHERE " + " OR ".join(conditions) + " ORDER BY created_at DESC",
                    values,
                ).fetchall()
                decisions = [self._serialize_review_decision(row) for row in rows]
            return {
                "question_id": question_id, "source": source, "revisions": revisions,
                "ai_derivations": derivations, "review_decisions": decisions,
            }


_repositories: dict[Path, LearningCenterRepository] = {}


def get_learning_center_repository() -> LearningCenterRepository:
    """Return a repository keyed by the current authenticated user scope.

    A process-global singleton would pin the first caller's database and leak
    data across users.  The path is the stable scope key; each repository still
    opens a fresh SQLite connection per operation.
    """
    db_path = get_path_service().get_learning_center_db().resolve()
    repository = _repositories.get(db_path)
    if repository is None:
        repository = LearningCenterRepository(db_path)
        _repositories[db_path] = repository
    return repository
