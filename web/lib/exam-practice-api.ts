import { apiFetch, apiUrl } from "@/lib/api";

const ROOT = "/api/v1/exam-practice";

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
      // Deliberately fall back to status below.
    }
    throw new Error(detail || `请求失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}

export interface ExamBank {
  id: string;
  name: string;
  source: string;
  version: string;
  metadata: Record<string, unknown>;
  question_count: number;
  created_at: number;
  updated_at: number;
}

export interface ExamSubject {
  id: string;
  bank_id: string;
  external_id: string;
  name: string;
  sort_order: number;
  question_count: number;
}

export interface ExamChapter {
  id: string;
  subject_id: string;
  external_id: string;
  name: string;
  parent_id: string | null;
  path: string;
  sort_order: number;
  question_count: number;
}

export interface PracticeQuestion {
  id: string;
  position: number;
  subject_id: string;
  subject_name: string;
  chapter_id: string | null;
  chapter_name: string;
  question_type: string;
  stem: string;
  options: Record<string, string>;
  answer_status: "verified" | "missing" | "ai_suggested" | string;
  source: string;
  metadata: Record<string, unknown>;
  user_answer: string;
  is_correct: boolean | null;
  judgment: string;
  submitted_at: number | null;
  source_answer?: string;
  source_explanation?: string;
  ai_explanation?: string;
}

export interface PracticeSession {
  id: string;
  title: string;
  status: "active" | "completed" | string;
  filters: Record<string, unknown>;
  created_at: number;
  completed_at: number | null;
  updated_at: number;
  total: number;
  answered: number;
  questions: PracticeQuestion[];
}

export interface WrongBookItem {
  question_id: string;
  stem: string;
  question_type: string;
  subject_id: string;
  subject_name: string;
  chapter_id: string | null;
  chapter_name: string;
  wrong_count: number;
  correct_count: number;
  first_wrong_at: number | null;
  last_wrong_at: number | null;
  last_answer_at: number | null;
  last_session_id: string | null;
  mastery_status: "learning" | "mastered" | string;
  updated_at: number;
}

export interface WrongBookResponse {
  items: WrongBookItem[];
  total: number;
}

export interface WrongStatistics {
  total_questions: number;
  total_wrong_attempts: number;
  total_correct_after_wrong: number;
  learning_count: number;
  mastered_count: number;
  recent: Array<Pick<WrongBookItem, "question_id" | "stem" | "wrong_count" | "mastery_status">>;
}

export interface ChapterStatistics {
  subject_id: string;
  subject_name: string;
  chapter_id: string | null;
  chapter_name: string;
  chapter_path: string;
  question_count: number;
  practiced_count: number;
  correct_attempts: number;
  wrong_attempts: number;
  wrong_question_count: number;
}

export interface WeakPointInsight {
  chapter_id?: string | null;
  chapter_name: string;
  subject_id?: string;
  subject_name?: string;
  title: string;
  summary: string;
  evidence_question_ids: string[];
  wrong_question_count: number;
  total_wrong_attempts: number;
}

export function listExamBanks(): Promise<ExamBank[]> {
  return request("/banks");
}

export function listExamSubjects(bankId?: string): Promise<ExamSubject[]> {
  return request(`/subjects${bankId ? `?bank_id=${encodeURIComponent(bankId)}` : ""}`);
}

export function listExamChapters(subjectId?: string): Promise<ExamChapter[]> {
  return request(`/chapters${subjectId ? `?subject_id=${encodeURIComponent(subjectId)}` : ""}`);
}

export function createPracticeSession(input: {
  title?: string;
  subject_id?: string;
  chapter_id?: string;
  question_types?: string[];
  limit: number;
}): Promise<PracticeSession> {
  return request("/sessions", { method: "POST", body: JSON.stringify(input) });
}

export function getPracticeSession(sessionId: string): Promise<PracticeSession> {
  return request(`/sessions/${encodeURIComponent(sessionId)}`);
}

export async function submitPracticeAnswer(
  sessionId: string,
  questionId: string,
  userAnswer: string,
): Promise<PracticeSession> {
  const response = await request<{ session: PracticeSession }>(
    `/sessions/${encodeURIComponent(sessionId)}/answers`,
    {
      method: "POST",
      body: JSON.stringify({ answers: [{ question_id: questionId, user_answer: userAnswer }] }),
    },
  );
  return response.session.questions?.length
    ? response.session
    : getPracticeSession(sessionId);
}

export function listWrongBook(status?: "learning" | "mastered"): Promise<WrongBookResponse> {
  const query = status ? `?mastery_status=${status}&limit=100` : "?limit=100";
  return request(`/wrong-book${query}`);
}

export function updateWrongBookStatus(
  questionId: string,
  masteryStatus: "learning" | "mastered",
): Promise<WrongBookItem> {
  return request(`/wrong-book/${encodeURIComponent(questionId)}`, {
    method: "PATCH",
    body: JSON.stringify({ mastery_status: masteryStatus }),
  });
}

export function getWrongStatistics(): Promise<WrongStatistics> {
  return request("/statistics/wrong");
}

export function getChapterStatistics(subjectId?: string): Promise<ChapterStatistics[]> {
  return request(`/statistics/chapters${subjectId ? `?subject_id=${encodeURIComponent(subjectId)}` : ""}`);
}

export async function getWeakPointInsights(subjectId?: string): Promise<WeakPointInsight[]> {
  const response = await request<{ items: WeakPointInsight[] }>("/insights/weak-points", {
    method: "POST",
    body: JSON.stringify(subjectId ? { subject_id: subjectId, limit: 8 } : { limit: 8 }),
  });
  return response.items;
}

export interface ExamQuestionDetail {
  id: string;
  bank_id: string;
  subject_id: string;
  subject_name: string;
  chapter_id: string | null;
  chapter_name: string;
  external_id: string;
  question_type: string;
  stem: string;
  options: Record<string, string>;
  source_answer: string;
  answer_status: string;
  source_explanation: string;
  ai_explanation: string;
  source: string;
  metadata: Record<string, unknown>;
  wrong_book: {
    question_id: string;
    wrong_count: number;
    correct_count: number;
    mastery_status: string;
  } | null;
}

export interface ExamDiscussionMessage {
  role: "user" | "assistant";
  content: string;
}

export function getExamQuestion(questionId: string): Promise<ExamQuestionDetail> {
  return request(`/questions/${encodeURIComponent(questionId)}`);
}

export function discussExamQuestion(
  questionId: string,
  message: string,
  history: ExamDiscussionMessage[],
): Promise<{ reply: string }> {
  return request(`/questions/${encodeURIComponent(questionId)}/discussion`, {
    method: "POST",
    body: JSON.stringify({ message, history }),
  });
}
