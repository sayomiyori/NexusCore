import assert from "node:assert/strict";
import http from "node:http";
import { after, before, beforeEach, test } from "node:test";
import { NextRequest } from "next/server.js";
import { GET as overview } from "../app/api/overview/route.ts";
import { DELETE, POST } from "../app/api/session/route.ts";
import { GET as tenants } from "../app/api/tenants/route.ts";
import { proxy } from "../proxy.ts";

const tenant = "00000000-0000-4000-8000-000000000001";
const bot = "00000000-0000-4000-8000-000000000002";
const eventId = "00000000-0000-4000-8000-000000000003";
const storageId = "00000000-0000-4000-8000-000000000004";
const browser = "http://127.0.0.1:3000";
const safeTenant = {
  id: tenant,
  name: "<script>private-name-sentinel</script>",
  role: "owner",
  created_at: "2026-10-21T09:00:00Z",
};
const event = {
  event_id: eventId,
  event_type: "webhook.bot.observed",
  schema_version: 1,
  occurred_at: "2026-10-23T10:00:00Z",
  tenant_id: tenant,
  bot_id: bot,
  correlation_id: bot,
  idempotency_key: eventId,
  payload: { is_active: false, webhook_status: "failed" },
};
let calls: {
  method: string;
  path: string;
  tenant?: string;
  payload: unknown;
}[] = [];
let mfa = false,
  denied = false,
  epDown = false,
  pwDown = false,
  conflict = false,
  malformed = false,
  empty = false;
let logoutDown = false,
  oversized = false,
  mismatched = false;
let tenantRows: unknown = [safeTenant];

