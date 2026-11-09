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
  authorization?: string;
  payload: unknown;
}[] = [];
let mfa = false,
  denied = false,
  epDown = false,
  pwDown = false,
  conflict = false,
  malformed = false,
  empty = false;
let logoutStatus = 204,
  logoutRefreshStatus = 204,
  failLogoutToken = "",
  failRefreshToken = "",
  revokeOnFirstAccess = false,
  accessRevoked = false,
  badRefresh = false,
  oversized = false,
  mismatched = false;
let tenantRows: unknown = [safeTenant];
let membershipStatus = 200;

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
      authorization: req.headers.authorization,
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
              refresh_token: badRefresh ? 42 : "private-refresh-secret",
              token_type: "bearer",
            },
      );
    if (path.endsWith("/auth/login/2fa"))
      return send({
        access_token: "synthetic-access",
        refresh_token: "private-refresh-secret",
        token_type: "bearer",
      });
    if (path.endsWith("/auth/logout/refresh")) {
      if (logoutRefreshStatus === 200) return send({});
      const refreshToken = raw ? JSON.parse(raw).refresh_token : undefined;
      res.statusCode =
        failRefreshToken && refreshToken === failRefreshToken
          ? 401
          : logoutRefreshStatus;
      res.end();
      return;
    }
    if (path.endsWith("/auth/logout")) {
      if (logoutStatus === 200) return send({});
      if (revokeOnFirstAccess) {
        res.statusCode = accessRevoked ? 401 : 204;
        accessRevoked = true;
        res.end();
        return;
      }
      res.statusCode =
        failLogoutToken &&
        req.headers.authorization === `Bearer ${failLogoutToken}`
          ? 401
          : logoutStatus;
      res.end();
      return;
    }
    assert.equal(req.headers.authorization, "Bearer synthetic-access");
    if (path.startsWith("/api/v1/tenants?"))
      return send(tenantRows, membershipStatus);
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
  membershipStatus = 200;
  mfa =
    denied =
    epDown =
    pwDown =
    conflict =
    malformed =
    empty =
    oversized =
    mismatched =
      false;
  logoutStatus = 204;
  logoutRefreshStatus = 204;
  failLogoutToken = "";
  failRefreshToken = "";
  revokeOnFirstAccess = false;
  accessRevoked = false;
  badRefresh = false;
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
  const originalOrigin = process.env.DASHBOARD_ORIGIN;
  Object.assign(process.env, {
    NODE_ENV: "production",
    DASHBOARD_ORIGIN: "https://127.0.0.1:3000",
  });
  try {
    const response = await POST(
      request(
        "/api/session",
        "POST",
        {
          email: "test@example.com",
          password: "synthetic-password",
        },
        { origin: "https://127.0.0.1:3000" },
      ),
    );
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.deepEqual(body, { requires2fa: false });
    assert(!JSON.stringify(body).includes("private-refresh-secret"));
    const cookies = response.headers.getSetCookie();
    const session = cookies.find((value) =>
      value.startsWith("__Host-nexus_session="),
    );
    const refresh = cookies.find((value) =>
      value.startsWith("__Host-nexus_refresh="),
    );
    assert(session);
    assert(refresh);
    assert.match(session, /HttpOnly/);
    assert.match(session, /Secure/);
    assert.match(session, /SameSite=strict/);
    assert.match(session, /Path=\//);
    assert.match(session, /Max-Age=900/);
    assert.match(refresh, /private-refresh-secret/);
    assert.match(refresh, /HttpOnly/);
    assert.match(refresh, /Secure/);
    assert.match(refresh, /SameSite=strict/);
    assert.match(refresh, /Path=\//);
    assert.match(refresh, /Max-Age=2592000/);
    assert(!cookies.some((value) => value.includes("Domain=")));
    assert.match(response.headers.get("cache-control") || "", /no-store/);
  } finally {
    if (original === undefined) Reflect.deleteProperty(process.env, "NODE_ENV");
    else Object.assign(process.env, { NODE_ENV: original });
    if (originalOrigin === undefined)
      Reflect.deleteProperty(process.env, "DASHBOARD_ORIGIN");
    else Object.assign(process.env, { DASHBOARD_ORIGIN: originalOrigin });
  }
});

