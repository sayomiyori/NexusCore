import assert from "node:assert/strict";
import http from "node:http";
import { after, before, beforeEach, test } from "node:test";
import { NextRequest } from "next/server.js";
import { GET } from "../app/api/jobs/route.ts";

const id = (n: number) =>
  `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;
const tenant = id(1),
  bot = id(2),
  browser = "http://127.0.0.1:3000",
  query = `tenant=${tenant}&bot=${bot}`;
const row = (n = 1000) => ({
  id: id(n),
  event_id: id(n + 10000),
  state: "completed",
  attempts: 0,
  provider: "private-provider",
  model: "private-model",
  answer: "private-answer",
  created_at: "2026-10-25T12:34:00+03:00",
  updated_at: "2026-10-25T09:35:00Z",
});
let calls: { path: string; method: string }[] = [];
let value: unknown,
  authStatus = 200,
  sourceStatus = 200,
  role = "owner",
  mismatched = false;
const server = http.createServer((req, res) => {
  const path = req.url || "";
  calls.push({ path, method: req.method || "" });
  assert.equal(req.headers.authorization, "Bearer synthetic-jobs");
  res.setHeader("Content-Type", "application/json");
  if (!path.includes("/ai/jobs")) {
    assert.equal(path, `/api/v1/tenants/${tenant}`);
    res.statusCode = authStatus;
    res.end(
      JSON.stringify(
        authStatus === 200
          ? { id: mismatched ? bot : tenant, name: "Jobs tenant", role }
          : { private: "private-issuer-error" },
      ),
    );
  } else {
    assert(
      path.startsWith(`/api/v1/tenants/${tenant}/bots/${bot}/ai/jobs?limit=50`),
    );
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
  value = { items: [row()], next_cursor: null };
  authStatus = sourceStatus = 200;
  role = "owner";
  mismatched = false;
});
function request(params = query, headers: Record<string, string> = {}) {
  return new NextRequest(`${browser}/api/jobs?${params}`, {
    headers: {
      host: "127.0.0.1:3000",
      cookie: "nexus_session=synthetic-jobs",
      ...headers,
    },
  });
}

test("jobs projects safe metadata with normalized UTC and GET-only authorized source reads", async () => {
  const response = await GET(request());
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "private, no-store");
  assert.deepEqual(await response.json(), {
    tenant: { id: tenant, name: "Jobs tenant", role: "owner" },
    bot,
    items: [
      {
        id: id(1000),
        eventId: id(11000),
        state: "completed",
        attempts: 0,
        created: "2026-10-25T09:34:00.000Z",
        updated: "2026-10-25T09:35:00.000Z",
      },
    ],
    nextCursor: null,
  });
  assert(calls.every((call) => call.method === "GET"));
  assert.equal(calls[0].path, `/api/v1/tenants/${tenant}`);
});

test("jobs preserves limit-plus-one cursor semantics for full final pages and continuation", async () => {
  const items = Array.from({ length: 50 }, (_, index) => row(1000 + index));
  value = { items, next_cursor: id(1049) };
  let response = await GET(request());
  assert.equal(response.status, 200);
  assert.equal((await response.json()).nextCursor, id(1049));
  value = { items, next_cursor: null };
  response = await GET(request());
  assert.equal(response.status, 200);
  assert.equal((await response.json()).nextCursor, null);
  value = { items: [row(1050), row(1051)], next_cursor: null };
  response = await GET(request(`${query}&cursor=${id(1049)}`));
  assert.equal(response.status, 200);
  assert.equal((await response.json()).items.length, 2);
  assert(calls.at(-1)?.path.endsWith(`limit=50&cursor=${id(1049)}`));
  value = { items: [], next_cursor: null };
  response = await GET(request(`${query}&cursor=${id(1051)}`));
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).items, []);
});

test("jobs rejects malformed, duplicate, out-of-order and invalid-cursor pages without partial data", async () => {
  const full = Array.from({ length: 50 }, (_, index) => row(1000 + index));
  for (const bad of [
    null,
    [],
    {},
    { items: null, next_cursor: null },
    { items: [row()] },
    {
      items: Array.from({ length: 51 }, (_, index) => row(1000 + index)),
      next_cursor: null,
    },
    { items: [row(), row()], next_cursor: null },
    { items: [row(1001), row(1000)], next_cursor: null },
    {
      items: [row(), { ...row(1001), event_id: id(11000) }],
      next_cursor: null,
    },
    { items: [row()], next_cursor: id(1000) },
    { items: full, next_cursor: id(1050) },
    { items: full, next_cursor: "private-invalid" },
  ]) {
    value = bad;
    const response = await GET(request());
    assert.equal(response.status, 502);
    assert(!JSON.stringify(await response.json()).includes("private"));
  }
  value = { items: [row(1000)], next_cursor: null };
  assert.equal((await GET(request(`${query}&cursor=${id(1000)}`))).status, 502);
  for (const patch of [
    { state: "inactive" },
    { state: null },
    { attempts: -1 },
    { attempts: "1" },
    { attempts: 0.5 },
    { attempts: 2147483648 },
    { id: "bad" },
    { event_id: null },
    { created_at: "invalid" },
    { updated_at: "2026-10-25T00:00:00" },
    { created_at: "2026-02-30T12:34:00Z" },
    { updated_at: "2026-04-31T12:34:00Z" },
  ]) {
    value = { items: [{ ...row(), ...patch }], next_cursor: null };
    assert.equal((await GET(request())).status, 502);
  }
});

test("jobs validates scope, cursor, Host and session before any upstream call", async () => {
  for (const bad of [
    "",
    `tenant=${tenant}`,
    `${query}&bot=${bot}`,
    `${query}&tenant=${tenant}`,
    `${query}&cursor=`,
    `${query}&cursor=${id(3)}&cursor=${id(4)}`,
    `${query}&limit=100`,
    `${query}&cursor=UPPERCASE`,
    query.replace(bot, "invalid"),
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

test("jobs repeats owner/member authorization and blocks source reads after issuer denial", async () => {
  for (const current of ["owner", "member"]) {
    role = current;
    const response = await GET(request());
    assert.equal(response.status, 200);
    assert.equal((await response.json()).tenant.role, current);
  }
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

test("jobs source failures and invalid origins never turn into empty metadata success", async () => {
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
