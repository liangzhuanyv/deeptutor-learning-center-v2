"""SQLite adapter for the standalone exam-practice question database."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from .models import EnrichmentResult, ExamQuestion

_DEFAULT_TABLE = "exam_questions"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COLUMN_ALIASES = {
    "id": ("id", "question_id"),
    "stem": ("stem", "question", "prompt", "content"),
    "options": ("options_json", "options", "choices_json", "choices"),
    # ``source_answer`` is the authoritative answer in the current exam-practice DB.
    "answer": ("source_answer", "correct_answer", "answer", "answer_text"),
    # Source text is immutable; generated text is written to a separate column
    # when the richer exam-practice schema is available.
    "source_explanation": ("source_explanation", "explanation", "analysis", "solution"),
}


class ExamPracticeSQLiteStore:
    """Read/write adapter with conservative, provenance-preserving updates.

    The current Exam Practice schema uses ``exam_questions`` with
    ``source_answer``, ``source_explanation``, ``ai_explanation``,
    ``answer_status`` and ``metadata_json``. This adapter understands that
    schema directly and keeps the two source fields untouched. A smaller,
    compatible question table can still be selected with ``--table``.
    """

    def __init__(self, db_path: str | Path, *, table: str = _DEFAULT_TABLE) -> None:
        self.db_path = Path(db_path)
        self.table = self._validate_identifier(table)
        self._columns: dict[str, str | None] | None = None

    @staticmethod
    def _validate_identifier(value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError(f"Unsafe SQLite identifier: {value!r}")
        return value

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _resolve_columns(self, conn: sqlite3.Connection) -> dict[str, str | None]:
        if self._columns is not None:
            return self._columns
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if self.table not in tables:
            raise ValueError(
                f"Table {self.table!r} does not exist in {self.db_path}. "
                "Pass --table for an existing question table."
            )
        available = {row[1] for row in conn.execute(f"PRAGMA table_info({self.table})").fetchall()}
        resolved: dict[str, str | None] = {}
        for logical_name, aliases in _COLUMN_ALIASES.items():
            column = next((candidate for candidate in aliases if candidate in available), None)
            if column is None:
                raise ValueError(
                    f"Table {self.table!r} lacks a {logical_name} column; expected one of {aliases}."
                )
            resolved[logical_name] = column

        # The production table stores AI text separately from imported source text.
        resolved["ai_explanation"] = (
            "ai_explanation" if "ai_explanation" in available else resolved["source_explanation"]
        )
        resolved["answer_status"] = "answer_status" if "answer_status" in available else None
        if "metadata_json" in available:
            resolved["metadata"] = "metadata_json"
        elif "enrichment_json" in available:
            resolved["metadata"] = "enrichment_json"
        else:
            conn.execute(
                f"ALTER TABLE {self.table} ADD COLUMN enrichment_json TEXT NOT NULL DEFAULT '{{}}'"
            )
            conn.commit()
            resolved["metadata"] = "enrichment_json"
        self._columns = resolved
        return resolved

    @staticmethod
    def _decode_json(value: Any, default: Any) -> Any:
        if isinstance(value, (dict, list)):
            return value
        if not isinstance(value, str) or not value.strip():
            return default
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return default
        return parsed if isinstance(parsed, type(default)) else default

    def iter_candidates(
        self, *, resume: bool = False, limit: int | None = None
    ) -> list[ExamQuestion]:
        """Return questions that are missing a source answer or all explanations.

        ``resume`` is intentionally idempotent: a prior answer suggestion or
        generated explanation is treated as complete while the original source
        columns remain blank and untouched.
        """
        del resume  # Both ordinary and resumed runs safely skip completed portions.
        if limit is not None and limit <= 0:
            return []
        with self._connect() as conn:
            columns = self._resolve_columns(conn)
            query = f"""
                SELECT {columns["id"]} AS _id, {columns["stem"]} AS _stem,
                       {columns["options"]} AS _options, {columns["answer"]} AS _answer,
                       {columns["source_explanation"]} AS _source_explanation,
                       {columns["ai_explanation"]} AS _ai_explanation,
                       {columns["metadata"]} AS _metadata
                FROM {self.table}
                WHERE TRIM(COALESCE({columns["answer"]}, '')) = ''
                   OR (
                       TRIM(COALESCE({columns["source_explanation"]}, '')) = ''
                       AND TRIM(COALESCE({columns["ai_explanation"]}, '')) = ''
                   )
                ORDER BY {columns["id"]}
            """
            if limit is not None:
                query += " LIMIT ?"
                rows = conn.execute(query, (limit,)).fetchall()
            else:
                rows = conn.execute(query).fetchall()
        questions: list[ExamQuestion] = []
        for row in rows:
            enrichment = self._decode_json(row["_metadata"], {})
            # Namespace only this service's metadata so other import/runtime
            # metadata fields survive an enrichment update exactly as-is.
            ai_enrichment = enrichment.get("ai_enrichment", {})
            if not isinstance(ai_enrichment, dict):
                ai_enrichment = {}
            question = ExamQuestion(
                id=row["_id"],
                stem=str(row["_stem"] or "").strip(),
                options=self._decode_json(row["_options"], {}),
                answer=str(row["_answer"] or "").strip(),
                explanation=(
                    str(row["_source_explanation"] or "").strip()
                    or str(row["_ai_explanation"] or "").strip()
                ),
                enrichment=ai_enrichment,
            )
            if question.stem and not self._is_already_enriched(question):
                questions.append(question)
        return questions

    @staticmethod
    def _is_already_enriched(question: ExamQuestion) -> bool:
        return not question.needs_answer and not question.needs_explanation

    def write_result(self, question: ExamQuestion, result: EnrichmentResult) -> tuple[bool, bool]:
        """Persist an AI answer suggestion/AI explanation without source mutations."""
        answer_written = question.needs_answer and bool(result.payload.suggested_answer)
        explanation_written = question.needs_explanation and bool(result.payload.explanation)
        if not answer_written and not explanation_written:
            return False, False

        provenance = {
            "provider": result.provider,
            "model": result.model,
            "generated_at": result.generated_at,
            "prompt_version": result.prompt_version,
        }
        with self._connect() as conn:
            columns = self._resolve_columns(conn)
            metadata_row = conn.execute(
                f"SELECT {columns['metadata']} AS _metadata FROM {self.table} "
                f"WHERE {columns['id']} = ?",
                (question.id,),
            ).fetchone()
            metadata = self._decode_json(metadata_row["_metadata"] if metadata_row else "", {})
            ai_enrichment = metadata.get("ai_enrichment", {})
            if not isinstance(ai_enrichment, dict):
                ai_enrichment = {}
            if answer_written:
                ai_enrichment["answer"] = {
                    "status": "ai_suggested",
                    "suggested_answer": result.payload.suggested_answer,
                    "confidence": result.payload.answer_confidence,
                    "needs_review": True,
                    **provenance,
                }
            if explanation_written:
                ai_enrichment["explanation"] = {"status": "ai_generated", **provenance}
            metadata["ai_enrichment"] = ai_enrichment

            assignments = [f"{columns['metadata']} = ?"]
            values: list[Any] = [json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))]
            if answer_written and columns["answer_status"]:
                assignments.append(f"{columns['answer_status']} = ?")
                values.append("ai_suggested")
            if explanation_written:
                assignments.append(f"{columns['ai_explanation']} = ?")
                values.append(result.payload.explanation)
            values.append(question.id)
            conn.execute(
                f"UPDATE {self.table} SET {', '.join(assignments)} WHERE {columns['id']} = ?",
                values,
            )
            conn.commit()
        return answer_written, explanation_written
