"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Observation, Overview, Tenant } from "../lib/overview.ts";

type TenantPage = { items: Tenant[]; hasMore: boolean; offset: number };
class RequestError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    cache: "no-store",
    credentials: "same-origin",
  });
  const data = await response.json();
  if (!response.ok)
    throw new RequestError(
      response.status,
      typeof data.error === "string"
        ? data.error
        : "Data is temporarily unavailable.",
    );
  return data as T;
}

const kindLabels = {
  auth: "Tenant access observed",
  webhook: "Bot configuration observed",
  agent: "AI job observed",
};
const stateLabels: Record<string, string> = {
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
const needsAttention = (event: Observation) =>
  event.conflict || ["failed", "unknown"].includes(event.state);

export default function Page() {
  const [screen, setScreen] = useState<"loading" | "login" | "overview">(
    "loading",
  );
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [selection, setSelection] = useState({ tenant: "" });
  const selected = selection.tenant;
  const [data, setData] = useState<Overview | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [mfa, setMfa] = useState(false);
  const query = useRef<AbortController | null>(null);
  const codeInput = useRef<HTMLInputElement>(null);

  const choose = useCallback((id: string) => {
    query.current?.abort();
    setData(null);
    setError("");
    setSelection({ tenant: id });
  }, []);

  const expire = useCallback(() => {
    choose("");
    setTenants([]);
    setScreen("login");
    setMfa(false);
    setError("Your session expired. Sign in again.");
  }, [choose]);

  const receiveTenants = useCallback(
    (page: TenantPage) => {
      if (page.offset === 0) {
        setTenants(page.items);
        choose(page.items[0]?.id || "");
      } else
        setTenants((current) => [
          ...current,
          ...page.items.filter(
            (item) => !current.some((other) => item.id === other.id),
          ),
        ]);
      setHasMore(page.hasMore);
      setOffset(page.offset + 50);
      setScreen("overview");
    },
    [choose],
  );

  useEffect(() => {
    const controller = new AbortController();
    api<TenantPage>("/api/tenants", { signal: controller.signal })
      .then(receiveTenants)
      .catch((reason) => {
        if (!controller.signal.aborted) {
          setScreen("login");
          if (!(reason instanceof RequestError && reason.status === 401))
            setError("Unable to load your workspace. Try signing in again.");
        }
      });
    return () => controller.abort();
  }, [receiveTenants]);

  useEffect(() => {
    if (mfa) codeInput.current?.focus();
  }, [mfa]);

  useEffect(() => {
    const tenant = selection.tenant;
    if (!tenant || screen !== "overview") return;
    const controller = new AbortController();
    query.current = controller;
    api<Overview>(`/api/overview?tenant=${tenant}`, {
      signal: controller.signal,
    })
      .then((result) => {
        if (!controller.signal.aborted) setData(result);
      })
      .catch((reason) => {
        if (controller.signal.aborted) return;
        if (reason instanceof RequestError && reason.status === 401) {
          expire();
        } else setError("Unable to load this tenant. Refresh to try again.");
      });
    return () => controller.abort();
  }, [selection, screen, expire]);

  async function signIn(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget,
      values = new FormData(form);
    setBusy(true);
    setError("");
    try {
      const result = await api<{ requires2fa: boolean }>("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          mfa
            ? { code: values.get("code") }
            : { email: values.get("email"), password: values.get("password") },
        ),
      });
      form.reset();
      if (result.requires2fa) setMfa(true);
      else {
        setMfa(false);
        receiveTenants(await api<TenantPage>("/api/tenants"));
      }
    } catch (reason) {
      setError(
        reason instanceof RequestError
          ? reason.message
          : "Unable to sign in. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function moreTenants() {
    setBusy(true);
    setError("");
    try {
      receiveTenants(await api<TenantPage>(`/api/tenants?offset=${offset}`));
    } catch (reason) {
      if (reason instanceof RequestError && reason.status === 401) expire();
      else setError("Unable to load more organizations. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    query.current?.abort();
    setBusy(true);
    let message = "";
    try {
      await api("/api/session", { method: "DELETE" });
    } catch (reason) {
      message =
        reason instanceof RequestError
          ? reason.message
          : "Sign-out could not be confirmed. Try again.";
    }
    choose("");
    setTenants([]);
    setScreen("login");
    setMfa(false);
    setBusy(false);
    setError(message);
  }

  const pending = Boolean(selected && !data && !error);
  const status = error ? (
    <p role="alert" className="notice error">
      {error}
    </p>
  ) : null;
  const brand = (
    <div className="brand">
      <span aria-hidden="true" className="brand-mark">
        N
      </span>
      <span>
        NexusCore<span className="brand-caption">BOT PLATFORM</span>
      </span>
    </div>
  );

  if (screen === "loading")
    return (
      <main className="loading-screen">
        <div className="loader" aria-hidden="true" />
        <p role="status">Opening your workspace…</p>
      </main>
    );

  if (screen === "login")
    return (
      <main className="login-shell">
        <section className="login-intro">
          {brand}
          <div>
            <span className="eyebrow">YOUR PLATFORM, OBSERVED</span>
            <h1>
              One workspace.
              <br />A clearer picture.
            </h1>
            <p>
              Tenant access, bot configuration and AI job observations, brought
              together.
            </p>
            <div className="architecture">
              <span>AuthFortress</span>
              <span>WebHook Manager</span>
              <span>AgentHub</span>
              <span className="architecture-flow" aria-hidden="true">
                ↓
              </span>
              <strong>EventPipe · PipeWatch</strong>
            </div>
          </div>
          <p className="muted">
            Read-only overview · Explicit tenant boundaries
          </p>
        </section>
        <section className="login-form">
          <div className="form-card">
            <span className="eyebrow">NEXUSCORE WORKSPACE</span>
            <h2>{mfa ? "Verify your sign-in" : "Sign in"}</h2>
            <p>
              {mfa
                ? "Enter an authenticator or one-use backup code."
                : "Continue with your AuthFortress account."}
            </p>
            {status}
            <form onSubmit={signIn}>
              {mfa ? (
                <label>
                  Verification code
                  <input
                    ref={codeInput}
                    name="code"
                    autoComplete="one-time-code"
                    required
                    minLength={4}
                    maxLength={32}
                  />
                </label>
              ) : (
                <>
                  <label>
                    Email
                    <input
                      name="email"
                      type="email"
                      autoComplete="username"
                      required
                      maxLength={254}
                    />
                  </label>
                  <label>
                    Password
                    <input
                      name="password"
                      type="password"
                      autoComplete="current-password"
                      required
                      maxLength={1024}
                    />
                  </label>
                </>
              )}
              <button type="submit" className="primary" disabled={busy}>
                {busy
                  ? "Please wait…"
                  : mfa
                    ? "Verify and continue"
                    : "Continue to workspace"}
                <span aria-hidden="true">→</span>
              </button>
              {mfa && (
                <button
                  type="button"
                  className="text-button"
                  disabled={busy}
                  onClick={() => {
                    setMfa(false);
                    setError("");
                  }}
                >
                  Back to sign in
                </button>
              )}
            </form>
            <p className="form-note">
              Your organizations and their observations stay within your
              authorized tenant context.
            </p>
          </div>
        </section>
      </main>
    );

  return (
    <div className="workspace">
      <aside className="sidebar">
        {brand}
        <div className="workspace-label">WORKSPACE</div>
        <label className="tenant-label">
          Organization
          <select
            value={selected}
            disabled={busy || !tenants.length}
            onChange={(event) => choose(event.target.value)}
          >
            {!tenants.length && <option value="">No organizations</option>}
            {tenants.map((tenant) => (
              <option key={tenant.id} value={tenant.id}>
                {tenant.name}
              </option>
            ))}
          </select>
        </label>
        {hasMore && (
          <button
            type="button"
            className="text-button"
            disabled={busy}
            onClick={moreTenants}
          >
            Load more organizations
          </button>
        )}
        <div className="nav-active">
          <span aria-hidden="true">▦</span>Overview
          <span className="nav-dot" />
        </div>
        <div className="sidebar-bottom">
          <span className="read-only">READ ONLY</span>
          <p>
            Observe your workspace.
            <br />
            Business data stays unchanged.
          </p>
          <button
            type="button"
            className="signout"
            disabled={busy}
            onClick={signOut}
          >
            Sign out <span aria-hidden="true">↗</span>
          </button>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <span>
            Workspace <span aria-hidden="true">/</span> Overview
          </span>
          <span className="view-badge">Tenant view</span>
        </header>
        <div className="content">
          <div className="page-heading">
            <div>
              <span className="eyebrow">WORKSPACE AT A GLANCE</span>
              <h1>Overview</h1>
              <p>
                Recent observations across{" "}
                {data?.tenant.name || "your organization"}.
              </p>
            </div>
            <button
              type="button"
              className="refresh"
              disabled={pending || busy || !selected}
              onClick={() => {
                choose(selected);
              }}
            >
              <span aria-hidden="true">↻</span> Refresh
            </button>
          </div>
          {status}
          {!tenants.length ? (
            <section className="empty panel">
              <h2>No organizations yet</h2>
              <p>This account has no available tenant memberships.</p>
            </section>
          ) : pending ? (
            <section className="empty panel" aria-live="polite">
              <div className="loader" aria-hidden="true" />
              <p role="status">Loading tenant observations…</p>
            </section>
          ) : (
            data && (
              <>
                <section className="cards" aria-label="Observation summary">
                  <article className="metric">
                    <span>Recent observations</span>
                    <strong>{data.events.length}</strong>
                    <p>In the displayed window</p>
                  </article>
                  <article className="metric">
                    <span>Need attention</span>
                    <strong>{data.events.filter(needsAttention).length}</strong>
                    <p>Failed, unknown or conflicting</p>
                  </article>
                  <article className="metric">
                    <span>Responding receivers</span>
                    <strong>
                      {Number(data.sources.eventpipe) +
                        Number(data.sources.pipewatch)}
                      <small> / 2</small>
                    </strong>
                    <p>Authorized reads completed</p>
                  </article>
                </section>
                {(!data.sources.eventpipe || !data.sources.pipewatch) && (
                  <p className="notice" role="status">
                    Some receiver data is unavailable. The view shows only
                    successful reads.
                  </p>
                )}
                <div className="overview-grid">
                  <section className="panel activity">
                    <div className="panel-heading">
                      <h2>Recent activity</h2>
                      <span>Latest 10 observations</span>
                    </div>
                    {data.events.length ? (
                      <ol>
                        {data.events.map((event) => (
                          <li key={event.id}>
                            <span
                              aria-hidden="true"
                              className={`event-icon ${event.kind}`}
                            >
                              {event.kind === "agent"
                                ? "AI"
                                : event.kind === "auth"
                                  ? "A"
                                  : "W"}
                            </span>
                            <div className="event-body">
                              <strong>{kindLabels[event.kind]}</strong>
                              <div className="event-meta">
                                {event.bot ? (
                                  <span>Bot · {event.bot.slice(0, 8)}</span>
                                ) : (
                                  <span>Tenant access</span>
                                )}
                                <span aria-hidden="true">·</span>
                                <time dateTime={event.at}>
                                  {new Date(event.at).toLocaleString("en-GB", {
                                    timeZone: "UTC",
                                    day: "2-digit",
                                    month: "short",
                                    hour: "2-digit",
                                    minute: "2-digit",
                                  })}{" "}
                                  UTC
                                </time>
                              </div>
                              <div className="receivers">
                                {event.receivers.map((receiver) => (
                                  <span key={receiver}>{receiver}</span>
                                ))}
                              </div>
                            </div>
                            <span
                              className={
                                "state " +
                                (needsAttention(event) ? "attention" : "")
                              }
                            >
                              {event.conflict
                                ? "Conflicting evidence"
                                : stateLabels[event.state] || "Observed"}
                            </span>
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <div className="empty">
                        <h3>No observations found</h3>
                        <p>
                          {data.sources.eventpipe || data.sources.pipewatch
                            ? "No supported events appeared in the recent receiver windows."
                            : "Receiver reads are unavailable. Refresh to try again."}
                        </p>
                      </div>
                    )}
                    <p className="activity-foot">
                      Snapshots can miss intermediate changes. This window is
                      not a lifetime activity total.
                    </p>
                  </section>
                  <section className="panel connections">
                    <div className="panel-heading">
                      <h2>Data connections</h2>
                    </div>
                    {[
                      ["AuthFortress", true, "Tenant membership"],
                      [
                        "EventPipe",
                        data.sources.eventpipe,
                        "Stored observations",
                      ],
                      [
                        "PipeWatch",
                        data.sources.pipewatch,
                        "Recent log observations",
                      ],
                    ].map(([name, available, detail]) => (
                      <div className="connection" key={String(name)}>
                        <div>
                          <strong>{name}</strong>
                          <p>{detail}</p>
                        </div>
                        <span
                          className={
                            "connection-state " +
                            (!available ? "unavailable" : "")
                          }
                        >
                          <i aria-hidden="true" />
                          {available ? "Responding" : "Unavailable"}
                        </span>
                      </div>
                    ))}
                    <div className="connection-note">
                      <span aria-hidden="true">ⓘ</span>
                      <p>
                        Availability describes these authorized reads. Bot and
                        AI states are observations, not live health checks.
                      </p>
                    </div>
                  </section>
                </div>
              </>
            )
          )}
        </div>
        <footer className="footer">
          NexusCore <span>Tenant-isolated observability</span>
        </footer>
      </main>
    </div>
  );
}
