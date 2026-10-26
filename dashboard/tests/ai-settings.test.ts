import assert from "node:assert/strict";
import http from "node:http";
import { after, before, beforeEach, test } from "node:test";
import { NextRequest } from "next/server.js";
import { GET, PUT } from "../app/api/ai-settings/route.ts";

const tenant = "00000000-0000-4000-8000-000000000001",
  bot = "00000000-0000-4000-8000-000000000002";
const browser = "http://127.0.0.1:3000",
  query = `tenant=${tenant}&bot=${bot}`;
let calls: { path: string; method: string; body?: unknown }[] = [];
let value: unknown,
  role = "owner",
  authStatus = 200,
  sourceStatus = 200;
const server = http.createServer(async (req, res) => {
  const path = req.url || "",
    call: { path: string; method: string; body?: unknown } = {
      path,
      method: req.method || "",
    };
  calls.push(call);
  assert.equal(req.headers.authorization, "Bearer synthetic-settings");
  res.setHeader("Content-Type", "application/json");
  if (!path.endsWith("/ai/settings")) {
    assert.equal(path, `/api/v1/tenants/${tenant}`);
    assert.equal(req.method, "GET");
    res.statusCode = authStatus;
    res.end(
      JSON.stringify(
        authStatus === 200
          ? { id: tenant, name: "Settings tenant", role }
          : { private: "private-issuer" },
      ),
    );
  } else {
    assert(
      [
        `/api/v1/tenants/${tenant}/ai/settings`,
        `/api/v1/tenants/${tenant}/bots/${bot}/ai/settings`,
      ].includes(path),
    );
    assert.equal(req.headers["x-tenant-id"], tenant);
    if (req.method === "PUT") {
      const parts: Buffer[] = [];
      for await (const part of req) parts.push(part);
      call.body = JSON.parse(Buffer.concat(parts).toString());
    }
    res.statusCode = sourceStatus;
    res.end(
      JSON.stringify(
        sourceStatus === 200 ? value : { private: "private-source" },
      ),
    );
  }
});
function view(selected: string | null = bot) {
  return {
    tenant_id: tenant,
    bot_id: selected,
    target: selected ? "bot" : "tenant",
    saved: { model: null, revision: 0, updated_at: null },
    effective: { scope: "platform", provider: "groq", model: "base-model" },
    processing_enabled: false,
    api_key: "private-key",
    updated_by: "private-actor",
  };
}
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
  value = view();
  role = "owner";
  authStatus = sourceStatus = 200;
});
function request(
  params = query,
  method = "GET",
  raw?: string,
  headers: Record<string, string> = {},
) {
  return new NextRequest(`${browser}/api/ai-settings?${params}`, {
    method,
    headers: {
      host: "127.0.0.1:3000",
      origin: browser,
      cookie: "nexus_session=synthetic-settings",
      "Content-Type": "application/json",
      ...headers,
    },
    ...(raw !== undefined ? { body: raw } : {}),
  });
}
const payload = JSON.stringify({ model: "chosen-model", expectedRevision: 0 });

test("settings reads tenant and bot with safe saved/effective projection", async () => {
  for (const selected of [null, bot]) {
    value = view(selected);
    const response = await GET(request(selected ? query : `tenant=${tenant}`));
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("cache-control"), "private, no-store");
    const data = await response.json();
    assert.equal(data.bot, selected);
    assert.equal(data.saved.revision, 0);
    assert.equal(data.effective.model, "base-model");
    assert(!JSON.stringify(data).includes("private"));
  }
  assert(calls.every((x) => x.method === "GET"));
});

test("settings PUT forwards one strict scoped versioned write after fresh owner authorization", async () => {
  value = {
    ...view(),
    saved: {
      model: "chosen-model",
      revision: 1,
      updated_at: "2026-10-26T09:00:00+03:00",
    },
    effective: { scope: "bot", provider: "groq", model: "chosen-model" },
  };
  const response = await PUT(request(query, "PUT", payload));
  assert.equal(response.status, 200);
  const data = await response.json();
  assert.equal(data.saved.updatedAt, "2026-10-26T06:00:00.000Z");
  assert.deepEqual(
    calls.map((x) => x.method),
    ["GET", "PUT"],
  );
  assert.deepEqual(calls[1].body, {
    model: "chosen-model",
    expected_revision: 0,
  });
  calls = [];
  value = {
    ...view(null),
    saved: { model: null, revision: 2, updated_at: "2026-10-26T06:00:00Z" },
  };
  assert.equal(
    (
      await PUT(
        request(
          `tenant=${tenant}`,
          "PUT",
          JSON.stringify({ model: null, expectedRevision: 1 }),
        ),
      )
    ).status,
    200,
  );
  assert.deepEqual(calls[1].body, { model: null, expected_revision: 1 });
});

test("settings rejects CSRF, Host, identity and malformed scope before upstream calls", async () => {
  for (const params of [
    "",
    `${query}&tenant=${tenant}`,
    `${query}&bot=${bot}`,
    `${query}&model=x`,
    `tenant=${tenant}&bot=`,
    query.replace(bot, "bad"),
  ]) {
    assert.equal((await GET(request(params))).status, 400);
    assert.equal(calls.length, 0);
  }
  for (const headers of [
    { origin: "https://attacker.invalid" },
    { origin: "" },
    { host: "attacker.invalid" },
  ] as Record<string, string>[]) {
    assert.equal(
      (await PUT(request(query, "PUT", payload, headers))).status,
      403,
    );
  }
  assert.equal(
    (await PUT(request(query, "PUT", payload, { cookie: "" }))).status,
    401,
  );
  assert.equal(calls.length, 0);
});

