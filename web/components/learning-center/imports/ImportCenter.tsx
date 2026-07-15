"use client";
/* eslint-disable i18n/no-literal-ui-text -- Chinese-first audited import workflow; locale extraction is handled with the canonical Learning Center shell. */

import { useMemo, useState } from "react";
import {
  BadgeCheck,
  Check,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  FileJson2,
  Filter,
  Loader2,
  Play,
  RotateCcw,
  ScanLine,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  Upload,
  XCircle,
} from "lucide-react";

import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import LearningCenterNav from "@/components/learning-center/LearningCenterNav";
import {
  analyzeImport,
  approveImport,
  cancelImport,
  commitImport,
  enrichImport,
  rollbackImport,
  updateImportMapping,
  type ImportApprovalMode,
  type ImportBatch,
  type ImportBatchItem,
  type LearningImportRequest,
} from "@/lib/learning-center-api";

const EXAMPLE = {
  schema_version: "learning-import/v1",
  project: { external_id: "biology-101", name: "Biology 101", kind: "course" },
  bank: { external_id: "bio-v1", name: "Cells", version: "v1", source: { type: "manual" } },
  items: [
    {
      external_id: "cell-1",
      module_path: ["Cells"],
      knowledge_points: ["Nucleus"],
      question_type: "single_choice",
      stem: "Which organelle contains DNA?",
      options: { A: "Nucleus", B: "Ribosome" },
      source_answer: "A",
      source_explanation: "The nucleus contains most cellular DNA.",
    },
  ],
};

type FilterMode = "all" | "valid" | "review" | "duplicate";

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function summaryNumber(batch: ImportBatch, key: string): number {
  const value = batch.summary[key];
  return typeof value === "number" ? value : 0;
}

function latestSuggestion(item: ImportBatchItem) {
  const suggestions = item.quality.ai_suggestions ?? [];
  return suggestions.at(-1);
}

