// Shared by the BFF (cookie names) and the middleware (HSTS): both policies
// activate only when the dashboard is served from an HTTPS production origin.
// The supported loopback topology stays plain HTTP, so this branch is dormant
// until a reviewed TLS proxy provides DASHBOARD_ORIGIN=https://...
export function httpsOrigin(): boolean {
  return (
    process.env.NODE_ENV === "production" &&
    (process.env.DASHBOARD_ORIGIN || "").startsWith("https://")
  );
}
