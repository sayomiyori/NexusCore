"use client";

import { useEffect, useRef, useState } from "react";
import type { BotPage } from "../lib/bots.ts";
import { api, RequestError } from "../lib/client.ts";
import { stateLabels } from "../lib/event-view.ts";
import type { JobPage } from "../lib/jobs.ts";

export default function Jobs({
  data,
  canFirst,
  onFirst,
  onNext,
  onExpired,
}: {
  data: BotPage;
  canFirst: boolean;
  onFirst: () => void;
  onNext: () => void;
  onExpired: () => void;
}) {
  const active = data.items.filter((bot) => bot.active);
  const [selected, setSelected] = useState(active[0]?.id || "");
  const [page, setPage] = useState<JobPage | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const query = useRef<AbortController | null>(null);
  useEffect(() => () => query.current?.abort(), []);

  function choose(bot: string) {
    query.current?.abort();
    setSelected(bot);
    setPage(null);
    setCursor(null);
    setError("");
    setLoading(false);
  }
  async function load(next: string | null) {
    query.current?.abort();
    const controller = new AbortController();
    query.current = controller;
    setPage(null);
    setCursor(next);
    setError("");
    setLoading(true);
    try {
      const params = new URLSearchParams({
        tenant: data.tenant.id,
        bot: selected,
      });
      if (next) params.set("cursor", next);
      const value = await api<JobPage>(`/api/jobs?${params}`, {
        signal: controller.signal,
      });
      if (!controller.signal.aborted) setPage(value);
    } catch (reason) {
      if (controller.signal.aborted) return;
      if (reason instanceof RequestError && reason.status === 401) onExpired();
      else
        setError(
          "Job metadata is unavailable for this tenant and bot. Check the active bot or try again.",
        );
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
        snapshots. Reads do not execute, retry or resend jobs.
      </p>
      {active.length ? (
        <form
          className="usage-form"
          onSubmit={(event) => {
            event.preventDefault();
            void load(null);
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
            {page.items.length} job snapshots on this page. Counts refer only to
            this page.
          </p>
          {page.items.length ? (
            <ol className="event-list job-list">
              {page.items.map((job) => (
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
          ) : (
            <div className="empty">
              <h3>{cursor ? "End of job list" : "No recorded jobs"}</h3>
              <p>
                No job snapshots were returned for this authorized bot and
                cursor.
              </p>
            </div>
          )}
          <nav className="bot-pagination" aria-label="AI job pages">
            <button
              type="button"
              className="refresh"
              disabled={!cursor || loading}
              onClick={() => void load(null)}
            >
              First job page
            </button>
            <button
              type="button"
              className="refresh"
              disabled={!page.nextCursor || loading}
              onClick={() => void load(page.nextCursor)}
            >
              Next job page
            </button>
          </nav>
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
      <p className="activity-foot">
        Read-only snapshots in UUID order, not live execution or a complete
        history total. Raw envelopes, answers, provider/model and error details
        are excluded. Refresh resets the selector and job pages.
      </p>
    </section>
  );
}
