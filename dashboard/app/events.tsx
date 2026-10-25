"use client";

import { useState } from "react";
import {
  type EventFilters,
  filterObservations,
  kindLabels,
  needsAttention,
  stateLabels,
} from "../lib/event-view.ts";
import type { Overview } from "../lib/overview.ts";

const initial: EventFilters = {
  kind: "all",
  receiver: "all",
  query: "",
  attention: false,
};

export default function Events({ data }: { data: Overview }) {
  const [filters, setFilters] = useState(initial);
  const events = filterObservations(data.events, filters);
  return (
    <section className="panel events" aria-label="Recent observation explorer">
      <div className="panel-heading">
        <h2>Recent observations</h2>
        <span role="status">
          {events.length} of {data.events.length} loaded
        </span>
      </div>
      <p className="events-window">
        Latest 10 merged observations. Filters apply only to this loaded window.
        Responding receivers:{" "}
        {Number(data.sources.eventpipe) + Number(data.sources.pipewatch)} / 2.
      </p>
      <ul className="event-receivers" aria-label="Receiver responses">
        <li>
          EventPipe: {data.sources.eventpipe ? "Responding" : "Unavailable"}
        </li>
        <li>
          PipeWatch: {data.sources.pipewatch ? "Responding" : "Unavailable"}
        </li>
      </ul>
      {(!data.sources.eventpipe || !data.sources.pipewatch) && (
        <p className="notice" role="status">
          Some receiver data is unavailable. Only successful reads are shown.
        </p>
      )}
      <fieldset className="event-filters">
        <legend>Filter loaded observations</legend>
        <label>
          Event kind
          <select
            value={filters.kind}
            onChange={(event) =>
              setFilters({
                ...filters,
                kind: event.target.value as EventFilters["kind"],
              })
            }
          >
            <option value="all">All kinds</option>
            <option value="auth">Tenant access</option>
            <option value="webhook">Bot configuration</option>
            <option value="agent">AI jobs</option>
          </select>
        </label>
        <label>
          Receiver
          <select
            value={filters.receiver}
            onChange={(event) =>
              setFilters({
                ...filters,
                receiver: event.target.value as EventFilters["receiver"],
              })
            }
          >
            <option value="all">All receivers</option>
            <option value="EventPipe">EventPipe</option>
            <option value="PipeWatch">PipeWatch</option>
          </select>
        </label>
        <label>
          Event or bot ID
          <input
            type="search"
            maxLength={36}
            placeholder="UUID or part of UUID"
            value={filters.query}
            onChange={(event) =>
              setFilters({ ...filters, query: event.target.value })
            }
          />
        </label>
        <label className="attention-filter">
          <input
            type="checkbox"
            checked={filters.attention}
            onChange={(event) =>
              setFilters({ ...filters, attention: event.target.checked })
            }
          />
          Needs attention
        </label>
        <button
          type="button"
          className="refresh"
          onClick={() => setFilters(initial)}
        >
          Reset filters
        </button>
      </fieldset>
      {events.length ? (
        <ol className="event-list">
          {events.map((event) => (
            <li key={event.id}>
              <div className="event-detail-heading">
                <h3>{kindLabels[event.kind]}</h3>
                <span
                  className={`state${needsAttention(event) ? " attention" : ""}`}
                >
                  {event.conflict
                    ? "Conflicting evidence"
                    : stateLabels[event.state] || "Observed"}
                </span>
              </div>
              <dl>
                <div>
                  <dt>Event ID</dt>
                  <dd>
                    <code>{event.id}</code>
                  </dd>
                </div>
                <div>
                  <dt>Bot ID</dt>
                  <dd>
                    {event.bot ? <code>{event.bot}</code> : "Tenant access"}
                  </dd>
                </div>
                <div>
                  <dt>Observed at (UTC)</dt>
                  <dd>
                    <time dateTime={event.at}>
                      {new Date(event.at).toLocaleString("en-GB", {
                        timeZone: "UTC",
                      })}
                    </time>
                  </dd>
                </div>
                <div>
                  <dt>Receivers</dt>
                  <dd>{event.receivers.join(" · ")}</dd>
                </div>
                {event.attempts !== undefined && (
                  <div>
                    <dt>Observed attempts</dt>
                    <dd>{event.attempts}</dd>
                  </div>
                )}
              </dl>
              {event.conflict && (
                <p className="event-conflict">
                  Receivers report different snapshots. This row is not a
                  confirmed state.
                </p>
              )}
            </li>
          ))}
        </ol>
      ) : (
        <div className="empty">
          <h3>
            {data.events.length
              ? "No matching observations"
              : "No observations found"}
          </h3>
          <p>
            {data.events.length
              ? "Change or reset filters to see other loaded observations."
              : data.sources.eventpipe || data.sources.pipewatch
                ? "No supported events appeared in the recent receiver windows."
                : "Receiver reads are unavailable. Refresh to try again."}
          </p>
        </div>
      )}
      <p className="activity-foot">
        Safe snapshots only. No historical search, raw logs or lifetime totals.
        Refresh reloads the recent window and resets filters.
      </p>
    </section>
  );
}
