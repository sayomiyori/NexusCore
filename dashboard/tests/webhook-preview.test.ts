import assert from "node:assert/strict";
import http from "node:http";
import { after, before, beforeEach, test } from "node:test";
import { NextRequest } from "next/server.js";
import { POST } from "../app/api/bot-webhook-preview/route.ts";

const browser = "http://127.0.0.1:3000";
const tenant = "00000000-0000-4000-8000-000000000001";
const bot = "00000000-0000-4000-8000-000000000002";
let role = "owner",
  issuerStatus = 200,
  webhookStatus = 200;
let result: Record<string, unknown>;
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
      return res.end(JSON.stringify({ id: tenant, name: "Synthetic", role }));
    }
    assert.equal(req.headers["x-tenant-id"], tenant);
    res.statusCode = webhookStatus;
    res.end(JSON.stringify(result));
  });
});
before(async () => {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert(address && typeof address === "object");
  const base = `http://127.0.0.1:${address.port}`;
  Object.assign(process.env, {
    DASHBOARD_ORIGIN: browser,
    DASHBOARD_AUTH_ORIGIN: base,
    DASHBOARD_WEBHOOK_ORIGIN: base,
  });
});
beforeEach(() => {
  calls = [];
  role = "owner";
  issuerStatus = webhookStatus = 200;
  result = {
    tenant_id: tenant,
    bot_id: bot,
    operation: "setWebhook",
    dry_run: true,
    webhook_url: `https://example.com/webhooks/telegram/${bot}`,
    secret: "private-value",
  };
});
after(async () => {
  server.closeAllConnections();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});
function request(
  query = `tenant=${tenant}&bot=${bot}`,
  headers: Record<string, string> = {},
) {
  return new NextRequest(`${browser}/api/bot-webhook-preview?${query}`, {
    method: "POST",
    body: "{}",
    headers: {
      host: "127.0.0.1:3000",
      origin: browser,
      cookie: "nexus_session=synthetic-access",
      "content-type": "application/json",
      ...headers,
    },
  });
}
test("owner preview sends only dry_run and returns no URL or secrets", async () => {
  const response = await POST(request());
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.deepEqual(body, { bot, ready: true });
  assert.deepEqual(
    calls.map((x) => x.method),
    ["GET", "POST"],
  );
  assert.equal(calls[1].path, `/api/v1/tenants/${tenant}/bots/${bot}/webhook`);
  assert.deepEqual(JSON.parse(calls[1].body), { dry_run: true });
});

test("preview requires an explicit empty JSON body", async () => {
  const req = new NextRequest(
    `${browser}/api/bot-webhook-preview?tenant=${tenant}&bot=${bot}`,
    {
      method: "POST",
      headers: {
        host: "127.0.0.1:3000",
        origin: browser,
        cookie: "nexus_session=synthetic-access",
      },
    },
  );
  assert.equal((await POST(req)).status, 400);
  assert.equal(calls.length, 0);
});
test("member, issuer denial, bad origin and invalid scopes cannot reach webhook", async () => {
  role = "member";
  assert.equal((await POST(request())).status, 403);
  assert.equal(calls.length, 1);
  role = "owner";
  issuerStatus = 403;
  calls = [];
  assert.equal((await POST(request())).status, 403);
  assert.equal(calls.length, 1);
  calls = [];
  for (const req of [
    request(`tenant=${tenant}&bot=${bot}`, { origin: "http://127.0.0.1:3001" }),
    request(`tenant=${tenant}&bot=${bot}&bot=${bot}`),
    request(`tenant=${tenant}&bot=invalid`),
    request(`tenant=${tenant}&bot=${bot}&dry_run=false`),
  ])
    assert([400, 403].includes((await POST(req)).status));
  const malicious = new NextRequest(
    `${browser}/api/bot-webhook-preview?tenant=${tenant}&bot=${bot}`,
    {
      method: "POST",
      headers: {
        host: "127.0.0.1:3000",
        origin: browser,
        cookie: "nexus_session=synthetic-access",
        "content-type": "application/json",
      },
      body: '{"dry_run":false}',
    },
  );
  assert.equal((await POST(malicious)).status, 400);
  assert.equal(calls.length, 0);
});
test("unsafe or mismatched preview response fails closed and never retries", async () => {
  const original = result;
  for (const patch of [
    { tenant_id: bot },
    { bot_id: tenant },
    { dry_run: false },
    { operation: "other" },
    { webhook_url: "http://example.com/" },
    {
      webhook_url: `https://example.com/webhooks/telegram/${bot}?secret=private`,
    },
    { webhook_url: `https://example.com/webhooks/telegram/${bot}?` },
    { webhook_url: `https://example.com/webhooks/telegram/${bot}#` },
  ]) {
    calls = [];
    result = { ...original, ...patch };
    const response = await POST(request());
    assert.equal(response.status, 502);
    assert(!JSON.stringify(await response.json()).includes("private"));
    assert.equal(calls.filter((x) => x.method === "POST").length, 1);
  }
  calls = [];
  webhookStatus = 503;
  assert.equal((await POST(request())).status, 502);
  assert.equal(calls.filter((x) => x.method === "POST").length, 1);
});
