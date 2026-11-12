import { createHash, randomBytes } from "node:crypto";
import type { NextRequest } from "next/server.js";
import { createLoginLimiter } from "../../../lib/login-limit.ts";
import { authorizedTenant } from "../../../lib/overview.ts";
import {
  ApiError,
  bearer,
  body,
  failure,
  guard,
  origin,
  record,
  reply,
  requestJson,
  text,
} from "../../../lib/server.ts";

const salt = randomBytes(16).toString("hex");
const limiter = createLoginLimiter({ limit: 5, windowMs: 60_000 });
const canonical = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;

export async function POST(request: NextRequest) {
  try {
    const token = guard(request),
      params = request.nextUrl.searchParams;
    const tenant = params.get("tenant"),
      bot = params.get("bot");
    if (!token) throw new ApiError(401);
    if (
      params.getAll("tenant").length !== 1 ||
      params.getAll("bot").length !== 1 ||
      [...params.keys()].some((key) => !["tenant", "bot"].includes(key)) ||
      !tenant ||
      !canonical.test(tenant) ||
      !bot ||
      !canonical.test(bot)
    )
      throw new ApiError(400);
    await body(request, []);
    const identity = await authorizedTenant(token, tenant);
    if (identity.role !== "owner") throw new ApiError(403);
    const key = createHash("sha256")
      .update(`${salt}:${bearer(token)}:${bot}`)
      .digest("hex");
    if (!limiter.allow(key).allowed) throw new ApiError(429);
    const result = record(
      await requestJson(
        origin("WEBHOOK"),
        `/api/v1/tenants/${tenant}/bots/${bot}/webhook`,
        token,
        tenant,
        { dry_run: false },
        undefined,
        200,
        { 400: 400, 403: 403, 404: 404, 409: 409, 502: 502, 503: 502 },
      ),
    );
    const rawUrl = text(result.webhook_url, 2048);
    let url: URL;
    try {
      url = new URL(rawUrl);
    } catch {
      throw new ApiError(502);
    }
    // The URL is validated but never returned to the browser.
    if (
      result.tenant_id !== tenant ||
      result.bot_id !== bot ||
      result.webhook_status !== "configured" ||
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      !/^[\x21-\x7e]+$/.test(rawUrl) ||
      rawUrl.includes("?") ||
      rawUrl.includes("#") ||
      url.search ||
      url.hash ||
      url.pathname !== `/webhooks/telegram/${bot}` ||
      !["", "80", "88", "8443"].includes(url.port)
    )
      throw new ApiError(502);
    return reply({ webhookStatus: "configured" });
  } catch (error) {
    return failure(error);
  }
}
