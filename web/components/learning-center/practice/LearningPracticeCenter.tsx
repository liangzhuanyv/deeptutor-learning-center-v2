"use client";
/* eslint-disable i18n/no-literal-ui-text -- Learning Center v2 is Chinese-first pending locale extraction. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Bookmark, CheckCircle2, ChevronLeft, ChevronRight, Clock3, Loader2, MessageCircle, Pause, Play, Send, Sparkles, Target } from "lucide-react";

import LearningCenterNav from "@/components/learning-center/LearningCenterNav";
import ExamRichText from "@/components/learning-center/ExamRichText";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import {
  addPracticeDiscussion,
  autosavePracticeSession,
  getLearningKnowledgePoints,
  getLearningModules,
  getLearningProjects,
  getPracticeDiscussion,
  getPracticeProposal,
  getPracticeReport,
  getPracticeSession,
  listResumablePracticeSessions,
  pausePracticeSession,
  resumePracticeSession,
  setPracticeBookmark,
  startPracticeSession,
  submitPracticeSession,
  type LearningKnowledgePointOption,
  type LearningModuleOption,
  type LearningProjectOption,
  type PracticeAnswerInput,
  type PracticeDiscussion,
  type PracticeMode,
  type PracticeProposal,
  type PracticeReport,
  type PracticeSession,
  type PracticeSessionItem,
  type ResumablePracticeSession,
} from "@/lib/learning-center-api";

type Draft = {
  user_answer: string;
  confidence: "" | "sure" | "uncertain" | "guess";
  marked_for_review: boolean;
  eliminated_option_keys: string[];
  elapsed_seconds: number;
};

const PRESETS = [10, 20, 40, 80];
const TIME_PRESETS = [null, 15, 30, 60, 120];

function toDraft(item: PracticeSessionItem): Draft {
  return {
    user_answer: item.user_answer,
    confidence: item.confidence,
    marked_for_review: item.marked_for_review,
    eliminated_option_keys: item.eliminated_option_keys,
    elapsed_seconds: item.elapsed_seconds ?? 0,
  };
}

function formatSeconds(seconds: number): string {
  const safe = Math.max(0, Math.round(seconds));
  return `${String(Math.floor(safe / 60)).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`;
}

function answerPayload(item: PracticeSessionItem, draft: Draft | undefined): PracticeAnswerInput {
  return { id: item.id, ...(draft ?? toDraft(item)) };
}

export default function LearningPracticeCenter() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [projects, setProjects] = useState<LearningProjectOption[]>([]);
  const [modules, setModules] = useState<LearningModuleOption[]>([]);
  const [knowledgePoints, setKnowledgePoints] = useState<LearningKnowledgePointOption[]>([]);
  const [projectId, setProjectId] = useState("");
  const [moduleId, setModuleId] = useState("");
  const [knowledgePointId, setKnowledgePointId] = useState("");
  const [mode, setMode] = useState<PracticeMode>("learning");
  const [limit, setLimit] = useState(20);
  const [timeBudget, setTimeBudget] = useState<number | null>(null);
  const [difficulty, setDifficulty] = useState("");
  const [statusFilter, setStatusFilter] = useState("unseen");
  const [proposal, setProposal] = useState<PracticeProposal | null>(null);
  const [session, setSession] = useState<PracticeSession | null>(null);
  const [resumable, setResumable] = useState<ResumablePracticeSession[]>([]);
  const bootstrappedRef = useRef(false);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [bookmarked, setBookmarked] = useState<Record<string, boolean>>({});
  const [discussion, setDiscussion] = useState<PracticeDiscussion | null>(null);
  const [discussionText, setDiscussionText] = useState("");
  const [report, setReport] = useState<PracticeReport | null>(null);
  const [clock, setClock] = useState(() => Date.now() / 1000);

  const selectedProject = useMemo(() => projects.find((project) => project.id === projectId), [projects, projectId]);
  const currentQuestion = session?.questions[currentIndex] ?? null;
  const activeDraft = currentQuestion ? drafts[currentQuestion.id] ?? toDraft(currentQuestion) : null;
  const elapsed = useMemo(() => Object.values(drafts).reduce((sum, draft) => sum + (draft.elapsed_seconds || 0), 0), [drafts]);
  useEffect(() => {
    if (!session || session.status !== "active" || !session.filters.time_budget_minutes) return;
    const timer = window.setInterval(() => setClock(Date.now() / 1000), 1_000);
    return () => window.clearInterval(timer);
  }, [session?.id, session?.status, session?.filters.time_budget_minutes]);

  const remainingSeconds = useMemo(() => {
    if (!session?.filters.time_budget_minutes) return null;
    const pausedAt = session.filters.paused_at ?? null;
    const end = pausedAt ?? clock;
    const activeSeconds = Math.max(0, end - session.started_at - (session.filters.paused_total_seconds ?? 0));
    return Math.max(0, session.filters.time_budget_minutes * 60 - activeSeconds);
  }, [clock, session]);

  const formInput = useCallback(() => ({
    project_id: projectId,
    module_id: moduleId || null,
    knowledge_point_id: knowledgePointId || null,
    difficulty: difficulty || null,
    status: statusFilter || null,
    limit,
  }), [difficulty, knowledgePointId, limit, moduleId, projectId, statusFilter]);

  const hydrateSession = useCallback(async (sessionId: string) => {
    setWorking(true);
    setError(null);
    try {
      let next = await getPracticeSession(sessionId);
      if (next.status === "paused") {
        next = await resumePracticeSession(sessionId);
      }
      setSession(next);
      setDrafts(Object.fromEntries(next.questions.map((item) => [item.id, toDraft(item)])));
      const firstOpen = next.questions.findIndex((item) => item.submitted_at == null);
      setCurrentIndex(firstOpen >= 0 ? firstOpen : 0);
      setDirty(false);
      setReport(null);
      setProjectId(next.project_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法恢复练习会话");
    } finally {
      setWorking(false);
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const values = await getLearningProjects();
        setProjects(values);
        const qpProject = searchParams.get("project_id") || "";
        const initialProject = qpProject || values[0]?.id || "";
        setProjectId((current) => current || initialProject);

        // Prefill filters from dashboard / recommendation deep links.
        const qpLimit = Number(searchParams.get("limit") || "");
        if (Number.isFinite(qpLimit) && qpLimit > 0) setLimit(Math.min(200, Math.max(1, qpLimit)));
        const qpStatus = searchParams.get("status");
        if (qpStatus != null) setStatusFilter(qpStatus);
        const qpModule = searchParams.get("module_id");
        if (qpModule) setModuleId(qpModule);
        const qpDifficulty = searchParams.get("difficulty");
        if (qpDifficulty) setDifficulty(qpDifficulty);
        const qpMode = searchParams.get("mode");
        if (qpMode === "learning" || qpMode === "exam") setMode(qpMode);

        const sessionId = searchParams.get("sessionId") || searchParams.get("session_id");
        if (sessionId && !bootstrappedRef.current) {
          bootstrappedRef.current = true;
          await hydrateSession(sessionId);
        } else if (initialProject) {
          try {
            setResumable(await listResumablePracticeSessions(initialProject, 5));
          } catch {
            setResumable([]);
          }
        }
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "无法加载学习项目");
      } finally {
        setLoading(false);
      }
    })();
    // Only bootstrap once on mount; query changes after start are intentional navigations.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!projectId) { setModules([]); setKnowledgePoints([]); setResumable([]); return; }
    void Promise.all([getLearningModules(projectId), getLearningKnowledgePoints(projectId)])
      .then(([nextModules, nextKnowledgePoints]) => {
        setModules(nextModules);
        setKnowledgePoints(nextKnowledgePoints);
        // Keep deep-linked module if still valid; otherwise reset.
        setModuleId((current) => (current && nextModules.some((m) => m.id === current) ? current : ""));
        setKnowledgePointId("");
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "无法加载项目范围"));
    void listResumablePracticeSessions(projectId, 5).then(setResumable).catch(() => setResumable([]));
  }, [projectId]);

  useEffect(() => {
    if (!session || session.status === "completed" || !dirty) return;
    const timer = window.setTimeout(() => {
      void autosavePracticeSession(session.id, session.questions.map((item) => answerPayload(item, drafts[item.id])))
        .then((next) => { setSession(next); setDirty(false); })
        .catch((reason) => setError(reason instanceof Error ? reason.message : "自动保存失败"));
    }, 900);
    return () => window.clearTimeout(timer);
  }, [dirty, drafts, session]);

  useEffect(() => {
    if (!currentQuestion || !session) { setDiscussion(null); return; }
    void getPracticeDiscussion(session.project_id, currentQuestion.question_id)
      .then(setDiscussion)
      .catch(() => setDiscussion(null));
  }, [currentQuestion?.question_id, session?.project_id]);

  useEffect(() => {
    if (!session || session.status !== "completed") { setReport(null); return; }
    void getPracticeReport(session.id).then(setReport).catch((reason) => setError(reason instanceof Error ? reason.message : "无法加载练习报告"));
  }, [session?.id, session?.status]);

  const preview = async () => {
    if (!projectId) return;
    setWorking(true); setError(null);
    try { setProposal(await getPracticeProposal(formInput())); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "无法生成组卷预览"); }
    finally { setWorking(false); }
  };

  const start = async () => {
    if (!projectId) return;
    setWorking(true); setError(null);
    try {
      let activeProposal = proposal;
      // If user did not preview, build a proposal first so start can pin the exact set.
      if (!activeProposal || activeProposal.project_id !== projectId) {
        activeProposal = await getPracticeProposal(formInput());
        setProposal(activeProposal);
      }
      const questionIds = activeProposal.questions.map((item) => item.question_id);
      const next = await startPracticeSession({
        ...formInput(),
        mode,
        time_budget_minutes: mode === "exam" ? timeBudget : null,
        question_ids: questionIds,
        limit: questionIds.length || limit,
      });
      setSession(next);
      setDrafts(Object.fromEntries(next.questions.map((item) => [item.id, toDraft(item)])));
      setCurrentIndex(0); setDirty(false); setReport(null);
      router.replace(`/space/learning-center/practice?sessionId=${encodeURIComponent(next.id)}`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "无法开始练习"); }
    finally { setWorking(false); }
  };

  const updateDraft = (changes: Partial<Draft>) => {
    if (!currentQuestion) return;
    setDrafts((current) => ({
      ...current,
      [currentQuestion.id]: {
        ...(current[currentQuestion.id] ?? toDraft(currentQuestion)),
        ...changes,
      },
    }));
    setDirty(true);
  };

  const selectOptionKey = useCallback(
    (key: string) => {
      if (!session || !currentQuestion || !activeDraft) return;
      if (session.status === "paused" || currentQuestion.submitted_at !== null) return;
      const optionKeys = Object.keys(currentQuestion.options);
      if (!optionKeys.includes(key)) return;
      if (currentQuestion.question_type === "multiple_choice") {
        const values = activeDraft.user_answer.split(",").filter(Boolean);
        const next = values.includes(key)
          ? values.filter((value) => value !== key)
          : [...values, key];
        updateDraft({ user_answer: next.join(",") });
        return;
      }
      updateDraft({ user_answer: key });
    },
    // updateDraft closes over currentQuestion; re-bind when question/draft changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [activeDraft, currentQuestion, session],
  );

  const submitCurrent = async () => {
    if (!session || !currentQuestion) return;
    if (session.status === "paused") return;
    if (session.mode === "learning" && currentQuestion.submitted_at !== null) return;
    setWorking(true);
    setError(null);
    try {
      const next = await submitPracticeSession(session.id, [
        answerPayload(currentQuestion, drafts[currentQuestion.id]),
      ]);
      setSession(next);
      setDirty(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "提交答案失败");
    } finally {
      setWorking(false);
    }
  };

  const submitCurrentRef = useRef(submitCurrent);
  submitCurrentRef.current = submitCurrent;

  // Keyboard: 1-4 / numpad 1-4 select options by order; Space submits
  // (learning mode, when not typing in an input).
  useEffect(() => {
    if (!session || !currentQuestion || !activeDraft) return;
    if (session.status === "completed") return;

    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName?.toLowerCase();
      if (
        tag === "input" ||
        tag === "textarea" ||
        tag === "select" ||
        target?.isContentEditable
      ) {
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      const optionKeys = Object.keys(currentQuestion.options).sort((a, b) =>
        a.localeCompare(b, undefined, { numeric: true }),
      );

      // Digit 1-4 / numpad 1-4 → Nth option (A/B/C/D by sort order)
      const digit =
        event.code.startsWith("Digit")
          ? event.code.slice(5)
          : event.code.startsWith("Numpad") &&
              event.code.length === 7 &&
              event.code[6] >= "0" &&
              event.code[6] <= "9"
            ? event.code.slice(6)
            : "";
      if (digit >= "1" && digit <= "4") {
        const index = Number(digit) - 1;
        const key = optionKeys[index];
        if (!key) return;
        event.preventDefault();
        selectOptionKey(key);
        return;
      }

      if (event.code === "Space" || event.key === " ") {
        // Learning: submit current. Exam finish is explicit (交卷).
        if (
          session.mode === "learning" &&
          currentQuestion.submitted_at === null &&
          session.status !== "paused" &&
          !working
        ) {
          event.preventDefault();
          void submitCurrentRef.current();
        }
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeDraft, currentQuestion, selectOptionKey, session, working]);

  const finish = async () => {
    if (!session) return;
    setWorking(true); setError(null);
    try {
      const next = await submitPracticeSession(session.id, session.questions.map((item) => answerPayload(item, drafts[item.id])), true);
      setSession(next); setDirty(false);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "交卷失败"); }
    finally { setWorking(false); }
  };

  const togglePause = async () => {
    if (!session) return;
    setWorking(true);
    try { setSession(session.status === "paused" ? await resumePracticeSession(session.id) : await pausePracticeSession(session.id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "切换暂停状态失败"); }
    finally { setWorking(false); }
  };

  const toggleBookmark = async () => {
    if (!session || !currentQuestion) return;
    const nextValue = !bookmarked[currentQuestion.question_id];
    try {
      await setPracticeBookmark({ project_id: session.project_id, question_id: currentQuestion.question_id, bookmarked: nextValue });
      setBookmarked((current) => ({ ...current, [currentQuestion.question_id]: nextValue }));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "书签保存失败"); }
  };

  const postDiscussion = async () => {
    if (!session || !currentQuestion || !discussionText.trim()) return;
    setWorking(true);
    try {
      setDiscussion(await addPracticeDiscussion(session.project_id, currentQuestion.question_id, discussionText));
      setDiscussionText("");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "讨论保存失败"); }
    finally { setWorking(false); }
  };

  if (loading) return <div className="flex min-h-64 items-center justify-center text-sm text-[var(--muted-foreground)]"><Loader2 className="mr-2 animate-spin" size={18} />加载学习中心…</div>;

  if (!session) return (
    <div className="mx-auto w-full max-w-6xl p-4 sm:p-6 lg:p-8">
      <LearningCenterNav />
      <SpaceSectionHeader icon={Target} title="学习训练中心" description="预览后固定题集开练；刷新可通过会话链接继续。默认优先未作答。" />
      {error && <p role="alert" className="mt-4 rounded-xl border border-red-300/70 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200">{error}</p>}
      {!!resumable.length && (
        <section className="mt-5 rounded-2xl border border-emerald-500/25 bg-emerald-500/5 p-4">
          <h2 className="text-sm font-semibold">可继续的会话</h2>
          <div className="mt-3 space-y-2">
            {resumable.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => void hydrateSession(item.id)}
                className="flex w-full items-center justify-between rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-left text-sm hover:border-emerald-500/50"
              >
                <span>{item.project_name} · {item.mode === "exam" ? "考试" : "学习"} · 已答 {item.answered}/{item.total}</span>
                <span className="text-xs text-emerald-700 dark:text-emerald-300">继续</span>
              </button>
            ))}
          </div>
        </section>
      )}
      {!projects.length ? <div className="mt-6 rounded-2xl border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--muted-foreground)]">还没有可训练项目。请先在导入中心导入题目。</div> : <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5">
          <h2 className="font-semibold">组卷设置</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <label className="text-sm">项目<select value={projectId} onChange={(event) => setProjectId(event.target.value)} className="mt-1.5 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"><option value="">选择项目</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
            <label className="text-sm">模块<select value={moduleId} onChange={(event) => setModuleId(event.target.value)} className="mt-1.5 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"><option value="">全部模块</option>{modules.map((module) => <option key={module.id} value={module.id}>{module.path || module.name}</option>)}</select></label>
            <label className="text-sm">知识点<select value={knowledgePointId} onChange={(event) => setKnowledgePointId(event.target.value)} className="mt-1.5 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"><option value="">全部知识点</option>{knowledgePoints.filter((point) => !moduleId || point.module_id === moduleId).map((point) => <option key={point.id} value={point.id}>{point.name}</option>)}</select></label>
            <label className="text-sm">难度<select value={difficulty} onChange={(event) => setDifficulty(event.target.value)} className="mt-1.5 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"><option value="">全部难度</option><option value="easy">简单</option><option value="medium">中等</option><option value="hard">困难</option></select></label>
            <label className="text-sm">训练状态<select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="mt-1.5 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"><option value="unseen">优先未作答</option><option value="">全部题目（已练过也抽）</option><option value="wrong">错题</option><option value="review_due">待复习</option></select></label>
            <div className="text-sm"><span>题量</span><div className="mt-1.5 flex flex-wrap gap-2">{PRESETS.map((value) => <button type="button" key={value} onClick={() => setLimit(value)} className={`rounded-lg border px-3 py-2 text-xs ${limit === value ? "border-sky-500 bg-sky-500 text-white" : "border-[var(--border)]"}`}>{value} 题</button>)}</div></div>
          </div>
          <div className="mt-5 flex flex-wrap items-center gap-2"><span className="text-sm">模式</span>{(["learning", "exam"] as PracticeMode[]).map((value) => <button type="button" key={value} onClick={() => setMode(value)} className={`rounded-lg border px-3 py-2 text-sm ${mode === value ? "border-sky-500 bg-sky-500 text-white" : "border-[var(--border)]"}`}>{value === "learning" ? "学习模式（即时判题）" : "考试模式（交卷后解析）"}</button>)}</div>
          {mode === "exam" && <div className="mt-4 flex flex-wrap items-center gap-2 text-sm"><Clock3 size={15} /> 时限 {TIME_PRESETS.map((value) => <button type="button" key={String(value)} onClick={() => setTimeBudget(value)} className={`rounded-lg border px-3 py-1.5 text-xs ${timeBudget === value ? "border-sky-500 bg-sky-500 text-white" : "border-[var(--border)]"}`}>{value ? `${value} 分钟` : "不限时"}</button>)}</div>}
          <div className="mt-6 flex gap-3"><button type="button" onClick={() => void preview()} disabled={working || !projectId} className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm disabled:opacity-50">预览组成</button><button type="button" onClick={() => void start()} disabled={working || !projectId} className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{working && <Loader2 className="animate-spin" size={16} />}开始{mode === "learning" ? "学习" : "考试"}</button></div>
        </section>
        <aside className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5"><h2 className="font-semibold">智能组成预览</h2>{proposal ? <div className="mt-4 space-y-4 text-sm"><p><strong>{proposal.candidate_count.toLocaleString()}</strong> 道候选题，将选取 <strong>{proposal.selected_count}</strong> 道{typeof proposal.unseen_selected_count === "number" ? <>（未作答 <strong>{proposal.unseen_selected_count}</strong>，已作答 <strong>{proposal.seen_selected_count ?? 0}</strong>）</> : null}。</p><div><p className="text-xs text-[var(--muted-foreground)]">题型</p><div className="mt-1 flex flex-wrap gap-1">{Object.entries(proposal.composition.question_types).map(([name, count]) => <span key={name} className="rounded bg-[var(--muted)] px-2 py-1 text-xs">{name} {count}</span>)}</div></div><div><p className="text-xs text-[var(--muted-foreground)]">模块</p><div className="mt-1 space-y-1">{Object.entries(proposal.composition.modules).slice(0, 5).map(([name, count]) => <p key={name} className="flex justify-between text-xs"><span className="truncate">{name}</span><span>{count}</span></p>)}</div></div></div> : <p className="mt-4 text-sm text-[var(--muted-foreground)]">选择范围后查看候选题和题型分布。</p>}</aside>
      </div>}
      {selectedProject && <p className="mt-4 text-xs text-[var(--muted-foreground)]">当前项目：{selectedProject.name}。练习数据仅写入 Learning Center，不会改动旧刷题数据库。</p>}
    </div>
  );

  if (session.status === "completed" && report) return (
    <div className="mx-auto w-full max-w-5xl p-4 sm:p-6 lg:p-8"><LearningCenterNav /><SpaceSectionHeader icon={CheckCircle2} title="本次练习报告" description="会话已完成，所有原始答案和解析现已可见。" />
      <div className="mt-6 grid gap-4 sm:grid-cols-4">{[["题目", report.total], ["已答", report.answered], ["正确", report.correct], ["正确率", report.accuracy == null ? "—" : `${Math.round(report.accuracy * 100)}%`]].map(([label, value]) => <div key={String(label)} className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4"><p className="text-xs text-[var(--muted-foreground)]">{label}</p><p className="mt-1 text-2xl font-semibold">{value}</p></div>)}</div>
      <section className="mt-5 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5"><div className="flex items-center justify-between gap-2"><h2 className="font-semibold">规则建议</h2><span className="rounded-full bg-slate-500/10 px-2 py-0.5 text-[11px] text-[var(--muted-foreground)]">非模型生成</span></div><p className="mt-2 text-sm text-[var(--muted-foreground)]">{report.ai_advisory.text}</p><div className="mt-4 flex flex-wrap gap-2">{report.follow_up_actions.map((action) => {
        const href = (action as { href?: string }).href;
        if (href) return <Link key={action.type} href={href} className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm">{action.label}</Link>;
        return <button key={action.type} type="button" onClick={() => { setSession(null); setProposal(null); router.replace("/space/learning-center/practice"); }} className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm">{action.label}</button>;
      })}</div></section>
      <section className="mt-5 space-y-3">{session.questions.map((question) => <article key={question.id} className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4"><p className="text-sm font-medium">{question.position}. <ExamRichText as="span" text={question.stem} /></p><p className={`mt-2 text-sm ${question.is_correct ? "text-emerald-600" : "text-red-600"}`}>{question.is_correct === null ? "未判定" : question.is_correct ? "回答正确" : "回答错误"} · 你的答案：{question.user_answer || "未作答"}</p><p className="mt-1 text-sm">正确答案：{question.source_answer || "未提供"}</p>{question.source_explanation && <ExamRichText className="mt-2 rounded-lg bg-[var(--muted)] p-3 text-sm text-[var(--muted-foreground)]" text={question.source_explanation} />}</article>)}</section>
    </div>
  );

  return <div className="mx-auto w-full max-w-7xl p-4 sm:p-6 lg:p-8"><LearningCenterNav />
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm font-semibold">{session.mode === "learning" ? "学习模式" : "考试模式"}</p><p className="mt-1 text-xs text-[var(--muted-foreground)]">{session.status === "paused" ? "已暂停，恢复后可继续作答。" : "作答会自动保存。"}</p></div><div className="flex items-center gap-2">{remainingSeconds != null && <span className="inline-flex items-center gap-1 rounded-lg bg-[var(--muted)] px-3 py-2 text-sm tabular-nums"><Clock3 size={15} />{formatSeconds(remainingSeconds)}</span>}<button type="button" onClick={() => void togglePause()} disabled={working} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-sm">{session.status === "paused" ? <Play size={15} /> : <Pause size={15} />}{session.status === "paused" ? "继续" : "暂停"}</button><button type="button" onClick={() => void finish()} disabled={working || session.status === "paused"} className="rounded-lg bg-sky-600 px-3 py-2 text-sm text-white disabled:opacity-50">{session.mode === "exam" ? "交卷" : "结束学习"}</button></div></div>
    {error && <p role="alert" className="mb-4 rounded-xl border border-red-300/70 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
    {currentQuestion && activeDraft && <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_19rem]"><aside className="order-2 self-start rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 xl:order-2"><div className="mb-3 flex items-center justify-between"><p className="text-sm font-semibold">题目导航</p><span className="text-xs text-[var(--muted-foreground)]">{currentIndex + 1} / {session.questions.length}</span></div><div className="grid grid-cols-5 gap-1.5 sm:grid-cols-10 xl:grid-cols-5">{session.questions.map((item, index) => <button type="button" key={item.id} onClick={() => setCurrentIndex(index)} className={`rounded-md px-2 py-1.5 text-xs ${index === currentIndex ? "bg-sky-600 text-white" : item.submitted_at ? "bg-emerald-100 text-emerald-700" : (drafts[item.id]?.marked_for_review ? "bg-amber-100 text-amber-800" : "bg-[var(--muted)]")}`}>{item.position}</button>)}</div></aside>
      <main className="order-1 min-w-0 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 sm:p-7 xl:order-1"><div className="flex items-start justify-between gap-3"><p className="text-sm text-[var(--muted-foreground)]">第 {currentQuestion.position} 题 · {currentQuestion.question_type}</p><button type="button" onClick={() => void toggleBookmark()} className={`rounded-lg p-2 ${bookmarked[currentQuestion.question_id] ? "text-amber-500" : "text-[var(--muted-foreground)]"}`} aria-label="收藏题目"><Bookmark size={18} fill={bookmarked[currentQuestion.question_id] ? "currentColor" : "none"} /></button></div><ExamRichText as="h1" className="mt-5 max-w-4xl text-xl font-semibold leading-9 sm:text-2xl sm:leading-10" text={currentQuestion.stem} />
        <div className="mt-7 grid gap-3">{Object.entries(currentQuestion.options).map(([key, content]) => <label key={key} className={`flex cursor-pointer gap-4 rounded-xl border p-4 text-[15px] leading-6 transition-colors ${activeDraft.user_answer === key ? "border-sky-500 bg-sky-50/70 dark:bg-sky-950/20" : "border-[var(--border)]"}`}><input type={currentQuestion.question_type === "multiple_choice" ? "checkbox" : "radio"} name={currentQuestion.id} checked={currentQuestion.question_type === "multiple_choice" ? activeDraft.user_answer.split(",").filter(Boolean).includes(key) : activeDraft.user_answer === key} onChange={() => { const values = currentQuestion.question_type === "multiple_choice" ? activeDraft.user_answer.split(",").filter(Boolean) : []; const next = values.includes(key) ? values.filter((value) => value !== key) : [...values, key]; updateDraft({ user_answer: currentQuestion.question_type === "multiple_choice" ? next.sort().join(",") : key }); }} disabled={session.status === "paused" || currentQuestion.submitted_at !== null} /><span className="min-w-0"><strong>{key}.</strong> <ExamRichText as="span" text={content} /></span></label>)}</div>
        {!Object.keys(currentQuestion.options).length && <textarea value={activeDraft.user_answer} onChange={(event) => updateDraft({ user_answer: event.target.value })} disabled={session.status === "paused" || currentQuestion.submitted_at !== null} className="mt-5 min-h-28 w-full rounded-xl border border-[var(--border)] bg-transparent p-3 text-sm" placeholder="输入你的答案" />}
        <div className="mt-5 flex flex-wrap gap-2"><span className="py-2 text-xs text-[var(--muted-foreground)]">把握：</span>{(["sure", "uncertain", "guess"] as const).map((value) => <button type="button" key={value} onClick={() => updateDraft({ confidence: value })} className={`rounded-lg border px-2.5 py-1.5 text-xs ${activeDraft.confidence === value ? "border-sky-500 text-sky-600" : "border-[var(--border)]"}`}>{value === "sure" ? "确定" : value === "uncertain" ? "不确定" : "猜测"}</button>)}<button type="button" onClick={() => updateDraft({ marked_for_review: !activeDraft.marked_for_review })} className={`rounded-lg border px-2.5 py-1.5 text-xs ${activeDraft.marked_for_review ? "border-amber-500 text-amber-600" : "border-[var(--border)]"}`}>标记复查</button></div>
        {Object.keys(currentQuestion.options).length > 0 && <div className="mt-3 flex flex-wrap gap-2 text-xs text-[var(--muted-foreground)]"><span className="py-1">排除：</span>{Object.keys(currentQuestion.options).map((key) => <button type="button" key={key} onClick={() => updateDraft({ eliminated_option_keys: activeDraft.eliminated_option_keys.includes(key) ? activeDraft.eliminated_option_keys.filter((value) => value !== key) : [...activeDraft.eliminated_option_keys, key] })} className={`rounded px-2 py-1 ${activeDraft.eliminated_option_keys.includes(key) ? "bg-red-100 text-red-700 line-through" : "bg-[var(--muted)]"}`}>{key}</button>)}</div>}
        {currentQuestion.source_answer !== undefined && <div className={`mt-5 rounded-xl border p-4 ${currentQuestion.is_correct ? "border-emerald-300 bg-emerald-50/70" : "border-red-300 bg-red-50/70"}`}><p className="text-sm font-medium">{currentQuestion.is_correct ? "回答正确" : "回答错误"} · 原始答案：{currentQuestion.source_answer || "未提供"}</p>{currentQuestion.source_explanation && <ExamRichText className="mt-2 text-sm text-[var(--muted-foreground)]" text={currentQuestion.source_explanation} />}<p className="mt-2 text-xs text-[var(--muted-foreground)]">来源：{currentQuestion.provenance?.kind === "ai_generated" ? `AI 生成解析${currentQuestion.provenance.model ? `（${currentQuestion.provenance.model}）` : ""}` : "原始题库"}</p></div>}
        <div className="mt-6 flex items-center justify-between"><button type="button" onClick={() => setCurrentIndex((index) => Math.max(0, index - 1))} disabled={currentIndex === 0} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-40"><ChevronLeft size={16} />上一题</button>{session.mode === "learning" && currentQuestion.submitted_at === null && <button type="button" onClick={() => void submitCurrent()} disabled={working || session.status === "paused"} className="rounded-lg bg-sky-600 px-4 py-2 text-sm text-white">提交并判题</button>}<button type="button" onClick={() => setCurrentIndex((index) => Math.min(session.questions.length - 1, index + 1))} disabled={currentIndex === session.questions.length - 1} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-40">下一题<ChevronRight size={16} /></button></div>
      </main>
      <aside className="order-3 self-start rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 xl:col-start-2 xl:row-start-2"><div className="flex items-center gap-2"><MessageCircle size={16} /><h2 className="text-sm font-semibold">本题笔记</h2></div><p className="mt-1 text-xs text-[var(--muted-foreground)]">当前仅保存你的笔记，不会自动调用 AI 教练。</p><div className="mt-3 max-h-60 space-y-2 overflow-auto">{discussion?.messages.length ? discussion.messages.map((message) => <p key={message.id} className={`rounded-lg p-2 text-xs ${message.role === "user" ? "bg-sky-50 text-sky-900 dark:bg-sky-950/30 dark:text-sky-100" : "bg-[var(--muted)]"}`}>{message.content}</p>) : <p className="text-xs text-[var(--muted-foreground)]">还没有讨论记录。</p>}</div><textarea value={discussionText} onChange={(event) => setDiscussionText(event.target.value)} className="mt-3 min-h-20 w-full rounded-lg border border-[var(--border)] bg-transparent p-2 text-xs" placeholder="记录你的疑问或推理…" /><button type="button" onClick={() => void postDiscussion()} disabled={working || !discussionText.trim()} className="mt-2 inline-flex w-full items-center justify-center gap-1 rounded-lg border border-[var(--border)] py-2 text-xs disabled:opacity-50"><Send size={13} />保存讨论</button><div className="mt-4 rounded-lg bg-[var(--muted)] p-3 text-xs text-[var(--muted-foreground)]"><Sparkles className="mb-1" size={14} />AI 深度讨论会在后续增强中使用已保存的题目、答案和你的推理作为上下文。</div></aside>
    </div>}
  </div>;
}
