import assert from "node:assert/strict";
import { test } from "node:test";
import { knowledgeStatus } from "../lib/knowledge-status.ts";

test("knowledge index states explain their limits without inventing failure causes", () => {
  const expectations = {
    pending: ["Waiting to be indexed", "operator"],
    processing: ["Indexing in progress"],
    ready: ["Indexed", "Embedding source is unverified"],
    failed: ["Indexing failed", "operator"],
  };
  for (const [status, phrases] of Object.entries(expectations)) {
    const result = knowledgeStatus(status);
    const visible = `${result.label} ${result.detail}`;
    for (const phrase of phrases)
      assert.ok(visible.includes(phrase), `${status}: missing ${phrase}`);
  }
});