test("production loopback keeps legacy cookie names but still sets Secure", async () => {
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
    const cookies = response.headers.getSetCookie().join(";");
    assert.match(cookies, /nexus_session=/);
    assert.match(cookies, /nexus_refresh=private-refresh-secret/);
    assert(!cookies.includes("__Host-"));
    assert.match(cookies, /Secure/);
    assert.match(cookies, /HttpOnly/);
    assert.match(cookies, /SameSite=strict/);
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
          value.startsWith("nexus_refresh=;") && value.includes("Max-Age=0"),
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
  const secondBody = await second.json();
  assert(!JSON.stringify(secondBody).includes("synthetic-access"));
  assert(
    second.headers
      .getSetCookie()
      .some(
        (value) =>
          value.startsWith("nexus_refresh=private-refresh-secret") &&
          value.includes("Max-Age=2592000"),
      ),
  );
});

test("login rejects a malformed refresh credential before setting any auth cookie", async () => {
  badRefresh = true;
  const response = await POST(
    request("/api/session", "POST", {
      email: "test@example.com",
      password: "synthetic-password",
    }),
  );
  assert.equal(response.status, 401);
  assert.equal(response.headers.getSetCookie().length, 0);
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

test("logout reports unconfirmed when the presented access credential fails", async () => {
  logoutStatus = 503;
  const response = await DELETE(request("/api/session", "DELETE"));
  assert.equal(response.status, 502);
  assert.match(JSON.stringify(await response.json()), /could not be confirmed/);
  assert.equal(
    response.headers
      .getSetCookie()
      .filter((value) => value.includes("Max-Age=0")).length,
    6,
  );
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, "POST");
  assert.equal(calls[0].path, "/api/v1/auth/logout");
});

test("logout confirms only when every presented credential returns 204", async () => {
  const response = await DELETE(
    request("/api/session", "DELETE", undefined, {
      cookie:
        "nexus_session=synthetic-access; nexus_refresh=private-refresh-secret",
    }),
  );
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.deepEqual(body, { signedOut: true });
  assert(!JSON.stringify(body).includes("private-refresh-secret"));
  assert.equal(calls.length, 2);
  assert.equal(calls[0].path, "/api/v1/auth/logout");
  assert.equal(calls[1].path, "/api/v1/auth/logout/refresh");
  const accessCall = calls.find((call) => call.path === "/api/v1/auth/logout");
  const refreshCall = calls.find(
    (call) => call.path === "/api/v1/auth/logout/refresh",
  );
  assert(accessCall);
  assert(refreshCall);
  assert.equal(accessCall.authorization, "Bearer synthetic-access");
  assert.deepEqual(accessCall.payload, {});
  assert.equal(refreshCall.authorization, undefined);
  assert.deepEqual(refreshCall.payload, {
    refresh_token: "private-refresh-secret",
  });
  assert.equal(
    response.headers
      .getSetCookie()
      .filter((value) => value.includes("Max-Age=0")).length,
    6,
  );
});

test("expired access cookie revokes the issuer session with the refresh credential", async () => {
  const response = await DELETE(
    request("/api/session", "DELETE", undefined, {
      cookie: "nexus_refresh=private-refresh-secret",
    }),
  );
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { signedOut: true });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, "/api/v1/auth/logout/refresh");
  assert.equal(calls[0].authorization, undefined);
  assert.deepEqual(calls[0].payload, {
    refresh_token: "private-refresh-secret",
  });
  assert.equal(
    response.headers
      .getSetCookie()
      .filter((value) => value.includes("Max-Age=0")).length,
    6,
  );
});

