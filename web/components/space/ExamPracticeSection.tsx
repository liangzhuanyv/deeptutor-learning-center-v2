"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpenCheck,
  BrainCircuit,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  ClipboardCheck,
  Loader2,
  RotateCcw,
  Sparkles,
  Target,
  Upload,
  XCircle,
} from "lucide-react";

import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import ExamQuestionDiscussionDialog from "@/components/space/ExamQuestionDiscussionDialog";
import {
  createPracticeSession,
  getChapterStatistics,
  getWeakPointInsights,
  getWrongStatistics,
  listExamBanks,
  listExamChapters,
  listExamSubjects,
  listWrongBook,
  submitPracticeAnswer,
  updateWrongBookStatus,
  type ExamBank,
  type ExamChapter,
  type ExamSubject,
  type PracticeQuestion,
  type PracticeSession,
  type WeakPointInsight,
  type WrongBookItem,
  type WrongStatistics,
} from "@/lib/exam-practice-api";

type Tab = "practice" | "wrong-book" | "insights";
const QUESTION_TYPES = ["单选", "多选", "判断", "不定项"];
const COUNTS = [10, 20, 30, 50, 100];

function displayAnswer(answer: string): string {
  return answer.replace(/[,，、\s]+/g, "").toUpperCase();
}

function optionEntries(question: PracticeQuestion): Array<[string, string]> {
  return Object.entries(question.options ?? {}).sort(([a], [b]) =>
    a.localeCompare(b, "en"),
  );
}

function isMulti(question: PracticeQuestion): boolean {
  return question.question_type.includes("多") || question.question_type.includes("不定");
}

function ErrorMessage({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="mb-4 flex items-start gap-2 rounded-xl border border-red-500/30 bg-red-500/5 px-3 py-2.5 text-[13px] text-red-600 dark:text-red-400">
      <CircleAlert size={16} className="mt-0.5 shrink-0" />
      <span>{error}</span>
    </div>
  );
}

function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: number | string;
  hint: string;
}) {
  return (
    <div className="rounded-xl border border-[var(--border)]/70 bg-[var(--card)] px-4 py-3">
      <p className="text-[12px] text-[var(--muted-foreground)]">{label}</p>
      <p className="mt-1 text-xl font-semibold tracking-tight text-[var(--foreground)]">{value}</p>
      <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">{hint}</p>
    </div>
  );
}

