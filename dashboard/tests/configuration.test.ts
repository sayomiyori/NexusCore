import assert from "node:assert/strict";
import http from "node:http";
import { after, before, beforeEach, test } from "node:test";
import { NextRequest } from "next/server.js";
import { GET } from "../app/api/configuration/route.ts";

const id = (n: number) =>
  `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;
const tenant = id(1),
  bot = id(2),
  browser = "http://127.0.0.1:3000",
  query = `tenant=${tenant}&bot=${bot}`;
let calls: { path: string; method: string }[] = [];
let value: unknown,
  authStatus = 200,
  sourceStatus = 200,
  role = "owner",
  mismatched = false;
const server = http.createServer((req, res) => {
  const path = req.url || "";
  calls.push({ path, method: req.method || "" });
  assert.equal(req.headers.authorization, "Bearer synthetic-configuration");
  res.setHeader("Content-Type", "application/json");
  if (!path.includes("/ai/configuration")) {
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
    assert(path === `/api/v1/tenants/${tenant}/bots/${bot}/ai/configuration`);
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
  value = configured();
  authStatus = sourceStatus = 200;
  role = "owner";
  mismatched = false;
});
function request(params = query, headers: Record<string, string> = {}) {
  return new NextRequest(`${browser}/api/configuration?${params}`, {
    headers: {
      host: "127.0.0.1:3000",
      cookie: "nexus_session=synthetic-configuration",
      ...headers,
    },
  });
}

function configured() {
  return {
    tenant_id: tenant,
    bot_id: bot,
    scope: "platform",
    provider: "groq",
    model: "synthetic-model",
    processing_enabled: false,
    api_key: "private-key",
    prompt: "private-prompt",
  };
}

test("configuration projects scoped shared policy with fresh GET-only resource access", async () => {
  const response = await GET(request());
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "private, no-store");
  assert.deepEqual(await response.json(), {
    tenant: { id: tenant, name: "Jobs tenant", role: "owner" },
    bot,
    scope: "platform",
    provider: "groq",
    model: "synthetic-model",
    processingEnabled: false,
  });
  assert(calls.every((call) => call.method === "GET"));
  assert.equal(calls.length, 2);
  value = { ...configured(), model: null };
  assert.equal((await (await GET(request())).json()).model, null);
  value = { ...configured(), processing_enabled: true };
  assert.equal((await (await GET(request())).json()).processingEnabled, true);
});

test("configuration rejects mismatched and malformed source fields rather than inventing defaults", async () => {
  for (const patch of [
    { tenant_id: bot },
    { bot_id: tenant },
    { scope: "bot" },
    { provider: "openai" },
    { model: "" },
    { model: "a".repeat(129) },
    { model: "private\nkey" },
    { model: "<script>" },
    { model: "model?api_key=private" },
    { model: "модель" },
    { model: 1 },
    { model: undefined },
    { processing_enabled: "false" },
    { processing_enabled: null },
    { scope: undefined },
  ]) {
    value = { ...configured(), ...patch };
    const response = await GET(request());
    assert.equal(response.status, 502, JSON.stringify(patch));
    assert(!JSON.stringify(await response.json()).includes("private"));
  }
  for (const invalid of [null, [], {}]) {
    value = invalid;
    assert.equal((await GET(request())).status, 502);
  }
});

test("configuration guards scope, duplicate/extra fields, Host and session before any call", async () => {
  for (const params of [
    "",
    `tenant=${tenant}`,
    `${query}&bot=${bot}`,
    `${query}&tenant=${tenant}`,
    `${query}&cursor=`,
    `${query}&model=x`,
    query.replace(bot, "invalid"),
  ]) {
    assert.equal((await GET(request(params))).status, 400);
    assert.equal(calls.length, 0);
  }
  assert.equal((await GET(request(query, { cookie: "" }))).status, 401);
  assert.equal(
    (await GET(request(query, { host: "attacker.invalid" }))).status,
    403,
  );
  assert.equal(calls.length, 0);
});

test("configuration repeats owner/member authorization and denies issuer loss before Agent", async () => {
  for (const current of ["owner", "member"]) {
    role = current;
    assert.equal((await GET(request())).status, 200);
  }
  for (const status of [401, 403, 404, 503]) {
    authStatus = status;
    calls = [];
    const response = await GET(request());
    assert.equal(response.status, status >= 500 ? 502 : status);
    assert.equal(calls.length, 1);
  }
  authStatus = 200;
  mismatched = true;
  calls = [];
  assert.equal((await GET(request())).status, 502);
  assert.equal(calls.length, 1);
});

test("configuration source and private origin failures never become unset success", async () => {
  for (const status of [401, 403, 404, 429, 503]) {
    sourceStatus = status;
    const response = await GET(request());
    assert.equal(response.status, status >= 500 ? 502 : status);
    assert(!JSON.stringify(await response.json()).includes("private"));
  }
  const original = process.env.DASHBOARD_AGENT_ORIGIN;
  try {
    process.env.DASHBOARD_AGENT_ORIGIN = "https://example.com";
    calls = [];
    assert.equal((await GET(request())).status, 503);
    assert.equal(calls.length, 1);
  } finally {
    process.env.DASHBOARD_AGENT_ORIGIN = original;
  }
});