test("a failure from either presented credential is unconfirmed without retry", async () => {
  const both = {
    cookie:
      "nexus_session=synthetic-access; nexus_refresh=private-refresh-secret",
  };
  logoutStatus = 401;
  let response = await DELETE(
    request("/api/session", "DELETE", undefined, both),
  );
  assert.equal(response.status, 502);
  assert.deepEqual(await response.json(), {
    error: "Local session cleared; issuer sign-out could not be confirmed.",
  });
  assert.equal(calls.length, 2);
  assert(calls.some((call) => call.path === "/api/v1/auth/logout"));
  assert(calls.some((call) => call.path === "/api/v1/auth/logout/refresh"));

  calls = [];
  logoutStatus = 204;
  logoutRefreshStatus = 401;
  response = await DELETE(request("/api/session", "DELETE", undefined, both));
  assert.equal(response.status, 502);
  assert.equal(calls.length, 2);

  calls = [];
  logoutRefreshStatus = 503;
  response = await DELETE(
    request("/api/session", "DELETE", undefined, {
      cookie: "nexus_refresh=private-refresh-secret",
    }),
  );
  assert.equal(response.status, 502);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, "/api/v1/auth/logout/refresh");
  assert.equal(
    response.headers
      .getSetCookie()
      .filter((value) => value.includes("Max-Age=0")).length,
    6,
  );

  calls = [];
  logoutRefreshStatus = 401;
  response = await DELETE(
    request("/api/session", "DELETE", undefined, {
      cookie: "nexus_refresh=private-refresh-secret",
    }),
  );
  assert.equal(response.status, 502);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, "/api/v1/auth/logout/refresh");
});

test("unexpected 200 from either logout endpoint is unconfirmed", async () => {
  logoutStatus = 200;
  let response = await DELETE(request("/api/session", "DELETE"));
  assert.equal(response.status, 502);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, "/api/v1/auth/logout");

  calls = [];
  logoutStatus = 204;
  logoutRefreshStatus = 200;
  response = await DELETE(
    request("/api/session", "DELETE", undefined, {
      cookie: "nexus_refresh=private-refresh-secret",
    }),
  );
  assert.equal(response.status, 502);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, "/api/v1/auth/logout/refresh");
});

test("HTTPS revokes every distinct access and refresh cookie value", async () => {
  const original = process.env.NODE_ENV;
  const originalOrigin = process.env.DASHBOARD_ORIGIN;
  Object.assign(process.env, {
    NODE_ENV: "production",
    DASHBOARD_ORIGIN: "https://127.0.0.1:3000",
  });
  try {
    const response = await DELETE(
      request("/api/session", "DELETE", undefined, {
        origin: "https://127.0.0.1:3000",
        cookie:
          "__Host-nexus_session=preferred-access; nexus_session=legacy-access; __Host-nexus_refresh=preferred-refresh; nexus_refresh=legacy-refresh",
      }),
    );
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { signedOut: true });
    assert.equal(calls.length, 4);
    for (const token of ["preferred-access", "legacy-access"])
      assert(
        calls.some(
          (call) =>
            call.path === "/api/v1/auth/logout" &&
            call.authorization === `Bearer ${token}`,
        ),
      );
    for (const token of ["preferred-refresh", "legacy-refresh"])
      assert(
        calls.some(
          (call) =>
            call.path === "/api/v1/auth/logout/refresh" &&
            (call.payload as { refresh_token?: string }).refresh_token ===
              token,
        ),
      );
    const cookies = response.headers.getSetCookie();
    for (const name of [
      "__Host-nexus_session=;",
      "nexus_session=;",
      "__Host-nexus_refresh=;",
      "nexus_refresh=;",
    ])
      assert(cookies.some((value) => value.startsWith(name)));
  } finally {
    if (original === undefined) Reflect.deleteProperty(process.env, "NODE_ENV");
    else Object.assign(process.env, { NODE_ENV: original });
    if (originalOrigin === undefined)
      Reflect.deleteProperty(process.env, "DASHBOARD_ORIGIN");
    else Object.assign(process.env, { DASHBOARD_ORIGIN: originalOrigin });
  }
});

