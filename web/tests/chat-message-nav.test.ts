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
  assert.ok(sel);
  assert.equal(sel["null"], 1);
  assert.equal(sel["1"], 2);
  assert.equal(sel["2"], 4);
  assert.equal(sel["4"], 5);
  assert.equal(selectionsToRevealMessage(messages, 999), null);
});
