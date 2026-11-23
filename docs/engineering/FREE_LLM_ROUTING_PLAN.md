# Free LLM routing

## Phase 1 · Gemini

The pipeline CLI accepts numbered Gemini keys alone. Process settings override dotenv. The loader keeps the lowest numbered copy of each key and assigns unlabeled keys separate quota scopes. An optional shared label groups related keys. DEC-036 records the owner's standing free-tier declaration. Explicit billing exclusions still apply. The default model chain and free-tier allowlist come from [the reviewed pricing snapshot](../../tools/llm_infra/gemini_free_models_v1.py). A local override can only narrow the list. The offline `check_config` reports billing assumptions, model selection and active blocks. The owner checks billing in Google Cloud.

`gemini_router` leases slots from the M4 pool. It excludes blocked projects for the requested model, disables a slot after an authentication failure, and bounds transport retries. `quota_policy` reads QuotaFailure and RetryInfo details, then checks legacy cause markers and Retry-After. If multiple retry delays apply, the later one wins.

| Evidence | Earliest next attempt |
| --- | --- |
| Requests per day | Next 08:00 UTC or provider retry time, whichever is later |
| Requests or tokens per minute | Provider retry time, otherwise 60 seconds |
| Unknown 429 with retry delay | Provider retry time |
| Unknown 429 without delay | 60, 120, 240, 480, then 900 seconds on consecutive failures |

Daily reset uses fixed UTC−08:00. This allows an extra hour during daylight saving time. Each block is capped at 26 hours. Success resets the scope's unknown streak. `quota_state` stores provider, model, project alias, expiry, fixed reason, streak and timestamps in SQLite. The primary key is (provider, model, project alias). The CLI defaults to `.local/llm_quota_state.sqlite3`; `LLM_QUOTA_STATE_PATH` overrides it. Library clients default to memory. Reopening the file purges expired rows.

A 429 moves to another eligible group until the router reaches its per-call 429 limit (default three). At that limit it pauses with the earliest expiry among the refused scopes and leaves untried scopes available. When all usable groups are blocked, the router can wait once within the 60-second budget. Otherwise it raises `QUOTA_EXHAUSTED` with the earliest UTC resume time. The client tries the next confirmed model. If the chain exhausts its quota, the pipeline records `FAILED` and the season reports `PAUSED_QUOTA`. Rerunning in the same output directory reuses completed stages. Authentication exhaustion reports `NO_USABLE_CREDENTIAL`.

## Planned phases

| Phase | Proposed work |
| --- | --- |
| 2 · Groq | Add free-project verification, model allowances and provider-specific rate-limit handling. |
| 3 · OpenRouter | Allow only `:free` models. Disable paid fallback and auto top-up. |
| 4 · Cloudflare Workers AI | Use a free-plan token with account-scoped permissions. Budget and track Neurons. |
| 5 · Unified routing | Route across eligible providers and benchmark script quality under the existing Script Quality Contract, preserving the frozen review criteria. |
