from __future__ import annotations

from pathlib import Path

from deeptutor.services.learning_center import LearningCenterRepository
from deeptutor.services.learning_center.practice import LearningPracticeService


def _seed(repo: LearningCenterRepository) -> dict[str, str]:
    alpha = repo.create_project(name="Alpha", kind="course")
    beta = repo.create_project(name="Beta", kind="course")
    source = repo.create_content_source(project_id=alpha["id"], source_type="fixture")
    bank = repo.create_bank(project_id=alpha["id"], source_id=source["id"], name="Alpha bank")
    version = repo.create_bank_version(bank_id=bank["id"], source_id=source["id"], version="v1")
    module = repo.create_module(project_id=alpha["id"], name="Core", path="core")
    knowledge = repo.create_knowledge_point(project_id=alpha["id"], module_id=module["id"], name="Basics")
    first = repo.create_question(
        project_id=alpha["id"], bank_id=bank["id"], bank_version_id=version["id"],
        module_id=module["id"], source_id=source["id"], stem="Alpha first", options={"A": "Yes", "B": "No"},
        source_answer="A", source_explanation="The original explanation.", difficulty="easy",
        knowledge_point_ids=[knowledge["id"]],
    )
    second = repo.create_question(
        project_id=alpha["id"], bank_id=bank["id"], bank_version_id=version["id"],
        module_id=module["id"], source_id=source["id"], stem="Alpha second", options={"A": "No", "B": "Yes"},
        source_answer="B", source_explanation="Second explanation.", difficulty="hard",
        knowledge_point_ids=[knowledge["id"]],
    )
    beta_source = repo.create_content_source(project_id=beta["id"], source_type="fixture")
    beta_bank = repo.create_bank(project_id=beta["id"], source_id=beta_source["id"], name="Beta bank")
    beta_version = repo.create_bank_version(bank_id=beta_bank["id"], source_id=beta_source["id"], version="v1")
    beta_question = repo.create_question(
        project_id=beta["id"], bank_id=beta_bank["id"], bank_version_id=beta_version["id"],
        source_id=beta_source["id"], stem="Never leak", options={"A": "No", "B": "Yes"}, source_answer="B",
    )
    return {
        "project": alpha["id"], "other_project": beta["id"], "module": module["id"],
        "knowledge": knowledge["id"], "first": first["id"], "second": second["id"], "other": beta_question["id"],
    }


def test_scoped_proposal_and_exam_redaction(tmp_path: Path) -> None:
    repo = LearningCenterRepository(tmp_path / "learning_center.db")
    ids = _seed(repo)
    service = LearningPracticeService(repo)

    proposal = service.propose(project_id=ids["project"], module_id=ids["module"], knowledge_point_id=ids["knowledge"], difficulty="easy")
    assert proposal["candidate_count"] == 1
    assert proposal["questions"][0]["question_id"] == ids["first"]
    assert ids["other"] not in {question["question_id"] for question in proposal["questions"]}

    exam = service.start(project_id=ids["project"], mode="exam", module_id=ids["module"], limit=2)
    assert {question["question_id"] for question in exam["questions"]} == {ids["first"], ids["second"]}
    assert all("source_answer" not in question and "source_explanation" not in question for question in exam["questions"])


def test_learning_reveal_resume_and_duplicate_submission(tmp_path: Path) -> None:
    repo = LearningCenterRepository(tmp_path / "learning_center.db")
    ids = _seed(repo)
    service = LearningPracticeService(repo)
    session = service.start(project_id=ids["project"], mode="learning", limit=2)
    first = next(question for question in session["questions"] if question["question_id"] == ids["first"])
    second = next(question for question in session["questions"] if question["question_id"] == ids["second"])

    saved = service.autosave(session["id"], [{
        "id": first["id"], "user_answer": "B", "confidence": "guess", "marked_for_review": True,
        "eliminated_option_keys": ["A"], "elapsed_seconds": 12.5,
    }])
    resumed = next(question for question in saved["questions"] if question["id"] == first["id"])
    assert resumed["user_answer"] == "B"
    assert resumed["confidence"] == "guess"
    assert resumed["marked_for_review"] is True
    assert resumed["eliminated_option_keys"] == ["A"]
    assert resumed["source_answer"] if resumed["submitted_at"] else "source_answer" not in resumed

    answered = service.submit(session["id"], [{
        "id": first["id"], "user_answer": "A", "confidence": "sure", "elapsed_seconds": 20,
        "eliminated_option_keys": ["B"],
    }])
    first_answered = next(question for question in answered["questions"] if question["id"] == first["id"])
    second_unanswered = next(question for question in answered["questions"] if question["id"] == second["id"])
    assert first_answered["source_answer"] == "A"
    assert "source_answer" not in second_unanswered

    duplicate = service.submit(session["id"], [{"id": first["id"], "user_answer": "B"}])
    with repo._connect() as conn:
        attempt_count = conn.execute("SELECT COUNT(*) FROM attempts WHERE session_item_id=?", (first["id"],)).fetchone()[0]
        eliminated = [row[0] for row in conn.execute("SELECT option_key FROM attempt_option_eliminations WHERE session_item_id=? ORDER BY option_key", (first["id"],))]
    assert attempt_count == 1
    assert eliminated == ["B"]
    assert next(question for question in duplicate["questions"] if question["id"] == first["id"])["user_answer"] == "A"


