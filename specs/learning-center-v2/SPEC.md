# DeepTutor Learning Center v2 — Product and Technical Specification

- **Status:** Approved for implementation
- **Owner:** Local DeepTutor user
- **Target:** DeepTutor v1.5.x, local macOS deployment
- **Date:** 2026-07-14
- **Primary repository:** `/Users/liangzhuanyv/Documents/ai play/deeptutor`
- **Companion implementation plan:** `specs/learning-center-v2/PLAN.md`

---

## 1. Executive summary

Learning Center v2 turns the current exam-specific “刷题中心” into a general-purpose, local-first personal learning and training system.

The long-term workflow is question-bank centric:

1. The user finds a question bank for any subject.
2. An AI agent analyzes, normalizes, validates, enriches, and previews it.
3. The user approves the import.
4. DeepTutor provides practice, exams, wrong-question review, mastery tracking, analytics, and AI coaching.
5. AI may make proactive recommendations, but it must not force learning actions or overwrite trusted source content.

Securities and fund qualification banks are the first migrated projects, not special hard-coded domains.

---

## 2. Current baseline that must be preserved

### 2.1 Runtime

- DeepTutor version: `1.5.0`
- Local frontend: `http://127.0.0.1:3782`
- Local backend: `http://127.0.0.1:8001`
- Container name: `deeptutor`
- Persistent volume: `deeptutor-data:/app/data`
- Latest recovery image at spec creation: `deeptutor:exam-practice-v1.5-discussion`

### 2.2 Existing question data

Existing database:

```text
/app/data/user/exam_practice.db
```

Expected baseline counts at migration time:

| Data | Expected count |
|---|---:|
| Total questions | 10,470 |
| Fund questions | 5,815 |
| Securities questions | 4,655 |
| AI-generated missing explanations | 2,319 |
| Questions still missing explanations | 0 |
| AI-suggested answers | 0 |

Existing persisted practice attempts, wrong-question state, and mastery labels must be retained. The current in-dialog AI conversation may be browser-session-local; v2 must persist new discussion threads, and migrate any discussion records that are found during the Phase 0 audit.

### 2.3 Existing source changes

The repository contains uncommitted changes, including user-owned provider/search modifications and previous Learning Center work. The implementation must not reset, discard, or overwrite unrelated changes.

Before editing, the implementing session must inspect:

```bash
git status --short
git diff -- deeptutor/api/main.py
git diff -- web/components/space/SpaceDashboard.tsx
```

Do not use `git reset --hard`, broad checkout/revert commands, or destructive database recreation.

---

## 3. Product definition

### 3.1 Product name

User-facing name:

```text
学习训练中心
```

Internal feature name:

```text
learning_center
```

Backward-compatible route:

```text
/space/exam-practice
```

Canonical route:

```text
/space/learning-center
```

The old route must redirect or render the canonical experience.

### 3.2 Product statement

> A local-first personal learning operating system that accepts AI-assisted question-bank imports for any subject and converts them into an auditable learning loop of practice, review, mastery, analytics, and optional AI recommendations.

### 3.3 Primary user characteristics

- Single local user on macOS for the first release.
- Subject matter is not predetermined.
- Learning time is irregular and chosen at session start.
- The user prefers dense professional data dashboards over playful gamification.
- The user wants AI to be proactive and opinionated, but advisory rather than controlling.
- The user does not want notifications.
- Trust, provenance, auditability, and correct separation of source vs AI content are mandatory.

---

## 4. Goals

### G1. Generalize the domain

The system must support arbitrary learning domains without adding domain-specific database columns or changing core code.

Canonical hierarchy:

```text
Learning Project → Module → Knowledge Point → Question
```

Aliases may be displayed per project:

- Project: exam, course, book, certification, subject
- Module: subject, chapter, unit, lesson
- Knowledge point: concept, objective, skill, competency

### G2. Make imports AI-friendly

AI agents must be able to import a new bank using a stable, versioned protocol instead of writing SQLite directly.

### G3. Create a complete learning loop

