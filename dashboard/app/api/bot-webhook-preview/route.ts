import type { NextRequest } from "next/server.js";
import { authorizedTenant } from "../../../lib/overview.ts";
import {
  ApiError,
  body,
  failure,
  guard,
  origin,
  record,
  reply,
  requestJson,
  text,
} from "../../../lib/server.ts";

export async function POST(request: NextRequest) {
  try {
    const token = guard(request),
      params = request.nextUrl.searchParams;
    const tenant = params.get("tenant"),
      bot = params.get("bot");
    const canonical = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
    if (!token) throw new ApiError(401);
    if (
      params.getAll("tenant").length !== 1 ||
      params.getAll("bot").length !== 1 ||
      [...params.keys()].some((k) => !["tenant", "bot"].includes(k)) ||
      !tenant ||
      !canonical.test(tenant) ||
      !bot ||
      !canonical.test(bot)
    )
      throw new ApiError(400);
    await body(request, []);
    const identity = await authorizedTenant(token, tenant);
    if (identity.role !== "owner") throw new ApiError(403);
    const result = record(
      await requestJson(
        origin("WEBHOOK"),
        `/api/v1/tenants/${tenant}/bots/${bot}/webhook`,
        token,
        tenant,
        { dry_run: true },
      ),
    );
    const rawUrl = text(result.webhook_url, 2048);
    let url: URL;
    try {
      url = new URL(rawUrl);
    } catch {
      throw new ApiError(502);
    }
    if (
      result.tenant_id !== tenant ||
      result.bot_id !== bot ||
      result.operation !== "setWebhook" ||
      result.dry_run !== true ||
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
    return reply({ bot, ready: true });
  } catch (error) {
    return failure(error);
  }
}
