import assert from "node:assert/strict";
import { test } from "node:test";
import { NextRequest } from "next/server.js";
import { DELETE } from "../app/api/session/route.ts";
import {
  ApiError,
  challengeCookieName,
  guard,
  sessionCookieName,
  singleCookie,
} from "../lib/server.ts";

const browser = "http://127.0.0.1:3000";

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
  } finally {
    if (original === undefined) Reflect.deleteProperty(process.env, "NODE_ENV");
    else Object.assign(process.env, { NODE_ENV: original });
    if (originalOrigin === undefined)
      Reflect.deleteProperty(process.env, "DASHBOARD_ORIGIN");
    else Object.assign(process.env, { DASHBOARD_ORIGIN: originalOrigin });
  }
});
