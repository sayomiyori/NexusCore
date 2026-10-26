"use client";

import { useEffect, useRef, useState } from "react";
import type { BotPage } from "../lib/bots.ts";
import { api, RequestError } from "../lib/client.ts";
import type { Configuration as ConfigurationData } from "../lib/configuration.ts";

export default function Configuration({
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
  const [result, setResult] = useState<ConfigurationData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const query = useRef<AbortController | null>(null);
  useEffect(() => () => query.current?.abort(), []);
  function choose(bot: string) {
    query.current?.abort();
    setSelected(bot);
    setResult(null);
    setError("");
    setLoading(false);
  }
  async function load() {
    query.current?.abort();
    const controller = new AbortController();
    query.current = controller;
    setResult(null);
    setError("");
    setLoading(true);
    try {
      const params = new URLSearchParams({
        tenant: data.tenant.id,
        bot: selected,
      });
      const value = await api<ConfigurationData>(
        `/api/configuration?${params}`,
        { signal: controller.signal },
      );
      if (!controller.signal.aborted) setResult(value);
    } catch (reason) {
      if (controller.signal.aborted) return;
      if (reason instanceof RequestError && reason.status === 401) onExpired();
      else
        setError(
          "AI configuration is unavailable for this tenant and bot. Check the active bot or try again.",
        );
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }
  return (
    <section
      className="panel usage configuration"
      aria-label="Read-only platform AI configuration"
    >
      <div className="panel-heading">
        <h2>Platform AI configuration</h2>
        <span>Operator-managed · Read only</span>
      </div>
      <p className="events-window">
        Choose an active bot from this page of up to 50 bots. This shows shared
        platform policy, not a saved bot-specific override.
      </p>
      {active.length ? (
        <form
          className="usage-form"
          onSubmit={(event) => {
            event.preventDefault();
            void load();
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
                <option key={bot.id} value={bot.id}>
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
            {loading ? "Loading configuration…" : "Load configuration"}
          </button>
          <p className="usage-bot-id">
            Selected bot: <code>{selected}</code>
          </p>
        </form>
      ) : (
        <div className="empty">
          <h3>No active bots on this page</h3>
          <p>
            Configuration reads require an active bot. Check another page or
            organization.
          </p>
        </div>
      )}
      <nav
        className="bot-pagination"
        aria-label="Configuration bot selection pages"
      >
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
          Reading platform configuration…
        </p>
      )}
      {result ? (
        <>
          <p className="usage-message" role="status">
            Shared platform settings read successfully.
          </p>
          <dl className="cards usage-cards">
            <div className="metric">
              <dt>Policy scope</dt>
              <dd>Shared platform</dd>
            </div>
            <div className="metric">
              <dt>Provider</dt>
              <dd>Groq</dd>
            </div>
            <div className="metric">
              <dt>Selected model</dt>
              <dd>{result.model || "Not selected"}</dd>
            </div>
            <div className="metric">
              <dt>Processing flag</dt>
              <dd>{result.processingEnabled ? "Enabled" : "Disabled"}</dd>
            </div>
          </dl>
        </>
      ) : (
        !loading &&
        !error &&
        active.length > 0 && (
          <p className="usage-message">
            Choose a bot and load configuration. No settings have been requested
            yet.
          </p>
        )
      )}
      <p className="activity-foot">
        The processing flag is a process setting, not proof of credentials,
        worker availability or provider connectivity. Reading does not activate
        AI or contact a provider. Credentials, prompts and service URLs are
        excluded. Changes remain operator-managed.
      </p>
    </section>
  );
}
