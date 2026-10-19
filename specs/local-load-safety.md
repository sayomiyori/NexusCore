# Local load probe safety

Strengthen the existing capacity-check tool without changing its URL allowlist,
request profile, report schema, gates or deployment. No service/WSL/data changes,
new dependencies or real Telegram/LLM traffic are needed.

## Independently verified increments

1. CLI argument errors exit 2 with static diagnostics. Malformed numeric/status
   values, unknown options, extra positional arguments and missing values must
   never echo caller input. Help remains available. Keep the existing safe
   runtime failure and exclusive-output behavior.
2. Stream response bodies as raw bytes, retaining no response body and performing
   no decompression. Limit each response to 64 KiB of wire payload, independent
   of Content-Length or transfer encoding. Exceeding the limit fails the probe,
   closes the response/client, cancels peer loops and creates no success report.
   Latency still covers the entire accepted response; status/redirect checks
   precede body reads. Exact-limit, empty and compressed responses remain valid.

Keep existing tests/callers compatible. Verify narrow regressions, the full root
suite, Ruff/compilation and fresh read-only/security review before each commit.
Use only synthetic disposable loopback listeners for actual CLI checks.

The 64 KiB cap bounds response payload, not total process memory or elapsed time.
HTTPX retains its five-second inactivity timeout; a trickling peer can take longer
than the requested duration. Sustained business capacity and deployment/off-host
recovery remain separate roadmap work.