const server = http.createServer((req, res) => {
  let raw = "";
  req.on("data", (chunk) => {
    raw += chunk;
  });
  req.on("end", () => {
    const path = req.url || "",
      method = req.method || "";
    calls.push({
      method,
      path,
      tenant: req.headers["x-tenant-id"] as string | undefined,
      payload: raw ? JSON.parse(raw) : undefined,
    });
    res.setHeader("Content-Type", "application/json");
    const send = (value: unknown, status = 200) => {
      res.statusCode = status;
      res.end(JSON.stringify(value));
    };
    if (path.endsWith("/auth/login"))
      return send(
        mfa
          ? { requires_2fa: true, temp_token: "synthetic-challenge" }
          : {
              access_token: "synthetic-access",
              refresh_token: "private-refresh-secret",
              token_type: "bearer",
            },
      );
    if (path.endsWith("/auth/login/2fa"))
      return send({
        access_token: "synthetic-access",
        refresh_token: "private-refresh-secret",
        token_type: "bearer",
      });
    if (path.endsWith("/auth/logout")) {
      res.statusCode = logoutDown ? 503 : 204;
      res.end();
      return;
    }
    assert.equal(req.headers.authorization, "Bearer synthetic-access");
    if (path.startsWith("/api/v1/tenants?")) return send(tenantRows);
    if (path.startsWith("/api/v1/tenants/"))
      return send(
        denied ? { private: "denied" } : safeTenant,
        denied ? 403 : 200,
      );
    assert.equal(req.headers["x-tenant-id"], tenant);
    if (path.startsWith("/api/v1/events?"))
      return send(
        empty
          ? []
          : [
              {
                event_id: storageId,
                source: "nexuscore",
                event_type: event.event_type,
                payload_preview: "private-preview",
              },
            ],
        epDown ? 503 : 200,
      );
    if (path === `/api/v1/events/${storageId}`)
      return send({
        event_id: storageId,
        source: "nexuscore",
        event_type: event.event_type,
        payload: mismatched
          ? { event_type: "unsupported" }
          : malformed
            ? { ...event, tenant_id: bot }
            : event,
        metadata: { relay_event_id: eventId, bot_id: bot },
        private: "private-answer-secret",
      });
    if (path.startsWith("/api/v1/logs?"))
      return send(
        {
          total: oversized ? 11 : empty ? 0 : 1,
          page: 1,
          size: 10,
          items: empty
            ? []
            : [
                {
                  service: "nexuscore",
                  trace_id: eventId,
                  message: event.event_type,
                  metadata: mismatched
                    ? { event_type: "unsupported" }
                    : conflict
                      ? {
                          ...event,
                          payload: {
                            ...event.payload,
                            webhook_status: "unknown",
                          },
                        }
                      : event,
                },
              ],
        },
        pwDown ? 503 : 200,
      );
    send({}, 404);
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
    DASHBOARD_EVENTPIPE_ORIGIN: base,
    DASHBOARD_PIPEWATCH_ORIGIN: base,
  });
});
beforeEach(() => {
  calls = [];
  tenantRows = [safeTenant];
  mfa =
    denied =
    epDown =
    pwDown =
    conflict =
    malformed =
    empty =
    logoutDown =
    oversized =
    mismatched =
      false;
});
after(async () => {
  server.closeAllConnections();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

function request(
  path: string,
  method = "GET",
  input?: unknown,
  headers: Record<string, string> = {},
) {
  return new NextRequest(browser + path, {
    method,
    headers: {
      host: "127.0.0.1:3000",
      origin: browser,
      cookie: "nexus_session=synthetic-access",
      "content-type": "application/json",
      ...headers,
    },
    ...(input === undefined ? {} : { body: JSON.stringify(input) }),
  });
}

test("login keeps access/refresh credentials out of JSON and secures production cookies", async () => {
  const original = process.env.NODE_ENV;
  Object.assign(process.env, { NODE_ENV: "production" });
  try {
    const response = await POST(
      request("/api/session", "POST", {
        email: "test@example.com",
        password: "synthetic-password",
      }),
    );
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { requires2fa: false });
    const cookies = response.headers.getSetCookie().join(";");
    assert.match(cookies, /HttpOnly/);
    assert.match(cookies, /Secure/);
    assert.match(cookies, /SameSite=strict/);
    assert(!cookies.includes("private-refresh-secret"));
    assert.match(response.headers.get("cache-control") || "", /no-store/);
  } finally {
    if (original === undefined) Reflect.deleteProperty(process.env, "NODE_ENV");
    else Object.assign(process.env, { NODE_ENV: original });
  }
});

test("2FA challenges stay HttpOnly and code exchange uses issuer contract", async () => {
  mfa = true;
  const first = await POST(
    request("/api/session", "POST", {
      email: "test@example.com",
      password: "synthetic-password",
    }),
  );
  assert.deepEqual(await first.json(), { requires2fa: true });
  assert(
    first.headers
      .getSetCookie()
      .some(
        (value) =>
          value.startsWith("nexus_session=;") && value.includes("Max-Age=0"),
      ),
  );
  assert(
    first.headers
      .getSetCookie()
      .some(
        (value) =>
          value.includes("synthetic-challenge") && value.includes("HttpOnly"),
      ),
  );
  const second = await POST(
    request(
      "/api/session",
      "POST",
      { code: "123456" },
      { cookie: "nexus_challenge=synthetic-challenge" },
    ),
  );
  assert.equal(second.status, 200);
  assert.deepEqual(calls.at(-1)?.payload, {
    temp_token: "synthetic-challenge",
    code: "123456",
  });
  assert(!JSON.stringify(await second.json()).includes("synthetic-access"));
});

test("session mutations reject foreign/missing Origin, wrong Host and malformed input before upstream", async () => {
  const badHeaders: Record<string, string>[] = [
    { origin: "https://attacker.invalid" },
    { origin: "" },
    { host: "attacker.invalid" },
  ];
  for (const headers of badHeaders) {
    assert.equal(
      (await POST(request("/api/session", "POST", {}, headers))).status,
      403,
    );
    assert.equal(
      (await DELETE(request("/api/session", "DELETE", undefined, headers)))
        .status,
      403,
    );
  }
  for (const input of [
    {},
    { email: "x", password: "y" },
    { email: "x@y.z", password: "x", role: "admin" },
    { email: "x@y.z", password: "x".repeat(17000) },
  ])
    assert.equal(
      (await POST(request("/api/session", "POST", input))).status,
      400,
    );
  assert.equal(calls.length, 0);
});

test("logout clears local cookies and accurately reports issuer failure", async () => {
  logoutDown = true;
  const response = await DELETE(request("/api/session", "DELETE"));
  assert.equal(response.status, 502);
  assert.match(JSON.stringify(await response.json()), /could not be confirmed/);
  assert.equal(
    response.headers
      .getSetCookie()
      .filter((value) => value.includes("Max-Age=0")).length,
    2,
  );
  assert.equal(calls[0].method, "POST");
  assert.equal(calls[0].path, "/api/v1/auth/logout");
});

test("membership list is fresh, projected and missing credentials fail before upstream", async () => {
  const missing = await tenants(
    request("/api/tenants", "GET", undefined, { cookie: "" }),
  );
  assert.equal(missing.status, 401);
  assert.equal(calls.length, 0);
  const response = await tenants(request("/api/tenants"));
  assert.deepEqual(await response.json(), {
    items: [{ id: tenant, name: safeTenant.name, role: "owner" }],
    hasMore: false,
    offset: 0,
  });
  assert.equal(calls[0].path, "/api/v1/tenants?offset=0&limit=50");
  assert.equal((await tenants(request("/api/tenants?offset=-1"))).status, 400);
  assert.equal(
    (await tenants(request("/api/tenants?offset=0&offset=50"))).status,
    400,
  );
});

test("membership pages preserve roles, bound results and reject invalid entries", async () => {
  tenantRows = Array.from({ length: 50 }, (_, index) => ({
    id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    name: `Synthetic organization ${index + 1}`,
    role: index % 2 ? "member" : "owner",
    private_metadata: "must-not-escape",
  }));
  const response = await tenants(request("/api/tenants?offset=50"));
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(body.offset, 50);
  assert.equal(body.hasMore, true);
  assert.equal(body.items.length, 50);
  assert.equal(body.items[0].role, "owner");
  assert.equal(body.items[1].role, "member");
  assert(!JSON.stringify(body).includes("must-not-escape"));
  assert.equal(calls[0].path, "/api/v1/tenants?offset=50&limit=50");

  tenantRows = [];
  assert.deepEqual(await (await tenants(request("/api/tenants"))).json(), {
    items: [],
    hasMore: false,
    offset: 0,
  });
  tenantRows = [safeTenant, safeTenant];
  assert.equal((await tenants(request("/api/tenants"))).status, 502);
  tenantRows = [{ ...safeTenant, role: "admin" }];
  assert.equal((await tenants(request("/api/tenants"))).status, 502);
  tenantRows = Array.from({ length: 51 }, () => safeTenant);
  assert.equal((await tenants(request("/api/tenants"))).status, 502);
});

test("foreign tenant denial occurs before any event or log query", async () => {
  denied = true;
  const response = await overview(request(`/api/overview?tenant=${tenant}`));
  assert.equal(response.status, 403);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, `/api/v1/tenants/${tenant}`);
  assert(!JSON.stringify(await response.json()).includes("private"));
});

