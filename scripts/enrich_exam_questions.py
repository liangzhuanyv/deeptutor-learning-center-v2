#!/usr/bin/env python3
"""Fill missing exam-question answers and explanations with a configured LLM.

The script reads a standalone exam-practice SQLite DB. It never overwrites an
existing answer: missing answers are retained as AI suggestions and are always
marked for human review. In the primary ``exam_questions`` schema, generated
explanations are written only to ``ai_explanation`` with ``metadata_json``
provenance.

Examples:
    python scripts/enrich_exam_questions.py --db data/exam_practice.db --dry-run
    python scripts/enrich_exam_questions.py --db data/exam_practice.db \\
        --profile-id llm-profile-pie-xian --model gemini-3.5-flash --resume
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from deeptutor.services.exam_enrichment import (
    ExamEnrichmentClient,
    ExamEnrichmentService,
    ExamPracticeSQLiteStore,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI-enrich missing exam answers and explanations")
    parser.add_argument(
        "--db", required=True, type=Path, help="Path to the exam-practice SQLite DB"
    )
    parser.add_argument(
        "--table",
        default="exam_questions",
        help="Question table name (default: exam_questions)",
    )
    parser.add_argument(
        "--profile-id",
        default="llm-profile-pie-xian",
        help=(
            "LLM profile ID in DeepTutor model_catalog.json "
            "(default/recommended: llm-profile-pie-xian)"
        ),
    )
    parser.add_argument(
        "--provider",
        help="Optional binding/provider override; defaults to the selected profile binding",
    )
    parser.add_argument(
        "--model",
        default="gemini-3.5-flash",
        help="Model override (default/recommended: gemini-3.5-flash)",
    )
    parser.add_argument(
        "--rpm",
        type=int,
        default=72,
        choices=range(1, 81),
        metavar="1-80",
        help="Maximum request starts per minute (default: 72; hard cap: 80)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=12, help="In-flight requests (default: 12)"
    )
    parser.add_argument(
        "--max-attempts", type=int, default=4, help="Attempts per question (default: 4)"
    )
    parser.add_argument("--limit", type=int, help="Maximum candidate questions to process")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report candidates without LLM calls or writes"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Safely continue unfinished fields marked in metadata_json.ai_enrichment",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser


async def _run(args: argparse.Namespace) -> int:
    store = ExamPracticeSQLiteStore(args.db, table=args.table)
    client = ExamEnrichmentClient(
        profile_id=args.profile_id, provider=args.provider, model=args.model
    )
    service = ExamEnrichmentService(
        store,
        client,
        requests_per_minute=args.rpm,
        concurrency=args.concurrency,
        max_attempts=args.max_attempts,
    )
    summary = await service.run(dry_run=args.dry_run, resume=args.resume, limit=args.limit)
    logging.getLogger(__name__).info(
        "summary selected=%d completed=%d suggested_answers=%d generated_explanations=%d "
        "failed=%d dry_run=%d",
        summary.selected,
        summary.completed,
        summary.suggested_answers,
        summary.generated_explanations,
        summary.failed,
        summary.dry_run,
    )
    return 1 if summary.failed else 0


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
