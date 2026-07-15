import test from "node:test";
import assert from "node:assert/strict";

import { analyzeImport, approveImport } from "../lib/learning-center-api";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

test("canonical import client posts the versioned payload", async () => {
  const originalFetch = globalThis.fetch;
  let receivedUrl = "";
  let receivedInit: RequestInit | undefined;
  (globalThis as { fetch: typeof fetch }).fetch = async (url, init) => {
    receivedUrl = String(url);
    receivedInit = init;
    return response({ id: "batch-1", status: "preview_ready", items: [], events: [], summary: {} }, 201);
  };
  try {
    const result = await analyzeImport({
      schema_version: "learning-import/v1",
      project: { external_id: "music", name: "Music" },
      bank: { external_id: "intervals", name: "Intervals", version: "v1" },
      items: [{ external_id: "q1", question_type: "single_choice", stem: "Fifth?" }],
    });
    assert.equal(result.id, "batch-1");
    assert.match(receivedUrl, /\/api\/v1\/learning-center\/imports\/analyze$/);
    assert.equal(receivedInit?.method, "POST");
    assert.deepEqual(JSON.parse(String(receivedInit?.body)), {
      schema_version: "learning-import/v1",
      project: { external_id: "music", name: "Music" },
      bank: { external_id: "intervals", name: "Intervals", version: "v1" },
      items: [{ external_id: "q1", question_type: "single_choice", stem: "Fifth?" }],
    });
  } finally {
    (globalThis as { fetch: typeof fetch }).fetch = originalFetch;
  }
});

test("selected approval posts only the user-selected valid import ids", async () => {
  const originalFetch = globalThis.fetch;
  let receivedInit: RequestInit | undefined;
  (globalThis as { fetch: typeof fetch }).fetch = async (_url, init) => {
    receivedInit = init;
    return response({ id: "batch-1", status: "approved", items: [], events: [], summary: { approved: 1 } });
  };
  try {
    const result = await approveImport("batch-1", {
      mode: "selected",
      selected_item_ids: ["item-2"],
      minimum_confidence: 0.9,
    });
    assert.equal(result.status, "approved");
    assert.deepEqual(JSON.parse(String(receivedInit?.body)), {
      mode: "selected",
      selected_item_ids: ["item-2"],
      minimum_confidence: 0.9,
    });
  } finally {
    (globalThis as { fetch: typeof fetch }).fetch = originalFetch;
  }
});
