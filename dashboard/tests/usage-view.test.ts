import assert from "node:assert/strict";
import { test } from "node:test";
import { usageRange } from "../lib/usage.ts";
import { USAGE_INTERVAL_ERROR, usageIntervalError } from "../lib/usage-view.ts";

const vectors: Array<[string, string]> = [
  ["2026-01-01", "2026-02-01"],
  ["2028-02-29", "2028-03-01"],
  ["9999-12-01", "9999-12-31"],
  ["2026-12-31", "2027-01-31"],
  ["2026-01-01", "2026-02-02"],
  ["2026-01-02", "2026-01-01"],
  ["2026-01-01", "2026-01-01"],
  ["2026-02-30", "2026-03-01"],
  ["0000-01-01", "0000-01-02"],
  ["2026-1-01", "2026-01-02"],
  ["", "2026-01-02"],
];

test("usage client interval accepts the same positive bounded UTC ranges", () => {
  assert.equal(usageIntervalError("2026-01-01", "2026-02-01"), "");
  assert.equal(usageIntervalError("2028-02-29", "2028-03-01"), "");
  assert.equal(usageIntervalError("9999-12-01", "9999-12-31"), "");
  assert.equal(usageIntervalError("2026-12-31", "2027-01-31"), "");
});

test("usage client interval rejects malformed, reversed and oversized ranges", () => {
  for (const [start, end] of vectors.slice(4))
    assert.equal(usageIntervalError(start, end), USAGE_INTERVAL_ERROR);
});

test("usage client interval rejects year zero and impossible calendar days", () => {
  assert.equal(
    usageIntervalError("0000-01-01", "0000-01-02"),
    USAGE_INTERVAL_ERROR,
  );
  assert.equal(
    usageIntervalError("2026-02-30", "2026-03-01"),
    USAGE_INTERVAL_ERROR,
  );
  assert.equal(
    usageIntervalError("2026-04-31", "2026-05-01"),
    USAGE_INTERVAL_ERROR,
  );
});

test("client interval validity agrees with the authoritative server helper", () => {
  for (const [start, end] of vectors) {
    let serverAllowed = true;
    try {
      usageRange(start, end);
    } catch {
      serverAllowed = false;
    }
    assert.equal(
      usageIntervalError(start, end) === "",
      serverAllowed,
      `${start}..${end}`,
    );
  }
});
