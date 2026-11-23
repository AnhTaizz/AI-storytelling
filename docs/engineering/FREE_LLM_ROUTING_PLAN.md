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

## Phase 2 · Groq

Add numbered `GROQ_API_KEY_<n>` settings to use Groq. Process settings override dotenv, and the lowest numbered copy of each key wins. Unlabeled keys get their own `groq_slot_<n>` scopes. Set the same `GROQ_ORG_LABEL_<n>` for keys from one organization to share cooldowns. Groq applies free limits per organization. [Groq console limits](https://console.groq.com/settings/limits)

The standing declaration treats undeclared keys as Free plan keys. Set `GROQ_KEYS_FREE_PLAN_CONFIRMED=false` to require explicit declarations. `GROQ_ORG_PLAN_<n>=FREE_PLAN_CONFIRMED` opts in a key, while `UNVERIFIED` and `PAID_PLAN` exclude it. Declarations must agree within a shared label. An API key cannot establish the plan, and the Developer plan charges per token. The application requires the shared free-only settings and a zero paid spending limit.

The production model snapshot records the Groq model list as reviewed on 2026-11-23. The default chain is `openai/gpt-oss-120b`, then `llama-3.3-70b-versatile`. Set `GROQ_MODEL` to select a chain and `GROQ_FREE_MODELS` to narrow the allowlist. The offline `check_config` reports Groq eligibility, models, and active cooldowns. [Production model snapshot](../../tools/llm_infra/groq_free_models_v1.py) · [Groq models](https://console.groq.com/docs/models)

The message takes precedence over the headers when identifying the limit. The latest applicable time from Retry-After, the message, and a matching reset header wins. [Groq rate limits](https://console.groq.com/docs/rate-limits)

| Evidence | Earliest next attempt |
| --- | --- |
| Requests per day (RPD) in the message or zero remaining requests | Latest retry delay or requests reset, otherwise 1 hour |
| Tokens per day (TPD) in the message | Retry delay, otherwise 1 hour |
| Tokens per minute (TPM) in the message or zero remaining tokens | Latest retry delay or tokens reset, otherwise 60 seconds |
| Requests per minute (RPM) in the message | Retry delay, otherwise 60 seconds |
| Unknown 429 | Retry delay, otherwise 60, 120, 240, 480, then 900 seconds on consecutive failures |

Blocks are capped at 26 hours and persist by provider, model, and organization scope in the shared SQLite file. A successful response clears the unknown streak. A success with zero remaining requests also records an RPD cooldown. The router pauses after three 429 responses per call by default. If every scope is blocked, it can wait once within 60 seconds, otherwise it reports the earliest resume time. Authentication failures disable individual slots for the life of the router.

The owner can run `python -m tools.llm_infra.groq_smoke --env-file .env` for a single small JSON-mode request. The smoke command selects the first model in the chain unless given `--model`. The pipeline integration is planned for Phase 5.

## Routing phases

| Phase | Work |
| --- | --- |
| 2 · Groq | Done. Free plan declarations, a production model allowlist, and organization quota handling. |
| 3 · OpenRouter | Allow only `:free` models. Disable paid fallback and auto top-up. |
| 4 · Cloudflare Workers AI | Use a free-plan token with account-scoped permissions. Budget and track Neurons. |
| 5 · Unified routing | Route across eligible providers and benchmark script quality under the existing Script Quality Contract, preserving the frozen review criteria. |
