import assert from "node:assert/strict";
import { test } from "node:test";
import { filterOrganizations } from "../lib/organization-view.ts";

test("organization search filters only loaded names without altering order or source", () => {
  const rows = [
    { id: "1", name: "Acme North", role: "owner" as const },
    { id: "2", name: "Команда Юг", role: "member" as const },
    { id: "3", name: "ACME South", role: "member" as const },
  ];
  const before = structuredClone(rows);
  assert.deepEqual(filterOrganizations(rows, "  aCmE  "), [rows[0], rows[2]]);
  assert.deepEqual(filterOrganizations(rows, "ЮГ"), [rows[1]]);
  assert.deepEqual(filterOrganizations(rows, "missing"), []);
  assert.deepEqual(filterOrganizations(rows, "   "), rows);
  assert.deepEqual(rows, before);
});
