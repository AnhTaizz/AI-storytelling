# LLM telemetry schema v1

The pipeline writes to `.local/llm_telemetry.sqlite3` by default. Set `LLM_TELEMETRY_PATH` to choose another file. Tests may use `:memory:`. The database uses `PRAGMA user_version = 1`. The `llm_requests` table has indexes on `timestamp_utc` and `(provider, model_requested)`.

| Columns | Meaning |
| --- | --- |
| `id`, `timestamp_utc` | SQLite integer row ID and ISO 8601 UTC timestamp with millisecond precision. |
| `run_id`, `stage`, `request_id` | Episode or run directory name, pipeline stage and logical call ID. IDs can recur across resumes. |
| `provider`, `model_requested`, `model_reported` | Provider slug, requested model, and response model or version when available. |
| `outcome`, `error_code` | `SUCCESS`, `FAILED` or `SKIPPED`, with an error or skip code when applicable. Success means the provider returned a response. Pipeline validation runs separately. |
| `input_tokens`, `output_tokens`, `reasoning_tokens`, `tokens_source` | Token counts and provenance. `reported` uses the available provider counters with absent fields left null. `estimated` uses rounded-up UTF-8 bytes divided by three and the policy's output reserve. Estimated output is a budget. `unknown` leaves all counts null. |
| `latency_ms`, `quota_scope`, `quota_remaining` | Router latency when available, scope type, and a JSON object of allowlisted public rate limit counters observed on the response. Empty objects indicate no available counters. |
| `cost_reported`, `cost_estimated`, `cost_source` | Provider-reported USD cost where available, reserved estimate field, and provenance. This version emits `reported` or `unknown` and leaves `cost_estimated` null. Cloudflare's local Neuron ledger remains separate. |
| `routing_policy_sha256`, `skip_reasons` | SHA-256 of the exact AUTO policy file bytes, and a JSON array of routing reason codes paired with provider slugs. Named providers leave the hash null. |

AUTO and named provider clients emit one row per considered candidate. A provider router may make several bounded transport attempts for that row. The legacy Gemini chain emits one row per logical completion. Locked runs keep the legacy output format and bypass Phase 5 telemetry.

The writer accepts a fixed set of metadata fields and numeric public counters. It filters values against the configured secrets of all four providers, including Workers account IDs. Prompts, response text, credential values, account IDs, Authorization headers, and provider error messages are excluded. SQLite errors only produce a generic warning. The dashboard can read records from a separate connection.
