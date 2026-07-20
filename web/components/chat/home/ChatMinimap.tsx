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
 * Thin gear-style ticks centered in the chat pane's **right margin**
 * (the empty band between the max-w 960px content column and the pane edge).
 *
 * Not flush to the viewport edge; not hugging the prose column.
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

  const count = ticks.length;
  // Open spacing so the stack reads as a vertical ruler, not a solid bar.
  const rowH = count > 48 ? 11 : count > 28 ? 13 : count > 16 ? 15 : 18;

  return (
    <div
      className="pointer-events-none absolute inset-y-0 z-30 hidden md:flex items-center justify-center"
      aria-label={t("Conversation outline")}
      style={{
        // Content column is max-w-[960px] centered. Right gutter width ≈
        // (100% - 960px) / 2. Center of that gutter sits at half the gutter
        // from the right edge → (100% - 960px) / 4.
        // Fallback when the pane is narrower than 960px: sit 2.5rem in.
        right: "max(2.5rem, calc((100% - 960px) / 4))",
        width: "3rem",
        transform: "translateX(50%)",
      }}
    >
      <div className="pointer-events-auto flex max-h-[70%] flex-col items-center justify-center">
        {ticks.map((m) => {
          const isUser = m.role === "user";
          const hovered = hoverId === m.id;
          const plain = messagePlainText(m.content);
          const preview = plain.slice(0, 100);

          return (
            <div
              key={m.id}
              className="relative flex items-center justify-center"
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
                className="group flex h-full w-10 items-center justify-center"
              >
                <span
                  className={`block h-[3px] rounded-full transition-[width,background-color,opacity,transform] duration-150 ${
                    isUser
                      ? hovered
                        ? "w-4 scale-y-150 bg-[var(--primary)] opacity-100"
                        : "w-3 bg-[var(--muted-foreground)] opacity-100 group-hover:bg-[var(--primary)]"
                      : hovered
                        ? "w-7 scale-y-150 bg-[var(--primary)] opacity-100"
                        : "w-5 bg-[var(--foreground)]/75 opacity-100 group-hover:bg-[var(--primary)]"
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
