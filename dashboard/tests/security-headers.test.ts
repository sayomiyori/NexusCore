import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import config from "../next.config.ts";

const original = process.env.NODE_ENV;

afterEach(() => {
  if (original === undefined) Reflect.deleteProperty(process.env, "NODE_ENV");
  else Object.assign(process.env, { NODE_ENV: original });
});

async function headers(): Promise<Record<string, string>> {
  if (typeof config.headers !== "function") throw new Error("no headers()");
  const rules = await config.headers();
  assert.equal(rules.length, 1);
  assert.equal(rules[0].source, "/(.*)");
  return Object.fromEntries(
    rules[0].headers.map(({ key, value }) => [key, value]),
  );
}

test("sends the documented security headers on every route", async () => {
  Object.assign(process.env, { NODE_ENV: "production" });
  const sent = await headers();
  assert.equal(sent["X-Content-Type-Options"], "nosniff");
  assert.equal(sent["X-Frame-Options"], "DENY");
  assert.equal(sent["Referrer-Policy"], "strict-origin-when-cross-origin");
  assert.equal(sent["Cross-Origin-Opener-Policy"], "same-origin");
  assert.match(sent["Permissions-Policy"], /camera=\(\)/);
  assert.match(sent["Permissions-Policy"], /geolocation=\(\)/);
  assert.equal(config.poweredByHeader, false);
});

test("locks the content security policy to same-origin framing", async () => {
  Object.assign(process.env, { NODE_ENV: "production" });
  const policy = (await headers())["Content-Security-Policy"];
  assert(policy);
  assert.match(policy, /frame-ancestors 'none'/);
  assert.match(policy, /base-uri 'self'/);
  assert.match(policy, /form-action 'self'/);
  assert.match(policy, /object-src 'none'/);
  assert.match(policy, /default-src 'self'/);
  assert.match(policy, /connect-src 'self'/);
  assert.match(policy, /script-src 'self' 'unsafe-inline'/);
  assert(!policy.includes("unsafe-eval"));
});

test("only the development server allows eval for hot reload", async () => {
  Object.assign(process.env, { NODE_ENV: "development" });
  const policy = (await headers())["Content-Security-Policy"];
  assert.match(policy, /script-src 'self' 'unsafe-inline' 'unsafe-eval'/);
});