```text
Import → Practice → Attempt evidence → Wrong-question state → Mastery → Review queue → Analytics → AI recommendation → User decision
```

### G4. Preserve user control

AI recommendations never force plan changes, mastery changes, deletion, or source-content replacement.

### G5. Provide strict trust management

Every derived field must retain provenance, model, timestamp, confidence, prompt version, and review status.

### G6. Preserve all existing data

The migration must be reversible and count-verified.

---

## 5. Non-goals for v2

The following are explicitly out of scope unless separately approved:

- Mobile application.
- Cloud account or cross-device sync.
- Email, WeChat, SMS, or macOS notification reminders.
- Social leaderboards.
- Coin economy, shop, or childish gamification.
- Public multi-tenant hosting.
- Automatic purchase or scraping of copyrighted commercial question banks.
- AI automatically declaring source answers “official”.
- AI silently changing user mastery decisions.

The architecture should avoid blocking future sync or multi-user work, but v2 remains local-first and single-user.

---

## 6. Product principles

### P1. Source content is immutable

Imported source values are never overwritten by AI values.

Example:

```text
source_answer
ai_suggested_answer
user_confirmed_answer
```

These are separate fields or revisions.

### P2. User-confirmed content has highest display authority

Display priority:

```text
User confirmed > trusted source > AI suggestion
```

The original value remains visible in revision history.

### P3. AI is advisory

AI produces recommendations and suggested changes. The user chooses whether to accept them.

### P4. Mastery is evidence-based but overridable

System mastery and user override are separate states.

### P5. No fixed schedule assumption

The user starts a session based on available time or desired question count.

### P6. Data density over decorative gamification

The UI should prioritize trends, comparisons, heat maps, evidence, and actionable next steps.

### P7. Every migration is reversible

Never delete the legacy database until the new system passes count and behavior verification.

---

## 7. Information architecture

```text
学习训练中心
├── 总览
├── 今日训练
├── 学习项目
│   └── 项目详情
│       ├── 概览
│       ├── 模块
│       ├── 知识点
│       ├── 题库
│       └── 数据
├── 练习
│   ├── 章节练习
│   ├── 智能训练
│   ├── 快速练习
│   └── 错题重练
├── 模拟考试
├── 错题本
├── 知识点
├── AI 建议
├── 数据分析
└── 导入中心
```

Recommended routes:

```text
/space/learning-center
/space/learning-center/projects
/space/learning-center/projects/{projectId}
/space/learning-center/practice/new
/space/learning-center/practice/{sessionId}
/space/learning-center/exams
/space/learning-center/wrong-book
/space/learning-center/knowledge
/space/learning-center/recommendations
/space/learning-center/analytics
/space/learning-center/imports
/space/learning-center/imports/{batchId}
```

---

## 8. Dashboard requirements

### FR-DASH-001: Global summary

Show:

- Active projects.
- Questions practiced today.
- Accuracy today.
- Learning time today.
- Due review items.
- Knowledge points by mastery state.
- Last activity.

### FR-DASH-002: Quick actions

Provide:

- Continue last practice.
- Quick 10 questions.
- Review due mistakes.
- Ask AI to suggest this session.
- Import a new bank.

### FR-DASH-003: Project cards

Each card shows:

- Total questions.
- Practiced questions.
- Accuracy.
- Mastery percentage.
- Due reviews.
- Last activity.

### FR-DASH-004: Analytics widgets

Initial widgets:

- 30-day practice-volume trend.
- 30-day accuracy trend.
- Mastery distribution.
- Module accuracy comparison.
- Chapter/knowledge-point error heat map.
- Error-reason distribution.
- New/wrong/review question mix.
- Average response time.

### FR-DASH-005: Empty and partial states

The dashboard must remain useful when:

- No projects exist.
- A project is imported but not practiced.
- Practice exists but no mastery model has run.
- AI recommendations are unavailable.

---

## 9. AI-friendly import center

### 9.1 Supported sources

