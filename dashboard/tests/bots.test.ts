import assert from "node:assert/strict";
import http from "node:http";
import { after, before, beforeEach, test } from "node:test";
import { NextRequest } from "next/server.js";
import { GET } from "../app/api/bots/route.ts";

const tenant = "00000000-0000-4000-8000-000000000001";
const foreign = "00000000-0000-4000-8000-000000000002";
const browser = "http://127.0.0.1:3000";
const id = (index: number) =>
  `00000000-0000-4000-8000-${index.toString(16).padStart(12, "0")}`;
const bot = (index = 100) => ({
  id: id(index),
  tenant_id: tenant,
  name: "<img src=x onerror=alert(1)>",
  is_active: false,
  webhook_status: "configured",
  created_at: "2026-10-23T09:00:00+00:00",
  updated_at: "2026-10-25T09:00:00+00:00",
  unexpected_field: "sentinel-value",
});
let page: unknown;
let authStatus = 200,
  serviceStatus = 200,
  authTenant = tenant;
let calls: { path: string; method: string; tenant: string | undefined }[] = [];
let base = "";
const server = http.createServer((req, res) => {
  const path = req.url || "";
  calls.push({
    path,
    method: req.method || "",
    tenant: req.headers["x-tenant-id"] as string | undefined,
  });
  assert.equal(req.method, "GET");
  assert.equal(req.headers.authorization, "Bearer synthetic-access");
  res.setHeader("Content-Type", "application/json");
  if (path.includes("/bots?")) {
    assert.equal(req.headers["x-tenant-id"], tenant);
    assert(path.startsWith(`/api/v1/tenants/${tenant}/bots?limit=50`));
    res.statusCode = serviceStatus;
    res.end(
      JSON.stringify(
        serviceStatus === 200 ? page : { error: "private-upstream-error" },
      ),
    );
  } else {
    assert.equal(path, `/api/v1/tenants/${tenant}`);
    res.statusCode = authStatus;
    res.end(
      JSON.stringify(
        authStatus === 200
          ? { id: authTenant, name: "Synthetic organization", role: "member" }
          : { error: "private-upstream-error" },
      ),
    );
  }
});
before(async () => {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert(address && typeof address === "object");
  base = `http://127.0.0.1:${address.port}`;
  Object.assign(process.env, {
    DASHBOARD_ORIGIN: browser,
    DASHBOARD_AUTH_ORIGIN: base,
    DASHBOARD_WEBHOOK_ORIGIN: base,
  });
});
beforeEach(() => {
  calls = [];
  authStatus = serviceStatus = 200;
  authTenant = tenant;
  page = { items: [bot()], next_cursor: null };
  process.env.DASHBOARD_WEBHOOK_ORIGIN = base;
});
after(async () => {
  server.closeAllConnections();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});
function request(
  query = `tenant=${tenant}`,
  headers: Record<string, string> = {},
) {
  return new NextRequest(`${browser}/api/bots?${query}`, {
    headers: {
      host: "127.0.0.1:3000",
      cookie: "nexus_session=synthetic-access",
      ...headers,
    },
  });
}

test("bots returns only scoped configuration fields through GET-only APIs", async () => {
  const response = await GET(request());
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "private, no-store");
  assert.deepEqual(await response.json(), {
    tenant: { id: tenant, name: "Synthetic organization", role: "member" },
    items: [
      {
        id: id(100),
        name: bot().name,
        active: false,
        webhook: "configured",
        created: "2026-10-23T09:00:00.000Z",
        updated: "2026-10-25T09:00:00.000Z",
      },
    ],
    nextCursor: null,
  });
  assert.equal(calls.length, 2);
  assert(calls.every((call) => call.method === "GET"));
});

test("bots follows validated UUID cursors and never invents lifetime totals", async () => {
  page = {
    items: Array.from({ length: 50 }, (_, i) => bot(100 + i)),
    next_cursor: id(149),
  };
  let response = await GET(request());
  assert.equal(response.status, 200);
  const value = await response.json();
  assert.equal(value.items.length, 50);
  assert.equal(value.nextCursor, id(149));
  assert(!("total" in value));
  page = { items: [bot(150)], next_cursor: null };
  response = await GET(request(`tenant=${tenant}&cursor=${id(149)}`));
  assert.equal(response.status, 200);
  assert.equal((await response.json()).items[0].id, id(150));
  assert.equal(
    calls.at(-1)?.path,
    `/api/v1/tenants/${tenant}/bots?limit=50&cursor=${id(149)}`,
  );
  page = { items: [], next_cursor: null };
  assert.deepEqual((await (await GET(request())).json()).items, []);
});

