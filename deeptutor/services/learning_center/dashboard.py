"""Read-optimized, local-only dashboard queries for Learning Center v2."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .repository import LearningCenterRepository


class LearningCenterDashboardService:
    """Aggregate learning evidence without touching legacy exam-practice data."""

    def __init__(self, repository: LearningCenterRepository | None = None) -> None:
        self.repository = repository or LearningCenterRepository()

    @staticmethod
    def _day(value: datetime) -> str:
        return value.strftime("%Y-%m-%d")

    @staticmethod
    def _accuracy(correct: int | float, total: int | float) -> float | None:
        return round(float(correct) / float(total), 4) if total else None

    def overview(self) -> dict[str, Any]:
        with self.repository._connect() as conn:
            counts = conn.execute(
                """SELECT
                    (SELECT COUNT(*) FROM learning_projects) AS project_count,
                    (SELECT COUNT(*) FROM questions) AS question_count,
                    (SELECT COUNT(*) FROM attempts WHERE is_correct IS NOT NULL) AS attempt_count,
                    (SELECT COUNT(*) FROM attempts WHERE is_correct = 1) AS correct_count,
                    (SELECT COUNT(*) FROM wrong_question_states
                       WHERE state IN ('new','review_due','reviewing','reopen_suggested')) AS review_due_count,
                    (SELECT COUNT(*) FROM practice_sessions WHERE status = 'active') AS active_session_count"""
            ).fetchone()
            latest = conn.execute(
                """SELECT s.id, s.mode, s.title, s.started_at, s.completed_at, p.id AS project_id, p.name AS project_name,
                          COUNT(i.id) AS total, SUM(CASE WHEN i.submitted_at IS NOT NULL THEN 1 ELSE 0 END) AS answered,
                          SUM(CASE WHEN i.is_correct = 1 THEN 1 ELSE 0 END) AS correct
                     FROM practice_sessions s
                     JOIN learning_projects p ON p.id = s.project_id
                     LEFT JOIN practice_session_items i ON i.session_id = s.id
                 GROUP BY s.id
                 ORDER BY COALESCE(s.completed_at, s.started_at) DESC
                    LIMIT 1"""
            ).fetchone()
        result = dict(counts)
        result["accuracy"] = self._accuracy(result.pop("correct_count"), result["attempt_count"])
        result["last_session"] = None if latest is None else {
            "id": latest["id"], "mode": latest["mode"], "title": latest["title"],
            "started_at": latest["started_at"], "completed_at": latest["completed_at"],
            "project_id": latest["project_id"], "project_name": latest["project_name"],
            "total": int(latest["total"] or 0), "answered": int(latest["answered"] or 0),
            "accuracy": self._accuracy(int(latest["correct"] or 0), int(latest["answered"] or 0)),
        }
        return result

    def project_summaries(self) -> list[dict[str, Any]]:
        with self.repository._connect() as conn:
            rows = conn.execute(
                """SELECT p.id, p.name, p.kind, p.updated_at,
                          COUNT(DISTINCT q.id) AS question_count,
                          COUNT(DISTINCT a.id) FILTER (WHERE a.is_correct IS NOT NULL) AS attempt_count,
                          COUNT(DISTINCT a.id) FILTER (WHERE a.is_correct = 1) AS correct_count,
                          COUNT(DISTINCT w.question_id) FILTER (WHERE w.state IN ('new','review_due','reviewing','reopen_suggested')) AS review_due_count,
                          MAX(s.started_at) AS last_session_at
                     FROM learning_projects p
                     LEFT JOIN questions q ON q.project_id = p.id
                     LEFT JOIN attempts a ON a.question_id = q.id
                     LEFT JOIN wrong_question_states w ON w.project_id = p.id
                     LEFT JOIN practice_sessions s ON s.project_id = p.id
                 GROUP BY p.id
                 ORDER BY last_session_at DESC NULLS LAST, p.updated_at DESC, p.name COLLATE NOCASE"""
            ).fetchall()
        return [
            {
                "id": row["id"], "name": row["name"], "kind": row["kind"],
                "question_count": int(row["question_count"] or 0),
                "attempt_count": int(row["attempt_count"] or 0),
                "accuracy": self._accuracy(int(row["correct_count"] or 0), int(row["attempt_count"] or 0)),
                "review_due_count": int(row["review_due_count"] or 0),
                "last_session_at": row["last_session_at"],
            }
            for row in rows
        ]

    def trends(self, days: int = 30) -> list[dict[str, Any]]:
        days = max(1, min(int(days), 365))
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=days - 1)
        with self.repository._connect() as conn:
            rows = conn.execute(
                """SELECT strftime('%Y-%m-%d', submitted_at, 'unixepoch') AS day,
                          COUNT(*) AS attempts,
                          SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct
                     FROM attempts
                    WHERE submitted_at >= ? AND is_correct IS NOT NULL
                 GROUP BY day""",
                (datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).timestamp(),),
            ).fetchall()
        indexed = {row["day"]: row for row in rows}
        values = []
        for offset in range(days):
            day = start + timedelta(days=offset)
            key = day.isoformat()
            row = indexed.get(key)
            attempts = int(row["attempts"] or 0) if row else 0
            correct = int(row["correct"] or 0) if row else 0
            values.append({"date": key, "attempt_count": attempts, "correct_count": correct, "accuracy": self._accuracy(correct, attempts)})
        return values

    def mastery_distribution(self) -> list[dict[str, Any]]:
        levels = ("unseen", "learning", "familiar", "stable", "retained")
        with self.repository._connect() as conn:
            rows = conn.execute(
                """SELECT COALESCE(m.system_mastery_level, 'unseen') AS level, COUNT(*) AS question_count
                     FROM questions q
                     LEFT JOIN question_mastery m ON m.question_id = q.id
                 GROUP BY COALESCE(m.system_mastery_level, 'unseen')"""
            ).fetchall()
        indexed = {row["level"]: int(row["question_count"] or 0) for row in rows}
        return [{"level": level, "question_count": indexed.get(level, 0)} for level in levels]

    def module_comparison(self, project_id: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE m.project_id = ?" if project_id else ""
        params: tuple[str, ...] = (project_id,) if project_id else ()
        with self.repository._connect() as conn:
            rows = conn.execute(
                f"""SELECT m.id, m.project_id, p.name AS project_name, m.name, m.path,
                           COUNT(DISTINCT q.id) AS question_count,
                           COUNT(DISTINCT a.id) FILTER (WHERE a.is_correct IS NOT NULL) AS attempt_count,
                           COUNT(DISTINCT a.id) FILTER (WHERE a.is_correct = 1) AS correct_count,
                           SUM(CASE WHEN a.is_correct = 0 THEN 1 ELSE 0 END) AS wrong_attempt_count
                      FROM content_modules m
                      JOIN learning_projects p ON p.id = m.project_id
                      LEFT JOIN questions q ON q.module_id = m.id
                      LEFT JOIN attempts a ON a.question_id = q.id
                      {where}
                  GROUP BY m.id
                  ORDER BY wrong_attempt_count DESC, question_count DESC, m.path COLLATE NOCASE""",
                params,
            ).fetchall()
        return [
            {"id": row["id"], "project_id": row["project_id"], "project_name": row["project_name"], "name": row["name"], "path": row["path"],
             "question_count": int(row["question_count"] or 0), "attempt_count": int(row["attempt_count"] or 0),
             "wrong_attempt_count": int(row["wrong_attempt_count"] or 0),
             "accuracy": self._accuracy(int(row["correct_count"] or 0), int(row["attempt_count"] or 0))}
            for row in rows
        ]

    def error_heatmap(self, days: int = 30) -> list[dict[str, Any]]:
        days = max(1, min(int(days), 90))
        start = datetime.now(timezone.utc) - timedelta(days=days - 1)
        with self.repository._connect() as conn:
            rows = conn.execute(
                """SELECT strftime('%Y-%m-%d', a.submitted_at, 'unixepoch') AS date,
                          COALESCE(m.id, 'unassigned') AS module_id,
                          COALESCE(m.name, '未分模块') AS module_name,
                          COUNT(*) AS attempt_count,
                          SUM(CASE WHEN a.is_correct = 0 THEN 1 ELSE 0 END) AS wrong_attempt_count
                     FROM attempts a
                     JOIN questions q ON q.id = a.question_id
                     LEFT JOIN content_modules m ON m.id = q.module_id
                    WHERE a.submitted_at >= ? AND a.is_correct IS NOT NULL
                 GROUP BY date, module_id, module_name
                 ORDER BY date, wrong_attempt_count DESC""",
                (start.timestamp(),),
            ).fetchall()
        return [
            {"date": row["date"], "module_id": row["module_id"], "module_name": row["module_name"],
             "attempt_count": int(row["attempt_count"] or 0), "wrong_attempt_count": int(row["wrong_attempt_count"] or 0)}
            for row in rows
        ]
