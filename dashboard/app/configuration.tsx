"use client";

import { useEffect, useRef, useState } from "react";
import type { AISettings } from "../lib/ai-settings.ts";
import type { BotPage } from "../lib/bots.ts";
import { api, RequestError } from "../lib/client.ts";

export default function Configuration({
  data,
  canFirst,
  onFirst,
  onNext,
  onExpired,
  onSaving,
}: {
  data: BotPage;
  canFirst: boolean;
  onFirst: () => void;
  onNext: () => void;
  onExpired: () => void;
  onSaving: (value: boolean) => void;
}) {
  const active = data.items.filter((bot) => bot.active);
  const [target, setTarget] = useState<"tenant" | "bot">("tenant");
  const [selected, setSelected] = useState(active[0]?.id || "");
  const [result, setResult] = useState<AISettings | null>(null);
  const [model, setModel] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const query = useRef<AbortController | null>(null),
    mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      query.current?.abort();
      onSaving(false);
    };
  }, [onSaving]);
  function clear() {
    query.current?.abort();
    setResult(null);
    setModel("");
    setError("");
    setNotice("");
    setLoading(false);
  }
  function path() {
    return `/api/ai-settings?${new URLSearchParams({ tenant: data.tenant.id, ...(target === "bot" ? { bot: selected } : {}) })}`;
  }
  async function load() {
    clear();
    const controller = new AbortController();
    query.current = controller;
    setLoading(true);
    try {
      const value = await api<AISettings>(path(), {
        signal: controller.signal,
      });
      if (!controller.signal.aborted) {
        setResult(value);
        setModel(value.saved.model || "");
      }
    } catch (reason) {
      if (controller.signal.aborted) return;
      if (reason instanceof RequestError && reason.status === 401) onExpired();
      else
        setError("AI settings are unavailable. Check your scope and reload.");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }
  async function save(value: string | null) {
    if (!result || saving) return;
    if (value !== null && !/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/.test(value)) {
      setError("Choose a valid model identifier of at most 128 characters.");
      return;
    }
    query.current?.abort();
    setSaving(true);
    onSaving(true);
    setError("");
    setNotice("");
    try {
      const next = await api<AISettings>(path(), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: value,
          expectedRevision: result.saved.revision,
        }),
      });
      if (!mounted.current) return;
      setResult(next);
      setModel(next.saved.model || "");
      setNotice(
        `Saved revision ${next.saved.revision}. Processing was not enabled by this change.`,
      );
    } catch (reason) {
      if (!mounted.current) return;
      if (reason instanceof RequestError && reason.status === 401) onExpired();
      else if (reason instanceof RequestError && reason.status === 400)
        setError("Choose a valid model identifier of at most 128 characters.");
      else {
        setResult(null);
        setModel("");
        setError(
          reason instanceof RequestError && reason.status === 409
            ? "Settings changed elsewhere. Reload settings before saving again."
            : "Save was not confirmed. Reload settings to check the stored revision before retrying.",
        );
      }
    } finally {
      if (mounted.current) {
        setSaving(false);
        onSaving(false);
      }
    }
  }
  return (
    <section
      className="panel usage configuration"
      aria-label="Tenant and bot AI settings"
    >
      <div className="panel-heading">
        <h2>AI model settings</h2>
        <span>Owner edits · Versioned saves</span>
      </div>
      <p className="events-window">
        Bot override → tenant default → operator platform model. Saving changes
        model selection for future first claims; retries keep their frozen
        model.
      </p>
      <form
        className="usage-form"
        onSubmit={(event) => {
          event.preventDefault();
          void load();
        }}
      >
        <label>
          Settings scope
          <select
            value={target}
            disabled={saving}
            onChange={(event) => {
              clear();
              setTarget(event.target.value as "tenant" | "bot");
            }}
          >
            <option value="tenant">Tenant default</option>
            <option value="bot">Bot override</option>
          </select>
        </label>
        {target === "bot" && (
          <label>
            Bot
            <select
              value={selected}
              disabled={saving || !active.length}
              onChange={(event) => {
                clear();
                setSelected(event.target.value);
              }}
            >
              {!active.length && (
                <option value="">No active bots on this page</option>
              )}
              {active.map((bot) => (
                <option value={bot.id} key={bot.id}>
                  {bot.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <button
          type="submit"
          className="refresh"
          disabled={loading || saving || (target === "bot" && !selected)}
        >
          {loading ? "Loading settings…" : "Load settings"}
        </button>
        <p className="usage-bot-id">
          {target === "tenant" ? (
            "Tenant default applies to bots without an override."
          ) : (
            <>
              Selected bot: <code>{selected || "None"}</code>
            </>
          )}
        </p>
      </form>
      {target === "bot" && (
        <nav
          className="bot-pagination"
          aria-label="Configuration bot selection pages"
        >
          <button
            type="button"
            className="refresh"
            disabled={!canFirst || saving}
            onClick={onFirst}
          >
            First bot page
          </button>
          <button
            type="button"
            className="refresh"
            disabled={!data.nextCursor || saving}
            onClick={onNext}
          >
            Next bot page
          </button>
        </nav>
      )}
      {target === "bot" && !active.length && (
        <p className="usage-message">
          No active bots on this page. Choose another bot page or edit the
          tenant default.
        </p>
      )}
      {error && (
        <p role="alert" className="notice error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="usage-message">
          {notice}
        </p>
      )}
      {loading && (
        <p role="status" className="usage-message">
          Reading stored AI settings…
        </p>
      )}
      {result ? (
        <>
          <dl className="cards usage-cards">
            <div className="metric">
              <dt>
                Saved {result.target} model · revision {result.saved.revision}
              </dt>
              <dd>{result.saved.model || "Inherited"}</dd>
            </div>
            <div className="metric">
              <dt>Effective model · {result.effective.scope}</dt>
              <dd>{result.effective.model || "Not selected"}</dd>
            </div>
            <div className="metric">
              <dt>Provider</dt>
              <dd>Groq</dd>
            </div>
            <div className="metric">
              <dt>Operator processing flag</dt>
              <dd>{result.processingEnabled ? "Enabled" : "Disabled"}</dd>
            </div>
          </dl>
          {result.tenant.role === "owner" ? (
            <form
              className="usage-form"
              onSubmit={(event) => {
                event.preventDefault();
                void save(model);
              }}
            >
              <label>
                Model identifier
                <input
                  value={model}
                  maxLength={128}
                  disabled={saving}
                  onChange={(event) => {
                    setModel(event.target.value);
                    setError("");
                    setNotice("");
                  }}
                />
              </label>
              <button
                type="submit"
                className="refresh"
                disabled={saving || !model}
              >
                {saving ? "Saving…" : "Save model"}
              </button>
              <button
                type="button"
                className="refresh"
                disabled={saving}
                onClick={() => void save(null)}
              >
                Use inherited model
              </button>
              <p className="usage-bot-id">
                Only the model is saved. Inheritance keeps the revision and
                audit trail. Concurrent changes require a reload.
              </p>
            </form>
          ) : (
            <p className="usage-message">
              Read-only member access. Only an organization owner can save AI
              settings.
            </p>
          )}
        </>
      ) : (
        !loading &&
        !error && (
          <p className="usage-message">
            Load settings before editing. No stored settings have been requested
            yet.
          </p>
        )
      )}
      <p className="activity-foot">
        Saving does not enable AI, execute a job or contact a provider. The
        processing flag is not proof of credentials, worker availability or
        connectivity. Credentials, prompts and activation remain
        operator-managed.
      </p>
    </section>
  );
}
