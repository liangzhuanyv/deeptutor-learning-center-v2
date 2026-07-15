"""Standalone, per-user SQLite persistence for exam-practice workflows."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from deeptutor.services.path_service import PathService

from .normalization import (
    clean_text,
    inferred_question_type,
    normalize_answer,
    normalize_options,
    question_fingerprint,
    stable_id,
)


class ExamPracticeError(Exception):
    """Base exception for the Exam Practice domain."""


class ExamPracticeNotFoundError(ExamPracticeError):
    """Raised when an entity or scoped relationship does not exist."""


class ExamPracticeValidationError(ExamPracticeError):
    """Raised for a syntactically valid but unusable domain request."""


_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS exam_banks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS exam_subjects (
    id TEXT PRIMARY KEY,
    bank_id TEXT NOT NULL REFERENCES exam_banks(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(bank_id, external_id),
    UNIQUE(bank_id, name)
);
CREATE INDEX IF NOT EXISTS idx_exam_subjects_bank ON exam_subjects(bank_id, sort_order, name);

CREATE TABLE IF NOT EXISTS exam_chapters (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL REFERENCES exam_subjects(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    parent_id TEXT REFERENCES exam_chapters(id) ON DELETE SET NULL,
    path TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(subject_id, external_id),
    UNIQUE(subject_id, path)
);
CREATE INDEX IF NOT EXISTS idx_exam_chapters_subject ON exam_chapters(subject_id, sort_order, name);

CREATE TABLE IF NOT EXISTS exam_questions (
    id TEXT PRIMARY KEY,
    bank_id TEXT NOT NULL REFERENCES exam_banks(id) ON DELETE CASCADE,
    subject_id TEXT NOT NULL REFERENCES exam_subjects(id) ON DELETE RESTRICT,
    chapter_id TEXT REFERENCES exam_chapters(id) ON DELETE SET NULL,
    external_id TEXT NOT NULL DEFAULT '',
    fingerprint TEXT NOT NULL,
    question_type TEXT NOT NULL DEFAULT '单选',
    stem TEXT NOT NULL,
    options_json TEXT NOT NULL DEFAULT '{}',
    source_answer TEXT NOT NULL DEFAULT '',
    answer_status TEXT NOT NULL DEFAULT '',
    source_explanation TEXT NOT NULL DEFAULT '',
    ai_explanation TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(bank_id, fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_exam_questions_filters
    ON exam_questions(subject_id, chapter_id, question_type);
CREATE INDEX IF NOT EXISTS idx_exam_questions_bank ON exam_questions(bank_id);

CREATE TABLE IF NOT EXISTS practice_sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    filters_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    completed_at REAL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS practice_session_questions (
    session_id TEXT NOT NULL REFERENCES practice_sessions(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES exam_questions(id) ON DELETE RESTRICT,
    position INTEGER NOT NULL,
    user_answer TEXT NOT NULL DEFAULT '',
    is_correct INTEGER,
    judgment TEXT NOT NULL DEFAULT '',
    submitted_at REAL,
    updated_at REAL NOT NULL,
    PRIMARY KEY(session_id, question_id),
    UNIQUE(session_id, position)
);
CREATE INDEX IF NOT EXISTS idx_practice_session_questions_question
    ON practice_session_questions(question_id);

CREATE TABLE IF NOT EXISTS practice_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES practice_sessions(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES exam_questions(id) ON DELETE RESTRICT,
    user_answer TEXT NOT NULL DEFAULT '',
    is_correct INTEGER,
    judgment TEXT NOT NULL DEFAULT '',
    submitted_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_practice_attempts_question ON practice_attempts(question_id, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_practice_attempts_session ON practice_attempts(session_id, submitted_at);

CREATE TABLE IF NOT EXISTS wrong_questions (
    question_id TEXT PRIMARY KEY REFERENCES exam_questions(id) ON DELETE CASCADE,
    wrong_count INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    first_wrong_at REAL NOT NULL,
    last_wrong_at REAL NOT NULL,
    last_answer_at REAL NOT NULL,
    last_session_id TEXT NOT NULL DEFAULT '',
    mastery_status TEXT NOT NULL DEFAULT 'learning'
        CHECK(mastery_status IN ('learning', 'mastered')),
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wrong_questions_status_recent
    ON wrong_questions(mastery_status, last_wrong_at DESC);
"""


