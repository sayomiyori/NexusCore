import type { NextRequest } from "next/server.js";
import { authorizedTenant, timestamp } from "../../../lib/overview.ts";
import {
  ApiError,
  body,
  displayName,
  failure,
  guard,
  origin,
  record,
  reply,
  requestJson,
  uuid,
} from "../../../lib/server.ts";

export async function POST(request: NextRequest) {
  try {
    const token = guard(request);
    const params = request.nextUrl.searchParams;
    const tenantId = params.get("tenant");
    if (!token) throw new ApiError(401);
    if (
      params.getAll("tenant").length !== 1 ||
      [...params.keys()].some((key) => key !== "tenant") ||
      !tenantId ||
      !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(tenantId)
    )
      throw new ApiError(400);
    const input = await body(request, ["name", "token"]);
    if (typeof input.name !== "string" || typeof input.token !== "string")
      throw new ApiError(400);
    const name = input.name.trim();
    if (
      !name ||
      Array.from(name).length > 128 ||
      input.token.length > 256 ||
      !/^[0-9]+:[A-Za-z0-9_-]+$/.test(input.token)
    )
      throw new ApiError(400);
    const tenant = await authorizedTenant(token, tenantId);
    if (tenant.role !== "owner") throw new ApiError(403);
    const result = record(
      await requestJson(
        origin("WEBHOOK"),
        `/api/v1/tenants/${tenant.id}/bots`,
        token,
        tenant.id,
        { name, token: input.token },
        undefined,
        201,
      ),
    );
    const id = uuid(result.id);
    if (
      result.tenant_id !== tenant.id ||
      displayName(result.name) !== name ||
      result.is_active !== true ||
      result.webhook_status !== "not_configured"
    )
      throw new ApiError(502);
    return reply(
      {
        bot: {
          id,
          name,
          active: true,
          webhook: "not_configured",
          created: timestamp(result.created_at),
          updated: timestamp(result.updated_at),
        },
      },
      201,
    );
  } catch (error) {
    return failure(error);
  }
}
