from __future__ import annotations

import time
from pathlib import Path

from deeptutor.services.learning_center import LearningCenterRepository
from deeptutor.services.learning_center.dashboard import LearningCenterDashboardService


def test_dashboard_aggregates_existing_learning_evidence(tmp_path: Path) -> None:
    repo = LearningCenterRepository(tmp_path / "learning_center.db")
    project = repo.create_project(name="Biology", kind="course")
    source = repo.create_content_source(project_id=project["id"], source_type="fixture")
    bank = repo.create_bank(project_id=project["id"], source_id=source["id"], name="Cells")
    version = repo.create_bank_version(bank_id=bank["id"], source_id=source["id"], version="v1")
    module = repo.create_module(project_id=project["id"], name="Cells", path="cells")
    first = repo.create_question(
        project_id=project["id"], bank_id=bank["id"], bank_version_id=version["id"],
        module_id=module["id"], source_id=source["id"], stem="Which organelle contains DNA?",
        options={"A": "Nucleus", "B": "Ribosome"}, source_answer="A",
    )
    second = repo.create_question(
        project_id=project["id"], bank_id=bank["id"], bank_version_id=version["id"],
        module_id=module["id"], source_id=source["id"], stem="Which organelle makes proteins?",
        options={"A": "Ribosome", "B": "Nucleus"}, source_answer="A",
    )
    now = time.time()
    with repo._connect() as conn:
        conn.execute(
            """INSERT INTO practice_sessions
               (id,project_id,bank_version_id,mode,title,status,started_at,completed_at,created_at,updated_at)
               VALUES ('session_1',?,?, 'learning','Cells review','completed',?,?,?,?)""",
            (project["id"], version["id"], now - 90, now - 30, now - 90, now - 30),
        )
        conn.executemany(
            """INSERT INTO attempts
               (id,session_id,question_id,user_answer,is_correct,confidence,judgment_json,submitted_at,created_at)
               VALUES (?,?,?,?,?,'sure','{}',?,?)""",
            [
                ("attempt_1", "session_1", first["id"], "A", 1, now - 60, now - 60),
                ("attempt_2", "session_1", second["id"], "B", 0, now - 50, now - 50),
            ],
        )
        conn.execute(
            """INSERT INTO wrong_question_states
               (question_id,project_id,state,wrong_count,correct_after_error_count,last_attempt_at,updated_at)
               VALUES (?,?,'review_due',1,0,?,?)""",
            (second["id"], project["id"], now - 50, now),
        )
        conn.execute(
            """INSERT INTO question_mastery
               (question_id,project_id,system_mastery_score,system_mastery_level,algorithm_version,updated_at)
               VALUES (?,?,0.9,'stable','test',?)""",
            (first["id"], project["id"], now),
        )

    dashboard = LearningCenterDashboardService(repo)
    overview = dashboard.overview()
    assert overview["project_count"] == 1
    assert overview["question_count"] == 2
    assert overview["attempt_count"] == 2
    assert overview["accuracy"] == 0.5
    assert overview["review_due_count"] == 1
    assert overview["last_session"]["id"] == "session_1"

    projects = dashboard.project_summaries()
    assert projects == [{
        "id": project["id"], "name": "Biology", "kind": "course", "question_count": 2,
        "attempt_count": 2, "accuracy": 0.5, "review_due_count": 1, "last_session_at": now - 90,
    }]
    assert any(day["attempt_count"] == 2 and day["accuracy"] == 0.5 for day in dashboard.trends(2))
    mastery = {item["level"]: item["question_count"] for item in dashboard.mastery_distribution()}
    assert mastery["stable"] == 1 and mastery["unseen"] == 1
    modules = dashboard.module_comparison(project["id"])
    assert modules[0]["wrong_attempt_count"] == 1 and modules[0]["accuracy"] == 0.5
    heatmap = dashboard.error_heatmap(2)
    assert heatmap[0]["module_id"] == module["id"] and heatmap[0]["wrong_attempt_count"] == 1
