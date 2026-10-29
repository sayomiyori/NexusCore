import assert from "node:assert/strict";
import http from "node:http";
import { after, before, test } from "node:test";
import { NextRequest } from "next/server.js";
import { POST } from "../app/api/session/route.ts";

let calls = 0;
const server = http.createServer((req, res) => {
  let body = "";
  req.on("data", (chunk) => {
    body += chunk;
  });
  req.on("end", () => {
    calls += 1;
    res.setHeader("Content-Type", "application/json");
    res.statusCode = 401;
    res.end(JSON.stringify({ detail: "Invalid email or password", body }));
  });
});

before(async () => {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert(address && typeof address === "object");
  Object.assign(process.env, {
    DASHBOARD_ORIGIN: "http://127.0.0.1:3000",
    DASHBOARD_AUTH_ORIGIN: `http://127.0.0.1:${address.port}`,
  });
});

after(async () => {
  server.closeAllConnections();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

function login(email: string) {
  return new NextRequest("http://127.0.0.1:3000/api/session", {
    method: "POST",
    body: JSON.stringify({ email, password: "Wrong1pass" }),
    headers: {
      host: "127.0.0.1:3000",
      origin: "http://127.0.0.1:3000",
      "content-type": "application/json",
    },
  });
}

test("one account cannot exhaust another account's login allowance", async () => {
  calls = 0;
  const first = `rate-a-${process.pid}-${Date.now()}@example.com`;
  const second = `rate-b-${process.pid}-${Date.now()}@example.com`;
  for (let attempt = 0; attempt < 5; attempt += 1)
    assert.equal((await POST(login(first))).status, 401);
  assert.equal((await POST(login(first))).status, 429);
  assert.equal((await POST(login(second))).status, 401);
  assert.equal(calls, 6);
});
