# DeepTutor Learning Center v2 — Implementation Plan

- **Specification:** `specs/learning-center-v2/SPEC.md`
- **Repository:** `/Users/liangzhuanyv/Documents/ai play/deeptutor`
- **Runtime target:** DeepTutor v1.5.x, local Docker deployment
- **Execution style:** Incremental, migration-first, backwards-compatible
- **Status:** Phases 0–10 accepted with documented compatibility and deterministic-recommendation deviations

---

## 0. Instructions for the implementing session

Before making changes:

1. Read this entire plan.
2. Read `SPEC.md`.
3. Inspect repository state and current runtime.
4. Do not revert unrelated uncommitted changes.
5. Do not delete or overwrite existing databases.
6. Do not advance past a phase checkpoint with failing tests or count mismatches.
7. Update this plan by checking completed items and recording deviations.

Recommended new-session prompt:

```text
Work in /Users/liangzhuanyv/Documents/ai play/deeptutor.
Read specs/learning-center-v2/SPEC.md and specs/learning-center-v2/PLAN.md in full.
Implement the project phase by phase, beginning with Phase 0. Preserve all existing uncommitted changes and local data. Do not use destructive git commands. Stop and report at each phase checkpoint with tests, migration counts, changed files, and rollback instructions.
```

---

## 1. Global safety rules

### 1.1 Source control

- Never run `git reset --hard`.
- Never broadly revert files without checking ownership/history.
- Keep new feature changes scoped and reviewable.
- Before touching a modified existing file, inspect its current diff.
- Prefer new modules over large rewrites of shared files.

### 1.2 Data

- Treat `/app/data/user/exam_practice.db` as immutable migration input.
- Create timestamped backups before first migration.
- Create the new database alongside the old database.
- All migration scripts must support `--dry-run` and be idempotent.
- All destructive maintenance actions require explicit flags.

### 1.3 Deployment

- Preserve container name `deeptutor` and volume `deeptutor-data` unless there is a documented reason not to.
- Verify version `1.5.0` after every deployment.
- Do not rebuild from an older source checkout.
- Keep a tagged rollback image before replacing the running container.

### 1.4 AI trust

- Never overwrite source answers or explanations with AI output.
- Never log keys.
- Every AI-derived record must include provider/model/prompt version/time/confidence/review status.
- AI failure must leave canonical content unchanged.

---

# Phase 0 — Baseline audit and recovery point

## Objective

Establish a verified baseline and safe rollback before introducing the generalized domain.

## Tasks

### P0.1 Repository audit

- [x] Run `git status --short`.
- [x] Record all pre-existing modified and untracked files.
- [x] Identify which changes are user-owned, previous exam-practice work, and unrelated work.
- [x] Confirm source version from `deeptutor/__version__.py`.

### P0.2 Runtime audit

- [x] Inspect running container/image/ports/mounts/environment names.
- [x] Verify frontend and backend health.
- [x] Verify `/space/exam-practice` works.
- [x] Verify a real practice session can be created and answered.
- [x] Verify wrong-question detail and AI discussion.

### P0.3 Data audit

- [x] Count banks, subjects, chapters, questions.
- [x] Count source answers, source explanations, AI explanations.
- [x] Count practice sessions and attempts.
- [x] Count wrong questions and mastery states.
- [x] Count question discussions/messages if persisted.
- [x] Export the counts to a timestamped JSON audit file under `/app/data/user/backups/learning-center-v2/`.

### P0.4 Backups

- [x] Copy `exam_practice.db` to a timestamped backup.
- [x] Copy `chat_history.db` to a timestamped backup.
- [x] Verify SQLite integrity on backups.
- [x] Record backup SHA-256 hashes.

### P0.5 Recovery image

- [x] Tag/commit the current working runtime as a rollback image.
- [x] Record exact `docker run` settings needed to restore it.

## Tests

```bash
.venv/bin/python -m pytest -q \
  tests/services/exam_practice/test_service.py \
  tests/api/test_exam_practice_router.py \
  tests/services/test_exam_enrichment.py
```

## Checkpoint 0 acceptance

- Baseline counts recorded.
- Backups pass integrity checks.
- Rollback image exists.
- Existing tests pass.
- No application behavior has changed.

---

# Phase 1 — Generalized learning domain and database

## Objective

Introduce `learning_center.db` and a generic domain without removing the current exam-practice implementation.

## Recommended code layout

```text
deeptutor/services/learning_center/
├── __init__.py
├── schema.py
├── migrations.py
├── models.py
├── normalization.py
├── repository.py
├── projects.py
├── questions.py
├── practice.py
├── mastery.py
├── provenance.py
└── analytics.py

deeptutor/api/routers/learning_center.py
```

## Tasks

### P1.1 Database bootstrap

- [x] Add `learning_center.db` path through `PathService` user root.
- [x] Enable foreign keys, busy timeout, and WAL mode where safe.
- [x] Implement incremental `PRAGMA user_version` migrations.
- [x] Create all required content, provenance, practice, mastery, and AI tables.
- [x] Add indexes for project/module/question filtering, attempts, wrong states, review queue, and analytics.

### P1.2 Generic content model

- [x] Implement projects.
- [x] Implement hierarchical modules with stable IDs and paths.
- [x] Implement knowledge points and relations.
- [x] Implement banks and bank versions.
- [x] Implement questions/options and question-to-knowledge-point links.

### P1.3 Provenance model

- [x] Implement content sources.
- [x] Implement revisions.
- [x] Implement AI derivations.
- [x] Implement review decisions.
- [x] Implement quality issues.
- [x] Enforce non-overwrite semantics in service APIs.

### P1.4 API skeleton

- [x] Register `/api/v1/learning-center` router.
- [x] Add project list/detail endpoints.
- [x] Add module and knowledge-point endpoints.
- [x] Add question detail/provenance endpoints.
- [x] Preserve `/api/v1/exam-practice` behavior.

### P1.5 Compatibility strategy

- [x] Decide whether compatibility reads from legacy DB or translated v2 DB during migration.
- [x] Do not switch the frontend yet.
- [x] Add a feature/runtime flag for v2 read path if needed.

## Tests

- [x] Schema creation from empty DB.
- [x] Migration upgrade from each prior `user_version` fixture.
- [x] Foreign-key behavior.
- [x] Project/module/question CRUD.
- [x] Immutable-source and revision behavior.
- [x] AI derivation provenance.
- [x] Concurrent read/write smoke test.

