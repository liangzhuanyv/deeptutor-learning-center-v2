"""Deterministic evidence-based mastery and review services (v1)."""
from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import Any

from .normalization import canonical_json, clean_text
from .repository import LearningCenterNotFoundError, LearningCenterRepository, LearningCenterValidationError

ALGORITHM_VERSION = "mastery-v1"
_LEVELS = ((0.85, "retained"), (0.70, "stable"), (0.45, "familiar"), (0.01, "learning"), (0.0, "unseen"))


def _loads(value: str | None, fallback: Any) -> Any:
    try:
        result = json.loads(value or "")
    except (TypeError, ValueError):
        return fallback
    return result if isinstance(result, type(fallback)) else fallback


def _level(score: float, attempt_count: int) -> str:
    if not attempt_count:
        return "unseen"
    return next(level for threshold, level in _LEVELS if score >= threshold)


class LearningMasteryService:
    def __init__(self, repository: LearningCenterRepository | None = None) -> None:
        self.repository = repository or LearningCenterRepository()

    @staticmethod
    def _score(attempts: list[Any]) -> tuple[float, dict[str, Any]]:
        graded = [row for row in attempts if row["is_correct"] is not None]
        if not graded:
            return 0.0, {"attempt_count": len(attempts), "graded_count": 0, "accuracy": None, "consecutive_correct": 0}
        correct = sum(bool(row["is_correct"]) for row in graded)
        consecutive = 0
        for row in reversed(graded):
            if not row["is_correct"]:
                break
            consecutive += 1
        confidence_bonus = sum(0.04 if row["confidence"] == "sure" and row["is_correct"] else -0.03 if row["confidence"] == "sure" else 0 for row in graded) / len(graded)
        score = max(0.0, min(1.0, 0.12 + 0.68 * (correct / len(graded)) + 0.12 * min(len(graded) / 5, 1) + 0.08 * min(consecutive / 3, 1) + confidence_bonus))
        return score, {"attempt_count": len(attempts), "graded_count": len(graded), "correct_count": correct, "accuracy": correct / len(graded), "consecutive_correct": consecutive, "confidence_adjustment": confidence_bonus}

    def _question_attempts(self, conn: Any, question_id: str) -> list[Any]:
        return conn.execute("SELECT * FROM attempts WHERE question_id=? ORDER BY submitted_at, id", (question_id,)).fetchall()

    def _manual_status(self, conn: Any, *, question_id: str | None = None, knowledge_point_id: str | None = None) -> str | None:
        column, value = ("question_id", question_id) if question_id else ("knowledge_point_id", knowledge_point_id)
        row = conn.execute(f"SELECT status FROM manual_mastery_overrides WHERE {column}=? ORDER BY updated_at DESC LIMIT 1", (value,)).fetchone()
        return row["status"] if row else None

    def _upsert_review(self, conn: Any, *, project_id: str, question_id: str, due_at: float, interval_days: float, reason: str, now: float) -> None:
        conn.execute("UPDATE review_schedule SET state='superseded', updated_at=? WHERE question_id=? AND state IN ('due','scheduled')", (now, question_id))
        conn.execute("INSERT INTO review_schedule (id,project_id,question_id,due_at,interval_days,state,metadata_json,created_at,updated_at) VALUES (?,?,?,?,?,'due',?,?,?)", (self.repository._new_id("review"), project_id, question_id, due_at, interval_days, canonical_json({"reason": reason, "algorithm_version": ALGORITHM_VERSION}), now, now))

    def record_attempt_in_connection(self, conn: Any, *, project_id: str, question_id: str, attempt_id: str, is_correct: int | None, confidence: str, now: float) -> dict[str, Any]:
        """Write immutable evidence and update the deterministic projections."""
        attempts = self._question_attempts(conn, question_id)
        score, rationale = self._score(attempts)
        level = _level(score, rationale["attempt_count"])
        manual_mastered = self._manual_status(conn, question_id=question_id) == "mastered"
        existing_state = conn.execute("SELECT * FROM wrong_question_states WHERE question_id=?", (question_id,)).fetchone()
        wrong_count = int(existing_state["wrong_count"]) if existing_state else 0
        correct_after_error = int(existing_state["correct_after_error_count"]) if existing_state else 0
        if is_correct == 0:
            wrong_count += 1
        elif is_correct == 1 and wrong_count:
            correct_after_error += 1
        state = "manual_mastered" if manual_mastered else ("reopen_suggested" if is_correct == 0 and existing_state and existing_state["state"] == "manual_mastered" else "review_due" if is_correct == 0 else "system_mastered" if level in {"stable", "retained"} else "reviewing" if wrong_count else "new")
        # A manual override is never removed by evidence.  Later errors surface a
        # visible advisory state while retaining the override record.
        if manual_mastered and is_correct == 0:
            state = "reopen_suggested"
        elif manual_mastered:
            state = "manual_mastered"
        conn.execute("INSERT INTO question_mastery (question_id,project_id,system_mastery_score,system_mastery_level,algorithm_version,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(question_id) DO UPDATE SET system_mastery_score=excluded.system_mastery_score,system_mastery_level=excluded.system_mastery_level,algorithm_version=excluded.algorithm_version,updated_at=excluded.updated_at", (question_id, project_id, score, level, ALGORITHM_VERSION, now))
        conn.execute("INSERT INTO wrong_question_states (question_id,project_id,state,wrong_count,correct_after_error_count,first_wrong_at,last_wrong_at,last_attempt_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(question_id) DO UPDATE SET state=excluded.state,wrong_count=excluded.wrong_count,correct_after_error_count=excluded.correct_after_error_count,first_wrong_at=COALESCE(wrong_question_states.first_wrong_at,excluded.first_wrong_at),last_wrong_at=COALESCE(excluded.last_wrong_at,wrong_question_states.last_wrong_at),last_attempt_at=excluded.last_attempt_at,updated_at=excluded.updated_at", (question_id, project_id, state, wrong_count, correct_after_error, now if is_correct == 0 else None, now if is_correct == 0 else None, now, now))
        payload = {**rationale, "is_correct": None if is_correct is None else bool(is_correct), "confidence": confidence, "score": score, "level": level, "state": state}
        conn.execute("INSERT INTO mastery_evidence (id,project_id,question_id,attempt_id,algorithm_version,evidence_type,payload_json,score_delta,created_at) VALUES (?,?,?,?,?,'attempt',?,?,?)", (self.repository._new_id("evidence"), project_id, question_id, attempt_id, ALGORITHM_VERSION, canonical_json(payload), score, now))
        interval = 1 if is_correct == 0 else 7 if level in {"stable", "retained"} else 3
        self._upsert_review(conn, project_id=project_id, question_id=question_id, due_at=now if is_correct == 0 else now + interval * 86400, interval_days=interval, reason="incorrect" if is_correct == 0 else "retention", now=now)
        self._recalculate_knowledge(conn, project_id=project_id, question_id=question_id, now=now)
        return payload

    def _recalculate_knowledge(self, conn: Any, *, project_id: str, question_id: str, now: float) -> None:
        points = conn.execute("SELECT knowledge_point_id FROM question_knowledge_points WHERE question_id=?", (question_id,)).fetchall()
        for point in points:
            scores = conn.execute("SELECT system_mastery_score FROM question_mastery qm JOIN question_knowledge_points qkp ON qkp.question_id=qm.question_id WHERE qkp.knowledge_point_id=?", (point["knowledge_point_id"],)).fetchall()
            score = sum(row["system_mastery_score"] for row in scores) / len(scores) if scores else 0.0
            level = _level(score, len(scores))
            conn.execute("INSERT INTO knowledge_mastery (knowledge_point_id,project_id,system_mastery_score,system_mastery_level,algorithm_version,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(knowledge_point_id) DO UPDATE SET system_mastery_score=excluded.system_mastery_score,system_mastery_level=excluded.system_mastery_level,algorithm_version=excluded.algorithm_version,updated_at=excluded.updated_at", (point["knowledge_point_id"], project_id, score, level, ALGORITHM_VERSION, now))

    def set_question_override(self, *, question_id: str, mastered: bool, note: str = "") -> dict[str, Any]:
        now = time.time()
        with self.repository._connect() as conn:
            question = conn.execute("SELECT project_id FROM questions WHERE id=?", (question_id,)).fetchone()
            if not question: raise LearningCenterNotFoundError("Question not found")
            status = "mastered" if mastered else "cleared"
            conn.execute("INSERT INTO manual_mastery_overrides (id,project_id,question_id,status,note,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", (self.repository._new_id("mastery_override"), question["project_id"], question_id, status, clean_text(note), now, now))
            target_state = "manual_mastered" if mastered else "review_due"
            conn.execute("INSERT INTO wrong_question_states (question_id,project_id,state,updated_at) VALUES (?,?,?,?) ON CONFLICT(question_id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at", (question_id, question["project_id"], target_state, now))
            if mastered: conn.execute("UPDATE review_schedule SET state='superseded',updated_at=? WHERE question_id=? AND state IN ('due','scheduled')", (now, question_id))
        return self.question_detail(question_id)

    def set_knowledge_override(self, *, knowledge_point_id: str, mastered: bool, note: str = "") -> dict[str, Any]:
        now=time.time()
        with self.repository._connect() as conn:
            kp=conn.execute("SELECT project_id FROM knowledge_points WHERE id=?", (knowledge_point_id,)).fetchone()
            if not kp: raise LearningCenterNotFoundError("Knowledge point not found")
            conn.execute("INSERT INTO manual_mastery_overrides (id,project_id,knowledge_point_id,status,note,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", (self.repository._new_id("mastery_override"),kp["project_id"],knowledge_point_id,"mastered" if mastered else "cleared",clean_text(note),now,now))
        return self.knowledge_summary(knowledge_point_id)

    def question_detail(self, question_id: str) -> dict[str, Any]:
        with self.repository._connect() as conn:
            q=conn.execute("SELECT q.*, (SELECT json_group_object(option_key,content) FROM question_options o WHERE o.question_id=q.id) options_json FROM questions q WHERE q.id=?", (question_id,)).fetchone()
            if not q: raise LearningCenterNotFoundError("Question not found")
            attempts=[dict(row) for row in conn.execute("SELECT * FROM attempts WHERE question_id=? ORDER BY submitted_at DESC",(question_id,))]
            kps=[dict(row) for row in conn.execute("SELECT kp.* FROM knowledge_points kp JOIN question_knowledge_points qkp ON qkp.knowledge_point_id=kp.id WHERE qkp.question_id=?",(question_id,))]
            discussion=conn.execute("SELECT id,title FROM question_discussions WHERE question_id=? ORDER BY updated_at DESC LIMIT 1",(question_id,)).fetchone()
            messages=[] if not discussion else [dict(row) for row in conn.execute("SELECT * FROM question_discussion_messages WHERE discussion_id=? ORDER BY created_at",(discussion['id'],))]
            schedule=conn.execute("SELECT * FROM review_schedule WHERE question_id=? ORDER BY updated_at DESC LIMIT 1",(question_id,)).fetchone()
            manual=conn.execute("SELECT * FROM manual_mastery_overrides WHERE question_id=? ORDER BY updated_at DESC LIMIT 1",(question_id,)).fetchone()
            state=conn.execute("SELECT * FROM wrong_question_states WHERE question_id=?",(question_id,)).fetchone(); mastery=conn.execute("SELECT * FROM question_mastery WHERE question_id=?",(question_id,)).fetchone()
            evidence=[dict(row) for row in conn.execute("SELECT * FROM mastery_evidence WHERE question_id=? ORDER BY created_at DESC",(question_id,))]
            return {"question": {**dict(q), "options": _loads(q['options_json'], {})}, "attempts":attempts, "confidence_timeline":[{"confidence":a['confidence'],"is_correct":a['is_correct'],"submitted_at":a['submitted_at']} for a in reversed(attempts)], "knowledge_points":kps, "wrong_state":None if not state else dict(state), "mastery":None if not mastery else dict(mastery), "manual_override":None if not manual else dict(manual), "review_schedule":None if not schedule else dict(schedule), "evidence":[{**row,"payload":_loads(row.pop('payload_json'),{})} for row in evidence], "discussion":{"id":None if not discussion else discussion['id'],"messages":messages}, "provenance":{"source_id":q['source_id'],"kind":q['provenance_type'],"review_status":q['review_status']}}

    def knowledge_summary(self, knowledge_point_id: str) -> dict[str, Any]:
        with self.repository._connect() as conn:
            kp=conn.execute("SELECT * FROM knowledge_points WHERE id=?",(knowledge_point_id,)).fetchone()
            if not kp: raise LearningCenterNotFoundError("Knowledge point not found")
            mastery=conn.execute("SELECT * FROM knowledge_mastery WHERE knowledge_point_id=?",(knowledge_point_id,)).fetchone()
            manual=conn.execute("SELECT * FROM manual_mastery_overrides WHERE knowledge_point_id=? ORDER BY updated_at DESC LIMIT 1",(knowledge_point_id,)).fetchone()
            return {"knowledge_point":dict(kp),"mastery":None if not mastery else dict(mastery),"manual_override":None if not manual else dict(manual)}

    def review_queue(self, *, project_id: str, module_id: str | None = None, knowledge_point_id: str | None = None, filter: str = "due") -> list[dict[str, Any]]:
        if filter not in {"due","all_wrong","repeated","reopen","manual_mastered"}: raise LearningCenterValidationError("Unsupported review filter")
        where=["w.project_id=?"]; params=[project_id]
        if module_id: where.append("q.module_id=?"); params.append(module_id)
        if knowledge_point_id: where.append("EXISTS (SELECT 1 FROM question_knowledge_points x WHERE x.question_id=q.id AND x.knowledge_point_id=?)"); params.append(knowledge_point_id)
        now=time.time()
        if filter=="due": where.append("EXISTS (SELECT 1 FROM review_schedule r WHERE r.question_id=q.id AND r.state='due' AND r.due_at<=?)"); params.append(now)
        elif filter=="repeated": where.append("w.wrong_count>=2")
        elif filter=="reopen": where.append("w.state='reopen_suggested'")
        elif filter=="manual_mastered": where.append("w.state='manual_mastered'")
        elif filter=="all_wrong": where.append("w.wrong_count>0")
        with self.repository._connect() as conn:
            self.repository._require_project(conn,project_id)
            rows=conn.execute("SELECT q.id AS question_id,q.stem,q.question_type,q.module_id,w.state,w.wrong_count,w.correct_after_error_count,m.system_mastery_score,m.system_mastery_level,(SELECT due_at FROM review_schedule r WHERE r.question_id=q.id AND r.state='due' ORDER BY due_at LIMIT 1) due_at FROM wrong_question_states w JOIN questions q ON q.id=w.question_id LEFT JOIN question_mastery m ON m.question_id=q.id WHERE "+" AND ".join(where)+" ORDER BY CASE WHEN w.state='reopen_suggested' THEN 0 ELSE 1 END, due_at, w.last_wrong_at DESC",params).fetchall()
            return [dict(row) for row in rows]

    def recalculate(self, *, project_id: str, dry_run: bool = False) -> dict[str, Any]:
        now=time.time(); changed=0
        with self.repository._connect() as conn:
            self.repository._require_project(conn,project_id)
            questions=conn.execute("SELECT id FROM questions WHERE project_id=?",(project_id,)).fetchall()
            for q in questions:
                attempts=self._question_attempts(conn,q['id']); score,rationale=self._score(attempts); level=_level(score,rationale['attempt_count'])
                current=conn.execute("SELECT system_mastery_score,system_mastery_level FROM question_mastery WHERE question_id=?",(q['id'],)).fetchone()
                if current is None or current['system_mastery_score'] != score or current['system_mastery_level'] != level: changed+=1
                if not dry_run: conn.execute("INSERT INTO question_mastery (question_id,project_id,system_mastery_score,system_mastery_level,algorithm_version,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(question_id) DO UPDATE SET system_mastery_score=excluded.system_mastery_score,system_mastery_level=excluded.system_mastery_level,algorithm_version=excluded.algorithm_version,updated_at=excluded.updated_at",(q['id'],project_id,score,level,ALGORITHM_VERSION,now)); self._recalculate_knowledge(conn,project_id=project_id,question_id=q['id'],now=now)
        return {"project_id":project_id,"algorithm_version":ALGORITHM_VERSION,"question_count":len(questions),"changed_count":changed,"dry_run":dry_run}
