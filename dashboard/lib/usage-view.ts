export const USAGE_INTERVAL_ERROR =
  "Choose a positive UTC date range of at most 31 days.";

const DAY_MS = 86400000;

function utcDay(value: string): number | null {
  if (!/^(?!0000)\d{4}-\d\d-\d\d$/.test(value)) return null;
  const parsed = Date.parse(`${value}T00:00:00.000Z`);
  if (
    !Number.isFinite(parsed) ||
    new Date(parsed).toISOString().slice(0, 10) !== value
  )
    return null;
  return parsed;
}

export function usageIntervalError(start: string, end: string): string {
  const first = utcDay(start),
    last = utcDay(end);
  if (first === null || last === null) return USAGE_INTERVAL_ERROR;
  const duration = last - first;
  return duration <= 0 || duration > 31 * DAY_MS ? USAGE_INTERVAL_ERROR : "";
}