test("one failing mixed HTTPS credential is unconfirmed", async () => {
  const original = process.env.NODE_ENV;
  const originalOrigin = process.env.DASHBOARD_ORIGIN;
  Object.assign(process.env, {
    NODE_ENV: "production",
    DASHBOARD_ORIGIN: "https://127.0.0.1:3000",
  });
  try {
    failRefreshToken = "legacy-refresh";
    let response = await DELETE(
      request("/api/session", "DELETE", undefined, {
        origin: "https://127.0.0.1:3000",
        cookie:
          "__Host-nexus_session=preferred-access; nexus_session=legacy-access; __Host-nexus_refresh=preferred-refresh; nexus_refresh=legacy-refresh",
      }),
    );
    assert.equal(response.status, 502);
    assert.equal(calls.length, 4);

    calls = [];
    failRefreshToken = "";
    failLogoutToken = "legacy-access";
    response = await DELETE(
      request("/api/session", "DELETE", undefined, {
        origin: "https://127.0.0.1:3000",
        cookie:
          "__Host-nexus_session=preferred-access; nexus_session=legacy-access; __Host-nexus_refresh=preferred-refresh; nexus_refresh=legacy-refresh",
      }),
    );
    assert.equal(response.status, 502);
    assert.equal(calls.length, 4);
  } finally {
    if (original === undefined) Reflect.deleteProperty(process.env, "NODE_ENV");
    else Object.assign(process.env, { NODE_ENV: original });
    if (originalOrigin === undefined)
      Reflect.deleteProperty(process.env, "DASHBOARD_ORIGIN");
    else Object.assign(process.env, { DASHBOARD_ORIGIN: originalOrigin });
  }
});

test("HTTPS revokes legacy-only credentials", async () => {
  const original = process.env.NODE_ENV;
  const originalOrigin = process.env.DASHBOARD_ORIGIN;
  Object.assign(process.env, {
    NODE_ENV: "production",
    DASHBOARD_ORIGIN: "https://127.0.0.1:3000",
  });
  try {
    const response = await DELETE(
      request("/api/session", "DELETE", undefined, {
        origin: "https://127.0.0.1:3000",
        cookie: "nexus_session=legacy-access; nexus_refresh=legacy-refresh",
      }),
    );
    assert.equal(response.status, 200);
    assert.equal(calls.length, 2);
    assert(
      calls.some(
        (call) =>
          call.path === "/api/v1/auth/logout" &&
          call.authorization === "Bearer legacy-access",
      ),
    );
    assert(
      calls.some(
        (call) =>
          call.path === "/api/v1/auth/logout/refresh" &&
          (call.payload as { refresh_token?: string }).refresh_token ===
            "legacy-refresh",
      ),
    );
  } finally {
    if (original === undefined) Reflect.deleteProperty(process.env, "NODE_ENV");
    else Object.assign(process.env, { NODE_ENV: original });
    if (originalOrigin === undefined)
      Reflect.deleteProperty(process.env, "DASHBOARD_ORIGIN");
    else Object.assign(process.env, { DASHBOARD_ORIGIN: originalOrigin });
  }
});

test("identical preferred and legacy values are deduplicated", async () => {
  const response = await DELETE(
    request("/api/session", "DELETE", undefined, {
      cookie:
        "__Host-nexus_session=same-access; nexus_session=same-access; __Host-nexus_refresh=same-refresh; nexus_refresh=same-refresh",
    }),
  );
  assert.equal(response.status, 200);
  assert.equal(calls.length, 2);
  assert(
    calls.some(
      (call) =>
        call.path === "/api/v1/auth/logout" &&
        call.authorization === "Bearer same-access",
    ),
  );
  assert(
    calls.some(
      (call) =>
        call.path === "/api/v1/auth/logout/refresh" &&
        (call.payload as { refresh_token?: string }).refresh_token ===
          "same-refresh",
    ),
  );
});

