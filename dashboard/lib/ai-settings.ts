import { authorizedTenant, type Tenant, timestamp } from "./overview.ts";
import { ApiError, origin, record, requestJson, uuid } from "./server.ts";

export type AISettings = {
  tenant: Tenant;
  bot: string | null;
  target: "tenant" | "bot";
  saved: { model: string | null; revision: number; updatedAt: string | null };
  effective: {
    scope: "platform" | "tenant" | "bot";
    provider: "groq";
    model: string | null;
  };
  processingEnabled: boolean;
};

export function modelIdentifier(value: unknown): string | null {
  if (value === null) return null;
  if (
    typeof value !== "string" ||
    !/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/.test(value)
  )
    throw new ApiError(502);
  return value;
}

export async function aiSettings(
  token: string,
  selected: string,
  selectedBot: string | null,
  input?: { model: string | null; expected_revision: number },
): Promise<AISettings> {
  const tenant = await authorizedTenant(token, selected),
    bot = selectedBot === null ? null : uuid(selectedBot);
  if (input && tenant.role !== "owner") throw new ApiError(403);
  const path = `/api/v1/tenants/${tenant.id}${bot ? `/bots/${bot}` : ""}/ai/settings`;
  const value = record(
    await requestJson(
      origin("AGENT"),
      path,
      token,
      tenant.id,
      input,
      input ? "PUT" : undefined,
    ),
  );
  const saved = record(value.saved),
    effective = record(value.effective);
  const target = bot === null ? "tenant" : "bot",
    savedModel = modelIdentifier(saved.model);
  if (
    value.tenant_id !== tenant.id ||
    value.bot_id !== bot ||
    value.target !== target ||
    typeof value.processing_enabled !== "boolean" ||
    typeof saved.revision !== "number" ||
    !Number.isInteger(saved.revision) ||
    saved.revision < 0 ||
    saved.revision > 2147483647 ||
    (saved.revision === 0
      ? saved.updated_at !== null || savedModel !== null
      : saved.updated_at === null) ||
    typeof effective.scope !== "string" ||
    !["platform", "tenant", "bot"].includes(effective.scope) ||
    effective.provider !== "groq" ||
    (target === "tenant" && effective.scope === "bot") ||
    (savedModel === null && effective.scope === target) ||
    (input &&
      (saved.revision !== input.expected_revision + 1 ||
        savedModel !== input.model)) ||
    (savedModel !== null &&
      (effective.scope !== target || effective.model !== savedModel))
  )
    throw new ApiError(502);
  const effectiveModel = modelIdentifier(effective.model);
  if (effectiveModel === null && effective.scope !== "platform")
    throw new ApiError(502);
  return {
    tenant,
    bot,
    target,
    saved: {
      model: savedModel,
      revision: saved.revision,
      updatedAt: saved.updated_at === null ? null : timestamp(saved.updated_at),
    },
    effective: {
      scope: effective.scope as AISettings["effective"]["scope"],
      provider: "groq",
      model: effectiveModel,
    },
    processingEnabled: value.processing_enabled,
  };
}
