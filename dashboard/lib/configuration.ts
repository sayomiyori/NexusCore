import { authorizedTenant, type Tenant } from "./overview.ts";
import { ApiError, origin, record, requestJson, uuid } from "./server.ts";

export type Configuration = {
  tenant: Tenant;
  bot: string;
  scope: "platform";
  provider: "groq";
  model: string | null;
  processingEnabled: boolean;
};

export async function configuration(
  token: string,
  selected: string,
  botId: string,
): Promise<Configuration> {
  const tenant = await authorizedTenant(token, selected),
    bot = uuid(botId);
  const value = record(
    await requestJson(
      origin("AGENT"),
      `/api/v1/tenants/${tenant.id}/bots/${bot}/ai/configuration`,
      token,
      tenant.id,
    ),
  );
  if (
    value.tenant_id !== tenant.id ||
    value.bot_id !== bot ||
    value.scope !== "platform" ||
    value.provider !== "groq" ||
    typeof value.processing_enabled !== "boolean" ||
    (value.model !== null &&
      (typeof value.model !== "string" ||
        !/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/.test(value.model)))
  )
    throw new ApiError(502);
  return {
    tenant,
    bot,
    scope: "platform",
    provider: "groq",
    model: value.model as string | null,
    processingEnabled: value.processing_enabled,
  };
}
