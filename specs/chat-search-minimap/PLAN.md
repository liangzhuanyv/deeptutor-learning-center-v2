# Chat Search + Minimap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add in-session keyword search (full current session) and a right-edge Q/A minimap on the home chat page so users can jump back to past explanations.

**Architecture:** Pure frontend. Shared nav helpers (`plain text`, `match`, `scroll`, `branch reveal`) feed a header search popover and a floating minimap. Message rows expose `data-message-id`. Search corpus = full in-memory session messages; minimap ticks = visible path only. No backend changes.

**Tech Stack:** Next.js / React 19, TypeScript, Tailwind CSS variables (existing tokens), lucide-react icons, i18next, Node test runner (`web/tests/*.test.ts` via `npm run test:node`).

**Spec:** `specs/chat-search-minimap/DESIGN.md`

---

## File map

| File | Responsibility |
|---|---|
| **Create** `web/lib/chat-message-nav.ts` | Plain-text extract, match/snippet, scroll-to-id, branch selections to reveal a message |
| **Create** `web/tests/chat-message-nav.test.ts` | Unit tests for helpers |
| **Create** `web/components/chat/home/ChatSearchPopover.tsx` | Header search popover UI |
| **Create** `web/components/chat/home/ChatMinimap.tsx` | Right-edge tick stack + hover preview |
| **Modify** `web/components/chat/home/ChatMessages.tsx` | `data-message-id`, search-hit / flash classes, optional user-text marks, pass-through props |
| **Modify** `web/app/(workspace)/home/[[...sessionId]]/page.tsx` | Search button, state, wire popover + minimap, jump orchestration |
| **Modify** `web/locales/en/app.json` | New UI strings |
| **Modify** `web/locales/zh/app.json` | Chinese strings (parity) |

---

### Task 1: Navigation helpers + unit tests (TDD)

**Files:**
- Create: `web/lib/chat-message-nav.ts`
- Create: `web/tests/chat-message-nav.test.ts`

- [ ] **Step 1: Write the failing tests**

```ts
// web/tests/chat-message-nav.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  messagePlainText,
  findMessageMatches,
  buildSnippet,
  selectionsToRevealMessage,
} from "../lib/chat-message-nav";

test("messagePlainText strips common markdown noise", () => {
  assert.equal(
    messagePlainText("**β** is `Cov/Var`\n\n- item"),
    "β is Cov/Var item",
  );
  assert.equal(messagePlainText(""), "");
});

test("findMessageMatches scans full list case-insensitively", () => {
  const messages = [
    { id: 1, role: "user" as const, content: "What is CAPM?" },
    { id: 2, role: "assistant" as const, content: "CAPM links return to beta." },
    { id: 3, role: "user" as const, content: "Other topic" },
    { id: 4, role: "system" as const, content: "ignore CAPM" },
  ];
  const hits = findMessageMatches(messages, "capm");
  assert.deepEqual(
    hits.map((h) => h.id),
    [1, 2],
  );
  assert.equal(findMessageMatches(messages, "   ").length, 0);
  assert.equal(findMessageMatches(messages, "zzz").length, 0);
});

test("buildSnippet centers the match window", () => {
  const long = "a".repeat(40) + "TARGET" + "b".repeat(40);
  const snip = buildSnippet(long, "TARGET", 20);
  assert.match(snip, /TARGET/);
  assert.ok(snip.length <= 50);
});

test("selectionsToRevealMessage walks parent chain", () => {
  const messages = [
    { id: 1, role: "user" as const, content: "q1", parentMessageId: null },
    { id: 2, role: "assistant" as const, content: "a1", parentMessageId: 1 },
    { id: 3, role: "user" as const, content: "q2-branchA", parentMessageId: 2 },
    { id: 4, role: "user" as const, content: "q2-branchB", parentMessageId: 2 },
    { id: 5, role: "assistant" as const, content: "a2-B", parentMessageId: 4 },
  ];
  const sel = selectionsToRevealMessage(messages, 5);
  assert.equal(sel["null"], 1);
  assert.equal(sel["1"], 2);
  assert.equal(sel["2"], 4);
  assert.equal(sel["4"], 5);
  assert.equal(selectionsToRevealMessage(messages, 999), null);
});
```

- [ ] **Step 2: Run tests — expect FAIL (module missing)**

```bash
cd web && node --test tests/chat-message-nav.test.ts
```

Expected: `Cannot find module` / fail to load `../lib/chat-message-nav`.

- [ ] **Step 3: Implement helpers**

