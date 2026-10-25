import assert from "node:assert/strict";
import http from "node:http";
import { after, before, beforeEach, test } from "node:test";
import { NextRequest } from "next/server.js";
import { GET } from "../app/api/usage/route.ts";

const tenant = "00000000-0000-4000-8000-000000000001",
  bot = "00000000-0000-4000-8000-000000000002";
const browser = "http://127.0.0.1:3000",
  query = `tenant=${tenant}&bot=${bot}&start=2026-10-01&end=2026-10-25`;
let calls: { path: string; method: string; tenant?: string }[] = [];
let authStatus = 200,
  sourceStatus = 200,
  mismatched = false;
let role = "owner";
let value: Record<string, unknown>;
const server = http.createServer((req, res) => {
  const path = req.url || "";
  calls.push({
    path,
    method: req.method || "",
    tenant: req.headers["x-tenant-id"] as string | undefined,
  });
  assert.equal(req.headers.authorization, "Bearer synthetic-usage");
  res.setHeader("Content-Type", "application/json");
  if (path === `/api/v1/tenants/${tenant}`) {
    res.statusCode = authStatus;
    res.end(
      JSON.stringify(
        authStatus === 200
          ? {
              id: mismatched ? bot : tenant,
              name: "Usage tenant",
              role,
              private: "private-issuer",
            }
          : { private: "private-issuer-error" },
      ),
    );
  } else {
    assert(path.startsWith(`/api/v1/tenants/${tenant}/bots/${bot}/ai/usage?`));
    assert.equal(req.headers["x-tenant-id"], tenant);
    res.statusCode = sourceStatus;
    res.end(
      JSON.stringify(
        sourceStatus === 200 ? value : { private: "private-source-error" },
      ),
    );
  }
});
before(async () => {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert(address && typeof address === "object");
  process.env.DASHBOARD_ORIGIN = browser;
  process.env.DASHBOARD_AUTH_ORIGIN = `http://127.0.0.1:${address.port}`;
  process.env.DASHBOARD_AGENT_ORIGIN = process.env.DASHBOARD_AUTH_ORIGIN;
});
after(async () => {
  server.closeAllConnections();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});
beforeEach(() => {
  calls = [];
  authStatus = sourceStatus = 200;
  mismatched = false;
  role = "owner";
  value = {
    records: 2,
    input_tokens: 123,
    output_tokens: 456,
    estimated_cost_usd: "0.12345678",
    provider: "private-provider",
    answer: "private-answer",
    credentials: "private-secret",
  };
});
function request(params = query, headers: Record<string, string> = {}) {
  return new NextRequest(`${browser}/api/usage?${params}`, {
    headers: {
      host: "127.0.0.1:3000",
      cookie: "nexus_session=synthetic-usage",
      ...headers,
    },
  });
}

test("usage projects exact bounded recorded totals via authorized GET-only requests", async () => {
  const response = await GET(request());
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "private, no-store");
  assert.deepEqual(await response.json(), {
    tenant: { id: tenant, name: "Usage tenant", role: "owner" },
    bot,
    start: "2026-10-01T00:00:00.000Z",
    end: "2026-10-25T00:00:00.000Z",
    records: 2,
    inputTokens: 123,
    outputTokens: 456,
    estimatedCostUsd: "0.12345678",
  });
  assert(calls.every((call) => call.method === "GET"));
  const url = new URL(calls[1].path, browser);
  assert.equal(url.searchParams.get("start"), "2026-10-01T00:00:00.000Z");
  assert.equal(url.searchParams.get("end"), "2026-10-25T00:00:00.000Z");
  assert.equal(calls[0].path, `/api/v1/tenants/${tenant}`);
});

test("usage validates real UTC calendar intervals before any issuer or source call", async () => {
  const base = `tenant=${tenant}&bot=${bot}`;
  for (const range of [
    "start=2026-02-29&end=2026-03-01",
    "start=2026-02-30&end=2026-03-01",
    "start=2026-10-01&end=2026-10-01",
    "start=2026-10-02&end=2026-10-01",
    "start=2026-01-01&end=2026-02-02",
    "start=0000-01-01&end=0000-01-02",
    "start=2026-1-01&end=2026-01-02",
    "start=2026-10-01T00:00:00Z&end=2026-10-02",
    "start=2026-13-01&end=2026-13-02",
  ]) {
    assert.equal((await GET(request(`${base}&${range}`))).status, 400, range);
    assert.equal(calls.length, 0);
  }
  for (const range of [
    "start=2024-02-29&end=2024-03-01",
    "start=2026-01-01&end=2026-02-01",
    "start=2026-12-31&end=2027-01-01",
  ]) {
    assert.equal((await GET(request(`${base}&${range}`))).status, 200, range);
  }
});

