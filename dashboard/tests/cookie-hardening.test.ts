import assert from "node:assert/strict";
import { test } from "node:test";
import { NextRequest } from "next/server.js";
import { DELETE } from "../app/api/session/route.ts";
import { GET as tenants } from "../app/api/tenants/route.ts";
import {
  ApiError,
  challengeCookieName,
  cookiePathScopes,
  guard,
  refreshCookieName,
  sessionCookieName,
  singleCookie,
} from "../lib/server.ts";

const browser = "http://127.0.0.1:3000";

function cookiePath(value: string): string {
  const path = value
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("Path="));
  if (!path) throw new Error(`missing Path in ${value}`);
  return path;
}

test("rejects duplicate session cookies", () => {
  const request = new NextRequest(`${browser}/api/session`, {
    headers: { cookie: "nexus_session=one; nexus_session=two" },
  });
  assert.throws(
    () => singleCookie(request, "nexus_session"),
    (error: unknown) => error instanceof ApiError && error.status === 400,
  );
});

test("reads one session cookie", () => {
  const request = new NextRequest(`${browser}/api/session`, {
    headers: { cookie: "nexus_session=value" },
  });
  assert.equal(singleCookie(request, "nexus_session"), "value");
});

test("uses host-prefixed cookies on HTTPS production origins", () => {
  const original = process.env.NODE_ENV;
  const originalOrigin = process.env.DASHBOARD_ORIGIN;
  Object.assign(process.env, {
    NODE_ENV: "production",
    DASHBOARD_ORIGIN: "https://127.0.0.1:3000",
  });
  try {
    assert.equal(sessionCookieName(), "__Host-nexus_session");
    assert.equal(challengeCookieName(), "__Host-nexus_challenge");
    assert.equal(refreshCookieName(), "__Host-nexus_refresh");
    const request = new NextRequest("https://127.0.0.1:3000/api/session", {
      headers: {
        host: "127.0.0.1:3000",
        origin: "https://127.0.0.1:3000",
        cookie: "__Host-nexus_session=token",
      },
    });
    assert.equal(guard(request), "token");
    const legacy = new NextRequest("https://127.0.0.1:3000/api/session", {
      headers: {
        host: "127.0.0.1:3000",
        origin: "https://127.0.0.1:3000",
        cookie: "nexus_session=token",
      },
    });
    assert.throws(
      () => guard(legacy),
      (error: unknown) => error instanceof ApiError && error.status === 401,
    );
  } finally {
    if (original === undefined) Reflect.deleteProperty(process.env, "NODE_ENV");
    else Object.assign(process.env, { NODE_ENV: original });
    if (originalOrigin === undefined)
      Reflect.deleteProperty(process.env, "DASHBOARD_ORIGIN");
    else Object.assign(process.env, { DASHBOARD_ORIGIN: originalOrigin });
  }
});

test("DELETE returns a bounded 400 and clears duplicates", async () => {
  const originalOrigin = process.env.DASHBOARD_ORIGIN;
  process.env.DASHBOARD_ORIGIN = browser;
  try {
    const request = new NextRequest(`${browser}/api/session`, {
      method: "DELETE",
      headers: {
        host: "127.0.0.1:3000",
        origin: browser,
        cookie: "nexus_session=one; nexus_session=two",
      },
    });
    const response = await DELETE(request);
    assert.equal(response.status, 400);
    assert(
      response.headers
        .getSetCookie()
        .some((value) => value.startsWith("nexus_session=;")),
    );
  } finally {
    if (originalOrigin === undefined)
      Reflect.deleteProperty(process.env, "DASHBOARD_ORIGIN");
    else Object.assign(process.env, { DASHBOARD_ORIGIN: originalOrigin });
  }
});

test("DELETE also clears a legacy cookie planted on /api", async () => {
  const originalOrigin = process.env.DASHBOARD_ORIGIN;
  process.env.DASHBOARD_ORIGIN = browser;
  try {
    const request = new NextRequest(`${browser}/api/session`, {
      method: "DELETE",
      headers: {
        host: "127.0.0.1:3000",
        origin: browser,
        cookie: "nexus_session=one; nexus_session=two",
      },
    });
    const response = await DELETE(request);
    assert.equal(response.status, 400);
    const cookies = response.headers.getSetCookie();
    assert(
      cookies.some(
        (value) =>
          value.startsWith("nexus_session=;") &&
          value.includes("Path=/api") &&
          value.includes("Max-Age=0"),
      ),
    );
    assert(
      cookies.some(
        (value) =>
          value.startsWith("nexus_challenge=;") && value.includes("Path=/api"),
      ),
    );
  } finally {
    if (originalOrigin === undefined)
      Reflect.deleteProperty(process.env, "DASHBOARD_ORIGIN");
    else Object.assign(process.env, { DASHBOARD_ORIGIN: originalOrigin });
  }
});

