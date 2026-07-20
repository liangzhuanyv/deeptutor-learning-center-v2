"use client";

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { messagePlainText, type NavMessage } from "@/lib/chat-message-nav";

export interface ChatMinimapProps {
  /** Visible-path user/assistant messages (one tick each). */
  messages: NavMessage[];
  onJump: (messageId: number) => void;
}

/**
 * Right-edge conversation outline — thin horizontal ticks (reference-style
 * "gear" / ruler marks), not a thick scrollbar rail.
 *
 * - One tick per user message, one per assistant message
 * - User ticks shorter/lighter; assistant ticks longer/slightly brighter
 * - Hover shows a floating preview card to the left of that tick
 * - Click jumps to the message
 */
export default function ChatMinimap({ messages, onJump }: ChatMinimapProps) {
  const { t } = useTranslation();
  const [hoverId, setHoverId] = useState<number | null>(null);

  const ticks = useMemo(
    () =>
      messages.filter(
        (m): m is NavMessage & { id: number } =>
          m.id != null && (m.role === "user" || m.role === "assistant"),
      ),
    [messages],
  );

  if (ticks.length === 0) return null;

  // Compress spacing as the thread grows so the stack stays centered and
  // readable without becoming a solid bar.
  const count = ticks.length;
  const rowH = count > 50 ? 8 : count > 28 ? 10 : count > 14 ? 12 : 14;

  return (
    <div
      className="pointer-events-none absolute inset-y-0 right-0 z-30 hidden w-5 md:flex items-center justify-end"
      aria-label={t("Conversation outline")}
    >
      {/*
        No pill / rail background. Ticks sit flush on the content edge like
        the reference gear marks — only the marks themselves are visible.
      */}
      <div
        className="pointer-events-auto flex max-h-[70%] flex-col items-end justify-center py-1"
        style={{ gap: 0 }}
      >
        {ticks.map((m) => {
          const isUser = m.role === "user";
          const hovered = hoverId === m.id;
          const plain = messagePlainText(m.content);
          const preview = plain.slice(0, 96);

          return (
            <div
              key={m.id}
              className="relative flex items-center justify-end"
              style={{ height: rowH }}
              onMouseEnter={() => setHoverId(m.id)}
              onMouseLeave={() =>
                setHoverId((id) => (id === m.id ? null : id))
              }
            >
              <button
                type="button"
                aria-label={
                  isUser ? t("Jump to question") : t("Jump to answer")
                }
                onClick={() => onJump(m.id)}
                onFocus={() => setHoverId(m.id)}
                onBlur={() => setHoverId((id) => (id === m.id ? null : id))}
                className="group flex h-full w-5 items-center justify-end pr-[3px]"
              >
                {/*
                  Visible mark only — thin horizontal tick.
                  Hit target is the full row (h = rowH) for easy hover.
                */}
                <span
                  className={`block h-[2px] rounded-full transition-[width,background-color,opacity] duration-150 ${
                    isUser
                      ? hovered
                        ? "w-2.5 bg-[var(--primary)] opacity-100"
                        : "w-2 bg-[var(--muted-foreground)]/70 opacity-80 group-hover:bg-[var(--primary)] group-hover:opacity-100"
                      : hovered
                        ? "w-3.5 bg-[var(--primary)] opacity-100"
                        : "w-3 bg-[var(--muted-foreground)] opacity-90 group-hover:bg-[var(--primary)] group-hover:opacity-100"
                  }`}
                />
              </button>

              {hovered && preview ? (
                <div
                  role="tooltip"
                  className="pointer-events-none absolute right-full top-1/2 z-40 mr-2 w-[240px] -translate-y-1/2 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2.5 py-2 text-left shadow-lg"
                >
                  <div className="mb-0.5 text-[10px] font-medium tracking-wide text-[var(--muted-foreground)]">
                    {isUser ? t("Question") : t("Answer")}
                  </div>
                  <div className="line-clamp-3 text-[12px] leading-snug text-[var(--foreground)]">
                    {preview}
                    {plain.length > 96 ? "…" : ""}
                  </div>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
