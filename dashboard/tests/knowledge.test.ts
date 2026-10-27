import assert from "node:assert/strict";
import http from "node:http";
import { after, before, beforeEach, test } from "node:test";
import { NextRequest } from "next/server.js";
import { GET } from "../app/api/knowledge/route.ts";

const tenant = "00000000-0000-4000-8000-000000000001";
const browser = "http://127.0.0.1:3000";
let rows: unknown,
  status = 200,
  agentStatus = 200,
  issuerTenant = tenant,
  calls: string[] = [],
  base = "";
const doc = (id = 1) => ({
  id,
  title: "A document",
  content_type: "txt",
  upload_status: "ready",
  chunk_count: 3,
  file_path: "private-path",
});
const server = http.createServer((req, res) => {
  const path = req.url || "";
  calls.push(path);
  assert.equal(req.method, "GET");
  assert.equal(req.headers.authorization, "Bearer synthetic-access");
  res.setHeader("content-type", "application/json");
  if (path.includes("/documents?")) {
    assert.equal(req.headers["x-tenant-id"], tenant);
    res.statusCode = agentStatus;
    res.end(JSON.stringify(rows));
  } else {
    res.statusCode = status;
    res.end(
      JSON.stringify(
        status === 200
          ? { id: issuerTenant, name: "Tenant", role: "member" }
          : {},
      ),
    );
  }
});
before(async () => {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert(address && typeof address === "object");
  base = `http://127.0.0.1:${address.port}`;
  Object.assign(process.env, {
    DASHBOARD_ORIGIN: browser,
    DASHBOARD_AUTH_ORIGIN: base,
    DASHBOARD_AGENT_ORIGIN: base,
  });
});
beforeEach(() => {
  rows = [doc()];
  status = 200;
  agentStatus = 200;
  issuerTenant = tenant;
  calls = [];
});
after(async () => {
  server.closeAllConnections();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});
function request(query = `tenant=${tenant}`) {
  return new NextRequest(`${browser}/api/knowledge?${query}`, {
    headers: {
      host: "127.0.0.1:3000",
      cookie: "nexus_session=synthetic-access",
    },
  });
}
test("knowledge projects authorized document metadata and excludes paths", async () => {
  const response = await GET(request());
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.deepEqual(body.items, [
    { id: 1, title: "A document", type: "txt", status: "ready", chunks: 3 },
  ]);
  assert(!JSON.stringify(body).includes("private-path"));
  assert.equal(
    calls.at(-1),
    `/api/v1/tenants/${tenant}/documents?offset=0&limit=50`,
  );
});
test("knowledge denies foreign access before reading documents", async () => {
  status = 403;
  assert.equal((await GET(request())).status, 403);
  assert.equal(calls.length, 1);
});
test("knowledge fails closed on changed issuer scope and agent outage", async () => {
  issuerTenant = "00000000-0000-4000-8000-000000000002";
  assert.equal((await GET(request())).status, 502);
  assert.equal(calls.length, 1);
  issuerTenant = tenant;
  agentStatus = 503;
  assert.equal((await GET(request())).status, 502);
  status = 401;
  assert.equal((await GET(request())).status, 401);
});
test("knowledge validates pagination and upstream metadata", async () => {
  for (const query of [
    `tenant=${tenant}&offset=-1`,
    `tenant=${tenant}&offset=01`,
    `tenant=${tenant}&offset=0&offset=1`,
  ])
    assert.equal((await GET(request(query))).status, 400);
  assert.equal(calls.length, 0);
  for (const invalid of [
    [doc(2), doc(1)],
    [{ ...doc(), upload_status: "other" }],
    [{ ...doc(), chunk_count: -1 }],
    Array.from({ length: 51 }, (_, i) => doc(i + 1)),
  ]) {
    rows = invalid;
    assert.equal((await GET(request())).status, 502);
  }
  rows = Array.from({ length: 50 }, (_, i) => doc(i + 1));
  assert.equal((await (await GET(request())).json()).nextOffset, 50);
  assert.equal(
    (await (await GET(request(`tenant=${tenant}&offset=999999`))).json())
      .nextOffset,
    null,
  );
});
