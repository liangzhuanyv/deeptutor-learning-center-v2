"""HTTP API for the standalone, local SQLite Exam Practice domain.

The application entry point intentionally does not include this router.  The
integrating branch should mount it under ``/api/v1/exam-practice``.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from deeptutor.services.llm.client import LLMClient
from deeptutor.services.llm.config import get_llm_config
from deeptutor.services.exam_practice import (
    ExamPracticeNotFoundError,
    ExamPracticeValidationError,
    get_exam_practice_store,
)

router = APIRouter()


class BankImport(BaseModel):
    id: str = Field(default="", max_length=256)
    external_id: str = Field(default="", max_length=256)
    name: str = Field(..., min_length=1, max_length=500)
    source: str = Field(default="", max_length=1000)
    version: str = Field(default="", max_length=256)
    metadata: dict[str, Any] = Field(default_factory=dict)


class QuestionImport(BaseModel):
    external_id: str = Field(default="", max_length=512)
    subject: str = Field(default="未分类", max_length=500)
    subject_id: str = Field(default="", max_length=256)
    subject_external_id: str = Field(default="", max_length=256)
    subject_sort_order: int = 0
    chapter: str = Field(default="", max_length=500)
    chapter_id: str = Field(default="", max_length=256)
    chapter_external_id: str = Field(default="", max_length=256)
    chapter_path: str = Field(default="", max_length=1000)
    chapter_sort_order: int = 0
    question_type: str = Field(default="", max_length=100)
    stem: str = Field(..., min_length=1, max_length=20000)
    options: dict[str, str] | list[str] | None = None
    source_answer: str = Field(default="", max_length=10000)
    answer_status: str = Field(default="", max_length=100)
    source_explanation: str = Field(default="", max_length=50000)
    ai_explanation: str = Field(default="", max_length=50000)
    source: str = Field(default="", max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImportRequest(BaseModel):
    bank: BankImport
    questions: list[QuestionImport] = Field(default_factory=list, max_length=10000)


class StartSessionRequest(BaseModel):
    title: str = Field(default="", max_length=500)
    subject_id: str | None = Field(default=None, max_length=256)
    chapter_id: str | None = Field(default=None, max_length=256)
    question_types: list[str] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=10, ge=1, le=200)


class AnswerSubmission(BaseModel):
    question_id: str = Field(..., min_length=1, max_length=256)
    user_answer: str = Field(default="", max_length=10000)
    is_correct: bool | None = None
    judgment: str = Field(default="", max_length=10000)


class SubmitAnswersRequest(BaseModel):
    answers: list[AnswerSubmission] = Field(..., min_length=1, max_length=200)


class MasteryStatusRequest(BaseModel):
    mastery_status: Literal["learning", "mastered"]


class WeakPointsRequest(BaseModel):
    subject_id: str | None = Field(default=None, max_length=256)
    limit: int = Field(default=10, ge=1, le=50)


class DiscussionMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=8_000)


class DiscussQuestionRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8_000)
    history: list[DiscussionMessage] = Field(default_factory=list, max_length=20)


def _discussion_context(question: dict[str, Any]) -> str:
    """Keep a focused, bounded context for a one-question tutoring dialogue."""
    def clip(value: Any, maximum: int = 10_000) -> str:
        text = str(value or "").strip()
        return text if len(text) <= maximum else text[:maximum] + "…"

    options = question.get("options") if isinstance(question.get("options"), dict) else {}
    option_text = "\n".join(f"{key}. {clip(value, 2_000)}" for key, value in options.items())
    explanation = question.get("source_explanation") or question.get("ai_explanation") or "（题库暂未提供解析）"
    return "\n".join(
        [
            f"科目：{clip(question.get('subject_name'), 500)}",
            f"章节：{clip(question.get('chapter_name'), 500)}",
            f"题型：{clip(question.get('question_type'), 100)}",
            f"题目：{clip(question.get('stem'))}",
            f"选项：\n{option_text}",
            f"标准答案：{clip(question.get('source_answer'), 500) or '待复核'}",
            f"现有解析：{clip(explanation)}",
        ]
    )


def _raise_domain_error(exc: Exception) -> None:
    if isinstance(exc, ExamPracticeNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ExamPracticeValidationError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise exc


@router.post("/imports", status_code=status.HTTP_201_CREATED)
def import_questions(payload: ImportRequest) -> dict[str, Any]:
    """Idempotently import one bank and its subject/chapter/question hierarchy."""
    try:
        return get_exam_practice_store().import_bank(
            payload.bank.model_dump(),
            (question.model_dump() for question in payload.questions),
        )
    except Exception as exc:
        _raise_domain_error(exc)


@router.get("/banks")
def list_banks() -> list[dict[str, Any]]:
    return get_exam_practice_store().list_banks()


@router.get("/subjects")
def list_subjects(bank_id: str | None = Query(default=None, max_length=256)) -> list[dict[str, Any]]:
    return get_exam_practice_store().list_subjects(bank_id=bank_id)


@router.get("/chapters")
def list_chapters(subject_id: str | None = Query(default=None, max_length=256)) -> list[dict[str, Any]]:
    return get_exam_practice_store().list_chapters(subject_id=subject_id)


@router.get("/questions/{question_id}")
def get_question(question_id: str) -> dict[str, Any]:
    try:
        return get_exam_practice_store().get_question(question_id)
    except Exception as exc:
        _raise_domain_error(exc)


@router.post("/questions/{question_id}/discussion")
async def discuss_question(question_id: str, payload: DiscussQuestionRequest) -> dict[str, str]:
    """Have the configured DeepTutor model tutor the learner on one saved question."""
    try:
        question = get_exam_practice_store().get_question(question_id)
    except Exception as exc:
        _raise_domain_error(exc)
        raise AssertionError("unreachable")

    system_prompt = """You are a patient Chinese financial-exam tutor. Discuss only the supplied practice question. Explain reasoning, distinguish the verified source answer from any AI-generated explanation, and admit uncertainty rather than inventing regulations. Be concise by default, but answer the learner's actual question directly.