test("bot names use the backend Unicode code point limit", async () => {
  for (const size of [65, 128, 129]) {
    const name = "\u{1f600}".repeat(size);
    page = { items: [{ ...bot(), name }], next_cursor: null };
    const response = await GET(request());
    assert.equal(response.status, size <= 128 ? 200 : 502);
    if (size <= 128) assert.equal((await response.json()).items[0].name, name);
  }
});

test("bots rejects malformed and mixed-tenant pages without returning partial data", async () => {
  for (const invalid of [
    null,
    [],
    { items: [], next_cursor: id(100) },
    { items: [bot()] },
    {
      items: Array.from({ length: 51 }, (_, i) => bot(100 + i)),
      next_cursor: id(150),
    },
    { items: [bot(), bot()], next_cursor: null },
    { items: [bot(101), bot(100)], next_cursor: null },
    ...[
      { tenant_id: foreign },
      { id: "private-invalid-id" },
      { name: "" },
      { name: "x".repeat(129) },
      { is_active: "false" },
      { webhook_status: ["configured"] },
      { webhook_status: "new-state" },
      { created_at: "2026-10-23" },
      { updated_at: null },
    ].map((change) => ({
      items: [{ ...bot(), ...change }],
      next_cursor: null,
    })),
  ]) {
    page = invalid;
    const response = await GET(request());
    assert.equal(response.status, 502);
    assert.deepEqual(await response.json(), {
      error: "Data is temporarily unavailable.",
    });
  }
  page = { items: [bot()], next_cursor: null };
  assert.equal(
    (await GET(request(`tenant=${tenant}&cursor=${id(100)}`))).status,
    502,
  );
  page = {
    items: Array.from({ length: 50 }, (_, i) => bot(100 + i)),
    next_cursor: id(148),
  };
  assert.equal((await GET(request())).status, 502);
});

test("bots authorizes membership freshly before every resource read", async () => {
  assert.equal((await GET(request())).status, 200);
  authStatus = 403;
  assert.equal((await GET(request())).status, 403);
  assert.equal(calls.filter((call) => call.path.includes("/bots?")).length, 1);
  assert.equal(calls.filter((call) => !call.path.includes("/bots?")).length, 2);
  calls = [];
  authStatus = 200;
  authTenant = foreign;
  assert.equal((await GET(request())).status, 502);
  assert.equal(calls.length, 1);
});

test("bots rejects missing identity, wrong Host and malformed query before upstream", async () => {
  assert.equal((await GET(request(undefined, { cookie: "" }))).status, 401);
  assert.equal(
    (await GET(request(undefined, { host: "example.com" }))).status,
    403,
  );
  for (const query of [
    "",
    `tenant=${tenant}&tenant=${tenant}`,
    `tenant=${tenant}&cursor=`,
    `tenant=${tenant}&cursor=${id(100)}&cursor=${id(101)}`,
    "tenant=invalid",
    `tenant=${tenant}&limit=100`,
    `tenant=${tenant}&cursor=../private`,
    `tenant=${tenant}&offset=50`,
  ])
    assert.equal((await GET(request(query))).status, 400);
  assert.equal(calls.length, 0);
});

test("bots handles issuer and source failures with fixed safe responses", async () => {
  for (const upstream of [401, 403, 429, 503]) {
    authStatus = upstream;
    const denied = await GET(request());
    assert.equal(denied.status, upstream === 503 ? 502 : upstream);
    assert(!(await denied.text()).includes("private-"));
    authStatus = 200;
    serviceStatus = upstream;
    const source = await GET(request());
    assert.equal(source.status, upstream === 503 ? 502 : upstream);
    assert(!(await source.text()).includes("private-"));
    serviceStatus = 200;
  }
  for (const value of [undefined, "https://example.com"]) {
    if (value === undefined) delete process.env.DASHBOARD_WEBHOOK_ORIGIN;
    else process.env.DASHBOARD_WEBHOOK_ORIGIN = value;
    const count = calls.length;
    assert.equal((await GET(request())).status, 503);
    assert.equal(calls.length, count + 1);
  }
});
