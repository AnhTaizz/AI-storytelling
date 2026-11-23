# AI Operations Dashboard Plan

## Phase 6A

`python -m tools.ops_dashboard` starts a standard-library HTTP server on loopback.
A fixed asset allowlist serves an offline HTML, CSS and JavaScript console. The six
GET endpoints expose overview, providers, usage, request history, routing policy
and pipeline metadata. Every JSON response identifies the mock mode and the
snapshot time. The local snapshot is generated once at startup.

`DataSource` provides the snapshot clock, telemetry rows, quota and provider
summaries, routing policy and pipeline runs. `MockDataSource` builds this snapshot
in memory from a seed and clock. Pure view functions aggregate the rows and expose
the same presentation shapes to every request. The HTTP layer validates query
parameters and serializes the results. The browser draws its own SVG charts and
uses hash navigation.

The telemetry contract comes from Phase 5 commit `4689167` on
`feat/free-llm-phase5-unified-router`. The sources are
`docs/engineering/LLM_TELEMETRY_SCHEMA.md` and `tools/llm_infra/telemetry.py`.
`tools/ops_dashboard/contract.py` is the dashboard's field map, including the
columns the browser reads. The mock routing policy follows
`configs/llm_routing/policy_v1.yaml` and `tools/llm_infra/routing_policy.py` at the
same commit. Its displayed SHA-256 fingerprints the mock JSON snapshot. Phase 5
fingerprints the exact policy file bytes.

Request totals count candidate rows, including skips. The success rate uses
dispatched candidates. Percentiles use nearest rank over available latency values.
Token totals add input and output and present reasoning separately when available,
since some providers include reasoning in output. Reported and estimated totals
remain separate. An unknown count stays null, and the requests chart counts the
rows with unknown token counts. Some estimates include an output reserve, including
preflight skips. The overview's zero cost is the mock free-tier assumption.
Phase 5 leaves estimated costs null and reports a cost only when the provider
supplies one. Provider quotas are independent synthetic snapshots based on the
[repository's free routing plan](FREE_LLM_ROUTING_PLAN.md).

## Phase 6B

Implement a read-only `DataSource` adapter over owner-selected paths:

1. Open telemetry SQLite using a resolved local `file:...?mode=ro` URI and
   `sqlite3.connect(..., uri=True)`. Check `PRAGMA user_version`, select only the
   Phase 5 columns, and use bounded, parameterized queries over the timestamp index.
   Preserve `reported`, `estimated`, `unknown` and null values through the API.
2. Open quota-state SQLite separately with `mode=ro`. Read public counters,
   scope categories, active cooldowns and the Cloudflare Neuron ledger. Calculate
   expiry in the adapter. Avoid quota-router helpers that create, migrate or purge
   the store. Keep provider counters and local ledger estimates labeled by source.
3. Read pipeline and season manifests from explicitly configured run roots.
   Allowlist run IDs, stages, statuses and resume times. Derive hints from fixed
   templates. Exclude prompts, generated artifacts, arbitrary paths and raw errors.
4. Read and validate the configured routing policy to display stage assignments
   and its file digest. Keep the dashboard independent of clients that resolve
   credentials or make provider calls. Show the connected read-only data mode
   clearly in the banner.

## Risks

- SQLite stores can be busy, absent or on an unsupported schema. Keep read
  transactions short and return a clear unavailable state. For a live WAL
  database, require readable, existing sidecars or an owner-provided snapshot so
  read-only dashboard startup does not create sidecar files.
- Candidate IDs may recur across resumes and candidate records can outnumber
  logical calls. Preserve Phase 5 row semantics when charting and filtering.
- Limits apply on different clocks and scopes. Keep quota resets, usage
  provenance and telemetry time buckets explicit. Clock differences can affect
  displayed relative times.
- Manifests and SQLite text are local inputs that can contain private data.
  Validate paths and text fields, suppress raw identifiers and provider errors,
  and review browser-origin protections for the connected local server.

## Proposed decision DEC-0xx (owner to record in DECISIONS.md at merge)

Adopt a loopback-only dashboard with a read-only source interface. Accept Phase 6A
with mock data and an offline interface. Treat the Phase 5 telemetry schema as
the compatibility boundary for Phase 6B and keep that adapter read-only across
telemetry, quota state, policy and run manifests. Provider calls, quota changes
and run triggers remain outside dashboard scope.