class ExamPracticeStore:
    """Owns the independent ``exam_practice.db`` SQLite database.

    A new connection is opened for every operation to keep this safe with
    FastAPI's worker threads.  The database is deliberately separate from
    ``chat_history.db`` / Question Notebook so imports and migrations cannot
    affect chat data.
    """

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (PathService.get_instance().get_user_root() / "exam_practice.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version < 1:
                conn.executescript(_SCHEMA_V1)
                conn.execute("PRAGMA user_version = 1")

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _loads(value: str, fallback: Any) -> Any:
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, type(fallback)) else fallback
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _now() -> float:
        return time.time()

    @staticmethod
    def _coerce_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _serialize_bank(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "source": row["source"],
            "version": row["version"],
            "metadata": self._loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _serialize_subject(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "bank_id": row["bank_id"],
            "external_id": row["external_id"],
            "name": row["name"],
            "sort_order": row["sort_order"],
            "question_count": row["question_count"] if "question_count" in row.keys() else 0,
        }

    def _serialize_chapter(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "subject_id": row["subject_id"],
            "external_id": row["external_id"],
            "name": row["name"],
            "parent_id": row["parent_id"],
            "path": row["path"],
            "sort_order": row["sort_order"],
            "question_count": row["question_count"] if "question_count" in row.keys() else 0,
        }

    def _serialize_question(self, row: sqlite3.Row, *, include_answer: bool) -> dict[str, Any]:
        result = {
            "id": row["id"],
            "bank_id": row["bank_id"],
            "subject_id": row["subject_id"],
            "subject_name": row["subject_name"] if "subject_name" in row.keys() else "",
            "chapter_id": row["chapter_id"],
            "chapter_name": row["chapter_name"] if "chapter_name" in row.keys() else "",
            "external_id": row["external_id"],
            "question_type": row["question_type"],
            "stem": row["stem"],
            "options": self._loads(row["options_json"], {}),
            "answer_status": row["answer_status"],
            "source": row["source"],
            "metadata": self._loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if include_answer:
            result.update(
                {
                    "source_answer": row["source_answer"],
                    "source_explanation": row["source_explanation"],
                    "ai_explanation": row["ai_explanation"],
                }
            )
        return result

    def _question_row(self, conn: sqlite3.Connection, question_id: str) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT q.*, s.name AS subject_name, c.name AS chapter_name
            FROM exam_questions q
            JOIN exam_subjects s ON s.id = q.subject_id
            LEFT JOIN exam_chapters c ON c.id = q.chapter_id
            WHERE q.id = ?
            """,
            (question_id,),
        ).fetchone()

    def _ensure_subject(
        self, conn: sqlite3.Connection, *, bank_id: str, external_id: str, name: str, sort_order: int, now: float
    ) -> str:
        cleaned_name = clean_text(name) or "未分类"
        # SQLite UNIQUE constraints treat an empty string as a real value.
        # Preserve idempotency for imports that do not provide external IDs by
        # deriving a stable internal import key from the subject name instead.
        cleaned_external_id = clean_text(external_id) or f"name:{cleaned_name}"
        subject_id = stable_id("subject", bank_id, cleaned_external_id)
        conn.execute(
            """
            INSERT INTO exam_subjects (id, bank_id, external_id, name, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                external_id = excluded.external_id,
                name = excluded.name,
                sort_order = excluded.sort_order,
                updated_at = excluded.updated_at
            """,
            (subject_id, bank_id, cleaned_external_id, cleaned_name, sort_order, now, now),
        )
        return subject_id

    def _ensure_chapter(
        self,
        conn: sqlite3.Connection,
        *,
        subject_id: str,
        external_id: str,
        name: str,
        path: str,
        sort_order: int,
        now: float,
    ) -> str | None:
        cleaned_name = clean_text(name)
        cleaned_path = clean_text(path) or cleaned_name
        if not cleaned_name and not cleaned_path:
            return None
        cleaned_external_id = clean_text(external_id) or f"path:{cleaned_path}"
        chapter_id = stable_id("chapter", subject_id, cleaned_external_id)
        conn.execute(
            """
            INSERT INTO exam_chapters (
                id, subject_id, external_id, name, path, sort_order, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                external_id = excluded.external_id,
                name = excluded.name,
                path = excluded.path,
                sort_order = excluded.sort_order,
                updated_at = excluded.updated_at
            """,
            (
                chapter_id,
                subject_id,
                cleaned_external_id,
                cleaned_name or cleaned_path,
                cleaned_path,
                sort_order,
                now,
                now,
            ),
        )
        return chapter_id

    def import_bank(
        self,
        bank: dict[str, Any],
        questions: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        """Upsert a bank and all of its questions.

        The idempotency key is ``(bank_id, external_id)`` when present, or a
        whitespace-insensitive stem/options/source-answer fingerprint.  A
        repeated import updates richer answers/explanations instead of adding
        duplicate questions.
        """
        bank_name = clean_text(bank.get("name")) or "未命名题库"
        bank_id = clean_text(bank.get("id") or bank.get("external_id")) or stable_id(
            "bank", bank_name, bank.get("source", "")
        )
        now = self._now()
        imported = updated = skipped = 0
        subject_ids: set[str] = set()
        chapter_ids: set[str] = set()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO exam_banks (id, name, source, version, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    source = excluded.source,
                    version = excluded.version,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    bank_id,
                    bank_name,
                    clean_text(bank.get("source")),
                    clean_text(bank.get("version")),
                    self._json(bank.get("metadata") if isinstance(bank.get("metadata"), dict) else {}),
                    now,
                    now,
                ),
            )

            for index, raw_question in enumerate(questions):
                if not isinstance(raw_question, dict):
                    skipped += 1
                    continue
                stem = clean_text(raw_question.get("stem") or raw_question.get("question") or raw_question.get("q"))
                source_answer = clean_text(
                    raw_question.get("source_answer")
                    if "source_answer" in raw_question
                    else raw_question.get("answer", raw_question.get("a"))
                )
                options = normalize_options(
                    raw_question.get("options") or raw_question.get("choices") or raw_question.get("c")
                )
                if not stem:
                    skipped += 1
                    continue

                subject_name = clean_text(raw_question.get("subject") or raw_question.get("subject_name")) or "未分类"
                subject_id = self._ensure_subject(
                    conn,
                    bank_id=bank_id,
                    external_id=clean_text(raw_question.get("subject_external_id") or raw_question.get("subject_id")),
                    name=subject_name,
                    sort_order=self._coerce_int(raw_question.get("subject_sort_order")),
                    now=now,
                )
                subject_ids.add(subject_id)
                chapter_name = clean_text(raw_question.get("chapter") or raw_question.get("chapter_name"))
                chapter_path = clean_text(raw_question.get("chapter_path")) or chapter_name
                chapter_id = self._ensure_chapter(
                    conn,
                    subject_id=subject_id,
                    external_id=clean_text(raw_question.get("chapter_external_id") or raw_question.get("chapter_id")),
                    name=chapter_name,
                    path=chapter_path,
                    sort_order=self._coerce_int(raw_question.get("chapter_sort_order")),
                    now=now,
                )
                if chapter_id:
                    chapter_ids.add(chapter_id)

                external_id = clean_text(raw_question.get("external_id") or raw_question.get("id"))
                fingerprint = question_fingerprint(stem, options, source_answer, external_id)
                existing = conn.execute(
                    "SELECT id FROM exam_questions WHERE bank_id = ? AND fingerprint = ?",
                    (bank_id, fingerprint),
                ).fetchone()
                question_id = existing["id"] if existing else stable_id("question", bank_id, fingerprint)
                question_type = inferred_question_type(
                    raw_question.get("question_type") or raw_question.get("type_cn") or raw_question.get("type"),
                    source_answer,
                )
                values = (
                    question_id,
                    bank_id,
                    subject_id,
                    chapter_id,
                    external_id,
                    fingerprint,
                    question_type,
                    stem,
                    self._json(options),
                    source_answer,
                    clean_text(raw_question.get("answer_status")),
                    clean_text(
                        raw_question.get("source_explanation")
                        or raw_question.get("explanation")
                        or raw_question.get("analysis")
                        or raw_question.get("an")
                    ),
                    clean_text(raw_question.get("ai_explanation")),
                    clean_text(raw_question.get("source") or bank.get("source")),
                    self._json(raw_question.get("metadata") if isinstance(raw_question.get("metadata"), dict) else {}),
                    now,
                    now,
                )
                conn.execute(
                    """
                    INSERT INTO exam_questions (
                        id, bank_id, subject_id, chapter_id, external_id, fingerprint, question_type,
                        stem, options_json, source_answer, answer_status, source_explanation,
                        ai_explanation, source, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(bank_id, fingerprint) DO UPDATE SET
                        subject_id = excluded.subject_id,
                        chapter_id = excluded.chapter_id,
                        external_id = excluded.external_id,
                        question_type = excluded.question_type,
                        stem = excluded.stem,
                        options_json = excluded.options_json,
                        source_answer = excluded.source_answer,
                        answer_status = excluded.answer_status,
                        source_explanation = excluded.source_explanation,
                        ai_explanation = excluded.ai_explanation,
                        source = excluded.source,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at
                    """,
                    values,
                )
                if existing:
                    updated += 1
                else:
                    imported += 1

        return {
            "bank_id": bank_id,
            "bank_name": bank_name,
            "created": imported,
            "updated": updated,
            "skipped": skipped,
            "subject_count": len(subject_ids),
            "chapter_count": len(chapter_ids),
        }

    def list_banks(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT b.*, COUNT(q.id) AS question_count
                FROM exam_banks b LEFT JOIN exam_questions q ON q.bank_id = b.id
                GROUP BY b.id ORDER BY b.updated_at DESC, b.name
                """
            ).fetchall()
            return [{**self._serialize_bank(row), "question_count": row["question_count"]} for row in rows]

    def list_subjects(self, bank_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            where, args = ("WHERE s.bank_id = ?", [bank_id]) if bank_id else ("", [])
            rows = conn.execute(
                f"""
                SELECT s.*, COUNT(q.id) AS question_count
                FROM exam_subjects s LEFT JOIN exam_questions q ON q.subject_id = s.id
                {where}
                GROUP BY s.id ORDER BY s.sort_order, s.name
                """,
                args,
            ).fetchall()
            return [self._serialize_subject(row) for row in rows]

    def list_chapters(self, subject_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            where, args = ("WHERE c.subject_id = ?", [subject_id]) if subject_id else ("", [])
            rows = conn.execute(
                f"""
                SELECT c.*, COUNT(q.id) AS question_count
                FROM exam_chapters c LEFT JOIN exam_questions q ON q.chapter_id = c.id
                {where}
                GROUP BY c.id ORDER BY c.sort_order, c.path, c.name
                """,
                args,
            ).fetchall()
            return [self._serialize_chapter(row) for row in rows]

    def get_question(self, question_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = self._question_row(conn, question_id)
            if not row:
                raise ExamPracticeNotFoundError("Question not found")
            result = self._serialize_question(row, include_answer=True)
            wrong = conn.execute("SELECT * FROM wrong_questions WHERE question_id = ?", (question_id,)).fetchone()
            result["wrong_book"] = self._serialize_wrong(row, wrong) if wrong else None
            return result

    def _selected_questions(
        self,
        conn: sqlite3.Connection,
        *,
        subject_id: str | None,
        chapter_id: str | None,
        question_types: list[str],
        limit: int,
    ) -> list[sqlite3.Row]:
        clauses: list[str] = []
        args: list[Any] = []
        if subject_id:
            clauses.append("q.subject_id = ?")
            args.append(subject_id)
        if chapter_id:
            clauses.append("q.chapter_id = ?")
            args.append(chapter_id)
        cleaned_types = [clean_text(item) for item in question_types if clean_text(item)]
        if cleaned_types:
            clauses.append(f"q.question_type IN ({','.join('?' for _ in cleaned_types)})")
            args.extend(cleaned_types)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return conn.execute(
            f"""
            SELECT q.*, s.name AS subject_name, c.name AS chapter_name
            FROM exam_questions q
            JOIN exam_subjects s ON s.id = q.subject_id
            LEFT JOIN exam_chapters c ON c.id = q.chapter_id
            {where}
            ORDER BY RANDOM() LIMIT ?
            """,
            [*args, limit],
        ).fetchall()

    def start_session(
        self,
        *,
        subject_id: str | None = None,
        chapter_id: str | None = None,
        question_types: list[str] | None = None,
        limit: int = 10,
        title: str = "",
    ) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise ExamPracticeValidationError("limit must be between 1 and 200")
        question_types = question_types or []
        with self._connect() as conn:
            rows = self._selected_questions(
                conn,
                subject_id=subject_id,
                chapter_id=chapter_id,
                question_types=question_types,
                limit=limit,
            )
            if not rows:
                raise ExamPracticeNotFoundError("No questions match the selected filters")
            now = self._now()
            session_id = f"practice_{uuid.uuid4().hex}"
            filters = {
                "subject_id": subject_id or "",
                "chapter_id": chapter_id or "",
                "question_types": [clean_text(item) for item in question_types if clean_text(item)],
                "limit": limit,
            }
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO practice_sessions (id, title, status, filters_json, created_at, updated_at) VALUES (?, ?, 'active', ?, ?, ?)",
                (session_id, clean_text(title), self._json(filters), now, now),
            )
            conn.executemany(
                """
                INSERT INTO practice_session_questions (session_id, question_id, position, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                [(session_id, row["id"], index, now) for index, row in enumerate(rows, start=1)],
            )
            return self._session_payload(conn, session_id, include_answers=False)

    def _session_payload(
        self, conn: sqlite3.Connection, session_id: str, *, include_answers: bool
    ) -> dict[str, Any]:
        session = conn.execute("SELECT * FROM practice_sessions WHERE id = ?", (session_id,)).fetchone()
        if not session:
            raise ExamPracticeNotFoundError("Practice session not found")
        rows = conn.execute(
            """
            SELECT sq.position, sq.user_answer, sq.is_correct, sq.judgment, sq.submitted_at,
                   q.*, s.name AS subject_name, c.name AS chapter_name
            FROM practice_session_questions sq
            JOIN exam_questions q ON q.id = sq.question_id
            JOIN exam_subjects s ON s.id = q.subject_id
            LEFT JOIN exam_chapters c ON c.id = q.chapter_id
            WHERE sq.session_id = ?
            ORDER BY sq.position
            """,
            (session_id,),
        ).fetchall()
        questions = []
        for row in rows:
            item = self._serialize_question(row, include_answer=include_answers or row["is_correct"] is not None)
            item.update(
                {
                    "position": row["position"],
                    "user_answer": row["user_answer"],
                    "is_correct": None if row["is_correct"] is None else bool(row["is_correct"]),
                    "judgment": row["judgment"],
                    "submitted_at": row["submitted_at"],
                }
            )
            questions.append(item)
        return {
            "id": session["id"],
            "title": session["title"],
            "status": session["status"],
            "filters": self._loads(session["filters_json"], {}),
            "created_at": session["created_at"],
            "completed_at": session["completed_at"],
            "updated_at": session["updated_at"],
            "questions": questions,
            "total": len(questions),
            "answered": sum(item["is_correct"] is not None for item in questions),
        }

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            return self._session_payload(conn, session_id, include_answers=False)

    def submit_answers(self, session_id: str, answers: Iterable[dict[str, Any]]) -> dict[str, Any]:
        payload = list(answers)
        if not payload:
            raise ExamPracticeValidationError("At least one answer is required")
        seen: set[str] = set()
        for answer in payload:
            question_id = clean_text(answer.get("question_id")) if isinstance(answer, dict) else ""
            if not question_id or question_id in seen:
                raise ExamPracticeValidationError("Each question can be submitted only once per request")
            seen.add(question_id)

        now = self._now()
        submitted: list[dict[str, Any]] = []
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            session = conn.execute("SELECT status FROM practice_sessions WHERE id = ?", (session_id,)).fetchone()
            if not session:
                raise ExamPracticeNotFoundError("Practice session not found")
            if session["status"] == "completed":
                raise ExamPracticeValidationError("Practice session is already completed")

            for answer in payload:
                question_id = clean_text(answer.get("question_id"))
                relation = conn.execute(
                    """
                    SELECT sq.question_id, q.source_answer
                    FROM practice_session_questions sq
                    JOIN exam_questions q ON q.id = sq.question_id
                    WHERE sq.session_id = ? AND sq.question_id = ?
                    """,
                    (session_id, question_id),
                ).fetchone()
                if not relation:
                    raise ExamPracticeNotFoundError("Question is not part of this practice session")
                user_answer = clean_text(answer.get("user_answer", answer.get("answer", "")))
                explicit_correct = answer.get("is_correct")
                if explicit_correct is None:
                    is_correct = bool(relation["source_answer"]) and (
                        normalize_answer(user_answer) == normalize_answer(relation["source_answer"])
                    )
                else:
                    is_correct = bool(explicit_correct)
                judgment = clean_text(answer.get("judgment"))
                conn.execute(
                    """
                    UPDATE practice_session_questions
                    SET user_answer = ?, is_correct = ?, judgment = ?, submitted_at = ?, updated_at = ?
                    WHERE session_id = ? AND question_id = ?
                    """,
                    (user_answer, int(is_correct), judgment, now, now, session_id, question_id),
                )
                conn.execute(
                    """
                    INSERT INTO practice_attempts (session_id, question_id, user_answer, is_correct, judgment, submitted_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (session_id, question_id, user_answer, int(is_correct), judgment, now),
                )
                self._record_wrong_book(
                    conn,
                    question_id=question_id,
                    session_id=session_id,
                    is_correct=is_correct,
                    now=now,
                )
                submitted.append({"question_id": question_id, "is_correct": is_correct})

            remaining = int(
                conn.execute(
                    "SELECT COUNT(*) FROM practice_session_questions WHERE session_id = ? AND is_correct IS NULL",
                    (session_id,),
                ).fetchone()[0]
            )
            status = "completed" if remaining == 0 else "active"
            conn.execute(
                """
                UPDATE practice_sessions
                SET status = ?, completed_at = CASE WHEN ? = 'completed' THEN ? ELSE completed_at END,
                    updated_at = ?
                WHERE id = ?
                """,
                (status, status, now, now, session_id),
            )
            session_payload = self._session_payload(conn, session_id, include_answers=False)
        return {"submitted": submitted, "remaining": remaining, "session": session_payload}

    def _record_wrong_book(
        self,
        conn: sqlite3.Connection,
        *,
        question_id: str,
        session_id: str,
        is_correct: bool,
        now: float,
    ) -> None:
        record = conn.execute("SELECT * FROM wrong_questions WHERE question_id = ?", (question_id,)).fetchone()
        if not record and is_correct:
            return
        if not record:
            conn.execute(
                """
                INSERT INTO wrong_questions (
                    question_id, wrong_count, correct_count, first_wrong_at, last_wrong_at,
                    last_answer_at, last_session_id, mastery_status, updated_at
                ) VALUES (?, 1, 0, ?, ?, ?, ?, 'learning', ?)
                """,
                (question_id, now, now, now, session_id, now),
            )
            return
        if is_correct:
            conn.execute(
                """
                UPDATE wrong_questions
                SET correct_count = correct_count + 1, last_answer_at = ?, last_session_id = ?, updated_at = ?
                WHERE question_id = ?
                """,
                (now, session_id, now, question_id),
            )
        else:
            conn.execute(
                """
                UPDATE wrong_questions
                SET wrong_count = wrong_count + 1, last_wrong_at = ?, last_answer_at = ?,
                    last_session_id = ?, mastery_status = 'learning', updated_at = ?
                WHERE question_id = ?
                """,
                (now, now, session_id, now, question_id),
            )

    def _serialize_wrong(self, question: sqlite3.Row, wrong: sqlite3.Row) -> dict[str, Any]:
        return {
            "question_id": question["id"],
            "stem": question["stem"],
            "question_type": question["question_type"],
            "subject_id": question["subject_id"],
            "subject_name": question["subject_name"] if "subject_name" in question.keys() else "",
            "chapter_id": question["chapter_id"],
            "chapter_name": question["chapter_name"] if "chapter_name" in question.keys() else "",
            "wrong_count": wrong["wrong_count"],
            "correct_count": wrong["correct_count"],
            "first_wrong_at": wrong["first_wrong_at"],
            "last_wrong_at": wrong["last_wrong_at"],
            "last_answer_at": wrong["last_answer_at"],
            "last_session_id": wrong["last_session_id"],
            "mastery_status": wrong["mastery_status"],
            "updated_at": wrong["updated_at"],
        }

    def list_wrong_questions(
        self, *, mastery_status: str | None = None, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        if not 1 <= limit <= 200 or offset < 0:
            raise ExamPracticeValidationError("limit must be 1..200 and offset must not be negative")
        if mastery_status and mastery_status not in {"learning", "mastered"}:
            raise ExamPracticeValidationError("mastery_status must be learning or mastered")
        with self._connect() as conn:
            clauses, args = [], []
            if mastery_status:
                clauses.append("w.mastery_status = ?")
                args.append(mastery_status)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"""
                SELECT w.*, q.*, s.name AS subject_name, c.name AS chapter_name
                FROM wrong_questions w
                JOIN exam_questions q ON q.id = w.question_id
                JOIN exam_subjects s ON s.id = q.subject_id
                LEFT JOIN exam_chapters c ON c.id = q.chapter_id
                {where}
                ORDER BY w.last_wrong_at DESC, w.updated_at DESC
                LIMIT ? OFFSET ?
                """,
                [*args, limit, offset],
            ).fetchall()
            total = int(conn.execute(f"SELECT COUNT(*) FROM wrong_questions w {where}", args).fetchone()[0])
            return {"items": [self._serialize_wrong(row, row) for row in rows], "total": total}

    def set_mastery_status(self, question_id: str, mastery_status: str) -> dict[str, Any]:
        if mastery_status not in {"learning", "mastered"}:
            raise ExamPracticeValidationError("mastery_status must be learning or mastered")
        with self._connect() as conn:
            now = self._now()
            cursor = conn.execute(
                "UPDATE wrong_questions SET mastery_status = ?, updated_at = ? WHERE question_id = ?",
                (mastery_status, now, question_id),
            )
            if not cursor.rowcount:
                raise ExamPracticeNotFoundError("Wrong-book record not found")
            question = self._question_row(conn, question_id)
            wrong = conn.execute("SELECT * FROM wrong_questions WHERE question_id = ?", (question_id,)).fetchone()
            assert question and wrong
            return self._serialize_wrong(question, wrong)

    def wrong_statistics(self) -> dict[str, Any]:
        with self._connect() as conn:
            summary = conn.execute(
                """
                SELECT COUNT(*) AS total_questions, COALESCE(SUM(wrong_count), 0) AS total_wrong_attempts,
                       COALESCE(SUM(correct_count), 0) AS total_correct_after_wrong,
                       COALESCE(SUM(CASE WHEN mastery_status = 'learning' THEN 1 ELSE 0 END), 0) AS learning_count,
                       COALESCE(SUM(CASE WHEN mastery_status = 'mastered' THEN 1 ELSE 0 END), 0) AS mastered_count
                FROM wrong_questions
                """
            ).fetchone()
            recent = conn.execute(
                """
                SELECT w.*, q.*, s.name AS subject_name, c.name AS chapter_name
                FROM wrong_questions w
                JOIN exam_questions q ON q.id = w.question_id
                JOIN exam_subjects s ON s.id = q.subject_id
                LEFT JOIN exam_chapters c ON c.id = q.chapter_id
                ORDER BY w.last_wrong_at DESC LIMIT 5
                """
            ).fetchall()
            return {**dict(summary), "recent": [self._serialize_wrong(row, row) for row in recent]}

    def weak_points(self, *, subject_id: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Build deterministic weak-point candidates from the wrong-book.

        A card groups all wrong-book questions in one chapter (or the
        subject's unchaptered bucket).  It deliberately performs no model
        inference; an enrichment worker can later replace/extend ``summary``.
        """
        if not 1 <= limit <= 50:
            raise ExamPracticeValidationError("limit must be between 1 and 50")
        with self._connect() as conn:
            where, args = ("WHERE q.subject_id = ?", [subject_id]) if subject_id else ("", [])
            rows = conn.execute(
                f"""
                SELECT w.*, q.id AS question_id, q.stem, q.source_explanation, q.ai_explanation,
                       s.id AS subject_id, s.name AS subject_name,
                       c.id AS chapter_id, c.name AS chapter_name, c.path AS chapter_path
                FROM wrong_questions w
                JOIN exam_questions q ON q.id = w.question_id
                JOIN exam_subjects s ON s.id = q.subject_id
                LEFT JOIN exam_chapters c ON c.id = q.chapter_id
                {where}
                ORDER BY s.name, c.path, c.name, w.wrong_count DESC, w.last_wrong_at DESC
                """,
                args,
            ).fetchall()

        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            chapter_id = row["chapter_id"] or f"uncategorized:{row['subject_id']}"
            chapter_name = row["chapter_name"] or "未分章节"
            key = (row["subject_id"], chapter_id)
            group = groups.setdefault(
                key,
                {
                    "chapter_id": row["chapter_id"],
                    "chapter_name": chapter_name,
                    "subject_id": row["subject_id"],
                    "subject_name": row["subject_name"],
                    "evidence_question_ids": [],
                    "wrong_question_count": 0,
                    "total_wrong_attempts": 0,
                    "_explanations": [],
                },
            )
            group["wrong_question_count"] += 1
            group["total_wrong_attempts"] += row["wrong_count"]
            if len(group["evidence_question_ids"]) < 5:
                group["evidence_question_ids"].append(row["question_id"])
            explanation = clean_text(row["ai_explanation"] or row["source_explanation"])
            if explanation and len(group["_explanations"]) < 2:
                group["_explanations"].append(explanation)

        cards: list[dict[str, Any]] = []
        for group in groups.values():
            chapter_name = group["chapter_name"]
            summary = (
                f"“{chapter_name}”共有 {group['wrong_question_count']} 道错题，"
                f"累计错误 {group['total_wrong_attempts']} 次，建议集中复习本章节。"
            )
            if group["_explanations"]:
                excerpts = "；".join(item[:120] for item in group["_explanations"])
                summary = f"{summary} 已有解析提示：{excerpts}"
            cards.append(
                {
                    "chapter_id": group["chapter_id"],
                    "chapter_name": chapter_name,
                    "title": f"{chapter_name} 易错知识点",
                    "evidence_question_ids": group["evidence_question_ids"],
                    "wrong_question_count": group["wrong_question_count"],
                    "total_wrong_attempts": group["total_wrong_attempts"],
                    "summary": summary,
                }
            )
        return sorted(
            cards,
            key=lambda card: (card["total_wrong_attempts"], card["wrong_question_count"], card["chapter_name"]),
            reverse=True,
        )[:limit]

    def chapter_statistics(self, subject_id: str | None = None) -> list[dict[str, Any]]:
        """Return chapter-level totals without multiplying attempts by sessions."""
        with self._connect() as conn:
            where, args = ("WHERE s.id = ?", [subject_id]) if subject_id else ("", [])
            rows = conn.execute(
                f"""
                WITH attempted_questions AS (
                    SELECT DISTINCT question_id FROM practice_session_questions WHERE is_correct IS NOT NULL
                ),
                attempt_totals AS (
                    SELECT question_id,
                           SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct_attempts,
                           SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END) AS wrong_attempts
                    FROM practice_attempts GROUP BY question_id
                )
                SELECT
                    s.id AS subject_id, s.name AS subject_name,
                    c.id AS chapter_id, c.name AS chapter_name, c.path AS chapter_path,
                    COUNT(q.id) AS question_count,
                    COALESCE(SUM(CASE WHEN aq.question_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS practiced_count,
                    COALESCE(SUM(at.correct_attempts), 0) AS correct_attempts,
                    COALESCE(SUM(at.wrong_attempts), 0) AS wrong_attempts,
                    COALESCE(SUM(CASE WHEN w.question_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS wrong_question_count
                FROM exam_subjects s
                LEFT JOIN exam_chapters c ON c.subject_id = s.id
                LEFT JOIN exam_questions q ON q.subject_id = s.id
                    AND (q.chapter_id = c.id OR (c.id IS NULL AND q.chapter_id IS NULL))
                LEFT JOIN attempted_questions aq ON aq.question_id = q.id
                LEFT JOIN attempt_totals at ON at.question_id = q.id
                LEFT JOIN wrong_questions w ON w.question_id = q.id
                {where}
                GROUP BY s.id, c.id
                HAVING COUNT(q.id) > 0
                ORDER BY s.name, c.path, c.name
                """,
                args,
            ).fetchall()
            return [dict(row) for row in rows]


def get_exam_practice_store() -> ExamPracticeStore:
    """Create a store for the current PathService user scope.

    No process-global cache is used so multi-user PathService scopes cannot
    accidentally share an SQLite path.
    """
    return ExamPracticeStore()