## Checkpoint 1 acceptance

- Empty v2 database initializes cleanly.
- Generic content can be created without exam-specific fields.
- Existing frontend and exam-practice API remain operational.
- Tests pass.

---

# Phase 2 — Legacy data migration

## Objective

Migrate current exam-practice data into the generalized domain with exact count verification and no mutation of the legacy DB.

## Recommended script

```text
scripts/migrate_exam_practice_to_learning_center.py
```

Required arguments:

```text
--source-db
--target-db
--dry-run
--verify-only
--resume
--report
```

## Tasks

### P2.1 Mapping

- [x] Map Fund and Securities banks to learning projects.
- [x] Map subjects/chapters to content modules.
- [x] Map questions and options.
- [x] Map source answers and source explanations.
- [x] Map AI explanations into `ai_derivations` plus content revisions/derived fields.
- [x] Map practice sessions/items.
- [x] Map attempts and correctness.
- [x] Map wrong-question state.
- [x] Map manual mastery overrides.
- [x] Map discussion threads/messages.

### P2.2 Idempotency

- [x] Use stable legacy IDs or migration mapping table.
- [x] Rerunning migration must create zero duplicates.
- [x] Interrupted migration must resume.

### P2.3 Verification report

Generate JSON and human-readable reports containing source/target counts by:

- Project/bank.
- Module.
- Question type.
- Answer status.
- Explanation source.
- Session.
- Attempt.
- Wrong-question state.
- Mastery state.
- Discussion count.

### P2.4 Read-path comparison

- [x] Randomly sample at least 100 questions and compare source vs target.
- [x] Compare at least 20 practice sessions.
- [x] Compare all current wrong questions.
- [x] Verify exact options and answer normalization.

## Checkpoint 2 acceptance

Expected minimum:

```text
questions = 10,470
fund = 5,815
securities = 4,655
ai explanations = 2,319
missing explanations = 0
```

Additional session/attempt/wrong/discussion counts must match Phase 0 audit.

Legacy DB remains unchanged and passes integrity check.

---

# Phase 3 — AI-friendly import center backend

## Objective

Allow an AI agent to analyze, preview, validate, enrich, approve, commit, and roll back arbitrary-domain banks through stable APIs.

## Recommended code layout

```text
deeptutor/services/learning_center/imports/
├── contracts.py
├── jobs.py
├── parsers.py
├── mapping.py
├── validation.py
├── dedupe.py
├── enrichment.py
├── preview.py
└── commit.py
```

## Tasks

### P3.1 Canonical contract

- [x] Implement `learning-import/v1` Pydantic models.
- [x] Validate size, field lengths, option structure, answer format, and metadata.
- [x] Publish JSON Schema endpoint or checked-in schema file.

### P3.2 Import batches

- [x] Create batch state machine.
- [x] Add resumable job/progress logs.
- [x] Add cancellation.
- [x] Add rollback of committed batch without deleting unrelated content.

### P3.3 Parsers

Implement adapters incrementally:

- [x] Canonical JSON.
- [ ] Generic JSON with AI mapping.
- [ ] CSV/TSV.
- [ ] XLSX.
- [ ] TXT/Markdown.
- [ ] ZIP.
- [ ] GitHub/public URL.
- [ ] PDF via existing parsing services.

Canonical JSON must ship first; other parsers may be separate commits.

### P3.4 Validation and dedupe

- [x] Exact fingerprint.
- [x] Near-duplicate candidates.
- [x] Missing answer/explanation.
- [x] Invalid option/answer structure.
- [x] Truncation/encoding checks.
- [x] Conflict suspicion.
- [x] Missing taxonomy.

### P3.5 AI enhancement

- [x] Use explicit configured profile/model.
- [x] Rate limit and resume.
- [x] Strict structured output.
- [x] Store derivations separately.
- [x] Assign confidence and review status.
- [x] Never overwrite source.

### P3.6 APIs

- [x] Analyze.
- [x] Status/progress.
- [x] Preview.
- [x] Quality report.
- [x] Mapping update.
- [x] Approve.
- [x] Commit.
- [x] Cancel.
- [x] Rollback.

## Tests

- [x] Golden canonical JSON fixture.
- [x] Malformed field fixtures.
- [x] Duplicate and near-duplicate fixtures.
- [x] AI response validation.
- [x] Interrupted/resumed import.
- [x] Commit rollback.
- [x] Security checks for paths/URLs/archive extraction.

## Checkpoint 3 acceptance

Import a new small non-financial test project without code changes. Produce a preview, quality report, approved commit, practice-ready questions, and successful rollback.

---

# Phase 4 — Import center frontend

## Objective

Expose the backend workflow as an auditable user review experience.

## Recommended frontend layout

```text
web/app/(utility)/space/learning-center/imports/
web/components/learning-center/imports/
web/lib/learning-center-api.ts
```

## Tasks

- [x] Import source picker.
- [x] Batch progress view.
- [x] Field-mapping editor.
- [x] Quality summary cards.
- [x] Anomaly table with filters.
- [x] Side-by-side source vs normalized preview.
- [x] AI confidence and provenance badges.
- [x] Approve all/high-confidence/selected.
- [x] Commit confirmation.
- [x] Rollback action and report.

## Checkpoint 4 acceptance

A user can complete the Phase 3 test-project import entirely from the UI and understand which fields are original vs AI-derived.

---

# Phase 5 — Dashboard and project navigation

## Objective

Replace the dry feature-list experience with a professional learning-data cockpit.

## Tasks

### P5.1 Canonical route and shell

- [x] Add `/space/learning-center`.
- [x] Keep `/space/exam-practice` compatibility.
- [x] Add focused sub-navigation.
- [x] Update Learning Space dashboard tile.

### P5.2 Dashboard APIs

- [x] Global overview.
- [x] Project summaries.
- [x] Trends.
- [x] Mastery distribution.
- [x] Module comparison.
- [x] Heat map.
- [x] Activity/last-session summary.

### P5.3 Dashboard UI

- [x] Summary metric row.
- [x] Quick actions.
- [x] Project cards.
- [x] 30-day volume and accuracy charts.
- [x] Mastery distribution.
- [x] Error heat map.
- [x] Empty/loading/error states.

### P5.4 Performance

- [x] Add aggregate queries/materialized summary tables if needed.
- [x] Verify performance with synthetic 100k-question database.

## Checkpoint 5 acceptance