Practice-question context:
""" + _discussion_context(question)
    try:
        reply = await LLMClient(get_llm_config()).complete(
            payload.message.strip(),
            system_prompt=system_prompt,
            history=[message.model_dump() for message in payload.history],
            max_retries=2,
            temperature=0.2,
            max_tokens=1_000,
        )
        return {"reply": reply.strip() or "这道题我暂时没有生成有效回复，请换一种问法。"}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI discussion is temporarily unavailable: {exc}",
        ) from exc


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def start_session(payload: StartSessionRequest) -> dict[str, Any]:
    try:
        return get_exam_practice_store().start_session(**payload.model_dump())
    except Exception as exc:
        _raise_domain_error(exc)


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    try:
        return get_exam_practice_store().get_session(session_id)
    except Exception as exc:
        _raise_domain_error(exc)


@router.post("/sessions/{session_id}/answers")
def submit_answers(session_id: str, payload: SubmitAnswersRequest) -> dict[str, Any]:
    try:
        return get_exam_practice_store().submit_answers(
            session_id,
            (answer.model_dump() for answer in payload.answers),
        )
    except Exception as exc:
        _raise_domain_error(exc)


@router.get("/wrong-book")
def list_wrong_book(
    mastery_status: Literal["learning", "mastered"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    try:
        return get_exam_practice_store().list_wrong_questions(
            mastery_status=mastery_status,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        _raise_domain_error(exc)


@router.patch("/wrong-book/{question_id}")
def update_wrong_book(question_id: str, payload: MasteryStatusRequest) -> dict[str, Any]:
    try:
        return get_exam_practice_store().set_mastery_status(question_id, payload.mastery_status)
    except Exception as exc:
        _raise_domain_error(exc)


@router.get("/statistics/wrong")
def wrong_statistics() -> dict[str, Any]:
    return get_exam_practice_store().wrong_statistics()


@router.get("/statistics/chapters")
def chapter_statistics(
    subject_id: str | None = Query(default=None, max_length=256),
) -> list[dict[str, Any]]:
    return get_exam_practice_store().chapter_statistics(subject_id=subject_id)


@router.post("/insights/weak-points")
def weak_points(payload: WeakPointsRequest | None = None) -> dict[str, Any]:
    """Return deterministic chapter-level weak-point cards for later AI enrichment."""
    try:
        cards = get_exam_practice_store().weak_points(**(payload.model_dump() if payload else {}))
        return {"items": cards, "total": len(cards)}
    except Exception as exc:
        _raise_domain_error(exc)
