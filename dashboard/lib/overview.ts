import { createHash } from "node:crypto";
import {
  ApiError,
  displayName,
  origin,
  record,
  requestJson,
  text,
  uuid,
} from "./server.ts";

export type Tenant = { id: string; name: string; role: "owner" | "member" };
export type Observation = {
  id: string;
  kind: "auth" | "webhook" | "agent";
  at: string;
  bot: string | null;
  state: string;
  attempts?: number;
  receivers: string[];
  conflict: boolean;
};
export type Overview = {
  tenant: Tenant;
  events: Observation[];
  sources: { eventpipe: boolean; pipewatch: boolean };
};
type Evidence = { view: Observation; key: string };

function evidence(view: Observation, raw: Record<string, unknown>): Evidence {
  const payload = Object.fromEntries(
    Object.entries(record(raw.payload)).sort(([a], [b]) => a.localeCompare(b)),
  );
  const canonical = Object.fromEntries(
    Object.entries({ ...raw, payload }).sort(([a], [b]) => a.localeCompare(b)),
  );
  return {
    view,
    key: createHash("sha256").update(JSON.stringify(canonical)).digest("hex"),
  };
}

export function tenantView(value: unknown): Tenant {
  const item = record(value);
  if (item.role !== "owner" && item.role !== "member") throw new ApiError(502);
  return { id: uuid(item.id), name: displayName(item.name), role: item.role };
}

export function timestamp(value: unknown): string {
  const result = text(value, 40);
  if (
    !/^\d{4}-\d\d-\d\dT.+(?:Z|[+-]\d\d:\d\d)$/.test(result) ||
    !Number.isFinite(Date.parse(result))
  )
    throw new ApiError(502);
  // Validate the local calendar separately: a valid offset may cross a UTC day.
  const day = result.slice(0, 10),
    calendar = new Date(`${day}T00:00:00Z`);
  if (
    day.startsWith("0000") ||
    !Number.isFinite(calendar.getTime()) ||
    calendar.toISOString().slice(0, 10) !== day ||
    Number(result.slice(11, 13)) > 23
  )
    throw new ApiError(502);
  return new Date(result).toISOString();
}

function fields(item: Record<string, unknown>, keys: string[]): void {
  if (Object.keys(item).sort().join(",") !== keys.sort().join(","))
    throw new ApiError(502);
}

export function observation(value: unknown, tenant: string): Evidence | null {
  const event = record(value);
  if (typeof event.event_type !== "string") throw new ApiError(502);
  if (
    ![
      "auth.tenant.observed",
      "webhook.bot.observed",
      "ai.job.observed",
    ].includes(event.event_type)
  )
    return null;
  fields(event, [
    "event_id",
    "event_type",
    "schema_version",
    "occurred_at",
    "tenant_id",
    "bot_id",
    "correlation_id",
    "idempotency_key",
    "payload",
  ]);
  const id = uuid(event.event_id),
    payload = record(event.payload);
  if (
    event.tenant_id !== tenant ||
    event.schema_version !== 1 ||
    event.idempotency_key !== id
  )
    throw new ApiError(502);
  uuid(event.correlation_id);
  const at = timestamp(event.occurred_at);
  if (event.event_type === "auth.tenant.observed") {
    fields(payload, ["tenant_created_at", "observed_role"]);
    timestamp(payload.tenant_created_at);
    const role = text(payload.observed_role, 6);
    if (
      event.bot_id !== null ||
      event.correlation_id !== tenant ||
      !["owner", "member"].includes(role)
    )
      throw new ApiError(502);
    return evidence(
      {
        id,
        kind: "auth",
        at,
        bot: null,
        state: role,
        receivers: [],
        conflict: false,
      },
      event,
    );
  }
  const bot = uuid(event.bot_id);
  if (event.event_type === "webhook.bot.observed") {
    fields(payload, ["is_active", "webhook_status"]);
    const status = text(payload.webhook_status, 32);
    if (
      typeof payload.is_active !== "boolean" ||
      ![
        "not_configured",
        "configuring",
        "configured",
        "failed",
        "unknown",
      ].includes(status) ||
      event.correlation_id !== bot
    )
      throw new ApiError(502);
    return evidence(
      {
        id,
        kind: "webhook",
        at,
        bot,
        state: payload.is_active ? status : "inactive",
        receivers: [],
        conflict: false,
      },
      event,
    );
  }
  fields(payload, ["job_id", "ingress_event_id", "state", "attempts"]);
  uuid(payload.job_id);
  const state = text(payload.state, 16);
  if (
    uuid(payload.ingress_event_id) !== event.correlation_id ||
    !["pending", "processing", "completed", "failed", "unknown"].includes(
      state,
    ) ||
    !Number.isInteger(payload.attempts) ||
    Number(payload.attempts) < 0 ||
    Number(payload.attempts) > 2147483647
  )
    throw new ApiError(502);
  return evidence(
    {
      id,
      kind: "agent",
      at,
      bot,
      state,
      attempts: Number(payload.attempts),
      receivers: [],
      conflict: false,
    },
    event,
  );
}