- GitHub repository or public URL.
- JSON.
- CSV/TSV.
- XLSX.
- TXT/Markdown.
- PDF question collection.
- ZIP archive.
- DeepTutor knowledge-base documents.
- AI-generated canonical payload.

### 9.2 Import stages

```text
created
→ fetching
→ parsing
→ mapping
→ validating
→ enriching
→ preview_ready
→ approved
→ committing
→ completed
```

Failure/cancellation states:

```text
failed
cancelled
rolled_back
```

### FR-IMPORT-001: Analyze without committing

The system must allow AI or a user to upload/provide a source and produce a preview without changing the canonical question store.

### FR-IMPORT-002: Field mapping

Map source fields into the canonical schema:

- stem
- options
- source answer
- source explanation
- question type
- module path
- knowledge points
- source identifier
- source revision

### FR-IMPORT-003: Quality validation

Detect at least:

- Missing answer.
- Answer not present in options.
- Invalid multiple-choice answer format.
- Missing explanation.
- Exact duplicates.
- Near duplicates.
- Truncated stem.
- Missing options.
- Answer/explanation conflict suspicion.
- Missing module/chapter.
- Missing media.
- Encoding corruption.
- Suspected outdated content.

### FR-IMPORT-004: AI enhancements

AI may suggest:

- Answer.
- Explanation.
- Module/chapter.
- Knowledge points.
- Difficulty.
- Common trap.
- Memory aid.

Every suggestion must have provenance and confidence.

### FR-IMPORT-005: Preview report

Show counts for:

- Discovered.
- Valid.
- Skipped.
- Duplicates.
- Missing answers.
- Missing explanations.
- AI-classified items.
- Low-confidence items.
- Manual-review items.

### FR-IMPORT-006: Approval controls

Allow:

- Import all.
- Import high-confidence only.
- Review anomalies.
- Edit mapping.
- Save draft.
- Cancel.

### FR-IMPORT-007: Stable AI contract

Canonical import request version `learning-import/v1`:

```json
{
  "schema_version": "learning-import/v1",
  "project": {
    "external_id": "string",
    "name": "string",
    "kind": "exam|course|book|skill|other",
    "metadata": {}
  },
  "bank": {
    "external_id": "string",
    "name": "string",
    "version": "string",
    "source": {}
  },
  "items": [
    {
      "external_id": "string",
      "module_path": ["string"],
      "knowledge_points": ["string"],
      "question_type": "single_choice",
      "stem": "string",
      "options": {"A": "string"},
      "source_answer": "A",
      "source_explanation": "string",
      "metadata": {}
    }
  ]
}
```

AI tools must never be instructed to insert directly into SQLite.

---

## 10. Practice modes

### FR-PRACTICE-001: Learning mode

- Reveal correctness immediately after submission.
- Show source answer.
- Show source explanation first; AI explanation as a labeled fallback or supplement.
- Show option-level explanation where available.
- Allow AI discussion.

### FR-PRACTICE-002: Exam mode

- Do not reveal answer before final submission.
- Show timer.
- Support marking for review.
- Support question navigator.
- Autosave.
- Submit the complete paper for scoring.

### FR-PRACTICE-003: Chapter/module practice

Filter by:

- Project.
- Bank version.
- Module(s).
- Knowledge point(s).
- Question type(s).
- Difficulty.
- New/practiced/all.
- Include/exclude wrong questions.
- Question count.

### FR-PRACTICE-004: Smart practice

AI or deterministic rules may recommend a composition using:

- Recent mistakes.
- Low-mastery knowledge points.
- Due reviews.
- Long-unseen questions.
- User-marked uncertain questions.
- New questions.
- Previously mastered questions needing retention checks.

The proposed composition must be shown before the session begins.

### FR-PRACTICE-005: Time-budget practice

Presets:

- 5 minutes.
- 10 minutes.
- 20 minutes.
- Custom.

Estimate question count from historical answer speed. The user may edit the estimate.

### FR-PRACTICE-006: Confidence capture

Optional confidence per attempt:

```text
sure
uncertain
guess
```

### FR-PRACTICE-007: Question actions

