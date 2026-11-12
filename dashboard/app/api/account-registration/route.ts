import { createHash, randomBytes } from "node:crypto";
import type { NextRequest } from "next/server.js";
import { createLoginLimiter } from "../../../lib/login-limit.ts";
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

// Per-process salt: the limiter key never contains the email and cannot be
// replayed against another dashboard process.
const salt = randomBytes(16).toString("hex");
const perEmail = createLoginLimiter({ limit: 5, windowMs: 60_000 });
const perProcess = createLoginLimiter({ limit: 20, windowMs: 60_000 });
const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export async function POST(request: NextRequest) {
  try {
    guard(request, false);
    const input = await body(request, ["email", "username", "password"]);
    const email =
      typeof input.email === "string" ? input.email.trim().toLowerCase() : "";
    const username =
      typeof input.username === "string" ? input.username.trim() : "";
    const password = typeof input.password === "string" ? input.password : "";
    if (
      !email ||
      email.length > 254 ||
      !emailPattern.test(email) ||
      !username ||
      Array.from(username).length > 128 ||
      password.length < 1 ||
      password.length > 1024
    )
      throw new ApiError(400);
    const key = createHash("sha256").update(`${salt}:${email}`).digest("hex");
    if (!perEmail.allow(key).allowed || !perProcess.allow("process").allowed)
      throw new ApiError(429);
    const result = record(
      await requestJson(
        origin("AUTH"),
        "/api/v1/auth/register",
        undefined,
        undefined,
        { email, username, password },
        undefined,
        200,
        { 400: 400, 409: 409, 422: 400, 429: 429 },
      ),
    );
    // The issuer echoes the normalized email; anything else is a bad peer.
    if (text(result.user_id, 64) && result.email !== email)
      throw new ApiError(502);
    // No email, username, password or issuer detail is echoed back.
    return reply({ registered: true }, 201);
  } catch (error) {
    return failure(error);
  }
}
