# AgentHub knowledge/embedding review — 2026-11-11

Read-only review of the AgentHub embedding and tenant-corpus work that the
roadmap lists as the next P1 item. Follow-up to
`docs/knowledge-embedding-investigation-2026-10-29.md`, which recorded the
original silent-fallback defect at `11352ff`. No AgentHub file, database or
container was modified. This document records what the source implements, what
is only designed, and what is actually verified.

## Repository state

| Item | Value |
| --- | --- |
| Worktree reviewed | `D:/Programming/AgentHub-unified-candidate` |
| HEAD | `4234a19` (`fix(rag): reject structurally incomplete tenant indexes`) |
| Status | clean, detached HEAD |
| `origin/main` in that repository | `4234a19` (same commit) |
| Tags containing it | none; the repository has no tags |
| Local `D:/Programming/AgentHub` checkout | `ba930c5` on `main`, two dozen commits behind; does **not** contain this work |
| Range | `11352ff..4234a19`, 14 commits |

Consequence: the embedding work is reachable only through `origin/main` or the
domestic detached worktree. Anyone running the plain local `AgentHub` checkout
gets none of it, and the live NexusCore stack still pins images that predate it.

## What the range implements

| Commit | Change |
| --- | --- |
| `88dd67a` | A configured Gemini provider can no longer degrade to the SHA-256 fallback: exceptions, empty responses and invalid vectors raise `EmbeddingUnavailable`; worker marks failed, direct RAG returns 503, agent knowledge tool returns a fixed unavailable answer and keeps incurred usage. Tenant paths require a provider client; standalone no-key fallback is preserved. Adds vector-norm checks and `%.9g` query serialization. |
| `84c85f1` | SDK transport test: three `:batchEmbedContents` requests with one sub-request each, explicit `outputDimensionality=1536` only for `gemini-embedding-001`. |
| `2388c7d`, `42919a4` | Read-only operator script `scripts/audit_embedding_fallback.py`: repeatable-read scan, bit-exact float32 comparison against the SHA-256 fallback, aggregate and per-document counts only, static errors, no writes or provider calls. |
| `ff275dc` | Planned index-recovery contract (staging, atomic activation, fence, cache identity). Documentation only. |
| `e9b9a61` | Draft generation design with four new tables and a seven-step coordination protocol. Title says "draft, not implemented". |
| `817e178` | Chunk provenance: the worker reads the source once into bytes, hashes and parses that snapshot, and stores `source_sha256` plus `embedding {provider, model, dimensions}` in chunk metadata. |
| `ebf7093` | Before committing ready chunks the worker re-reads and re-hashes the source; a changed or missing file aborts with a static error and keeps the previous chunks. |
| `e6beda4` | Gemini SDK client uses one attempt and a 20 s transport timeout instead of SDK defaults. |
| `5dbd762` | `MAX_DOCUMENT_CHUNKS` (default 1000, 1..10000) rejects an oversized document after splitting and before any provider call, through the existing failed-document path. |
| `79395a6` | Tenant retrieval requires an exact embedding receipt for the whole selected corpus in the same SQL snapshot, adds a 10 000-chunk cap, moves retrieval before cache reads and versions the tenant cache namespace (`receipt-v1` + model). |
| `cba9eab` | Chunks belonging to non-ready documents make the tenant corpus unavailable while remaining retained for recovery. |
| `baa6253` | Retry replaces a document's retained chunks inside the already-locked transaction instead of appending a second set. |
| `4234a19` | Structural completeness: per-document `chunk_count` must equal the actual chunk count, indexes must be unique and cover `0..count-1`, checked in the same snapshot; documents are capped at 10 000. |

## Specifications and coverage

| Spec | Status | Key tests |
| --- | --- | --- |
| `embedding-provider-failure.md` | implemented | `tests/test_embedding_provider_failure.py`, `tests/test_infrastructure.py:233-327` |
| `tenant-embedding-boundary.md` | implemented | `tests/test_tenant_embedding_boundary.py`, `tests/test_infrastructure.py:292-327` |
| `embedding-request-bounds.md` | implemented | `tests/test_embedding_sdk_transport.py:34-81` |
| `chunk-provenance.md` | implemented | `tests/test_document_snapshot.py`, `tests/test_infrastructure.py:330-366` |
| `document-source-change.md` | implemented | `tests/test_infrastructure.py:369-402` |
| `document-embedding-budget.md` | implemented | `tests/test_document_embedding_budget.py`, `tests/test_infrastructure.py:405-437` |
| `document-retry-replacement.md` | implemented | `tests/test_infrastructure.py:116-159` |
| `tenant-corpus-model-check.md` | implemented | `tests/test_tenant_resources.py:412-471` |
| `tenant-corpus-readiness.md` | implemented | `tests/test_tenant_resources.py:474-504` |
| `tenant-corpus-completeness.md` | implemented | `tests/test_tenant_resources.py:507-557` |
| `fallback-vector-inventory.md` | implemented (operator script) | `tests/test_fallback_inventory.py` |
| `knowledge-index-recovery.md` | **planned only** | none |
| `knowledge-generation-design.md` | **draft only** | none |
| `unified-release.md` | pre-range release contract | `tests/test_unified_release_guard.py`, `tests/test_tenant_migration.py`, `tests/test_platform_schema.py` |