- Bookmark.
- Mark uncertain.
- Eliminate option.
- Report issue.
- Mark mastered.
- Add to later review.
- Discuss with AI.
- View source and provenance.

### FR-PRACTICE-008: Resume

An interrupted session must resume with answers, elapsed time, eliminated options, confidence, and marked questions intact.

---

## 11. Session report

### FR-REPORT-001: Quantitative result

- Total/correct/incorrect/unanswered.
- Accuracy.
- Average answer time.
- Sure-but-wrong count.
- Guess-but-correct count.
- New wrong questions.
- Changed mastery states.

### FR-REPORT-002: AI review

Generate an advisory report containing:

- Main weaknesses.
- Likely error causes.
- Knowledge points to revisit.
- Recommended next practice.
- Questions recommended for immediate retry.

### FR-REPORT-003: User decision

AI recommendations must expose:

- Accept.
- Edit and accept.
- Ignore.
- Defer.

---

## 12. Wrong-question and review system

### 12.1 Wrong-question states

```text
new
review_due
reviewing
system_mastered
manual_mastered
reopen_suggested
```

### FR-WRONG-001: Full detail

Display:

- Complete question and options.
- Source/user/AI answers.
- All historical attempts.
- Confidence history.
- Error count.
- Correct-after-error count.
- Error-reason labels.
- Knowledge points.
- Source and AI explanations.
- AI discussion history.
- Suggested next review.

### FR-WRONG-002: Manual mastery

A “已掌握” action must exist at question and knowledge-point levels.

Manual mastery:

- Does not delete evidence.
- Removes the item from the default due queue.
- Is reversible.
- Is not automatically cancelled.
- May trigger a non-binding reopen recommendation after future errors.

### FR-WRONG-003: Review filters

- Due now.
- All wrong questions.
- Repeated errors.
- By project/module/knowledge point.
- Reopen suggested.
- Manual mastered.

---

## 13. Mastery model

### 13.1 Separate system and user states

Store:

```text
system_mastery_score
system_mastery_level
manual_override
manual_override_at
manual_override_note
```

### 13.2 Mastery levels

```text
unseen
learning
familiar
stable
retained
```

### 13.3 Evidence inputs

- Recent and lifetime accuracy.
- Consecutive correct answers.
- Interval-retention result.
- Response time normalized by question type.
- Attempt confidence.
- Repeated same-error patterns.
- Cross-question-type performance.
- Optional explain-back evaluation.

### 13.4 Versioning

The mastery algorithm must be versioned. Recalculation must not destroy original evidence.

Initial algorithm may be simple and deterministic. It must expose why a score changed.

---

## 14. AI coach and recommendation center

### FR-AI-001: Proactive but advisory

AI may generate recommendations when:

- The user opens the dashboard.
- A practice session completes.
- A mock exam completes.
- A knowledge point has repeated errors.
- A manually mastered item is answered incorrectly.
- A new bank is imported.

### FR-AI-002: Recommendation fields

- Type.
- Title.
- Explanation.
- Evidence references.
- Confidence.
- Estimated time.
- Proposed question set or action.
- Provider/model.
- Prompt version.
- Created/expiry time.
- User decision.

### FR-AI-003: User control

Actions:

- Accept.
- Edit and accept.
- Ignore.
- Defer.
- Reduce similar recommendations.

### FR-AI-004: No notifications

Recommendations appear only inside DeepTutor. No system notification integration is included.

---

## 15. Trust, provenance, and audit requirements

### 15.1 Provenance classes

```text
source_original
official
user_edited
ai_generated
ai_inferred
ai_suggested
```

### FR-TRUST-001: AI derivation record

For each AI-derived field store:

- Provider.
- Model.
- Generated timestamp.
- Prompt version.
- Input/evidence references.
- Confidence.
- Review status.
- Superseded revision if applicable.

### FR-TRUST-002: Review status

```text
unreviewed
accepted
rejected
superseded
```

### FR-TRUST-003: Revision history

Corrections create revisions. Do not destructively replace canonical history.

