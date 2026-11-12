import assert from "node:assert/strict";
import http from "node:http";
import { after, before, beforeEach, test } from "node:test";
import { NextRequest } from "next/server.js";
import { POST } from "../app/api/bot-webhook-setup/route.ts";

const browser = "http://127.0.0.1:3000";
const tenant = "00000000-0000-4000-8000-000000000001";
const bot = "00000000-0000-4000-8000-000000000002";
let role = "owner",
  issuerStatus = 200,
  webhookStatus = 200;
let acknowledgement: Record<string, unknown>;
let calls: { method: string; path: string; body: string }[] = [];
const server = http.createServer((req, res) => {
  let body = "";
  req.on("data", (chunk) => {
    body += chunk;
  });
  req.on("end", () => {
    calls.push({ method: req.method || "", path: req.url || "", body });
    res.setHeader("Content-Type", "application/json");
    if (req.method === "GET") {
      res.statusCode = issuerStatus;
      return res.end(JSON.stringify({ id: tenant, name: "Synthetic", role }));
    }
    assert.equal(req.headers["x-tenant-id"], tenant);
    res.statusCode = webhookStatus;
    res.end(JSON.stringify(acknowledgement));
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
  acknowledgement = {
    tenant_id: tenant,
    bot_id: bot,
    webhook_url: `https://example.com/webhooks/telegram/${bot}`,
    webhook_status: "configured",
    secret: "private-value",
  };
});
after(async () => {
  server.closeAllConnections();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});
let counter = 0;
function request(
  query = `tenant=${tenant}&bot=${bot}`,
  headers: Record<string, string> = {},
) {
  counter += 1;
  return new NextRequest(`${browser}/api/bot-webhook-setup?${query}`, {
    method: "POST",
    body: "{}",
    headers: {
      host: "127.0.0.1:3000",
      origin: browser,
      cookie: `nexus_session=token-${counter}`,
      "content-type": "application/json",
      ...headers,
    },
  });
}

test("owner setup sends only dry_run=false and returns no URL or secrets", async () => {
  const response = await POST(request());
  const text = await response.text();
  assert.equal(response.status, 200);
  assert.deepEqual(JSON.parse(text), { webhookStatus: "configured" });
  assert(!text.includes("example.com"));
  assert(!text.includes("private-value"));
  assert.deepEqual(
    calls.map((x) => x.method),
    ["GET", "POST"],
  );
  assert.equal(calls[1].path, `/api/v1/tenants/${tenant}/bots/${bot}/webhook`);
  assert.deepEqual(JSON.parse(calls[1].body), { dry_run: false });
});

test("setup requires an explicit empty JSON body", async () => {
  const req = new NextRequest(
    `${browser}/api/bot-webhook-setup?tenant=${tenant}&bot=${bot}`,
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

test("member, issuer denial, bad origin and invalid scopes never apply", async () => {
  role = "member";
  assert.equal((await POST(request())).status, 403);
  assert.equal(calls.filter((x) => x.method === "POST").length, 0);
  role = "owner";
  issuerStatus = 403;
  calls = [];
  assert.equal((await POST(request())).status, 403);
  assert.equal(calls.filter((x) => x.method === "POST").length, 0);
  issuerStatus = 200;
  calls = [];
  for (const req of [
    request(`tenant=${tenant}&bot=${bot}`, {
      origin: "http://127.0.0.1:3001",
    }),
    request(`tenant=${tenant}&bot=${bot}&bot=${bot}`),
    request(`tenant=${tenant}&bot=invalid`),
    request(`tenant=${tenant}&bot=${bot}&dry_run=false`),
  ])
    assert([400, 403].includes((await POST(req)).status));
  assert.equal(calls.filter((x) => x.method === "POST").length, 0);
});

test("issuer statuses map exactly and unconfirmed outcomes fail closed", async () => {
  const cases: [number, number][] = [
    [400, 400],
    [403, 403],
    [404, 404],
    [409, 409],
    [502, 502],
    [503, 502],
  ];
  for (const [upstream, expected] of cases) {
    calls = [];
    webhookStatus = upstream;
    assert.equal((await POST(request())).status, expected);
    assert.equal(calls.filter((x) => x.method === "POST").length, 1);
  }
});

test("malformed or mismatched acknowledgements fail closed", async () => {
  for (const patch of [
    { tenant_id: bot },
    { bot_id: tenant },
    { webhook_status: "failed" },
    { webhook_url: "http://example.com/webhooks/telegram/" + bot },
    { webhook_url: "https://example.com/other" },
    { webhook_url: `https://example.com/webhooks/telegram/${bot}?x=1` },
    { webhook_url: `https://user:pass@example.com/webhooks/telegram/${bot}` },
  ]) {
    calls = [];
    webhookStatus = 200;
    acknowledgement = { ...acknowledgement, ...patch };
    assert.equal((await POST(request())).status, 502);
  }
});

test("the credential and bot limiter rejects the sixth attempt without an upstream call", async () => {
  calls = [];
  const token = "limit-token";
  const raw = (): NextRequest =>
    new NextRequest(
      `${browser}/api/bot-webhook-setup?tenant=${tenant}&bot=${bot}`,
      {
        method: "POST",
        body: "{}",
        headers: {
          host: "127.0.0.1:3000",
          origin: browser,
          cookie: `nexus_session=${token}`,
          "content-type": "application/json",
        },
      },
    );
  for (let attempt = 0; attempt < 5; attempt += 1)
    assert.equal((await POST(raw())).status, 200);
  assert.equal(calls.filter((x) => x.method === "POST").length, 5);
  assert.equal((await POST(raw())).status, 429);
  assert.equal(calls.filter((x) => x.method === "POST").length, 5);
});