test("tenant names retain the issuer Unicode code point limit across list and scoped reads", async () => {
  const original = safeTenant.name;
  try {
    for (const length of [65, 128]) {
      safeTenant.name = "😀".repeat(length);
      const listed = await tenants(request("/api/tenants"));
      assert.equal(listed.status, 200);
      assert.equal((await listed.json()).items[0].name, safeTenant.name);
      const scoped = await overview(request(`/api/overview?tenant=${tenant}`));
      assert.equal(scoped.status, 200);
      assert.equal((await scoped.json()).tenant.name, safeTenant.name);
    }
    for (const name of ["😀".repeat(129), "a".repeat(129), ""]) {
      safeTenant.name = name;
      assert.equal((await tenants(request("/api/tenants"))).status, 502);
      calls = [];
      assert.equal(
        (await overview(request(`/api/overview?tenant=${tenant}`))).status,
        502,
      );
      assert.equal(calls.length, 1);
      assert.equal(calls[0].path, `/api/v1/tenants/${tenant}`);
    }
  } finally {
    safeTenant.name = original;
  }
});

test("overview deduplicates both receivers and never exports raw previews/payloads", async () => {
  const response = await overview(request(`/api/overview?tenant=${tenant}`));
  const data = await response.json();
  assert.equal(response.status, 200);
  assert.equal(data.events.length, 1);
  assert.deepEqual(data.events[0].receivers, ["EventPipe", "PipeWatch"]);
  assert.equal(data.events[0].conflict, false);
  assert.deepEqual(data.sources, { eventpipe: true, pipewatch: true });
  for (const secret of [
    "private-preview",
    "private-answer-secret",
    "synthetic-access",
    "payload",
    "contentKey",
    '"key"',
  ])
    assert(!JSON.stringify(data).includes(secret));
  assert(calls.every((item) => item.method === "GET"));
});

test("full safe payload conflicts remain visible even for the same displayed inactive state", async () => {
  conflict = true;
  const data = await (
    await overview(request(`/api/overview?tenant=${tenant}`))
  ).json();
  assert.equal(data.events[0].state, "inactive");
  assert.equal(data.events[0].conflict, true);
});

test("known outer markers cannot hide invalid inner types as successful empty reads", async () => {
  mismatched = true;
  const data = await (
    await overview(request(`/api/overview?tenant=${tenant}`))
  ).json();
  assert.deepEqual(data.sources, { eventpipe: false, pipewatch: false });
  assert.equal(data.events.length, 0);
});

test("independent outages and invalid scopes degrade without false empty success", async () => {
  epDown = true;
  let data = await (
    await overview(request(`/api/overview?tenant=${tenant}`))
  ).json();
  assert.deepEqual(data.sources, { eventpipe: false, pipewatch: true });
  assert.equal(data.events.length, 1);
  epDown = false;
  malformed = true;
  oversized = true;
  data = await (
    await overview(request(`/api/overview?tenant=${tenant}`))
  ).json();
  assert.deepEqual(data.sources, { eventpipe: false, pipewatch: false });
  assert.equal(data.events.length, 0);
  malformed = oversized = false;
  empty = true;
  data = await (
    await overview(request(`/api/overview?tenant=${tenant}`))
  ).json();
  assert.deepEqual(data.sources, { eventpipe: true, pipewatch: true });
  assert.equal(data.events.length, 0);
});

test("nonce CSP is unique, propagated and excludes unsafe production scripts", () => {
  const original = process.env.NODE_ENV;
  Object.assign(process.env, { NODE_ENV: "production" });
  try {
    const first = proxy(request("/")),
      second = proxy(request("/"));
    assert.notEqual(
      first.headers.get("content-security-policy"),
      second.headers.get("content-security-policy"),
    );
    assert.match(first.headers.get("content-security-policy") || "", /nonce-/);
    assert(
      !(first.headers.get("content-security-policy") || "").includes("unsafe-"),
    );
    assert.match(
      first.headers.get("content-security-policy") || "",
      /frame-ancestors 'none'/,
    );
    assert.match(first.headers.get("cache-control") || "", /no-store/);
  } finally {
    if (original === undefined) Reflect.deleteProperty(process.env, "NODE_ENV");
    else Object.assign(process.env, { NODE_ENV: original });
  }
});