```ts
// web/lib/chat-message-nav.ts

export type NavMessage = {
  id?: number;
  role: "user" | "assistant" | "system" | string;
  content?: string | null;
  parentMessageId?: number | null;
};

export type MessageMatch = {
  id: number;
  role: "user" | "assistant";
  content: string;
  plain: string;
};

/** Strip light markdown for search/summary. Not a full markdown parser. */
export function messagePlainText(content: unknown): string {
  let text = "";
  if (content == null) text = "";
  else if (typeof content === "string") text = content;
  else text = String(content);

  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[#>*_~]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function findMessageMatches(
  messages: NavMessage[],
  query: string,
): MessageMatch[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const out: MessageMatch[] = [];
  for (const msg of messages) {
    if (msg.id == null) continue;
    if (msg.role !== "user" && msg.role !== "assistant") continue;
    const plain = messagePlainText(msg.content);
    if (!plain) continue;
    if (!plain.toLowerCase().includes(q)) continue;
    out.push({
      id: msg.id,
      role: msg.role,
      content: typeof msg.content === "string" ? msg.content : plain,
      plain,
    });
  }
  // Chronological: lower id first (optimistic negative ids sort first — acceptable)
  out.sort((a, b) => a.id - b.id);
  return out;
}

export function buildSnippet(
  plain: string,
  query: string,
  radius: number = 36,
): string {
  const q = query.trim();
  if (!q) return plain.slice(0, radius * 2);
  const lower = plain.toLowerCase();
  const idx = lower.indexOf(q.toLowerCase());
  if (idx < 0) return plain.slice(0, radius * 2);
  const start = Math.max(0, idx - radius);
  const end = Math.min(plain.length, idx + q.length + radius);
  let snip = plain.slice(start, end);
  if (start > 0) snip = "…" + snip;
  if (end < plain.length) snip = snip + "…";
  return snip;
}

/**
 * Parent-key → child-id map that makes `targetId` lie on the visible path
 * when merged into `selectedBranches`. Keys use the same convention as
 * `message-branches.ts`: root parent is `"null"`.
 */
export function selectionsToRevealMessage(
  messages: NavMessage[],
  targetId: number,
): Record<string, number> | null {
  const byId = new Map<number, NavMessage>();
  for (const m of messages) {
    if (m.id != null) byId.set(m.id, m);
  }
  if (!byId.has(targetId)) return null;

  const chain: NavMessage[] = [];
  let cur: NavMessage | undefined = byId.get(targetId);
  const guard = new Set<number>();
  while (cur && cur.id != null && !guard.has(cur.id)) {
    guard.add(cur.id);
    chain.push(cur);
    const pid = cur.parentMessageId;
    cur = pid == null ? undefined : byId.get(pid);
  }
  chain.reverse();

  const selections: Record<string, number> = {};
  for (const msg of chain) {
    if (msg.id == null) continue;
    const parentKey =
      msg.parentMessageId == null ? "null" : String(msg.parentMessageId);
    selections[parentKey] = msg.id;
  }
  return selections;
}

export function scrollToMessageId(
  messageId: number,
  options?: { root?: ParentNode | null; behavior?: ScrollBehavior },
): boolean {
  if (typeof document === "undefined") return false;
  const root =
    options?.root ??
    document.querySelector("[data-chat-scroll-root='true']") ??
    document;
  const el = root.querySelector(
    `[data-message-id="${CSS.escape(String(messageId))}"]`,
  );
  if (!(el instanceof HTMLElement)) return false;
  el.scrollIntoView({
    block: "center",
    behavior: options?.behavior ?? "smooth",
  });
  return true;
}

/** Split plain text into segments for <mark> rendering. */
export function splitHighlight(
  text: string,
  query: string,
): Array<{ text: string; hit: boolean }> {
  const q = query.trim();
  if (!q || !text) return [{ text, hit: false }];
  const lower = text.toLowerCase();
  const qLower = q.toLowerCase();
  const parts: Array<{ text: string; hit: boolean }> = [];
  let i = 0;
  while (i < text.length) {
    const idx = lower.indexOf(qLower, i);
    if (idx < 0) {
      parts.push({ text: text.slice(i), hit: false });
      break;
    }
    if (idx > i) parts.push({ text: text.slice(i, idx), hit: false });
    parts.push({ text: text.slice(idx, idx + q.length), hit: true });
    i = idx + q.length;
  }
  return parts.length ? parts : [{ text, hit: false }];
}
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd web && node --test tests/chat-message-nav.test.ts
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add web/lib/chat-message-nav.ts web/tests/chat-message-nav.test.ts
git commit -m "feat(chat): add message nav helpers for search and minimap"
```

---

