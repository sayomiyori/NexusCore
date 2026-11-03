import type { Job } from "./jobs.ts";

export const jobStates = [
  "pending",
  "processing",
  "completed",
  "failed",
  "unknown",
] as const;

export type JobStateFilter = "all" | Job["state"];

export function filterJobs(jobs: Job[], state: JobStateFilter): Job[] {
  return jobs.filter((job) => state === "all" || job.state === state);
}
