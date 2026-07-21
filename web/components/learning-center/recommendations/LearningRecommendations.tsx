"use client";
/* eslint-disable i18n/no-literal-ui-text -- Chinese-first Learning Center v2 UI. */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Sparkles } from "lucide-react";

import LearningCenterNav from "@/components/learning-center/LearningCenterNav";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import {
  decideLearningRecommendation,
  generateLearningRecommendations,
  getLearningProjects,
  getLearningRecommendations,
  type LearningProjectOption,
  type LearningRecommendation,
} from "@/lib/learning-center-api";

function practiceHref(query: Record<string, string | number | null | undefined>): string {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value == null || value === "") return;
    params.set(key, String(value));
  });
  const q = params.toString();
  return `/space/learning-center/practice${q ? `?${q}` : ""}`;
}

export default function LearningRecommendations() {
  const router = useRouter();
  const [projects, setProjects] = useState<LearningProjectOption[]>([]);
  const [project, setProject] = useState("");
  const [items, setItems] = useState<LearningRecommendation[]>([]);
  const [budget, setBudget] = useState("今天只有10分钟");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (id: string) => {
    if (!id) return;
    setItems(await getLearningRecommendations(id));
  }, []);

  useEffect(() => {
    void getLearningProjects()
      .then((result) => {
        setProjects(result);
        const first = result[0]?.id ?? "";
        setProject(first);
        if (first) void load(first);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "无法加载项目"));
  }, [load]);

  const generate = async () => {
    if (!project) return;
    setBusy(true);
    setError("");
    try {
      setItems(
        await generateLearningRecommendations({
          project_id: project,
          trigger: "time_budget",
          time_budget_text: budget,
        }),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "生成建议失败");
    } finally {
      setBusy(false);
    }
  };

  const decide = async (id: string, action: "accepted" | "ignored" | "deferred" | "reduced") => {
    setBusy(true);
    setError("");
    try {
      const result = await decideLearningRecommendation(id, action);
      if (action === "accepted" || action === "reduced") {
        const next = result.next_action;
        if (next?.href) {
          router.push(practiceHref(next.query || { project_id: project }));
          return;
        }
        // Fallback: open practice for this project.
        router.push(`/space/learning-center/practice?project_id=${encodeURIComponent(project)}`);
        return;
      }
      await load(project);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-5xl p-4 sm:p-6 lg:p-8">
      <LearningCenterNav />
      <SpaceSectionHeader
        icon={Sparkles}
        title="规则建议"
        description="当前为确定性规则建议（非大模型）。接受后只会打开练习预填，不会自动改掌握度或计划。"
      />
      {error && (
        <p role="alert" className="mt-4 rounded-xl border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}
      <div className="mt-5 flex flex-wrap items-end gap-2">
        <label className="text-sm">
          项目
          <select
            value={project}
            onChange={(event) => {
              setProject(event.target.value);
              void load(event.target.value);
            }}
            className="mt-1 block rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
          >
            {projects.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="min-w-[16rem] flex-1 text-sm">
          时间预算（可选）
          <input
            value={budget}
            onChange={(event) => setBudget(event.target.value)}
            className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
          />
        </label>
        <button
          type="button"
          disabled={busy || !project}
          onClick={() => void generate()}
          className="inline-flex items-center gap-1 rounded-lg bg-[var(--foreground)] px-3.5 py-2 text-sm font-medium text-[var(--background)] disabled:opacity-40"
        >
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
          生成规则建议
        </button>
      </div>

      <div className="mt-5 space-y-3">
        {!items.length && (
          <p className="rounded-2xl border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--muted-foreground)]">
            暂无建议。可先完成一组练习，或点击上方生成。
          </p>
        )}
        {items.map((item) => (
          <article key={item.id} className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="text-[11px] text-[var(--muted-foreground)]">
                  {item.provider}/{item.model} · 置信 {item.confidence == null ? "—" : Math.round(item.confidence * 100)}%
                  {item.estimated_minutes ? ` · 约 ${item.estimated_minutes} 分钟` : ""}
                </p>
                <h2 className="mt-1 text-[15px] font-semibold">{item.title}</h2>
                <p className="mt-1 text-sm leading-relaxed text-[var(--muted-foreground)]">{item.explanation}</p>
              </div>
              <span className="rounded-full bg-slate-500/10 px-2 py-1 text-[11px] text-[var(--muted-foreground)]">规则建议</span>
            </div>
            {!!item.evidence?.length && (
              <p className="mt-3 text-[12px] text-[var(--muted-foreground)]">证据 {item.evidence.length} 条（错题/风险信号）</p>
            )}
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => void decide(item.id, "accepted")}
                className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm text-white disabled:opacity-40"
              >
                接受并去练习
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void decide(item.id, "reduced")}
                className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm"
              >
                减半题量
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void decide(item.id, "deferred")}
                className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm"
              >
                稍后
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void decide(item.id, "ignored")}
                className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--muted-foreground)]"
              >
                忽略
              </button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
