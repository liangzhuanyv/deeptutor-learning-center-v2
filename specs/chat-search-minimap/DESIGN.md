# Chat In-Session Search + Right Minimap — Design

**Date:** 2026-07-20  
**Status:** Approved for implementation planning  
**Scope:** Home chat (`/home/[[...sessionId]]`) only  
**Approach:** Pure frontend (no backend / SQLite / API changes)

## Problem

Long tutoring sessions make it hard to re-find an earlier explanation. Users need:

1. **Keyword search inside the current session** to jump to a past Q or explanation.
2. **A right-edge minimap** (reference: per-message tick marks with hover preview) for spatial jump navigation.

## Goals

- Search **all** messages belonging to the **current session** (not merely the viewport).
- Result list + in-bubble keyword highlight.
- Right-side, vertically centered minimap: **one tick per question, one tick per answer**, visually distinct; hover preview + click jump.
- Visual language must match the existing DeepTutor dark chat chrome (header icon buttons, popovers, borders, hover states).

## Non-goals

- Cross-session search (sidebar “Recents” / Space chat-history remain as-is).
- Backend FTS / new session APIs.
- Permanent right outline column that steals main content width.
- Scroll-spy “current section” highlight on the minimap (hover + click only).
- Merging upstream DeepTutor v1.5.1 / v1.5.2.
- Learning Center practice pages.

## Current baseline (facts)

| Area | Location | Notes |
|---|---|---|
| Home chat page | `web/app/(workspace)/home/[[...sessionId]]/page.tsx` | Header actions, `data-chat-scroll-root` scroller, `ChatMessageList`, composer, `SessionViewerPanel` |
| Message list | `web/components/chat/home/ChatMessages.tsx` | Visible path via `buildVisiblePath`; keys are index-based; `msg.id` exists in memory but **no DOM `data-message-id`** |
| Chat state | `web/context/UnifiedChatContext.tsx` | `loadSession` → `getSession` → `hydrateMessages` |
| Session API | `GET /api/v1/sessions/{id}` via `web/lib/session-api.ts` | **Full message list, no pagination** |
| SQLite store | `deeptutor/services/session/sqlite_store.py` `_get_messages_sync` | `SELECT … FROM messages WHERE session_id = ? ORDER BY id ASC` (no `LIMIT`) |
| Closest outline pattern | `web/app/(workspace)/book/components/PageOutlineNav.tsx` | Floating right nav + `scrollIntoView` (reuse interaction ideas, not Book domain coupling) |
| Existing “search” | `HistorySessionPicker`, Space `ChatHistorySection` | Session-level title / last_message only — **not** in-thread |

## Architecture

```
ChatPage (home)
├── Header actions: Bookmark | Download | Search (new) | Panel
│     └── ChatSearchPopover
│           - query state
│           - results from full session messages
│           - jump + highlight coordination
├── Messages scroller [data-chat-scroll-root]
│     ├── ChatMessageList
│     │     └── message roots: data-message-id={id}
│     │           └── optional <mark> highlight for active query
│     └── ChatMinimap (absolute, right-center)
│           - ticks for visible path only
│           - hover preview + click jump
└── UnifiedChatContext messages (full session corpus)
```

**Coordination (lightweight):**

- Shared helpers (new module under `web/lib/` or `web/components/chat/home/`):
  - `messagePlainText(content)` — strip markdown-ish noise for match/summary.
  - `findMessageMatches(messages, query)` — case-insensitive substring.
  - `scrollToMessageId(id)` — query `[data-message-id="…"]` inside scroll root, `scrollIntoView({ block: "center", behavior: "smooth" })`, flash highlight class.
- Search highlight state lives on the home chat page (or a tiny local React context colocated with the page) so list + popover share `query` / `activeMatchId` without bloating `UnifiedChatContext`.

No changes to `UnifiedChatContext` message schema required beyond ensuring every hydrated user/assistant message retains stable `id`.

## Feature 1 — In-session search

### Entry

- New header icon button (search / magnifier), **same size / stroke / hover as** existing bookmark, download, and panel icons.
- Order: **Bookmark → Download → Search → Panel**.

### Panel

- Popover anchored under the search button (~360–400px wide).
- Contents:
  1. Search input (auto-focus on open).
  2. Result list (scrollable).
- Close: `Esc`, click outside, or toggle icon again.
- Match existing popover / input / list item styling (radius, border, muted text, hover fill) used by settings / history pickers — do not invent a new visual system.

### Corpus (hard requirement)

- Corpus = **all** `user` + `assistant` messages for the **current session** as returned by `getSession` / held in chat state after `loadSession`.
- **Not** limited to the virtualized viewport, DOM-mounted nodes, or only the currently visible branch path.
- **Invariant for future refactors:** if message list virtualization is added later, search must keep using the full in-memory session array (or re-fetch full session), never “only mounted rows.”
- Today this is already true: store + API load the entire session with no `LIMIT`.

### Matching

- Case-insensitive substring on plain text derived from message `content`.
- Include both user and assistant roles.
- Include in-progress streaming assistant text if present in state.
- Skip empty content / system messages.
- No fuzzy / pinyin / regex in v1.

### Results

