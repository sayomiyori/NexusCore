import { authorizedTenant, type Tenant } from "./overview.ts";
import { ApiError, origin, record, requestJson, text, uuid } from "./server.ts";

export type Usage = {
  tenant: Tenant;
  bot: string;
  start: string;
  end: string;
  records: number;
  inputTokens: number;
  outputTokens: number;
  estimatedCostUsd: string;
};

export function usageRange(start: string, end: string) {
  const dates = [start, end].map((value) => {
    if (!/^(?!0000)\d{4}-\d\d-\d\d$/.test(value)) throw new ApiError(400);
    const date = new Date(`${value}T00:00:00.000Z`);
    if (
      !Number.isFinite(date.getTime()) ||
      date.toISOString().slice(0, 10) !== value
    )
      throw new ApiError(400);
    return date;
  });
  const duration = dates[1].getTime() - dates[0].getTime();
  if (duration <= 0 || duration > 31 * 86400000) throw new ApiError(400);
  return { start: dates[0].toISOString(), end: dates[1].toISOString() };
}

function cost(value: unknown): string {
  const match = text(value, 64).match(
    /^(\d{1,38})(?:\.(\d{1,8}))?(?:[eE]([+-]?\d{1,2}))?$/,
  );
  if (!match) throw new ApiError(502);
  let units = BigInt(match[1] + (match[2] || ""));
  const power = 8 - (match[2]?.length || 0) + Number(match[3] || 0);
  if (power >= 0) units *= 10n ** BigInt(power);
  else {
    const divisor = 10n ** BigInt(-power);
    if (units % divisor !== 0n) throw new ApiError(502);
    units /= divisor;
  }
  const digits = units.toString().padStart(9, "0");
  if (digits.length > 38) throw new ApiError(502);
  return `${digits.slice(0, -8)}.${digits.slice(-8)}`;
}

function count(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0)
    throw new ApiError(502);
  return value;
}

export async function usage(
  token: string,
  selected: string,
  botId: string,
  range: { start: string; end: string },
): Promise<Usage> {
  const tenant = await authorizedTenant(token, selected),
    bot = uuid(botId);
  const value = record(
    await requestJson(
      origin("AGENT"),
      `/api/v1/tenants/${tenant.id}/bots/${bot}/ai/usage?start=${encodeURIComponent(range.start)}&end=${encodeURIComponent(range.end)}`,
      token,
      tenant.id,
    ),
  );
  return {
    tenant,
    bot,
    ...range,
    records: count(value.records),
    inputTokens: count(value.input_tokens),
    outputTokens: count(value.output_tokens),
    estimatedCostUsd: cost(value.estimated_cost_usd),
  };
}