### FR-TRUST-004: Display labels

The UI must visibly label:

- Original/source.
- User confirmed.
- AI generated.
- AI suggested.
- Low confidence.
- Potentially outdated.

### FR-TRUST-005: Issue reporting

Issue types:

- Wrong answer.
- Conflicting explanation.
- Outdated question.
- Wrong module/knowledge point.
- Missing option/media.
- Duplicate.
- Poor AI explanation.

---

## 16. Data architecture

### 16.1 Database

New database:

```text
/app/data/user/learning_center.db
```

Legacy database remains untouched during migration:

```text
/app/data/user/exam_practice.db
```

### 16.2 Core tables

#### Content

```text
learning_projects
content_modules
knowledge_points
knowledge_point_relations
question_banks
question_bank_versions
questions
question_options
question_knowledge_points
```

#### Provenance and quality

```text
content_sources
content_revisions
ai_derivations
quality_issues
review_decisions
import_batches
import_items
```

#### Practice

```text
practice_sessions
practice_session_items
attempts
attempt_option_eliminations
bookmarks
wrong_question_states
```

#### Mastery and review

```text
question_mastery
knowledge_mastery
mastery_evidence
manual_mastery_overrides
review_schedule
```

#### AI and reports

```text
ai_recommendations
ai_recommendation_actions
question_discussions
question_discussion_messages
learning_reports
```

### 16.3 Required common columns

Most mutable records should include:

```text
id
created_at
updated_at
```

Versioned content should include:

```text
version
source_id
provenance_type
review_status
supersedes_id
```

### 16.4 IDs

Use stable opaque string IDs, not UI labels. Import deduplication should use bank-version scope plus source external ID or canonical fingerprint.

---

## 17. API surface

Prefix:

```text
/api/v1/learning-center
```

### Projects and taxonomy

```text
GET    /projects
POST   /projects
GET    /projects/{projectId}
PATCH  /projects/{projectId}
GET    /projects/{projectId}/modules
GET    /projects/{projectId}/knowledge-points
```

### Imports

```text
POST   /imports/analyze
GET    /imports/{batchId}
GET    /imports/{batchId}/preview
GET    /imports/{batchId}/quality-report
PATCH  /imports/{batchId}/mapping
POST   /imports/{batchId}/approve
POST   /imports/{batchId}/commit
POST   /imports/{batchId}/cancel
POST   /imports/{batchId}/rollback
```

### Practice

```text
POST   /practice/proposals
POST   /practice/sessions
GET    /practice/sessions/{sessionId}
PATCH  /practice/sessions/{sessionId}
POST   /practice/sessions/{sessionId}/answers
POST   /practice/sessions/{sessionId}/submit
GET    /practice/sessions/{sessionId}/report
```

### Questions

```text
GET    /questions/{questionId}
POST   /questions/{questionId}/bookmark
POST   /questions/{questionId}/mastery
POST   /questions/{questionId}/issues
GET    /questions/{questionId}/provenance
GET    /questions/{questionId}/attempts
POST   /questions/{questionId}/discussion
```

### Wrong questions and mastery

```text
GET    /wrong-questions
GET    /review-queue
GET    /mastery/summary
GET    /mastery/knowledge-points/{knowledgePointId}
POST   /mastery/knowledge-points/{knowledgePointId}/override
DELETE /mastery/knowledge-points/{knowledgePointId}/override
```

### Recommendations and analytics

```text
GET    /recommendations
POST   /recommendations/generate
POST   /recommendations/{recommendationId}/accept
POST   /recommendations/{recommendationId}/ignore
POST   /recommendations/{recommendationId}/defer
GET    /analytics/overview
GET    /analytics/trends
GET    /analytics/heatmap
```

### Compatibility

Existing `/api/v1/exam-practice` routes must remain available until the canonical frontend is fully migrated and verified.

---

## 18. Integration with existing DeepTutor features

### 18.1 Knowledge bases

Projects and questions may reference DeepTutor knowledge bases. Question discussion should optionally retrieve grounded context from selected KBs.

