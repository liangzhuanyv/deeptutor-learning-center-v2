#!/usr/bin/env python3
"""Import public Chinese fund/securities exam banks into DeepTutor's question bank.

The importer intentionally treats the existing Question Notebook as the UI
surface: imported questions live in two synthetic sessions, are grouped into
subject categories, and can be selected as context for follow-up questions.
It is idempotent for the two managed ``imported-v1`` batches.

Usage (inside the DeepTutor container):
    python scripts/import_exam_question_banks.py --db /app/data/user/chat_history.db

Use ``--dry-run`` to download, normalize, de-duplicate, and report counts
without changing the database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote
from urllib.request import Request, urlopen

USER_AGENT = "DeepTutor exam-bank importer/1.0"
IMPORT_TURN_ID = "imported-v1"

FUND_RAW_BASE = "https://raw.githubusercontent.com/0xminmin2025/fund-exam/main/"
SEC_API_ROOT = "https://api.github.com/repos/NomadJoe-1993/sec-exam/contents"
SEC_RAW_BASE = "https://raw.githubusercontent.com/NomadJoe-1993/sec-exam/main/"
FUND_FILES = {
    "q_fagui.json": ("fund", "基金从业·科目一 法规"),
    "q_zhengquan.json": ("fund", "基金从业·科目二 证券投资"),
    "q_simu.json": ("fund", "基金从业·科目三 私募股权"),
}


def fetch_bytes(url: str) -> bytes:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(request, timeout=60) as response:  # nosec B310 - fixed public URLs
                return response.read()
        except Exception as exc:  # network hiccups should not lose one file
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    assert last_error is not None
    raise last_error


def fetch_json(url: str) -> Any:
    return json.loads(fetch_bytes(url).decode("utf-8"))


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).replace("\u00a0", " ").strip()


def normalize_stem(value: str) -> str:
    return re.sub(r"\s+", "", value).strip()


def answer_text(value: Any) -> str:
    if isinstance(value, list):
        return "".join(clean_text(item) for item in value)
    return clean_text(value).replace("答案：", "").replace("答案:", "").strip()


def normalize_options(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        result: dict[str, str] = {}
        for key, text in value.items():
            key_text = clean_text(key).strip().rstrip("、.")
            if key_text:
                result[key_text] = clean_text(text)
        return result
    if isinstance(value, list):
        return {chr(ord("A") + index): clean_text(text) for index, text in enumerate(value)}
    return {}


def question_type(record: dict[str, Any], answer: str) -> str:
    raw = clean_text(record.get("type_cn") or record.get("question_type") or record.get("type"))
    if "多" in raw or len(re.sub(r"[^A-D]", "", answer)) > 1:
        return "多选"
    if "判断" in raw or raw.lower() in {"tf", "judge", "j", "true_false"}:
        return "判断"
    if "不定" in raw or raw.lower() in {"u", "uncertain"}:
        return "不定项"
    return "单选"


def make_question(
    record: dict[str, Any],
    *,
    subject: str,
    subject_label: str,
    source: str,
) -> dict[str, Any] | None:
    stem = clean_text(record.get("stem") or record.get("question") or record.get("q"))
    options = normalize_options(record.get("options") or record.get("choices") or record.get("c"))
    answer = answer_text(record.get("answer") if "answer" in record else record.get("a"))
    if not stem or not answer or len(options) < 1:
        return None
    explanation = clean_text(
        record.get("analysis")
        or record.get("explanation")
        or record.get("an")
        or record.get("explain")
    )
    return {
        "subject": subject,
        "subject_label": subject_label,
        "stem": stem,
        "options": options,
        "answer": answer,
        "explanation": explanation,
        "type": question_type(record, answer),
        "source": source,
    }


def iter_question_records(value: Any) -> Iterable[dict[str, Any]]:
    """Find question-shaped dicts in the varied securities-bank JSON files."""
    if isinstance(value, dict):
        has_stem = any(key in value for key in ("stem", "question", "q"))
        has_options = any(key in value for key in ("options", "choices", "c"))
        has_answer = any(key in value for key in ("answer", "a"))
        if has_stem and has_options and has_answer:
            yield value
            return
        for child in value.values():
            yield from iter_question_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_question_records(child)


def securities_subject(source: str, record: dict[str, Any]) -> tuple[str, str]:
    text = f"{source} {clean_text(record.get('subject'))} {clean_text(record.get('title'))}"
    if any(token in text for token in ("法律法规", "law", "法规", "zc_fl", "jxtk_zc_fl")):
        return "securities-law", "证券从业·法律法规"
    if any(token in text for token in ("金融基础", "金融市场基础知识", "fin", "金融市场")):
        return "securities-fin", "证券从业·金融基础"
    return "securities-mixed", "证券从业·综合题库"


def best_question(existing: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    def score(item: dict[str, Any]) -> tuple[int, int, int]:
        source = item["source"]
        return (
            1 if item["explanation"] else 0,
            len(item["explanation"]),
            1 if "2026" in source else 0,
        )

    return candidate if score(candidate) > score(existing) else existing


def load_fund_questions() -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for filename, (subject, subject_label) in FUND_FILES.items():
        data = fetch_json(FUND_RAW_BASE + filename)
        for record in data if isinstance(data, list) else []:
            question = make_question(
                record,
                subject=subject,
                subject_label=subject_label,
                source=f"0xminmin2025/fund-exam · {filename}",
            )
            if question is None:
                continue
            key = (subject_label, normalize_stem(question["stem"]))
            grouped[key] = best_question(grouped[key], question) if key in grouped else question
    return list(grouped.values())


def load_securities_questions() -> list[dict[str, Any]]:
    listing = fetch_json(SEC_API_ROOT)
    filenames = [
        item["name"]
        for item in listing
        if item.get("type") == "file"
        and item.get("name", "").endswith(".json")
        and item.get("name") not in {"access.json", "manifest.json"}
    ]
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for filename in filenames:
        try:
            data = fetch_json(SEC_RAW_BASE + quote(filename, safe="/"))
        except Exception as exc:  # tolerate a single malformed/public file
            print(f"[warn] skip {filename}: {exc}")
            continue
        for record in iter_question_records(data):
            subject, subject_label = securities_subject(filename, record)
            question = make_question(
                record,
                subject=subject,
                subject_label=subject_label,
                source=f"NomadJoe-1993/sec-exam · {filename}",
            )
            if question is None:
                continue
            key = (subject, normalize_stem(question["stem"]))
            grouped[key] = best_question(grouped[key], question) if key in grouped else question
    return list(grouped.values())


def add_source_marker(explanation: str, source: str) -> str:
    marker = f"\n\n来源：{source}"
    return explanation.strip() + marker if explanation.strip() else f"来源：{source}"


def ensure_category(conn: sqlite3.Connection, name: str, now: float) -> int:
    row = conn.execute("SELECT id FROM notebook_categories WHERE name = ?", (name,)).fetchone()
    if row:
        return int(row[0])
    cursor = conn.execute(
        "INSERT INTO notebook_categories (name, created_at) VALUES (?, ?)",
        (name, now),
    )
    return int(cursor.lastrowid)


def create_or_update_session(conn: sqlite3.Connection, session_id: str, title: str, now: float) -> None:
    conn.execute(
        """
        INSERT INTO sessions (id, title, created_at, updated_at, compressed_summary,
                              summary_up_to_msg_id, preferences_json)
        VALUES (?, ?, ?, ?, '', 0, '{}')
        ON CONFLICT(id) DO UPDATE SET title = excluded.title, updated_at = excluded.updated_at
        """,
        (session_id, title, now, now),
    )


def import_questions(db_path: Path, questions: list[dict[str, Any]], *, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] would import {len(questions)} questions")
        for subject_label in sorted({q["subject_label"] for q in questions}):
            print(f"  {subject_label}: {sum(q['subject_label'] == subject_label for q in questions)}")
        return

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"sessions", "notebook_entries", "notebook_categories", "notebook_entry_categories"}
        missing = required - tables
        if missing:
            raise RuntimeError(f"DeepTutor database is missing tables: {', '.join(sorted(missing))}")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(notebook_entries)")}
        now = time.time()

        sessions = {
            "fund": ("imported-fund-bank", "基金从业考试题库"),
            "securities": ("imported-securities-bank", "证券从业考试题库"),
        }
        for session_id, title in sessions.values():
            create_or_update_session(conn, session_id, title, now)
            old_entries = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM notebook_entries WHERE session_id = ? AND turn_id = ?",
                    (session_id, IMPORT_TURN_ID),
                ).fetchall()
            ]
            if old_entries:
                placeholders = ",".join("?" for _ in old_entries)
                conn.execute(
                    f"DELETE FROM notebook_entry_categories WHERE entry_id IN ({placeholders})",  # nosec B608
                    old_entries,
                )
            conn.execute(
                "DELETE FROM notebook_entries WHERE session_id = ? AND turn_id = ?",
                (session_id, IMPORT_TURN_ID),
            )

        category_ids: dict[str, int] = {}
        category_names = {
            "fund": "基金从业考试",
            "securities": "证券从业考试",
            "基金从业·科目一 法规": "基金从业·科目一 法规",
            "基金从业·科目二 证券投资": "基金从业·科目二 证券投资",
            "基金从业·科目三 私募股权": "基金从业·科目三 私募股权",
            "证券从业·法律法规": "证券从业·法律法规",
            "证券从业·金融基础": "证券从业·金融基础",
            "证券从业·综合题库": "证券从业·综合题库",
        }
        for name in category_names.values():
            category_ids[name] = ensure_category(conn, name, now)

        entry_columns = [
            "session_id",
            "turn_id",
            "question_id",
            "question",
            "question_type",
            "options_json",
            "correct_answer",
            "explanation",
            "difficulty",
            "user_answer",
            "is_correct",
            "bookmarked",
            "followup_session_id",
            "created_at",
            "updated_at",
        ]
        if "user_answer_images_json" in columns:
            entry_columns.insert(10, "user_answer_images_json")
        if "ai_judgment" in columns:
            entry_columns.append("ai_judgment")
        placeholders = ",".join("?" for _ in entry_columns)
        sql = f"INSERT INTO notebook_entries ({','.join(entry_columns)}) VALUES ({placeholders})"  # nosec B608

        counts: dict[str, int] = {}
        for question in questions:
            bank_kind = question["subject"] if question["subject"] in {"fund", "securities"} else "securities"
            session_id = sessions[bank_kind][0]
            question_key = question["subject_label"] + "\0" + normalize_stem(question["stem"])
            question_id = f"{bank_kind}-{hashlib.sha1(question_key.encode('utf-8')).hexdigest()[:20]}"
            explanation = add_source_marker(question["explanation"], question["source"])
            values_by_column: dict[str, Any] = {
                "session_id": session_id,
                "turn_id": IMPORT_TURN_ID,
                "question_id": question_id,
                "question": question["stem"],
                "question_type": f"{question['type']} · {question['subject_label']}",
                "options_json": json.dumps(question["options"], ensure_ascii=False),
                "correct_answer": question["answer"],
                "explanation": explanation,
                "difficulty": "",
                "user_answer": "",
                "user_answer_images_json": "[]",
                "is_correct": 0,
                "bookmarked": 0,
                "followup_session_id": "",
                "created_at": now,
                "updated_at": now,
                "ai_judgment": "",
            }
            cursor = conn.execute(sql, [values_by_column[column] for column in entry_columns])
            entry_id = int(cursor.lastrowid)
            broad_category = category_ids["基金从业考试" if bank_kind == "fund" else "证券从业考试"]
            subject_category = category_ids[question["subject_label"]]
            conn.execute(
                "INSERT OR IGNORE INTO notebook_entry_categories (entry_id, category_id) VALUES (?, ?)",
                (entry_id, broad_category),
            )
            conn.execute(
                "INSERT OR IGNORE INTO notebook_entry_categories (entry_id, category_id) VALUES (?, ?)",
                (entry_id, subject_category),
            )
            counts[question["subject_label"]] = counts.get(question["subject_label"], 0) + 1

        conn.commit()
        print(f"Imported {sum(counts.values())} questions into {db_path}")
        for name, count in sorted(counts.items()):
            print(f"  {name}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("/app/data/user/chat_history.db"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Downloading and normalizing fund question bank...")
    fund_questions = load_fund_questions()
    print("Downloading and normalizing securities question bank...")
    securities_questions = load_securities_questions()
    questions = fund_questions + securities_questions
    print(f"Prepared {len(questions)} de-duplicated questions")
    import_questions(args.db, questions, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
