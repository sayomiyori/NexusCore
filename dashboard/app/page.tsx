"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  type BotAction,
  type BotNavigation,
  begin,
  canGoFirst,
  canGoPrevious,
  canRetry,
  cursorFor,
  fail,
  initialNavigation,
  previousCursor,
  resetNavigation,
  succeed,
} from "../lib/bot-history.ts";
import { filterBots } from "../lib/bot-view.ts";
import type { BotPage } from "../lib/bots.ts";
import { api, RequestError } from "../lib/client.ts";
import { kindLabels, needsAttention, stateLabels } from "../lib/event-view.ts";
import type { Overview, Tenant } from "../lib/overview.ts";
import BotRegistration from "./bot-registration.tsx";
import BotWebhookPreview from "./bot-webhook-preview.tsx";
import Configuration from "./configuration.tsx";
import Events from "./events.tsx";
import Jobs from "./jobs.tsx";
import Knowledge from "./knowledge.tsx";
import Organizations from "./organizations.tsx";
import Usage from "./usage.tsx";

type TenantPage = { items: Tenant[]; hasMore: boolean; offset: number };
type BotView = "bots" | "usage" | "jobs" | "configuration";
type SettingsTarget = "tenant" | "bot";
type Selection = {
  tenant: string;
  view:
    | "overview"
    | "tenants"
    | "bots"
    | "events"
    | "usage"
    | "jobs"
    | "configuration"
    | "knowledge";
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
    tenants: "Organizations",
    bots: "Bots",
    events: "Events",
    usage: "Usage",
    jobs: "AI jobs",
    configuration: "AI Configuration",
    knowledge: "Knowledge Base",
  }[selection.view];
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsTarget, setSettingsTarget] =
    useState<SettingsTarget>("tenant");
  const [knowledgeRefresh, setKnowledgeRefresh] = useState(0);
  const [botQuery, setBotQuery] = useState("");
  const [botPages, setBotPages] = useState<BotNavigation>(initialNavigation);
  const [botLoading, setBotLoading] = useState(false);
  const [data, setData] = useState<Overview | BotPage | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [membershipState, setMembershipState] = useState<
    "loading" | "ready" | "error"
  >("loading");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [previousSession, setPreviousSession] = useState(false);
  const [busy, setBusy] = useState(false);
  const [mfa, setMfa] = useState(false);
  const query = useRef<AbortController | null>(null);
  const membershipQuery = useRef<AbortController | null>(null);
  // Synchronous same-tab guard shared by login and both sign-out actions. React
  // state updates are async, so `busy` alone cannot stop a second submit that
  // slips in before the next render.
  const authInFlight = useRef(false);
  const codeInput = useRef<HTMLInputElement>(null);
  const botPageRequest = useRef(false);

  const choose = useCallback(
    (id: string, view?: Selection["view"], cursor: string | null = null) => {
      query.current?.abort();
      botPageRequest.current = false;
      setData(null);
      setError("");
      setBotLoading(false);
      setBotPages(resetNavigation());
      setBotQuery("");
      setSettingsTarget("tenant");
      setSelection((current) => ({
        tenant: id,
        view: view ?? current.view,
        cursor,
      }));
    },
    [],
  );

  const pageBots = useCallback((action: BotAction, view: BotView = "bots") => {
    query.current?.abort();
    botPageRequest.current = true;
    setData(null);
    setError("");
    setBotLoading(true);
    setBotPages((state) => begin(state, action));
    setSelection((current) => ({
      tenant: current.tenant,
      view,
      cursor: cursorFor(action),
    }));
  }, []);

  const expire = useCallback(() => {
    // Never abort a pending sign-out here. Aborting the fetch only discards the
    // client-side promise; it cannot cancel the server response or the cookie
    // clearing that response carries. The in-flight guard owns `busy` until the
    // DELETE actually settles.
    membershipQuery.current?.abort();
    choose("");
    setTenants([]);
    setHasMore(false);
    setOffset(0);
    if (!authInFlight.current) setBusy(false);
    setScreen("login");
    setMfa(false);
    setNotice("");
    setPreviousSession(true);
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
      setMembershipState("ready");
      setScreen("overview");
    },
    [choose],
  );

  useEffect(() => {
    const controller = new AbortController();
    membershipQuery.current = controller;
    api<TenantPage>("/api/tenants", { signal: controller.signal })
      .then((page) => {
        if (!controller.signal.aborted) receiveTenants(page);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) {
          setScreen("login");
          if (reason instanceof RequestError && reason.status === 401)
            setPreviousSession(true);
          else setError("Unable to load your workspace. Try signing in again.");
        }
      });
    return () => {
      controller.abort();
      membershipQuery.current?.abort();
    };
  }, [receiveTenants]);

  useEffect(() => {
    if (mfa) codeInput.current?.focus();
  }, [mfa]);

  useEffect(() => {
    const tenant = selection.tenant;
    if (!tenant || screen !== "overview") return;
    if (["knowledge", "tenants"].includes(selection.view)) return;
    const controller = new AbortController();
    query.current = controller;
    const botView = ["bots", "usage", "jobs", "configuration"].includes(
      selection.view,
    );
    const path = `/api/${botView ? "bots" : "overview"}?tenant=${tenant}${botView && selection.cursor ? `&cursor=${selection.cursor}` : ""}`;
    api<Overview | BotPage>(path, {
      signal: controller.signal,
    })
      .then((result) => {
        if (controller.signal.aborted) return;
        setData(result);
        setBotLoading(false);
        if (botPageRequest.current) setBotPages((state) => succeed(state));
      })
      .catch((reason) => {
        if (controller.signal.aborted) return;
        setBotLoading(false);
        if (reason instanceof RequestError && reason.status === 401) {
          expire();
        } else if (botPageRequest.current) {
          setBotPages((state) => fail(state));
          setError(
            selection.view === "bots"
              ? "This bot page could not be loaded. Retry the page, step back, or return to the first page."
              : "This bot page could not be loaded. Refresh to try again.",
          );
        } else setError("Unable to load this tenant. Refresh to try again.");
      });
    return () => controller.abort();
  }, [selection, screen, expire]);

  async function signIn(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    // A login must never race a pending previous-session sign-out: its late
    // Set-Cookie clearing could log out the credentials just issued here. The
    // guard is checked and set synchronously, and the pending DELETE is left
    // alone because aborting it cannot stop the server from answering.
    if (authInFlight.current) return;
    authInFlight.current = true;
    const form = event.currentTarget,
      values = new FormData(form);
    setBusy(true);
    setError("");
    setNotice("");
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
        setPreviousSession(false);
        receiveTenants(await api<TenantPage>("/api/tenants"));
      }
    } catch (reason) {
      setError(
        reason instanceof RequestError
          ? reason.message
          : "Unable to sign in. Try again.",
      );
    } finally {
      authInFlight.current = false;
      setBusy(false);
    }
  }

  async function signOutPrevious() {
    if (authInFlight.current) return;
    authInFlight.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<{ signedOut: boolean; revoked: number }>(
        "/api/session",
        { method: "DELETE" },
      );
      // The route clears the challenge cookie too, so the 2FA step cannot
      // continue after a confirmed or unconfirmed attempt.
      setMfa(false);
      setPreviousSession(false);
      setNotice(
        result.revoked > 0
          ? "Previous session signed out."
          : "No stored session was found.",
      );
    } catch (reason) {
      // A 403 guard failure happens before the route clears anything, and a
      // transport failure or an infrastructure error may also leave cookies in
      // place. Keep the retry control instead of assuming every HTTP error
      // cleared the browser's credentials.
      setError(
        reason instanceof RequestError
          ? reason.message
          : "Sign-out could not be confirmed. Try again.",
      );
    } finally {
      // Release only after the DELETE has settled. A late login cannot overtake
      // this request, and the guard is never cleared by expiry.
      authInFlight.current = false;
      setBusy(false);
    }
  }

  async function moreTenants(refresh = false) {
    membershipQuery.current?.abort();
    const controller = new AbortController();
    membershipQuery.current = controller;
    setBusy(true);
    setError("");
    if (refresh) {
      choose("", "tenants");
      setTenants([]);
      setHasMore(false);
      setOffset(0);
      setMembershipState("loading");
    }
    try {
      const page = await api<TenantPage>(
        `/api/tenants?offset=${refresh ? 0 : offset}`,
        { signal: controller.signal },
      );
      if (!controller.signal.aborted) receiveTenants(page);
    } catch (reason) {
      if (controller.signal.aborted) return;
      if (reason instanceof RequestError && reason.status === 401) expire();
      else {
        if (refresh) setMembershipState("error");
        setError(
          refresh
            ? "Unable to load organizations. Refresh to try again."
            : "Unable to load more organizations. Try again.",
        );
      }
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  async function signOut() {
    if (authInFlight.current) return;
    authInFlight.current = true;
    query.current?.abort();
    membershipQuery.current?.abort();
    setBusy(true);
    let message = "";
    try {
      await api("/api/session", { method: "DELETE" });
    } catch (reason) {
      message =
        reason instanceof RequestError
          ? reason.message
          : "Sign-out could not be confirmed. Try again.";
    } finally {
      authInFlight.current = false;
    }
    choose("");
    setTenants([]);
    setScreen("login");
    setMfa(false);
    setBusy(false);
    setError(message);
  }

  const pending = Boolean(
    selected &&
      !["knowledge", "tenants"].includes(selection.view) &&
      !data &&
      !error &&
      !(selection.view === "bots" && botLoading),
  );
  const botPage =
    data && "items" in data && selection.view === "bots" ? data : null;
  const botMatches = botPage ? filterBots(botPage.items, botQuery) : [];
  const status = error ? (
    <p role="alert" className="notice error">
      {error}
    </p>
  ) : notice ? (
    <p role="status" className="notice">
      {notice}
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
              <button
                type="submit"
                className="primary"
                disabled={busy || savingSettings}
              >
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
                  disabled={busy || savingSettings}
                  onClick={() => {
                    setMfa(false);
                    setError("");
                  }}
                >
                  Back to sign in
                </button>
              )}
            </form>
            {previousSession && (
              <>
                <button
                  type="button"
                  className="text-button"
                  disabled={busy || savingSettings}
                  onClick={signOutPrevious}
                >
                  Sign out previous session
                </button>
                <p className="form-note">
                  If this browser still holds a previous session, sign out
                  before signing in again so AuthFortress can revoke it.
                </p>
              </>
            )}
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
            disabled={busy || savingSettings || !tenants.length}
            onChange={(event) => choose(event.target.value)}
          >
            {!tenants.length && (
              <option value="">
                {membershipState === "loading"
                  ? "Loading organizations…"
                  : membershipState === "error"
                    ? "Organizations unavailable"
                    : "No organizations"}
              </option>
            )}
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
            disabled={busy || savingSettings}
            onClick={() => moreTenants()}
          >
            Load more organizations
          </button>
        )}
        <nav className="workspace-nav" aria-label="Workspace sections">
          {(
            [
              "overview",
              "tenants",
              "bots",
              "events",
              "usage",
              "jobs",
              "configuration",
              "knowledge",
            ] as const
          ).map((view) => (
            <button
              key={view}
              type="button"
              disabled={busy || savingSettings}
              className={`nav-item${selection.view === view ? " nav-active" : ""}`}
              aria-current={selection.view === view ? "page" : undefined}
              onClick={() => choose(selected, view)}
            >
              <span aria-hidden="true">
                {view === "overview"
                  ? "▦"
                  : view === "tenants"
                    ? "▤"
                    : view === "bots"
                      ? "◇"
                      : view === "events"
                        ? "≡"
                        : view === "usage"
                          ? "$"
                          : "AI"}
              </span>
              {
                {
                  overview: "Overview",
                  tenants: "Organizations",
                  bots: "Bots",
                  events: "Events",
                  usage: "Usage",
                  jobs: "AI jobs",
                  configuration: "AI Configuration",
                  knowledge: "Knowledge Base",
                }[view]
              }
              {selection.view === view && (
                <span className="nav-dot" aria-hidden="true" />
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="read-only">
            {selection.view === "configuration"
              ? "MODEL SETTINGS"
              : selection.view === "bots"
                ? "BOT REGISTRATION"
                : "READ ONLY"}
          </span>
          <p>
            Observe your workspace.
            <br />
            {selection.view === "configuration"
              ? "Saving requires owner access."
              : selection.view === "bots"
                ? "Registration requires owner access."
                : "Business data stays unchanged."}
          </p>
          <button
            type="button"
            className="signout"
            disabled={busy || savingSettings}
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
                {selection.view === "tenants"
                  ? "Organizations loaded for your account"
                  : selection.view === "knowledge"
                    ? "Documents for "
                    : selection.view === "configuration"
                      ? "Tenant and bot AI configuration for "
                      : selection.view === "jobs"
                        ? "Stored job metadata for "
                        : selection.view === "usage"
                          ? "Recorded usage for "
                          : selection.view === "bots"
                            ? "Bot configuration for "
                            : "Recent observations across "}
                {selection.view !== "tenants" &&
                  (data?.tenant.name ||
                    tenants.find((item) => item.id === selected)?.name ||
                    "your organization")}
                .
              </p>
            </div>
            <button
              type="button"
              className="refresh"
              disabled={
                pending ||
                busy ||
                savingSettings ||
                (selection.view !== "tenants" && !selected)
              }
              onClick={() => {
                if (selection.view === "tenants") {
                  void moreTenants(true);
                  return;
                }
                if (selection.view === "knowledge")
                  setKnowledgeRefresh((value) => value + 1);
                choose(selected);
              }}
            >
              <span aria-hidden="true">↻</span> Refresh
            </button>
          </div>
          {status}
          {selection.view === "tenants" && tenants.length > 0 && (
            <Organizations
              tenants={tenants}
              selected={selected}
              hasMore={hasMore}
              disabled={busy || savingSettings}
              onOpen={(id) => choose(id, "overview")}
            />
          )}
          {selected && selection.view === "knowledge" && (
            <Knowledge
              key={`${selected}-${knowledgeRefresh}`}
              tenant={selected}
              onExpired={expire}
            />
          )}
          {membershipState === "loading" ? (
            <section className="empty panel" aria-live="polite">
              <p role="status">Loading organizations…</p>
            </section>
          ) : membershipState === "error" ? (
            <section className="empty panel">
              <h2>Organizations unavailable</h2>
              <p>Open Organizations and Refresh to try again.</p>
            </section>
          ) : !tenants.length ? (
            <section className="empty panel">
              <h2>No organizations yet</h2>
              <p>This account has no available tenant memberships.</p>
            </section>
          ) : pending ? (
            <section className="empty panel" aria-live="polite">
              <div className="loader" aria-hidden="true" />
              <p role="status">
                {["bots", "usage", "jobs", "configuration"].includes(
                  selection.view,
                )
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
              canFirst={canGoFirst(botPages)}
              canPrevious={canGoPrevious(botPages)}
              onFirst={() => pageBots({ kind: "first" }, "usage")}
              onPrevious={() =>
                pageBots(
                  { kind: "previous", cursor: previousCursor(botPages) },
                  "usage",
                )
              }
              onNext={() =>
                data.nextCursor &&
                pageBots({ kind: "next", cursor: data.nextCursor }, "usage")
              }
              onExpired={expire}
            />
          )}
          {data && "items" in data && selection.view === "configuration" && (
            <Configuration
              onSaving={setSavingSettings}
              data={data}
              target={settingsTarget}
              onTargetChange={setSettingsTarget}
              canFirst={canGoFirst(botPages)}
              canPrevious={canGoPrevious(botPages)}
              onFirst={() => pageBots({ kind: "first" }, "configuration")}
              onPrevious={() =>
                pageBots(
                  { kind: "previous", cursor: previousCursor(botPages) },
                  "configuration",
                )
              }
              onNext={() =>
                data.nextCursor &&
                pageBots(
                  { kind: "next", cursor: data.nextCursor },
                  "configuration",
                )
              }
              onExpired={expire}
            />
          )}
          {data && "items" in data && selection.view === "jobs" && (
            <Jobs
              data={data}
              canFirst={canGoFirst(botPages)}
              canPrevious={canGoPrevious(botPages)}
              onFirst={() => pageBots({ kind: "first" }, "jobs")}
              onPrevious={() =>
                pageBots(
                  { kind: "previous", cursor: previousCursor(botPages) },
                  "jobs",
                )
              }
              onNext={() =>
                data.nextCursor &&
                pageBots({ kind: "next", cursor: data.nextCursor }, "jobs")
              }
              onExpired={expire}
            />
          )}
          {selection.view === "bots" &&
            (botPage || botPages.failed || botLoading) && (
              <section className="panel bots" aria-label="Tenant bot inventory">
                <div className="panel-heading">
                  <h2>Registered bots</h2>
                  <span role="status">
                    {botPage
                      ? `${botMatches.length} of ${botPage.items.length} on this page · Up to 50`
                      : "Page not loaded"}
                  </span>
                </div>
                {botPage?.tenant.role === "owner" && (
                  <BotRegistration
                    tenant={selected}
                    onSaving={setSavingSettings}
                    onCreated={() => choose(selected, "bots")}
                    onExpired={expire}
                  />
                )}
                <fieldset className="event-filters">
                  <legend>Search loaded bots</legend>
                  <label>
                    Bot name
                    <input
                      type="search"
                      maxLength={128}
                      value={botQuery}
                      disabled={busy || savingSettings}
                      onChange={(event) => setBotQuery(event.target.value)}
                    />
                  </label>
                </fieldset>
                {botLoading ? (
                  <div className="empty" aria-live="polite">
                    <div className="loader" aria-hidden="true" />
                    <p role="status">Reading the authorized bot inventory…</p>
                  </div>
                ) : !botPage ? (
                  <div className="empty">
                    <h3>Bot page unavailable</h3>
                    <p>
                      This page could not be loaded. Retry the page, step back,
                      or return to the first page.
                    </p>
                  </div>
                ) : botPage.items.length === 0 ? (
                  <div className="empty">
                    <h3>
                      {botPages.current
                        ? "End of bot list"
                        : "No bots registered"}
                    </h3>
                    <p>
                      {botPages.current
                        ? "There are no more bots after this cursor."
                        : "This organization has no registered bots."}
                    </p>
                  </div>
                ) : botMatches.length === 0 ? (
                  <div className="empty">
                    <h3>No matching bots</h3>
                    <p>Search applies only to loaded bots.</p>
                  </div>
                ) : (
                  <ul className="bot-list">
                    {botMatches.map((bot) => (
                      <li key={bot.id}>
                        <div className="bot-identity">
                          <h3>{bot.name}</h3>
                          <code>{bot.id}</code>
                          <p>
                            Added{" "}
                            <time dateTime={bot.created}>
                              {new Date(bot.created).toLocaleDateString(
                                "en-GB",
                                {
                                  timeZone: "UTC",
                                },
                              )}
                            </time>
                          </p>
                        </div>
                        <div className="bot-status">
                          <span className="bot-field">Configuration</span>
                          <strong>{bot.active ? "Active" : "Inactive"}</strong>
                          <span className="bot-field">
                            Stored webhook status
                          </span>
                          <span
                            className={`state${["failed", "unknown"].includes(bot.webhook) ? " attention" : ""}`}
                          >
                            {stateLabels[bot.webhook]}
                          </span>
                          <p>
                            Updated{" "}
                            <time dateTime={bot.updated}>
                              {new Date(bot.updated).toLocaleDateString(
                                "en-GB",
                                {
                                  timeZone: "UTC",
                                },
                              )}
                            </time>
                          </p>
                          {botPage.tenant.role === "owner" && bot.active && (
                            <BotWebhookPreview
                              tenant={selected}
                              bot={bot.id}
                              disabled={busy || savingSettings}
                              onExpired={expire}
                            />
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
                <nav className="bot-pagination" aria-label="Bot pages">
                  <button
                    type="button"
                    className="refresh"
                    disabled={
                      botLoading ||
                      !canGoFirst(botPages) ||
                      busy ||
                      savingSettings
                    }
                    onClick={() => pageBots({ kind: "first" })}
                  >
                    First page
                  </button>
                  <button
                    type="button"
                    className="refresh"
                    disabled={
                      botLoading ||
                      !canGoPrevious(botPages) ||
                      busy ||
                      savingSettings
                    }
                    onClick={() =>
                      pageBots({
                        kind: "previous",
                        cursor: previousCursor(botPages),
                      })
                    }
                  >
                    <span aria-hidden="true">←</span> Previous page
                  </button>
                  <button
                    type="button"
                    className="refresh"
                    disabled={
                      botLoading ||
                      !botPage?.nextCursor ||
                      busy ||
                      savingSettings
                    }
                    onClick={() =>
                      botPage?.nextCursor &&
                      pageBots({ kind: "next", cursor: botPage.nextCursor })
                    }
                  >
                    Next page <span aria-hidden="true">→</span>
                  </button>
                  {canRetry(botPages) && botPages.attempted && (
                    <button
                      type="button"
                      className="refresh"
                      disabled={botLoading || busy || savingSettings}
                      onClick={() =>
                        botPages.attempted && pageBots(botPages.attempted)
                      }
                    >
                      Retry page
                    </button>
                  )}
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
