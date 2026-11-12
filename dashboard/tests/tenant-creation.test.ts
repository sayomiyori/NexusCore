import assert from "node:assert/strict";
import http from "node:http";
import { after, before, beforeEach, test } from "node:test";
import { NextRequest } from "next/server.js";
import { POST } from "../app/api/tenant-creation/route.ts";

const browser = "http://127.0.0.1:3000";
const id = "00000000-0000-4000-8000-000000000020";
let status = 201;
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
  status = 201;
  acknowledgement = {
    id,
    name: "New Org",
    role: "owner",
    created_at: "2026-11-12T10:00:00Z",
  };
});
after(async () => {
  server.closeAllConnections();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});
function request(
  body: string,
  token = "synthetic-access",
  headers: Record<string, string> = {},
): NextRequest {
  return new NextRequest(`${browser}/api/tenant-creation`, {
    method: "POST",
    body,
    headers: {
      host: "127.0.0.1:3000",
      origin: browser,
      cookie: `nexus_session=${token}`,
      "content-type": "application/json",
      ...headers,
    },
  });
}
const valid = (name = " New Org ") => JSON.stringify({ name });

test("tenant creation posts once and returns a safe owner projection", async () => {
  const response = await POST(request(valid()));
  const result = await response.json();
  assert.equal(response.status, 201);
  assert.deepEqual(result, {
    id,
    name: "New Org",
    role: "owner",
    createdAt: "2026-11-12T10:00:00.000Z",
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, "POST");
  assert.equal(calls[0].path, "/api/v1/tenants");
  assert.deepEqual(JSON.parse(calls[0].body), { name: "New Org" });
});

test("invalid session, origin, fields and name never reach the issuer", async () => {
  calls = [];
  for (const req of [
    request(valid(), "synthetic-access", { origin: "http://127.0.0.1:3001" }),
    request(valid(), "synthetic-access", { host: "evil.example" }),
    request(valid(), "synthetic-access", { cookie: "" }),
    request(JSON.stringify({ name: "" })),
    request(JSON.stringify({ name: "   " })),
    request(JSON.stringify({ name: "x".repeat(129) })),
    request(JSON.stringify({ name: "Org", extra: true })),
    request('{"name":"Org","name":"Other"}'),
  ]) {
    assert([400, 401, 403].includes((await POST(req)).status));
  }
  assert.equal(calls.length, 0);
});

test("issuer statuses map exactly and malformed acknowledgements fail closed", async () => {
  const cases: [number, number][] = [
    [401, 401],
    [422, 422],
    [429, 429],
    [500, 502],
    [400, 502],
    [201, 502],
  ];
  for (const [upstream, expected] of cases) {
    calls = [];
    status = upstream;
    if (upstream === 201)
      acknowledgement = { ...acknowledgement, role: "member" };
    const response = await POST(
      request(valid(), `token-${upstream}-${Math.random()}`),
    );
    assert.equal(response.status, expected);
    assert.equal(calls.length, 1);
  }
  acknowledgement = { ...acknowledgement, role: "owner", name: "Other" };
  assert.equal((await POST(request(valid(), "mismatch-name"))).status, 502);
});

test("the credential limiter rejects the sixth attempt without an upstream call", async () => {
  calls = [];
  const token = "limit-token";
  for (let attempt = 0; attempt < 5; attempt += 1)
    assert.equal((await POST(request(valid(), token))).status, 201);
  assert.equal(calls.length, 5);
  assert.equal((await POST(request(valid(), token))).status, 429);
  assert.equal(calls.length, 5);
});