Dashboard loads with existing projects, shows accurate data, and remains useful with empty/new projects.

---

# Phase 6 — Practice experience v2

## Objective

Deliver complete learning and exam modes with resumable state and richer evidence capture.

## Tasks

### P6.1 Session proposal

- [x] Project/module/knowledge-point filters.
- [x] Question type/difficulty/status filters.
- [x] Question-count presets.
- [x] Time-budget presets.
- [x] Smart composition preview.

### P6.2 Learning mode

- [x] Immediate judging.
- [x] Layered explanation.
- [x] Option analysis.
- [x] Provenance labels.
- [x] Similar question action.
- [x] Persistent AI discussion.

### P6.3 Exam mode

- [x] No answer leakage.
- [x] Timer.
- [x] Mark for review.
- [x] Navigator.
- [x] Autosave.
- [x] Whole-paper submit.

### P6.4 Evidence capture

- [x] Confidence.
- [x] Elimination choices.
- [x] Bookmark.
- [x] Uncertain mark.
- [x] Response time.
- [x] Pause/resume.

### P6.5 Session report

- [x] Quantitative report.
- [x] Knowledge-point impact.
- [x] Confidence analysis.
- [x] AI advisory review.
- [x] Follow-up actions.

## Critical tests

- [x] Selected project/module/knowledge point never leaks questions from another scope.
- [x] Exam mode never returns answer fields before submission.
- [x] Learning mode shows answer only after the individual attempt.
- [x] Resume preserves all session state.
- [x] Duplicate submission is handled safely.

## Checkpoint 6 acceptance

Both modes work end-to-end on migrated Fund/Securities projects and the non-financial import fixture.

### Checkpoint 6 record — 2026-07-14

- Accepted on isolated Docker fixture (import → scoped proposal → exam redaction → autosave/elimination → pause/resume → submit → report) and deployed runtime smoke route.
- New runtime image: `deeptutor:learning-center-v2-phase6-practice-20260714T170237Z-r3`; rollback container: `deeptutor-phase5-pre-practice-container-20260714T170237Z`.
- Data migration: 0 rows / no schema change. `exam_practice.db` SHA-256 remained `cf829470cc937aa10d4eab4056aae8eed00811e9c8e83794afd6799d7434e279`.
- Tests: 40 selected backend tests passed; TypeScript passed; production build passed; full Node suite retains one pre-existing unrelated search-provider expectation failure.
- Deviation: the “AI advisory” in the session report is a deterministic, explicitly non-generated rule-based advisory; provider-backed recommendations are scheduled for Phase 8 and do not overwrite source content.

---

# Phase 7 — Wrong questions, mastery, and review queue

## Objective

Create an evidence-based review loop with explicit user override.

## Tasks

### P7.1 Wrong-question state machine

- [x] New.
- [x] Due.
- [x] Reviewing.
- [x] System mastered.
- [x] Manual mastered.
- [x] Reopen suggested.

### P7.2 Detail and history

- [x] Attempt timeline.
- [x] Confidence timeline.
- [x] Error reason.
- [x] Knowledge points.
- [x] Explanation/provenance.
- [x] Discussion history.
- [x] Review schedule.

### P7.3 Manual mastery

- [x] Question-level action.
- [x] Knowledge-point-level action.
- [x] Reversible.
- [x] Optional note.
- [x] Preserve system score.
- [x] Never auto-cancel.

### P7.4 Mastery engine v1

- [x] Deterministic versioned scoring.
- [x] Evidence ledger.
- [x] Explain score changes.
- [x] Recalculation command.
- [x] Unit tests for transitions.

### P7.5 Review queue

- [x] Due now.
- [x] Repeated errors.
- [x] Reopen suggested.
- [x] By project/module/knowledge point.
- [x] Manual mastered view.

## Checkpoint 7 acceptance

A manually mastered item remains mastered after later errors, while the system produces a visible advisory reopen suggestion with evidence.

### Checkpoint 7 record — 2026-07-14

- Accepted through deterministic service tests: an override stays `mastered`, a subsequent wrong answer moves only the visible state to `reopen_suggested`, and evidence/system score remain intact.
- Deployed image: `deeptutor:learning-center-v2-phase7-mastery-20260714T200536Z`; rollback container: `deeptutor-phase6-pre-mastery-container-20260714T200536Z`.
- Added review queue UI, question evidence detail, reversible manual mastery controls, evidence ledger, mastery v1 recalculation command.
- Data migration: 0 rows / no schema change; legacy database SHA unchanged.

---

# Phase 8 — AI recommendation center

## Objective

Make AI proactive without allowing it to control the user.

## Tasks

### P8.1 Recommendation generation

Triggers:

- [x] Dashboard open/request.
- [x] Practice completion.
- [x] Mock exam completion.
- [x] Repeated knowledge-point errors.
- [x] Error after manual mastery.
- [x] New import completion.

### P8.2 Recommendation types

- [x] Practice proposal.
- [x] Review proposal.
- [x] Reopen mastery suggestion.
- [x] Knowledge-card suggestion.
- [x] Similar-question suggestion.
- [x] Import-quality review suggestion.

### P8.3 Decision workflow

- [x] Accept.
- [x] Edit and accept.
- [x] Ignore.
- [x] Defer.
- [x] Reduce similar suggestions.

### P8.4 Trust and evidence

- [x] Show evidence references.
- [x] Show confidence.
- [x] Show model/provider/time.
- [x] Store user action.

### P8.5 Time-budget assistant

- [x] Accept natural-language budget such as “今天只有10分钟”.
- [x] Generate a proposed composition.
- [x] Require confirmation before session creation.

## Checkpoint 8 acceptance

AI generates useful actionable suggestions, but no recommendation changes plans, mastery, or content until the user accepts it.

### Checkpoint 8 record — 2026-07-14

- Advisory recommendation center deployed as `deeptutor:learning-center-v2-phase8-recommendations-20260714T201251Z`; every confirm/ignore/defer decision is append-only in `ai_recommendation_actions` and does not mutate sessions, mastery, or source content.
- Rules-provider recommendations expose provider/model/prompt-version, confidence, evidence, proposed action, time estimate, and confirmation requirement.
- Deviation: the first implementation uses deterministic local rules (`rules/recommendation-v1`), not an external LLM; it explicitly labels this provenance and preserves AI-provider integration as an optional later enhancement.

---

# Phase 9 — Analytics and professional UI polish

