import type { NextRequest } from "next/server.js";
import { configuration } from "../../../lib/configuration.ts";
import { ApiError, failure, guard, reply } from "../../../lib/server.ts";

export async function GET(request: NextRequest) {
  try {
    const token = guard(request),
      values = request.nextUrl.searchParams;
    const tenant = values.get("tenant"),
      bot = values.get("bot");
    const canonical = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
    if (
      values.getAll("tenant").length !== 1 ||
      values.getAll("bot").length !== 1 ||
      [...values.keys()].some((key) => !["tenant", "bot"].includes(key)) ||
      !tenant ||
      !bot ||
      !canonical.test(tenant) ||
      !canonical.test(bot)
    )
      throw new ApiError(400);
    if (!token) throw new ApiError(401);
    return reply(await configuration(token, tenant, bot));
  } catch (error) {
    return failure(error);
  }
}