### Task 2: DOM anchors on message rows

**Files:**
- Modify: `web/components/chat/home/ChatMessages.tsx`

- [ ] **Step 1: Extend `ChatMessageList` props**

Add optional:

```ts
highlightQuery?: string;
activeMatchId?: number | null;
matchIds?: Set<number> | number[];
```

Normalize `matchIds` to a `Set` inside the component with `useMemo`.

- [ ] **Step 2: Tag user message root**

On `UserMessage` outer root (`div.group.flex.justify-end` ~line 1018), add:

```tsx
data-message-id={msg.id != null ? String(msg.id) : undefined}
data-search-hit={
  msg.id != null && matchIdSet.has(msg.id) ? "true" : undefined
}
className={`group flex justify-end ${
  msg.id != null && activeMatchId === msg.id
    ? "rounded-xl ring-2 ring-[var(--primary)]/50 transition-shadow"
    : ""
} ${
  msg.id != null && matchIdSet.has(msg.id)
    ? "bg-[var(--primary)]/[0.04]"
    : ""
}`}
```

Pass `highlightQuery`, `activeMatchId`, `matchIdSet` into `UserMessage` props.

- [ ] **Step 3: User bubble keyword marks (plain text only)**

Where user content is rendered as plain text (non-editing bubble), if `highlightQuery` is non-empty:

```tsx
import { splitHighlight } from "@/lib/chat-message-nav";

// inside bubble:
{highlightQuery?.trim()
  ? splitHighlight(msg.content, highlightQuery).map((part, i) =>
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
    )
  : msg.content}
```

Do **not** attempt to inject marks into assistant markdown AST in v1 (breaks math/code). Assistant rows still get container `data-search-hit` + active ring.

- [ ] **Step 4: Tag assistant message wrapper**

On the assistant row wrapper (`div.w-full` ~line 1380):

```tsx
<div
  key={`${msg.role}-${i}`}
  className={`w-full ${
    msg.id != null && activeMatchId === msg.id
      ? "rounded-xl ring-2 ring-[var(--primary)]/50"
      : ""
  } ${
    msg.id != null && matchIdSet.has(msg.id)
      ? "bg-[var(--primary)]/[0.03]"
      : ""
  }`}
  data-message-id={msg.id != null ? String(msg.id) : undefined}
  data-search-hit={
    msg.id != null && matchIdSet.has(msg.id) ? "true" : undefined
  }
>
```

- [ ] **Step 5: Smoke typecheck (optional local)**

```bash
cd web && npx tsc --noEmit -p tsconfig.json 2>&1 | head -40
```

Fix any prop plumbing errors.

- [ ] **Step 6: Commit**

```bash
git add web/components/chat/home/ChatMessages.tsx
git commit -m "feat(chat): add data-message-id and search hit styling on rows"
```

---

### Task 3: ChatSearchPopover component

**Files:**
- Create: `web/components/chat/home/ChatSearchPopover.tsx`

- [ ] **Step 1: Implement popover**

Match existing dark UI: `var(--card)`, `var(--border)`, `var(--muted)`, rounded-xl, small type. Pattern loosely after compact pickers / header tooltips — **not** full-screen modal.

```tsx
// web/components/chat/home/ChatSearchPopover.tsx
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
```

- [ ] **Step 2: Commit**

```bash
git add web/components/chat/home/ChatSearchPopover.tsx
git commit -m "feat(chat): add in-session search popover UI"
```

---

### Task 4: ChatMinimap component

**Files:**
- Create: `web/components/chat/home/ChatMinimap.tsx`

- [ ] **Step 1: Implement minimap**

```tsx
// web/components/chat/home/ChatMinimap.tsx
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
```

Notes for implementer:
- Parent scroller must be `relative` so absolute minimap anchors correctly.
- Keep ticks subtle; match dark theme — no bright rainbow colors.

- [ ] **Step 2: Commit**

```bash
git add web/components/chat/home/ChatMinimap.tsx
git commit -m "feat(chat): add right-edge Q/A minimap"
```

---

### Task 5: Wire home chat page

**Files:**
- Modify: `web/app/(workspace)/home/[[...sessionId]]/page.tsx`

- [ ] **Step 1: Imports + state**

```tsx
import { BookmarkPlus, Download, PanelRight, Search } from "lucide-react";
import ChatSearchPopover from "@/components/chat/home/ChatSearchPopover";
import ChatMinimap from "@/components/chat/home/ChatMinimap";
import {
  findMessageMatches,
  scrollToMessageId,
  selectionsToRevealMessage,
} from "@/lib/chat-message-nav";
import { buildVisiblePath } from "@/lib/message-branches";

// inside ChatPage component:
const [searchOpen, setSearchOpen] = useState(false);
const [searchQuery, setSearchQuery] = useState("");
const [activeMatchId, setActiveMatchId] = useState<number | null>(null);
const searchWrapRef = useRef<HTMLDivElement>(null);
```