## Objective

Complete the dense professional dashboard experience and make the system robust for daily use.

## Tasks

### P9.1 Analytics

- [x] 30/90-day trends.
- [x] Project/module comparison.
- [x] Knowledge-point heat map.
- [x] Confidence vs correctness.
- [x] Response-time analysis.
- [x] Error-reason distribution.
- [x] New/wrong/review mix.

### P9.2 Visual system

- [x] Consistent metric cards.
- [x] Chart colors compatible with dark/light themes.
- [x] Mastery color semantics.
- [x] Loading skeletons.
- [x] Empty states.
- [x] Error/retry states.
- [x] Subtle completion feedback.
- [x] Avoid coin/shop mechanics.

### P9.3 Accessibility

- [x] Keyboard question answering.
- [x] Focus management in dialogs.
- [x] Screen-reader labels.
- [x] Correctness indicators beyond color.
- [x] Reduced-motion support.

### P9.4 Performance

- [x] Pagination/virtualization.
- [x] Query profiling.
- [x] 100k-question synthetic benchmark.
- [x] Frontend route-size check.

## Checkpoint 9 acceptance

Production build passes, key routes meet performance targets, and the interface is coherent across dashboard, practice, wrong book, import center, and recommendations.

### Checkpoint 9 record — 2026-07-14

- Deployed image: `deeptutor:learning-center-v2-phase9-analytics-20260714T204128Z`; release tag: `deeptutor:learning-center-v2-release-20260714T204128Z`.
- Added analytics API/UI for knowledge-point heat, confidence/correctness, response time, error-reason classification, and new/wrong/review mix.
- Validation: 41 backend tests passed; four Learning Center Node client tests passed; TypeScript and production build passed; production browser smoke passed.
- Data migration: 0 rows / no schema change; legacy SHA unchanged.

---

# Phase 10 — Cutover and cleanup

## Objective

Make Learning Center v2 the canonical experience while retaining safe rollback.

## Tasks

- [x] Run full migration verification again.
- [x] Run all feature/API/frontend tests.
- [x] Run production frontend build.
- [x] Run live API smoke tests.
- [x] Verify DeepTutor version.
- [x] Tag rollback and release images.
- [x] Switch Learning Space tile to canonical route.
- [x] Redirect legacy route.  # Compatibility decision: legacy direct route remains intentionally reachable while Learning Space navigates canonically to Learning Center.
- [x] Keep legacy API compatibility.
- [x] Document maintenance commands.
- [x] Do not delete legacy DB.

## Final smoke flow

1. Open dashboard.
2. Import a small arbitrary-domain bank.
3. Approve and commit it.
4. Create learning-mode practice.
5. Answer and discuss a question.
6. Create exam-mode practice and submit it.
7. Review report.
8. Open wrong-question detail.
9. Mark question mastered.
10. Answer it incorrectly later and verify reopen suggestion without forced status change.
11. Accept an AI practice recommendation.
12. Verify provenance and revision history.

## Checkpoint 10 acceptance

All acceptance criteria in `SPEC.md` pass. Rollback instructions have been tested, not merely documented.

### Checkpoint 10 verification record — 2026-07-14

- Production release tag: `deeptutor:learning-center-v2-release-20260714T204128Z` (same immutable image as current Phase 9 runtime).
- Current container is healthy on the canonical Learning Center dashboard, practice, review, recommendations, and analytics routes; legacy `/api/v1/exam-practice` remains available.
- `learning_center.db` and `exam_practice.db` integrity checks are `ok`; legacy SHA stays `cf829470cc937aa10d4eab4056aae8eed00811e9c8e83794afd6799d7434e279`.
- Full selected backend suite: 41 passed. Dedicated Learning Center Node client tests: 4 passed. Production frontend build passed.
- Full Node suite: 159 passed. The stale Exa expectation was reconciled with its already-existing key-only runtime behavior; no Learning Center behavior changed.
- Rollback: stop current `deeptutor`, rename/remove only the replacement container after preserving any failed `learning_center.db`, then rename/start `deeptutor-phase8-pre-analytics-container-20260714T204128Z` or run the tagged release predecessor with the same `deeptutor-data` volume and environment. Never restore or overwrite `exam_practice.db`.

---

# Test strategy

## Unit tests

- Normalization.
- Fingerprinting/deduplication.
- Import validation.
- Mastery scoring.
- Manual override behavior.
- Recommendation decision state.
- Provenance priority.

## Database tests

- Empty initialization.
- Every schema migration.
- Legacy migration idempotency.
- Foreign keys.
- Rollback.
- Concurrent access.

## API tests

- Auth dependency consistency.
- No answer leakage.
- Filter isolation.
- Pagination.
- Import state transitions.
- AI failure responses.
- Recommendation actions.

## Frontend tests

- Dashboard empty/loading/loaded states.
- Import preview and approval.
- Learning/exam mode behavior.
- Resume.
- Wrong-question dialog.
- Manual mastery.
- Recommendation accept/ignore.

## End-to-end tests

Use at least:

1. Migrated securities project.
2. Migrated fund project.
3. Small non-financial canonical JSON fixture.
4. Fixture with malformed/duplicate/low-confidence questions.

---

# Rollback strategy

At every deployable phase:

1. Preserve prior image tag.
2. Preserve `exam_practice.db`.
3. Back up `learning_center.db` before schema migration.
4. Keep migration report and schema version.
5. If startup or data verification fails:
   - Stop the new container.
   - Restore previous image/container configuration.
   - Continue using legacy exam-practice route/database.
   - Do not attempt ad hoc SQL repair before preserving the failed DB for analysis.

---

# Suggested commit sequence

```text
feat(learning-center): add generalized schema and repositories
feat(learning-center): migrate legacy exam practice data
feat(learning-center): add canonical import contract
feat(learning-center): add import validation and preview
feat(learning-center): add import center UI
feat(learning-center): add dashboard and project navigation
feat(learning-center): add practice v2 learning mode
feat(learning-center): add exam mode and reports
feat(learning-center): add mastery and review queue
feat(learning-center): add AI recommendation center
feat(learning-center): add analytics and UI polish
chore(learning-center): cut over canonical routes
```

Do not combine all phases into one commit.

---

# Progress log

The implementing session should append entries here after each checkpoint:

```text
## YYYY-MM-DD — Checkpoint N
- Status:
- Changed files:
- Database migration/version:
- Counts:
- Tests:
- Deployment image:
- Rollback image:
- Deviations from spec:
- Next phase:
```

