"use client";

import { useEffect, useState } from "react";
import { api, RequestError } from "../lib/client.ts";
import type { KnowledgePage } from "../lib/knowledge.ts";

export default function Knowledge({
  tenant,
  onExpired,
}: {
  tenant: string;
  onExpired: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<KnowledgePage | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setPage(null);
    setError("");
    api<KnowledgePage>(`/api/knowledge?tenant=${tenant}&offset=${offset}`, {
      signal: controller.signal,
    })
      .then((result) => {
        if (!controller.signal.aborted) setPage(result);
      })
      .catch((reason) => {
        if (controller.signal.aborted) return;
        if (reason instanceof RequestError && reason.status === 401)
          onExpired();
        else setError("Unable to load documents. Refresh to try again.");
      });
    return () => controller.abort();
  }, [tenant, offset, onExpired]);
  return (
    <section className="panel activity">
      <div className="panel-heading">
        <h2>Documents</h2>
        <span>Up to 50 per page</span>
      </div>
      {error ? (
        <p role="alert">{error}</p>
      ) : !page ? (
        <p role="status">Loading documents…</p>
      ) : (
        <>
          {page.items.length ? (
            <ul className="bot-list">
              {page.items.map((item) => (
                <li key={item.id}>
                  <div className="bot-identity">
                    <h3>{item.title}</h3>
                    <code>Document {item.id}</code>
                    <p>{item.type.toUpperCase()}</p>
                  </div>
                  <div className="bot-status">
                    <span className="bot-field">Index status</span>
                    <strong>{item.status}</strong>
                    <p>{item.chunks} chunks</p>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="empty">
              <h3>{offset ? "End of document list" : "No documents"}</h3>
              <p>Documents for this organization appear here.</p>
            </div>
          )}
          <nav className="bot-pagination" aria-label="Document pages">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset(0)}
            >
              First page
            </button>
            <button
              type="button"
              disabled={page.nextOffset === null}
              onClick={() => setOffset(page.nextOffset ?? 0)}
            >
              Next page
            </button>
          </nav>
          <p className="activity-foot">
            Pages may shift when documents change. A pending document may need
            operator attention.
          </p>
        </>
      )}
    </section>
  );
}
