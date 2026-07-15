from __future__ import annotations

import importlib
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient
exam_practice_router_module = importlib.import_module("deeptutor.api.routers.exam_practice")
exam_practice_router = exam_practice_router_module.router

from deeptutor.services.exam_practice import ExamPracticeStore


def _app(store: ExamPracticeStore, monkeypatch) -> FastAPI:
    monkeypatch.setattr(exam_practice_router_module, "get_exam_practice_store", lambda: store)
    app = FastAPI()
    app.include_router(exam_practice_router, prefix="/api/v1/exam-practice")
    return app


def _import_payload() -> dict:
    return {
        "bank": {"id": "bank-1", "name": "路由题库"},
        "questions": [
            {
                "external_id": "q-1",
                "subject": "法规",
                "chapter": "信息披露",
                "question_type": "单选",
                "stem": "披露题",
                "options": {"A": "错", "B": "对"},
                "source_answer": "B",
                "source_explanation": "应当真实披露。",
            }
        ],
    }


def test_exam_practice_router_end_to_end_with_weak_points(tmp_path: Path, monkeypatch) -> None:
    store = ExamPracticeStore(tmp_path / "router.db")
    with TestClient(_app(store, monkeypatch)) as client:
        imported = client.post("/api/v1/exam-practice/imports", json=_import_payload())
        assert imported.status_code == 201
        assert imported.json()["created"] == 1

        subjects = client.get("/api/v1/exam-practice/subjects?bank_id=bank-1")
        assert subjects.status_code == 200
        subject_id = subjects.json()[0]["id"]
        chapter_id = client.get(
            f"/api/v1/exam-practice/chapters?subject_id={subject_id}"
        ).json()[0]["id"]

        started = client.post(
            "/api/v1/exam-practice/sessions",
            json={"subject_id": subject_id, "chapter_id": chapter_id, "limit": 1},
        )
        assert started.status_code == 201
        session = started.json()
        question = session["questions"][0]
        assert "source_answer" not in question

        submitted = client.post(
            f"/api/v1/exam-practice/sessions/{session['id']}/answers",
            json={"answers": [{"question_id": question["id"], "user_answer": "A"}]},
        )
        assert submitted.status_code == 200
        assert submitted.json()["session"]["questions"][0]["source_answer"] == "B"

        weak_points = client.post(
            "/api/v1/exam-practice/insights/weak-points",
            json={"subject_id": subject_id, "limit": 3},
        )
        assert weak_points.status_code == 200
        body = weak_points.json()
        assert body["total"] == 1
        card = body["items"][0]
        assert card["chapter_name"] == "信息披露"
        assert card["evidence_question_ids"] == [question["id"]]
        assert card["wrong_question_count"] == 1
        assert card["total_wrong_attempts"] == 1
        assert "真实披露" in card["summary"]