- [ ] **Step 2: Derived match set + visible path for minimap**

```tsx
const searchMatchIds = useMemo(() => {
  if (!searchQuery.trim()) return new Set<number>();
  return new Set(
    findMessageMatches(state.messages, searchQuery).map((m) => m.id),
  );
}, [state.messages, searchQuery]);

const visibleNavMessages = useMemo(
  () =>
    buildVisiblePath(state.messages, state.selectedBranches).messages.filter(
      (m) => m.role === "user" || m.role === "assistant",
    ),
  [state.messages, state.selectedBranches],
);
```

Confirm `state.selectedBranches` is available from `useUnifiedChat()` / session state (same source already passed to `ChatMessageList` as `selectedBranches`). Use the identical prop value already on the page.

- [ ] **Step 3: Jump handler**

```tsx
const handleJumpToMessage = useCallback(
  (messageId: number) => {
    const visibleIds = new Set(
      buildVisiblePath(state.messages, state.selectedBranches).messages
        .map((m) => m.id)
        .filter((id): id is number => id != null),
    );

    if (!visibleIds.has(messageId)) {
      const selections = selectionsToRevealMessage(state.messages, messageId);
      if (selections) {
        for (const [parentKey, childId] of Object.entries(selections)) {
          const parentId =
            parentKey === "null" ? null : Number(parentKey);
          // switchBranch from useUnifiedChat
          switchBranch(parentId, childId);
        }
      }
    }

    setActiveMatchId(messageId);
    // Wait a frame (or two) for branch re-render before scrolling
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        scrollToMessageId(messageId, {
          root: messagesContainerRef.current,
        });
      });
    });

    window.setTimeout(() => {
      setActiveMatchId((cur) => (cur === messageId ? null : cur));
    }, 1200);
  },
  [state.messages, state.selectedBranches, switchBranch, messagesContainerRef],
);
```

Wire `switchBranch` from `useUnifiedChat()` (already used for list branching).

- [ ] **Step 4: Outside click closes search**

```tsx
useEffect(() => {
  if (!searchOpen) return;
  const onPointer = (e: MouseEvent) => {
    if (!searchWrapRef.current?.contains(e.target as Node)) {
      setSearchOpen(false);
    }
  };
  document.addEventListener("mousedown", onPointer);
  return () => document.removeEventListener("mousedown", onPointer);
}, [searchOpen]);
```

Clear highlights when closing:

```tsx
const closeSearch = useCallback(() => {
  setSearchOpen(false);
  setSearchQuery("");
  setActiveMatchId(null);
}, []);
```

- [ ] **Step 5: Header button order**

Inside the header actions `div` (`flex shrink-0 items-center gap-0.5`), order:

1. Bookmark (existing)
2. Download (existing)
3. **Search (new)** — wrap in `relative` ref container with popover
4. Panel (existing)

```tsx
<div ref={searchWrapRef} className="relative">
  <HeaderActionButton
    onClick={() => setSearchOpen((v) => !v)}
    active={searchOpen}
    disabled={!state.messages.length}
    icon={Search}
    label={t("Search in conversation")}
    title={t("Search messages in this chat")}
  />
  <ChatSearchPopover
    open={searchOpen}
    onClose={closeSearch}
    query={searchQuery}
    onQueryChange={setSearchQuery}
    messages={state.messages}
    onSelectMatch={handleJumpToMessage}
    activeMatchId={activeMatchId}
  />
</div>
```

- [ ] **Step 6: Scroller becomes positioning context + minimap**

Change messages scroller wrapper so minimap can sit on the right **without** being clipped incorrectly:

- Keep `data-chat-scroll-root` on the scrolling element.
- Prefer an outer `relative flex-1 min-h-0` wrapper:

```tsx
<div className="relative flex min-h-0 flex-1 flex-col">
  <div
    ref={messagesContainerRef}
    data-chat-scroll-root="true"
    onScroll={handleMessagesScroll}
    ...
  >
    <ChatMessageList
      ...
      highlightQuery={searchQuery}
      activeMatchId={activeMatchId}
      matchIds={searchMatchIds}
    />
  </div>
  {hasMessages ? (
    <ChatMinimap
      messages={visibleNavMessages}
      onJump={handleJumpToMessage}
    />
  ) : null}
</div>
```

