"use client";

import { useEffect, useRef, useState } from "react";
import { api, RequestError } from "../lib/client.ts";

export default function BotRegistration({
  tenant,
  onSaving,
  onCreated,
  onExpired,
}: {
  tenant: string;
  onSaving: (value: boolean) => void;
  onCreated: () => void;
  onExpired: () => void;
}) {
  const [saving, setSaving] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true),
    inFlight = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      onSaving(false);
    };
  }, [onSaving]);
  async function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current || uncertain) return;
    const form = event.currentTarget,
      values = new FormData(form);
    const name = values.get("name"),
      token = values.get("token");
    form.reset();
    if (
      typeof name !== "string" ||
      !name.trim() ||
      Array.from(name.trim()).length > 128 ||
      typeof token !== "string" ||
      token.length > 256 ||
      !/^[0-9]+:[A-Za-z0-9_-]+$/.test(token)
    ) {
      setError("Enter a name and a valid bot token.");
      return;
    }
    inFlight.current = true;
    setSaving(true);
    onSaving(true);
    setError("");
    try {
      await api(`/api/bot-registration?tenant=${tenant}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, token }),
      });
      if (mounted.current) onCreated();
    } catch (reason) {
      if (!mounted.current) return;
      if (reason instanceof RequestError && reason.status === 401) onExpired();
      else if (
        reason instanceof RequestError &&
        [400, 403, 404, 409, 429].includes(reason.status)
      )
        setError(
          reason.status === 409
            ? "This bot is already registered."
            : "Registration was rejected. Check access and details before trying again.",
        );
      else {
        setUncertain(true);
        setError(
          "Registration could not be confirmed. Refresh the bot list before trying again.",
        );
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) {
        setSaving(false);
        onSaving(false);
      }
    }
  }
  return (
    <form className="usage-form" onSubmit={submit} autoComplete="off">
      <label>
        Bot name
        <input
          name="name"
          maxLength={256}
          required
          disabled={saving || uncertain}
        />
      </label>
      <label>
        Telegram bot token
        <input
          name="token"
          type="password"
          maxLength={256}
          required
          autoComplete="off"
          disabled={saving || uncertain}
        />
      </label>
      <button type="submit" className="refresh" disabled={saving || uncertain}>
        {saving ? "Registering…" : "Register bot"}
      </button>
      <p>Registration verifies the token. It does not configure a webhook.</p>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}
