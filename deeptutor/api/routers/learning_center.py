"""Authenticated API skeleton for the generic Learning Center v2 domain.

This router talks only to ``learning_center.db``.  During Phases 1-2 it never
reads from or writes to the legacy exam-practice database, so the existing
``/api/v1/exam-practice`` contract remains an independent compatibility path.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from deeptutor.services.learning_center import (
    LearningCenterNotFoundError,
    LearningCenterValidationError,
    get_learning_center_repository,
)

router = APIRouter()


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    kind: Literal["exam", "course", "book", "skill", "other"] = "other"
    external_id: str = Field(default="", max_length=512)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=500)
    kind: Literal["exam", "course", "book", "skill", "other"] | None = None
    aliases: list[str] | None = Field(default=None, max_length=30)
    metadata: dict[str, Any] | None = None


class ModuleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    path: str | None = Field(default=None, max_length=2000)
    parent_id: str | None = Field(default=None, max_length=256)
    external_id: str = Field(default="", max_length=512)
    sort_order: int = Field(default=0, ge=-1_000_000, le=1_000_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgePointCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    module_id: str | None = Field(default=None, max_length=256)
    description: str = Field(default="", max_length=10_000)
    external_id: str = Field(default="", max_length=512)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _raise_domain_error(exc: Exception) -> None:
    if isinstance(exc, LearningCenterNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, LearningCenterValidationError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if isinstance(exc, sqlite3.IntegrityError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflicting learning-center record") from exc
    raise exc


@router.get("/projects")
def list_projects() -> list[dict[str, Any]]:
    return get_learning_center_repository().list_projects()


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreateRequest) -> dict[str, Any]:
    try:
        return get_learning_center_repository().create_project(**payload.model_dump())
    except Exception as exc:
        _raise_domain_error(exc)
        raise AssertionError("unreachable")


@router.get("/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    try:
        return get_learning_center_repository().get_project(project_id)
    except Exception as exc:
        _raise_domain_error(exc)
        raise AssertionError("unreachable")


@router.patch("/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdateRequest) -> dict[str, Any]:
    try:
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise LearningCenterValidationError("At least one project field is required")
        return get_learning_center_repository().update_project(project_id, **changes)
    except Exception as exc:
        _raise_domain_error(exc)
        raise AssertionError("unreachable")


@router.get("/projects/{project_id}/modules")
def list_modules(project_id: str) -> list[dict[str, Any]]:
    try:
        return get_learning_center_repository().list_modules(project_id)
    except Exception as exc:
        _raise_domain_error(exc)
        raise AssertionError("unreachable")


@router.post("/projects/{project_id}/modules", status_code=status.HTTP_201_CREATED)
def create_module(project_id: str, payload: ModuleCreateRequest) -> dict[str, Any]:
    try:
        return get_learning_center_repository().create_module(project_id=project_id, **payload.model_dump())
    except Exception as exc:
        _raise_domain_error(exc)
        raise AssertionError("unreachable")


@router.get("/projects/{project_id}/knowledge-points")
def list_knowledge_points(project_id: str) -> list[dict[str, Any]]:
    try:
        return get_learning_center_repository().list_knowledge_points(project_id)
    except Exception as exc:
        _raise_domain_error(exc)
        raise AssertionError("unreachable")


@router.post("/projects/{project_id}/knowledge-points", status_code=status.HTTP_201_CREATED)
def create_knowledge_point(project_id: str, payload: KnowledgePointCreateRequest) -> dict[str, Any]:
    try:
        return get_learning_center_repository().create_knowledge_point(project_id=project_id, **payload.model_dump())
    except Exception as exc:
        _raise_domain_error(exc)
        raise AssertionError("unreachable")


@router.get("/questions/{question_id}")
def get_question(question_id: str) -> dict[str, Any]:
    try:
        return get_learning_center_repository().get_question(question_id)
    except Exception as exc:
        _raise_domain_error(exc)
        raise AssertionError("unreachable")


@router.get("/questions/{question_id}/provenance")
def get_question_provenance(question_id: str) -> dict[str, Any]:
    try:
        return get_learning_center_repository().get_question_provenance(question_id)
    except Exception as exc:
        _raise_domain_error(exc)
        raise AssertionError("unreachable")

# Import-center endpoints are appended here so the canonical learning-center
# prefix keeps one authenticated router while the import service remains a
# separate domain package.
from deeptutor.services.learning_center.imports import (  # noqa: E402
    ImportBatchNotFoundError,
    ImportBatchStateError,
    LearningImportRequest,
    LearningImportService,
    ImportEnrichmentRequest,
    ImportApprovalRequest,
)


class MappingUpdateRequest(BaseModel):
    mapping: dict[str, Any] = Field(default_factory=dict)


def _import_service() -> LearningImportService:
    return LearningImportService(get_learning_center_repository())


def _raise_import_error(exc: Exception) -> None:
    if isinstance(exc, ImportBatchNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ImportBatchStateError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    _raise_domain_error(exc)


@router.get('/imports/schema')
def import_schema() -> dict[str, Any]:
    return LearningImportRequest.model_json_schema()


@router.post('/imports/analyze', status_code=status.HTTP_201_CREATED)
def analyze_import(payload: LearningImportRequest) -> dict[str, Any]:
    try:
        return _import_service().analyze(payload)
    except Exception as exc:
        _raise_import_error(exc)
        raise AssertionError('unreachable')


@router.get('/imports/{batch_id}')
def get_import(batch_id: str) -> dict[str, Any]:
    try:
        return _import_service().get_batch(batch_id)
    except Exception as exc:
        _raise_import_error(exc)
        raise AssertionError('unreachable')


@router.get('/imports/{batch_id}/preview')
def get_import_preview(batch_id: str) -> dict[str, Any]:
    try:
        return _import_service().preview(batch_id)
    except Exception as exc:
        _raise_import_error(exc)
        raise AssertionError('unreachable')


@router.get('/imports/{batch_id}/quality-report')
def get_import_quality(batch_id: str) -> dict[str, Any]:
    try:
        return _import_service().quality_report(batch_id)
    except Exception as exc:
        _raise_import_error(exc)
        raise AssertionError('unreachable')


@router.patch('/imports/{batch_id}/mapping')
def update_import_mapping(batch_id: str, payload: MappingUpdateRequest) -> dict[str, Any]:
    try:
        return _import_service().update_mapping(batch_id, payload.mapping)
    except Exception as exc:
        _raise_import_error(exc)
        raise AssertionError('unreachable')


@router.post('/imports/{batch_id}/approve')
def approve_import(batch_id: str, payload: ImportApprovalRequest | None = None) -> dict[str, Any]:
    try:
        approval = payload or ImportApprovalRequest()
        return _import_service().approve(batch_id, **approval.model_dump())
    except Exception as exc:
        _raise_import_error(exc)
        raise AssertionError('unreachable')


@router.post('/imports/{batch_id}/commit')
def commit_import(batch_id: str) -> dict[str, Any]:
    try:
        return _import_service().commit(batch_id)
    except Exception as exc:
        _raise_import_error(exc)
        raise AssertionError('unreachable')


@router.post('/imports/{batch_id}/cancel')
def cancel_import(batch_id: str) -> dict[str, Any]:
    try:
        return _import_service().cancel(batch_id)
    except Exception as exc:
        _raise_import_error(exc)
        raise AssertionError('unreachable')


@router.post('/imports/{batch_id}/rollback')
def rollback_import(batch_id: str) -> dict[str, Any]:
    try:
        return _import_service().rollback(batch_id)
    except Exception as exc:
        _raise_import_error(exc)
        raise AssertionError('unreachable')

@router.post('/imports/{batch_id}/enrich')
async def enrich_import(batch_id: str, payload: ImportEnrichmentRequest) -> dict[str, Any]:
    try:
        return await _import_service().enrich(batch_id, **payload.model_dump())
    except Exception as exc:
        _raise_import_error(exc)
        raise AssertionError('unreachable')

# Dashboard APIs remain read-only projections over learning_center.db.  They
# intentionally never consult the legacy exam-practice database.
from deeptutor.services.learning_center.dashboard import LearningCenterDashboardService  # noqa: E402


def _dashboard_service() -> LearningCenterDashboardService:
    return LearningCenterDashboardService(get_learning_center_repository())


@router.get('/dashboard/overview')
def dashboard_overview() -> dict[str, Any]:
    return _dashboard_service().overview()


@router.get('/dashboard/projects')
def dashboard_projects() -> list[dict[str, Any]]:
    return _dashboard_service().project_summaries()


@router.get('/dashboard/trends')
def dashboard_trends(days: int = 30) -> list[dict[str, Any]]:
    return _dashboard_service().trends(days)


@router.get('/dashboard/mastery')
def dashboard_mastery_distribution() -> list[dict[str, Any]]:
    return _dashboard_service().mastery_distribution()


@router.get('/dashboard/modules')
def dashboard_module_comparison(project_id: str | None = None) -> list[dict[str, Any]]:
    return _dashboard_service().module_comparison(project_id)


@router.get('/dashboard/heatmap')
def dashboard_error_heatmap(days: int = 30) -> list[dict[str, Any]]:
    return _dashboard_service().error_heatmap(days)

# Phase 6 practice session API.  Session reads apply answer redaction by mode.
from deeptutor.services.learning_center.practice import LearningPracticeService  # noqa: E402


class PracticeProposalRequest(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=256)
    module_id: str | None = Field(default=None, max_length=256)
    knowledge_point_id: str | None = Field(default=None, max_length=256)
    question_types: list[str] = Field(default_factory=list, max_length=20)
    difficulty: str | None = Field(default=None, max_length=128)
    status: str | None = Field(default=None, max_length=128)
    limit: int = Field(default=20, ge=1, le=200)


class PracticeStartRequest(PracticeProposalRequest):
    mode: Literal['learning', 'exam']
    title: str = Field(default='', max_length=500)
    time_budget_minutes: int | None = Field(default=None, ge=1, le=600)
    question_ids: list[str] = Field(default_factory=list, max_length=200)


class PracticeAutosaveItem(BaseModel):
    id: str = Field(..., min_length=1, max_length=256)
    user_answer: str = Field(default='', max_length=10_000)
    confidence: Literal['', 'sure', 'uncertain', 'guess'] = ''
    marked_for_review: bool = False
    elapsed_seconds: float | None = Field(default=None, ge=0, le=86_400)
    eliminated_option_keys: list[str] = Field(default_factory=list, max_length=20)


class PracticeSubmitRequest(BaseModel):
    answers: list[PracticeAutosaveItem] = Field(default_factory=list, max_length=200)
    finish: bool = False


def _practice_service() -> LearningPracticeService:
    return LearningPracticeService(get_learning_center_repository())


@router.post('/practice/proposal')
def practice_proposal(payload: PracticeProposalRequest) -> dict[str, Any]:
    try:
        return _practice_service().propose(**payload.model_dump())
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.post('/practice/sessions', status_code=status.HTTP_201_CREATED)
def start_practice_session(payload: PracticeStartRequest) -> dict[str, Any]:
    try:
        return _practice_service().start(**payload.model_dump())
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.get('/practice/sessions/{session_id}')
def get_practice_session(session_id: str) -> dict[str, Any]:
    try:
        return _practice_service().get(session_id)
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.get('/practice/resumable')
def list_resumable_practice_sessions(project_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    try:
        return _practice_service().list_resumable_sessions(project_id=project_id, limit=limit)
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.post('/practice/sessions/archive-stale')
def archive_stale_practice_sessions(older_than_seconds: float = 86400, only_empty: bool = True) -> dict[str, Any]:
    try:
        return _practice_service().archive_stale_sessions(
            older_than_seconds=older_than_seconds,
            only_empty=only_empty,
        )
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.patch('/practice/sessions/{session_id}')
def autosave_practice_session(session_id: str, items: list[PracticeAutosaveItem]) -> dict[str, Any]:
    try:
        return _practice_service().autosave(session_id, [item.model_dump() for item in items])
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.post('/practice/sessions/{session_id}/submit')
def submit_practice_session(session_id: str, payload: PracticeSubmitRequest) -> dict[str, Any]:
    try:
        return _practice_service().submit(session_id, [item.model_dump() for item in payload.answers], finish=payload.finish)
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


class PracticeBookmarkRequest(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=256)
    question_id: str = Field(..., min_length=1, max_length=256)
    bookmarked: bool = True
    note: str = Field(default='', max_length=2_000)


class PracticeDiscussionMessageRequest(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=256)
    content: str = Field(..., min_length=1, max_length=10_000)
    role: Literal['user', 'assistant', 'system'] = 'user'


@router.post('/practice/sessions/{session_id}/pause')
def pause_practice_session(session_id: str) -> dict[str, Any]:
    try:
        return _practice_service().pause(session_id)
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.post('/practice/sessions/{session_id}/resume')
def resume_practice_session(session_id: str) -> dict[str, Any]:
    try:
        return _practice_service().resume(session_id)
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.get('/practice/sessions/{session_id}/report')
def practice_session_report(session_id: str) -> dict[str, Any]:
    try:
        return _practice_service().report(session_id)
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.post('/practice/bookmarks')
def set_practice_bookmark(payload: PracticeBookmarkRequest) -> dict[str, Any] | None:
    try:
        return _practice_service().set_bookmark(**payload.model_dump())
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.get('/practice/questions/{question_id}/bookmark')
def get_practice_bookmark(question_id: str) -> dict[str, Any] | None:
    try:
        return _practice_service().get_bookmark(question_id)
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.get('/practice/questions/{question_id}/similar')
def similar_practice_questions(question_id: str, project_id: str, limit: int = 5) -> list[dict[str, Any]]:
    try:
        return _practice_service().similar(project_id=project_id, question_id=question_id, limit=limit)
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.get('/practice/questions/{question_id}/discussion')
def get_practice_discussion(question_id: str, project_id: str) -> dict[str, Any]:
    try:
        return _practice_service().discussion(project_id=project_id, question_id=question_id)
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.post('/practice/questions/{question_id}/discussion')
def add_practice_discussion(question_id: str, payload: PracticeDiscussionMessageRequest) -> dict[str, Any]:
    try:
        return _practice_service().add_discussion_message(question_id=question_id, **payload.model_dump())
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


class PracticeAIDiscussionRequest(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=256)
    message: str = Field(..., min_length=1, max_length=8_000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=20)


def _learning_discussion_context(question: dict[str, Any]) -> str:
    def clip(value: Any, maximum: int = 10_000) -> str:
        text = str(value or "").strip()
        return text if len(text) <= maximum else text[: maximum] + "…"

    options = question.get("options") if isinstance(question.get("options"), dict) else {}
    option_text = "\n".join(f"{key}. {clip(value, 2_000)}" for key, value in sorted(options.items()))
    return "\n".join(
        [
            f"模块：{clip(question.get('module_path'), 500) or '未归类'}",
            f"题型：{clip(question.get('question_type'), 100)}",
            f"题目：{clip(question.get('stem'))}",
            f"选项：\n{option_text}" if option_text else "选项：（无）",
            f"标准答案：{clip(question.get('source_answer'), 500) or '待复核'}",
            f"现有解析：{clip(question.get('explanation'))}",
        ]
    )


@router.post('/practice/questions/{question_id}/ai-discussion')
async def discuss_practice_question(question_id: str, payload: PracticeAIDiscussionRequest) -> dict[str, Any]:
    """AI tutor reply for one Learning Center question; also persists the turn."""
    from deeptutor.services.llm.client import LLMClient
    from deeptutor.services.llm.config import get_llm_config

    try:
        question = _practice_service().question_discussion_context(
            project_id=payload.project_id,
            question_id=question_id,
        )
    except Exception as exc:
        _raise_domain_error(exc)
        raise AssertionError('unreachable')

    # Persist user message first so history survives even if the model fails.
    try:
        _practice_service().add_discussion_message(
            project_id=payload.project_id,
            question_id=question_id,
            content=payload.message,
            role='user',
        )
    except Exception as exc:
        _raise_domain_error(exc)
        raise AssertionError('unreachable')

    system_prompt = (
        "You are a patient Chinese exam tutor for DeepTutor Learning Center. "
        "Discuss only the supplied practice question. Explain reasoning, "
        "distinguish the verified source answer from any AI-generated explanation, "
        "and admit uncertainty rather than inventing facts. Be concise by default, "
        "but answer the learner's actual question directly.\n\n"
        "Practice-question context:\n"
        + _learning_discussion_context(question)
    )
    history = []
    for item in payload.history[-20:]:
        role = str(item.get('role') or '')
        content = str(item.get('content') or '').strip()
        if role in {'user', 'assistant'} and content:
            history.append({'role': role, 'content': content})
    try:
        cfg = get_llm_config()
        client = LLMClient(cfg)
        reply = await client.complete(
            payload.message.strip(),
            system_prompt=system_prompt,
            history=history,
            max_retries=2,
            temperature=0.2,
            max_tokens=1_000,
        )
        text = (reply or '').strip() or '这道题我暂时没有生成有效回复，请换一种问法。'
        provider = getattr(cfg, 'provider', '') or getattr(cfg, 'name', '') or 'llm'
        model = getattr(cfg, 'model', '') or ''
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f'AI discussion is temporarily unavailable: {exc}',
        ) from exc

    try:
        discussion = _practice_service().add_discussion_message(
            project_id=payload.project_id,
            question_id=question_id,
            content=text,
            role='assistant',
            provider=str(provider),
            model=str(model),
        )
    except Exception as exc:
        _raise_domain_error(exc)
        raise AssertionError('unreachable')
    return {'reply': text, 'discussion': discussion}

# Phase 7 evidence-based mastery and review APIs.
from deeptutor.services.learning_center.mastery import LearningMasteryService  # noqa: E402


class MasteryOverrideRequest(BaseModel):
    mastered: bool = True
    note: str = Field(default='', max_length=2_000)


def _mastery_service() -> LearningMasteryService:
    return LearningMasteryService(get_learning_center_repository())


@router.get('/questions/{question_id}/attempts')
def question_attempt_history(question_id: str) -> dict[str, Any]:
    try:
        return _mastery_service().question_detail(question_id)
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.post('/questions/{question_id}/mastery')
def set_question_mastery(question_id: str, payload: MasteryOverrideRequest) -> dict[str, Any]:
    try:
        return _mastery_service().set_question_override(question_id=question_id, **payload.model_dump())
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.get('/wrong-questions')
def wrong_questions(project_id: str, module_id: str | None = None, knowledge_point_id: str | None = None, filter: str = 'all_wrong') -> list[dict[str, Any]]:
    try:
        return _mastery_service().review_queue(project_id=project_id, module_id=module_id, knowledge_point_id=knowledge_point_id, filter=filter)
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.get('/review-queue')
def review_queue(project_id: str, module_id: str | None = None, knowledge_point_id: str | None = None, filter: str = 'due') -> list[dict[str, Any]]:
    try:
        return _mastery_service().review_queue(project_id=project_id, module_id=module_id, knowledge_point_id=knowledge_point_id, filter=filter)
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.get('/mastery/knowledge-points/{knowledge_point_id}')
def knowledge_mastery(knowledge_point_id: str) -> dict[str, Any]:
    try:
        return _mastery_service().knowledge_summary(knowledge_point_id)
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.post('/mastery/knowledge-points/{knowledge_point_id}/override')
def set_knowledge_mastery(knowledge_point_id: str, payload: MasteryOverrideRequest) -> dict[str, Any]:
    try:
        return _mastery_service().set_knowledge_override(knowledge_point_id=knowledge_point_id, **payload.model_dump())
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')


@router.delete('/mastery/knowledge-points/{knowledge_point_id}/override')
def clear_knowledge_mastery(knowledge_point_id: str, note: str = '') -> dict[str, Any]:
    try:
        return _mastery_service().set_knowledge_override(knowledge_point_id=knowledge_point_id, mastered=False, note=note)
    except Exception as exc:
        _raise_domain_error(exc); raise AssertionError('unreachable')

# Phase 8 advisory recommendation center.
from deeptutor.services.learning_center.recommendations import LearningRecommendationService  # noqa: E402

class RecommendationGenerateRequest(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=256)
    trigger: Literal['dashboard_open','requested','practice_completion','mock_exam_completion','repeated_errors','manual_mastery_error','import_completion','time_budget'] = 'requested'
    time_budget_text: str = Field(default='', max_length=500)
class RecommendationDecisionRequest(BaseModel):
    action: Literal['accepted','edited_accepted','ignored','deferred','reduced']
    payload: dict[str, Any] = Field(default_factory=dict)
def _recommendation_service() -> LearningRecommendationService: return LearningRecommendationService(get_learning_center_repository())
@router.get('/recommendations')
def list_recommendations(project_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]: return _recommendation_service().list(project_id=project_id,limit=limit)
@router.post('/recommendations/generate')
def generate_recommendations(payload: RecommendationGenerateRequest) -> list[dict[str, Any]]:
    try: return _recommendation_service().generate(**payload.model_dump())
    except Exception as exc: _raise_domain_error(exc); raise AssertionError('unreachable')
@router.post('/recommendations/{recommendation_id}/accept')
def accept_recommendation(recommendation_id: str, payload: RecommendationDecisionRequest) -> dict[str, Any]:
    try:
        action = payload.action if payload.action in {'accepted','edited_accepted'} else 'accepted'
        return _recommendation_service().decide(recommendation_id=recommendation_id,action=action,payload=payload.payload)
    except Exception as exc: _raise_domain_error(exc); raise AssertionError('unreachable')
@router.post('/recommendations/{recommendation_id}/ignore')
def ignore_recommendation(recommendation_id: str, payload: RecommendationDecisionRequest) -> dict[str, Any]:
    try: return _recommendation_service().decide(recommendation_id=recommendation_id,action='ignored',payload=payload.payload)
    except Exception as exc: _raise_domain_error(exc); raise AssertionError('unreachable')
@router.post('/recommendations/{recommendation_id}/defer')
def defer_recommendation(recommendation_id: str, payload: RecommendationDecisionRequest) -> dict[str, Any]:
    try: return _recommendation_service().decide(recommendation_id=recommendation_id,action='deferred',payload=payload.payload)
    except Exception as exc: _raise_domain_error(exc); raise AssertionError('unreachable')

from deeptutor.services.learning_center.analytics import LearningAnalyticsService  # noqa: E402
def _analytics_service() -> LearningAnalyticsService: return LearningAnalyticsService(get_learning_center_repository())
@router.get('/analytics/knowledge-heatmap')
def analytics_knowledge_heatmap(project_id: str | None = None) -> list[dict[str, Any]]: return _analytics_service().knowledge_heatmap(project_id)
@router.get('/analytics/confidence')
def analytics_confidence(project_id: str | None = None) -> list[dict[str, Any]]: return _analytics_service().confidence(project_id)
@router.get('/analytics/response-time')
def analytics_response_time(project_id: str | None = None) -> list[dict[str, Any]]: return _analytics_service().response_time(project_id)
@router.get('/analytics/error-reasons')
def analytics_error_reasons(project_id: str | None = None) -> list[dict[str, Any]]: return _analytics_service().error_reasons(project_id)
@router.get('/analytics/content-mix')
def analytics_content_mix(project_id: str | None = None) -> dict[str, int]: return _analytics_service().content_mix(project_id)
