# Exam-practice AI enrichment

This service fills only missing answer/explanation material in a standalone
SQLite exam-practice database. It uses the configured DeepTutor LLM catalog;
credentials remain in `model_catalog.json` and are neither accepted as CLI
arguments nor written to logs/database provenance.

## Recommended invocation

```bash
python scripts/enrich_exam_questions.py \
  --db /path/to/exam_practice.db \
  --profile-id llm-profile-pie-xian \
  --model gemini-3.5-flash \
  --dry-run

# Run after inspecting the dry run.
python scripts/enrich_exam_questions.py \
  --db /path/to/exam_practice.db \
  --profile-id llm-profile-pie-xian \
  --model gemini-3.5-flash \
  --resume
```

`--profile-id llm-profile-pie-xian` and `--model gemini-3.5-flash` are the
script defaults. `--provider` remains available as a binding override; callers
can also choose another profile/model without modifying source code.

Defaults are 72 request starts/minute (hard-capped at 80) and 12 concurrent
requests. The batch uses exponential backoff with `Retry-After` support for
429s, item-level failure reporting, and idempotent resume behavior.

## SQLite contract

The default table is `exam_questions`. Use `--table` for another
name. Required logical columns can use these aliases:

| Logical field | Supported columns |
| --- | --- |
| ID | `id`, `question_id` |
| question text | `question`, `stem`, `prompt`, `content` |
| choices | `options_json`, `options`, `choices_json`, `choices` |
| original answer | `source_answer`, `correct_answer`, `answer`, `answer_text` |
| source explanation | `source_explanation`, `explanation`, `analysis`, `solution` |

For the primary `exam_questions` table, the service **never** changes
`source_answer` or `source_explanation`. It writes an answer suggestion to
`metadata_json.ai_enrichment.answer` and sets `answer_status` to
`ai_suggested`; it writes a generated explanation only to `ai_explanation`.
Existing `metadata_json` fields are retained. The `ai_enrichment` object
contains the requested review/provenance data, for example:

```json
{"ai_enrichment":{"answer":{"status":"ai_suggested","suggested_answer":"A","confidence":0.91,"needs_review":true}}}
```

The matching `ai_enrichment.explanation` records `status: ai_generated`,
`provider`, `model`, `generated_at`, and `prompt_version`. For smaller custom
tables without `metadata_json`, an `enrichment_json` column is added; without
an `ai_explanation` column, the configured explanation field is the fallback.

## Structured output

Each request asks the OpenAI-compatible endpoint for a strict JSON Schema and
then validates it with Pydantic before any database update. Invalid JSON or
schema violations are retried as transient per-item failures; no partial write
is made for a failed request.
