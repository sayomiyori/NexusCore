import { authorizedTenant, type Tenant, timestamp } from "./overview.ts";
import { ApiError, origin, record, requestJson, text, uuid } from "./server.ts";

export type Bot = {
  id: string;
  name: string;
  active: boolean;
  webhook:
    | "not_configured"
    | "configuring"
    | "configured"
    | "failed"
    | "unknown";
  created: string;
  updated: string;
};
export type BotPage = {
  tenant: Tenant;
  items: Bot[];
  nextCursor: string | null;
};

export async function bots(
  token: string,
  selected: string,
  cursor: string | null,
): Promise<BotPage> {
  const tenant = await authorizedTenant(token, selected);
  const page = record(
    await requestJson(
      origin("WEBHOOK"),
      `/api/v1/tenants/${tenant.id}/bots?limit=50${cursor ? `&cursor=${uuid(cursor)}` : ""}`,
      token,
      tenant.id,
    ),
  );
  if (!Array.isArray(page.items) || page.items.length > 50)
    throw new ApiError(502);
  let previous = cursor || "";
  const items = page.items.map((value): Bot => {
    const item = record(value),
      id = uuid(item.id);
    // The backend counts Unicode code points; JavaScript length counts UTF-16 units.
    const name = text(item.name, 256);
    if (
      item.tenant_id !== tenant.id ||
      id <= previous ||
      Array.from(name).length > 128 ||
      typeof item.is_active !== "boolean" ||
      typeof item.webhook_status !== "string" ||
      ![
        "not_configured",
        "configuring",
        "configured",
        "failed",
        "unknown",
      ].includes(item.webhook_status)
    )
      throw new ApiError(502);
    previous = id;
    return {
      id,
      name,
      active: item.is_active,
      webhook: item.webhook_status as Bot["webhook"],
      created: timestamp(item.created_at),
      updated: timestamp(item.updated_at),
    };
  });
  const nextCursor = items.length === 50 ? items[items.length - 1].id : null;
  if (page.next_cursor !== nextCursor) throw new ApiError(502);
  return { tenant, items, nextCursor };
}
