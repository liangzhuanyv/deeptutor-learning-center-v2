import test from "node:test";
import assert from "node:assert/strict";

import { getPracticeProposal, startPracticeSession, submitPracticeSession } from "../lib/learning-center-api";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

test("practice client scopes proposal and starts a redacted exam session", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  (globalThis as { fetch: typeof fetch }).fetch = async (url, init) => {
    requests.push({ url: String(url), init });
    return response({ id: "session-1", status: "active", questions: [] }, init?.method === "POST" ? 201 : 200);
  };
  try {
    await getPracticeProposal({ project_id: "project-1", module_id: "module-1", difficulty: "hard", limit: 10 });
    await startPracticeSession({ project_id: "project-1", mode: "exam", limit: 10, time_budget_minutes: 30 });
    assert.match(requests[0].url, /\/api\/v1\/learning-center\/practice\/proposal$/);
    assert.deepEqual(JSON.parse(String(requests[0].init?.body)), { project_id: "project-1", module_id: "module-1", difficulty: "hard", limit: 10 });
    assert.match(requests[1].url, /\/api\/v1\/learning-center\/practice\/sessions$/);
    assert.deepEqual(JSON.parse(String(requests[1].init?.body)), { project_id: "project-1", mode: "exam", limit: 10, time_budget_minutes: 30 });
  } finally {
    (globalThis as { fetch: typeof fetch }).fetch = originalFetch;
  }
});

test("practice client submits a whole paper with evidence", async () => {
  const originalFetch = globalThis.fetch;
  let received: RequestInit | undefined;
  (globalThis as { fetch: typeof fetch }).fetch = async (_url, init) => {
    received = init;
    return response({ id: "session-1", status: "completed", questions: [] });
  };
  try {
    await submitPracticeSession("session-1", [{ id: "item-1", user_answer: "A", confidence: "uncertain", eliminated_option_keys: ["B"], elapsed_seconds: 12 }], true);
    assert.equal(received?.method, "POST");
    assert.deepEqual(JSON.parse(String(received?.body)), {
      answers: [{ id: "item-1", user_answer: "A", confidence: "uncertain", eliminated_option_keys: ["B"], elapsed_seconds: 12 }], finish: true,
    });
  } finally {
    (globalThis as { fetch: typeof fetch }).fetch = originalFetch;
  }
});
