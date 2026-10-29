import { createHash, randomBytes } from "node:crypto";
import type { NextRequest } from "next/server.js";
import { createLoginLimiter } from "../../../lib/login-limit.ts";
import {
  ApiError,
  bearer,
  body,
  cookie,
  failure,
  guard,
  origin,
  record,
  reply,
  requestJson,
} from "../../../lib/server.ts";

const loginLimiter = createLoginLimiter({ limit: 5, windowMs: 60_000 });
const loginSalt = randomBytes(32);

export async function POST(request: NextRequest) {
  try {
    guard(request, false);
    const input = await body(request);
    let path: string, credentials: Record<string, string>;
    if (
      Object.keys(input).sort().join(",") === "email,password" &&
      typeof input.email === "string" &&
      input.email.length <= 254 &&
      /^[^\s@]+@[^\s@]+$/.test(input.email) &&
      typeof input.password === "string" &&
      input.password.length > 0 &&
      input.password.length <= 1024
    ) {
      const key = createHash("sha256")
        .update(loginSalt)
        .update(input.email.trim().toLowerCase())
        .digest("hex");
      if (!loginLimiter.allow(key).allowed) throw new ApiError(429);
      path = "/api/v1/auth/login";
      credentials = { email: input.email, password: input.password };
    } else if (
      Object.keys(input).join(",") === "code" &&
      typeof input.code === "string" &&
      input.code.length >= 4 &&
      input.code.length <= 32
    ) {
      path = "/api/v1/auth/login/2fa";
      credentials = {
        temp_token: bearer(request.cookies.get("nexus_challenge")?.value),
        code: input.code,
      };
    } else {
      throw new ApiError(400);
    }
    const result = record(
      await requestJson(
        origin("AUTH"),
        path,
        undefined,
        undefined,
        credentials,
      ),
    );
    if (result.requires_2fa === true) {
      const response = reply({ requires2fa: true });
      cookie(response, "nexus_session", "", 0);
      cookie(response, "nexus_challenge", bearer(result.temp_token), 300);
      return response;
    }
    if (result.token_type !== "bearer") throw new ApiError(502);
    const response = reply({ requires2fa: false });
    cookie(response, "nexus_session", bearer(result.access_token), 900);
    cookie(response, "nexus_challenge", "", 0);
    return response;
  } catch (error) {
    return failure(error);
  }
}

export async function DELETE(request: NextRequest) {
  try {
    guard(request, false);
  } catch (error) {
    return failure(error);
  }
  let failed = false;
  const token = request.cookies.get("nexus_session")?.value;
  if (token) {
    try {
      await requestJson(
        origin("AUTH"),
        "/api/v1/auth/logout",
        bearer(token),
        undefined,
        {},
      );
    } catch (error) {
      failed = !(error instanceof ApiError && error.status === 401);
    }
  }
  const response = reply(
    failed
      ? {
          error:
            "Local session cleared; issuer sign-out could not be confirmed.",
        }
      : { signedOut: true },
    failed ? 502 : 200,
  );
  cookie(response, "nexus_session", "", 0);
  cookie(response, "nexus_challenge", "", 0);
  return response;
}
