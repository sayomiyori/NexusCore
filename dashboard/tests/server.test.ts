import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import http from "node:http";
import { after, before, test } from "node:test";
import { observation, tenantView, timestamp } from "../lib/overview.ts";
import { ApiError, privateOrigin, requestJson } from "../lib/server.ts";

test("small dashboard text and control focus meet WCAG AA contrast", () => {
  const css = readFileSync(
    new URL("../app/globals.css", import.meta.url),
    "utf8",
  );
  const declaration = (selector: string, property: string): string => {
    const start = css.indexOf(`${selector} {`);
    assert(start >= 0, selector);
    const block = css.slice(start, css.indexOf("}", start));
    const value = block.match(
      new RegExp(`(?:^|[;\\s])${property}: ([^;]+);`),
    )?.[1];
    assert(value, `${selector}: ${property}`);
    if (value.startsWith("var("))
      return declaration(":root", value.slice(4, -1));
    return value;
  };
  const luminance = (color: string) => {
    assert(/^#[0-9a-f]{6}$/i.test(color), color);
    const rgb = [1, 3, 5].map((offset) => {
      const n = Number.parseInt(color.slice(offset, offset + 2), 16) / 255;
      return n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
  };
  const check = (foreground: string, background: string, minimum = 4.5) => {
    const a = luminance(foreground),
      b = luminance(background);
    assert(
      (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) >= minimum,
      `${foreground} on ${background}`,
    );
  };
  for (const selector of [
    ".brand-caption",
    ".footer > span",
    ".metric small",
    ".metric p",
    ".connection p",
  ])
    check(declaration(selector, "color"), declaration("body", "background"));
  for (const selector of [
    ".receivers span",
    ".connection-note",
    ".state",
    ".state.attention",
    ".event-icon.webhook",
    ".event-icon.agent",
  ])
    check(declaration(selector, "color"), declaration(selector, "background"));
  check(declaration(".connection-state", "color"), "#ffffff");
  const focus = css.match(/outline: 3px solid (#[0-9a-f]{6})/)?.[1];
  assert(focus);
  check(focus, declaration("body", "background"), 3);
});

const tenant = "00000000-0000-4000-8000-000000000001";
const bot = "00000000-0000-4000-8000-000000000002";
const id = "00000000-0000-4000-8000-000000000003";
const ingress = "00000000-0000-4000-8000-000000000004";
export const job = {
  event_id: id,
  event_type: "ai.job.observed",
  schema_version: 1,
  occurred_at: "2026-10-23T10:00:00+00:00",
  tenant_id: tenant,
  bot_id: bot,
  correlation_id: ingress,
  idempotency_key: id,
  payload: {
    job_id: id,
    ingress_event_id: ingress,
    state: "completed",
    attempts: 1,
  },
};

let base = "";
let calls = 0;
const server = http.createServer((req, res) => {
  calls++;
  res.setHeader("Content-Type", "application/json");
  if (req.url === "/api/v1/redirect") {
    res.writeHead(302, { Location: "/api/v1/data" });
    res.end("{}");
  } else if (req.url === "/api/v1/large")
    res.end(JSON.stringify({ private: "x".repeat(256 * 1024) }));
  else if (req.url === "/api/v1/gzip") {
    res.setHeader("Content-Encoding", "gzip");
    res.end("{}");
  } else if (req.url === "/api/v1/html") {
    res.setHeader("Content-Type", "text/html");
    res.end("private-sentinel");
  } else if (req.url === "/api/v1/invalid") res.end("private-not-json");
  else if (req.url === "/api/v1/hang") {
    /* The client deadline closes this socket. */
  } else res.end(JSON.stringify({ ok: true }));
});
before(async () => {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert(address && typeof address === "object");
  base = `http://127.0.0.1:${address.port}`;
});
after(async () => {
  server.closeAllConnections();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

test("private origins reject public, ambiguous, credential and path targets", () => {
  for (const value of [
    "https://example.com",
    "http://8.8.8.8",
    "http://169.254.169.254",
    "http://127.1",
    "http://2130706433",
    "http://127.0.0.1.",
    "http://127.0.0.1:0",
    "http://u:p@127.0.0.1",
    "http://127.0.0.1/path",
    "http://127.0.0.1?token=private",
    "http://127.0.0.1#private",
    "http://127.0.0.1:",
    "http://127.0.0.1\n",
  ]) {
    assert.throws(() => privateOrigin(value), ApiError);
  }
  for (const value of [
    "http://127.0.0.1:3000",
    "https://10.0.0.1",
    "http://172.31.0.1",
    "http://192.168.4.5",
  ])
    assert(privateOrigin(value));
  assert.throws(() => privateOrigin("http://10.0.0.1", true), ApiError);
});

test("direct bounded transport ignores proxies and never follows redirects", async () => {
  const saved = process.env.HTTP_PROXY;
  process.env.HTTP_PROXY = "http://127.0.0.1:1";
  try {
    assert.deepEqual(await requestJson(base, "/api/v1/data"), { ok: true });
  } finally {
    if (saved === undefined) delete process.env.HTTP_PROXY;
    else process.env.HTTP_PROXY = saved;
  }
  const count = calls;
  await assert.rejects(requestJson(base, "/api/v1/redirect"), ApiError);
  assert.equal(calls, count + 1);
  for (const path of ["large", "gzip", "html", "invalid"])
    await assert.rejects(requestJson(base, `/api/v1/${path}`), ApiError);
});

test("upstream absolute deadline closes an unfinished response", {
  timeout: 10000,
}, async () => {
  await assert.rejects(requestJson(base, "/api/v1/hang"), ApiError);
});

test("minimal tenant projection keeps authorized display text and discards extras", () => {
  assert.deepEqual(
    tenantView({
      id: tenant,
      role: "owner",
      name: "<script>sentinel</script>",
      private: "no",
    }),
    { id: tenant, role: "owner", name: "<script>sentinel</script>" },
  );
  assert.throws(
    () => tenantView({ id: tenant, role: "admin", name: "x" }),
    ApiError,
  );
});

test("observation allowlist validates complete safe scope and typed fields", () => {
  assert.equal(observation(job, tenant)?.view.state, "completed");
  for (const bad of [
    { ...job, tenant_id: bot },
    { ...job, schema_version: true },
    { ...job, private: "secret" },
    { ...job, occurred_at: "2026-10-23T10:00:00" },
    { ...job, idempotency_key: bot },
    { ...job, payload: { ...job.payload, state: ["completed"] } },
    { ...job, payload: { ...job.payload, attempts: true } },
    { ...job, payload: { ...job.payload, answer: "private-answer" } },
    { ...job, event_type: ["ai.job.observed"] },
  ]) {
    assert.throws(() => observation(bad, tenant), ApiError);
  }
  assert.equal(observation({ event_type: "future.unsupported" }, tenant), null);
});

test("stored timestamps reject impossible calendars without rejecting offset day changes", () => {
  for (const value of [
    "2026-02-30T12:34:00Z",
    "2026-04-31T12:34:00Z",
    "2026-02-29T12:34:00Z",
    "2024-02-29T24:00:00Z",
    "0000-01-01T00:00:00Z",
  ]) {
    assert.throws(() => timestamp(value), ApiError);
    assert.throws(
      () => observation({ ...job, occurred_at: value }, tenant),
      ApiError,
    );
  }
  assert.equal(
    timestamp("2024-02-29T23:59:59.123456-03:00"),
    "2024-03-01T02:59:59.123Z",
  );
  assert.equal(
    timestamp("2026-03-01T00:00:00+03:00"),
    "2026-02-28T21:00:00.000Z",
  );
});

test("all observation types preserve full-content conflict keys without exporting payloads", () => {
  const auth = {
    ...job,
    event_type: "auth.tenant.observed",
    bot_id: null,
    correlation_id: tenant,
    payload: {
      tenant_created_at: "2026-10-21T09:00:00Z",
      observed_role: "owner",
    },
  };
  assert.equal(observation(auth, tenant)?.view.bot, null);
  const webhook = {
    ...job,
    event_type: "webhook.bot.observed",
    correlation_id: bot,
    payload: { is_active: false, webhook_status: "failed" },
  };
  const first = observation(webhook, tenant);
  const changed = observation(
    { ...webhook, payload: { is_active: false, webhook_status: "unknown" } },
    tenant,
  );
  assert.equal(first?.view.state, "inactive");
  assert.notEqual(first?.key, changed?.key);
  assert(!JSON.stringify(first?.view).includes("webhook_status"));
  const reordered = {
    ...job,
    payload: Object.fromEntries(Object.entries(job.payload).reverse()),
  };
  assert.equal(
    observation(job, tenant)?.key,
    observation(reordered, tenant)?.key,
  );
});
