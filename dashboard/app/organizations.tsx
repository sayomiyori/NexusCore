"use client";

import { useState } from "react";
import { filterOrganizations } from "../lib/organization-view.ts";
import type { Tenant } from "../lib/overview.ts";

export default function Organizations({
  tenants,
  selected,
  hasMore,
  disabled,
  onOpen,
}: {
  tenants: Tenant[];
  selected: string;
  hasMore: boolean;
  disabled: boolean;
  onOpen: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const matches = filterOrganizations(tenants, query);
  return (
    <section className="panel activity">
      <div className="panel-heading">
        <h2>Memberships</h2>
        <span role="status">
          {matches.length} of {tenants.length} loaded
        </span>
      </div>
      <fieldset className="event-filters">
        <legend>Search loaded organizations</legend>
        <label>
          Organization name
          <input
            type="search"
            maxLength={128}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </fieldset>
      {matches.length ? (
        <ul className="bot-list">
          {matches.map((tenant) => (
            <li key={tenant.id}>
              <div className="bot-identity">
                <h3>{tenant.name}</h3>
                <p>
                  {tenant.id === selected
                    ? "Current organization"
                    : "Available organization"}
                </p>
              </div>
              <div className="bot-status">
                <span className="bot-field">Your role</span>
                <strong>{tenant.role}</strong>
                <button
                  type="button"
                  className="refresh"
                  disabled={disabled}
                  onClick={() => onOpen(tenant.id)}
                  aria-label={`Open ${tenant.name} overview`}
                >
                  Open overview
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <div className="empty">
          <h3>No matching organizations</h3>
          <p>Search applies only to loaded organizations.</p>
        </div>
      )}
      <p className="activity-foot">
        {hasMore
          ? "More organizations may be available. Use Load more organizations."
          : "This list reflects loaded membership pages and may change."}
      </p>
    </section>
  );
}
