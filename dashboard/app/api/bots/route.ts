import type { NextRequest } from "next/server.js";
import { bots } from "../../../lib/bots.ts";
import { ApiError, failure, guard, reply } from "../../../lib/server.ts";

export async function GET(request: NextRequest) {
  try {
    const token = guard(request),
      values = request.nextUrl.searchParams;
    const tenant = values.get("tenant"),
      cursor = values.get("cursor");
    const canonical = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
    if (
      values.getAll("tenant").length !== 1 ||
      values.getAll("cursor").length > 1 ||
      [...values.keys()].some((key) => !["tenant", "cursor"].includes(key)) ||
      !tenant ||
      !canonical.test(tenant) ||
      (cursor !== null && !canonical.test(cursor))
    )
      throw new ApiError(400);
    if (!token) throw new ApiError(401);
    return reply(await bots(token, tenant, cursor));
  } catch (error) {
    return failure(error);
  }
}