- Ordered by message chronology (`id` ascending / session order).
- Each row: role chip（问 / 答 or User / Assistant per i18n）, one-line snippet with the match window, keyword emphasized in the snippet.
- Empty query: short hint to type keywords.
- No hits: “本会话无匹配” / i18n equivalent.

### Jump + highlight

1. On result click:
   - If the message is **not** on the current visible branch (`buildVisiblePath`), switch branch selection so the message becomes visible (reuse existing `switchBranch` / `updateBranchSelection` path). If branch switch is ambiguous or unavailable, still attempt scroll after ensuring the message is in the rendered path; document any residual edge case in implementation notes.
   - `scrollToMessageId(id)`.
   - Set `activeMatchId` for a short flash (border/background pulse, ~1.2s).
2. While `query` is non-empty, **all** matched messages in the list render keyword `<mark>` (or styled equivalent) inside bubble text where practical.
3. Clearing the query or closing the popover clears list selection flash and in-bubble marks.

### Keyboard (v1)

- Open → focus input.
- `Esc` closes.
- Optional: ↑/↓ in result list + Enter to jump (nice-to-have if cheap).
- **No** global ⌘/Ctrl+F hijack in v1 (avoid fighting the browser).

## Feature 2 — Right minimap

### Placement

- Absolutely positioned on the **inside right edge** of the messages scroll region (sibling of the list, not a new grid column).
- Vertically **centered** within the scroller’s client height.
- Does not reflow or permanently narrow the prose column.
- Desktop only (e.g. `md+`); hidden on narrow viewports so it never covers the answer body.

### Ticks

- One tick per **visible** user message, one tick per **visible** assistant message (`buildVisiblePath` filtered to user/assistant).
- Visual distinction required:
  - User vs assistant: different opacity, width, or subtle color token already used in chat (user bubble vs assistant text muted tones) — keep minimal, match dark UI.
- Density:
  - Container max-height ≈ middle band of scroller (e.g. 60–70% of client height), vertically centered.
  - Tick thickness / gap scale down as count grows so the stack stays within the band (reference “gear / ruler” feel).
- Active/hover state: slightly brighter tick; no continuous scroll-spy tracking in v1.

### Interaction

- **Hover:** floating preview card near the tick (or to the left of the stack) showing role + ~80 characters of plain-text summary.
- **Click:** `scrollToMessageId(id)` (same helper as search).
- Previews and ticks use the same plain-text helper as search.

### Data source difference (intentional)

| Surface | Data |
|---|---|
| Search | Full session messages (all branches) |
| Minimap | Visible path only (what the scroller currently represents) |

Rationale: minimap mirrors spatial layout of what is on screen; search is for recall across the whole session including other edit branches.

## DOM contract

Every rendered user/assistant row root in `ChatMessageList` must expose:

```html
data-message-id="{stableId}"
```

- Prefer server integer ids.
- Optimistic / streaming rows with temporary negative ids are addressable for the lifetime of that row; after re-hydrate, search uses the persisted id.

`scrollToMessageId` looks up within `[data-chat-scroll-root]` only.

## i18n

- Add strings to `web/locales/en/app.json` and `web/locales/zh/app.json` for:
  - Search button aria-label
  - Placeholder, empty, no-results
  - Role labels in results / minimap preview
- Follow existing key naming style in those files.

## Testing

- Unit (frontend): plain-text extraction, match finder (case, multi-hit, empty), snippet windowing.
- Component / light integration where the repo already tests chat UI patterns:
  - Message row renders `data-message-id`.
  - Search filters full in-memory list (fixture with messages not “on screen”).
  - Minimap tick count equals visible user+assistant count.
- Manual smoke on a long real session: search early turn, jump, highlight clear; minimap hover + jump; header icon alignment with existing three buttons.

## Rollout / risk

| Risk | Mitigation |
|---|---|
| Branch jump complexity | Implement scroll-on-visible-path first; branch switch if message missing from path; fall back to best-effort scroll |
| Huge sessions (10k+ msgs) client search cost | Linear scan is fine for tutoring-scale; debounce input ~150ms |
| Minimap clutter | Density scaling + hide on small screens |
| Style drift | Reuse header `button` classes / tokens from existing icon actions |
| Autoscroll fighting jump | Temporarily release pin-to-bottom via existing `useChatAutoScroll` scroll handler behavior (user scroll already unpins) |

## Implementation sketch (for plan, not binding file names)

1. Add DOM ids + shared `scrollToMessageId` / plain-text / match helpers.
2. Header Search icon + `ChatSearchPopover` + highlight state on home page.
3. Keyword mark rendering in message bubbles (minimal invasive path in `ChatMessages` / markdown renderer).
4. `ChatMinimap` floating stack + hover preview.
5. i18n + unit tests + manual smoke.

## Decision log

| Decision | Choice |
|---|---|
| Approach | Pure frontend |
| Search scope | Current session, **full** message set |
| Search UI | Popover list + in-bubble highlight |
| Header order | Bookmark, Download, Search, Panel |
| Minimap unit | Separate ticks for Q and A |
| Minimap interaction | Hover preview + click (no scroll-spy) |
| Minimap placement | Right-center float, adaptive density |
| Visual | Match existing DeepTutor UI |
| Backend | No changes |
| Upstream merge | Out of scope |
