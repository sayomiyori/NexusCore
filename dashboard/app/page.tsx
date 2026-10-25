"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { BotPage } from "../lib/bots.ts";
import { api, RequestError } from "../lib/client.ts";
import { kindLabels, needsAttention, stateLabels } from "../lib/event-view.ts";
import type { Overview, Tenant } from "../lib/overview.ts";
import Events from "./events.tsx";
import Usage from "./usage.tsx";

type TenantPage = { items: Tenant[]; hasMore: boolean; offset: number };
type Selection = {
  tenant: string;
  view: "overview" | "bots" | "events" | "usage";
  cursor: string | null;
};
export default function Page() {
  const [screen, setScreen] = useState<"loading" | "login" | "overview">(
    "loading",
  );
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [selection, setSelection] = useState<Selection>({
    tenant: "",
    view: "overview",
    cursor: null,
  });
  const selected = selection.tenant;
  const title = {
    overview: "Overview",
    bots: "Bots",
    events: "Events",
    usage: "Usage",
  }[selection.view];
  const [data, setData] = useState<Overview | BotPage | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [mfa, setMfa] = useState(false);
  const query = useRef<AbortController | null>(null);
  const codeInput = useRef<HTMLInputElement>(null);

  const choose = useCallback(
    (id: string, view?: Selection["view"], cursor: string | null = null) => {
      query.current?.abort();
      setData(null);
      setError("");
      setSelection((current) => ({
        tenant: id,
        view: view ?? current.view,
        cursor,
      }));
    },
    [],
  );

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
    const botView = selection.view === "bots" || selection.view === "usage";
    const path = `/api/${botView ? "bots" : "overview"}?tenant=${tenant}${botView && selection.cursor ? `&cursor=${selection.cursor}` : ""}`;
    api<Overview | BotPage>(path, {
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
        <nav className="workspace-nav" aria-label="Workspace sections">
          {(["overview", "bots", "events", "usage"] as const).map((view) => (
            <button
              key={view}
              type="button"
              disabled={busy}
              className={`nav-item${selection.view === view ? " nav-active" : ""}`}
              aria-current={selection.view === view ? "page" : undefined}
              onClick={() => choose(selected, view)}
            >
              <span aria-hidden="true">
                {view === "overview"
                  ? "▦"
                  : view === "bots"
                    ? "◇"
                    : view === "events"
                      ? "≡"
                      : "$"}
              </span>
              {
                {
                  overview: "Overview",
                  bots: "Bots",
                  events: "Events",
                  usage: "Usage",
                }[view]
              }
              {selection.view === view && (
                <span className="nav-dot" aria-hidden="true" />
              )}
            </button>
          ))}
        </nav>
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
            Workspace <span aria-hidden="true">/</span> {title}
          </span>
          <span className="view-badge">Tenant view</span>
        </header>
        <div className="content">
          <div className="page-heading">
            <div>
              <span className="eyebrow">WORKSPACE AT A GLANCE</span>
              <h1>{title}</h1>
              <p>
                {selection.view === "usage"
                  ? "Recorded usage for "
                  : selection.view === "bots"
                    ? "Bot configuration for "
                    : "Recent observations across "}
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
              <p role="status">
                {selection.view === "bots" || selection.view === "usage"
                  ? "Loading tenant bots…"
                  : "Loading tenant observations…"}
              </p>
            </section>
          ) : (
            data &&
            "events" in data &&
            selection.view === "overview" && (
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
          {data && "events" in data && selection.view === "events" && (
            <Events data={data} />
          )}
          {data && "items" in data && selection.view === "usage" && (
            <Usage
              data={data}
              canFirst={Boolean(selection.cursor)}
              onFirst={() => choose(selected, "usage")}
              onNext={() => choose(selected, "usage", data.nextCursor)}
              onExpired={expire}
            />
          )}
          {data && "items" in data && selection.view === "bots" && (
            <section className="panel bots" aria-label="Tenant bot inventory">
              <div className="panel-heading">
                <h2>Registered bots</h2>
                <span>{data.items.length} on this page · Up to 50</span>
              </div>
              {data.items.length ? (
                <ul className="bot-list">
                  {data.items.map((bot) => (
                    <li key={bot.id}>
                      <div className="bot-identity">
                        <h3>{bot.name}</h3>
                        <code>{bot.id}</code>
                        <p>
                          Added{" "}
                          <time dateTime={bot.created}>
                            {new Date(bot.created).toLocaleDateString("en-GB", {
                              timeZone: "UTC",
                            })}
                          </time>
                        </p>
                      </div>
                      <div className="bot-status">
                        <span className="bot-field">Configuration</span>
                        <strong>{bot.active ? "Active" : "Inactive"}</strong>
                        <span className="bot-field">Stored webhook status</span>
                        <span
                          className={`state${["failed", "unknown"].includes(bot.webhook) ? " attention" : ""}`}
                        >
                          {stateLabels[bot.webhook]}
                        </span>
                        <p>
                          Updated{" "}
                          <time dateTime={bot.updated}>
                            {new Date(bot.updated).toLocaleDateString("en-GB", {
                              timeZone: "UTC",
                            })}
                          </time>
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="empty">
                  <h3>
                    {selection.cursor
                      ? "End of bot list"
                      : "No bots registered"}
                  </h3>
                  <p>
                    {selection.cursor
                      ? "There are no more bots after this cursor."
                      : "This organization has no registered bots."}
                  </p>
                </div>
              )}
              <nav className="bot-pagination" aria-label="Bot pages">
                <button
                  type="button"
                  className="refresh"
                  disabled={!selection.cursor || busy}
                  onClick={() => choose(selected, "bots")}
                >
                  First page
                </button>
                <button
                  type="button"
                  className="refresh"
                  disabled={!data.nextCursor || busy}
                  onClick={() => choose(selected, "bots", data.nextCursor)}
                >
                  Next page <span aria-hidden="true">→</span>
                </button>
              </nav>
              <p className="activity-foot">
                Configuration records from WebHook Manager. No live Telegram
                health check is performed. Refresh returns to the first page.
              </p>
            </section>
          )}
        </div>
        <footer className="footer">
          NexusCore <span>Tenant-isolated observability</span>
        </footer>
      </main>
    </div>
  );
}
