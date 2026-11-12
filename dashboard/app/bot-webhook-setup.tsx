"use client";

import { useEffect, useRef, useState } from "react";
import { api, RequestError } from "../lib/client.ts";

export default function BotWebhookSetup({
  tenant,
  bot,
  disabled,
  onExpired,
  onConfigured,
}: {
  tenant: string;
  bot: string;
  disabled: boolean;
  onExpired: () => void;
  onConfigured: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState(false);
  const current = useRef<AbortController | null>(null);
  useEffect(() => () => current.current?.abort(), []);
  function cancel() {
    setConfirming(false);
    setMessage("");
    setError(false);
  }
  async function setup() {
    if (current.current || disabled) return;
    const controller = new AbortController();
    current.current = controller;
    setBusy(true);
    setMessage("");
    setError(false);
    try {
      await api(`/api/bot-webhook-setup?tenant=${tenant}&bot=${bot}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
        signal: controller.signal,
      });
      if (!controller.signal.aborted) {
        setConfirming(false);
        setMessage("Webhook configured. The stored status refreshes now.");
        onConfigured();
      }
    } catch (reason) {
      if (controller.signal.aborted) return;
      if (reason instanceof RequestError && reason.status === 401) onExpired();
      else {
        setError(true);
        setMessage(
          reason instanceof RequestError && reason.status === 409
            ? "The bot state changed. Refresh the inventory and try again."
            : reason instanceof RequestError &&
                [400, 403, 404].includes(reason.status)
              ? reason.message
              : "Webhook setup is unconfirmed. Refresh the bot inventory before retrying.",
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
      {confirming ? (
        <>
          <p>This configures the Telegram webhook for this bot.</p>
          <button
            type="button"
            className="refresh"
            disabled={busy || disabled}
            onClick={setup}
          >
            {busy ? "Configuring…" : "Confirm setup"}
          </button>
          <button
            type="button"
            className="text-button"
            disabled={busy}
            onClick={cancel}
          >
            Cancel
          </button>
        </>
      ) : (
        <button
          type="button"
          className="refresh"
          disabled={busy || disabled}
          onClick={() => {
            setConfirming(true);
            setMessage("");
            setError(false);
          }}
        >
          Configure webhook
        </button>
      )}
      {message && <p role={error ? "alert" : "status"}>{message}</p>}
    </div>
  );
}