export default function ExamPracticeSection() {
  const [tab, setTab] = useState<Tab>("practice");
  const [banks, setBanks] = useState<ExamBank[]>([]);
  const [subjects, setSubjects] = useState<ExamSubject[]>([]);
  const [chapters, setChapters] = useState<ExamChapter[]>([]);
  const [selectedBankId, setSelectedBankId] = useState("");
  const [selectedSubjectId, setSelectedSubjectId] = useState("");
  const [selectedChapterId, setSelectedChapterId] = useState("");
  const [selectedTypes, setSelectedTypes] = useState<string[]>([]);
  const [count, setCount] = useState(20);
  const [session, setSession] = useState<PracticeSession | null>(null);
  const [questionIndex, setQuestionIndex] = useState(0);
  const [draftAnswers, setDraftAnswers] = useState<Record<string, string>>({});
  const [wrongItems, setWrongItems] = useState<WrongBookItem[]>([]);
  const [selectedWrongQuestionId, setSelectedWrongQuestionId] = useState<string | null>(null);
  const [wrongStats, setWrongStats] = useState<WrongStatistics | null>(null);
  const [insights, setInsights] = useState<WeakPointInsight[]>([]);
  const [chapterStats, setChapterStats] = useState<Array<{ chapter_name: string; wrong_attempts: number; wrong_question_count: number }>>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedSubject = useMemo(
    () => subjects.find((item) => item.id === selectedSubjectId) ?? null,
    [subjects, selectedSubjectId],
  );
  const currentQuestion = session?.questions[questionIndex] ?? null;
  const selectedAnswer = currentQuestion
    ? (draftAnswers[currentQuestion.id] ?? currentQuestion.user_answer ?? "")
    : "";

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const nextBanks = await listExamBanks();
      setBanks(nextBanks);
      const keepBank = nextBanks.some((bank) => bank.id === selectedBankId)
        ? selectedBankId
        : nextBanks[0]?.id ?? "";
      setSelectedBankId(keepBank);
      if (!keepBank) {
        setSubjects([]);
        setChapters([]);
        return;
      }
      const nextSubjects = await listExamSubjects(keepBank);
      setSubjects(nextSubjects);
      const keepSubject = nextSubjects.some((subject) => subject.id === selectedSubjectId)
        ? selectedSubjectId
        : nextSubjects[0]?.id ?? "";
      setSelectedSubjectId(keepSubject);
      if (keepSubject) {
        const nextChapters = await listExamChapters(keepSubject);
        setChapters(nextChapters);
      } else {
        setChapters([]);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载题库失败");
    } finally {
      setLoading(false);
    }
  }, [selectedBankId, selectedSubjectId]);

  const loadReview = useCallback(async () => {
    try {
      const [wrong, stats, nextInsights, nextChapterStats] = await Promise.all([
        listWrongBook(),
        getWrongStatistics(),
        getWeakPointInsights(selectedSubjectId || undefined).catch(() => []),
        getChapterStatistics(selectedSubjectId || undefined).catch(() => []),
      ]);
      setWrongItems(wrong.items);
      setWrongStats(stats);
      setInsights(nextInsights);
      setChapterStats(nextChapterStats);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载错题本失败");
    }
  }, [selectedSubjectId]);

  useEffect(() => {
    void loadCatalog();
    // Catalog starts on mount only; subsequent controls load their own slice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (tab === "wrong-book" || tab === "insights") void loadReview();
  }, [tab, loadReview]);

  const changeBank = useCallback(async (bankId: string) => {
    setSelectedBankId(bankId);
    setSelectedSubjectId("");
    setSelectedChapterId("");
    setChapters([]);
    setError(null);
    try {
      const nextSubjects = await listExamSubjects(bankId);
      setSubjects(nextSubjects);
      const firstSubject = nextSubjects[0]?.id ?? "";
      setSelectedSubjectId(firstSubject);
      if (firstSubject) setChapters(await listExamChapters(firstSubject));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载科目失败");
    }
  }, []);

  const changeSubject = useCallback(async (subjectId: string) => {
    setSelectedSubjectId(subjectId);
    setSelectedChapterId("");
    setError(null);
    try {
      setChapters(await listExamChapters(subjectId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载章节失败");
    }
  }, []);

  const startPractice = useCallback(async () => {
    if (!selectedSubjectId) return;
    setStarting(true);
    setError(null);
    try {
      const scope = selectedChapterId
        ? chapters.find((chapter) => chapter.id === selectedChapterId)?.name ?? "章节"
        : selectedSubject?.name ?? "科目";
      const result = await createPracticeSession({
        title: `${scope} · ${count} 题练习`,
        subject_id: selectedSubjectId,
        chapter_id: selectedChapterId || undefined,
        question_types: selectedTypes.length ? selectedTypes : undefined,
        limit: count,
      });
      setSession(result);
      setQuestionIndex(0);
      setDraftAnswers({});
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建练习失败");
    } finally {
      setStarting(false);
    }
  }, [chapters, count, selectedChapterId, selectedSubject, selectedSubjectId, selectedTypes]);

  const setAnswer = useCallback((question: PracticeQuestion, key: string) => {
    setDraftAnswers((previous) => {
      const current = displayAnswer(previous[question.id] ?? question.user_answer ?? "");
      if (!isMulti(question)) return { ...previous, [question.id]: key };
      const next = current.includes(key)
        ? current.replace(key, "")
        : `${current}${key}`;
      return { ...previous, [question.id]: displayAnswer(next) };
    });
  }, []);

  const submitCurrent = useCallback(async () => {
    if (!session || !currentQuestion || !selectedAnswer || currentQuestion.submitted_at) return;
    setSubmitting(true);
    setError(null);
    try {
      const nextSession = await submitPracticeAnswer(session.id, currentQuestion.id, selectedAnswer);
      setSession(nextSession);
      setDraftAnswers((previous) => ({
        ...previous,
        [currentQuestion.id]: selectedAnswer,
      }));
      void loadReview();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "提交答案失败");
    } finally {
      setSubmitting(false);
    }
  }, [currentQuestion, loadReview, selectedAnswer, session]);

  const toggleMastered = useCallback(async (item: WrongBookItem) => {
    try {
      await updateWrongBookStatus(
        item.question_id,
        item.mastery_status === "mastered" ? "learning" : "mastered",
      );
      await loadReview();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "更新掌握状态失败");
    }
  }, [loadReview]);

  const toggleType = (type: string) => {
    setSelectedTypes((previous) =>
      previous.includes(type) ? previous.filter((item) => item !== type) : [...previous, type],
    );
  };

  if (loading) {
    return (
      <div className="flex min-h-[360px] items-center justify-center text-[var(--muted-foreground)]">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  return (
    <section>
      <SpaceSectionHeader
        icon={BookOpenCheck}
        title="刷题中心"
        description="按科目与章节随机练习；交卷后查看解析，错题自动沉淀为可复习的错题本。"
        meta={
          <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:text-emerald-300">
            基金从业 · 证券从业
          </span>
        }
        action={
          <Link
            href="/space/learning-center/imports"
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-2 text-[12px] font-medium text-[var(--foreground)] hover:bg-[var(--muted)]"
          >
            <Upload size={14} /> 导入题库
          </Link>
        }
      />
      <ErrorMessage error={error} />

      <div className="mb-6 flex gap-1 rounded-xl border border-[var(--border)]/70 bg-[var(--muted)]/25 p-1">
        {([
          ["practice", ClipboardCheck, "章节刷题"],
          ["wrong-book", RotateCcw, "错题本"],
          ["insights", BrainCircuit, "易错知识点"],
        ] as const).map(([key, Icon, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-[13px] transition-colors ${
              tab === key
                ? "bg-[var(--card)] font-medium text-[var(--foreground)] shadow-sm"
                : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
          >
            <Icon size={15} />
            {label}
          </button>
        ))}
      </div>

      {tab === "practice" && !session && (
        <div className="space-y-5">
          {!banks.length ? (
            <div className="rounded-2xl border border-dashed border-[var(--border)] p-10 text-center">
              <BookOpenCheck className="mx-auto h-9 w-9 text-[var(--muted-foreground)]/55" />
              <p className="mt-3 font-medium text-[var(--foreground)]">题库正在准备中</p>
              <p className="mx-auto mt-1 max-w-md text-[13px] leading-relaxed text-[var(--muted-foreground)]">
                导入完成后，这里会显示基金从业和证券从业的科目、章节与练习入口。
              </p>
            </div>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                {banks.map((bank) => {
                  const selected = bank.id === selectedBankId;
                  return (
                    <button
                      key={bank.id}
                      onClick={() => void changeBank(bank.id)}
                      className={`rounded-xl border p-4 text-left transition-all ${
                        selected
                          ? "border-[var(--primary)] bg-[var(--primary)]/5 ring-1 ring-[var(--primary)]/25"
                          : "border-[var(--border)]/70 bg-[var(--card)] hover:border-[var(--primary)]/45"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="font-medium text-[var(--foreground)]">{bank.name}</p>
                          <p className="mt-1 text-[12px] text-[var(--muted-foreground)]">{bank.question_count.toLocaleString()} 道题目</p>
                        </div>
                        {selected && <CheckCircle2 size={18} className="text-[var(--primary)]" />}
                      </div>
                    </button>
                  );
                })}
              </div>

              <div className="rounded-2xl border border-[var(--border)]/70 bg-[var(--card)] p-5">
                <div className="grid gap-5 md:grid-cols-2">
                  <label className="block">
                    <span className="mb-1.5 block text-[12px] font-medium text-[var(--muted-foreground)]">科目</span>
                    <select value={selectedSubjectId} onChange={(event) => void changeSubject(event.target.value)} className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]">
                      {subjects.map((subject) => <option key={subject.id} value={subject.id}>{subject.name}（{subject.question_count}题）</option>)}
                    </select>
                  </label>
                  <label className="block">
                    <span className="mb-1.5 block text-[12px] font-medium text-[var(--muted-foreground)]">章节 <em className="ml-1 not-italic font-normal">（可选）</em></span>
                    <select value={selectedChapterId} onChange={(event) => setSelectedChapterId(event.target.value)} className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]">
                      <option value="">全科目随机</option>
                      {chapters.map((chapter) => <option key={chapter.id} value={chapter.id}>{chapter.path || chapter.name}（{chapter.question_count}题）</option>)}
                    </select>
                  </label>
                </div>

                <div className="mt-5 border-t border-[var(--border)]/60 pt-4">
                  <p className="text-[12px] font-medium text-[var(--muted-foreground)]">题型 <span className="font-normal">（不选则包含全部题型）</span></p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {QUESTION_TYPES.map((type) => (
                      <button key={type} onClick={() => toggleType(type)} className={`rounded-full border px-3 py-1.5 text-[12px] transition-colors ${selectedTypes.includes(type) ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]" : "border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"}`}>{type}</button>
                    ))}
                  </div>
                </div>

                <div className="mt-5 flex flex-col gap-4 border-t border-[var(--border)]/60 pt-4 sm:flex-row sm:items-end sm:justify-between">
                  <div>
                    <p className="text-[12px] font-medium text-[var(--muted-foreground)]">本次题量</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {COUNTS.map((number) => <button key={number} onClick={() => setCount(number)} className={`min-w-10 rounded-lg px-2.5 py-1.5 text-[12px] ${count === number ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : "bg-[var(--muted)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"}`}>{number}</button>)}
                    </div>
                  </div>
                  <button disabled={!selectedSubjectId || starting} onClick={() => void startPractice()} className="inline-flex items-center justify-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2.5 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-45">
                    {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Target size={16} />}
                    开始刷题
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {tab === "practice" && session && currentQuestion && (
        <div className="grid gap-5 lg:grid-cols-[210px_minmax(0,1fr)]">
          <aside className="rounded-2xl border border-[var(--border)]/70 bg-[var(--card)] p-3 lg:sticky lg:top-5 lg:h-fit">
            <div className="flex items-center justify-between px-1 pb-3">
              <div><p className="text-[12px] font-medium text-[var(--foreground)]">{session.title}</p><p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">已答 {session.answered} / {session.total}</p></div>
              <span className={`rounded-full px-2 py-0.5 text-[10px] ${session.status === "completed" ? "bg-emerald-500/10 text-emerald-700" : "bg-amber-500/10 text-amber-700"}`}>{session.status === "completed" ? "已完成" : "练习中"}</span>
            </div>
            <div className="grid grid-cols-5 gap-1.5">
              {session.questions.map((question, index) => <button key={question.id} onClick={() => setQuestionIndex(index)} className={`h-8 rounded-md text-[11px] font-medium ${index === questionIndex ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : question.is_correct === true ? "bg-emerald-500/10 text-emerald-700" : question.is_correct === false ? "bg-red-500/10 text-red-600" : "bg-[var(--muted)] text-[var(--muted-foreground)]"}`}>{index + 1}</button>)}
            </div>
            <button onClick={() => { setSession(null); setQuestionIndex(0); }} className="mt-4 w-full rounded-lg border border-[var(--border)] px-2 py-2 text-[12px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]">结束并返回设置</button>
          </aside>

          <article className="rounded-2xl border border-[var(--border)]/70 bg-[var(--card)] p-5 sm:p-6">
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--muted-foreground)]"><span className="rounded-full bg-[var(--muted)] px-2 py-1">第 {currentQuestion.position} 题</span><span>{currentQuestion.question_type}</span><span>·</span><span>{currentQuestion.chapter_name || currentQuestion.subject_name}</span></div>
            <h2 className="mt-4 text-[17px] font-medium leading-relaxed text-[var(--foreground)]">{currentQuestion.stem}</h2>
            <div className="mt-6 space-y-2.5">
              {optionEntries(currentQuestion).map(([key, option]) => {
                const picked = displayAnswer(selectedAnswer).includes(key);
                const submitted = Boolean(currentQuestion.submitted_at);
                const correct = submitted && displayAnswer(currentQuestion.source_answer ?? "").includes(key);
                const wrongPick = submitted && picked && !correct;
                return <button key={key} disabled={submitted} onClick={() => setAnswer(currentQuestion, key)} className={`flex w-full items-start gap-3 rounded-xl border px-3.5 py-3 text-left text-[13px] transition-colors disabled:cursor-default ${correct ? "border-emerald-500/45 bg-emerald-500/7" : wrongPick ? "border-red-500/45 bg-red-500/7" : picked ? "border-[var(--primary)] bg-[var(--primary)]/6" : "border-[var(--border)] hover:border-[var(--primary)]/40"}`}><span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold ${correct ? "border-emerald-500 bg-emerald-500 text-white" : wrongPick ? "border-red-500 bg-red-500 text-white" : picked ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]" : "border-[var(--border)] text-[var(--muted-foreground)]"}`}>{correct ? <Check size={13} /> : wrongPick ? <XCircle size={13} /> : key}</span><span className="leading-relaxed text-[var(--foreground)]">{option}</span></button>;
              })}
            </div>

            {!currentQuestion.submitted_at ? <div className="mt-6 flex justify-end"><button disabled={!selectedAnswer || submitting} onClick={() => void submitCurrent()} className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2.5 text-[13px] font-medium text-[var(--primary-foreground)] disabled:opacity-40">{submitting && <Loader2 className="h-4 w-4 animate-spin" />}提交本题</button></div> : <div className={`mt-6 rounded-xl border p-4 ${currentQuestion.is_correct ? "border-emerald-500/30 bg-emerald-500/5" : "border-red-500/30 bg-red-500/5"}`}><div className="flex items-center gap-2 font-medium text-[var(--foreground)]">{currentQuestion.is_correct ? <CheckCircle2 size={18} className="text-emerald-600" /> : <XCircle size={18} className="text-red-500" />}{currentQuestion.is_correct ? "回答正确" : "已加入错题本"}<span className="ml-auto text-[12px] font-normal text-[var(--muted-foreground)]">答案：{currentQuestion.source_answer || "待 AI 复核"}</span></div><div className="mt-3 border-t border-[var(--border)]/60 pt-3"><p className="text-[12px] font-medium text-[var(--muted-foreground)]">解析</p><p className="mt-1.5 whitespace-pre-wrap text-[13px] leading-relaxed text-[var(--foreground)]">{currentQuestion.source_explanation || currentQuestion.ai_explanation || "这道题暂缺原始解析，AI 补全任务会自动生成解析后显示在这里。"}</p>{!currentQuestion.source_explanation && currentQuestion.ai_explanation && <p className="mt-2 inline-flex items-center gap-1 text-[11px] text-violet-600 dark:text-violet-300"><Sparkles size={12} />AI 补充解析</p>}</div></div>}
            <div className="mt-6 flex items-center justify-between border-t border-[var(--border)]/60 pt-4"><button disabled={questionIndex === 0} onClick={() => setQuestionIndex((value) => Math.max(0, value - 1))} className="inline-flex items-center gap-1 text-[12px] text-[var(--muted-foreground)] disabled:opacity-30"><ArrowLeft size={14} />上一题</button><button disabled={questionIndex >= session.questions.length - 1} onClick={() => setQuestionIndex((value) => Math.min(session.questions.length - 1, value + 1))} className="inline-flex items-center gap-1 text-[12px] text-[var(--muted-foreground)] disabled:opacity-30">下一题<ArrowRight size={14} /></button></div>
          </article>
        </div>
      )}

      {tab === "wrong-book" && <div className="space-y-5">{wrongStats && <div className="grid grid-cols-2 gap-3 sm:grid-cols-4"><StatCard label="错题数" value={wrongStats.total_questions} hint="曾答错的题目" /><StatCard label="错误次数" value={wrongStats.total_wrong_attempts} hint="累计错误提交" /><StatCard label="待掌握" value={wrongStats.learning_count} hint="需要复习" /><StatCard label="已掌握" value={wrongStats.mastered_count} hint="手动或复练标记" /></div>}<div className="rounded-2xl border border-[var(--border)]/70 bg-[var(--card)]">{wrongItems.length === 0 ? <div className="p-10 text-center"><CheckCircle2 className="mx-auto h-9 w-9 text-emerald-500/70" /><p className="mt-3 text-[13px] font-medium text-[var(--foreground)]">还没有错题</p><p className="mt-1 text-[12px] text-[var(--muted-foreground)]">开始章节练习后，答错题目会自动汇总到这里。</p></div> : wrongItems.map((item) => <div key={item.question_id} role="button" tabIndex={0} onClick={() => setSelectedWrongQuestionId(item.question_id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedWrongQuestionId(item.question_id); } }} className="flex w-full cursor-pointer flex-col gap-3 border-b border-[var(--border)]/60 p-4 text-left transition-colors last:border-0 hover:bg-[var(--muted)]/35 sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><div className="mb-1 flex flex-wrap items-center gap-2 text-[11px] text-[var(--muted-foreground)]"><span>{item.subject_name}</span><ChevronRight size={12} /><span>{item.chapter_name || "未分类章节"}</span><span className="rounded-full bg-red-500/10 px-1.5 py-0.5 text-red-600">错 {item.wrong_count} 次</span><span className="text-[var(--primary)]">点击查看详情并讨论</span></div><p className="line-clamp-2 text-[13px] leading-relaxed text-[var(--foreground)]">{item.stem}</p></div><button onClick={(event) => { event.stopPropagation(); void toggleMastered(item); }} className={`shrink-0 rounded-lg border px-3 py-1.5 text-[12px] ${item.mastery_status === "mastered" ? "border-emerald-500/35 bg-emerald-500/8 text-emerald-700" : "border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"}`}>{item.mastery_status === "mastered" ? "已掌握" : "标记已掌握"}</button></div>)}</div></div>}

      {tab === "insights" && <div className="space-y-5">{insights.length === 0 ? <div className="rounded-2xl border border-dashed border-[var(--border)] p-10 text-center"><BrainCircuit className="mx-auto h-9 w-9 text-violet-500/60" /><p className="mt-3 font-medium text-[var(--foreground)]">还没有足够的错题模式</p><p className="mx-auto mt-1 max-w-md text-[13px] leading-relaxed text-[var(--muted-foreground)]">完成一些章节练习后，系统会按错误集中章节、错误次数和题目解析归纳易错知识点。</p></div> : <><div className="grid gap-3 md:grid-cols-2">{insights.map((insight, index) => <div key={`${insight.title}-${index}`} className="rounded-2xl border border-violet-500/20 bg-violet-500/[0.035] p-4"><div className="flex items-start gap-2"><span className="mt-0.5 rounded-lg bg-violet-500/10 p-1.5 text-violet-600"><BrainCircuit size={15} /></span><div><p className="text-[11px] text-[var(--muted-foreground)]">{insight.subject_name ? `${insight.subject_name} · ` : ""}{insight.chapter_name || "综合"}</p><h3 className="mt-1 text-[14px] font-medium text-[var(--foreground)]">{insight.title}</h3></div></div><p className="mt-3 text-[13px] leading-relaxed text-[var(--muted-foreground)]">{insight.summary}</p><div className="mt-3 flex items-center gap-3 text-[11px] text-violet-700 dark:text-violet-300"><span>{insight.wrong_question_count} 道关联错题</span><span>{insight.total_wrong_attempts} 次错误</span></div></div>)}</div><div className="rounded-xl border border-[var(--border)]/70 bg-[var(--card)] p-4"><p className="text-[12px] font-medium text-[var(--muted-foreground)]">按章节的错误热度</p><div className="mt-3 space-y-3">{chapterStats.filter((item) => item.wrong_attempts > 0).slice(0, 8).map((item) => <div key={item.chapter_name}><div className="mb-1 flex justify-between gap-4 text-[12px]"><span className="truncate text-[var(--foreground)]">{item.chapter_name || "未分类章节"}</span><span className="shrink-0 text-[var(--muted-foreground)]">{item.wrong_attempts} 次错误</span></div><div className="h-1.5 overflow-hidden rounded-full bg-[var(--muted)]"><div className="h-full rounded-full bg-violet-500" style={{ width: `${Math.min(100, Math.max(8, item.wrong_question_count * 12))}%` }} /></div></div>)}</div></div></>}</div>}
      {selectedWrongQuestionId && (
        <ExamQuestionDiscussionDialog
          questionId={selectedWrongQuestionId}
          onClose={() => setSelectedWrongQuestionId(null)}
        />
      )}
    </section>
  );
}
