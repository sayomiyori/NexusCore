"use client";

import { useEffect, useState } from "react";
import { api, RequestError } from "../lib/client.ts";
import type { KnowledgePage } from "../lib/knowledge.ts";
import { knowledgeStatus } from "../lib/knowledge-status.ts";

export function KnowledgeStatus({
  status,
  chunks,
}: {
  status: string;
  chunks: number;
}) {
  const { label, detail } = knowledgeStatus(status);
  return (
    <>
      <span className="bot-field">Index status</span>
      <strong>{label}</strong>
      <p>{chunks} chunks</p>
      <p>{detail}</p>
    </>
  );
}

export default function Knowledge({
  tenant,
  onExpired,
}: {
  tenant: string;
  onExpired: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [page, setPage] = useState<KnowledgePage | null>(null);
  const [error, setError] = useState("");
  // biome-ignore lint/correctness/useExhaustiveDependencies: An explicit retry repeats the current page read.
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
        else setError("Unable to load documents. Retry to try again.");
      });
    return () => controller.abort();
  }, [tenant, offset, onExpired, attempt]);
  return (
    <section className="panel activity">
      <div className="panel-heading">
        <h2>Documents</h2>
        <span>Up to 50 per page</span>
      </div>
      {error ? (
        <div className="empty">
          <p role="alert">{error}</p>
          <button
            type="button"
            className="refresh"
            onClick={() => setAttempt((value) => value + 1)}
          >
            Retry page
          </button>
        </div>
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
                    <KnowledgeStatus
                      status={item.status}
                      chunks={item.chunks}
                    />
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
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 50))}
            >
              Previous page
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
