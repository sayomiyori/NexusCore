import { createHash, randomBytes } from "node:crypto";
import type { NextRequest } from "next/server.js";
import { createLoginLimiter } from "../../../lib/login-limit.ts";
import { timestamp } from "../../../lib/overview.ts";
import {
  ApiError,
  bearer,
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

// Per-process salt: the limiter key never contains the access credential.
const salt = randomBytes(16).toString("hex");
const limiter = createLoginLimiter({ limit: 5, windowMs: 60_000 });

export async function POST(request: NextRequest) {
  try {
    const token = guard(request);
    const input = await body(request, ["name"]);
    const name = typeof input.name === "string" ? input.name.trim() : "";
    if (!name || Array.from(name).length > 128) throw new ApiError(400);
    const key = createHash("sha256")
      .update(`${salt}:${bearer(token)}`)
      .digest("hex");
    if (!limiter.allow(key).allowed) throw new ApiError(429);
    const result = record(
      await requestJson(
        origin("AUTH"),
        "/api/v1/tenants",
        token,
        undefined,
        { name },
        undefined,
        201,
        { 401: 401, 422: 422, 429: 429 },
      ),
    );
    const id = uuid(result.id);
    const createdAt = timestamp(result.created_at);
    if (result.role !== "owner" || displayName(result.name) !== name)
      throw new ApiError(502);
    return reply({ id, name, role: "owner", createdAt }, 201);
  } catch (error) {
    return failure(error);
  }
}
