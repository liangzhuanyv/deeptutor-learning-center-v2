#!/usr/bin/env python3
"""Seed the standalone Exam Practice DB from the two GitHub question banks already imported to DeepTutor.

This intentionally reads only the managed `turn_id=imported-v1` entries created by
`scripts/import_exam_question_banks.py`; those entries originated from:
- 0xminmin2025/fund-exam
- NomadJoe-1993/sec-exam

It is idempotent.  It does not alter `chat_history.db` or Question Notebook.

Examples (inside the DeepTutor container):
  python scripts/import_exam_practice_from_notebook.py
  python scripts/import_exam_practice_from_notebook.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from deeptutor.services.exam_practice import ExamPracticeStore

DEFAULT_SOURCE_DB = Path("/app/data/user/chat_history.db")
DEFAULT_EXAM_DB = Path("/app/data/user/exam_practice.db")
IMPORT_TURN_ID = "imported-v1"

BANKS: dict[str, dict[str, Any]] = {
    "fund": {
        "id": "github-fund-exam-v1",
        "name": "基金从业考试题库",
        "source": "github:0xminmin2025/fund-exam",
        "version": "imported-v1",
        "metadata": {"repository": "0xminmin2025/fund-exam"},
    },
    "securities": {
        "id": "github-sec-exam-v1",
        "name": "证券从业考试题库",
        "source": "github:NomadJoe-1993/sec-exam",
        "version": "imported-v1",
        "metadata": {"repository": "NomadJoe-1993/sec-exam"},
    },
}


def clean(value: Any) -> str:
    return "" if value is None else str(value).replace("\u00a0", " ").strip()


def source_parts(explanation: str) -> tuple[str, str]:
    """Split legacy source marker without treating it as a learner-facing explanation."""
    marker = "\n\n来源："
    if marker in explanation:
        body, source = explanation.rsplit(marker, 1)
        return body.strip(), source.strip()
    if explanation.startswith("来源："):
        return "", explanation.removeprefix("来源：").strip()
    return explanation.strip(), ""


def bank_kind(subject: str) -> str:
    return "fund" if subject.startswith("基金") else "securities"


def derive_chapter(kind: str, subject: str, source: str) -> tuple[str, str]:
    """Use source-file chapters when present; Fund raw files have no chapter field."""
    filename = source.rsplit("·", 1)[-1].strip().removesuffix(".json")
    if kind == "fund":
        # The upstream Fund JSON is only partitioned by exam subject.  Keep this
        # explicit instead of hallucinating a chapter taxonomy before AI syllabus
        # classification is available.
        return "原题库未标注章节", f"{subject}/原题库未标注章节"
    match = re.search(r"(?:^|[_-])(?:ch|fl)(\d+)([ab])?(?:$|[_-])", filename, re.I)
    if match:
        suffix = match.group(2) or ""
        chapter = f"第{int(match.group(1))}章{suffix.upper()}"
        return chapter, f"{subject}/{chapter}"
    if filename.startswith(("zt_", "real_")):
        return "历年真题", f"{subject}/历年真题"
    if filename.startswith(("sim_", "sprint_")):
        return "模拟与冲刺", f"{subject}/模拟与冲刺"
    return "综合题库", f"{subject}/综合题库"


def load_questions(source_db: Path) -> dict[str, list[dict[str, Any]]]:
    if not source_db.exists():
        raise FileNotFoundError(f"Question Notebook DB not found: {source_db}")
    grouped: dict[str, list[dict[str, Any]]] = {"fund": [], "securities": []}
    with sqlite3.connect(source_db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT question_id, question, question_type, options_json, correct_answer, explanation
            FROM notebook_entries
            WHERE turn_id = ?
            ORDER BY id
            """,
            (IMPORT_TURN_ID,),
        ).fetchall()
    for row in rows:
        question_type, separator, subject = clean(row["question_type"]).partition(" · ")
        subject = subject if separator else "未分类"
        kind = bank_kind(subject)
        try:
            options = json.loads(row["options_json"] or "{}")
        except json.JSONDecodeError:
            options = {}
        explanation, source = source_parts(clean(row["explanation"]))
        chapter, chapter_path = derive_chapter(kind, subject, source)
        grouped[kind].append(
            {
                "external_id": clean(row["question_id"]),
                "subject": subject,
                "subject_external_id": subject,
                "chapter": chapter,
                "chapter_external_id": f"{subject}:{chapter}",
                "chapter_path": chapter_path,
                "question_type": question_type or "单选",
                "stem": clean(row["question"]),
                "options": options,
                "source_answer": clean(row["correct_answer"]),
                "answer_status": "verified" if clean(row["correct_answer"]) else "missing",
                "source_explanation": explanation,
                "source": source,
                "metadata": {"notebook_turn_id": IMPORT_TURN_ID},
            }
        )
    return grouped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE_DB)
    parser.add_argument("--exam-db", type=Path, default=DEFAULT_EXAM_DB)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    grouped = load_questions(args.source_db)
    all_questions = [question for questions in grouped.values() for question in questions]
    print(f"Found {len(all_questions)} managed GitHub-imported questions")
    print("  " + ", ".join(f"{kind}={len(items)}" for kind, items in grouped.items()))
    print(f"  missing answers={sum(not q['source_answer'] for q in all_questions)}")
    print(f"  missing explanations={sum(not q['source_explanation'] for q in all_questions)}")
    print("  chapters=" + ", ".join(f"{name}:{count}" for name, count in Counter(q['chapter'] for q in all_questions).most_common(12)))
    if args.dry_run:
        return

    store = ExamPracticeStore(args.exam_db)
    for kind, questions in grouped.items():
        result = store.import_bank(BANKS[kind], questions)
        print(f"Imported {kind}: {json.dumps(result, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