### 18.2 Memory

Store only durable preferences and recurring error patterns in general memory. Raw attempts remain in `learning_center.db`.

### 18.3 Chat

Question discussion remains a focused thread and may expose “Open in main chat”. Discussion history must persist.

### 18.4 Agents

Future specialized agents may use the stable APIs:

- Import agent.
- Quality-audit agent.
- Study-planning agent.
- Wrong-question analysis agent.
- Mock-exam review agent.

---

## 19. Migration requirements

### FR-MIG-001: Backup

Before migration, create timestamped backups of:

```text
exam_practice.db
chat_history.db
```

### FR-MIG-002: Idempotency

Migration can be rerun without duplicating content, attempts, discussions, or wrong-question state.

### FR-MIG-003: Count verification

At minimum verify:

- Questions by bank/project.
- Source answers.
- Source explanations.
- AI explanations.
- Practice sessions.
- Attempts.
- Wrong-question states.
- Manual mastery states.
- Discussions/messages.

### FR-MIG-004: Read-only legacy preservation

Do not delete or mutate `exam_practice.db` during v2 migration.

### FR-MIG-005: Compatibility fallback

If the new database cannot initialize, the existing exam-practice feature must remain usable.

---

## 20. Non-functional requirements

### NFR-001: Local-first

No learning data leaves the machine except explicit configured AI/API calls.

### NFR-002: Performance

Target with 100,000 questions:

- Dashboard summary: under 1 second after warm start.
- Filtered question list: under 500 ms.
- Session creation: under 1 second excluding AI proposal generation.
- Wrong-book pagination: under 500 ms.

Use indexes, pagination, and pre-aggregated statistics where needed.

### NFR-003: Reliability

- SQLite WAL mode where appropriate.
- Foreign keys enabled.
- Busy timeout.
- Atomic migrations.
- Background jobs are resumable.
- AI failures do not corrupt canonical data.

### NFR-004: Security

- Do not log API keys.
- Do not return provider secrets through APIs.
- Validate import paths and URLs.
- Bound uploaded/imported file size.
- Sanitize rendered rich text.

### NFR-005: Accessibility

- Keyboard-accessible practice flow.
- Visible focus states.
- Dialog focus handling.
- Non-color-only correctness indicators.

### NFR-006: Observability

- Structured logs for import/migration/background jobs.
- Progress endpoints for long jobs.
- Job IDs and resumable status.

### NFR-007: Version stability

DeepTutor must remain on v1.5.x during this project unless separately approved. The UI must continue to display the correct version.

---

## 21. Acceptance criteria for the complete project

1. A new arbitrary-domain JSON bank can be imported through the stable API without core-code changes.
2. AI can analyze and preview an import without committing it.
3. Source and AI-derived fields are visibly and structurally separated.
4. Existing 10,470 questions and 2,319 AI explanations migrate with matching counts.
5. Existing attempts, wrong questions, manual mastery, and discussions are retained.
6. The dashboard displays global and per-project learning analytics.
7. Learning mode and exam mode both function.
8. Sessions support confidence, bookmarks, uncertainty, pause/resume, and reports.
9. Wrong questions have a complete evidence/history view.
10. Manual mastery is available, reversible, and never automatically cancelled.
11. The mastery model is explainable and versioned.
12. AI recommendations are proactive but require a user decision.
13. No notification subsystem is added.
14. The feature works locally on macOS through the existing Docker deployment.
15. Legacy exam-practice routes remain available during migration.
16. Automated tests cover migrations, import validation, filtering isolation, answer hiding, mastery overrides, trust/provenance, and API authorization behavior.
17. A production frontend build and backend smoke tests pass before deployment.
18. A rollback can restore the previous container/image and continue using `exam_practice.db`.

---

## 22. Final implementation rule

This project must be implemented as a sequence of independently testable migrations and feature slices. Do not perform a “big bang” replacement of the current exam-practice module.

The implementation session must follow `PLAN.md`, preserve existing data, and stop at phase checkpoints for verification before proceeding.