test("HTTP mixed host-prefixed and legacy credentials are all attempted", async () => {
  const mixed = {
    cookie:
      "__Host-nexus_session=host-access; nexus_session=legacy-access; __Host-nexus_refresh=host-refresh; nexus_refresh=legacy-refresh",
  };
  let response = await DELETE(
    request("/api/session", "DELETE", undefined, mixed),
  );
  assert.equal(response.status, 200);
  assert.equal(calls.length, 4);
  for (const token of ["host-access", "legacy-access"])
    assert(
      calls.some(
        (call) =>
          call.path === "/api/v1/auth/logout" &&
          call.authorization === `Bearer ${token}`,
      ),
    );
  for (const token of ["host-refresh", "legacy-refresh"])
    assert(
      calls.some(
        (call) =>
          call.path === "/api/v1/auth/logout/refresh" &&
          (call.payload as { refresh_token?: string }).refresh_token === token,
      ),
    );

  calls = [];
  failRefreshToken = "legacy-refresh";
  response = await DELETE(request("/api/session", "DELETE", undefined, mixed));
  assert.equal(response.status, 502);
  assert.equal(calls.length, 4);
});

test("absent cookies are local-only success", async () => {
  const response = await DELETE(
    request("/api/session", "DELETE", undefined, { cookie: "" }),
  );
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { signedOut: true });
  assert.equal(calls.length, 0);
  assert.equal(
    response.headers
      .getSetCookie()
      .filter((value) => value.includes("Max-Age=0")).length,
    6,
  );
});

test("duplicate refresh cookies fail locally and clear all cookies", async () => {
  const response = await DELETE(
    request("/api/session", "DELETE", undefined, {
      cookie:
        "nexus_session=synthetic-access; nexus_refresh=one; nexus_refresh=two",
    }),
  );
  assert.equal(response.status, 400);
  assert.equal(calls.length, 0);
  const cleared = response.headers
    .getSetCookie()
    .filter((value) => value.includes("Max-Age=0"));
  assert.equal(cleared.length, 6);
  assert(cleared.some((value) => value.startsWith("nexus_refresh=;")));
});

test("access failure without a refresh cookie is not retried", async () => {
  logoutStatus = 401;
  const response = await DELETE(request("/api/session", "DELETE"));
  assert.equal(response.status, 502);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, "/api/v1/auth/logout");
});

test("a second distinct access credential after revocation is unconfirmed", async () => {
  revokeOnFirstAccess = true;
  const response = await DELETE(
    request("/api/session", "DELETE", undefined, {
      cookie: "__Host-nexus_session=one; nexus_session=two",
    }),
  );
  assert.equal(response.status, 502);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].authorization, "Bearer one");
  assert.equal(calls[1].authorization, "Bearer two");
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

test("refresh replaces membership snapshots and propagates issuer failures without stale rows", async () => {
  const read = () => tenants(request("/api/tenants?offset=0"));
  assert.equal((await (await read()).json()).items[0].role, "owner");
  tenantRows = [{ ...safeTenant, role: "member" }];
  assert.equal((await (await read()).json()).items[0].role, "member");
  tenantRows = [];
  assert.deepEqual((await (await read()).json()).items, []);
  for (const status of [401, 403, 503]) {
    membershipStatus = status;
    tenantRows = { private: "issuer-error-must-not-escape" };
    const response = await read();
    assert.equal(response.status, status === 503 ? 502 : status);
    const body = await response.json();
    assert.equal(body.items, undefined);
    assert(!JSON.stringify(body).includes("issuer-error-must-not-escape"));
  }
  assert(
    calls.every((call) => call.path === "/api/v1/tenants?offset=0&limit=50"),
  );
});

test("last permitted membership page cannot advertise an invalid next offset", async () => {
  tenantRows = Array.from({ length: 50 }, (_, index) => ({
    ...safeTenant,
    id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
  }));
  for (const offset of [99951, 99999, 100000]) {
    const response = await tenants(request(`/api/tenants?offset=${offset}`));
    assert.equal(response.status, 200);
    assert.equal((await response.json()).hasMore, false);
  }
  assert.equal(
    (await (await tenants(request("/api/tenants?offset=99950"))).json())
      .hasMore,
    true,
  );
  const count = calls.length;
  assert.equal(
    (await tenants(request("/api/tenants?offset=100050"))).status,
    400,
  );
  assert.equal(calls.length, count);
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
