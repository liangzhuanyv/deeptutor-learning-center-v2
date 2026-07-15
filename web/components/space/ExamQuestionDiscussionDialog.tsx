"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  CheckCircle2,
  Loader2,
  MessageCircleMore,
  Send,
  Sparkles,
  X,
} from "lucide-react";

import {
  discussExamQuestion,
  getExamQuestion,
  type ExamQuestionDetail,
} from "@/lib/exam-practice-api";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface ExamQuestionDiscussionDialogProps {
  questionId: string;
  onClose: () => void;
}

function sortedOptions(detail: ExamQuestionDetail): Array<[string, string]> {
  return Object.entries(detail.options ?? {}).sort(([left], [right]) =>
    left.localeCompare(right, "en"),
  );
}

export default function ExamQuestionDiscussionDialog({
  questionId,
  onClose,
}: ExamQuestionDiscussionDialogProps) {
  const [detail, setDetail] = useState<ExamQuestionDetail | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setMessages([]);
    void getExamQuestion(questionId)
      .then((question) => {
        if (!cancelled) setDetail(question);
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "加载题目详情失败");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [questionId]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const explanation = useMemo(() => {
    if (!detail) return "";
    return detail.source_explanation || detail.ai_explanation || "题库暂未提供解析。";
  }, [detail]);

  const send = async () => {
    const content = draft.trim();
    if (!content || sending) return;
    const nextHistory = [...messages, { role: "user" as const, content }];
    setMessages(nextHistory);
    setDraft("");
    setSending(true);
    setError(null);
    try {
      const result = await discussExamQuestion(questionId, content, messages);
      setMessages((previous) => [
        ...previous,
        { role: "assistant", content: result.reply },
      ]);
    } catch (caught) {
      setMessages(messages);
      setError(caught instanceof Error ? caught.message : "AI 暂时不可用，请稍后再试。");
      setDraft(content);
      requestAnimationFrame(() => inputRef.current?.focus());
    } finally {
      setSending(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-stretch justify-end bg-black/45 p-0 backdrop-blur-[1px] sm:p-5"
      role="dialog"
      aria-modal="true"
      aria-label="错题详情与 AI 讨论"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="flex h-full w-full max-w-6xl flex-col overflow-hidden rounded-none border border-[var(--border)] bg-[var(--background)] shadow-2xl sm:h-[min(860px,calc(100vh-40px))] sm:rounded-2xl">
        <header className="flex shrink-0 items-center justify-between border-b border-[var(--border)] px-5 py-3.5">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="rounded-lg bg-red-500/10 p-2 text-red-500">
              <MessageCircleMore size={17} />
            </span>
            <div className="min-w-0">
              <h2 className="text-[14px] font-semibold text-[var(--foreground)]">错题详情与 AI 讨论</h2>
              <p className="truncate text-[11px] text-[var(--muted-foreground)]">
                查看完整题目、答案与解析，然后针对本题继续追问。
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            aria-label="关闭"
          >
            <X size={18} />
          </button>
        </header>

        {loading ? (
          <div className="flex flex-1 items-center justify-center text-[var(--muted-foreground)]">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : !detail ? (
          <div className="flex flex-1 items-center justify-center p-8 text-center text-[13px] text-red-500">
            {error || "题目详情不可用。"}
          </div>
        ) : (
          <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,1.1fr)_minmax(380px,0.9fr)]">
            <article className="min-h-0 overflow-y-auto border-b border-[var(--border)] p-5 sm:p-6 lg:border-b-0 lg:border-r">
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
                <span>{detail.subject_name}</span>
                <span>›</span>
                <span>{detail.chapter_name || "未分类章节"}</span>
                <span className="rounded-full bg-[var(--muted)] px-2 py-0.5">{detail.question_type}</span>
                <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-red-600">错 {detail.wrong_book?.wrong_count ?? 0} 次</span>
              </div>
              <h3 className="mt-4 text-[16px] font-medium leading-relaxed text-[var(--foreground)]">{detail.stem}</h3>
              <div className="mt-5 space-y-2">
                {sortedOptions(detail).map(([key, option]) => {
                  const isAnswer = detail.source_answer.includes(key);
                  return (
                    <div
                      key={key}
                      className={`flex gap-3 rounded-xl border px-3.5 py-3 text-[13px] ${
                        isAnswer
                          ? "border-emerald-500/35 bg-emerald-500/5"
                          : "border-[var(--border)]/80"
                      }`}
                    >
                      <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${isAnswer ? "bg-emerald-500 text-white" : "bg-[var(--muted)] text-[var(--muted-foreground)]"}`}>
                        {isAnswer ? <CheckCircle2 size={13} /> : key}
                      </span>
                      <span className="leading-relaxed text-[var(--foreground)]">{option}</span>
                    </div>
                  );
                })}
              </div>
              <div className="mt-5 rounded-xl border border-emerald-500/25 bg-emerald-500/[0.045] p-4">
                <p className="text-[12px] font-medium text-emerald-700 dark:text-emerald-300">标准答案：{detail.source_answer || "待 AI 复核"}</p>
                <p className="mt-3 text-[12px] font-medium text-[var(--muted-foreground)]">解析</p>
                <p className="mt-1.5 whitespace-pre-wrap text-[13px] leading-relaxed text-[var(--foreground)]">{explanation}</p>
                {!detail.source_explanation && detail.ai_explanation && (
                  <span className="mt-3 inline-flex items-center gap-1 text-[11px] text-violet-600 dark:text-violet-300">
                    <Sparkles size={12} /> Gemini 补充解析
                  </span>
                )}
              </div>
            </article>

            <aside className="flex min-h-0 flex-col bg-[var(--card)]">
              <div className="flex items-center gap-2 border-b border-[var(--border)] px-5 py-3">
                <Bot size={16} className="text-[var(--primary)]" />
                <div>
                  <p className="text-[13px] font-medium text-[var(--foreground)]">就这道题问 AI</p>
                  <p className="text-[11px] text-[var(--muted-foreground)]">AI 已带入题干、选项、答案和解析。</p>
                </div>
              </div>
              <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
                {messages.length === 0 && (
                  <div className="rounded-xl border border-dashed border-[var(--border)] p-4 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                    例如：<br />
                    “为什么 B 不对？”<br />
                    “这题对应哪个知识点？”<br />
                    “给我一个容易记住的判断方法。”
                  </div>
                )}
                {messages.map((message, index) => (
                  <div key={`${message.role}-${index}`} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                    <div className={`max-w-[92%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-[13px] leading-relaxed ${message.role === "user" ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : "border border-[var(--border)] bg-[var(--background)] text-[var(--foreground)]"}`}>
                      {message.content}
                    </div>
                  </div>
                ))}
                {sending && <div className="flex items-center gap-2 text-[12px] text-[var(--muted-foreground)]"><Loader2 className="h-3.5 w-3.5 animate-spin" />AI 正在分析这道题…</div>}
              </div>
              <div className="shrink-0 border-t border-[var(--border)] p-3">
                {error && <p className="mb-2 text-[11px] leading-relaxed text-red-500">{error}</p>}
                <div className="flex items-end gap-2 rounded-xl border border-[var(--border)] bg-[var(--background)] p-2 focus-within:border-[var(--primary)]/60">
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
                    placeholder="针对这道题问 AI…（Enter 发送，Shift+Enter 换行）"
                    rows={2}
                    className="max-h-28 min-h-[42px] flex-1 resize-none bg-transparent px-1 py-1 text-[13px] text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
                  />
                  <button
                    disabled={!draft.trim() || sending}
                    onClick={() => void send()}
                    className="rounded-lg bg-[var(--primary)] p-2 text-[var(--primary-foreground)] disabled:opacity-35"
                    aria-label="发送"
                  >
                    <Send size={16} />
                  </button>
                </div>
              </div>
            </aside>
          </div>
        )}
      </section>
    </div>
  );
}