test("settings rejects duplicate, extra, invalid and oversized body fields before authorization", async () => {
  for (const raw of [
    "null",
    "[]",
    "{}",
    '{"model":"a","model":"b","expectedRevision":0}',
    JSON.stringify({
      model: "a",
      expectedRevision: 0,
      processingEnabled: true,
    }),
    JSON.stringify({ model: "a", expectedRevision: true }),
    JSON.stringify({ model: "a", expectedRevision: -1 }),
    JSON.stringify({ model: "a", expectedRevision: 2147483647 }),
    JSON.stringify({ model: "", expectedRevision: 0 }),
    JSON.stringify({ model: "a\n", expectedRevision: 0 }),
    JSON.stringify({ model: "a".repeat(129), expectedRevision: 0 }),
    JSON.stringify({ model: "модель", expectedRevision: 0 }),
    '{"model":NaN,"expectedRevision":0}',
    "x".repeat(16385),
  ]) {
    assert.equal(
      (await PUT(request(query, "PUT", raw))).status,
      400,
      raw.slice(0, 80),
    );
    assert.equal(calls.length, 0);
  }
  assert.equal(
    (
      await PUT(
        request(query, "PUT", payload, { "Content-Type": "text/plain" }),
      )
    ).status,
    400,
  );
  value = {
    ...view(),
    saved: {
      model: "chosen-model",
      revision: 1,
      updated_at: "2026-10-26T06:00:00Z",
    },
    effective: { scope: "bot", provider: "groq", model: "chosen-model" },
  };
  assert.equal(
    (
      await PUT(
        request(
          query,
          "PUT",
          '{"mo\\u0064el":"chosen-model","expectedRevision":0}',
        ),
      )
    ).status,
    200,
  );
});

test("settings membership and role are fresh; member PUT and revoked identity never reach Agent", async () => {
  role = "member";
  assert.equal((await GET(request())).status, 200);
  calls = [];
  assert.equal((await PUT(request(query, "PUT", payload))).status, 403);
  assert.equal(calls.length, 1);
  role = "owner";
  for (const status of [401, 403, 404, 503]) {
    authStatus = status;
    calls = [];
    assert.equal(
      (await PUT(request(query, "PUT", payload))).status,
      status >= 500 ? 502 : status,
    );
    assert.equal(calls.length, 1);
  }
});

test("settings conflict and uncertain failures are bounded and never retried or reported as success", async () => {
  for (const status of [400, 401, 403, 404, 409, 429, 503]) {
    sourceStatus = status;
    calls = [];
    const response = await PUT(request(query, "PUT", payload));
    assert.equal(response.status, status >= 500 ? 502 : status);
    assert.equal(calls.filter((x) => x.method === "PUT").length, 1);
    assert(!JSON.stringify(await response.json()).includes("private"));
  }
});

test("settings PUT requires an acknowledgement of the exact model and next revision", async () => {
  for (const patch of [
    {
      saved: { model: null, revision: 0, updated_at: null },
      effective: { scope: "platform", provider: "groq", model: "base-model" },
    },
    {
      saved: {
        model: "other-model",
        revision: 1,
        updated_at: "2026-10-26T06:00:00Z",
      },
      effective: { scope: "bot", provider: "groq", model: "other-model" },
    },
    {
      saved: {
        model: "chosen-model",
        revision: 2,
        updated_at: "2026-10-26T06:00:00Z",
      },
      effective: { scope: "bot", provider: "groq", model: "chosen-model" },
    },
  ]) {
    value = { ...view(), ...patch };
    calls = [];
    assert.equal((await PUT(request(query, "PUT", payload))).status, 502);
    assert.equal(calls.filter((x) => x.method === "PUT").length, 1);
  }
  value = {
    ...view(),
    effective: { scope: "bot", provider: "groq", model: "invented-bot-model" },
  };
  assert.equal((await GET(request())).status, 502);
});

test("settings validates scope, inheritance and revision consistency on every source response", async () => {
  for (const patch of [
    { tenant_id: bot },
    { bot_id: tenant },
    { target: "tenant" },
    { saved: { model: "", revision: 0, updated_at: null } },
    { saved: { model: "a", revision: 0, updated_at: null } },
    { saved: { model: null, revision: 1, updated_at: null } },
    { saved: { model: null, revision: -1, updated_at: null } },
    { saved: { model: null, revision: "0", updated_at: null } },
    { saved: { model: null, revision: 1, updated_at: "2026-02-30T01:00:00Z" } },
    { effective: { scope: "future", provider: "groq", model: "a" } },
    { effective: { scope: ["platform"], provider: "groq", model: "a" } },
    { effective: { scope: "bot", provider: "groq", model: null } },
    { effective: { scope: "platform", provider: "openai", model: "a" } },
    { processing_enabled: "false" },
  ]) {
    value = { ...view(), ...patch };
    assert.equal((await GET(request())).status, 502);
  }
  value = {
    ...view(null),
    effective: { scope: "bot", provider: "groq", model: "a" },
  };
  assert.equal((await GET(request(`tenant=${tenant}`))).status, 502);
});
