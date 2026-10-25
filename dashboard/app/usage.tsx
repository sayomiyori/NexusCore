"use client";

import { useEffect, useRef, useState } from "react";
import type { BotPage } from "../lib/bots.ts";
import { api, RequestError } from "../lib/client.ts";
import type { Usage as UsageData } from "../lib/usage.ts";

export default function Usage({
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
  const [values, setValues] = useState(() => {
    const now = new Date();
    return {
      bot: active[0]?.id || "",
      start: now.toISOString().slice(0, 10),
      end: new Date(now.getTime() + 86400000).toISOString().slice(0, 10),
    };
  });
  const [result, setResult] = useState<UsageData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const query = useRef<AbortController | null>(null);
  useEffect(() => () => query.current?.abort(), []);

  function change(key: keyof typeof values, value: string) {
    query.current?.abort();
    setResult(null);
    setError("");
    setLoading(false);
    setValues({ ...values, [key]: value });
  }

  async function load(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    query.current?.abort();
    const controller = new AbortController();
    query.current = controller;
    setResult(null);
    setError("");
    setLoading(true);
    try {
      const params = new URLSearchParams({ tenant: data.tenant.id, ...values });
      const value = await api<UsageData>(`/api/usage?${params}`, {
        signal: controller.signal,
      });
      if (!controller.signal.aborted) setResult(value);
    } catch (reason) {
      if (controller.signal.aborted) return;
      if (reason instanceof RequestError && reason.status === 401) onExpired();
      else
        setError(
          reason instanceof RequestError && reason.status === 400
            ? "Choose valid UTC dates with a positive interval of at most 31 days."
            : "Usage is unavailable for this tenant and bot. Check the active bot or try again.",
        );
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  return (
    <section className="panel usage" aria-label="Per-bot recorded AI usage">
      <div className="panel-heading">
        <h2>Recorded AI usage</h2>
        <span>One active bot · UTC dates</span>
      </div>
      <p className="events-window">
        Select an active bot from this page of up to 50 records. Estimates are
        recorded usage, not invoices or live bills. End date is exclusive;
        maximum interval is 31 days.
      </p>
      {active.length ? (
        <form className="usage-form" onSubmit={load}>
          <label>
            Bot
            <select
              value={values.bot}
              onChange={(event) => change("bot", event.target.value)}
              required
            >
              {active.map((bot) => (
                <option key={bot.id} value={bot.id}>
                  {bot.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Start date (UTC, inclusive)
            <input
              type="date"
              value={values.start}
              onChange={(event) => change("start", event.target.value)}
              required
            />
          </label>
          <label>
            End date (UTC, exclusive)
            <input
              type="date"
              value={values.end}
              onChange={(event) => change("end", event.target.value)}
              required
            />
          </label>
          <button
            type="submit"
            className="refresh"
            disabled={loading || !values.bot}
          >
            {loading ? "Loading usage…" : "Load usage"}
          </button>
          <p className="usage-bot-id">
            Selected bot: <code>{values.bot}</code>
          </p>
        </form>
      ) : (
        <div className="empty">
          <h3>No active bots on this page</h3>
          <p>
            AgentHub usage reads require an active bot. Check another page or
            organization.
          </p>
        </div>
      )}
      <nav className="bot-pagination" aria-label="Usage bot pages">
        <button
          type="button"
          className="refresh"
          disabled={!canFirst}
          onClick={onFirst}
        >
          First page
        </button>
        <button
          type="button"
          className="refresh"
          disabled={!data.nextCursor}
          onClick={onNext}
        >
          Next page <span aria-hidden="true">→</span>
        </button>
      </nav>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {loading && (
        <p className="usage-message" role="status">
          Reading recorded usage…
        </p>
      )}
      {result ? (
        <div className="usage-result" aria-live="polite">
          <p className="usage-message">
            {result.start.slice(0, 10)} inclusive → {result.end.slice(0, 10)}{" "}
            exclusive, UTC. Recorded estimates only.
          </p>
          <div className="cards usage-cards">
            <article className="metric">
              <span>Usage records</span>
              <strong>{result.records.toLocaleString("en-GB")}</strong>
              <p>Within this bot and interval</p>
            </article>
            <article className="metric">
              <span>Input tokens</span>
              <strong>{result.inputTokens.toLocaleString("en-GB")}</strong>
              <p>Recorded input tokens</p>
            </article>
            <article className="metric">
              <span>Output tokens</span>
              <strong>{result.outputTokens.toLocaleString("en-GB")}</strong>
              <p>Recorded output tokens</p>
            </article>
            <article className="metric">
              <span>Estimated USD</span>
              <strong>${result.estimatedCostUsd}</strong>
              <p>Estimate, not billing</p>
            </article>
          </div>
        </div>
      ) : (
        !loading &&
        !error &&
        active.length > 0 && (
          <p className="usage-message">
            Choose dates and load usage. No usage totals have been requested
            yet.
          </p>
        )
      )}
      <p className="activity-foot">
        Read-only AgentHub records. No AI request, provider activation or
        tenant-wide aggregation is performed. Refresh or bot-page changes reset
        this form.
      </p>
    </section>
  );
}
