import type { NextRequest } from "next/server.js";
import { ApiError, failure, guard, reply } from "../../../lib/server.ts";
import { usage, usageRange } from "../../../lib/usage.ts";

export async function GET(request: NextRequest) {
  try {
    const token = guard(request),
      values = request.nextUrl.searchParams;
    const keys = ["tenant", "bot", "start", "end"];
    if (
      keys.some((key) => values.getAll(key).length !== 1) ||
      [...values.keys()].some((key) => !keys.includes(key))
    )
      throw new ApiError(400);
    const tenant = values.get("tenant"),
      bot = values.get("bot"),
      start = values.get("start"),
      end = values.get("end");
    const canonical = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
    if (
      !tenant ||
      !bot ||
      !start ||
      !end ||
      !canonical.test(tenant) ||
      !canonical.test(bot)
    )
      throw new ApiError(400);
    const range = usageRange(start, end);
    if (!token) throw new ApiError(401);
    return reply(await usage(token, tenant, bot, range));
  } catch (error) {
    return failure(error);
  }
}
