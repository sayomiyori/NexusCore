import type { NextRequest } from "next/server.js";
import { tenantView } from "../../../lib/overview.ts";
import {
  ApiError,
  failure,
  guard,
  origin,
  reply,
  requestJson,
} from "../../../lib/server.ts";

export async function GET(request: NextRequest) {
  try {
    const token = guard(request),
      values = request.nextUrl.searchParams;
    if (
      [...values.keys()].some((key) => key !== "offset") ||
      values.getAll("offset").length > 1
    )
      throw new ApiError(400);
    const offset = values.get("offset") || "0";
    if (!/^\d{1,6}$/.test(offset) || Number(offset) > 100000)
      throw new ApiError(400);
    const rows = await requestJson(
      origin("AUTH"),
      `/api/v1/tenants?offset=${Number(offset)}&limit=50`,
      token,
    );
    if (!Array.isArray(rows) || rows.length > 50) throw new ApiError(502);
    const items = rows.map(tenantView);
    if (new Set(items.map((item) => item.id)).size !== items.length)
      throw new ApiError(502);
    return reply({
      items,
      hasMore: items.length === 50,
      offset: Number(offset),
    });
  } catch (error) {
    return failure(error);
  }
}
