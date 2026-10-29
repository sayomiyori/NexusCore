"use client";

import { useEffect, useRef, useState } from "react";
import { api, RequestError } from "../lib/client.ts";

export default function BotWebhookPreview({
  tenant,
  bot,
  disabled,
  onExpired,
}: {
  tenant: string;
  bot: string;
  disabled: boolean;
  onExpired: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState(false);
  const current = useRef<AbortController | null>(null);
  useEffect(() => () => current.current?.abort(), []);
  async function preview() {
    if (current.current || disabled) return;
    const controller = new AbortController();
    current.current = controller;
    setBusy(true);
    setMessage("");
    setError(false);
    try {
      await api(`/api/bot-webhook-preview?tenant=${tenant}&bot=${bot}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
        signal: controller.signal,
      });
      if (!controller.signal.aborted)
        setMessage("Preparation check passed. No webhook was changed.");
    } catch (reason) {
      if (controller.signal.aborted) return;
      if (reason instanceof RequestError && reason.status === 401) onExpired();
      else {
        setError(true);
        setMessage(
          "Preparation check unavailable. Check access or try again later.",
        );
      }
    } finally {
      if (!controller.signal.aborted) {
        current.current = null;
        setBusy(false);
      }
    }
  }
  return (
    <div>
      <button
        type="button"
        className="refresh"
        disabled={busy || disabled}
        onClick={preview}
      >
        {busy ? "Checking…" : "Check webhook preparation"}
      </button>
      {message && <p role={error ? "alert" : "status"}>{message}</p>}
    </div>
  );
}