async function eventpipe(token: string, tenant: string): Promise<Evidence[]> {
  const base = origin("EVENTPIPE");
  const rows = await requestJson(
    base,
    "/api/v1/events?source=nexuscore&page=1&size=10",
    token,
    tenant,
  );
  if (!Array.isArray(rows) || rows.length > 10) throw new ApiError(502);
  const seen = new Set<string>();
  const events = await Promise.all(
    rows.map(async (value) => {
      const row = record(value),
        storageId = uuid(row.event_id);
      if (row.source !== "nexuscore" || seen.has(storageId))
        throw new ApiError(502);
      seen.add(storageId);
      const full = record(
        await requestJson(base, `/api/v1/events/${storageId}`, token, tenant),
      );
      if (
        full.event_id !== storageId ||
        full.source !== "nexuscore" ||
        full.event_type !== row.event_type ||
        record(full.payload).event_type !== full.event_type
      )
        throw new ApiError(502);
      const event = observation(full.payload, tenant);
      const metadata = record(full.metadata);
      if (
        event &&
        (metadata.relay_event_id !== event.view.id ||
          (event.view.bot
            ? metadata.bot_id !== event.view.bot
            : metadata.bot_id !== undefined))
      )
        throw new ApiError(502);
      return event;
    }),
  );
  return events.filter((event): event is Evidence => event !== null);
}

async function pipewatch(token: string, tenant: string): Promise<Evidence[]> {
  const page = record(
    await requestJson(
      origin("PIPEWATCH"),
      "/api/v1/logs?service=nexuscore&page=1&size=10",
      token,
      tenant,
    ),
  );
  if (
    !Number.isInteger(page.total) ||
    Number(page.total) < 0 ||
    page.page !== 1 ||
    page.size !== 10 ||
    !Array.isArray(page.items) ||
    page.items.length !== Math.min(Number(page.total), 10)
  )
    throw new ApiError(502);
  return page.items.flatMap((value) => {
    const row = record(value),
      event = observation(row.metadata, tenant);
    if (
      row.service !== "nexuscore" ||
      row.message !== record(row.metadata).event_type ||
      (event && row.trace_id !== event.view.id)
    )
      throw new ApiError(502);
    return event ? [event] : [];
  });
}

export async function authorizedTenant(
  token: string,
  selected: string,
): Promise<Tenant> {
  const tenant = tenantView(
    await requestJson(
      origin("AUTH"),
      `/api/v1/tenants/${uuid(selected)}`,
      token,
    ),
  );
  if (tenant.id !== selected) throw new ApiError(502);
  return tenant;
}

export async function overview(
  token: string,
  selected: string,
): Promise<Overview> {
  const tenant = await authorizedTenant(token, selected);
  const results = await Promise.allSettled([
    eventpipe(token, selected),
    pipewatch(token, selected),
  ]);
  const events = new Map<string, Evidence>();
  results.forEach((result, index) => {
    if (result.status !== "fulfilled") return;
    const receiver = index === 0 ? "EventPipe" : "PipeWatch";
    for (const event of result.value) {
      const existing = events.get(event.view.id);
      if (!existing) {
        events.set(event.view.id, {
          ...event,
          view: { ...event.view, receivers: [receiver] },
        });
        continue;
      }
      existing.view.conflict ||= existing.key !== event.key;
      if (!existing.view.receivers.includes(receiver))
        existing.view.receivers.push(receiver);
    }
  });
  return {
    tenant,
    events: [...events.values()]
      .map((event) => event.view)
      .sort((a, b) => b.at.localeCompare(a.at) || a.id.localeCompare(b.id))
      .slice(0, 10),
    sources: {
      eventpipe: results[0].status === "fulfilled",
      pipewatch: results[1].status === "fulfilled",
    },
  };
}
