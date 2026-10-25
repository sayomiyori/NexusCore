import { authorizedTenant, type Tenant, timestamp } from "./overview.ts";
import { ApiError, origin, record, requestJson, uuid } from "./server.ts";

export type Job = {
  id: string;
  eventId: string;
  state: "pending" | "processing" | "completed" | "failed" | "unknown";
  attempts: number;
  created: string;
  updated: string;
};
export type JobPage = {
  tenant: Tenant;
  bot: string;
  items: Job[];
  nextCursor: string | null;
};

export async function jobs(
  token: string,
  selected: string,
  botId: string,
  cursor: string | null,
): Promise<JobPage> {
  const tenant = await authorizedTenant(token, selected),
    bot = uuid(botId);
  const page = record(
    await requestJson(
      origin("AGENT"),
      `/api/v1/tenants/${tenant.id}/bots/${bot}/ai/jobs?limit=50${cursor ? `&cursor=${uuid(cursor)}` : ""}`,
      token,
      tenant.id,
    ),
  );
  if (!Array.isArray(page.items) || page.items.length > 50)
    throw new ApiError(502);
  let previous = cursor || "";
  const seenEvents = new Set<string>();
  const items = page.items.map((value): Job => {
    const item = record(value),
      id = uuid(item.id),
      eventId = uuid(item.event_id);
    if (
      id <= previous ||
      seenEvents.has(eventId) ||
      typeof item.state !== "string" ||
      !["pending", "processing", "completed", "failed", "unknown"].includes(
        item.state,
      ) ||
      !Number.isInteger(item.attempts) ||
      Number(item.attempts) < 0 ||
      Number(item.attempts) > 2147483647
    )
      throw new ApiError(502);
    previous = id;
    seenEvents.add(eventId);
    return {
      id,
      eventId,
      state: item.state as Job["state"],
      attempts: Number(item.attempts),
      created: timestamp(item.created_at),
      updated: timestamp(item.updated_at),
    };
  });
  const nextCursor = page.next_cursor === null ? null : uuid(page.next_cursor);
  if (
    nextCursor &&
    (items.length !== 50 || nextCursor !== items[items.length - 1].id)
  )
    throw new ApiError(502);
  return { tenant, bot, items, nextCursor };
}