No `knowledge_generation*` implementation or migration exists; `app/db/migrations`
still ends at `004_merge_ai_settings_tenant_resources.py`.

## Test inventory and environment

Embedding-focused files: `test_embedding_provider_failure.py`,
`test_embedding_sdk_transport.py`, `test_tenant_embedding_boundary.py`,
`test_document_snapshot.py`, `test_document_embedding_budget.py`,
`test_fallback_inventory.py`, `test_document_uncertain_outcomes.py`, plus the
tenant/corpus cases in `test_tenant_resources.py` and `test_infrastructure.py`.

- `test_tenant_resources.py` needs a migrated platform PostgreSQL database
  (`AGENTHUB_PLATFORM_TEST_DATABASE_URL`) and Redis for the cache fixture.
- `test_infrastructure.py` needs PostgreSQL and Redis
  (`AGENTHUB_TEST_DATABASE_URL`, `AGENTHUB_TEST_REDIS_URL`).
- `test_fallback_inventory.py` has one PostgreSQL case that skips without it;
  the other three are pure unit tests.
- The remaining files are provider-mocked and network-free.
- CI documents PostgreSQL/pgvector on `55432`, Redis on `6379`,
  `AGENTHUB_CREATE_ISOLATED_TEST_DATABASES=yes` and `GEMINI_API_KEY=""`;
  the pytest command is `pytest -q tests/`.
- `docker-compose.verification.yml` and `docs/verification-checkpoint.md` give
  loopback fixture ports and env exports for a local run.

## Verification status

**No recorded run covers commits `84c85f1..4234a19`.** The strongest in-tree
evidence is scoped to the first commit only:
`docs/ERRORS.md:129-136` records "In the isolated no-network PostgreSQL/Redis
fixture, 28 tests passed" for the tenant-provider-boundary fix. The README's
"250 tests passed" line is dated 2026-10-09 and predates all 2026-10-30/31
changes. There are no CI artifacts, run logs or coverage output in the
worktree, and the commit bodies contain only subjects.

So, by this review's standard:

- **Implemented:** the behaviour above exists in source with unit or
  PostgreSQL-gated tests written alongside it.
- **Verified:** only the 2026-10-29 28-test slice is recorded; the later
  provenance, source-change, budget, receipt, readiness, replacement and
  completeness work is **not** verified by a recorded run in this worktree.
- **Planned:** tenant-wide generation staging, atomic activation, corpus fence
  and generation-qualified cache identity. These remain design documents and
  must not be presented as delivered.

This review did not execute the suite: the session had no AgentHub virtualenv
and did not start Docker or a disposable PostgreSQL/Redis fixture. A green
claim would require that run, not this document.

## Open gaps and residuals

- Existing stored vectors are unlabelled. `specs/knowledge-index-recovery.md`
  forbids inferring their provider/model or certifying them; the inventory
  script can only classify a vector as this exact fallback algorithm, unknown,
  or non-matching.
- Receipt and structural checks are per-query eligibility guards, not a
  generation fence. A partial reindex could still expose mixed documents to a
  query that starts between commits.
- `knowledge-generation-design.md` and `knowledge-index-recovery.md` have no
  code, migration or tests. Activation is explicitly blocked on unresolved
  implementation details in the design itself.
- The tenant query path scans at most 10 001 chunks/documents and rejects
  larger corpora instead of searching a partial one. Vector-index acceleration
  at scale is not established.
- The SDK timeout bounds one transport attempt, not a job deadline; redirects
  and cancellation are unchanged.
- Standalone (`tenant_id is None`) retrieval keeps the legacy paths, including
  the fallback vector and the empty-result score fallback. Tenant paths only.
- Document enqueue can still return "outcome unknown" and leave a pending
  document; automatic reconciliation is not implemented.

## Consequences for NexusCore adoption

1. The work is on AgentHub `origin/main` but absent from the local main
   worktree, so a deployment decision must name the exact revision and build
   a new image from it.
2. A platform deployment needs the `004_merge_ai_resources` migration and a
   reviewed adoption plan; the NexusCore receipts still pin older AgentHub
   images.
3. Any reindex needs an inventory run with
   `scripts/audit_embedding_fallback.py` against the actual tenant data and
   separate approval. No reindex or repair was attempted here.
4. Rebuilding the generation fence is a new AgentHub increment, not a root
   change. It should be specified and reviewed there before NexusCore adopts
   it.

## Recommended next slice

1. Run the candidate suite against a disposable PostgreSQL/pgvector + Redis
   fixture and record test counts, skips and the exact revision in an AgentHub
   receipt. That converts the implemented work into verified work.
2. Only then decide whether tenant-wide generation staging (the draft design)
   is the next AgentHub feature or whether the current per-query guards are
   sufficient for the demo.
3. Keep reindexing, real provider traffic and public deployment behind their
   existing separate approvals.

## What this review did not do

No test execution, no Docker start, no database access, no migration, no
reindex, no AgentHub commit or push. No vendor API was called. The statements
above are source and documentation inspection at `4234a19`.
