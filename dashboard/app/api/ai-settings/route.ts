import type { NextRequest } from "next/server.js";
import { aiSettings, modelIdentifier } from "../../../lib/ai-settings.ts";
import { ApiError, body, failure, guard, reply } from "../../../lib/server.ts";

function scope(request: NextRequest) {
  const token = guard(request),
    params = request.nextUrl.searchParams;
  const tenant = params.get("tenant"),
    bot = params.get("bot");
  const canonical = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
  if (
    params.getAll("tenant").length !== 1 ||
    params.getAll("bot").length > 1 ||
    [...params.keys()].some((key) => !["tenant", "bot"].includes(key)) ||
    !tenant ||
    !canonical.test(tenant) ||
    (bot !== null && !canonical.test(bot))
  )
    throw new ApiError(400);
  if (!token) throw new ApiError(401);
  return { token, tenant, bot };
}

export async function GET(request: NextRequest) {
  try {
    const { token, tenant, bot } = scope(request);
    return reply(await aiSettings(token, tenant, bot));
  } catch (error) {
    return failure(error);
  }
}

export async function PUT(request: NextRequest) {
  try {
    const { token, tenant, bot } = scope(request);
    const value = await body(request, ["model", "expectedRevision"]);
    let model: string | null;
    try {
      model = modelIdentifier(value.model);
    } catch {
      throw new ApiError(400);
    }
    if (
      typeof value.expectedRevision !== "number" ||
      !Number.isInteger(value.expectedRevision) ||
      value.expectedRevision < 0 ||
      value.expectedRevision >= 2147483647
    )
      throw new ApiError(400);
    return reply(
      await aiSettings(token, tenant, bot, {
        model,
        expected_revision: value.expectedRevision,
      }),
    );
  } catch (error) {
    return failure(error);
  }
}
