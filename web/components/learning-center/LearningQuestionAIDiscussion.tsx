"use client";
/* eslint-disable i18n/no-literal-ui-text -- Chinese-first Learning Center UI. */

import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, Loader2, MessageCircleMore, Send, Sparkles } from "lucide-react";

import ExamRichText from "@/components/learning-center/ExamRichText";
import {
  discussLearningQuestion,
  getPracticeDiscussion,
  type PracticeDiscussion,
} from "@/lib/learning-center-api";

type ChatMessage = { role: "user" | "assistant"; content: string };

type Props = {
  projectId: string;
  questionId: string;
  stem?: string;
  compact?: boolean;
  className?: string;
};

export default function LearningQuestionAIDiscussion({
  projectId,
  questionId,
  stem,
  compact = false,
  className = "",
}: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void getPracticeDiscussion(projectId, questionId)
      .then((discussion: PracticeDiscussion) => {
        if (cancelled) return;
        const history = (discussion.messages || [])
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));
        setMessages(history);
      })
      .catch(() => {
        if (!cancelled) setMessages([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, questionId]);

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, sending]);

  const title = useMemo(() => (compact ? "就这道题问 AI" : "错题 AI 对话"), [compact]);

  const send = async () => {
    const content = draft.trim();
    if (!content || sending) return;
    const historyForApi = messages.slice(-20);
    const optimistic = [...messages, { role: "user" as const, content }];
    setMessages(optimistic);
    setDraft("");
    setSending(true);
    setError(null);
    try {
      const result = await discussLearningQuestion(projectId, questionId, content, historyForApi);
      const fromServer = (result.discussion?.messages || [])
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));
      setMessages(fromServer.length ? fromServer : [...optimistic, { role: "assistant", content: result.reply }]);
    } catch (caught) {
      setMessages(messages);
      setDraft(content);
      setError(caught instanceof Error ? caught.message : "AI 暂时不可用，请稍后再试。");
      requestAnimationFrame(() => inputRef.current?.focus());
    } finally {
      setSending(false);
    }
  };

  return (
    <div className={`flex min-h-0 flex-col rounded-2xl border border-[var(--border)] bg-[var(--card)] ${className}`}>
      <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-3">
        <span className="rounded-lg bg-violet-500/10 p-1.5 text-violet-600 dark:text-violet-300">
          <MessageCircleMore size={15} />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold">{title}</p>
          <p className="truncate text-[11px] text-[var(--muted-foreground)]">
            {stem ? <ExamRichText as="span" text={stem} /> : "AI 已可读取题干、选项、答案与解析"}
          </p>
        </div>
        <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-violet-500/10 px-2 py-0.5 text-[10px] text-violet-700 dark:text-violet-300">
          <Sparkles size={11} /> AI
        </span>
      </div>

      <div ref={listRef} className={`min-h-0 flex-1 space-y-2 overflow-y-auto p-3 ${compact ? "max-h-56" : "max-h-80"}`}>
        {loading && (
          <p className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
            <Loader2 size={13} className="animate-spin" /> 加载对话…
          </p>
        )}
        {!loading && !messages.length && (
          <div className="rounded-xl bg-[var(--muted)]/60 p-3 text-xs leading-relaxed text-[var(--muted-foreground)]">
            <p className="mb-1 inline-flex items-center gap-1 font-medium text-[var(--foreground)]">
              <Bot size={13} /> 可以这样问
            </p>
            <p>为什么这题选这个？我的选项错在哪？帮我用更短的话记考点。</p>
          </div>
        )}
        {messages.map((message, index) => (
          <div
            key={`${message.role}-${index}-${message.content.slice(0, 12)}`}
            className={`rounded-xl px-3 py-2 text-[12px] leading-relaxed ${
              message.role === "user"
                ? "ml-6 bg-sky-50 text-sky-950 dark:bg-sky-950/30 dark:text-sky-100"
                : "mr-4 bg-[var(--muted)] text-[var(--foreground)]"
            }`}
          >
            <p className="mb-1 text-[10px] font-medium text-[var(--muted-foreground)]">
              {message.role === "user" ? "你" : "AI"}
            </p>
            <ExamRichText text={message.content} />
          </div>
        ))}
        {sending && (
          <p className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
            <Loader2 size={13} className="animate-spin" /> AI 正在分析这道题…
          </p>
        )}
      </div>

      <div className="border-t border-[var(--border)] p-3">
        {error && <p className="mb-2 text-[11px] leading-relaxed text-red-500">{error}</p>}
        <div className="flex items-end gap-2 rounded-xl border border-[var(--border)] bg-[var(--background)] px-2 py-1.5">
          <textarea
            ref={inputRef}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
            placeholder="针对这道题问 AI…（Enter 发送）"
            rows={2}
            className="max-h-28 min-h-[40px] flex-1 resize-none bg-transparent px-1 py-1 text-[13px] outline-none placeholder:text-[var(--muted-foreground)]"
          />
          <button
            type="button"
            disabled={sending || !draft.trim()}
            onClick={() => void send()}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-violet-600 text-white disabled:opacity-40"
            aria-label="发送"
          >
            {sending ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
          </button>
        </div>
      </div>
    </div>
  );
}
