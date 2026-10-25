import assert from "node:assert/strict";
import { test } from "node:test";
import { type EventFilters, filterObservations } from "../lib/event-view.ts";
import type { Observation } from "../lib/overview.ts";

const filters: EventFilters = {
  kind: "all",
  receiver: "all",
  query: "",
  attention: false,
};
const rows: Observation[] = [
  {
    id: "00000000-0000-4000-8000-0000000000ab",
    kind: "auth",
    at: "2026-10-25T10:00:00Z",
    bot: null,
    state: "owner",
    receivers: ["EventPipe", "PipeWatch"],
    conflict: false,
  },
  {
    id: "00000000-0000-4000-8000-0000000000ac",
    kind: "webhook",
    at: "2026-10-25T09:00:00Z",
    bot: "00000000-0000-4000-8000-0000000000bd",
    state: "failed",
    receivers: ["PipeWatch"],
    conflict: false,
  },
  {
    id: "00000000-0000-4000-8000-0000000000ad",
    kind: "agent",
    at: "2026-10-25T08:00:00Z",
    bot: "00000000-0000-4000-8000-0000000000be",
    state: "completed",
    attempts: 2,
    receivers: ["EventPipe"],
    conflict: true,
  },
  {
    id: "00000000-0000-4000-8000-0000000000ae",
    kind: "agent",
    at: "2026-10-25T07:00:00Z",
    bot: "00000000-0000-4000-8000-0000000000bf",
    state: "unknown",
    attempts: 0,
    receivers: ["EventPipe", "PipeWatch"],
    conflict: false,
  },
];

test("event filters combine kind, receiver, attention and UUID query", () => {
  assert.deepEqual(
    filterObservations(rows, {
      ...filters,
      kind: "agent",
      receiver: "EventPipe",
      attention: true,
      query: "  0000000000BE  ",
    }),
    [rows[2]],
  );
  assert.deepEqual(
    filterObservations(rows, {
      ...filters,
      kind: "webhook",
      receiver: "EventPipe",
    }),
    [],
  );
  assert.deepEqual(
    filterObservations(rows, { ...filters, receiver: "PipeWatch" }),
    [rows[0], rows[1], rows[3]],
  );
});

test("attention includes failed, unknown and conflicting completed snapshots", () => {
  assert.deepEqual(
    filterObservations(rows, { ...filters, attention: true }),
    rows.slice(1),
  );
  assert.deepEqual(
    filterObservations(rows, { ...filters, query: rows[0].id.toUpperCase() }),
    [rows[0]],
  );
  assert.deepEqual(
    filterObservations(rows, { ...filters, query: rows[1].bot || "" }),
    [rows[1]],
  );
  assert.deepEqual(
    filterObservations(rows, { ...filters, query: "owner" }),
    [],
  );
});

test("empty/reset filters preserve source order without mutating source evidence", () => {
  const before = structuredClone(rows);
  for (const row of rows) {
    Object.freeze(row.receivers);
    Object.freeze(row);
  }
  Object.freeze(rows);
  const result = filterObservations(rows, filters);
  assert.deepEqual(result, before);
  assert.notEqual(result, rows);
  assert.deepEqual(
    filterObservations(rows, { ...filters, query: "   " }),
    before,
  );
  assert.deepEqual(filterObservations([], filters), []);
  assert.deepEqual(rows, before);
});
