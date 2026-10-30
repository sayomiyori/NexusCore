import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { NextRequest } from "next/server.js";
import { proxy } from "../proxy.ts";

const browser = "http://127.0.0.1:3000";
const original = process.env.NODE_ENV;

afterEach(() => {
  if (original === undefined) Reflect.deleteProperty(process.env, "NODE_ENV");
  else Object.assign(process.env, { NODE_ENV: original });
});

function request(path = "/"): NextRequest {
  return new NextRequest(browser + path, {
    headers: { host: "127.0.0.1:3000", origin: browser },
  });
}

test("the middleware answers with the full documented header set", () => {
  Object.assign(process.env, { NODE_ENV: "production" });
  const response = proxy(request("/dashboard"));
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.equal(response.headers.get("x-frame-options"), "DENY");
  assert.equal(response.headers.get("referrer-policy"), "no-referrer");
  assert.equal(
    response.headers.get("cross-origin-opener-policy"),
    "same-origin",
  );
  assert.equal(
    response.headers.get("permissions-policy"),
    "camera=(), microphone=(), geolocation=()",
  );
  assert.match(response.headers.get("cache-control") || "", /no-store/);
});

test("the nonce policy is strict in production and relaxed only in dev", () => {
  Object.assign(process.env, { NODE_ENV: "production" });
  const first = proxy(request());
  const policy = first.headers.get("content-security-policy") || "";
  assert.match(policy, /'nonce-[^']+'/);
  assert.match(policy, /'strict-dynamic'/);
  assert.match(policy, /frame-ancestors 'none'/);
  assert.match(policy, /object-src 'none'/);
  assert.match(policy, /base-uri 'none'/);
  assert.match(policy, /form-action 'self'/);
  assert(!policy.includes("unsafe-"));

  Object.assign(process.env, { NODE_ENV: "development" });
  assert.match(
    proxy(request()).headers.get("content-security-policy") || "",
    /'unsafe-eval'/,
  );
});

test("every response carries a fresh nonce", () => {
  const first = proxy(request()).headers.get("content-security-policy");
  const second = proxy(request()).headers.get("content-security-policy");
  assert.notEqual(first, second);
});
