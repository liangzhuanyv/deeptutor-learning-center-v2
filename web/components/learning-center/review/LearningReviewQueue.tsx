"use client";
/* eslint-disable i18n/no-literal-ui-text -- Chinese-first Learning Center v2 UI. */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Loader2, RefreshCw, RotateCcw, ShieldCheck, Target } from "lucide-react";

import LearningCenterNav from "@/components/learning-center/LearningCenterNav";
import ExamRichText from "@/components/learning-center/ExamRichText";
import LearningQuestionAIDiscussion from "@/components/learning-center/LearningQuestionAIDiscussion";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import {
  getLearningProjects,
  getMasteryQuestionDetail,
  getReviewQueue,
  setQuestionMastery,
  type LearningProjectOption,
  type MasteryQuestionDetail,
  type ReviewQueueItem,
} from "@/lib/learning-center-api";

const FILTERS = [
  ["due", "待复习"],
  ["all_wrong", "全部错题"],
  ["repeated", "反复错误"],
  ["reopen", "建议重新打开"],
  ["manual_mastered", "手动已掌握"],
] as const;

export default function LearningReviewQueue() {
  const [projects, setProjects] = useState<LearningProjectOption[]>([]);
  const [projectId, setProjectId] = useState("");
  const [filter, setFilter] = useState<(typeof FILTERS)[number][0]>("due");
  const [items, setItems] = useState<ReviewQueueItem[]>([]);
  const [selected, setSelected] = useState<MasteryQuestionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");

  useEffect(() => {
    void getLearningProjects()
      .then((result) => {
        setProjects(result);
        setProjectId(result[0]?.id ?? "");
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "无法加载项目"))
      .finally(() => setLoading(false));
  }, []);

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      setItems(await getReviewQueue({ project_id: projectId, filter }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法加载复习队列");
    } finally {
      setLoading(false);
    }
  }, [filter, projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const select = async (questionId: string) => {
    try {
      setSelected(await getMasteryQuestionDetail(questionId));
      setNote("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法加载错题详情");
    }
  };

  const override = async (mastered: boolean) => {
    if (!selected) return;
    try {
      setSelected(await setQuestionMastery(selected.question.id, mastered, note));
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存掌握状态失败");
    }
  };

  return (
    <div className="mx-auto w-full max-w-7xl p-4 sm:p-6 lg:p-8">
      <LearningCenterNav />
      <SpaceSectionHeader
        icon={RotateCcw}
        title="错题与复习队列"
        description="「待复习」与总览待复习风险对齐：包含 review_due / reviewing / reopen 等仍需处理的错题。手动已掌握不会删除证据。"
      />
      {error && (
        <p role="alert" className="mt-4 rounded-xl border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}
      <div className="mt-5 flex flex-wrap gap-2">
        <select
          value={projectId}
          onChange={(event) => setProjectId(event.target.value)}
          className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm"
        >
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
        {FILTERS.map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setFilter(value)}
            className={`rounded-lg border px-3 py-2 text-sm ${
              filter === value ? "border-sky-500 bg-sky-600 text-white" : "border-[var(--border)]"
            }`}
          >
            {label}
          </button>
        ))}
        <Link
          href={`/space/learning-center/practice?project_id=${encodeURIComponent(projectId)}&status=wrong&limit=10`}
          className="inline-flex items-center gap-1 rounded-lg bg-[var(--foreground)] px-3 py-2 text-sm font-medium text-[var(--background)]"
        >
          <Target size={15} /> 重练当前风险题
        </Link>
        <button type="button" onClick={() => void load()} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-sm">
          <RefreshCw size={15} /> 刷新
        </button>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_30rem]">
        <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)]">
          <div className="border-b border-[var(--border)] px-4 py-3 text-sm font-medium">
            {loading ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="animate-spin" size={15} /> 加载中
              </span>
            ) : (
              `共 ${items.length} 题`
            )}
          </div>
          {!loading && !items.length && (
            <p className="p-8 text-center text-sm text-[var(--muted-foreground)]">当前筛选下没有题目。</p>
          )}
          {items.map((item) => (
            <button
              type="button"
              key={item.question_id}
              onClick={() => void select(item.question_id)}
              className={`block w-full border-b border-[var(--border)]/60 p-4 text-left hover:bg-[var(--muted)] ${
                selected?.question.id === item.question_id ? "bg-[var(--muted)]" : ""
              }`}
            >
              <ExamRichText className="line-clamp-2 text-sm font-medium" text={item.stem} />
              <p className="mt-2 text-[11px] text-[var(--muted-foreground)]">
                {item.state} · 错 {item.wrong_count} · {item.system_mastery_level || "unseen"}
              </p>
            </button>
          ))}
        </section>

        <aside className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5">
          {selected ? (
            <>
              <div className="flex items-center gap-2">
                <ShieldCheck size={17} />
                <h2 className="font-semibold">错题证据详情</h2>
              </div>
              <ExamRichText className="mt-4 text-sm font-medium leading-6" text={selected.question.stem} />
              {selected.question.options && Object.keys(selected.question.options).length > 0 && (
                <div className="mt-3 space-y-1 text-sm">
                  {Object.entries(selected.question.options).map(([key, value]) => (
                    <div key={key} className="rounded-lg border border-[var(--border)]/70 px-3 py-2">
                      <span className="font-medium">{key}. </span>
                      <ExamRichText as="span" text={String(value)} />
                    </div>
                  ))}
                </div>
              )}
              <p className="mt-3 text-sm">原始答案：{selected.question.source_answer || "未提供"}</p>
              {selected.question.source_explanation ? (
                <ExamRichText className="mt-2 rounded-lg bg-[var(--muted)] p-3 text-sm text-[var(--muted-foreground)]" text={selected.question.source_explanation} />
              ) : (
                <p className="mt-2 text-sm text-[var(--muted-foreground)]">暂无解析。</p>
              )}
              <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
                <p className="rounded bg-[var(--muted)] p-2">错误：{selected.wrong_state?.wrong_count ?? 0}</p>
                <p className="rounded bg-[var(--muted)] p-2">状态：{selected.wrong_state?.state ?? "—"}</p>
                <p className="rounded bg-[var(--muted)] p-2">系统掌握：{selected.mastery?.system_mastery_level ?? "unseen"}</p>
                <p className="rounded bg-[var(--muted)] p-2">手动：{selected.manual_override?.status ?? "无"}</p>
              </div>
              {!!selected.attempts?.length && (
                <div className="mt-4">
                  <h3 className="text-sm font-medium">作答记录</h3>
                  <ul className="mt-2 max-h-40 space-y-1 overflow-auto text-xs text-[var(--muted-foreground)]">
                    {selected.attempts.slice(0, 8).map((attempt) => (
                      <li key={attempt.id}>
                        {attempt.is_correct ? "对" : "错"} · {attempt.user_answer || "空"} · {attempt.confidence || "未标信心"}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                <Link
                  href={`/space/learning-center/practice?project_id=${encodeURIComponent(projectId)}&status=wrong&limit=10`}
                  className="inline-flex items-center gap-1 rounded-lg bg-sky-600 px-3 py-1.5 text-sm text-white"
                >
                  <Target size={14} /> 重练错题
                </Link>
              </div>
              <label className="mt-4 block text-sm">
                备注
                <input
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
                  placeholder="可选"
                />
              </label>
              <div className="mt-3 flex gap-2">
                <button type="button" onClick={() => void override(true)} className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm text-white">
                  <CheckCircle2 size={14} /> 手动已掌握
                </button>
                <button type="button" onClick={() => void override(false)} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm">
                  重新纳入复习
                </button>
              </div>
              <div className="mt-5">
                <LearningQuestionAIDiscussion
                  projectId={projectId}
                  questionId={selected.question.id}
                  stem={selected.question.stem}
                />
              </div>
            </>
          ) : (
            <p className="text-sm text-[var(--muted-foreground)]">选择左侧题目查看证据与操作。</p>
          )}
        </aside>
      </div>
    </div>
  );
}
