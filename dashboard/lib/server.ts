import http from "node:http";
import https from "node:https";
import { isIPv4 } from "node:net";
import { type NextRequest, NextResponse } from "next/server.js";

export class ApiError extends Error {
  status: number;
  constructor(status: number) {
    super("Dashboard request failed");
    this.status = status;
  }
}

export function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new ApiError(502);
  return value as Record<string, unknown>;
}

export function text(value: unknown, max = 8192): string {
  if (typeof value !== "string" || !value.length || value.length > max)
    throw new ApiError(502);
  return value;
}

export function uuid(value: unknown): string {
  const result = text(value, 36);
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      result,
    )
  )
    throw new ApiError(502);
  return result;
}

export function privateOrigin(
  value: string | undefined,
  loopback = false,
): string {
  if (!value || !/^[\x21-\x7e]+$/.test(value)) throw new ApiError(503);
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new ApiError(503);
  }
  const octets = url.hostname.split(".").map(Number);
  const explicit = value.match(/^https?:\/\/([0-9.]+)(?::[0-9]+)?\/?$/);
  if (
    !isIPv4(url.hostname) ||
    (loopback
      ? octets[0] !== 127
      : !(
          octets[0] === 127 ||
          octets[0] === 10 ||
          (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31) ||
          (octets[0] === 192 && octets[1] === 168)
        )) ||
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash ||
    url.port === "0" ||
    explicit?.[1] !== url.hostname
  ) {
    throw new ApiError(503);
  }
  return url.origin;
}

export function origin(
  role: "AUTH" | "EVENTPIPE" | "PIPEWATCH" | "WEBHOOK",
): string {
  return privateOrigin(process.env[`DASHBOARD_${role}_ORIGIN`]);
}

export function bearer(value: unknown): string {
  if (
    typeof value !== "string" ||
    !value.length ||
    value.length > 8192 ||
    !/^[\x21-\x7e]+$/.test(value)
  )
    throw new ApiError(401);
  return value;
}

export function guard(
  request: NextRequest,
  session = true,
): string | undefined {
  const expected = privateOrigin(process.env.DASHBOARD_ORIGIN, true);
  if (
    request.headers.get("host") !== new URL(expected).host ||
    (request.method !== "GET" && request.headers.get("origin") !== expected)
  )
    throw new ApiError(403);
  if (!session) return undefined;
  const token = request.cookies.get("nexus_session")?.value;
  if (!token) throw new ApiError(401);
  return bearer(token);
}

export function reply(data: unknown, status = 200): NextResponse {
  return NextResponse.json(data, {
    status,
    headers: {
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

export function failure(error: unknown): NextResponse {
  const status = error instanceof ApiError ? error.status : 502;
  return reply(
    {
      error:
        status === 401
          ? "Sign in to continue."
          : status === 403 || status === 404
            ? "Access denied."
            : status === 429
              ? "Too many attempts. Try again later."
              : status === 400
                ? "Check the submitted values."
                : "Data is temporarily unavailable.",
    },
    status,
  );
}

export function cookie(
  response: NextResponse,
  name: string,
  value: string,
  maxAge: number,
): void {
  response.cookies.set(name, value, {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge,
  });
}

export async function body(
  request: NextRequest,
): Promise<Record<string, unknown>> {
  if (
    !/^application\/json(?:;|$)/i.test(
      request.headers.get("content-type") || "",
    )
  )
    throw new ApiError(400);
  const reader = request.body?.getReader();
  if (!reader) throw new ApiError(400);
  const chunks: Uint8Array[] = [];
  let size = 0,
    expired = false;
  const timer = setTimeout(() => {
    expired = true;
    void reader.cancel().catch(() => {});
  }, 5000);
  timer.unref();
  try {
    while (true) {
      const result = await reader.read();
      if (result.done) break;
      size += result.value.byteLength;
      if (size > 16 * 1024) throw new ApiError(400);
      chunks.push(result.value);
    }
    if (expired) throw new ApiError(400);
    return record(JSON.parse(Buffer.concat(chunks).toString("utf8")));
  } catch {
    await reader.cancel().catch(() => {});
    throw new ApiError(400);
  } finally {
    clearTimeout(timer);
    reader.releaseLock();
  }
}

export function requestJson(
  base: string,
  path: string,
  token?: string,
  tenant?: string,
  payload?: unknown,
): Promise<unknown> {
  const target = privateOrigin(base) + path;
  if (!path.startsWith("/api/v1/") || path.includes("#"))
    throw new ApiError(502);
  return new Promise((resolve, reject) => {
    const encoded = payload === undefined ? undefined : JSON.stringify(payload);
    const req = (target.startsWith("https:") ? https : http).request(
      target,
      {
        method: encoded === undefined ? "GET" : "POST",
        agent: false,
        headers: {
          Accept: "application/json",
          "Accept-Encoding": "identity",
          ...(token ? { Authorization: `Bearer ${bearer(token)}` } : {}),
          ...(tenant ? { "X-Tenant-ID": uuid(tenant) } : {}),
          ...(encoded
            ? {
                "Content-Type": "application/json",
                "Content-Length": Buffer.byteLength(encoded),
              }
            : {}),
        },
      },
      (res) => {
        const status = res.statusCode || 502;
        const chunks: Buffer[] = [];
        let size = 0;
        if (
          res.headers["content-encoding"] &&
          res.headers["content-encoding"] !== "identity"
        ) {
          req.destroy(new ApiError(502));
          return;
        }
        res.on("data", (chunk: Buffer) => {
          size += chunk.length;
          if (size > 256 * 1024) req.destroy(new ApiError(502));
          else chunks.push(chunk);
        });
        res.on("error", () => {
          clearTimeout(timer);
          reject(new ApiError(502));
        });
        res.on("end", () => {
          clearTimeout(timer);
          if (status !== 200 && status !== 204) {
            reject(
              new ApiError(
                status === 422
                  ? 400
                  : [400, 401, 403, 404, 429].includes(status)
                    ? status
                    : 502,
              ),
            );
            return;
          }
          if (status === 204) {
            resolve(null);
            return;
          }
          if (
            !/^application\/json(?:;|$)/i.test(
              res.headers["content-type"] || "",
            )
          ) {
            reject(new ApiError(502));
            return;
          }
          try {
            resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
          } catch {
            reject(new ApiError(502));
          }
        });
      },
    );
    const timer = setTimeout(() => req.destroy(new ApiError(502)), 5000);
    timer.unref();
    req.on("error", (error) => {
      clearTimeout(timer);
      reject(error instanceof ApiError ? error : new ApiError(502));
    });
    req.end(encoded);
  });
}