test("usage rejects malformed scope, queries and missing identity before upstream access", async () => {
  for (const bad of [
    "",
    `${query}&limit=10`,
    `${query}&tenant=${tenant}`,
    `${query}&bot=${bot}`,
    `${query}&start=2026-10-01`,
    query.replace(`bot=${bot}`, "bot="),
    query.replace(tenant, tenant.toUpperCase().replace("0001", "000A")),
    query.replace("&end=2026-10-25", ""),
    `${query}&cursor=${bot}`,
  ]) {
    assert.equal((await GET(request(bad))).status, 400, bad);
    assert.equal(calls.length, 0);
  }
  assert.equal((await GET(request(query, { cookie: "" }))).status, 401);
  assert.equal(
    (await GET(request(query, { host: "attacker.invalid" }))).status,
    403,
  );
  assert.equal(calls.length, 0);
});

test("usage checks membership freshly and never reads source after denied or mismatched issuer scope", async () => {
  assert.equal((await GET(request())).status, 200);
  role = "member";
  const member = await GET(request());
  assert.equal(member.status, 200);
  assert.equal((await member.json()).tenant.role, "member");
  for (const status of [401, 403, 404, 503]) {
    authStatus = status;
    calls = [];
    const response = await GET(request());
    assert.equal(response.status, status >= 500 ? 502 : status);
    assert.equal(calls.length, 1);
    assert(!JSON.stringify(await response.json()).includes("private"));
  }
  authStatus = 200;
  mismatched = true;
  calls = [];
  assert.equal((await GET(request())).status, 502);
  assert.equal(calls.length, 1);
});

test("usage normalizes Decimal scientific and zero values without floating point loss", async () => {
  for (const [raw, expected] of [
    ["0", "0.00000000"],
    ["0E-8", "0.00000000"],
    ["1E-8", "0.00000001"],
    ["1.2E+2", "120.00000000"],
    ["9007199254740993.12345678", "9007199254740993.12345678"],
    ["0001.25000000", "1.25000000"],
  ]) {
    value.estimated_cost_usd = raw;
    const response = await GET(request());
    assert.equal(response.status, 200, raw);
    assert.equal((await response.json()).estimatedCostUsd, expected);
  }
  value = {
    records: 0,
    input_tokens: 0,
    output_tokens: 0,
    estimated_cost_usd: "0E-8",
  };
  const response = await GET(request());
  assert.equal(response.status, 200);
  assert.equal((await response.json()).records, 0);
});

test("usage fails closed on invalid money, unsafe integers and malformed source data", async () => {
  for (const bad of [-1, 0.5, Number.MAX_SAFE_INTEGER + 1, "1", null]) {
    for (const key of ["records", "input_tokens", "output_tokens"]) {
      const original = value[key];
      value[key] = bad;
      assert.equal((await GET(request())).status, 502, key);
      value[key] = original;
    }
  }
  for (const bad of [
    1,
    null,
    "",
    "-1",
    "NaN",
    "Infinity",
    " 1",
    "+1",
    "1.000000001",
    "1E-9",
    "1E+99",
    "1".repeat(65),
  ]) {
    value.estimated_cost_usd = bad;
    const response = await GET(request());
    assert.equal(response.status, 502, String(bad));
    assert(!JSON.stringify(await response.json()).includes("private"));
  }
});

test("usage source failures stay explicit and missing or public origins never receive requests", async () => {
  for (const status of [401, 403, 404, 429, 503]) {
    sourceStatus = status;
    const response = await GET(request());
    assert.equal(response.status, status >= 500 ? 502 : status);
    assert(!JSON.stringify(await response.json()).includes("private"));
  }
  const original = process.env.DASHBOARD_AGENT_ORIGIN;
  try {
    for (const target of [undefined, "https://example.com"]) {
      if (target === undefined)
        Reflect.deleteProperty(process.env, "DASHBOARD_AGENT_ORIGIN");
      else process.env.DASHBOARD_AGENT_ORIGIN = target;
      calls = [];
      assert.equal((await GET(request())).status, 503);
      assert.equal(calls.length, 1);
    }
  } finally {
    process.env.DASHBOARD_AGENT_ORIGIN = original;
  }
});
