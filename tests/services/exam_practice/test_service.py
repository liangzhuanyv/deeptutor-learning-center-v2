from __future__ import annotations

from pathlib import Path

from deeptutor.services.exam_practice import ExamPracticeStore


def _questions() -> list[dict[str, object]]:
    return [
        {
            "external_id": "law-1",
            "subject": "证券法规",
            "subject_external_id": "law",
            "chapter": "信息披露",
            "chapter_external_id": "disclosure",
            "question_type": "单选",
            "stem": "信息披露的第一题",
            "options": {"A": "错误", "B": "正确"},
            "source_answer": "B",
            "source_explanation": "需要及时、真实、准确披露。",
        },
        {
            "external_id": "law-2",
            "subject": "证券法规",
            "subject_external_id": "law",
            "chapter": "信息披露",
            "chapter_external_id": "disclosure",
            "question_type": "单选",
            "stem": "信息披露的第二题",
            "options": {"A": "错误", "B": "正确"},
            "source_answer": "B",
            "ai_explanation": "披露义务是本章核心。",
        },
        {
            "external_id": "fin-1",
            "subject": "金融基础",
            "subject_external_id": "finance",
            "chapter": "货币市场",
            "chapter_external_id": "money-market",
            "question_type": "多选",
            "stem": "货币市场工具",
            "options": {"A": "国库券", "B": "股票", "C": "商业票据"},
            "source_answer": "AC",
        },
    ]


def _store(tmp_path: Path) -> ExamPracticeStore:
    return ExamPracticeStore(tmp_path / "exam-practice.db")


def test_import_is_idempotent_and_builds_subject_chapter_hierarchy(tmp_path: Path) -> None:
    store = _store(tmp_path)
    bank = {"id": "securities", "name": "证券题库", "source": "fixture"}

    first = store.import_bank(bank, _questions())
    updated_questions = _questions()
    updated_questions[0] = {**updated_questions[0], "source_explanation": "更新后的解析。"}
    second = store.import_bank(bank, updated_questions)

    assert first == {
        "bank_id": "securities",
        "bank_name": "证券题库",
        "created": 3,
        "updated": 0,
        "skipped": 0,
        "subject_count": 2,
        "chapter_count": 2,
    }
    assert second["created"] == 0
    assert second["updated"] == 3
    assert store.list_banks()[0]["question_count"] == 3

    subjects = store.list_subjects("securities")
    assert {subject["name"] for subject in subjects} == {"证券法规", "金融基础"}
    law_subject = next(subject for subject in subjects if subject["name"] == "证券法规")
    chapters = store.list_chapters(law_subject["id"])
    assert chapters == [
        {
            "id": chapters[0]["id"],
            "subject_id": law_subject["id"],
            "external_id": "disclosure",
            "name": "信息披露",
            "parent_id": None,
            "path": "信息披露",
            "sort_order": 0,
            "question_count": 2,
        }
    ]


def test_session_submission_updates_wrong_book_statistics_and_weak_points(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.import_bank({"id": "securities", "name": "证券题库"}, _questions())
    law_subject = next(subject for subject in store.list_subjects() if subject["name"] == "证券法规")
    disclosure = store.list_chapters(law_subject["id"])[0]

    session = store.start_session(chapter_id=disclosure["id"], question_types=["单选"], limit=2)
    assert session["total"] == 2
    assert all("source_answer" not in question for question in session["questions"])

    result = store.submit_answers(
        session["id"],
        [{"question_id": question["id"], "user_answer": "A"} for question in session["questions"]],
    )
    assert result["remaining"] == 0
    assert result["session"]["status"] == "completed"
    assert all(not item["is_correct"] for item in result["submitted"])
    assert all("source_answer" in question for question in result["session"]["questions"])

    wrong_book = store.list_wrong_questions()
    assert wrong_book["total"] == 2
    assert {item["wrong_count"] for item in wrong_book["items"]} == {1}
    store.set_mastery_status(wrong_book["items"][0]["question_id"], "mastered")

    wrong_stats = store.wrong_statistics()
    assert wrong_stats["total_questions"] == 2
    assert wrong_stats["total_wrong_attempts"] == 2
    assert wrong_stats["mastered_count"] == 1
    assert wrong_stats["learning_count"] == 1

    chapter_stats = store.chapter_statistics(law_subject["id"])
    assert chapter_stats == [
        {
            "subject_id": law_subject["id"],
            "subject_name": "证券法规",
            "chapter_id": disclosure["id"],
            "chapter_name": "信息披露",
            "chapter_path": "信息披露",
            "question_count": 2,
            "practiced_count": 2,
            "correct_attempts": 0,
            "wrong_attempts": 2,
            "wrong_question_count": 2,
        }
    ]

    cards = store.weak_points(subject_id=law_subject["id"], limit=5)
    assert len(cards) == 1
    card = cards[0]
    assert card["chapter_id"] == disclosure["id"]
    assert card["chapter_name"] == "信息披露"
    assert card["title"] == "信息披露 易错知识点"
    assert set(card["evidence_question_ids"]) == {
        question["question_id"] for question in wrong_book["items"]
    }
    assert card["wrong_question_count"] == 2
    assert card["total_wrong_attempts"] == 2
    assert "已有解析提示" in card["summary"]
