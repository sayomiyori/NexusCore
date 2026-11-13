"use client";

import { useEffect, useRef, useState } from "react";
import type { BotPage } from "../lib/bots.ts";
import { api, RequestError } from "../lib/client.ts";
import { stateLabels } from "../lib/event-view.ts";
import {
  begin,
  canGoFirst,
  fail,
  initialNavigation,
  type JobAction,
  type JobNavigation,
  resetNavigation,
  succeed,
} from "../lib/job-history.ts";
import { filterJobs, type JobStateFilter, jobStates } from "../lib/job-view.ts";
import type { JobPage } from "../lib/jobs.ts";

export default function Jobs({
  data,
  canFirst,
  canPrevious,
  onFirst,
  onPrevious,
  onNext,
  onExpired,
}: {
  data: BotPage;
  canFirst: boolean;
  canPrevious: boolean;
  onFirst: () => void;
  onPrevious: () => void;
  onNext: () => void;
  onExpired: () => void;
}) {
  const active = data.items.filter((bot) => bot.active);
  const [selected, setSelected] = useState(active[0]?.id || "");
  const [page, setPage] = useState<JobPage | null>(null);
  const [state, setState] = useState<JobStateFilter>("all");
  const items = page ? filterJobs(page.items, state) : [];
  const [navigation, setNavigation] =
    useState<JobNavigation>(initialNavigation);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const query = useRef<AbortController | null>(null);
  useEffect(() => () => query.current?.abort(), []);

  function choose(bot: string) {
    query.current?.abort();
    setSelected(bot);
    setPage(null);
    setState("all");
    setNavigation(resetNavigation());
    setError("");
    setLoading(false);
  }
  async function load(action: JobAction) {
    query.current?.abort();
    const controller = new AbortController();
    query.current = controller;
    setPage(null);
    setError("");
    setLoading(true);
    setNavigation((state) => begin(state, action));
    try {
      const params = new URLSearchParams({
        tenant: data.tenant.id,
        bot: selected,
      });
      const cursor = action.kind === "first" ? null : action.cursor;
      if (cursor) params.set("cursor", cursor);
      const value = await api<JobPage>(`/api/jobs?${params}`, {
        signal: controller.signal,
      });
      if (!controller.signal.aborted) {
        setPage(value);
        setNavigation((state) => succeed(state));
      }
    } catch (reason) {
      if (controller.signal.aborted) return;
      if (reason instanceof RequestError && reason.status === 401) onExpired();
      else {
        setError(
          "Job metadata is unavailable for this tenant and bot. Check the active bot or try again.",
        );
        setNavigation((state) => fail(state));
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }
  return (
    <section className="panel usage jobs" aria-label="Per-bot AI job metadata">
      <div className="panel-heading">
        <h2>Stored AI jobs</h2>
        <span>UUID order · Up to 50 per page</span>
      </div>
      <p className="events-window">
        Choose an active bot from this page of up to 50 bots, then load its job
        snapshots. Reads do not execute, retry or resend jobs; Retry job page
        only repeats a failed read.
      </p>
      {active.length ? (
        <form
          className="usage-form"
          onSubmit={(event) => {
            event.preventDefault();
            void load({ kind: "first" });
          }}
        >
          <label>
            Bot
            <select
              value={selected}
              onChange={(event) => choose(event.target.value)}
              required
            >
              {active.map((bot) => (
                <option value={bot.id} key={bot.id}>
                  {bot.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            className="refresh"
            disabled={loading || !selected}
          >
            {loading ? "Loading jobs…" : "Load jobs"}
          </button>
          <p className="usage-bot-id">
            Selected bot: <code>{selected}</code>
          </p>
        </form>
      ) : (
        <div className="empty">
          <h3>No active bots on this page</h3>
          <p>
            Job metadata reads require an active bot. Check another page or
            organization.
          </p>
        </div>
      )}
      <nav className="bot-pagination" aria-label="Job bot selection pages">
        <button
          type="button"
          className="refresh"
          disabled={!canFirst}
          onClick={onFirst}
        >
          First bot page
        </button>
        <button
          type="button"
          className="refresh"
          disabled={!canPrevious}
          onClick={onPrevious}
        >
          <span aria-hidden="true">←</span> Previous bot page
        </button>
        <button
          type="button"
          className="refresh"
          disabled={!data.nextCursor}
          onClick={onNext}
        >
          Next bot page
        </button>
      </nav>
      {error && (
        <p role="alert" className="notice error">
          {error}
        </p>
      )}
      {loading && (
        <p className="usage-message" role="status">
          Reading stored job metadata…
        </p>
      )}
      {page ? (
        <>
          <p className="usage-message" role="status">
            {items.length} of {page.items.length} job snapshots on this page.
            Filter and counts apply only to loaded rows.
          </p>
          {page.items.length > 0 && (
            <fieldset className="event-filters">
              <legend>Filter loaded job snapshots</legend>
              <label>
                Job state
                <select
                  value={state}
                  onChange={(event) =>
                    setState(event.target.value as JobStateFilter)
                  }
                >
                  <option value="all">All states</option>
                  {jobStates.map((value) => (
                    <option key={value} value={value}>
                      {stateLabels[value]}
                    </option>
                  ))}
                </select>
              </label>
            </fieldset>
          )}
          {items.length ? (
            <ol className="event-list job-list">
              {items.map((job) => (
                <li key={job.id}>
                  <div className="event-detail-heading">
                    <h3>Job snapshot</h3>
                    <span
                      className={`state${["failed", "unknown"].includes(job.state) ? " attention" : ""}`}
                    >
                      {stateLabels[job.state]}
                    </span>
                  </div>
                  <dl>
                    <div>
                      <dt>Job ID</dt>
                      <dd>
                        <code>{job.id}</code>
                      </dd>
                    </div>
                    <div>
                      <dt>Input event ID</dt>
                      <dd>
                        <code>{job.eventId}</code>
                      </dd>
                    </div>
                    <div>
                      <dt>Recorded attempts</dt>
                      <dd>{job.attempts}</dd>
                    </div>
                    <div>
                      <dt>Created at (UTC)</dt>
                      <dd>
                        <time dateTime={job.created}>
                          {new Date(job.created).toLocaleString("en-GB", {
                            timeZone: "UTC",
                          })}
                        </time>
                      </dd>
                    </div>
                    <div>
                      <dt>Updated at (UTC)</dt>
                      <dd>
                        <time dateTime={job.updated}>
                          {new Date(job.updated).toLocaleString("en-GB", {
                            timeZone: "UTC",
                          })}
                        </time>
                      </dd>
                    </div>
                  </dl>
                </li>
              ))}
            </ol>
          ) : page.items.length ? (
            <div className="empty">
              <h3>No jobs in this state</h3>
              <p>Change the state filter to see other loaded job snapshots.</p>
            </div>
          ) : (
            <div className="empty">
              <h3>
                {navigation.current ? "End of job list" : "No recorded jobs"}
              </h3>
              <p>
                No job snapshots were returned for this authorized bot and
                cursor.
              </p>
            </div>
          )}
        </>
      ) : (
        !loading &&
        !error &&
        active.length > 0 && (
          <p className="usage-message">
            Choose a bot and load jobs. No job metadata has been requested yet.
          </p>
        )
      )}
      <nav className="bot-pagination" aria-label="AI job pages">
        <button
          type="button"
          className="refresh"
          disabled={loading || !canGoFirst(navigation)}
          onClick={() => void load({ kind: "first" })}
        >
          First job page
        </button>
        <button
          type="button"
          className="refresh"
          disabled={loading || !navigation.history.length}
          onClick={() =>
            void load({
              kind: "previous",
              cursor: navigation.history.at(-1) ?? null,
            })
          }
        >
          Previous job page
        </button>
        <button
          type="button"
          className="refresh"
          disabled={loading || !page?.nextCursor}
          onClick={() =>
            page?.nextCursor &&
            void load({ kind: "next", cursor: page.nextCursor })
          }
        >
          Next job page
        </button>
        {navigation.failed && navigation.attempted && (
          <button
            type="button"
            className="refresh"
            disabled={loading}
            onClick={() =>
              navigation.attempted && void load(navigation.attempted)
            }
          >
            Retry job page
          </button>
        )}
      </nav>
      <p className="activity-foot">
        Read-only snapshots in UUID order, not live execution or a complete
        history total. Raw envelopes, answers, provider/model and error details
        are excluded. Refresh resets the selector and job pages.
      </p>
    </section>
  );
}
