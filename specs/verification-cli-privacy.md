# Verification CLI argument privacy

The metrics, standalone smoke, AI smoke and Telegram-edge CLIs must reject
invalid syntax with exit 2 and static `Invalid arguments; details withheld`
diagnostics. Never echo a rejected value, unknown option or extra positional
argument. Reuse the existing local-tool parser pattern; AI may reuse its already
imported smoke parser. Add no module dependencies or container mounts.

Argument rejection must precede HTTP, Docker, fixture/temp-directory creation
and fixture filesystem writes. Help and all valid options/defaults/runtime behavior
remain unchanged. Verify both direct calls with runtime-boundary guards and
actual subprocess errors/help. Run root checks and fresh read-only/security
review before publication. This changes CLI syntax diagnostics only; Docker
runtime acceptance and deployment/provider activation remain separate.
