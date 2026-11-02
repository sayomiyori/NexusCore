import assert from "node:assert/strict";
import { test } from "node:test";
import { filterBots } from "../lib/bot-view.ts";
import type { Bot } from "../lib/bots.ts";

function bot(id: string, name: string): Bot {
  return {
    id,
    name,
    active: true,
    webhook: "configured",
    created: "2026-11-01T00:00:00Z",
    updated: "2026-11-01T00:00:00Z",
  };
}

test("bot search filters only loaded names without altering order or source", () => {
  const rows = [
    bot("1", "Acme Support"),
    bot("2", "Помощник продаж"),
    bot("3", "ACME Alerts"),
  ];
  const before = structuredClone(rows);
  assert.deepEqual(filterBots(rows, "  aCmE  "), [rows[0], rows[2]]);
  assert.deepEqual(filterBots(rows, "продаж"), [rows[1]]);
  assert.deepEqual(filterBots(rows, "missing"), []);
  assert.deepEqual(filterBots(rows, "   "), rows);
  assert.deepEqual(rows, before);
});

test("bot search keeps the same on-page rows for an empty query", () => {
  const rows = [bot("1", "Only bot")];
  assert.equal(filterBots(rows, "")[0], rows[0]);
});
