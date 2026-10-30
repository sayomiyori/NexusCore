import assert from "node:assert/strict";
import http from "node:http";
import { after, before, beforeEach, test } from "node:test";
import { NextRequest } from "next/server.js";
import { POST } from "../app/api/bot-registration/route.ts";

const browser = "http://127.0.0.1:3000";
const tenant = "00000000-0000-4000-8000-000000000001";
const bot = "00000000-0000-4000-8000-000000000002";
const token = "1:test";
let role = "owner",
  issuerStatus = 200,
  upstreamStatus = 201,
  dropAcknowledgement = false;
let issuerTenant = tenant;
let acknowledgement: Record<string, unknown>;
let calls: { method: string; path: string; body: string }[] = [];
const server = http.createServer((req, res) => {
  let body = "";
  req.on("data", (chunk) => {
    body += chunk;
  });
  req.on("end", () => {
    calls.push({ method: req.method || "", path: req.url || "", body });
    assert.equal(req.headers.authorization, "Bearer synthetic-access");
    res.setHeader("Content-Type", "application/json");
    if (req.method === "GET") {
      res.statusCode = issuerStatus;
      return res.end(
        JSON.stringify({ id: issuerTenant, name: "Tenant", role }),
      );
    }
    assert.equal(req.headers["x-tenant-id"], tenant);
    if (dropAcknowledgement) {
      req.socket.destroy();
      return;
    }
    res.statusCode = upstreamStatus;
    res.end(JSON.stringify(acknowledgement));
  });
});
before(async () => {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert(address && typeof address === "object");
  const origin = `http://127.0.0.1:${address.port}`;
  Object.assign(process.env, {
    DASHBOARD_ORIGIN: browser,
    DASHBOARD_AUTH_ORIGIN: origin,
    DASHBOARD_WEBHOOK_ORIGIN: origin,
  });
});
beforeEach(() => {
  calls = [];
  role = "owner";
  issuerStatus = 200;
  upstreamStatus = 201;
  dropAcknowledgement = false;
  issuerTenant = tenant;
  acknowledgement = {
    id: bot,
    tenant_id: tenant,
    name: "Support",
    is_active: true,
    webhook_status: "not_configured",
    created_at: "2026-10-29T10:00:00Z",
    updated_at: "2026-10-29T10:00:00Z",
    unexpected_field: "sentinel-value",
  };
});
after(async () => {
  server.closeAllConnections();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});
function request(
  body: string,
  query = `tenant=${tenant}`,
  headers: Record<string, string> = {},
) {
  return new NextRequest(`${browser}/api/bot-registration?${query}`, {
    method: "POST",
    body,
    headers: {
      host: "127.0.0.1:3000",
      origin: browser,
      cookie: "nexus_session=synthetic-access",
      "content-type": "application/json",
      ...headers,
    },
  });
}
const valid = () => JSON.stringify({ name: " Support ", token });

test("owner registration returns only safe acknowledged metadata and posts once", async () => {
  const response = await POST(request(valid()));
  const result = await response.json();
  assert.equal(response.status, 201);
  assert.equal(result.bot.name, "Support");
  assert.equal(result.bot.id, bot);
  assert(!JSON.stringify(result).includes(token));
  assert(!JSON.stringify(result).includes("sentinel-value"));
  assert.deepEqual(
    calls.map((x) => x.method),
    ["GET", "POST"],
  );
  assert.equal(calls[1].path, `/api/v1/tenants/${tenant}/bots`);
  assert.deepEqual(JSON.parse(calls[1].body), { name: "Support", token });
});

test("member, revoked identity, foreign origin, invalid scopes and inputs never post", async () => {
  role = "member";
  assert.equal((await POST(request(valid()))).status, 403);
  assert.equal(calls.filter((x) => x.method === "POST").length, 0);
  role = "owner";
  issuerStatus = 403;
  calls = [];
  assert.equal((await POST(request(valid()))).status, 403);
  assert.equal(calls.filter((x) => x.method === "POST").length, 0);
  issuerStatus = 200;
  issuerTenant = bot;
  calls = [];
  assert.equal((await POST(request(valid()))).status, 502);
  assert.equal(calls.filter((x) => x.method === "POST").length, 0);
  calls = [];
  for (const req of [
    request(valid(), `tenant=${tenant}`, { origin: "http://127.0.0.1:3001" }),
    request(valid(), `tenant=${tenant}&tenant=${tenant}`),
    request('{"name":"A","token":"1:a","token":"2:b"}'),
    request(JSON.stringify({ name: "", token })),
    request(JSON.stringify({ name: "X", token: "invalid" })),
    request(JSON.stringify({ name: "X", token, extra: true })),
  ]) {
    assert([400, 403].includes((await POST(req)).status));
  }
  assert.equal(calls.length, 0);
});

test("unexpected status, mismatched acknowledgement and upstream errors never claim success or leak", async () => {
  for (const status of [200, 204, 400, 401, 403, 404, 409, 422, 429, 503]) {
    calls = [];
    upstreamStatus = status;
    const response = await POST(request(valid()));
    assert.equal(
      response.status,
      [200, 204, 422, 503].includes(status) ? 502 : status,
    );
    assert(!JSON.stringify(await response.json()).includes("sentinel-value"));
    assert.equal(calls.filter((x) => x.method === "POST").length, 1);
  }
  upstreamStatus = 201;
  for (const patch of [
    { tenant_id: bot },
    { name: "Other" },
    { is_active: false },
    { webhook_status: "configured" },
    { id: "not-a-uuid" },
  ]) {
    calls = [];
    const previous = acknowledgement;
    acknowledgement = { ...previous, ...patch };
    assert.equal((await POST(request(valid()))).status, 502);
    assert.equal(calls.filter((x) => x.method === "POST").length, 1);
    acknowledgement = previous;
  }
});

test("lost acknowledgement is unconfirmed and never automatically retried", async () => {
  dropAcknowledgement = true;
  const response = await POST(request(valid()));
  assert.equal(response.status, 502);
  assert.equal(calls.filter((call) => call.method === "POST").length, 1);
  assert(!JSON.stringify(await response.json()).includes(token));
});
