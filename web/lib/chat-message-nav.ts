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
    .replace(/(^|\n)\s*[-*+]\s+/g, " ")
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
  options?: {
    root?: ParentNode | null;
    behavior?: ScrollBehavior;
    /** Defaults to ``start`` so long answers land at the top, not mid-body. */
    block?: ScrollLogicalPosition;
    /** Extra px below the scroller top (clears the chat fade mask). */
    topOffset?: number;
  },
): boolean {
  if (typeof document === "undefined") return false;
  const rootNode =
    options?.root ??
    document.querySelector("[data-chat-scroll-root='true']") ??
    document;
  const el = rootNode.querySelector(
    `[data-message-id="${CSS.escape(String(messageId))}"]`,
  );
  if (!(el instanceof HTMLElement)) return false;

  const behavior = options?.behavior ?? "smooth";
  const block = options?.block ?? "start";
  const topOffset = options?.topOffset ?? 28;

  // Prefer manual scroll on the chat scroller so ``block: start`` is not
  // eaten by the top fade mask / nested layout, and long answers open at
  // their beginning instead of their midpoint.
  const scrollRoot =
    options?.root instanceof HTMLElement
      ? options.root
      : (document.querySelector(
          "[data-chat-scroll-root='true']",
        ) as HTMLElement | null);

  if (scrollRoot instanceof HTMLElement && scrollRoot.contains(el)) {
    const rootRect = scrollRoot.getBoundingClientRect();
    const elRect = el.getBoundingClientRect();
    const delta = elRect.top - rootRect.top - topOffset;
    if (typeof scrollRoot.scrollBy === "function") {
      scrollRoot.scrollBy({ top: delta, behavior });
    } else {
      scrollRoot.scrollTop += delta;
    }
    return true;
  }

  el.scrollIntoView({ block, behavior });
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