function StatusPill({ status }: { status: string }) {
  const className =
    status === "completed" || status === "valid" || status === "approved"
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
      : status === "manual_review" || status === "preview_ready" || status === "committing"
        ? "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300"
        : status === "duplicate" || status === "cancelled"
          ? "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300"
          : "border-[var(--border)] bg-[var(--muted)]/50 text-[var(--muted-foreground)]";
  return <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${className}`}>{status}</span>;
}

function MetricCard({ label, value, tone = "default" }: { label: string; value: number; tone?: "default" | "warn" | "danger" }) {
  const color = tone === "danger" ? "text-red-600 dark:text-red-400" : tone === "warn" ? "text-amber-600 dark:text-amber-400" : "text-[var(--foreground)]";
  return (
    <div className="rounded-xl border border-[var(--border)]/70 bg-[var(--card)] px-3.5 py-3">
      <p className="text-[11px] text-[var(--muted-foreground)]">{label}</p>
      <p className={`mt-1 text-xl font-semibold tabular-nums ${color}`}>{value.toLocaleString()}</p>
    </div>
  );
}

export default function ImportCenter() {
  const [sourceText, setSourceText] = useState(() => formatJson(EXAMPLE));
  const [batch, setBatch] = useState<ImportBatch | null>(null);
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<FilterMode>("all");
  const [mappingText, setMappingText] = useState('{\n  "module": "module_path",\n  "knowledge_point": "knowledge_points"\n}');
  const [approvalMode, setApprovalMode] = useState<ImportApprovalMode>("all_valid");
  const [minimumConfidence, setMinimumConfidence] = useState("0.8");
  const [profileId, setProfileId] = useState("");
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [confirmCommit, setConfirmCommit] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const activeItem = useMemo(
    () => batch?.items.find((item) => item.id === activeItemId) ?? batch?.items[0] ?? null,
    [activeItemId, batch],
  );
  const visibleItems = useMemo(() => {
    if (!batch) return [];
    return batch.items.filter((item) => {
      if (filter === "valid") return item.status === "valid";
      if (filter === "review") return item.status === "manual_review";
      if (filter === "duplicate") return item.status === "duplicate";
      return true;
    });
  }, [batch, filter]);

  async function run(label: string, action: () => Promise<ImportBatch>) {
    setPending(label);
    setError(null);
    try {
      const next = await action();
      setBatch(next);
      setActiveItemId((current) => current ?? next.items[0]?.id ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败");
    } finally {
      setPending(null);
    }
  }

  async function handleAnalyze() {
    let parsed: LearningImportRequest;
    try {
      parsed = JSON.parse(sourceText) as LearningImportRequest;
    } catch {
      setError("导入内容不是有效 JSON。请使用 learning-import/v1 规范。");
      return;
    }
    await run("analyze", () => analyzeImport(parsed));
  }

  async function handleFile(file: File | undefined) {
    if (!file) return;
    try {
      setSourceText(await file.text());
      setError(null);
    } catch {
      setError("无法读取该文件。请选择 UTF-8 编码的 canonical JSON 文件。");
    }
  }

  async function handleMapping() {
    if (!batch) return;
    try {
      const mapping = JSON.parse(mappingText) as Record<string, unknown>;
      await run("mapping", () => updateImportMapping(batch.id, mapping));
    } catch {
      setError("字段映射必须是有效 JSON 对象。");
    }
  }

  async function handleApprove() {
    if (!batch) return;
    const selected = [...selectedIds];
    await run("approve", () =>
      approveImport(batch.id, {
        mode: approvalMode,
        selected_item_ids: approvalMode === "selected" ? selected : undefined,
        minimum_confidence: Number(minimumConfidence) || 0.8,
      }),
    );
  }

  const busy = pending !== null;
  const canReview = batch?.status === "preview_ready";
  const canCommit = batch?.status === "approved";
  const canRollback = batch?.status === "completed";

  return (
    <div className="pb-12">
      <SpaceSectionHeader
        icon={FileJson2}
        title="题库导入中心"
        description="先分析，再审计、批准并提交。源内容与 AI 建议始终分离保留。"
        meta={batch ? <StatusPill status={batch.status} /> : undefined}
        action={
          <button
            type="button"
            onClick={() => setSourceText(formatJson(EXAMPLE))}
            className="rounded-lg border border-[var(--border)] px-3 py-2 text-[12px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          >
            载入示例
          </button>
        }
      />
      <LearningCenterNav />

      {error && (
        <div className="mb-5 flex items-start gap-2 rounded-xl border border-red-500/30 bg-red-500/5 px-3.5 py-3 text-[13px] text-red-700 dark:text-red-300">
          <ShieldAlert size={17} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
        <div className="flex flex-col gap-3 border-b border-[var(--border)]/60 pb-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-[14px] font-semibold text-[var(--foreground)]">1. 选择 canonical JSON 来源</h2>
            <p className="mt-0.5 text-[12px] text-[var(--muted-foreground)]">支持粘贴或上传。文件仅在浏览器读取，服务端不会根据 metadata 读取路径或 URL。</p>
          </div>
          <label className="inline-flex cursor-pointer items-center justify-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-2 text-[12px] font-medium hover:bg-[var(--muted)]">
            <Upload size={14} /> 上传 JSON
            <input className="hidden" type="file" accept="application/json,.json" onChange={(event) => void handleFile(event.target.files?.[0])} />
          </label>
        </div>
        <textarea
          value={sourceText}
          onChange={(event) => setSourceText(event.target.value)}
          spellCheck={false}
          className="mt-3 min-h-64 w-full rounded-xl border border-[var(--border)] bg-[var(--background)] p-3 font-mono text-[11px] leading-relaxed text-[var(--foreground)] outline-none ring-0 focus:border-sky-500/60"
          aria-label="learning-import/v1 JSON"
        />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <span className="text-[11px] text-[var(--muted-foreground)]">协议：learning-import/v1 · 最大 10,000 题</span>
          <button type="button" disabled={busy} onClick={() => void handleAnalyze()} className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3.5 py-2 text-[12px] font-medium text-[var(--background)] disabled:opacity-50">
            {pending === "analyze" ? <Loader2 size={14} className="animate-spin" /> : <ScanLine size={14} />}
            分析并生成预览
          </button>
        </div>
      </section>

      {batch && (
        <div className="mt-5 space-y-5">
          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="发现题目" value={summaryNumber(batch, "discovered")} />
            <MetricCard label="可直接提交" value={summaryNumber(batch, "valid")} />
            <MetricCard label="待人工复核" value={summaryNumber(batch, "manual_review_items")} tone="warn" />
            <MetricCard label="重复项" value={summaryNumber(batch, "duplicates")} tone="danger" />
            <MetricCard label="缺少答案" value={summaryNumber(batch, "missing_answers")} tone="danger" />
            <MetricCard label="已提交" value={summaryNumber(batch, "committed")} />
          </section>

          <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4">
              <div className="flex flex-col gap-3 border-b border-[var(--border)]/60 pb-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="text-[14px] font-semibold">2. 质量审计与逐题选择</h2>
                  <p className="mt-0.5 text-[12px] text-[var(--muted-foreground)]">选择仅影响“选中项批准”；重复项和待复核项不会被静默提交。</p>
                </div>
                <div className="flex flex-wrap gap-1 rounded-lg bg-[var(--muted)]/50 p-1">
                  {(["all", "valid", "review", "duplicate"] as FilterMode[]).map((mode) => (
                    <button key={mode} type="button" onClick={() => setFilter(mode)} className={`rounded-md px-2.5 py-1 text-[11px] ${filter === mode ? "bg-[var(--card)] font-medium shadow-sm" : "text-[var(--muted-foreground)]"}`}>
                      {mode === "all" ? "全部" : mode === "valid" ? "可提交" : mode === "review" ? "待复核" : "重复"}
                    </button>
                  ))}
                </div>
              </div>
              <div className="mt-3 max-h-[430px] overflow-auto rounded-xl border border-[var(--border)]/70">
                {visibleItems.map((item) => {
                  const suggestion = latestSuggestion(item);
                  const isSelectable = item.status === "valid";
                  const selected = selectedIds.has(item.id);
                  return (
                    <button key={item.id} type="button" onClick={() => setActiveItemId(item.id)} className={`grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 border-b border-[var(--border)]/60 px-3 py-3 text-left last:border-b-0 hover:bg-[var(--muted)]/40 ${activeItem?.id === item.id ? "bg-sky-500/5" : ""}`}>
                      <span onClick={(event) => event.stopPropagation()}>
                        <input
                          type="checkbox"
                          disabled={!isSelectable || batch.status !== "preview_ready"}
                          checked={selected}
                          onChange={() => setSelectedIds((previous) => {
                            const next = new Set(previous);
                            if (next.has(item.id)) next.delete(item.id); else next.add(item.id);
                            return next;
                          })}
                          aria-label={`选择 ${item.external_id}`}
                        />
                      </span>
                      <span className="min-w-0">
                        <span className="flex items-center gap-2"><StatusPill status={item.status} /><span className="truncate text-[12px] font-medium">{item.external_id}</span></span>
                        <span className="mt-1 block truncate text-[12px] text-[var(--muted-foreground)]">{item.normalized.stem}</span>
                        {item.quality.issues.length > 0 && <span className="mt-1 block text-[11px] text-amber-700 dark:text-amber-300">{item.quality.issues.map((issue) => issue.type).join(" · ")}</span>}
                      </span>
                      <span className="text-right">
                        {suggestion?.answer_confidence != null && <span className="inline-flex items-center gap-1 text-[11px] text-violet-700 dark:text-violet-300"><Sparkles size={12} /> {(suggestion.answer_confidence * 100).toFixed(0)}%</span>}
                        <ChevronRight size={15} className="ml-auto mt-1 text-[var(--muted-foreground)]" />
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            <aside className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4">
              <div className="flex items-center gap-2"><SlidersHorizontal size={15} /><h2 className="text-[14px] font-semibold">字段映射</h2></div>
              <p className="mt-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">映射会写入批次审计记录，批准后保持不可变。</p>
              <textarea value={mappingText} onChange={(event) => setMappingText(event.target.value)} spellCheck={false} className="mt-3 min-h-36 w-full rounded-xl border border-[var(--border)] bg-[var(--background)] p-3 font-mono text-[11px] outline-none focus:border-sky-500/60" />
              <button type="button" disabled={!canReview || busy} onClick={() => void handleMapping()} className="mt-2 inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-2 text-[12px] font-medium disabled:opacity-50 hover:bg-[var(--muted)]">
                {pending === "mapping" ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} 保存映射
              </button>
              <div className="mt-5 border-t border-[var(--border)]/60 pt-4">
                <div className="flex items-center gap-2"><Sparkles size={15} /><h2 className="text-[14px] font-semibold">AI 结构化补全</h2></div>
                <p className="mt-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">仅生成独立建议与置信度，不会覆盖源字段。</p>
                <div className="mt-3 grid gap-2">
                  <input value={profileId} onChange={(event) => setProfileId(event.target.value)} placeholder="配置 profile ID（可选）" className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-2 text-[12px]" />
                  <div className="grid grid-cols-2 gap-2"><input value={provider} onChange={(event) => setProvider(event.target.value)} placeholder="provider" className="min-w-0 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-2 text-[12px]" /><input value={model} onChange={(event) => setModel(event.target.value)} placeholder="model" className="min-w-0 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-2 text-[12px]" /></div>
                </div>
                <button type="button" disabled={!canReview || busy} onClick={() => batch && void run("enrich", () => enrichImport(batch.id, { profile_id: profileId || undefined, provider: provider || undefined, model: model || undefined, rate_limit_per_minute: 60 }))} className="mt-2 inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-violet-500/30 bg-violet-500/5 px-3 py-2 text-[12px] font-medium text-violet-700 disabled:opacity-50 dark:text-violet-300">
                  {pending === "enrich" ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />} 生成可审计建议
                </button>
              </div>
            </aside>
          </section>

          {activeItem && (
            <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4">
              <div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="text-[14px] font-semibold">3. 源内容与规范化预览</h2><p className="mt-0.5 text-[12px] text-[var(--muted-foreground)]">原始输入在左；规范化值和 AI 派生建议在右。</p></div><StatusPill status={activeItem.status} /></div>
              <div className="mt-3 grid gap-3 lg:grid-cols-2">
                <div><p className="mb-1.5 text-[11px] font-medium text-[var(--muted-foreground)]">SOURCE · 不可变</p><pre className="max-h-96 overflow-auto rounded-xl border border-[var(--border)] bg-[var(--background)] p-3 text-[11px] leading-relaxed">{formatJson(activeItem.raw)}</pre></div>
                <div><p className="mb-1.5 text-[11px] font-medium text-[var(--muted-foreground)]">NORMALIZED / AI · 可审计派生</p><pre className="max-h-96 overflow-auto rounded-xl border border-[var(--border)] bg-[var(--background)] p-3 text-[11px] leading-relaxed">{formatJson({ normalized: activeItem.normalized, ai_suggestions: activeItem.quality.ai_suggestions ?? [], issues: activeItem.quality.issues })}</pre></div>
              </div>
            </section>
          )}

          <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4">
            <div className="flex flex-col gap-3 border-b border-[var(--border)]/60 pb-3 lg:flex-row lg:items-center lg:justify-between">
              <div><h2 className="text-[14px] font-semibold">4. 批准、提交与回滚</h2><p className="mt-0.5 text-[12px] text-[var(--muted-foreground)]">提交前确认；完成后可以只删除该批次创建的内容。</p></div>
              <div className="flex items-center gap-2 text-[11px] text-[var(--muted-foreground)]"><ClipboardCheck size={14} /> 已选 {selectedIds.size} / 可提交 {summaryNumber(batch, "valid")}</div>
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
              <div className="grid gap-2 sm:grid-cols-3">
                {(["all_valid", "high_confidence", "selected"] as ImportApprovalMode[]).map((mode) => <label key={mode} className={`cursor-pointer rounded-xl border p-3 ${approvalMode === mode ? "border-sky-500/50 bg-sky-500/5" : "border-[var(--border)]"}`}><input type="radio" name="approval-mode" className="sr-only" checked={approvalMode === mode} onChange={() => setApprovalMode(mode)} /><span className="block text-[12px] font-medium">{mode === "all_valid" ? "批准全部可提交项" : mode === "high_confidence" ? "仅高置信度" : "仅已选择项"}</span><span className="mt-1 block text-[11px] text-[var(--muted-foreground)]">{mode === "all_valid" ? "所有校验通过的源题" : mode === "high_confidence" ? "AI 建议 ≥ 阈值；无 AI 时保留源可信度" : "仅勾选的校验通过题目"}</span></label>)}
              </div>
              <div className="flex flex-col gap-2">
                <label className="text-[11px] text-[var(--muted-foreground)]">高置信阈值<input type="number" min="0" max="1" step="0.05" value={minimumConfidence} onChange={(event) => setMinimumConfidence(event.target.value)} className="mt-1 block w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-2 text-[12px]" /></label>
                <button type="button" disabled={!canReview || busy || (approvalMode === "selected" && selectedIds.size === 0)} onClick={() => void handleApprove()} className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-sky-600 px-3.5 py-2 text-[12px] font-medium text-white disabled:opacity-50"><BadgeCheck size={14} /> {pending === "approve" ? "批准中…" : "批准批次"}</button>
                <button type="button" disabled={!canReview || busy} onClick={() => batch && void run("cancel", () => cancelImport(batch.id))} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-red-500/30 px-3.5 py-2 text-[12px] text-red-700 disabled:opacity-50 dark:text-red-300"><XCircle size={14} /> 取消导入</button>
              </div>
            </div>
            {canCommit && !confirmCommit && <button type="button" disabled={busy} onClick={() => setConfirmCommit(true)} className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3.5 py-2 text-[12px] font-medium text-[var(--background)]"><Play size={14} /> 提交已批准内容</button>}
            {confirmCommit && <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 p-3"><ShieldAlert size={17} className="text-amber-600" /><p className="mr-auto text-[12px] text-[var(--foreground)]">将写入 {summaryNumber(batch, "approved")} 道批准题目；源内容会保留为不可变快照。</p><button type="button" onClick={() => setConfirmCommit(false)} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px]">返回</button><button type="button" disabled={busy} onClick={() => { setConfirmCommit(false); batch && void run("commit", () => commitImport(batch.id)); }} className="rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-[12px] font-medium text-[var(--background)]">确认提交</button></div>}
            {canRollback && <button type="button" disabled={busy} onClick={() => batch && void run("rollback", () => rollbackImport(batch.id))} className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-red-500/30 px-3.5 py-2 text-[12px] font-medium text-red-700 disabled:opacity-50 dark:text-red-300"><RotateCcw size={14} /> 回滚本批次并查看报告</button>}
          </section>

          <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4">
            <div className="flex items-center gap-2"><Filter size={15} /><h2 className="text-[14px] font-semibold">批次审计轨迹</h2></div>
            <ol className="mt-3 space-y-2 border-l border-[var(--border)] pl-4">
              {batch.events.map((event, index) => <li key={`${event.stage}-${event.created_at}-${index}`} className="relative text-[12px]"><span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-sky-500" /><div className="flex flex-wrap items-center gap-x-2"><span className="font-medium">{event.stage}</span><span className="text-[var(--muted-foreground)]">{event.message}</span><time className="ml-auto text-[11px] text-[var(--muted-foreground)]">{new Date(event.created_at * 1000).toLocaleString()}</time></div></li>)}
            </ol>
          </section>
        </div>
      )}
    </div>
  );
}
