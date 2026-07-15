from __future__ import annotations

import importlib
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

router_module = importlib.import_module("deeptutor.api.routers.learning_center")
router = router_module.router

from deeptutor.services.learning_center import LearningCenterRepository


def _app(repository: LearningCenterRepository, monkeypatch) -> FastAPI:
    monkeypatch.setattr(router_module, "get_learning_center_repository", lambda: repository)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/learning-center")
    return app


def test_project_taxonomy_and_question_provenance_endpoints(tmp_path: Path, monkeypatch) -> None:
    repository = LearningCenterRepository(tmp_path / "learning_center.db")
    with TestClient(_app(repository, monkeypatch)) as client:
        assert client.get("/api/v1/learning-center/projects").json() == []
        created = client.post("/api/v1/learning-center/projects", json={"name": "Biology", "kind": "course"})
        assert created.status_code == 201
        project = created.json()
        assert project["kind"] == "course"
        project_id = project["id"]

        module = client.post(
            f"/api/v1/learning-center/projects/{project_id}/modules", json={"name": "Cells", "path": "cells"}
        )
        assert module.status_code == 201
        knowledge = client.post(
            f"/api/v1/learning-center/projects/{project_id}/knowledge-points",
            json={"name": "Cell membrane", "module_id": module.json()["id"]},
        )
        assert knowledge.status_code == 201
        assert client.get(f"/api/v1/learning-center/projects/{project_id}/modules").json()[0]["name"] == "Cells"
        assert client.get(f"/api/v1/learning-center/projects/{project_id}/knowledge-points").json()[0]["name"] == "Cell membrane"

        updated = client.patch(f"/api/v1/learning-center/projects/{project_id}", json={"name": "Biology 101"})
        assert updated.status_code == 200
        assert updated.json()["name"] == "Biology 101"

        source = repository.create_content_source(project_id=project_id, source_type="json", locator="fixture://biology")
        bank = repository.create_bank(project_id=project_id, source_id=source["id"], name="Biology bank")
        version = repository.create_bank_version(bank_id=bank["id"], source_id=source["id"], version="v1")
        question = repository.create_question(
            project_id=project_id, bank_id=bank["id"], bank_version_id=version["id"], module_id=module.json()["id"], source_id=source["id"],
            stem="Which organelle contains DNA?", options={"A": "Nucleus", "B": "Ribosome"}, source_answer="A",
            question_type="single_choice", knowledge_point_ids=[knowledge.json()["id"]],
        )
        repository.add_ai_derivation(
            project_id=project_id, question_id=question["id"], derivation_type="explanation", output={"text": "Nucleus."},
            provider="test", model="test-model", prompt_version="v1", confidence=0.8,
        )
        detail = client.get(f"/api/v1/learning-center/questions/{question['id']}")
        assert detail.status_code == 200
        assert detail.json()["source_answer"] == "A"
        provenance = client.get(f"/api/v1/learning-center/questions/{question['id']}/provenance")
        assert provenance.status_code == 200
        assert provenance.json()["source"]["id"] == source["id"]
        assert provenance.json()["ai_derivations"][0]["model"] == "test-model"

        assert client.get("/api/v1/learning-center/projects/missing").status_code == 404
        assert client.post("/api/v1/learning-center/projects", json={"name": ""}).status_code == 422


def test_canonical_import_preview_commit_and_rollback(tmp_path: Path, monkeypatch) -> None:
    repository = LearningCenterRepository(tmp_path / 'imports.db')
    with TestClient(_app(repository, monkeypatch)) as client:
        payload={
          'schema_version':'learning-import/v1',
          'project':{'external_id':'music-theory','name':'Music Theory','kind':'course'},
          'bank':{'external_id':'music-v1','name':'Intervals','version':'v1','source':{}},
          'items':[{'external_id':'interval-1','module_path':['Intervals'],'knowledge_points':[],'question_type':'single_choice','stem':'A perfect fifth spans how many semitones?','options':{'A':'7','B':'5'},'source_answer':'A','source_explanation':'A perfect fifth is seven semitones.'}]
        }
        schema=client.get('/api/v1/learning-center/imports/schema')
        assert schema.status_code==200 and schema.json()['properties']['schema_version']['const']=='learning-import/v1'
        analyzed=client.post('/api/v1/learning-center/imports/analyze',json=payload)
        assert analyzed.status_code==201
        batch=analyzed.json(); batch_id=batch['id']; assert batch['status']=='preview_ready'
        assert client.get(f'/api/v1/learning-center/imports/{batch_id}/quality-report').json()['summary']['valid']==1
        selected_id = batch['items'][0]['id']
        approval = client.post(
            f'/api/v1/learning-center/imports/{batch_id}/approve',
            json={'mode': 'selected', 'selected_item_ids': [selected_id]},
        )
        assert approval.status_code == 200 and approval.json()['summary']['approved'] == 1
        committed=client.post(f'/api/v1/learning-center/imports/{batch_id}/commit')
        assert committed.status_code==200 and committed.json()['status']=='completed'
        assert committed.json()['summary']['committed']==1
        assert client.post(f'/api/v1/learning-center/imports/{batch_id}/rollback').json()['status']=='rolled_back'