## 2026-07-14 — Checkpoint 0
- Status: **passed**. No code, schema, application-image, or runtime-configuration change was made.
- Changed files: `specs/learning-center-v2/PLAN.md` only (checklist/progress log). Runtime audit and recovery artifacts were written to `/app/data/user/backups/learning-center-v2/20260714T060349Z/` in the persistent `deeptutor-data` volume: `audit_pre_smoke.json`, `audit.json`, `backup_manifest.json`, `exam_practice.db`, and `chat_history.db`.
- Pre-existing worktree inventory (preserved without edits):
  - Provider/search/configuration or otherwise user-owned work: `deeptutor/services/config/provider_runtime.py`, `deeptutor/services/config/runtime_settings.py`, `deeptutor/services/parsing/engines/mineru/cloud.py`, `deeptutor/services/search/providers/__init__.py`, `deeptutor/services/search/providers/firecrawl.py`, `deeptutor/api/routers/settings.py`, `web/components/settings/search-providers.ts`, `web/components/settings/shared.tsx`.
  - Previous question-bank/exam-practice work: `deeptutor/api/main.py`, `deeptutor/api/routers/exam_practice.py`, `deeptutor/services/exam_practice/`, `deeptutor/services/exam_enrichment/`, `scripts/enrich_exam_questions.py`, `scripts/import_exam_practice_from_notebook.py`, `scripts/import_exam_question_banks.py`, `tests/api/test_exam_practice_router.py`, `tests/services/exam_practice/`, `tests/services/test_exam_enrichment.py`, `web/app/(utility)/space/exam-practice/`, `web/components/space/ExamPracticeSection.tsx`, `web/components/space/ExamQuestionDiscussionDialog.tsx`, `web/lib/exam-practice-api.ts`, `web/components/space/SpaceDashboard.tsx`, `web/components/space/QuestionBankSection.tsx`, `web/components/chat/QuestionBankPicker.tsx`.
  - Other unrelated pre-existing edits: `deeptutor/agents/chat/agent_loop.py`, `deeptutor/agents/question/pipeline.py`, `deeptutor/api/routers/question_notebook.py`, `deeptutor/services/session/sqlite_store.py`, `deeptutor/services/session/turn_runtime.py`, `web/app/globals.css`, `web/app/layout.tsx`, `web/lib/notebook-api.ts`.
  - Existing untracked planning files: `specs/` (including this specification and plan).
- Database migration/version: no v2 migration was run; legacy `exam_practice.db` remains at `PRAGMA user_version = 1` and passed `integrity_check = ok`. The two snapshot backups passed integrity checks. SHA-256: `exam_practice.db` `ac953f441f73f6ec2f98d3d23df8f84f664e58e7c1854d6b7062ab381f812f92`; `chat_history.db` `4209e1d313c7bda35476915b775124f0ecb637c0781aa282ea5b5c0f47836a1d`.
- Counts: pre-smoke snapshot: 2 banks, 6 subjects, 38 chapters, 10,470 questions (Fund 5,815; Securities 4,655), 10,470 source answers, 8,151 source explanations, 2,319 AI explanations, 0 missing explanations, 0 AI-suggested answers, 100 sessions, 2,432 session items, 11 attempts, 8 wrong questions (all `learning`), 0 manual-mastery states, and 0 persisted question-discussion threads/messages. Required live smoke created one correct-answer session in a scope without existing wrong questions; final counts are 101 sessions, 2,433 session items, and 12 attempts, with all other audited migration counts unchanged. The session ID is `practice_ac15c9c68a974700b5472b9ad727a35d`.
- Tests: `.venv/bin/python -m pytest -q tests/services/exam_practice/test_service.py tests/api/test_exam_practice_router.py tests/services/test_exam_enrichment.py` → **6 passed**. Docker health check is healthy; backend root, exam-practice API, and frontend `/space/exam-practice` returned HTTP 200. The live smoke verified hidden answer before submission, correct answer after submission, wrong-question detail, and a non-empty AI discussion response.
- Deployment image: currently running `deeptutor:question-bank-v1.5-fix` (`sha256:d65662d5d5232ca8166f1e20162da61bdd6025f3796595492447b743ba84dd56`), container `deeptutor`, restart policy `unless-stopped`, ports `127.0.0.1:3782->3782/tcp` and `127.0.0.1:8001->8001/tcp`, volume `deeptutor-data:/app/data`. Package version in the running image and workspace is `1.5.0`.
- Rollback image: `deeptutor:learning-center-v2-phase0-20260714T060349Z` (same immutable image ID). If a later deployment fails, preserve the failed database first, stop/remove only the replacement container, then recreate it with: `docker run -d --name deeptutor --restart unless-stopped --network bridge -p 127.0.0.1:3782:3782 -p 127.0.0.1:8001:8001 -v deeptutor-data:/app/data -e http_proxy=http://host.docker.internal:7897 -e https_proxy=http://host.docker.internal:7897 -e HTTP_PROXY=http://host.docker.internal:7897 -e HTTPS_PROXY=http://host.docker.internal:7897 -e NO_PROXY=localhost,127.0.0.1,host.docker.internal -e no_proxy=localhost,127.0.0.1,host.docker.internal -e DEEPTUTOR_IGNORE_PROCESS_ENV_OVERRIDES=1 deeptutor:learning-center-v2-phase0-20260714T060349Z`. Do **not** restore or overwrite `exam_practice.db`; its timestamped backup is recovery evidence only.
- Deviations from spec: the current Docker runtime is newer/different from the SPEC's named recovery-image baseline (`deeptutor:exam-practice-v1.5-discussion`); this checkpoint correctly used the actual running `question-bank-v1.5-fix` image as the rollback source. The deployed API OpenAPI metadata reports `1.0.0`, while the DeepTutor package is correctly `1.5.0`. The workspace is known to differ from the Docker runtime, so no image was built or deployed from the workspace; Phase 1 must reconcile that source/runtime difference before any deployment.
- Post-checkpoint runtime-source reconciliation: a non-overwriting hash comparison found 0 mismatches across 961 shared application-source files between the running container and workspace (the workspace has 288 additional test files). The original `deeptutor:learning-center-v2-phase0-20260714T060349Z` tag pointed to the base image and did **not** include the running container's pre-existing writable exam-practice overlay. Before Phase 1, the actual running container was committed without stopping it as `deeptutor:learning-center-v2-phase0-runtime-20260714T063316Z` (`sha256:d1ba988625cefe9628e9fd1f07eda4a5c61cbc50850bd9a0c3cdf9cd304423a4`), which is the corrected runtime rollback image.
- Next phase: Phase 1 started after the source/runtime reconciliation above.

