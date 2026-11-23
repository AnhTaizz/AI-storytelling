# Free LLM routing

## Phase 1 · Gemini

The pipeline CLI reads dotenv and process settings, with the environment taking precedence. After deduplication (lowest slot wins), a single credential may omit its project label. Multiple credentials require a label on every slot. Keys for the same Google Cloud project share a label and a project–model quota scope.

Only projects explicitly attested as free are eligible. A blank slot inherits the status declared for its project. Conflicting declarations block configuration. The bulk confirmation applies only to one project scope and explicit project status takes precedence. Every model in the selected chain must appear in the owner's required `GEMINI_FREE_MODELS` allowlist. Offline `check_config` reports the application policy, per-project attestation sources and active blocks. The owner verifies billing with Google.

`gemini_router` leases slots from the M4 pool. It excludes blocked projects for the requested model, disables a slot after an authentication failure, and bounds transport retries. `quota_policy` reads QuotaFailure and RetryInfo details, then checks legacy cause markers and Retry-After. If multiple retry delays apply, the later one wins.

| Evidence | Earliest next attempt |
| --- | --- |
| Requests per day | Next 08:00 UTC or provider retry time, whichever is later |
| Requests or tokens per minute | Provider retry time, otherwise 60 seconds |
| Unknown 429 with retry delay | Provider retry time |
| Unknown 429 without delay | 60, 120, 240, 480, then 900 seconds on consecutive failures |

Daily reset uses fixed UTC−08:00. This allows an extra hour during daylight saving time. Each block is capped at 26 hours. Success resets the scope's unknown streak. `quota_state` stores provider, model, project alias, expiry, fixed reason, streak and timestamps in SQLite. The primary key is (provider, model, project alias). The CLI defaults to `.local/llm_quota_state.sqlite3`; `LLM_QUOTA_STATE_PATH` overrides it. Library clients default to memory. Reopening the file purges expired rows.

A 429 moves immediately to another eligible group. When all usable groups are blocked, the router can wait once within the 60-second budget. Otherwise it raises `QUOTA_EXHAUSTED` with the earliest UTC resume time. The client tries the next confirmed model. If the chain exhausts its quota, the pipeline records `FAILED` and the season reports `PAUSED_QUOTA`. Rerunning in the same output directory reuses completed stages. Authentication exhaustion reports `NO_USABLE_CREDENTIAL`.

## Planned phases

| Phase | Proposed work |
| --- | --- |
| 2 · Groq | Add free-project verification, model allowances and provider-specific rate-limit handling. |
| 3 · OpenRouter | Allow only `:free` models. Disable paid fallback and auto top-up. |
| 4 · Cloudflare Workers AI | Use a free-plan token with account-scoped permissions. Budget and track Neurons. |
| 5 · Unified routing | Route across eligible providers and benchmark script quality under the existing Script Quality Contract, preserving the frozen review criteria. |
