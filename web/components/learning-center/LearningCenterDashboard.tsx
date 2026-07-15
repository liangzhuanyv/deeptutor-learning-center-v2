"use client";
/* eslint-disable i18n/no-literal-ui-text -- Learning Center dashboard is Chinese-first until locale extraction. */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { BarChart3, BookOpenCheck, CircleAlert, FileJson2, Loader2, RefreshCw, Target, TrendingUp } from "lucide-react";

import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import LearningCenterNav from "@/components/learning-center/LearningCenterNav";
import {
  getLearningDashboardHeatmap,
  getLearningDashboardMastery,
  getLearningDashboardModules,
  getLearningDashboardOverview,
  getLearningDashboardProjects,
  getLearningDashboardTrends,
  type LearningDashboardOverview,
  type LearningDashboardProject,
  type LearningErrorHeatmapCell,
  type LearningMasteryBucket,
  type LearningModuleComparison,
  type LearningTrendPoint,
} from "@/lib/learning-center-api";

type DashboardData = {
  overview: LearningDashboardOverview;
  projects: LearningDashboardProject[];
  trends: LearningTrendPoint[];
  mastery: LearningMasteryBucket[];
  modules: LearningModuleComparison[];
  heatmap: LearningErrorHeatmapCell[];
};

const MASTERY_COLORS: Record<string, string> = {
  unseen: "bg-slate-400", learning: "bg-amber-500", familiar: "bg-sky-500", stable: "bg-emerald-500", retained: "bg-violet-500",
};

function formatPercent(value: number | null): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function formatTime(value: number | null): string {
  return value ? new Date(value * 1000).toLocaleString() : "暂无记录";
}

function Metric({ label, value, hint }: { label: string; value: string | number; hint: string }) {
  return <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4"><p className="text-[11px] text-[var(--muted-foreground)]">{label}</p><p className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{value}</p><p className="mt-1 text-[11px] text-[var(--muted-foreground)]">{hint}</p></div>;
}

