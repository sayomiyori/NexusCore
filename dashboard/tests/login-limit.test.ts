import assert from "node:assert/strict";
import { test } from "node:test";
import { createLoginLimiter } from "../lib/login-limit.ts";

test("limits each account independently and resets after the window", () => {
  let now = 0;
  const limiter = createLoginLimiter({
    limit: 5,
    windowMs: 60_000,
    now: () => now,
  });
  for (let attempt = 0; attempt < 5; attempt += 1)
    assert.equal(limiter.allow("account-a").allowed, true);
  const blocked = limiter.allow("account-a");
  assert.equal(blocked.allowed, false);
  assert(blocked.retryAfter > 0);
  assert.equal(limiter.allow("account-b").allowed, true);
  now += 60_000;
  assert.equal(limiter.allow("account-a").allowed, true);
});

test("does not extend the window on blocked attempts", () => {
  let now = 0;
  const limiter = createLoginLimiter({
    limit: 5,
    windowMs: 60_000,
    now: () => now,
  });
  for (let attempt = 0; attempt < 5; attempt += 1) limiter.allow("account");
  now = 50_000;
  for (let attempt = 0; attempt < 5; attempt += 1)
    assert.equal(limiter.allow("account").allowed, false);
  now = 60_001;
  assert.equal(limiter.allow("account").allowed, true);
});

test("bounds the number of tracked accounts", () => {
  const now = 0;
  const limiter = createLoginLimiter({
    limit: 2,
    windowMs: 60_000,
    maxKeys: 2,
    now: () => now,
  });
  limiter.allow("a");
  limiter.allow("b");
  limiter.allow("c");
  assert(limiter.size() <= 2);
});