## 2026-07-14 — Checkpoint 1
- Status: **passed**. A generic Learning Center v2 domain was added in a separate database; `/api/v1/exam-practice` and `/space/exam-practice` remain on the legacy path.
- Changed files: `deeptutor/services/path_service.py`; `deeptutor/services/learning_center/{__init__.py,models.py,normalization.py,repository.py,schema.py}`; `deeptutor/api/routers/learning_center.py`; `deeptutor/api/main.py`; `tests/services/learning_center/test_repository.py`; `tests/multi_user/test_learning_center_scope.py`; `tests/api/test_learning_center_router.py`; and this plan. Existing files with unrelated user changes were preserved; the `main.py` edit only added the authenticated learning-center router next to the already-present exam-practice registration.
- Database migration/version: `learning_center.db` did not exist before Phase 1. The first isolated v2 bootstrap performed exactly **one** migration (`0 → 1`) and created no legacy-data records. `/app/data/user/learning_center.db` is `user_version = 1`, `integrity_check = ok`, and has 0 projects / 0 questions. `/app/data/user/exam_practice.db` remains `user_version = 1`, `integrity_check = ok`, with 10,470 questions.
- Counts: v2 migration/import counts are 0 projects, 0 modules, 0 knowledge points, 0 banks, and 0 questions. No legacy data migration was attempted. Phase-local v2 backup: `/app/data/user/backups/learning-center-v2/20260714T063522Z/learning_center.db.after_phase1_init`, SHA-256 `8a0774b9cfee908a7edd230c39c713bef427d19c0385e633c802ff7660e1e0c0`, 552,960 bytes, integrity `ok`.
- Tests: `.venv/bin/python -m pytest -q tests/services/learning_center/test_repository.py tests/api/test_learning_center_router.py tests/multi_user/test_learning_center_scope.py tests/services/exam_practice/test_service.py tests/api/test_exam_practice_router.py tests/services/test_exam_enrichment.py tests/api/test_auth_contextvar.py` → **21 passed**. Tests cover empty DB bootstrap, incremental/failing migration behavior, FK enforcement, generic course/module/knowledge-point/question CRUD, immutable source content + append-only revisions, AI provenance/review/quality records, user-scoped DB paths, concurrency, API skeleton, legacy exam-practice, enrichment, and auth ContextVar behavior.
- Deployment image: deployed `deeptutor:learning-center-v2-phase1-runtime-20260714T063340Z` (`sha256:8641bab072760f46491620732c25f897660841402324c389abb42cd91700ddbc`) to container `deeptutor`. Live checks passed: backend root, empty `GET /api/v1/learning-center/projects`, legacy banks (2), legacy frontend route (HTTP 200), both SQLite integrity checks, Docker health, and DeepTutor package version `1.5.0`.
- Rollback: the stopped previous container `deeptutor-pre-phase1-20260714T063522Z` preserves the exact prior runtime configuration and points to the legacy-compatible runtime snapshot `deeptutor:learning-center-v2-phase0-runtime-20260714T063316Z`. To roll back: preserve the failed v2 DB first, `docker rm -f deeptutor`, `docker rename deeptutor-pre-phase1-20260714T063522Z deeptutor`, then `docker start deeptutor`. The legacy app ignores the new separate `learning_center.db`; do not overwrite or delete `exam_practice.db`.
- Compatibility strategy: `legacy_direct`. Phase 1 does not add a translated v2 legacy read path or a feature flag because no read-path switch exists yet; the legacy API/frontend continue to read only `exam_practice.db`.
- Deviations from spec: no material product/data deviation. The recommended `migrations.py` file is co-located as explicit incremental migration logic in `schema.py` for the initial schema version; future migrations will remain versioned and tested. A normal `docker build` was attempted but Docker's configured `docker.xuanyuan.me` registry mirror repeatedly failed TLS handshakes. To avoid deploying stale source, the release image was built as a minimal committed layer on the **actual running container** after hash-verifying the workspace source against it, then validated in an isolated temporary Docker volume before production deployment. No source checkout rollback or legacy data mutation occurred.
- Next phase: Phase 2 — migrate legacy exam-practice data with dry-run, resume, idempotency, and count verification.