export default function LearningCenterDashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [overview, projects, trends, mastery, modules, heatmap] = await Promise.all([
        getLearningDashboardOverview(), getLearningDashboardProjects(), getLearningDashboardTrends(30),
        getLearningDashboardMastery(), getLearningDashboardModules(), getLearningDashboardHeatmap(30),
      ]);
      setData({ overview, projects, trends, mastery, modules, heatmap });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法加载学习数据");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const trendMax = useMemo(() => Math.max(1, ...(data?.trends.map((point) => point.attempt_count) ?? [1])), [data]);
  const heatByModule = useMemo(() => {
    const grouped = new Map<string, { name: string; wrong: number; attempts: number }>();
    for (const cell of data?.heatmap ?? []) {
      const current = grouped.get(cell.module_id) ?? { name: cell.module_name, wrong: 0, attempts: 0 };
      current.wrong += cell.wrong_attempt_count; current.attempts += cell.attempt_count; grouped.set(cell.module_id, current);
    }
    return [...grouped.entries()].map(([id, value]) => ({ id, ...value })).sort((a, b) => b.wrong - a.wrong).slice(0, 8);
  }, [data]);

  return (
    <div className="pb-12">
      <SpaceSectionHeader icon={BarChart3} title="学习训练中心" description="按项目审视练习证据、掌握度与待复习风险；旧刷题路径保持可用。" action={<button type="button" onClick={() => void load()} disabled={loading} className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-2 text-[12px] font-medium hover:bg-[var(--muted)] disabled:opacity-50">{loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} 刷新数据</button>} />
      <LearningCenterNav />
      {error && <div className="mb-5 flex items-center gap-2 rounded-xl border border-red-500/30 bg-red-500/5 px-3.5 py-3 text-[13px] text-red-700 dark:text-red-300"><CircleAlert size={16} />{error}</div>}
      {loading && !data ? <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 8 }, (_, index) => <div key={index} className="h-28 animate-pulse rounded-2xl bg-[var(--muted)]/70" />)}</div> : data && <>
        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Metric label="学习项目" value={data.overview.project_count} hint="已导入的独立学习域" />
          <Metric label="可练题目" value={data.overview.question_count.toLocaleString()} hint="源内容与派生内容可追溯" />
          <Metric label="练习正确率" value={formatPercent(data.overview.accuracy)} hint={`${data.overview.attempt_count.toLocaleString()} 次已判定作答`} />
          <Metric label="待复习风险" value={data.overview.review_due_count} hint={`${data.overview.active_session_count} 个进行中会话`} />
        </section>

        <section className="mt-5 grid gap-3 lg:grid-cols-3">
          <Link href="/space/learning-center/imports" className="group rounded-2xl border border-sky-500/25 bg-sky-500/5 p-4 hover:border-sky-500/50"><FileJson2 size={18} className="text-sky-600 dark:text-sky-300" /><h2 className="mt-3 text-[14px] font-semibold">导入新的学习项目</h2><p className="mt-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">从 canonical JSON 开始，逐项审计再提交。</p></Link>
          <Link href="/space/exam-practice" className="group rounded-2xl border border-violet-500/25 bg-violet-500/5 p-4 hover:border-violet-500/50"><BookOpenCheck size={18} className="text-violet-600 dark:text-violet-300" /><h2 className="mt-3 text-[14px] font-semibold">继续兼容刷题</h2><p className="mt-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">保留基金与证券题库的现有工作流。</p></Link>
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4"><Target size={18} className="text-emerald-600 dark:text-emerald-300" /><h2 className="mt-3 text-[14px] font-semibold">最近活动</h2>{data.overview.last_session ? <p className="mt-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">{data.overview.last_session.project_name} · {data.overview.last_session.answered}/{data.overview.last_session.total} 题 · {formatPercent(data.overview.last_session.accuracy)}</p> : <p className="mt-1 text-[12px] text-[var(--muted-foreground)]">开始一次练习后，这里会保留最近证据。</p>}</div>
        </section>

        {data.projects.length === 0 ? <section className="mt-5 rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)] p-8 text-center"><FileJson2 size={28} className="mx-auto text-[var(--muted-foreground)]" /><h2 className="mt-3 text-[15px] font-semibold">还没有学习项目</h2><p className="mx-auto mt-1 max-w-md text-[12px] text-[var(--muted-foreground)]">导入第一份题库后，总览会显示练习趋势、掌握度和错误热度。</p><Link href="/space/learning-center/imports" className="mt-4 inline-flex rounded-lg bg-[var(--foreground)] px-3.5 py-2 text-[12px] font-medium text-[var(--background)]">去导入中心</Link></section> : <>
          <section className="mt-5"><div className="mb-3 flex items-center justify-between"><h2 className="text-[15px] font-semibold">学习项目</h2><span className="text-[12px] text-[var(--muted-foreground)]">最近会话与风险优先</span></div><div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{data.projects.map((project) => <article key={project.id} className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4"><div className="flex items-start justify-between gap-2"><div><h3 className="text-[14px] font-semibold">{project.name}</h3><p className="mt-1 text-[11px] text-[var(--muted-foreground)]">{project.kind} · {project.question_count.toLocaleString()} 题</p></div><span className="rounded-full bg-amber-500/10 px-2 py-1 text-[11px] text-amber-700 dark:text-amber-300">{project.review_due_count} 待复习</span></div><div className="mt-4 grid grid-cols-2 gap-2 text-[12px]"><div className="rounded-lg bg-[var(--muted)]/50 p-2"><span className="block text-[11px] text-[var(--muted-foreground)]">正确率</span><strong>{formatPercent(project.accuracy)}</strong></div><div className="rounded-lg bg-[var(--muted)]/50 p-2"><span className="block text-[11px] text-[var(--muted-foreground)]">最近练习</span><strong className="text-[11px]">{formatTime(project.last_session_at)}</strong></div></div></article>)}</div></section>

          <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(300px,0.85fr)]">
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4"><div className="flex items-center gap-2"><TrendingUp size={16} /><h2 className="text-[14px] font-semibold">30 天练习量与正确率</h2></div><div className="mt-5 flex h-44 items-end gap-1.5">{data.trends.map((point) => <div key={point.date} className="group flex min-w-0 flex-1 flex-col items-center justify-end"><span className="mb-1 hidden rounded bg-[var(--foreground)] px-1.5 py-0.5 text-[10px] text-[var(--background)] group-hover:block">{point.attempt_count} · {formatPercent(point.accuracy)}</span><div className="w-full max-w-4 rounded-t bg-sky-500/80" style={{ height: `${Math.max(point.attempt_count ? 8 : 2, (point.attempt_count / trendMax) * 100)}%` }} /><span className="mt-2 hidden text-[9px] text-[var(--muted-foreground)] sm:block">{point.date.slice(5)}</span></div>)}</div></div>
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4"><h2 className="text-[14px] font-semibold">掌握度分布</h2><div className="mt-4 space-y-3">{data.mastery.map((bucket) => <div key={bucket.level}><div className="mb-1 flex justify-between text-[12px]"><span>{bucket.level}</span><span className="text-[var(--muted-foreground)]">{bucket.question_count.toLocaleString()}</span></div><div className="h-2 overflow-hidden rounded-full bg-[var(--muted)]"><div className={`h-full ${MASTERY_COLORS[bucket.level]}`} style={{ width: `${data.overview.question_count ? (bucket.question_count / data.overview.question_count) * 100 : 0}%` }} /></div></div>)}</div></div>
          </section>

          <section className="mt-5 grid gap-5 xl:grid-cols-2"><div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4"><h2 className="text-[14px] font-semibold">错误热度</h2><p className="mt-1 text-[12px] text-[var(--muted-foreground)]">近 30 天按模块汇总的错误作答。</p><div className="mt-4 space-y-3">{heatByModule.length ? heatByModule.map((cell) => <div key={cell.id}><div className="mb-1 flex justify-between gap-3 text-[12px]"><span className="truncate">{cell.name}</span><span className="shrink-0 text-red-600 dark:text-red-300">{cell.wrong}/{cell.attempts}</span></div><div className="h-2 rounded-full bg-[var(--muted)]"><div className="h-full rounded-full bg-red-500" style={{ width: `${cell.attempts ? (cell.wrong / cell.attempts) * 100 : 0}%` }} /></div></div>) : <p className="py-8 text-center text-[12px] text-[var(--muted-foreground)]">暂无已判定错误，完成练习后生成热度。</p>}</div></div>
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4"><h2 className="text-[14px] font-semibold">模块比较</h2><div className="mt-3 max-h-72 overflow-auto rounded-xl border border-[var(--border)]/70">{data.modules.map((module) => <div key={module.id} className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-3 border-b border-[var(--border)]/60 px-3 py-2.5 text-[12px] last:border-0"><div className="min-w-0"><p className="truncate font-medium">{module.path}</p><p className="truncate text-[11px] text-[var(--muted-foreground)]">{module.project_name} · {module.question_count} 题</p></div><span className="text-red-600 dark:text-red-300">错 {module.wrong_attempt_count}</span><span>{formatPercent(module.accuracy)}</span></div>)}</div></div></section>
        </>}
      </>}
    </div>
  );
}
