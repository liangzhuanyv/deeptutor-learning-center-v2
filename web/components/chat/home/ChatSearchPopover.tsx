"use client";

import { useEffect, useMemo, useRef } from "react";
import { Search, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  buildSnippet,
  findMessageMatches,
  splitHighlight,
  type NavMessage,
} from "@/lib/chat-message-nav";

export interface ChatSearchPopoverProps {
  open: boolean;
  onClose: () => void;
  query: string;
  onQueryChange: (q: string) => void;
  messages: NavMessage[];
  onSelectMatch: (messageId: number) => void;
  activeMatchId?: number | null;
  /** Anchor: render as absolute panel under header actions; parent is relative */
  className?: string;
}

export default function ChatSearchPopover({
  open,
  onClose,
  query,
  onQueryChange,
  messages,
  onSelectMatch,
  activeMatchId,
  className = "",
}: ChatSearchPopoverProps) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);

  const matches = useMemo(
    () => findMessageMatches(messages, query),
    [messages, query],
  );

  useEffect(() => {
    if (!open) return;
    const id = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-label={t("Search in conversation")}
      className={`absolute right-0 top-full z-40 mt-1.5 flex w-[min(400px,calc(100vw-2rem))] flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-lg ${className}`}
    >
      <div className="flex items-center gap-2 border-b border-[var(--border)] px-3 py-2">
        <Search size={14} className="shrink-0 text-[var(--muted-foreground)]" />
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder={t("Search messages in this chat…")}
          className="min-w-0 flex-1 bg-transparent text-[13px] text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]/70"
        />
        {query ? (
          <button
            type="button"
            aria-label={t("Clear search")}
            onClick={() => onQueryChange("")}
            className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]/50"
          >
            <X size={14} />
          </button>
        ) : null}
      </div>

      <div className="max-h-[min(360px,50vh)] overflow-y-auto py-1">
        {!query.trim() ? (
          <p className="px-3 py-6 text-center text-[12px] text-[var(--muted-foreground)]">
            {t("Type to search this conversation")}
          </p>
        ) : matches.length === 0 ? (
          <p className="px-3 py-6 text-center text-[12px] text-[var(--muted-foreground)]">
            {t("No matches in this conversation")}
          </p>
        ) : (
          matches.map((m) => {
            const snip = buildSnippet(m.plain, query);
            const active = activeMatchId === m.id;
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => onSelectMatch(m.id)}
                className={`flex w-full flex-col gap-0.5 px-3 py-2 text-left transition-colors hover:bg-[var(--muted)]/40 ${
                  active ? "bg-[var(--primary)]/10" : ""
                }`}
              >
                <span className="text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                  {m.role === "user" ? t("Question") : t("Answer")}
                </span>
                <span className="line-clamp-2 text-[12.5px] leading-snug text-[var(--foreground)]">
                  {splitHighlight(snip, query).map((part, i) =>
                    part.hit ? (
                      <mark
                        key={i}
                        className="rounded-sm bg-[var(--primary)]/25 text-inherit"
                      >
                        {part.text}
                      </mark>
                    ) : (
                      <span key={i}>{part.text}</span>
                    ),
                  )}
                </span>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
