import type { NextRequest } from "next/server.js";
import { overview } from "../../../lib/overview.ts";
import { ApiError, failure, guard, reply } from "../../../lib/server.ts";

export async function GET(request: NextRequest) {
  try {
    const token = guard(request),
      values = request.nextUrl.searchParams;
    const tenant = values.get("tenant");
    if (
      values.getAll("tenant").length !== 1 ||
      [...values.keys()].some((key) => key !== "tenant") ||
      !tenant ||
      !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(tenant)
    )
      throw new ApiError(400);
    if (!token) throw new ApiError(401);
    return reply(await overview(token, tenant));
  } catch (error) {
    return failure(error);
  }
}
