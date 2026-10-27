import type { NextRequest } from "next/server.js";
import { knowledge } from "../../../lib/knowledge.ts";
import { ApiError, failure, guard, reply } from "../../../lib/server.ts";

export async function GET(request: NextRequest) {
  try {
    const token = guard(request),
      values = request.nextUrl.searchParams;
    const tenant = values.get("tenant"),
      offset = values.get("offset") ?? "0";
    if (
      values.getAll("tenant").length !== 1 ||
      values.getAll("offset").length > 1 ||
      [...values.keys()].some((key) => !["tenant", "offset"].includes(key)) ||
      !tenant ||
      !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(tenant) ||
      !/^(0|[1-9][0-9]{0,6})$/.test(offset) ||
      Number(offset) > 1000000
    )
      throw new ApiError(400);
    if (!token) throw new ApiError(401);
    return reply(await knowledge(token, tenant, Number(offset)));
  } catch (error) {
    return failure(error);
  }
}
