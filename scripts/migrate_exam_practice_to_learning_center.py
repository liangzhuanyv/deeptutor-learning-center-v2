#!/usr/bin/env python3
"""Migrate legacy Exam Practice data into the generic Learning Center v2 DB."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# ``python /app/scripts/...`` sets sys.path to /app/scripts, unlike
# ``python scripts/...`` from a checkout.  Make the packaged Docker entrypoint
# explicitly resolve the application root without relying on cwd.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from deeptutor.services.learning_center.legacy_migration import LegacyExamPracticeMigrator


def _write_report(report: dict, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    text_path = destination.with_suffix(".txt")
    source = report["source"]
    target = report.get("target", report.get("projected_target", {}))
    lines = [
        f"Migration: {report['migration_name']}", f"Mode: {report['mode']}",
        f"Source questions: {source['questions']}", f"Target questions: {target.get('questions', 'n/a')}",
        f"Source sessions/attempts: {source['practice_sessions']}/{source['attempts']}",
        f"Target sessions/attempts: {target.get('practice_sessions', 'n/a')}/{target.get('attempts', 'n/a')}",
    ]
    comparison = report.get("comparison")
    if comparison is not None:
        lines.append(f"Verification passed: {comparison['passed']}")
        lines.append(f"Count mismatches: {len(comparison['count_mismatches'])}")
        lines.append(f"Question sample differences: {len(comparison['question_sample']['differences'])}")
        lines.append(f"Session sample differences: {len(comparison['session_sample']['differences'])}")
        lines.append(f"Wrong-question differences: {len(comparison['wrong_question_differences'])}")
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", required=True, type=Path, help="Read-only legacy exam_practice.db")
    parser.add_argument("--target-db", required=True, type=Path, help="Independent learning_center.db")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Audit source and project counts without writing target")
    mode.add_argument("--verify-only", action="store_true", help="Verify an existing target without writing either DB")
    parser.add_argument("--resume", action="store_true", help="Resume/re-run idempotently using migration mappings")
    parser.add_argument("--report", type=Path, required=True, help="Write JSON report and matching .txt summary")
    args = parser.parse_args()

    migrator = LegacyExamPracticeMigrator(args.source_db, args.target_db, resume=args.resume)
    if args.dry_run:
        result = migrator.dry_run()
    elif args.verify_only:
        result = migrator.verify()
    else:
        result = migrator.migrate()
    _write_report(result.report, args.report)
    print(json.dumps(result.report, ensure_ascii=False, indent=2))
    return 0 if result.report.get("comparison", {"passed": True})["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