test("DELETE clears host-prefixed cookies in HTTPS production", async () => {
  const original = process.env.NODE_ENV;
  const originalOrigin = process.env.DASHBOARD_ORIGIN;
  Object.assign(process.env, {
    NODE_ENV: "production",
    DASHBOARD_ORIGIN: "https://127.0.0.1:3000",
  });
  try {
    const request = new NextRequest("https://127.0.0.1:3000/api/session", {
      method: "DELETE",
      headers: {
        host: "127.0.0.1:3000",
        origin: "https://127.0.0.1:3000",
        cookie: "__Host-nexus_session=one; __Host-nexus_session=two",
      },
    });
    const response = await DELETE(request);
    assert.equal(response.status, 400);
    const cookies = response.headers.getSetCookie();
    assert(
      cookies.some(
        (value) =>
          value.startsWith("__Host-nexus_session=;") &&
          value.includes("Secure"),
      ),
    );
    assert(
      cookies.some(
        (value) =>
          value.startsWith("__Host-nexus_refresh=;") &&
          value.includes("Secure"),
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

test("cookie path scopes cover every scope that can shadow a request", () => {
  assert.deepEqual(cookiePathScopes("/"), ["/"]);
  assert.deepEqual(cookiePathScopes("/api"), ["/", "/api"]);
  assert.deepEqual(cookiePathScopes("/api/session"), [
    "/",
    "/api",
    "/api/",
    "/api/session",
  ]);
  assert.deepEqual(cookiePathScopes("/api/session/"), [
    "/",
    "/api",
    "/api/",
    "/api/session",
    "/api/session/",
  ]);
});

test("a duplicate on a nested BFF route clears every scope that can shadow it", async () => {
  const originalOrigin = process.env.DASHBOARD_ORIGIN;
  process.env.DASHBOARD_ORIGIN = browser;
  try {
    const request = new NextRequest(`${browser}/api/tenants`, {
      headers: {
        host: "127.0.0.1:3000",
        cookie: "nexus_session=one; nexus_session=two",
      },
    });
    const response = await tenants(request);
    assert.equal(response.status, 400);
    const cookies = response.headers.getSetCookie();
    const scopes = ["/", "/api", "/api/", "/api/tenants"];
    assert.equal(cookies.length, 15);
    for (const name of ["nexus_session", "nexus_refresh", "nexus_challenge"])
      for (const scope of scopes)
        assert(
          cookies.some(
            (value) =>
              value.startsWith(`${name}=;`) &&
              cookiePath(value) === `Path=${scope}`,
          ),
          `${name} was not cleared at ${scope}`,
        );
    for (const value of cookies) {
      assert(value.includes("Max-Age=0"));
      assert(scopes.includes(cookiePath(value).slice("Path=".length)));
    }
  } finally {
    if (originalOrigin === undefined)
      Reflect.deleteProperty(process.env, "DASHBOARD_ORIGIN");
    else Object.assign(process.env, { DASHBOARD_ORIGIN: originalOrigin });
  }
});

test("successful sign-out emits only the root and /api clearing scopes", async () => {
  const originalOrigin = process.env.DASHBOARD_ORIGIN;
  process.env.DASHBOARD_ORIGIN = browser;
  try {
    const request = new NextRequest(`${browser}/api/session`, {
      method: "DELETE",
      headers: { host: "127.0.0.1:3000", origin: browser, cookie: "" },
    });
    const response = await DELETE(request);
    assert.equal(response.status, 200);
    const cookies = response.headers.getSetCookie();
    assert.equal(cookies.length, 9);
    assert.deepEqual(
      new Set(cookies.map((value) => cookiePath(value).slice("Path=".length))),
      new Set(["/", "/api"]),
    );
    for (const name of ["nexus_session", "nexus_challenge", "nexus_refresh"])
      assert(
        cookies.some(
          (value) =>
            value.startsWith(`${name}=;`) && cookiePath(value) === "Path=/",
        ),
        `${name} was not cleared at the root`,
      );
  } finally {
    if (originalOrigin === undefined)
      Reflect.deleteProperty(process.env, "DASHBOARD_ORIGIN");
    else Object.assign(process.env, { DASHBOARD_ORIGIN: originalOrigin });
  }
});

test("rejects duplicate refresh cookies and clears both prefixed and legacy names", async () => {
  const original = process.env.NODE_ENV;
  const originalOrigin = process.env.DASHBOARD_ORIGIN;
  Object.assign(process.env, {
    NODE_ENV: "production",
    DASHBOARD_ORIGIN: "https://127.0.0.1:3000",
  });
  try {
    const request = new NextRequest("https://127.0.0.1:3000/api/session", {
      method: "DELETE",
      headers: {
        host: "127.0.0.1:3000",
        origin: "https://127.0.0.1:3000",
        cookie:
          "__Host-nexus_session=token; __Host-nexus_refresh=one; __Host-nexus_refresh=two; nexus_refresh=legacy",
      },
    });
    const response = await DELETE(request);
    assert.equal(response.status, 400);
    const cookies = response.headers.getSetCookie();
    assert(cookies.some((value) => value.startsWith("__Host-nexus_refresh=;")));
    assert(cookies.some((value) => value.startsWith("nexus_refresh=;")));
  } finally {
    if (original === undefined) Reflect.deleteProperty(process.env, "NODE_ENV");
    else Object.assign(process.env, { NODE_ENV: original });
    if (originalOrigin === undefined)
      Reflect.deleteProperty(process.env, "DASHBOARD_ORIGIN");
    else Object.assign(process.env, { DASHBOARD_ORIGIN: originalOrigin });
  }
});