def test_dashboard_endpoints_are_available_for_empty_learning_center(tmp_path: Path, monkeypatch) -> None:
    repository = LearningCenterRepository(tmp_path / "dashboard.db")
    with TestClient(_app(repository, monkeypatch)) as client:
        overview = client.get("/api/v1/learning-center/dashboard/overview")
        assert overview.status_code == 200
        assert overview.json()["project_count"] == 0
        assert overview.json()["last_session"] is None
        assert client.get("/api/v1/learning-center/dashboard/projects").json() == []
        assert len(client.get("/api/v1/learning-center/dashboard/trends?days=7").json()) == 7
        assert {item["level"] for item in client.get("/api/v1/learning-center/dashboard/mastery").json()} == {
            "unseen", "learning", "familiar", "stable", "retained"
        }
        assert client.get("/api/v1/learning-center/dashboard/modules").json() == []
        assert client.get("/api/v1/learning-center/dashboard/heatmap").json() == []


def test_practice_api_redacts_exam_answers_and_resumes(tmp_path: Path, monkeypatch) -> None:
    repository = LearningCenterRepository(tmp_path / "practice.db")
    project = repository.create_project(name="Practice", kind="course")
    source = repository.create_content_source(project_id=project["id"], source_type="fixture")
    bank = repository.create_bank(project_id=project["id"], source_id=source["id"], name="Bank")
    version = repository.create_bank_version(bank_id=bank["id"], source_id=source["id"], version="v1")
    question = repository.create_question(
        project_id=project["id"], bank_id=bank["id"], bank_version_id=version["id"], source_id=source["id"],
        stem="API question", options={"A": "Yes", "B": "No"}, source_answer="A", source_explanation="Original.",
    )
    with TestClient(_app(repository, monkeypatch)) as client:
        proposal = client.post("/api/v1/learning-center/practice/proposal", json={"project_id": project["id"], "limit": 10})
        assert proposal.status_code == 200 and proposal.json()["candidate_count"] == 1
        start = client.post("/api/v1/learning-center/practice/sessions", json={"project_id": project["id"], "mode": "exam", "limit": 1})
        assert start.status_code == 201
        session = start.json()
        assert "source_answer" not in session["questions"][0]
        item = session["questions"][0]
        saved = client.patch(f"/api/v1/learning-center/practice/sessions/{session['id']}", json=[{
            "id": item["id"], "user_answer": "A", "confidence": "sure", "eliminated_option_keys": ["B"], "elapsed_seconds": 9,
        }])
        assert saved.status_code == 200 and saved.json()["questions"][0]["eliminated_option_keys"] == ["B"]
        assert client.post(f"/api/v1/learning-center/practice/sessions/{session['id']}/pause").json()["status"] == "paused"
        assert client.post(f"/api/v1/learning-center/practice/sessions/{session['id']}/resume").json()["status"] == "active"
        completed = client.post(f"/api/v1/learning-center/practice/sessions/{session['id']}/submit", json={"answers": [{"id": item["id"], "user_answer": "A"}], "finish": True})
        assert completed.status_code == 200 and completed.json()["questions"][0]["source_answer"] == "A"
        assert client.get(f"/api/v1/learning-center/practice/sessions/{session['id']}/report").json()["accuracy"] == 1.0
        bookmark = client.post("/api/v1/learning-center/practice/bookmarks", json={"project_id": project["id"], "question_id": question["id"], "note": "keep"})
        assert bookmark.status_code == 200 and bookmark.json()["note"] == "keep"
        discussion = client.post(f"/api/v1/learning-center/practice/questions/{question['id']}/discussion", json={"project_id": project["id"], "content": "Explain why"})
        assert discussion.status_code == 200 and discussion.json()["messages"][-1]["content"] == "Explain why"
