"use client";

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { messagePlainText, type NavMessage } from "@/lib/chat-message-nav";

export interface ChatMinimapProps {
  messages: NavMessage[]; // already visible-path user+assistant only, or full visible path
  onJump: (messageId: number) => void;
}

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

  const hoverMsg = hoverId != null ? ticks.find((m) => m.id === hoverId) : null;
  const preview = hoverMsg
    ? messagePlainText(hoverMsg.content).slice(0, 80)
    : "";

  if (ticks.length === 0) return null;

  // Density: more messages → thinner ticks / tighter gap
  const count = ticks.length;
  const tickH = count > 40 ? 2 : count > 20 ? 3 : 4;
  const gap = count > 40 ? 2 : count > 20 ? 3 : 4;

  return (
    <div
      className="pointer-events-none absolute inset-y-0 right-1 z-20 hidden md:flex items-center"
      aria-hidden={false}
    >
      <div
        className="pointer-events-auto relative flex max-h-[70%] flex-col items-end justify-center py-2"
        style={{ gap }}
      >
        {ticks.map((m) => {
          const isUser = m.role === "user";
          const hovered = hoverId === m.id;
          return (
            <button
              key={m.id}
              type="button"
              title={messagePlainText(m.content).slice(0, 80)}
              aria-label={
                isUser
                  ? t("Jump to question")
                  : t("Jump to answer")
              }
              onMouseEnter={() => setHoverId(m.id)}
              onMouseLeave={() => setHoverId((id) => (id === m.id ? null : id))}
              onFocus={() => setHoverId(m.id)}
              onBlur={() => setHoverId((id) => (id === m.id ? null : id))}
              onClick={() => onJump(m.id)}
              className={`rounded-full transition-all ${
                isUser
                  ? "w-2.5 bg-[var(--muted-foreground)]/35 hover:bg-[var(--primary)]/70"
                  : "w-3.5 bg-[var(--muted-foreground)]/55 hover:bg-[var(--primary)]"
              } ${hovered ? "scale-y-125 opacity-100" : "opacity-80"}`}
              style={{ height: tickH }}
            />
          );
        })}

        {hoverMsg && preview ? (
          <div className="pointer-events-none absolute right-full mr-2 w-56 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2.5 py-2 text-left shadow-md">
            <div className="mb-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
              {hoverMsg.role === "user" ? t("Question") : t("Answer")}
            </div>
            <div className="line-clamp-3 text-[11.5px] leading-snug text-[var(--foreground)]">
              {preview}
              {messagePlainText(hoverMsg.content).length > 80 ? "…" : ""}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
