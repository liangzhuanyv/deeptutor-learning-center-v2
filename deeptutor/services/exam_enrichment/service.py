"""Asynchronous, rate-limited batch service for exam enrichment."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import random
import time
from typing import TypeVar

from deeptutor.services.llm.exceptions import LLMRateLimitError

from .client import ExamEnrichmentClient
from .models import EnrichmentResult, EnrichmentSummary, ExamQuestion
from .prompts import build_prompt
from .store import ExamPracticeSQLiteStore

logger = logging.getLogger(__name__)

T = TypeVar("T")
ProgressCallback = Callable[[str], None]


class RequestRateLimiter:
    """Evenly spaces request starts, preventing bursty RPM overshoots."""

    def __init__(self, requests_per_minute: int) -> None:
        if not 1 <= requests_per_minute <= 80:
            raise ValueError("requests_per_minute must be between 1 and 80")
        self.interval = 60.0 / requests_per_minute
        self._next_start = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            scheduled = max(now, self._next_start)
            self._next_start = scheduled + self.interval
        delay = scheduled - now
        if delay > 0:
            await asyncio.sleep(delay)


@dataclass(frozen=True)
class _WorkResult:
    question: ExamQuestion
    result: EnrichmentResult | None = None
    error: Exception | None = None


class ExamEnrichmentService:
    """Coordinate schema-validated LLM calls and conservative SQLite writes."""

    def __init__(
        self,
        store: ExamPracticeSQLiteStore,
        client: ExamEnrichmentClient,
        *,
        requests_per_minute: int = 72,
        concurrency: int = 12,
        max_attempts: int = 4,
        progress: ProgressCallback | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.store = store
        self.client = client
        self.max_attempts = max_attempts
        self._semaphore = asyncio.Semaphore(concurrency)
        self._limiter = RequestRateLimiter(requests_per_minute)
        self._progress = progress or logger.info

    async def run(
        self,
        *,
        dry_run: bool = False,
        resume: bool = False,
        limit: int | None = None,
    ) -> EnrichmentSummary:
        questions = self.store.iter_candidates(resume=resume, limit=limit)
        summary = EnrichmentSummary(selected=len(questions))
        if dry_run:
            summary.dry_run = len(questions)
            self._progress(f"dry-run: {len(questions)} questions would be enriched")
            return summary
        if not questions:
            self._progress("no exam questions need enrichment")
            return summary

        self._progress(f"enriching {len(questions)} questions")
        tasks = [asyncio.create_task(self._enrich_one(question)) for question in questions]
        for completed_count, task in enumerate(asyncio.as_completed(tasks), start=1):
            outcome = await task
            if outcome.error is not None:
                summary.failed += 1
                self._progress(
                    f"[{completed_count}/{len(questions)}] question={outcome.question.id}: "
                    f"failed: {outcome.error}"
                )
                continue
            assert outcome.result is not None
            answer_written, explanation_written = self.store.write_result(
                outcome.question, outcome.result
            )
            summary.completed += 1
            summary.suggested_answers += int(answer_written)
            summary.generated_explanations += int(explanation_written)
            self._progress(
                f"[{completed_count}/{len(questions)}] question={outcome.question.id}: "
                f"answer_suggested={answer_written} explanation_generated={explanation_written}"
            )
        return summary

    async def _enrich_one(self, question: ExamQuestion) -> _WorkResult:
        async with self._semaphore:
            try:
                payload = await self._request_with_retry(question)
                provider, model = self.client.resolved_provider_and_model()
                return _WorkResult(
                    question=question,
                    result=EnrichmentResult(
                        question_id=question.id,
                        payload=payload,
                        provider=provider,
                        model=model,
                        generated_at=datetime.now(UTC).isoformat(),
                    ),
                )
            except Exception as exc:  # a failed item must not cancel the batch
                return _WorkResult(question=question, error=exc)

    async def _request_with_retry(self, question: ExamQuestion):
        prompt = build_prompt(question)
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                await self._limiter.acquire()
                return await self.client.enrich(prompt)
            except Exception as exc:
                last_error = exc
                if attempt == self.max_attempts or not self._is_retryable(exc):
                    raise
                delay = self._retry_delay(exc, attempt)
                self._progress(
                    f"question={question.id}: attempt {attempt}/{self.max_attempts} failed "
                    f"({type(exc).__name__}); retrying in {delay:.1f}s"
                )
                await asyncio.sleep(delay)
        assert last_error is not None
        raise last_error

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        message = str(exc).lower()
        return (
            isinstance(exc, LLMRateLimitError)
            or status_code == 429
            or any(
                marker in message
                for marker in (
                    "429",
                    "rate limit",
                    "timeout",
                    "temporarily unavailable",
                    "overloaded",
                    "503",
                )
            )
            or isinstance(exc, ValueError)
        )

    @staticmethod
    def _retry_delay(exc: Exception, attempt: int) -> float:
        retry_after = getattr(exc, "retry_after", None)
        if isinstance(retry_after, (int, float)) and retry_after > 0:
            return min(float(retry_after), 120.0)
        return min(2.0 ** (attempt - 1) + random.uniform(0.0, 0.25), 60.0)