If minimap is **outside** the scroll container, ticks won't scroll with content — that is intended (fixed spatial overview of the thread). Ticks map 1:1 to message order, not pixel position; click still `scrollIntoView`. This matches the reference "ruler" UX.

- [ ] **Step 7: Manual smoke checklist**

1. Open a long session → search early keyword → result list → click → scrolls + flash.
2. Clear search / close → marks gone.
3. Minimap hover preview + click jump.
4. Header icons align with existing three.
5. Narrow viewport: minimap hidden (`md:flex`).
6. Empty session: search disabled.

- [ ] **Step 8: Commit**

```bash
git add web/app/(workspace)/home/[[...sessionId]]/page.tsx
git commit -m "feat(chat): wire in-session search and minimap on home page"
```

---

### Task 6: i18n strings

**Files:**
- Modify: `web/locales/en/app.json`
- Modify: `web/locales/zh/app.json`

- [ ] **Step 1: Add keys (exact English keys used by `t(...)`)**

English (`web/locales/en/app.json`) — add near other chat strings:

```json
"Search in conversation": "Search in conversation",
"Search messages in this chat": "Search messages in this chat",
"Search messages in this chat…": "Search messages in this chat…",
"Type to search this conversation": "Type to search this conversation",
"No matches in this conversation": "No matches in this conversation",
"Clear search": "Clear search",
"Question": "Question",
"Answer": "Answer",
"Jump to question": "Jump to question",
"Jump to answer": "Jump to answer"
```

If `"Question"` / `"Answer"` already exist, reuse — do not duplicate keys.

Chinese (`web/locales/zh/app.json`):

```json
"Search in conversation": "在对话中搜索",
"Search messages in this chat": "搜索本会话消息",
"Search messages in this chat…": "搜索本会话消息…",
"Type to search this conversation": "输入关键词搜索本会话",
"No matches in this conversation": "本会话无匹配",
"Clear search": "清除搜索",
"Question": "问",
"Answer": "答",
"Jump to question": "跳转到问题",
"Jump to answer": "跳转到回答"
```

- [ ] **Step 2: Parity check**

```bash
cd web && npm run i18n:parity
```

Expected: pass (or only pre-existing unrelated diffs — fix any new missing keys you introduced).

- [ ] **Step 3: Commit**

```bash
git add web/locales/en/app.json web/locales/zh/app.json
git commit -m "i18n: add chat search and minimap strings"
```

---

### Task 7: Final verification

- [ ] **Step 1: Unit tests**

```bash
cd web && node --test tests/chat-message-nav.test.ts
```

Expected: PASS.

- [ ] **Step 2: Broader node tests (no regressions)**

```bash
cd web && npm run test:node
```

Expected: all pass (or only pre-existing failures unrelated to this work — do not "fix" unrelated failures by weakening tests).

- [ ] **Step 3: Browser smoke on running app**

- Search full session (including early messages).
- Jump from search + minimap.
- Confirm no layout regression on composer / header.
- Confirm Learning Center routes untouched.

- [ ] **Step 4: Final commit if any fixups**

```bash
git add -A
git status
# if needed:
git commit -m "fix(chat): polish search minimap edge cases"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|---|---|
| Full-session search corpus | Task 1 + 3 + 5 (`state.messages`, not visible path) |
| Result list + snippet highlight | Task 3 |
| In-bubble marks (practical) | Task 2 (user plain text + container hit for all) |
| Header icon order | Task 5 |
| Match existing UI chrome | Tasks 3–5 (tokens / HeaderActionButton) |
| Minimap Q/A separate ticks | Task 4 |
| Hover preview + click | Task 4 |
| Right-center, adaptive density, md+ | Task 4 |
| `data-message-id` | Task 2 |
| Branch reveal on off-path hit | Task 1 `selectionsToRevealMessage` + Task 5 |
| No backend | All tasks frontend-only |
| i18n | Task 6 |
| Tests | Task 1 + 7 |

## Intentional v1 limits (documented)

1. **Assistant in-bubble `<mark>`** not injected into markdown AST (math/code safety). Container `data-search-hit` + result-list marks cover recall UX.
2. **No ⌘/Ctrl+F** hijack.
3. **No scroll-spy** active tick.
4. **Minimap = visible path only**; search = full session.

---

## Self-review notes

- No TBD placeholders.
- Helper names consistent: `messagePlainText`, `findMessageMatches`, `selectionsToRevealMessage`, `scrollToMessageId`, `splitHighlight`.
- `selectedBranches` / `switchBranch` must use the same objects already on the home page for `ChatMessageList`.
