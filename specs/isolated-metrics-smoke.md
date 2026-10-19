# Existing exporter and platform-denial acceptance

Verify the first observability boundary without deploying Prometheus, Grafana,
EventPipe or changing any service. Use fresh isolated smoke fixtures, synthetic
data and the existing exporters; no main data, WSL, live Telegram/LLM or dependency
changes. This is endpoint/marker acceptance, not a complete Prometheus parser,
tenant dashboard, event-pipeline integration or production scrape configuration.

## Contract

Run `scripts/verify_metrics.py ROLE [--platform]` only inside inspected owned API
containers. It always sends a direct loopback GET to `127.0.0.1:8000/metrics`,
with a five-second timeout, no proxy/redirect handling and at most 1 MiB read.
There is no caller-supplied URL, auth, body, output path or application import.

In standalone mode all three exporters must return HTTP 200 and `text/plain`
with the existing required `# TYPE` markers: Auth registration/active sessions,
WebHook ingress/delivery, Agent document/chunk/LLM request families. Only marker
presence is checked; raw values, labels and bodies are never printed or saved.

In controlled platform mode Auth still exports its existing metrics. WebHook
must return its existing 503 JSON denial and Agent its existing 404 JSON denial,
each with the exact known `detail` body and no extra fields/exposition. Do not
weaken these closures to make a scrape pass.

Add this stage after functional verification and before optional load. Reuse
the exact owned-API/running/no-OOM check from the load stage. Mount only this
script read-only at its fixed verification path. Store safe role summaries in
the receipt and its source hash. A failure fails the smoke and retains existing
owned-only cleanup and partial-report behavior.

## Acceptance

- Test each standalone exporter marker set and each platform denial.
- Reject unexpected status/content type, missing markers, oversized or invalid
  bodies and malformed/widened denial JSON; always close the connection.
- Test actual CLI safe output/failure, ownership and mount boundaries, and both
  drivers' receipt/failure paths without using Docker in root unit tests.
- Run root checks/review and real sequential isolated scanner/load smoke;
  prove original deployment data/configuration/resources/scanners unchanged.