def test_pause_resume_report_bookmark_and_discussion(tmp_path: Path) -> None:
    repo = LearningCenterRepository(tmp_path / "learning_center.db")
    ids = _seed(repo)
    service = LearningPracticeService(repo)
    session = service.start(project_id=ids["project"], mode="exam", limit=2, time_budget_minutes=10)
    first = session["questions"][0]

    paused = service.pause(session["id"])
    assert paused["status"] == "paused"
    resumed = service.resume(session["id"])
    assert resumed["status"] == "active"
    service.set_bookmark(project_id=ids["project"], question_id=first["question_id"], bookmarked=True, note="review")
    assert service.get_bookmark(first["question_id"])["note"] == "review"
    discussion = service.add_discussion_message(project_id=ids["project"], question_id=first["question_id"], content="Why?", role="user")
    assert discussion["messages"][-1]["content"] == "Why?"

    complete = service.submit(session["id"], [{"id": item["id"], "user_answer": "A", "confidence": "uncertain"} for item in session["questions"]], finish=True)
    assert complete["status"] == "completed"
    assert all("source_answer" in question for question in complete["questions"])
    report = service.report(session["id"])
    assert report["total"] == 2
    assert report["answered"] == 2
    assert "confidence" in report and "follow_up_actions" in report


def test_propose_prefers_unseen_over_already_attempted(tmp_path: Path) -> None:
    """After finishing a session, the next propose should not re-pick the same
    fixed first-N-by-id set when unseen questions remain in scope."""
    repo = LearningCenterRepository(tmp_path / "learning_center.db")
    ids = _seed(repo)
    service = LearningPracticeService(repo)

    # Seed three extra questions so scope has 5 total (first, second + 3).
    source = repo.create_content_source(project_id=ids["project"], source_type="fixture")
    bank = repo.create_bank(project_id=ids["project"], source_id=source["id"], name="Extra")
    version = repo.create_bank_version(bank_id=bank["id"], source_id=source["id"], version="v1")
    extras = []
    for stem in ("Extra 3", "Extra 4", "Extra 5"):
        extras.append(
            repo.create_question(
                project_id=ids["project"],
                bank_id=bank["id"],
                bank_version_id=version["id"],
                module_id=ids["module"],
                source_id=source["id"],
                stem=stem,
                options={"A": "1", "B": "2"},
                source_answer="A",
                knowledge_point_ids=[ids["knowledge"]],
            )["id"]
        )

    first_session = service.start(project_id=ids["project"], mode="learning", module_id=ids["module"], limit=2)
    first_ids = {q["question_id"] for q in first_session["questions"]}
    assert len(first_ids) == 2

    # Submit both so they become "seen".
    service.submit(
        first_session["id"],
        [{"id": item["id"], "user_answer": "A", "confidence": "sure"} for item in first_session["questions"]],
        finish=True,
    )

    second = service.propose(project_id=ids["project"], module_id=ids["module"], limit=2)
    second_ids = {q["question_id"] for q in second["questions"]}
    assert second["selected_count"] == 2
    assert second["unseen_selected_count"] == 2
    assert second["seen_selected_count"] == 0
    # Must not re-select the already-attempted pair while unseen remain.
    assert first_ids.isdisjoint(second_ids)

    # Explicit unseen filter only returns never-attempted questions.
    unseen = service.propose(project_id=ids["project"], module_id=ids["module"], status="unseen", limit=50)
    assert all(q["attempt_count"] == 0 for q in unseen["questions"])
    assert first_ids.isdisjoint({q["question_id"] for q in unseen["questions"]})



def test_start_pins_question_ids_and_finish_grades_autosave(tmp_path: Path) -> None:
    repo = LearningCenterRepository(tmp_path / "learning_center.db")
    ids = _seed(repo)
    service = LearningPracticeService(repo)

    proposal = service.propose(project_id=ids["project"], limit=2)
    pinned = [q["question_id"] for q in proposal["questions"]]
    assert len(pinned) == 2

    # Force a different random order by starting with explicit ids reversed.
    session = service.start(
        project_id=ids["project"],
        mode="exam",
        question_ids=list(reversed(pinned)),
        limit=2,
    )
    started_ids = [q["question_id"] for q in session["questions"]]
    assert started_ids == list(reversed(pinned))

    first, second = session["questions"]
    # Autosave both answers but only submit empty finish payload.
    service.autosave(session["id"], [
        {"id": first["id"], "user_answer": "A", "confidence": "sure"},
        {"id": second["id"], "user_answer": "B", "confidence": "guess"},
    ])
    finished = service.submit(session["id"], [], finish=True)
    assert finished["status"] == "completed"
    assert all(q["submitted_at"] is not None for q in finished["questions"])
    with repo._connect() as conn:
        attempts = conn.execute("SELECT COUNT(*) FROM attempts WHERE session_id=?", (session["id"],)).fetchone()[0]
    assert attempts == 2


def test_list_resumable_hides_empty_zombies(tmp_path: Path) -> None:
    repo = LearningCenterRepository(tmp_path / "learning_center.db")
    ids = _seed(repo)
    service = LearningPracticeService(repo)
    empty = service.start(project_id=ids["project"], mode="learning", limit=1)
    active = service.start(project_id=ids["project"], mode="learning", limit=1)
    item = active["questions"][0]
    service.autosave(active["id"], [{"id": item["id"], "user_answer": "A"}])
    resumable = service.list_resumable_sessions(project_id=ids["project"])
    assert {row["id"] for row in resumable} == {active["id"]}
    archived = service.archive_stale_sessions(older_than_seconds=0, only_empty=True)
    assert archived["archived_count"] >= 1
    empty_after = service.get(empty["id"])
    assert empty_after["status"] == "abandoned"
