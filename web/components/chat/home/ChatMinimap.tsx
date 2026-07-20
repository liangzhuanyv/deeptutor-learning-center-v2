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
 * Conversation outline as thin horizontal ticks in the chat pane's right
 * margin (outside the max-width content column). Reference-style gear marks:
 * short = question, longer = answer; hover preview; click to jump.
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

  // Spacious density — use the right-side empty margin generously.
  const count = ticks.length;
  const rowH = count > 48 ? 12 : count > 28 ? 14 : count > 16 ? 16 : 18;

  return (
    <div
      className="pointer-events-none absolute inset-y-0 right-0 z-30 hidden w-14 lg:flex items-center justify-end pr-3 xl:pr-5"
      aria-label={t("Conversation outline")}
    >
      <div className="pointer-events-auto flex max-h-[68%] flex-col items-end justify-center">
        {ticks.map((m) => {
          const isUser = m.role === "user";
          const hovered = hoverId === m.id;
          const plain = messagePlainText(m.content);
          const preview = plain.slice(0, 100);

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
                className="group flex h-full w-12 items-center justify-end"
              >
                <span
                  className={`block h-[3px] rounded-full transition-[width,background-color,opacity,transform] duration-150 ${
                    isUser
                      ? hovered
                        ? "w-4 scale-y-125 bg-[var(--primary)] opacity-100"
                        : "w-3 bg-[var(--muted-foreground)]/80 opacity-90 group-hover:bg-[var(--primary)] group-hover:opacity-100"
                      : hovered
                        ? "w-6 scale-y-125 bg-[var(--primary)] opacity-100"
                        : "w-5 bg-[var(--foreground)]/65 opacity-95 group-hover:bg-[var(--primary)] group-hover:opacity-100"
                  }`}
                />
              </button>

              {hovered && preview ? (
                <div
                  role="tooltip"
                  className="pointer-events-none absolute right-full top-1/2 z-40 mr-3 w-[260px] -translate-y-1/2 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-left shadow-xl"
                >
                  <div className="mb-1 text-[10px] font-medium tracking-wide text-[var(--muted-foreground)]">
                    {isUser ? t("Question") : t("Answer")}
                  </div>
                  <div className="line-clamp-4 text-[12.5px] leading-relaxed text-[var(--foreground)]">
                    {preview}
                    {plain.length > 100 ? "…" : ""}
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
