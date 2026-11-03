import assert from "node:assert/strict";
import { test } from "node:test";
import type { Document } from "../lib/knowledge.ts";
import { filterDocuments } from "../lib/knowledge-view.ts";

function document(id: number, title: string): Document {
  return { id, title, type: "txt", status: "ready", chunks: 1 };
}

test("document search filters loaded titles case-insensitively and trimmed", () => {
  const rows = [
    document(1, "Acme Handbook"),
    document(2, "Помощник продаж"),
    document(3, "ACME Billing"),
  ];
  const before = structuredClone(rows);
  assert.deepEqual(filterDocuments(rows, "  aCmE  "), [rows[0], rows[2]]);
  assert.deepEqual(filterDocuments(rows, "Помощник"), [rows[1]]);
  assert.deepEqual(filterDocuments(rows, "missing"), []);
  assert.deepEqual(filterDocuments(rows, "   "), rows);
  assert.deepEqual(rows, before);
});

test("document search preserves order, returns a new array and handles empty pages", () => {
  const rows = [document(1, "Alpha"), document(2, "Beta")];
  const filtered = filterDocuments(rows, "a");
  assert.deepEqual(
    filtered.map((row) => row.id),
    [1, 2],
  );
  assert.equal(filtered[0], rows[0]);
  assert.notEqual(filterDocuments(rows, ""), rows);
  assert.deepEqual(filterDocuments([], "anything"), []);
});
