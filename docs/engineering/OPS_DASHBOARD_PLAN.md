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

## Phase 6B — implemented, pending owner review

The dashboard CLI defaults to live mode. `--mock` keeps the Phase 6A snapshot.
The read-only adapter uses these sources and bounds:

1. **Telemetry SQLite v1** uses indexed UTC windows with parameterized queries.
   Overview and usage aggregate up to 10,000 recent candidates per window. History
   covers seven days with at most 500 rows per page, using timestamp and row ID
   order. Provider counters are timestamped observations from the recent window.
2. **Quota SQLite** supplies up to 500 active blocks and UTC-day Cloudflare Neuron
   estimates. Scope references are opaque and local to the snapshot. Both SQLite
   connections use `mode=ro` and `PRAGMA query_only=ON`. A missing file, unsupported
   schema, busy store or WAL file produces a source-specific message.
3. **Pipeline and season metadata** supply at most 50 entries by manifest mtime,
   alongside allowlisted call-log timings for ordinary runs. Reads cap each manifest
   at 4 MiB and each call log at 8 MiB. A gate-locked season supplies only its status
   and the fixed lock label. Its episode manifests and artifacts are excluded.
4. **Routing policy** reuses the Phase 5 validator and SHA-256 of the file bytes.
   **Static model capabilities and limits** include the original snapshot source and
   verification date. **Configuration counts** reuse offline environment settings
   inspectors. The dashboard does not read dotenv or dispatch calls.
5. **API and UI** preserve reported, estimated, unknown and static provenance. An
   allowlist and final secret/path scrubber protect all API responses. Overview,
   Providers and Pipeline refresh every 30 seconds while the tab is visible and
   support a manual refresh.

## Risks

- SQLite stores can be busy, absent or on an unsupported schema. Read transactions
  stay short and report unavailability. Use an owner-provided rollback-journal
  snapshot for WAL data to avoid SQLite sidecar changes.
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
