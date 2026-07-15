import { apiFetch, apiUrl } from "./api";

const ROOT = "/api/v1/learning-center";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(apiUrl(`${ROOT}${path}`), {
    cache: "no-store",
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = "";
    try {
      const payload = (await response.json()) as { detail?: unknown };
      detail = typeof payload.detail === "string" ? payload.detail : "";
    } catch {
      // Prefer a useful HTTP status when the response cannot be decoded.
    }
    throw new Error(detail || `请求失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}

export type ImportQuestionType =
  | "single_choice"
  | "multiple_choice"
  | "true_false"
  | "short_answer"
  | "other";
export type ImportProjectKind = "exam" | "course" | "book" | "skill" | "other";
export type ImportBatchStatus =
  | "preview_ready"
  | "approved"
  | "committing"
  | "completed"
  | "cancelled"
  | "rolled_back"
  | string;
export type ImportItemStatus = "valid" | "manual_review" | "duplicate" | "committed" | string;

export interface LearningImportItemInput {
  external_id: string;
  module_path?: string[];
  knowledge_points?: string[];
  question_type: ImportQuestionType;
  stem: string;
  options?: Record<string, string>;
  source_answer?: string;
  source_explanation?: string;
  metadata?: Record<string, unknown>;
}

export interface LearningImportRequest {
  schema_version: "learning-import/v1";
  project: {
    external_id: string;
    name: string;
    kind?: ImportProjectKind;
    metadata?: Record<string, unknown>;
  };
  bank: {
    external_id: string;
    name: string;
    version: string;
    source?: Record<string, unknown>;
  };
  items: LearningImportItemInput[];
}

export interface ImportIssue {
  type: string;
  severity: "error" | "warning" | string;
  message?: string;
  [key: string]: unknown;
}

export interface ImportAiSuggestion {
  suggested_answer?: string | null;
  answer_confidence?: number | null;
  explanation?: string;
  provider: string;
  model: string;
  prompt_version: string;
  generated_at: string;
  review_status: string;
}

export interface ImportItemQuality {
  issues: ImportIssue[];
  ai_suggestions?: ImportAiSuggestion[];
}

export interface ImportBatchItem {
  id: string;
  external_id: string;
  ordinal: number;
  status: ImportItemStatus;
  raw: LearningImportItemInput;
  normalized: LearningImportItemInput & { fingerprint?: string };
  quality: ImportItemQuality;
  question_id: string | null;
}

export interface ImportBatchEvent {
  stage: string;
  message: string;
  payload: Record<string, unknown>;
  created_at: number;
}

export interface ImportBatch {
  id: string;
  project_id: string | null;
  schema_version: string;
  status: ImportBatchStatus;
  configuration: {
    request?: LearningImportRequest;
    mapping?: Record<string, unknown>;
    approval?: {
      mode: ImportApprovalMode;
      item_ids: string[];
      minimum_confidence: number;
    };
    protocol?: string;
  };
  summary: Record<string, number | string | boolean | null | undefined>;
  items: ImportBatchItem[];
  events: ImportBatchEvent[];
  created_at: number;
  updated_at: number;
  completed_at: number | null;
}

export interface ImportQualityReport {
  batch_id: string;
  status: ImportBatchStatus;
  summary: ImportBatch["summary"];
  items: Array<Pick<ImportBatchItem, "id" | "external_id" | "status" | "quality">>;
}

export type ImportApprovalMode = "all_valid" | "high_confidence" | "selected";

export interface ImportApprovalInput {
  mode?: ImportApprovalMode;
  selected_item_ids?: string[];
  minimum_confidence?: number;
}

export interface ImportEnrichmentInput {
  profile_id?: string;
  provider?: string;
  model?: string;
  prompt_version?: string;
  limit?: number;
  rate_limit_per_minute?: number;
}

export function getImportSchema(): Promise<Record<string, unknown>> {
  return request("/imports/schema");
}

export function analyzeImport(payload: LearningImportRequest): Promise<ImportBatch> {
  return request("/imports/analyze", { method: "POST", body: JSON.stringify(payload) });
}

export function getImportBatch(batchId: string): Promise<ImportBatch> {
  return request(`/imports/${encodeURIComponent(batchId)}`);
}

export function getImportPreview(batchId: string): Promise<ImportBatch> {
  return request(`/imports/${encodeURIComponent(batchId)}/preview`);
}

export function getImportQualityReport(batchId: string): Promise<ImportQualityReport> {
  return request(`/imports/${encodeURIComponent(batchId)}/quality-report`);
}

export function updateImportMapping(batchId: string, mapping: Record<string, unknown>): Promise<ImportBatch> {
  return request(`/imports/${encodeURIComponent(batchId)}/mapping`, {
    method: "PATCH",
    body: JSON.stringify({ mapping }),
  });
}

export function approveImport(batchId: string, approval: ImportApprovalInput = {}): Promise<ImportBatch> {
  return request(`/imports/${encodeURIComponent(batchId)}/approve`, {
    method: "POST",
    body: JSON.stringify(approval),
  });
}

export function commitImport(batchId: string): Promise<ImportBatch> {
  return request(`/imports/${encodeURIComponent(batchId)}/commit`, { method: "POST" });
}

export function cancelImport(batchId: string): Promise<ImportBatch> {
  return request(`/imports/${encodeURIComponent(batchId)}/cancel`, { method: "POST" });
}

export function rollbackImport(batchId: string): Promise<ImportBatch> {
  return request(`/imports/${encodeURIComponent(batchId)}/rollback`, { method: "POST" });
}

export function enrichImport(batchId: string, input: ImportEnrichmentInput): Promise<ImportBatch> {
  return request(`/imports/${encodeURIComponent(batchId)}/enrich`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export interface LearningDashboardOverview {
  project_count: number;
  question_count: number;
  attempt_count: number;
  accuracy: number | null;
  review_due_count: number;
  active_session_count: number;
  last_session: {
    id: string;
    mode: string;
    title: string;
    started_at: number;
    completed_at: number | null;
    project_id: string;
    project_name: string;
    total: number;
    answered: number;
    accuracy: number | null;
  } | null;
}

export interface LearningDashboardProject {
  id: string;
  name: string;
  kind: string;
  question_count: number;
  attempt_count: number;
  accuracy: number | null;
  review_due_count: number;
  last_session_at: number | null;
}

export interface LearningTrendPoint {
  date: string;
  attempt_count: number;
  correct_count: number;
  accuracy: number | null;
}

export interface LearningMasteryBucket {
  level: "unseen" | "learning" | "familiar" | "stable" | "retained";
  question_count: number;
}

export interface LearningModuleComparison {
  id: string;
  project_id: string;
  project_name: string;
  name: string;
  path: string;
  question_count: number;
  attempt_count: number;
  wrong_attempt_count: number;
  accuracy: number | null;
}

export interface LearningErrorHeatmapCell {
  date: string;
  module_id: string;
  module_name: string;
  attempt_count: number;
  wrong_attempt_count: number;
}

export function getLearningDashboardOverview(): Promise<LearningDashboardOverview> {
  return request("/dashboard/overview");
}

export function getLearningDashboardProjects(): Promise<LearningDashboardProject[]> {
  return request("/dashboard/projects");
}

export function getLearningDashboardTrends(days = 30): Promise<LearningTrendPoint[]> {
  return request(`/dashboard/trends?days=${encodeURIComponent(days)}`);
}

export function getLearningDashboardMastery(): Promise<LearningMasteryBucket[]> {
  return request("/dashboard/mastery");
}

export function getLearningDashboardModules(projectId?: string): Promise<LearningModuleComparison[]> {
  return request(`/dashboard/modules${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""}`);
}

export function getLearningDashboardHeatmap(days = 30): Promise<LearningErrorHeatmapCell[]> {
  return request(`/dashboard/heatmap?days=${encodeURIComponent(days)}`);
}

export interface LearningProjectOption {
  id: string;
  name: string;
  kind: string;
  question_count?: number;
}

export interface LearningModuleOption {
  id: string;
  project_id: string;
  name: string;
  path: string;
}

export interface LearningKnowledgePointOption {
  id: string;
  project_id: string;
  module_id: string | null;
  name: string;
}

export type PracticeMode = "learning" | "exam";
export type PracticeConfidence = "" | "sure" | "uncertain" | "guess";

export interface PracticeProposalInput {
  project_id: string;
  module_id?: string | null;
  knowledge_point_id?: string | null;
  question_types?: string[];
  difficulty?: string | null;
  status?: string | null;
  limit?: number;
}

export interface PracticeProposalQuestion {
  question_id: string;
  question_type: string;
  stem: string;
  module_id: string | null;
  module_path: string;
  difficulty: string;
}

export interface PracticeProposal {
  project_id: string;
  candidate_count: number;
  selected_count: number;
  filters: PracticeProposalInput & { limit: number };
  composition: { question_types: Record<string, number>; difficulties: Record<string, number>; modules: Record<string, number> };
  questions: PracticeProposalQuestion[];
}

export interface PracticeSessionItem {
  id: string;
  question_id: string;
  position: number;
  question_type: string;
  stem: string;
  options: Record<string, string>;
  user_answer: string;
  confidence: PracticeConfidence;
  marked_for_review: boolean;
  eliminated_option_keys: string[];
  elapsed_seconds: number | null;
  submitted_at: number | null;
  is_correct: boolean | null;
  source_answer?: string;
  source_explanation?: string;
  provenance?: { source_id: string | null; kind: string };
}

export interface PracticeSession {
  id: string;
  project_id: string;
  mode: PracticeMode;
  title: string;
  status: "active" | "paused" | "completed" | string;
  filters: PracticeProposalInput & { time_budget_minutes?: number | null; paused_at?: number | null; paused_total_seconds?: number };
  proposal: PracticeProposal;
  started_at: number;
  completed_at: number | null;
  questions: PracticeSessionItem[];
}

export interface PracticeAnswerInput {
  id: string;
  user_answer?: string;
  confidence?: PracticeConfidence;
  marked_for_review?: boolean;
  elapsed_seconds?: number | null;
  eliminated_option_keys?: string[];
}

export interface PracticeReport {
  session_id: string;
  project_id: string;
  mode: PracticeMode;
  status: string;
  total: number;
  answered: number;
  graded: number;
  correct: number;
  accuracy: number | null;
  confidence: Record<string, { count: number; correct: number; accuracy: number | null }>;
  knowledge_point_impact: Record<string, { total: number; wrong: number }>;
  ai_advisory: { text: string; provider: string; model: string; generated: boolean };
  follow_up_actions: Array<{ type: string; label: string }>;
}

export interface PracticeDiscussion {
  id: string | null;
  project_id: string;
  question_id: string;
  messages: Array<{ id: string; role: "system" | "user" | "assistant"; content: string; created_at: number }>;
}

export function getLearningProjects(): Promise<LearningProjectOption[]> {
  return request("/projects");
}

export function getLearningModules(projectId: string): Promise<LearningModuleOption[]> {
  return request(`/projects/${encodeURIComponent(projectId)}/modules`);
}

export function getLearningKnowledgePoints(projectId: string): Promise<LearningKnowledgePointOption[]> {
  return request(`/projects/${encodeURIComponent(projectId)}/knowledge-points`);
}

export function getPracticeProposal(input: PracticeProposalInput): Promise<PracticeProposal> {
  return request("/practice/proposal", { method: "POST", body: JSON.stringify(input) });
}

export function startPracticeSession(input: PracticeProposalInput & { mode: PracticeMode; title?: string; time_budget_minutes?: number | null }): Promise<PracticeSession> {
  return request("/practice/sessions", { method: "POST", body: JSON.stringify(input) });
}

export function getPracticeSession(sessionId: string): Promise<PracticeSession> {
  return request(`/practice/sessions/${encodeURIComponent(sessionId)}`);
}

export function autosavePracticeSession(sessionId: string, answers: PracticeAnswerInput[]): Promise<PracticeSession> {
  return request(`/practice/sessions/${encodeURIComponent(sessionId)}`, { method: "PATCH", body: JSON.stringify(answers) });
}

export function submitPracticeSession(sessionId: string, answers: PracticeAnswerInput[], finish = false): Promise<PracticeSession> {
  return request(`/practice/sessions/${encodeURIComponent(sessionId)}/submit`, { method: "POST", body: JSON.stringify({ answers, finish }) });
}

export function pausePracticeSession(sessionId: string): Promise<PracticeSession> {
  return request(`/practice/sessions/${encodeURIComponent(sessionId)}/pause`, { method: "POST" });
}

export function resumePracticeSession(sessionId: string): Promise<PracticeSession> {
  return request(`/practice/sessions/${encodeURIComponent(sessionId)}/resume`, { method: "POST" });
}

export function getPracticeReport(sessionId: string): Promise<PracticeReport> {
  return request(`/practice/sessions/${encodeURIComponent(sessionId)}/report`);
}

export function setPracticeBookmark(input: { project_id: string; question_id: string; bookmarked: boolean; note?: string }): Promise<Record<string, unknown> | null> {
  return request("/practice/bookmarks", { method: "POST", body: JSON.stringify(input) });
}

export function getPracticeDiscussion(projectId: string, questionId: string): Promise<PracticeDiscussion> {
  return request(`/practice/questions/${encodeURIComponent(questionId)}/discussion?project_id=${encodeURIComponent(projectId)}`);
}

export function addPracticeDiscussion(projectId: string, questionId: string, content: string): Promise<PracticeDiscussion> {
  return request(`/practice/questions/${encodeURIComponent(questionId)}/discussion`, { method: "POST", body: JSON.stringify({ project_id: projectId, content }) });
}

export interface ReviewQueueItem {
  question_id: string;
  stem: string;
  question_type: string;
  module_id: string | null;
  state: string;
  wrong_count: number;
  correct_after_error_count: number;
  system_mastery_score: number | null;
  system_mastery_level: string | null;
  due_at: number | null;
}

export interface MasteryQuestionDetail {
  question: { id: string; project_id: string; stem: string; source_answer: string; source_explanation: string; options: Record<string, string> };
  attempts: Array<{ id: string; user_answer: string; is_correct: number | null; confidence: string; elapsed_seconds: number | null; submitted_at: number }>;
  confidence_timeline: Array<{ confidence: string; is_correct: number | null; submitted_at: number }>;
  knowledge_points: Array<{ id: string; name: string }>;
  wrong_state: { state: string; wrong_count: number; correct_after_error_count: number } | null;
  mastery: { system_mastery_score: number; system_mastery_level: string; algorithm_version: string } | null;
  manual_override: { status: string; note: string; updated_at: number } | null;
  review_schedule: { due_at: number; interval_days: number | null; state: string } | null;
  evidence: Array<{ id: string; evidence_type: string; score_delta: number | null; created_at: number; payload: Record<string, unknown> }>;
  discussion: { id: string | null; messages: Array<{ id: string; role: string; content: string; created_at: number }> };
  provenance: { source_id: string | null; kind: string; review_status: string };
}

export function getReviewQueue(input: { project_id: string; module_id?: string; knowledge_point_id?: string; filter?: "due" | "all_wrong" | "repeated" | "reopen" | "manual_mastered" }): Promise<ReviewQueueItem[]> {
  const params = new URLSearchParams({ project_id: input.project_id, filter: input.filter ?? "due" });
  if (input.module_id) params.set("module_id", input.module_id);
  if (input.knowledge_point_id) params.set("knowledge_point_id", input.knowledge_point_id);
  return request(`/review-queue?${params}`);
}

export function getMasteryQuestionDetail(questionId: string): Promise<MasteryQuestionDetail> {
  return request(`/questions/${encodeURIComponent(questionId)}/attempts`);
}

export function setQuestionMastery(questionId: string, mastered: boolean, note = ""): Promise<MasteryQuestionDetail> {
  return request(`/questions/${encodeURIComponent(questionId)}/mastery`, { method: "POST", body: JSON.stringify({ mastered, note }) });
}

export interface LearningRecommendation { id: string; project_id: string | null; recommendation_type: string; title: string; explanation: string; evidence: Array<Record<string, unknown>>; proposed_action: Record<string, unknown>; provider: string; model: string; prompt_version: string; confidence: number | null; estimated_minutes: number | null; created_at: number; actions: Array<{ action: string; payload: Record<string, unknown>; created_at: number }>; }
export function getLearningRecommendations(projectId?: string): Promise<LearningRecommendation[]> { return request(`/recommendations${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""}`); }
export function generateLearningRecommendations(input: { project_id: string; trigger?: string; time_budget_text?: string }): Promise<LearningRecommendation[]> { return request("/recommendations/generate", {method:"POST",body:JSON.stringify(input)}); }
export function decideLearningRecommendation(id: string, action: "accepted"|"edited_accepted"|"ignored"|"deferred"|"reduced", payload: Record<string, unknown> = {}): Promise<LearningRecommendation> { const route=action === "ignored" ? "ignore" : action === "deferred" ? "defer" : "accept"; return request(`/recommendations/${encodeURIComponent(id)}/${route}`, {method:"POST",body:JSON.stringify({action,payload})}); }
export interface KnowledgeHeatmapCell { id:string; name:string; project_id:string; question_count:number; attempt_count:number; wrong_count:number; }
export interface ConfidenceAnalytics { confidence:string; attempt_count:number; correct_count:number; accuracy:number|null; }
export interface ResponseTimeAnalytics { question_type:string; attempt_count:number; average_seconds:number|null; min_seconds:number|null; max_seconds:number|null; }
export interface ErrorReasonAnalytics { reason:string; count:number; }
export interface ContentMixAnalytics { total:number; new_count:number; wrong_count:number; review_count:number; }
export function getKnowledgeHeatmap(projectId?:string):Promise<KnowledgeHeatmapCell[]>{return request(`/analytics/knowledge-heatmap${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`)}
export function getConfidenceAnalytics(projectId?:string):Promise<ConfidenceAnalytics[]>{return request(`/analytics/confidence${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`)}
export function getResponseTimeAnalytics(projectId?:string):Promise<ResponseTimeAnalytics[]>{return request(`/analytics/response-time${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`)}
export function getErrorReasonAnalytics(projectId?:string):Promise<ErrorReasonAnalytics[]>{return request(`/analytics/error-reasons${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`)}
export function getContentMixAnalytics(projectId?:string):Promise<ContentMixAnalytics>{return request(`/analytics/content-mix${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`)}
