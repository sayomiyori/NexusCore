import assert from "node:assert/strict";
import { test } from "node:test";
import { filterJobs, jobStates } from "../lib/job-view.ts";
import type { Job } from "../lib/jobs.ts";

function job(id: string, state: Job["state"]): Job {
  return {
    id,
    eventId: `${id}-event`,
    state,
    attempts: 0,
    created: "2026-11-02T00:00:00Z",
    updated: "2026-11-02T01:00:00Z",
  };
}

test("job state filter keeps only the requested loaded state", () => {
  const rows = jobStates.map((state, index) => job(String(index), state));
  assert.deepEqual(filterJobs(rows, "failed"), [rows[3]]);
  assert.deepEqual(filterJobs(rows, "pending"), [rows[0]]);
  assert.deepEqual(filterJobs(rows, "completed"), [rows[2]]);
});

test("all and unknown-but-valid filters are explicit", () => {
  const rows = [job("1", "failed"), job("2", "unknown")];
  assert.deepEqual(filterJobs(rows, "all"), rows);
  assert.deepEqual(filterJobs(rows, "unknown"), [rows[1]]);
  assert.deepEqual(filterJobs([], "failed"), []);
});

test("filtering preserves response order and never mutates the source", () => {
  const rows = [
    job("1", "completed"),
    job("2", "failed"),
    job("3", "completed"),
  ];
  const before = structuredClone(rows);
  const filtered = filterJobs(rows, "completed");
  assert.deepEqual(
    filtered.map((row) => row.id),
    ["1", "3"],
  );
  assert.equal(filtered[0], rows[0]);
  assert.notEqual(filterJobs(rows, "all"), rows);
  assert.deepEqual(rows, before);
});
