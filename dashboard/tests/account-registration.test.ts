import assert from "node:assert/strict";
import http from "node:http";
import { after, before, beforeEach, test } from "node:test";
import { NextRequest } from "next/server.js";
import { POST } from "../app/api/account-registration/route.ts";

const browser = "http://127.0.0.1:3000";
let status = 200;
let acknowledgement: Record<string, unknown> = {};
let calls: { method: string; path: string; body: string }[] = [];
const server = http.createServer((req, res) => {
  let body = "";
  req.on("data", (chunk) => {
    body += chunk;
  });
  req.on("end", () => {
    calls.push({ method: req.method || "", path: req.url || "", body });
    res.setHeader("Content-Type", "application/json");
    res.statusCode = status;
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
  });
});
beforeEach(() => {
  calls = [];
  status = 200;
  acknowledgement = {
    user_id: "00000000-0000-4000-8000-000000000010",
    email: "new@example.com",
  };
});
after(async () => {
  server.closeAllConnections();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});
function request(
  body: string,
  headers: Record<string, string> = {},
): NextRequest {
  return new NextRequest(`${browser}/api/account-registration`, {
    method: "POST",
    body,
    headers: {
      host: "127.0.0.1:3000",
      origin: browser,
      "content-type": "application/json",
      ...headers,
    },
  });
}
const valid = (email = "new@example.com") =>
  JSON.stringify({ email, username: " New User ", password: "secret-value" });

test("registration posts once and never echoes credentials", async () => {
  const response = await POST(request(valid()));
  const text = await response.text();
  assert.equal(response.status, 201);
  assert.deepEqual(JSON.parse(text), { registered: true });
  assert(!text.includes("new@example.com"));
  assert(!text.includes("secret-value"));
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, "POST");
  assert.equal(calls[0].path, "/api/v1/auth/register");
  assert.deepEqual(JSON.parse(calls[0].body), {
    email: "new@example.com",
    username: "New User",
    password: "secret-value",
  });
});

test("duplicate email is a 409 and upstream failures are bounded", async () => {
  status = 409;
  assert.equal((await POST(request(valid("dupe@example.com")))).status, 409);
  for (const upstream of [429, 503, 500]) {
    calls = [];
    status = upstream;
    const response = await POST(request(valid(`fail-${upstream}@example.com`)));
    assert.equal(response.status, upstream === 429 ? 429 : 502);
    assert.equal(calls.length, 1);
  }
});

test("invalid metadata, origin and extra fields never reach the issuer", async () => {
  calls = [];
  for (const req of [
    request(valid(), { origin: "http://127.0.0.1:3001" }),
    request(valid(), { host: "evil.example" }),
    request(JSON.stringify({ email: "x", username: "u", password: "p" })),
    request(JSON.stringify({ email: "a@b.co", username: "", password: "p" })),
    request(JSON.stringify({ email: "a@b.co", username: "u", password: "" })),
    request(
      JSON.stringify({
        email: "a@b.co",
        username: "u",
        password: "p",
        extra: true,
      }),
    ),
    request(
      `{"email":"a@b.co","username":"u","password":"${"x".repeat(17_000)}"}`,
    ),
  ]) {
    assert([400, 403].includes((await POST(req)).status));
  }
  assert.equal(calls.length, 0);
});

test("a mismatched issuer acknowledgement is not treated as success", async () => {
  acknowledgement = {
    user_id: "00000000-0000-4000-8000-000000000010",
    email: "other@example.com",
  };
  assert.equal(
    (await POST(request(valid("mismatch@example.com")))).status,
    502,
  );
});

test("the per-email limiter rejects the sixth attempt without an upstream call", async () => {
  calls = [];
  const email = "limit@example.com";
  acknowledgement = {
    user_id: "00000000-0000-4000-8000-000000000010",
    email,
  };
  for (let attempt = 0; attempt < 5; attempt += 1)
    assert.equal((await POST(request(valid(email)))).status, 201);
  assert.equal(calls.length, 5);
  assert.equal((await POST(request(valid(email)))).status, 429);
  assert.equal(calls.length, 5);
});
