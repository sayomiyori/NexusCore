import { createHash, randomBytes } from "node:crypto";
import type { NextRequest, NextResponse } from "next/server.js";
import { createLoginLimiter } from "../../../lib/login-limit.ts";
import {
  ApiError,
  bearer,
  body,
  challengeCookieName,
  cookie,
  failure,
  guard,
  origin,
  record,
  refreshCookieMaxAge,
  refreshCookieName,
  reply,
  requestJson,
  sessionCookieName,
  singleCookie,
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
        temp_token: bearer(singleCookie(request, challengeCookieName())),
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
      clearAccessCookies(response);
      clearRefreshCookies(response);
      cookie(response, challengeCookieName(), bearer(result.temp_token), 300);
      return response;
    }
    if (result.token_type !== "bearer") throw new ApiError(502);
    // Validate both issuer credentials before setting either cookie. A partial
    // response must not leave a mixed access/refresh pair in the browser.
    const access = bearer(result.access_token);
    const refresh = bearer(result.refresh_token);
    const response = reply({ requires2fa: false });
    cookie(response, sessionCookieName(), access, 900);
    cookie(response, refreshCookieName(), refresh, refreshCookieMaxAge);
    cookie(response, challengeCookieName(), "", 0);
    return response;
  } catch (error) {
    return failure(error);
  }
}

function clearAccessCookies(response: NextResponse): void {
  for (const name of ["__Host-nexus_session", "nexus_session"])
    cookie(response, name, "", 0);
}

function clearRefreshCookies(response: NextResponse): void {
  for (const name of ["__Host-nexus_refresh", "nexus_refresh"])
    cookie(response, name, "", 0);
}

function clearSessionCookies(response: NextResponse): void {
  clearAccessCookies(response);
  for (const name of ["__Host-nexus_challenge", "nexus_challenge"])
    cookie(response, name, "", 0);
  clearRefreshCookies(response);
}

function presentedCredentials(
  request: NextRequest,
  names: Iterable<string>,
): string[] {
  const values = new Set<string>();
  for (const name of new Set(names)) {
    const value = singleCookie(request, name);
    if (value) values.add(value);
  }
  return [...values];
}

export async function DELETE(request: NextRequest) {
  try {
    guard(request, false);
  } catch (error) {
    return failure(error);
  }
  let access: string[], refresh: string[];
  try {
    access = presentedCredentials(request, [
      "__Host-nexus_session",
      "nexus_session",
    ]);
    refresh = presentedCredentials(request, [
      "__Host-nexus_refresh",
      "nexus_refresh",
    ]);
  } catch (error) {
    const response = failure(error);
    clearSessionCookies(response);
    return response;
  }
  let failed = false;
  // Access logout first: AuthFortress authenticates it against the live session.
  // Revoking through the refresh credential first would make a matched access
  // call return 401 and turn a normal logout into a false unconfirmed result.
  for (const credential of access) {
    try {
      await requestJson(
        origin("AUTH"),
        "/api/v1/auth/logout",
        bearer(credential),
        undefined,
        {},
        undefined,
        204,
      );
    } catch {
      failed = true;
    }
  }
  for (const credential of refresh) {
    try {
      await requestJson(
        origin("AUTH"),
        "/api/v1/auth/logout/refresh",
        undefined,
        undefined,
        { refresh_token: bearer(credential) },
        undefined,
        204,
      );
    } catch {
      failed = true;
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
  clearSessionCookies(response);
  return response;
}
