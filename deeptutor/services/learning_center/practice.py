"""Scoped, resumable Learning Center practice sessions.

The service works exclusively against ``learning_center.db``.  It deliberately
returns a redacted question projection for active exam sessions so source
answers and explanations cannot accidentally leak through a frontend bug.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from typing import Any, Iterable

from .mastery import LearningMasteryService
from .normalization import canonical_json, clean_text
from .repository import (
    LearningCenterNotFoundError,
    LearningCenterRepository,
    LearningCenterValidationError,
)

_CONFIDENCE = {"", "sure", "uncertain", "guess"}
_WRONG_STATES = {"new", "review_due", "reviewing", "system_mastered", "manual_mastered", "reopen_suggested"}


def _answer(value: str) -> str:
    """Normalize choice answers without changing source data."""
    return "".join(clean_text(value).upper().replace("，", ",").split(","))


def _json(value: str | None, fallback: Any) -> Any:
    try:
        parsed = json.loads(value or "")
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


class LearningPracticeService:
    def __init__(self, repository: LearningCenterRepository | None = None) -> None:
        self.repository = repository or LearningCenterRepository()

    @staticmethod
    def _clean_choices(values: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(clean_text(value) for value in values if clean_text(value)))

    def _scope(
        self,
        *,
        project_id: str,
        module_id: str | None,
        knowledge_point_id: str | None,
        question_types: Iterable[str],
        difficulty: str | None,
        status: str | None,
    ) -> tuple[list[str], list[Any], dict[str, Any]]:
        types = self._clean_choices(question_types)
        normalized_difficulty = clean_text(difficulty or "")
        normalized_status = clean_text(status or "")
        if normalized_status and normalized_status not in _WRONG_STATES | {"unseen", "wrong"}:
            raise LearningCenterValidationError("Unsupported practice status filter")

        where = ["q.project_id = ?"]
        params: list[Any] = [project_id]
        if module_id:
            where.append("q.module_id = ?")
            params.append(module_id)
        if knowledge_point_id:
            where.append(
                "EXISTS (SELECT 1 FROM question_knowledge_points qkp "
                "WHERE qkp.question_id = q.id AND qkp.knowledge_point_id = ?)"
            )
            params.append(knowledge_point_id)
        if types:
            where.append(f"q.question_type IN ({','.join('?' for _ in types)})")
            params.extend(types)
        if normalized_difficulty:
            where.append("q.difficulty = ?")
            params.append(normalized_difficulty)
        if normalized_status == "unseen":
            # "未作答/未抽过": exclude anything already graded OR already placed in a
            # practice session. Users abandon sessions without submitting; those
            # questions must not reappear as "new" on the next compose.
            where.append(
                "NOT EXISTS (SELECT 1 FROM attempts a WHERE a.question_id = q.id) "
                "AND NOT EXISTS (SELECT 1 FROM practice_session_items psi WHERE psi.question_id = q.id)"
            )
        elif normalized_status == "wrong":
            where.append("EXISTS (SELECT 1 FROM wrong_question_states w WHERE w.question_id = q.id AND w.wrong_count > 0)")
        elif normalized_status:
            where.append("EXISTS (SELECT 1 FROM wrong_question_states w WHERE w.question_id = q.id AND w.state = ?)")
            params.append(normalized_status)
        return where, params, {
            "module_id": module_id,
            "knowledge_point_id": knowledge_point_id,
            "question_types": types,
            "difficulty": normalized_difficulty or None,
            "status": normalized_status or None,
        }

    def propose(
        self,
        *,
        project_id: str,
        module_id: str | None = None,
        knowledge_point_id: str | None = None,
        question_types: Iterable[str] = (),
        difficulty: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 200))
        where, params, filters = self._scope(
            project_id=project_id,
            module_id=module_id,
            knowledge_point_id=knowledge_point_id,
            question_types=question_types,
            difficulty=difficulty,
            status=status,
        )
        clause = " AND ".join(where)
        with self.repository._connect() as conn:
            self.repository._require_project(conn, project_id)
            candidate_count = int(conn.execute(f"SELECT COUNT(*) FROM questions q WHERE {clause}", params).fetchone()[0])
            # Prefer never-drawn, then never-attempted, then least-attempted,
            # then oldest last attempt. RANDOM() only breaks true ties so the
            # same scope does not freeze on fixed first-N by id.
            rows = conn.execute(
                f"""SELECT q.id, q.question_type, q.stem, q.module_id, q.difficulty,
                           COALESCE(m.path, '') AS module_path,
                           COALESCE(stats.attempt_count, 0) AS attempt_count,
                           stats.last_attempt_at AS last_attempt_at,
                           COALESCE(drawn.drawn_count, 0) AS drawn_count
                    FROM questions q
                    LEFT JOIN content_modules m ON m.id = q.module_id
                    LEFT JOIN (
                        SELECT question_id,
                               COUNT(*) AS attempt_count,
                               MAX(submitted_at) AS last_attempt_at
                        FROM attempts
                        GROUP BY question_id
                    ) stats ON stats.question_id = q.id
                    LEFT JOIN (
                        SELECT question_id, COUNT(*) AS drawn_count
                        FROM practice_session_items
                        GROUP BY question_id
                    ) drawn ON drawn.question_id = q.id
                    WHERE {clause}
                    ORDER BY COALESCE(drawn.drawn_count, 0) ASC,
                             COALESCE(stats.attempt_count, 0) ASC,
                             COALESCE(stats.last_attempt_at, 0) ASC,
                             RANDOM()
                    LIMIT ?""",
                [*params, limit],
            ).fetchall()
            composition_rows = conn.execute(
                f"""SELECT q.question_type, q.difficulty, COALESCE(m.path, '未归类') AS module_path, COUNT(*) AS count
                    FROM questions q
                    LEFT JOIN content_modules m ON m.id = q.module_id
                    WHERE {clause}
                    GROUP BY q.question_type, q.difficulty, COALESCE(m.path, '未归类')""",
                params,
            ).fetchall()

        selected = [
            {
                "question_id": row["id"],
                "question_type": row["question_type"],
                "stem": row["stem"],
                "module_id": row["module_id"],
                "module_path": row["module_path"],
                "difficulty": row["difficulty"],
                "attempt_count": int(row["attempt_count"] or 0),
                "drawn_count": int(row["drawn_count"] or 0) if "drawn_count" in row.keys() else 0,
            }
            for row in rows
        ]
        types = Counter()
        difficulties = Counter()
        modules = Counter()
        for row in composition_rows:
            types[row["question_type"] or "other"] += row["count"]
            difficulties[row["difficulty"] or "unspecified"] += row["count"]
            modules[row["module_path"]] += row["count"]
        unseen_count = sum(1 for item in selected if item["attempt_count"] == 0)
        return {
            "project_id": project_id,
            "candidate_count": candidate_count,
            "selected_count": len(selected),
            "unseen_selected_count": unseen_count,
            "seen_selected_count": len(selected) - unseen_count,
            "filters": {**filters, "limit": limit},
            "composition": {
                "question_types": dict(types),
                "difficulties": dict(difficulties),
                "modules": dict(modules),
            },
            "questions": selected,
        }

    def _proposal_from_ids(
        self,
        *,
        project_id: str,
        question_ids: list[str],
        module_id: str | None = None,
        knowledge_point_id: str | None = None,
        question_types: Iterable[str] = (),
        difficulty: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Build a proposal that pins the exact confirmed question set."""
        ordered_ids = list(dict.fromkeys(clean_text(qid) for qid in question_ids if clean_text(qid)))
        if not ordered_ids:
            raise LearningCenterValidationError("question_ids must not be empty")
        if len(ordered_ids) > 200:
            raise LearningCenterValidationError("question_ids must not exceed 200 items")
        types = self._clean_choices(question_types)
        filters = {
            "module_id": module_id,
            "knowledge_point_id": knowledge_point_id,
            "question_types": types,
            "difficulty": clean_text(difficulty or "") or None,
            "status": clean_text(status or "") or None,
            "limit": max(1, min(int(limit), 200)),
            "pinned_question_ids": ordered_ids,
        }
        placeholders = ",".join("?" for _ in ordered_ids)
        with self.repository._connect() as conn:
            self.repository._require_project(conn, project_id)
            rows = conn.execute(
                f"""SELECT q.id, q.question_type, q.stem, q.module_id, q.difficulty,
                           COALESCE(m.path, '') AS module_path,
                           COALESCE(stats.attempt_count, 0) AS attempt_count
                    FROM questions q
                    LEFT JOIN content_modules m ON m.id = q.module_id
                    LEFT JOIN (
                        SELECT question_id, COUNT(*) AS attempt_count
                        FROM attempts GROUP BY question_id
                    ) stats ON stats.question_id = q.id
                    WHERE q.project_id = ? AND q.id IN ({placeholders})""",
                [project_id, *ordered_ids],
            ).fetchall()
            by_id = {row["id"]: row for row in rows}
            missing = [qid for qid in ordered_ids if qid not in by_id]
            if missing:
                raise LearningCenterValidationError(
                    f"Unknown or out-of-project question_ids: {', '.join(missing[:5])}"
                )
            selected = []
            for qid in ordered_ids:
                row = by_id[qid]
                selected.append({
                    "question_id": row["id"],
                    "question_type": row["question_type"],
                    "stem": row["stem"],
                    "module_id": row["module_id"],
                    "module_path": row["module_path"],
                    "difficulty": row["difficulty"],
                    "attempt_count": int(row["attempt_count"] or 0),
                })
        unseen = sum(1 for item in selected if item["attempt_count"] == 0)
        types_c, diffs, mods = Counter(), Counter(), Counter()
        for item in selected:
            types_c[item["question_type"] or "other"] += 1
            diffs[item["difficulty"] or "unspecified"] += 1
            mods[item["module_path"] or "未归类"] += 1
        return {
            "project_id": project_id,
            "candidate_count": len(selected),
            "selected_count": len(selected),
            "unseen_selected_count": unseen,
            "seen_selected_count": len(selected) - unseen,
            "filters": filters,
            "composition": {
                "question_types": dict(types_c),
                "difficulties": dict(diffs),
                "modules": dict(mods),
            },
            "questions": selected,
        }

    def start(
        self,
        *,
        project_id: str,
        mode: str,
        title: str = "",
        module_id: str | None = None,
        knowledge_point_id: str | None = None,
        question_types: Iterable[str] = (),
        difficulty: str | None = None,
        status: str | None = None,
        limit: int = 20,
        time_budget_minutes: int | None = None,
        question_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        if mode not in {"learning", "exam"}:
            raise LearningCenterValidationError("mode must be learning or exam")
        if time_budget_minutes is not None and not 1 <= int(time_budget_minutes) <= 600:
            raise LearningCenterValidationError("time budget must be between 1 and 600 minutes")
        pinned = [clean_text(qid) for qid in (question_ids or []) if clean_text(qid)]
        if pinned:
            proposal = self._proposal_from_ids(
                project_id=project_id,
                question_ids=pinned,
                module_id=module_id,
                knowledge_point_id=knowledge_point_id,
                question_types=question_types,
                difficulty=difficulty,
                status=status,
                limit=limit if limit else len(pinned),
            )
        else:
            proposal = self.propose(
                project_id=project_id,
                module_id=module_id,
                knowledge_point_id=knowledge_point_id,
                question_types=question_types,
                difficulty=difficulty,
                status=status,
                limit=limit,
            )
        if not proposal["questions"]:
            raise LearningCenterValidationError("No questions match the selected scope")

        now = time.time()
        session_id = self.repository._new_id("session")
        filters = {
            **proposal["filters"],
            "time_budget_minutes": time_budget_minutes,
            "paused_at": None,
            "paused_total_seconds": 0,
        }
        with self.repository._connect() as conn:
            conn.execute(
                """INSERT INTO practice_sessions
                   (id, project_id, mode, title, status, filters_json, proposal_json, started_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)""",
                (session_id, project_id, mode, clean_text(title), canonical_json(filters), canonical_json(proposal), now, now, now),
            )
            conn.executemany(
                """INSERT INTO practice_session_items (id, session_id, question_id, position, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (self.repository._new_id("session_item"), session_id, question["question_id"], position, now)
                    for position, question in enumerate(proposal["questions"], 1)
                ],
            )
        return self.get(session_id)

    def _questions(self, conn: Any, session_id: str, mode: str, *, reveal: bool) -> list[dict[str, Any]]:
        rows = conn.execute(
            """SELECT i.*, q.question_type, q.stem, q.source_answer, q.source_explanation, q.source_id,
                       (SELECT json_group_object(option_key, content) FROM question_options o WHERE o.question_id = q.id) AS options_json,
                       (
                         SELECT d.output_json FROM ai_derivations d
                         WHERE d.question_id = q.id
                           AND d.derivation_type IN (
                             'explanation', 'source_explanation', 'ai_explanation',
                             'missing_explanation', 'enrich_explanation'
                           )
                         ORDER BY
                           CASE d.review_status WHEN 'accepted' THEN 0 WHEN 'unreviewed' THEN 1 ELSE 2 END,
                           d.created_at DESC
                         LIMIT 1
                       ) AS ai_explanation_json,
                       (
                         SELECT d.provider FROM ai_derivations d
                         WHERE d.question_id = q.id
                           AND d.derivation_type IN (
                             'explanation', 'source_explanation', 'ai_explanation',
                             'missing_explanation', 'enrich_explanation'
                           )
                         ORDER BY
                           CASE d.review_status WHEN 'accepted' THEN 0 WHEN 'unreviewed' THEN 1 ELSE 2 END,
                           d.created_at DESC
                         LIMIT 1
                       ) AS ai_provider,
                       (
                         SELECT d.model FROM ai_derivations d
                         WHERE d.question_id = q.id
                           AND d.derivation_type IN (
                             'explanation', 'source_explanation', 'ai_explanation',
                             'missing_explanation', 'enrich_explanation'
                           )
                         ORDER BY
                           CASE d.review_status WHEN 'accepted' THEN 0 WHEN 'unreviewed' THEN 1 ELSE 2 END,
                           d.created_at DESC
                         LIMIT 1
                       ) AS ai_model
                FROM practice_session_items i
                JOIN questions q ON q.id = i.question_id
                WHERE i.session_id = ?
                ORDER BY i.position""",
            (session_id,),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            eliminated = [
                eliminated_row[0]
                for eliminated_row in conn.execute(
                    "SELECT option_key FROM attempt_option_eliminations WHERE session_item_id = ? ORDER BY option_key",
                    (row["id"],),
                )
            ]
            item = {
                "id": row["id"],
                "question_id": row["question_id"],
                "position": row["position"],
                "question_type": row["question_type"],
                "stem": row["stem"],
                "options": _json(row["options_json"], {}),
                "user_answer": row["user_answer"],
                "confidence": row["confidence"],
                "marked_for_review": bool(row["marked_for_review"]),
                "eliminated_option_keys": eliminated,
                "elapsed_seconds": row["elapsed_seconds"],
                "submitted_at": row["submitted_at"],
                "is_correct": None if row["is_correct"] is None else bool(row["is_correct"]),
            }
            # Never return answer/explanation fields in an active or paused exam.
            if reveal or (mode == "learning" and row["submitted_at"] is not None):
                source_explanation = clean_text(row["source_explanation"] or "")
                ai_payload = _json(row["ai_explanation_json"], {})
                ai_explanation = ""
                if isinstance(ai_payload, dict):
                    ai_explanation = clean_text(
                        str(
                            ai_payload.get("explanation")
                            or ai_payload.get("source_explanation")
                            or ai_payload.get("text")
                            or ai_payload.get("content")
                            or ai_payload.get("value")
                            or ""
                        )
                    )
                elif isinstance(ai_payload, str):
                    ai_explanation = clean_text(ai_payload)
                if not ai_explanation and row["ai_explanation_json"]:
                    raw = str(row["ai_explanation_json"]).strip().strip('"')
                    ai_explanation = clean_text(raw)
                explanation = source_explanation or ai_explanation
                provenance_kind = "source_original" if source_explanation else ("ai_generated" if ai_explanation else "source_original")
                item.update(
                    {
                        "source_answer": row["source_answer"],
                        "source_explanation": explanation,
                        "ai_explanation": ai_explanation or None,
                        "provenance": {
                            "source_id": row["source_id"],
                            "kind": provenance_kind,
                            "provider": row["ai_provider"] if provenance_kind == "ai_generated" else None,
                            "model": row["ai_model"] if provenance_kind == "ai_generated" else None,
                        },
                    }
                )
            result.append(item)
        return result

    def get(self, session_id: str) -> dict[str, Any]:
        with self.repository._connect() as conn:
            session = conn.execute("SELECT * FROM practice_sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                raise LearningCenterNotFoundError("Practice session not found")
            return {
                "id": session["id"],
                "project_id": session["project_id"],
                "mode": session["mode"],
                "title": session["title"],
                "status": session["status"],
                "filters": _json(session["filters_json"], {}),
                "proposal": _json(session["proposal_json"], {}),
                "started_at": session["started_at"],
                "completed_at": session["completed_at"],
                "questions": self._questions(conn, session_id, session["mode"], reveal=session["status"] == "completed"),
            }

    @staticmethod
    def _validate_item(item: dict[str, Any]) -> tuple[str, str, str, bool, float | None, list[str]]:
        item_id = clean_text(str(item.get("id", "")))
        if not item_id:
            raise LearningCenterValidationError("Session item id is required")
        confidence = clean_text(str(item.get("confidence", "")))
        if confidence not in _CONFIDENCE:
            raise LearningCenterValidationError("Unsupported confidence value")
        elapsed = item.get("elapsed_seconds")
        if elapsed is not None:
            try:
                elapsed = float(elapsed)
            except (TypeError, ValueError) as exc:
                raise LearningCenterValidationError("elapsed_seconds must be numeric") from exc
            if not 0 <= elapsed <= 86_400:
                raise LearningCenterValidationError("elapsed_seconds must be between 0 and 86400")
        eliminated = sorted(set(clean_text(str(value)).upper() for value in item.get("eliminated_option_keys", []) if clean_text(str(value))))
        return item_id, clean_text(str(item.get("user_answer", ""))), confidence, bool(item.get("marked_for_review", False)), elapsed, eliminated

    def _replace_eliminations(self, conn: Any, *, session_item_id: str, option_keys: list[str], now: float) -> None:
        conn.execute("DELETE FROM attempt_option_eliminations WHERE session_item_id = ?", (session_item_id,))
        if option_keys:
            conn.executemany(
                """INSERT INTO attempt_option_eliminations (id, session_item_id, option_key, created_at)
                   VALUES (?, ?, ?, ?)""",
                [(self.repository._new_id("elimination"), session_item_id, key, now) for key in option_keys],
            )

    def autosave(self, session_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        now = time.time()
        with self.repository._connect() as conn:
            session = conn.execute("SELECT status FROM practice_sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                raise LearningCenterNotFoundError("Practice session not found")
            if session["status"] != "active":
                raise LearningCenterValidationError("Only active sessions can be autosaved")
            for raw_item in items:
                item_id, user_answer, confidence, marked, elapsed, eliminated = self._validate_item(raw_item)
                row = conn.execute(
                    "SELECT question_id FROM practice_session_items WHERE id = ? AND session_id = ?",
                    (item_id, session_id),
                ).fetchone()
                if row is None:
                    raise LearningCenterValidationError("Session item does not belong to this session")
                conn.execute(
                    """UPDATE practice_session_items
                       SET user_answer = ?, confidence = ?, marked_for_review = ?, elapsed_seconds = ?, updated_at = ?
                       WHERE id = ?""",
                    (user_answer, confidence, int(marked), elapsed, now, item_id),
                )
                self._replace_eliminations(conn, session_item_id=item_id, option_keys=eliminated, now=now)
            conn.execute("UPDATE practice_sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        return self.get(session_id)

    def _update_wrong_state(self, conn: Any, *, project_id: str, question_id: str, is_correct: int | None, now: float) -> None:
        if is_correct is None:
            return
        current = conn.execute("SELECT * FROM wrong_question_states WHERE question_id = ?", (question_id,)).fetchone()
        if current is None:
            conn.execute(
                """INSERT INTO wrong_question_states
                   (question_id, project_id, state, wrong_count, correct_after_error_count, first_wrong_at, last_wrong_at, last_attempt_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    question_id,
                    project_id,
                    "review_due" if not is_correct else "new",
                    0 if is_correct else 1,
                    0,
                    None if is_correct else now,
                    None if is_correct else now,
                    now,
                    now,
                ),
            )
            return
        if is_correct:
            conn.execute(
                """UPDATE wrong_question_states
                   SET correct_after_error_count = correct_after_error_count + CASE WHEN wrong_count > 0 THEN 1 ELSE 0 END,
                       last_attempt_at = ?, updated_at = ? WHERE question_id = ?""",
                (now, now, question_id),
            )
        else:
            conn.execute(
                """UPDATE wrong_question_states
                   SET state = 'review_due', wrong_count = wrong_count + 1,
                       first_wrong_at = COALESCE(first_wrong_at, ?), last_wrong_at = ?, last_attempt_at = ?, updated_at = ?
                   WHERE question_id = ?""",
                (now, now, now, now, question_id),
            )

    def submit(self, session_id: str, answers: list[dict[str, Any]], *, finish: bool = False) -> dict[str, Any]:
        now = time.time()
        completed = False
        with self.repository._connect() as conn:
            session = conn.execute("SELECT * FROM practice_sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                raise LearningCenterNotFoundError("Practice session not found")
            if session["status"] == "completed":
                return self.get(session_id)
            if session["status"] != "active":
                raise LearningCenterValidationError("Resume the session before submitting answers")
            for raw_answer in answers:
                item_id, user_answer, confidence, marked, elapsed, eliminated = self._validate_item(raw_answer)
                row = conn.execute(
                    """SELECT i.*, q.source_answer FROM practice_session_items i
                       JOIN questions q ON q.id = i.question_id WHERE i.id = ? AND i.session_id = ?""",
                    (item_id, session_id),
                ).fetchone()
                if row is None:
                    raise LearningCenterValidationError("Session item does not belong to this session")
                if row["submitted_at"] is not None:
                    continue  # idempotent duplicate submission
                source_answer = _answer(row["source_answer"])
                is_correct: int | None = None if not source_answer else int(_answer(user_answer) == source_answer)
                conn.execute(
                    """UPDATE practice_session_items
                       SET user_answer = ?, confidence = ?, marked_for_review = ?, elapsed_seconds = ?,
                           is_correct = ?, submitted_at = ?, updated_at = ? WHERE id = ?""",
                    (user_answer, confidence, int(marked), elapsed, is_correct, now, now, item_id),
                )
                attempt_id = self.repository._new_id("attempt")
                conn.execute(
                    """INSERT INTO attempts
                       (id, session_id, session_item_id, question_id, user_answer, is_correct, confidence,
                        judgment_json, elapsed_seconds, submitted_at, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        attempt_id,
                        session_id,
                        item_id,
                        row["question_id"],
                        user_answer,
                        is_correct,
                        confidence,
                        canonical_json({"judged_by": "source_answer", "source_available": bool(source_answer)}),
                        elapsed,
                        now,
                        now,
                    ),
                )
                self._replace_eliminations(conn, session_item_id=item_id, option_keys=eliminated, now=now)
                LearningMasteryService(self.repository).record_attempt_in_connection(conn, project_id=session["project_id"], question_id=row["question_id"], attempt_id=attempt_id, is_correct=is_correct, confidence=confidence, now=now)
            if finish:
                # Grade remaining autosaved answers that the client forgot to include.
                pending = conn.execute(
                    """SELECT i.*, q.source_answer FROM practice_session_items i
                       JOIN questions q ON q.id = i.question_id
                       WHERE i.session_id = ? AND i.submitted_at IS NULL
                         AND TRIM(COALESCE(i.user_answer, '')) != ''""",
                    (session_id,),
                ).fetchall()
                for row in pending:
                    user_answer = clean_text(row["user_answer"] or "")
                    confidence = clean_text(row["confidence"] or "")
                    if confidence not in _CONFIDENCE:
                        confidence = ""
                    source_answer = _answer(row["source_answer"])
                    is_correct: int | None = None if not source_answer else int(_answer(user_answer) == source_answer)
                    conn.execute(
                        """UPDATE practice_session_items
                           SET is_correct = ?, submitted_at = ?, updated_at = ? WHERE id = ?""",
                        (is_correct, now, now, row["id"]),
                    )
                    attempt_id = self.repository._new_id("attempt")
                    conn.execute(
                        """INSERT INTO attempts
                           (id, session_id, session_item_id, question_id, user_answer, is_correct, confidence,
                            judgment_json, elapsed_seconds, submitted_at, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            attempt_id,
                            session_id,
                            row["id"],
                            row["question_id"],
                            user_answer,
                            is_correct,
                            confidence,
                            canonical_json({"judged_by": "source_answer", "source_available": bool(source_answer), "promoted_from_autosave": True}),
                            row["elapsed_seconds"],
                            now,
                            now,
                        ),
                    )
                    LearningMasteryService(self.repository).record_attempt_in_connection(
                        conn,
                        project_id=session["project_id"],
                        question_id=row["question_id"],
                        attempt_id=attempt_id,
                        is_correct=is_correct,
                        confidence=confidence,
                        now=now,
                    )
                completed = True
                conn.execute(
                    "UPDATE practice_sessions SET status = 'completed', completed_at = ?, updated_at = ? WHERE id = ?",
                    (now, now, session_id),
                )
        response = self.get(session_id)
        if completed:
            self._persist_report(session_id, response)
            # Advisory generation must never make a completed practice session fail.
            try:
                from .recommendations import LearningRecommendationService
                LearningRecommendationService(self.repository).generate(project_id=response["project_id"], trigger="practice_completion")
            except Exception:
                pass
        return response

    def pause(self, session_id: str) -> dict[str, Any]:
        now = time.time()
        with self.repository._connect() as conn:
            session = conn.execute("SELECT * FROM practice_sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                raise LearningCenterNotFoundError("Practice session not found")
            if session["status"] == "completed":
                raise LearningCenterValidationError("Completed sessions cannot be paused")
            filters = _json(session["filters_json"], {})
            if session["status"] == "paused":
                return self.get(session_id)
            filters["paused_at"] = now
            conn.execute("UPDATE practice_sessions SET status = 'paused', filters_json = ?, updated_at = ? WHERE id = ?", (canonical_json(filters), now, session_id))
        return self.get(session_id)

    def resume(self, session_id: str) -> dict[str, Any]:
        now = time.time()
        with self.repository._connect() as conn:
            session = conn.execute("SELECT * FROM practice_sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                raise LearningCenterNotFoundError("Practice session not found")
            if session["status"] == "completed":
                raise LearningCenterValidationError("Completed sessions cannot be resumed")
            filters = _json(session["filters_json"], {})
            paused_at = filters.get("paused_at")
            if isinstance(paused_at, (int, float)):
                filters["paused_total_seconds"] = max(0, float(filters.get("paused_total_seconds") or 0) + now - paused_at)
            filters["paused_at"] = None
            conn.execute("UPDATE practice_sessions SET status = 'active', filters_json = ?, updated_at = ? WHERE id = ?", (canonical_json(filters), now, session_id))
        return self.get(session_id)

    def set_bookmark(self, *, project_id: str, question_id: str, bookmarked: bool, note: str = "") -> dict[str, Any] | None:
        now = time.time()
        with self.repository._connect() as conn:
            question = conn.execute("SELECT project_id FROM questions WHERE id = ?", (question_id,)).fetchone()
            if question is None:
                raise LearningCenterNotFoundError("Question not found")
            if question["project_id"] != project_id:
                raise LearningCenterValidationError("Bookmark question must belong to the project")
            if not bookmarked:
                conn.execute("DELETE FROM bookmarks WHERE question_id = ?", (question_id,))
                return None
            existing = conn.execute("SELECT id FROM bookmarks WHERE question_id = ?", (question_id,)).fetchone()
            if existing:
                conn.execute("UPDATE bookmarks SET note = ?, updated_at = ? WHERE question_id = ?", (clean_text(note), now, question_id))
            else:
                conn.execute(
                    """INSERT INTO bookmarks (id, project_id, question_id, note, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (self.repository._new_id("bookmark"), project_id, question_id, clean_text(note), now, now),
                )
        return self.get_bookmark(question_id)

    def get_bookmark(self, question_id: str) -> dict[str, Any] | None:
        with self.repository._connect() as conn:
            row = conn.execute("SELECT * FROM bookmarks WHERE question_id = ?", (question_id,)).fetchone()
            return None if row is None else dict(row)

    def discussion(self, *, project_id: str, question_id: str) -> dict[str, Any]:
        with self.repository._connect() as conn:
            question = conn.execute("SELECT project_id FROM questions WHERE id = ?", (question_id,)).fetchone()
            if question is None:
                raise LearningCenterNotFoundError("Question not found")
            if question["project_id"] != project_id:
                raise LearningCenterValidationError("Discussion question must belong to the project")
            discussion = conn.execute(
                "SELECT * FROM question_discussions WHERE project_id = ? AND question_id = ? ORDER BY updated_at DESC LIMIT 1",
                (project_id, question_id),
            ).fetchone()
            if discussion is None:
                return {"id": None, "project_id": project_id, "question_id": question_id, "messages": []}
            messages = [dict(row) for row in conn.execute("SELECT * FROM question_discussion_messages WHERE discussion_id = ? ORDER BY created_at", (discussion["id"],))]
            return {"id": discussion["id"], "project_id": project_id, "question_id": question_id, "title": discussion["title"], "messages": messages}


    def question_discussion_context(self, *, project_id: str, question_id: str) -> dict[str, Any]:
        """Load a single question with options + best available explanation for AI tutoring."""
        with self.repository._connect() as conn:
            row = conn.execute(
                """SELECT q.*, COALESCE(m.path, '') AS module_path,
                          (SELECT json_group_object(option_key, content)
                             FROM question_options o WHERE o.question_id = q.id) AS options_json,
                          (
                            SELECT d.output_json FROM ai_derivations d
                            WHERE d.question_id = q.id
                              AND d.derivation_type IN (
                                'explanation', 'source_explanation', 'ai_explanation',
                                'missing_explanation', 'enrich_explanation'
                              )
                            ORDER BY
                              CASE d.review_status WHEN 'accepted' THEN 0 WHEN 'unreviewed' THEN 1 ELSE 2 END,
                              d.created_at DESC
                            LIMIT 1
                          ) AS ai_explanation_json
                   FROM questions q
                   LEFT JOIN content_modules m ON m.id = q.module_id
                   WHERE q.id = ? AND q.project_id = ?""",
                (question_id, project_id),
            ).fetchone()
            if row is None:
                raise LearningCenterNotFoundError("Question not found")
            options = _json(row["options_json"], {})
            source_explanation = clean_text(row["source_explanation"] or "")
            ai_payload = _json(row["ai_explanation_json"], {})
            ai_explanation = ""
            if isinstance(ai_payload, dict):
                ai_explanation = clean_text(
                    str(
                        ai_payload.get("explanation")
                        or ai_payload.get("source_explanation")
                        or ai_payload.get("text")
                        or ai_payload.get("content")
                        or ai_payload.get("value")
                        or ""
                    )
                )
            elif isinstance(ai_payload, str):
                ai_explanation = clean_text(ai_payload)
            return {
                "id": row["id"],
                "project_id": row["project_id"],
                "module_path": row["module_path"],
                "question_type": row["question_type"],
                "stem": row["stem"],
                "options": options if isinstance(options, dict) else {},
                "source_answer": row["source_answer"],
                "source_explanation": source_explanation,
                "ai_explanation": ai_explanation,
                "explanation": source_explanation or ai_explanation or "题库暂未提供解析。",
            }

    def add_discussion_message(
        self,
        *,
        project_id: str,
        question_id: str,
        content: str,
        role: str = "user",
        provider: str = "",
        model: str = "",
    ) -> dict[str, Any]:
        if role not in {"system", "user", "assistant"}:
            raise LearningCenterValidationError("Unsupported discussion role")
        text = clean_text(content)
        if not text:
            raise LearningCenterValidationError("Discussion content is required")
        now = time.time()
        with self.repository._connect() as conn:
            question = conn.execute("SELECT project_id FROM questions WHERE id = ?", (question_id,)).fetchone()
            if question is None:
                raise LearningCenterNotFoundError("Question not found")
            if question["project_id"] != project_id:
                raise LearningCenterValidationError("Discussion question must belong to the project")
            discussion = conn.execute(
                "SELECT * FROM question_discussions WHERE project_id = ? AND question_id = ? ORDER BY updated_at DESC LIMIT 1",
                (project_id, question_id),
            ).fetchone()
            if discussion is None:
                discussion_id = self.repository._new_id("discussion")
                conn.execute(
                    """INSERT INTO question_discussions (id, project_id, question_id, title, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (discussion_id, project_id, question_id, "题目讨论", now, now),
                )
            else:
                discussion_id = discussion["id"]
                conn.execute("UPDATE question_discussions SET updated_at = ? WHERE id = ?", (now, discussion_id))
            conn.execute(
                """INSERT INTO question_discussion_messages
                   (id, discussion_id, role, content, provider, model, metadata_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, '{}', ?)""",
                (
                    self.repository._new_id("discussion_message"),
                    discussion_id,
                    role,
                    text,
                    clean_text(provider),
                    clean_text(model),
                    now,
                ),
            )
        return self.discussion(project_id=project_id, question_id=question_id)

    def similar(self, *, project_id: str, question_id: str, limit: int = 5) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 20))
        with self.repository._connect() as conn:
            source = conn.execute("SELECT * FROM questions WHERE id = ? AND project_id = ?", (question_id, project_id)).fetchone()
            if source is None:
                raise LearningCenterNotFoundError("Question not found")
            rows = conn.execute(
                """SELECT id, stem, question_type, difficulty, module_id FROM questions
                   WHERE project_id = ? AND id != ? AND question_type = ?
                   ORDER BY CASE WHEN module_id = ? THEN 0 ELSE 1 END, id LIMIT ?""",
                (project_id, question_id, source["question_type"], source["module_id"], limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def report(self, session_id: str) -> dict[str, Any]:
        with self.repository._connect() as conn:
            session = conn.execute("SELECT * FROM practice_sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                raise LearningCenterNotFoundError("Practice session not found")
            item_rows = conn.execute(
                """SELECT i.*, q.question_type, q.module_id FROM practice_session_items i
                   JOIN questions q ON q.id = i.question_id WHERE i.session_id = ? ORDER BY i.position""",
                (session_id,),
            ).fetchall()
            total = len(item_rows)
            answered = sum(row["submitted_at"] is not None for row in item_rows)
            graded = [row for row in item_rows if row["is_correct"] is not None]
            correct = sum(bool(row["is_correct"]) for row in graded)
            confidence = {key: {"count": 0, "correct": 0} for key in sorted(_CONFIDENCE)}
            module_impact: dict[str, dict[str, int]] = {}
            knowledge_impact: dict[str, dict[str, int]] = {}
            for row in item_rows:
                confidence[row["confidence"]]["count"] += 1
                confidence[row["confidence"]]["correct"] += int(bool(row["is_correct"]))
                module_key = row["module_id"] or "unassigned"
                module_impact.setdefault(module_key, {"total": 0, "wrong": 0})["total"] += 1
                module_impact[module_key]["wrong"] += int(row["is_correct"] == 0)
                for kp in conn.execute("SELECT knowledge_point_id FROM question_knowledge_points WHERE question_id = ?", (row["question_id"],)):
                    bucket = knowledge_impact.setdefault(kp["knowledge_point_id"], {"total": 0, "wrong": 0})
                    bucket["total"] += 1
                    bucket["wrong"] += int(row["is_correct"] == 0)
            weak_kps = [key for key, value in knowledge_impact.items() if value["wrong"]]
            wrong = max(0, answered - correct) if graded else sum(1 for row in item_rows if row["is_correct"] == 0)
            advisory = (
                f"规则建议：本次已作答 {answered}/{total}，正确 {correct}。"
                + (f" 有 {wrong} 道错题，建议先复盘错题再开下一组。" if wrong else " 正确率不错，可用相似题巩固。")
            )
            return {
                "session_id": session_id,
                "project_id": session["project_id"],
                "mode": session["mode"],
                "status": session["status"],
                "total": total,
                "answered": answered,
                "graded": len(graded),
                "correct": correct,
                "accuracy": (correct / len(graded)) if graded else None,
                "confidence": {key: {**value, "accuracy": value["correct"] / value["count"] if value["count"] else None} for key, value in confidence.items()},
                "module_impact": module_impact,
                "knowledge_point_impact": knowledge_impact,
                "ai_advisory": {
                    "text": advisory,
                    "provider": "rules",
                    "model": "session-report-v1",
                    "generated": False,
                    "label": "规则建议（非模型生成）",
                },
                "follow_up_actions": [
                    {"type": "review_wrong", "label": "去复习错题", "href": "/space/learning-center/review"},
                    {"type": "start_unseen", "label": "再练一组未作答", "href": "/space/learning-center/practice?status=unseen"},
                    {"type": "open_recommendations", "label": "查看学习建议", "href": "/space/learning-center/recommendations"},
                ],
            }

    def _persist_report(self, session_id: str, session: dict[str, Any]) -> None:
        report = self.report(session_id)
        now = time.time()
        with self.repository._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM learning_reports WHERE session_id = ? AND report_type = 'practice_session' ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if existing:
                conn.execute("UPDATE learning_reports SET summary_json = ?, updated_at = ? WHERE id = ?", (canonical_json(report), now, existing["id"]))
            else:
                conn.execute(
                    """INSERT INTO learning_reports
                       (id, project_id, session_id, report_type, summary_json, provider, model, prompt_version, created_at, updated_at)
                       VALUES (?, ?, ?, 'practice_session', ?, '', '', '', ?, ?)""",
                    (self.repository._new_id("report"), session["project_id"], session_id, canonical_json(report), now, now),
                )

    def list_resumable_sessions(self, *, project_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Sessions that still have progress and can be continued."""
        limit = max(1, min(int(limit), 100))
        where = ["s.status IN ('active', 'paused')"]
        params: list[Any] = []
        if project_id:
            where.append("s.project_id = ?")
            params.append(project_id)
        # Prefer sessions with any draft/submitted answer; hide pure zombies.
        where.append(
            "EXISTS (SELECT 1 FROM practice_session_items i WHERE i.session_id = s.id "
            "AND (i.submitted_at IS NOT NULL OR TRIM(COALESCE(i.user_answer, '')) != ''))"
        )
        clause = " AND ".join(where)
        with self.repository._connect() as conn:
            rows = conn.execute(
                f"""SELECT s.id, s.project_id, p.name AS project_name, s.mode, s.title, s.status,
                           s.started_at, s.updated_at,
                           COUNT(i.id) AS total,
                           SUM(CASE WHEN i.submitted_at IS NOT NULL THEN 1 ELSE 0 END) AS answered,
                           SUM(CASE WHEN TRIM(COALESCE(i.user_answer, '')) != '' THEN 1 ELSE 0 END) AS drafted
                    FROM practice_sessions s
                    JOIN learning_projects p ON p.id = s.project_id
                    LEFT JOIN practice_session_items i ON i.session_id = s.id
                    WHERE {clause}
                    GROUP BY s.id
                    ORDER BY s.updated_at DESC
                    LIMIT ?""",
                [*params, limit],
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "project_id": row["project_id"],
                    "project_name": row["project_name"],
                    "mode": row["mode"],
                    "title": row["title"],
                    "status": row["status"],
                    "started_at": row["started_at"],
                    "updated_at": row["updated_at"],
                    "total": int(row["total"] or 0),
                    "answered": int(row["answered"] or 0),
                    "drafted": int(row["drafted"] or 0),
                }
                for row in rows
            ]

    def archive_stale_sessions(self, *, older_than_seconds: float = 24 * 3600, only_empty: bool = True) -> dict[str, Any]:
        """Mark abandoned empty/old active sessions so dashboards stay trustworthy."""
        now = time.time()
        cutoff = now - max(0.0, float(older_than_seconds))
        with self.repository._connect() as conn:
            if only_empty:
                rows = conn.execute(
                    """SELECT s.id FROM practice_sessions s
                       WHERE s.status = 'active' AND s.started_at < ?
                         AND NOT EXISTS (
                           SELECT 1 FROM practice_session_items i
                           WHERE i.session_id = s.id
                             AND (i.submitted_at IS NOT NULL OR TRIM(COALESCE(i.user_answer, '')) != '')
                         )""",
                    (cutoff,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id FROM practice_sessions WHERE status = 'active' AND started_at < ?",
                    (cutoff,),
                ).fetchall()
            ids = [row["id"] for row in rows]
            for session_id in ids:
                conn.execute(
                    "UPDATE practice_sessions SET status = 'abandoned', updated_at = ? WHERE id = ?",
                    (now, session_id),
                )
        return {"archived_count": len(ids), "older_than_seconds": older_than_seconds, "only_empty": only_empty}

