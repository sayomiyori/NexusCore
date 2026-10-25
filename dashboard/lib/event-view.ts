import type { Observation } from "./overview.ts";

export const kindLabels = {
  auth: "Tenant access observed",
  webhook: "Bot configuration observed",
  agent: "AI job observed",
};
export const stateLabels: Record<string, string> = {
  owner: "Owner",
  member: "Member",
  not_configured: "Not configured",
  configuring: "Configuring",
  configured: "Configured",
  inactive: "Inactive",
  pending: "Pending",
  processing: "Processing",
  completed: "Completed",
  failed: "Failed",
  unknown: "Unknown",
};
export const needsAttention = (event: Observation) =>
  event.conflict || ["failed", "unknown"].includes(event.state);

export type EventFilters = {
  kind: "all" | Observation["kind"];
  receiver: "all" | "EventPipe" | "PipeWatch";
  query: string;
  attention: boolean;
};

export function filterObservations(
  events: Observation[],
  filters: EventFilters,
): Observation[] {
  const query = filters.query.trim().toLowerCase();
  return events.filter(
    (event) =>
      (filters.kind === "all" || event.kind === filters.kind) &&
      (filters.receiver === "all" ||
        event.receivers.includes(filters.receiver)) &&
      (!filters.attention || needsAttention(event)) &&
      (!query || event.id.includes(query) || event.bot?.includes(query)),
  );
}
