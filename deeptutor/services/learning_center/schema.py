"""SQLite schema and incremental migrations for Learning Center v2.

The legacy ``exam_practice.db`` is deliberately not referenced here.  This
module owns only the new, independent ``learning_center.db`` database.
"""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 3

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS learning_projects (
    id TEXT PRIMARY KEY,
    external_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'other'
        CHECK(kind IN ('exam', 'course', 'book', 'skill', 'other')),
    aliases_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_learning_projects_external
    ON learning_projects(external_id) WHERE external_id <> '';
CREATE INDEX IF NOT EXISTS idx_learning_projects_kind_name
    ON learning_projects(kind, name);

CREATE TABLE IF NOT EXISTS content_modules (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    parent_id TEXT REFERENCES content_modules(id) ON DELETE SET NULL,
    external_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    depth INTEGER NOT NULL DEFAULT 0 CHECK(depth >= 0),
    sort_order INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(project_id, path)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_content_modules_project_external
    ON content_modules(project_id, external_id) WHERE external_id <> '';
CREATE INDEX IF NOT EXISTS idx_content_modules_project_path
    ON content_modules(project_id, path, sort_order);
CREATE INDEX IF NOT EXISTS idx_content_modules_parent
    ON content_modules(parent_id, sort_order);

CREATE TABLE IF NOT EXISTS knowledge_points (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    module_id TEXT REFERENCES content_modules(id) ON DELETE SET NULL,
    external_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(project_id, name)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_points_project_external
    ON knowledge_points(project_id, external_id) WHERE external_id <> '';
CREATE INDEX IF NOT EXISTS idx_knowledge_points_project_module
    ON knowledge_points(project_id, module_id, name);

CREATE TABLE IF NOT EXISTS knowledge_point_relations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    from_knowledge_point_id TEXT NOT NULL REFERENCES knowledge_points(id) ON DELETE CASCADE,
    to_knowledge_point_id TEXT NOT NULL REFERENCES knowledge_points(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'related_to',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    UNIQUE(from_knowledge_point_id, to_knowledge_point_id, relation_type),
    CHECK(from_knowledge_point_id <> to_knowledge_point_id)
);
CREATE INDEX IF NOT EXISTS idx_knowledge_relations_to
    ON knowledge_point_relations(to_knowledge_point_id, relation_type);

CREATE TABLE IF NOT EXISTS content_sources (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES learning_projects(id) ON DELETE SET NULL,
    source_type TEXT NOT NULL DEFAULT 'unknown',
    locator TEXT NOT NULL DEFAULT '',
    external_id TEXT NOT NULL DEFAULT '',
    revision TEXT NOT NULL DEFAULT '',
    checksum TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_content_sources_project_external
    ON content_sources(project_id, external_id);

CREATE TABLE IF NOT EXISTS question_banks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES content_sources(id) ON DELETE SET NULL,
    external_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(project_id, name)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_question_banks_project_external
    ON question_banks(project_id, external_id) WHERE external_id <> '';
CREATE INDEX IF NOT EXISTS idx_question_banks_project ON question_banks(project_id, name);

CREATE TABLE IF NOT EXISTS question_bank_versions (
    id TEXT PRIMARY KEY,
    bank_id TEXT NOT NULL REFERENCES question_banks(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES content_sources(id) ON DELETE SET NULL,
    version TEXT NOT NULL,
    content_hash TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('draft', 'active', 'superseded', 'rolled_back')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(bank_id, version)
);
CREATE INDEX IF NOT EXISTS idx_bank_versions_bank_status
    ON question_bank_versions(bank_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    bank_id TEXT NOT NULL REFERENCES question_banks(id) ON DELETE RESTRICT,
    bank_version_id TEXT NOT NULL REFERENCES question_bank_versions(id) ON DELETE RESTRICT,
    module_id TEXT REFERENCES content_modules(id) ON DELETE SET NULL,
    source_id TEXT REFERENCES content_sources(id) ON DELETE SET NULL,
    external_id TEXT NOT NULL DEFAULT '',
    fingerprint TEXT NOT NULL,
    question_type TEXT NOT NULL DEFAULT 'single_choice',
    stem TEXT NOT NULL,
    source_answer TEXT NOT NULL DEFAULT '',
    source_explanation TEXT NOT NULL DEFAULT '',
    difficulty TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    provenance_type TEXT NOT NULL DEFAULT 'source_original'
        CHECK(provenance_type IN ('source_original', 'official', 'user_edited', 'ai_generated', 'ai_inferred', 'ai_suggested')),
    review_status TEXT NOT NULL DEFAULT 'accepted'
        CHECK(review_status IN ('unreviewed', 'accepted', 'rejected', 'superseded')),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(bank_version_id, fingerprint)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_questions_version_external
    ON questions(bank_version_id, external_id) WHERE external_id <> '';
CREATE INDEX IF NOT EXISTS idx_questions_project_module_type
    ON questions(project_id, module_id, question_type);
CREATE INDEX IF NOT EXISTS idx_questions_bank_version ON questions(bank_version_id);
CREATE INDEX IF NOT EXISTS idx_questions_fingerprint ON questions(fingerprint);

CREATE TABLE IF NOT EXISTS question_options (
    id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    option_key TEXT NOT NULL,
    content TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(question_id, option_key),
    UNIQUE(question_id, sort_order)
);
CREATE INDEX IF NOT EXISTS idx_question_options_question
    ON question_options(question_id, sort_order);

CREATE TABLE IF NOT EXISTS question_knowledge_points (
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    knowledge_point_id TEXT NOT NULL REFERENCES knowledge_points(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'primary',
    confidence REAL,
    created_at REAL NOT NULL,
    PRIMARY KEY(question_id, knowledge_point_id)
);
CREATE INDEX IF NOT EXISTS idx_question_kps_knowledge_point
    ON question_knowledge_points(knowledge_point_id, question_id);

CREATE TABLE IF NOT EXISTS content_revisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    question_id TEXT REFERENCES questions(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES content_sources(id) ON DELETE SET NULL,
    field_name TEXT NOT NULL,
    value_json TEXT NOT NULL,
    provenance_type TEXT NOT NULL
        CHECK(provenance_type IN ('source_original', 'official', 'user_edited', 'ai_generated', 'ai_inferred', 'ai_suggested')),
    review_status TEXT NOT NULL DEFAULT 'unreviewed'
        CHECK(review_status IN ('unreviewed', 'accepted', 'rejected', 'superseded')),
    supersedes_id TEXT REFERENCES content_revisions(id) ON DELETE SET NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_content_revisions_question_field
    ON content_revisions(question_id, field_name, created_at DESC);

CREATE TABLE IF NOT EXISTS ai_derivations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    question_id TEXT REFERENCES questions(id) ON DELETE CASCADE,
    revision_id TEXT REFERENCES content_revisions(id) ON DELETE SET NULL,
    derivation_type TEXT NOT NULL,
    output_json TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_references_json TEXT NOT NULL DEFAULT '[]',
    confidence REAL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    review_status TEXT NOT NULL DEFAULT 'unreviewed'
        CHECK(review_status IN ('unreviewed', 'accepted', 'rejected', 'superseded')),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_derivations_question_type
    ON ai_derivations(question_id, derivation_type, created_at DESC);

CREATE TABLE IF NOT EXISTS review_decisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    revision_id TEXT REFERENCES content_revisions(id) ON DELETE SET NULL,
    derivation_id TEXT REFERENCES ai_derivations(id) ON DELETE SET NULL,
    decision TEXT NOT NULL CHECK(decision IN ('accepted', 'rejected', 'superseded')),
    decided_by TEXT NOT NULL DEFAULT 'user',
    note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    CHECK(revision_id IS NOT NULL OR derivation_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_review_decisions_revision ON review_decisions(revision_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_review_decisions_derivation ON review_decisions(derivation_id, created_at DESC);

CREATE TABLE IF NOT EXISTS quality_issues (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    question_id TEXT REFERENCES questions(id) ON DELETE CASCADE,
    import_item_id TEXT,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'warning' CHECK(severity IN ('info', 'warning', 'error')),
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'resolved', 'ignored')),
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quality_issues_project_status ON quality_issues(project_id, status, severity);

CREATE TABLE IF NOT EXISTS import_batches (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES learning_projects(id) ON DELETE SET NULL,
    source_id TEXT REFERENCES content_sources(id) ON DELETE SET NULL,
    schema_version TEXT NOT NULL DEFAULT 'learning-import/v1',
    status TEXT NOT NULL DEFAULT 'created',
    configuration_json TEXT NOT NULL DEFAULT '{}',
    summary_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_import_batches_status ON import_batches(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS import_items (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL DEFAULT '',
    ordinal INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    raw_json TEXT NOT NULL DEFAULT '{}',
    normalized_json TEXT NOT NULL DEFAULT '{}',
    quality_json TEXT NOT NULL DEFAULT '{}',
    question_id TEXT REFERENCES questions(id) ON DELETE SET NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(batch_id, ordinal)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_import_items_batch_external
    ON import_items(batch_id, external_id) WHERE external_id <> '';
CREATE INDEX IF NOT EXISTS idx_import_items_batch_status ON import_items(batch_id, status, ordinal);

CREATE TABLE IF NOT EXISTS practice_sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE RESTRICT,
    bank_version_id TEXT REFERENCES question_bank_versions(id) ON DELETE SET NULL,
    mode TEXT NOT NULL DEFAULT 'learning' CHECK(mode IN ('learning', 'exam')),
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    filters_json TEXT NOT NULL DEFAULT '{}',
    proposal_json TEXT NOT NULL DEFAULT '{}',
    started_at REAL NOT NULL,
    completed_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_practice_sessions_project_status ON practice_sessions(project_id, status, started_at DESC);

CREATE TABLE IF NOT EXISTS practice_session_items (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES practice_sessions(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
    position INTEGER NOT NULL,
    user_answer TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL DEFAULT '' CHECK(confidence IN ('', 'sure', 'uncertain', 'guess')),
    marked_for_review INTEGER NOT NULL DEFAULT 0 CHECK(marked_for_review IN (0, 1)),
    is_correct INTEGER CHECK(is_correct IN (0, 1)),
    elapsed_seconds REAL,
    submitted_at REAL,
    updated_at REAL NOT NULL,
    UNIQUE(session_id, question_id),
    UNIQUE(session_id, position)
);
CREATE INDEX IF NOT EXISTS idx_session_items_question ON practice_session_items(question_id, submitted_at DESC);

CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES practice_sessions(id) ON DELETE SET NULL,
    session_item_id TEXT REFERENCES practice_session_items(id) ON DELETE SET NULL,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
    user_answer TEXT NOT NULL DEFAULT '',
    is_correct INTEGER CHECK(is_correct IN (0, 1)),
    confidence TEXT NOT NULL DEFAULT '' CHECK(confidence IN ('', 'sure', 'uncertain', 'guess')),
    judgment_json TEXT NOT NULL DEFAULT '{}',
    elapsed_seconds REAL,
    submitted_at REAL NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attempts_question_time ON attempts(question_id, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_attempts_session_time ON attempts(session_id, submitted_at);

CREATE TABLE IF NOT EXISTS attempt_option_eliminations (
    id TEXT PRIMARY KEY,
    attempt_id TEXT REFERENCES attempts(id) ON DELETE CASCADE,
    session_item_id TEXT REFERENCES practice_session_items(id) ON DELETE CASCADE,
    option_key TEXT NOT NULL,
    created_at REAL NOT NULL,
    CHECK(attempt_id IS NOT NULL OR session_item_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_attempt_eliminations_attempt ON attempt_option_eliminations(attempt_id);

CREATE TABLE IF NOT EXISTS bookmarks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(question_id)
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_project ON bookmarks(project_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS wrong_question_states (
    question_id TEXT PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    state TEXT NOT NULL DEFAULT 'new'
        CHECK(state IN ('new', 'review_due', 'reviewing', 'system_mastered', 'manual_mastered', 'reopen_suggested')),
    wrong_count INTEGER NOT NULL DEFAULT 0,
    correct_after_error_count INTEGER NOT NULL DEFAULT 0,
    first_wrong_at REAL,
    last_wrong_at REAL,
    last_attempt_at REAL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wrong_states_project_state ON wrong_question_states(project_id, state, last_wrong_at DESC);

CREATE TABLE IF NOT EXISTS question_mastery (
    question_id TEXT PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    system_mastery_score REAL NOT NULL DEFAULT 0,
    system_mastery_level TEXT NOT NULL DEFAULT 'unseen'
        CHECK(system_mastery_level IN ('unseen', 'learning', 'familiar', 'stable', 'retained')),
    algorithm_version TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_question_mastery_project_level ON question_mastery(project_id, system_mastery_level);

CREATE TABLE IF NOT EXISTS knowledge_mastery (
    knowledge_point_id TEXT PRIMARY KEY REFERENCES knowledge_points(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    system_mastery_score REAL NOT NULL DEFAULT 0,
    system_mastery_level TEXT NOT NULL DEFAULT 'unseen'
        CHECK(system_mastery_level IN ('unseen', 'learning', 'familiar', 'stable', 'retained')),
    algorithm_version TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_mastery_project_level ON knowledge_mastery(project_id, system_mastery_level);

CREATE TABLE IF NOT EXISTS mastery_evidence (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    question_id TEXT REFERENCES questions(id) ON DELETE CASCADE,
    knowledge_point_id TEXT REFERENCES knowledge_points(id) ON DELETE CASCADE,
    attempt_id TEXT REFERENCES attempts(id) ON DELETE SET NULL,
    algorithm_version TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    score_delta REAL,
    created_at REAL NOT NULL,
    CHECK(question_id IS NOT NULL OR knowledge_point_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_mastery_evidence_question ON mastery_evidence(question_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mastery_evidence_knowledge ON mastery_evidence(knowledge_point_id, created_at DESC);

CREATE TABLE IF NOT EXISTS manual_mastery_overrides (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    question_id TEXT REFERENCES questions(id) ON DELETE CASCADE,
    knowledge_point_id TEXT REFERENCES knowledge_points(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK(status IN ('mastered', 'cleared')),
    note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    CHECK(question_id IS NOT NULL OR knowledge_point_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_manual_mastery_question ON manual_mastery_overrides(question_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_manual_mastery_knowledge ON manual_mastery_overrides(knowledge_point_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS review_schedule (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    question_id TEXT REFERENCES questions(id) ON DELETE CASCADE,
    knowledge_point_id TEXT REFERENCES knowledge_points(id) ON DELETE CASCADE,
    due_at REAL NOT NULL,
    interval_days REAL,
    state TEXT NOT NULL DEFAULT 'due',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    CHECK(question_id IS NOT NULL OR knowledge_point_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_review_schedule_due ON review_schedule(project_id, state, due_at);

CREATE TABLE IF NOT EXISTS ai_recommendations (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES learning_projects(id) ON DELETE CASCADE,
    recommendation_type TEXT NOT NULL,
    title TEXT NOT NULL,
    explanation TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    proposed_action_json TEXT NOT NULL DEFAULT '{}',
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    confidence REAL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    estimated_minutes INTEGER,
    expires_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_recommendations_project_created ON ai_recommendations(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ai_recommendation_actions (
    id TEXT PRIMARY KEY,
    recommendation_id TEXT NOT NULL REFERENCES ai_recommendations(id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK(action IN ('accepted', 'edited_accepted', 'ignored', 'deferred', 'reduced')),
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recommendation_actions_recommendation ON ai_recommendation_actions(recommendation_id, created_at DESC);

CREATE TABLE IF NOT EXISTS question_discussions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_question_discussions_question ON question_discussions(question_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS question_discussion_messages (
    id TEXT PRIMARY KEY,
    discussion_id TEXT NOT NULL REFERENCES question_discussions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('system', 'user', 'assistant')),
    content TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_discussion_messages_discussion ON question_discussion_messages(discussion_id, created_at);

CREATE TABLE IF NOT EXISTS learning_reports (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES practice_sessions(id) ON DELETE SET NULL,
    report_type TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}',
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_learning_reports_project_created ON learning_reports(project_id, created_at DESC);

-- Maps legacy IDs and import IDs without mutating the source database.
CREATE TABLE IF NOT EXISTS migration_mappings (
    id TEXT PRIMARY KEY,
    migration_name TEXT NOT NULL,
    legacy_table TEXT NOT NULL,
    legacy_id TEXT NOT NULL,
    target_table TEXT NOT NULL,
    target_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(migration_name, legacy_table, legacy_id),
    UNIQUE(migration_name, target_table, target_id)
);
CREATE INDEX IF NOT EXISTS idx_migration_mappings_target
    ON migration_mappings(migration_name, target_table, target_id);
"""

_SCHEMA_V2 = """
-- Preserve legacy per-item judgment evidence during Phase 2 migration.
ALTER TABLE practice_session_items
    ADD COLUMN judgment_json TEXT NOT NULL DEFAULT '{}';
"""

_SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS import_batch_events (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_import_batch_events_batch_time
    ON import_batch_events(batch_id, created_at);
"""

MIGRATIONS: dict[int, str] = {1: _SCHEMA_V1, 2: _SCHEMA_V2, 3: _SCHEMA_V3}


def migrate(conn: sqlite3.Connection) -> int:
    """Upgrade a connection atomically to :data:`SCHEMA_VERSION`.

    SQLite migrations are strictly incremental and never downgrade a database.
    A database with a future schema version is rejected to avoid accidental
    destructive compatibility behavior.
    """
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"learning_center.db schema {current} is newer than supported {SCHEMA_VERSION}"
        )
    for version in range(current + 1, SCHEMA_VERSION + 1):
        # ``executescript`` manages statements itself, so include the explicit
        # transaction in the script rather than relying on the caller's
        # context manager.  A failed migration is rolled back before its
        # user_version is made visible.
        script = MIGRATIONS[version]
        try:
            conn.executescript(
                f"BEGIN IMMEDIATE;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;"
            )
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
    return SCHEMA_VERSION