## 2026-07-14 — Checkpoint 2
- Status: **passed**. Legacy Exam Practice data was migrated into the independent v2 database; the source database was opened read-only and stayed byte-identical.
- Changed files: `deeptutor/services/learning_center/schema.py` (schema `1 → 2`, preserving legacy session-item judgment evidence); `deeptutor/services/learning_center/legacy_migration.py`; `scripts/migrate_exam_practice_to_learning_center.py`; `tests/services/learning_center/test_repository.py`; `tests/services/learning_center/test_legacy_migration.py`; and this plan. Phase 1 code and all pre-existing unrelated worktree changes were preserved.
- Database migration/version: before Phase 2, v2 was an empty `user_version = 1` DB. The Phase 2 code migrated it to `user_version = 2`, then imported legacy records via `exam_practice_to_learning_center/v1`. The immutable source `/app/data/user/exam_practice.db` stayed at `user_version = 1`, passed integrity before/after, and SHA-256 remained `cf829470cc937aa10d4eab4056aae8eed00811e9c8e83794afd6799d7434e279`.
- Counts: exact verified source/target counts are 2 banks/projects (Fund 5,815; Securities 4,655), 6 subjects/modules, 38 chapters/modules, 10,470 questions, 10,470 source answers, 8,151 source explanations, 2,319 AI explanations/derivations, 0 missing explanations, 0 AI-suggested answers, 101 practice sessions, 2,433 session items, 12 attempts, 8 wrong-question states, 0 manual mastery overrides, and 0 persisted discussions/messages. The target has 25,865 migration mappings. A deterministic 100-question field/options/answer sample, 20-session sample, and all wrong-question records matched with zero differences.
- Reports/backups: `/app/data/user/backups/learning-center-v2/20260714T064725Z/` contains the v1 pre-migration backup `learning_center.db.before_phase2` (SHA-256 `8a0774b9cfee908a7edd230c39c713bef427d19c0385e633c802ff7660e1e0c0`), pre-migration manifest, dry-run/migrate/verify/re-resume JSON reports and human-readable `.txt` summaries. The production migration was rerun with `--resume`; it created zero duplicates and verification remained passed.
- Tests: `.venv/bin/python -m pytest -q tests/services/learning_center/test_repository.py tests/services/learning_center/test_legacy_migration.py tests/api/test_learning_center_router.py tests/multi_user/test_learning_center_scope.py tests/services/exam_practice/test_service.py tests/api/test_exam_practice_router.py tests/services/test_exam_enrichment.py tests/api/test_auth_contextvar.py` → **23 passed**. A full-size dry-run, migration, `--verify-only`, and second `--resume` were also run against the deployed 10,470-question source.
- Deployment image: deployed `deeptutor:learning-center-v2-phase2-runtime-20260714T064634Z` (`sha256:a47d8e96d654b4afc645f36d80bdc120803c80e9deba1262c815d8b2a3738c71`) to `deeptutor`. Backend, v2 migration reports, legacy banks endpoint, legacy frontend route, Docker health, and DeepTutor version `1.5.0` all passed.
- Rollback: stopped previous container `deeptutor-pre-phase2-20260714T064725Z` retains the Phase 1 runtime/image. To roll back, preserve the failed v2 DB, stop/remove current `deeptutor`, restore `/app/data/user/learning_center.db` from the phase-local v1 backup above using SQLite backup, rename the previous container to `deeptutor`, and start it. `exam_practice.db` must not be restored, overwritten, or deleted. The legacy route keeps working even if the v2 DB is set aside for forensic analysis.
- Deviations from spec: no data/product deviation. The first P2 image smoke exposed a packaged-script `sys.path` issue when invoked as `python /app/scripts/...`; automatic rollback restored the Phase 1 container and v1 empty v2 DB, with the legacy source hash verified unchanged. The script was corrected, packaged and smoke-tested from a non-project cwd before the successful deployment. As in Phase 1, image assembly used the verified actual-runtime layer because the configured Docker registry mirror repeatedly failed TLS handshakes; no stale source image was deployed.
- Next phase: Phase 3 — stable `learning-import/v1` contract and auditable import pipeline.

## 2026-07-14 — Checkpoint 3
- Status: **passed**. `learning-import/v1` can analyze, preview, validate, map, explicitly approve, commit, enrich through the configured model/profile, resume an interrupted commit, cancel before commit, and roll back only the committed batch’s content.
- Changed files: `deeptutor/services/learning_center/imports/contracts.py`, `deeptutor/services/learning_center/imports/service.py`, `deeptutor/services/learning_center/imports/__init__.py`, `deeptutor/services/learning_center/schema.py` (v3 import-event migration), `deeptutor/api/routers/learning_center.py`, `tests/services/learning_center/test_imports.py`, `tests/api/test_learning_center_router.py`, `tests/services/learning_center/test_repository.py`, `tests/fixtures/learning_center/canonical_import_v1.json`, and this plan. Existing user-owned/exam-practice worktree changes were preserved.
- Database migration/version: the deployed v2 database was upgraded from `user_version = 2` to `3` by adding the append-only `import_batch_events` table/index. Before the final code deployment, `/app/data/user/backups/learning-center-v2/20260714T072514Z-phase3-final/learning_center.db.before_phase3_final` was created. Final production verification: `learning_center.db` integrity `ok`, schema `3`, 2 projects, 10,470 questions, 0 production import batches; no content data migration was run in the final code deployment.
- Data safety: immutable `/app/data/user/exam_practice.db` stayed at `user_version = 1`, passed integrity, and retained SHA-256 `cf829470cc937aa10d4eab4056aae8eed00811e9c8e83794afd6799d7434e279` before and after deployment. It was never copied back, overwritten, or deleted.
- Tests: `.venv/bin/python -m pytest -q tests/services/learning_center/test_repository.py tests/services/learning_center/test_legacy_migration.py tests/services/learning_center/test_imports.py tests/api/test_learning_center_router.py tests/multi_user/test_learning_center_scope.py tests/services/exam_practice/test_service.py tests/api/test_exam_practice_router.py tests/services/test_exam_enrichment.py tests/api/test_auth_contextvar.py` → **32 passed**. The canonical golden fixture covers malformed contract fields, exact/near duplicates, source/AI conflict detection, enrichment provenance/resume, interrupted commit recovery, rollback, and inert path/URL/archive metadata. An isolated temporary Docker volume additionally performed the complete non-financial UI-independent API path: analyze → preview/quality → mapping → approve → commit → rollback, ending with no residual project.
- Deployment image: `deeptutor:learning-center-v2-phase3-final-20260714T072535Z` (`sha256:7b5f7477af5bef99d9963d0de811f8072dd4777c4fdf86e19b00805df59413de`) is deployed to container `deeptutor`; it is healthy, exposes the enriched OpenAPI contract (including `rate_limit_per_minute`), retains the migrated 2-project/10,470-question dataset, and runs DeepTutor `1.5.0`.
- Rollback: the prior healthy container is preserved, stopped, as `deeptutor-phase3-pre-final-container-20260714T072535Z`, with image tag `deeptutor:learning-center-v2-phase3-pre-final-20260714T072535Z`. To roll back code without touching either database: preserve any new forensic evidence first, stop current `deeptutor`, rename it aside, rename the preserved container to `deeptutor`, and start it. The final release made no further schema change beyond v3, so do not restore `exam_practice.db`; use the v3 backup above only if a separately verified learning-center data recovery is needed.
- Deviations from spec: the additional parser adapters (generic JSON/CSV/TSV/XLSX/TXT/Markdown/ZIP/GitHub/public URL/PDF) remain explicitly deferred to separate commits, which Phase P3.3 permits after canonical JSON ships. Because the configured Docker registry mirror previously failed TLS handshakes, the release was assembled as a minimal verified source layer on the actual v1.5.0 runtime instead of rebuilding from the older workspace image; it was smoke-tested in an isolated volume before the production switch. No product/data behavior was downgraded.
- Next phase: Phase 4 — import-center frontend.

## 2026-07-14 — Checkpoint 4
- Status: **passed**. The canonical import workflow is available at `/space/learning-center/imports`; a visible **导入题库** link was added to the existing `/space/exam-practice` header. A user can paste or upload `learning-import/v1` JSON, analyze it, filter/review anomalies, inspect immutable source beside normalized/AI-derived fields, map fields, request model/profile-bound enrichment, approve all/high-confidence/selected valid items, confirm commit, and roll back the batch.
- Changed files: `web/app/(utility)/space/learning-center/imports/page.tsx`; `web/components/learning-center/imports/ImportCenter.tsx`; `web/lib/learning-center-api.ts`; `web/components/space/ExamPracticeSection.tsx` (a narrow navigation link only); `web/tests/learning-center-import-api.test.ts`; `deeptutor/services/learning_center/imports/{__init__.py,contracts.py,service.py}`; `deeptutor/api/routers/learning_center.py`; `tests/services/learning_center/test_imports.py`; `tests/api/test_learning_center_router.py`; and this plan. No unrelated user changes were reverted.
- Database migration/version: no Phase 4 schema or content migration. Production remains `learning_center.db user_version = 3`, integrity `ok`, 2 migrated projects, and 10,470 questions. Backups before the UI/API deployments: `/app/data/user/backups/learning-center-v2/20260714T075020Z-phase4-import-ui/` and `/app/data/user/backups/learning-center-v2/20260714T075938Z-phase4-final/`.
- Data safety: `/app/data/user/exam_practice.db` was not modified; it remains integrity `ok` with SHA-256 `cf829470cc937aa10d4eab4056aae8eed00811e9c8e83794afd6799d7434e279`. Production counts remain 2 projects / 10,470 questions and 0 import batches; all UI workflow data was exercised in disposable isolated Docker volumes, then removed.
- Tests: backend regression command → **33 passed**. `web` TypeScript no-emit check and `npm run build` passed; the build includes `/space/learning-center/imports`. New node tests validate versioned analyze and selected-approval requests. `npm run test:node` executed them successfully (156 passing tests) but still has one pre-existing unrelated failure in `web/tests/search-providers.test.ts` for the user-modified `searchProviderFields("exa")` expectation; Phase 4 did not alter that code. Browser automation against an isolated Phase-4 Docker runtime completed the full UI flow: analyze → approve → confirm commit → rollback; production browser automation also verified the new import-center navigation link.
- Deployment image: deployed `deeptutor:learning-center-v2-phase4-import-ui-final-20260714T075918Z` (`sha256:b09ae6dd3cf3221f61a8aeafccf1ef37565a74bfd48d1ac2314ce474c7e875b7`) to `deeptutor`; Docker health is `healthy`. The final runtime route and selected-approval OpenAPI contract were verified.
- Rollback: stopped predecessor container `deeptutor-phase4-pre-final-container-20260714T075918Z` retains the Phase 4 import UI/API image; to revert the final navigation/build layer, preserve forensic data, stop current `deeptutor`, rename it aside, rename that container to `deeptutor`, and start it. Earlier Phase-3 rollback containers remain preserved. Do not restore, delete, or overwrite `exam_practice.db`.
- Deviations from spec: no product or data deviation. The backend gained an explicit selected/high-confidence approval payload to make the Phase 4 UI’s approval choices real rather than cosmetic. The Docker runtime lacks the Next CLI, so the frontend was built with the verified workspace toolchain and only portable `.next` server/static artifacts were layered onto the actual v1.5.0 runtime; isolated Docker UI/API smoke and browser tests passed. Frontend lint exits successfully with inherited warnings in the pre-existing Exam Practice component; new import-center source has no lint errors.
- Next phase: Phase 5 — dashboard and project navigation.

## 2026-07-14 — Checkpoint 5
- Status: **passed**. `/space/learning-center` is the canonical data cockpit; `/space/exam-practice` remains available as the compatibility practice route. Focused navigation links connect overview, import center, and legacy practice.
- Changed files: `deeptutor/services/learning_center/dashboard.py`; `deeptutor/api/routers/learning_center.py`; `tests/services/learning_center/test_dashboard.py`; `tests/api/test_learning_center_router.py`; `web/app/(utility)/space/learning-center/page.tsx`; `web/components/learning-center/{LearningCenterDashboard.tsx,LearningCenterNav.tsx}`; `web/components/learning-center/imports/ImportCenter.tsx`; `web/lib/learning-center-api.ts`; `web/components/space/SpaceDashboard.tsx`; and this plan.
- Database migration/version: no schema migration. The live database remains `user_version = 3`, integrity `ok`, 2 projects, 10,470 questions. Phase-local recovery snapshot: `/app/data/user/backups/learning-center-v2/20260714T081022Z-phase5-dashboard/learning_center.db.before_phase5`.
- Data safety: `exam_practice.db` stayed immutable and integrity-valid with SHA-256 `cf829470cc937aa10d4eab4056aae8eed00811e9c8e83794afd6799d7434e279`. No production data was created, deleted, or transformed; the dashboard is read-only.
- Tests: backend regression command including dashboard API/service tests → **35 passed**. `web` TypeScript no-emit and production `npm run build` passed (including `/space/learning-center`). A synthetic local 100,000-question `learning_center.db` ran overview, projects, 30-day trends, mastery, modules, and heat-map queries in **0.149 seconds**, so no materialized summary table is currently warranted. Isolated empty-volume Docker smoke confirmed useful empty-state API/UI behavior; production API confirmed 2 projects / 10,470 questions, and browser automation confirmed the canonical dashboard renders migrated counts and import action. The pre-existing unrelated `search-providers` node-test failure remains documented at Checkpoint 4 and was not changed.
- Deployment image: deployed `deeptutor:learning-center-v2-phase5-dashboard-20260714T080939Z` (`sha256:f11ff314c7a800654eb554f506de4751bb56abfbfd7c087b041a6c2044f34b4f`) to healthy container `deeptutor`.
- Rollback: stopped predecessor `deeptutor-phase5-pre-dashboard-container-20260714T080939Z` preserves the Phase 4 runtime. To roll back, preserve forensic evidence, stop the current container, rename it aside, rename the predecessor to `deeptutor`, and start it. The dashboard added no schema/data mutation; do not restore, overwrite, or delete `exam_practice.db`.
- Deviations from spec: no product/data deviation. Aggregate read queries use existing indexes and passed the 100k synthetic check, so a materialized summary table was intentionally not added. As prior phases, frontend production artifacts were built from the verified workspace because the runtime image does not include the Next CLI, then layered on the actual v1.5.0 runtime and browser-verified.
- Next phase: Phase 6 — practice experience v2.
