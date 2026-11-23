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

Start with `GROQ_API_KEY_1`. Process settings override dotenv, and the lowest numbered copy of each key wins. All unlabeled keys share the `org` scope. Use `GROQ_ORG_LABEL_<n>` only for a different organization you control. Groq applies Free limits per organization. [Groq console limits](https://console.groq.com/settings/limits)

The standing declaration treats undeclared keys as Free plan keys. Set `GROQ_KEYS_FREE_PLAN_CONFIRMED=false` to require explicit declarations. `GROQ_ORG_PLAN_<n>=FREE_PLAN_CONFIRMED` opts in a key, while `UNVERIFIED` and `PAID_PLAN` exclude it. Effective plans must agree within every scope, including `org`. An API key cannot establish the plan, and the Developer plan charges per token. The application requires the shared free-only settings and a zero paid spending limit.

The production model snapshot reviewed on 2026-11-23 allows `openai/gpt-oss-120b` and `openai/gpt-oss-20b`, in that default order. The two Llama IDs were removed after their 2026-08-16 shutdown. Set `GROQ_MODEL` to select a chain and `GROQ_FREE_MODELS` to narrow the allowlist. The offline `check_config` reports Groq eligibility, models, and active cooldowns. [Production model snapshot](../../tools/llm_infra/groq_free_models_v1.py) · [Groq deprecations](https://console.groq.com/docs/deprecations)

The message takes precedence over the headers when identifying the limit. The latest applicable time from Retry-After, the message, and a matching reset header wins. [Groq rate limits](https://console.groq.com/docs/rate-limits)

| Evidence | Earliest next attempt |
| --- | --- |
| Requests per day (RPD) in the message or zero remaining requests | Latest retry delay or requests reset, otherwise 1 hour |
| Tokens per day (TPD) in the message | Retry delay, otherwise 1 hour |
| Tokens per minute (TPM) in the message or zero remaining tokens | Latest retry delay or tokens reset, otherwise 60 seconds |
| Requests per minute (RPM) in the message | Retry delay, otherwise 60 seconds |
| Unknown 429 | Retry delay, otherwise 60, 120, 240, 480, then 900 seconds on consecutive failures |

The router picks the first unblocked, enabled key in configuration order. Later keys in the same scope are used only after authentication failures disable earlier keys for the life of the router. Blocks are capped at 26 hours and persist by provider, model, and organization scope in the shared SQLite file. A successful response clears the unknown streak. A success with zero remaining requests also records an RPD cooldown. The router pauses after three quota 429s per call by default. If every scope is blocked, it can wait once within 60 seconds. Otherwise it reports the earliest resume time.

HTTP 413 and HTTP 400 or 429 with a “Request too large” message return `REQUEST_TOO_LARGE` immediately without retrying or recording a block. The Free limit of 8,000 tokens per minute includes reasoning tokens and is too low for long pipeline prompts. Pipeline integration is deferred until the M9 gate sample ends and is planned for Phase 5.

Run `python -m tools.llm_infra.groq_smoke` to inspect settings and active blocks offline. With the owner's `--live` opt-in, the first eligible key sends one synthetic JSON-mode request using `openai/gpt-oss-20b` or an allowlisted `--model`. It has a 32-token output cap, a 20-second timeout, and no retry, fallback, or quota-state update. [Groq Free setup guide](../guides/GROQ_FREE_SETUP.md)

## Phase 3 · OpenRouter

Start with `OPENROUTER_API_KEY_1`. Process settings override dotenv, and the lowest numbered copy of each key wins. All unlabeled keys share the `openrouter_account` scope. Use `OPENROUTER_ACCOUNT_LABEL_<n>` only for a key known to belong to a different account you control. OpenRouter applies free-model limits account-wide and governs capacity globally. The limits are 20 requests per minute and 50 per UTC day, rising to 1,000 per day after the account has bought at least 10 credits. [OpenRouter limits](https://openrouter.ai/docs/api/reference/limits)

The rule reviewed on 2026-11-23 permits lower-case model IDs with a terminal `:free` and the default `openrouter/free` router. Set `OPENROUTER_MODEL` to select a chain and `OPENROUTER_FREE_MODELS` to narrow the rule. The transport rechecks the model and sends a single `model` in each request, which excludes paid model fallback through a `models` array. After reading the response, the transport raises `PAID_USAGE_DETECTED` if the reported cost is positive or the reported model violates the free rule. A payment refusal or detected charge stops the call immediately and leaves quota state untouched. The caller can report these errors to the owner. Requests omit attribution headers. An unset `OPENROUTER_DATA_COLLECTION` leaves privacy selection to the account settings. [Free variant rule](../../tools/llm_infra/openrouter_free_models_v1.py) · [Free models router](https://openrouter.ai/openrouter/free)

The router tries scopes in order of their first key and uses the lowest-numbered enabled key within each scope. An authentication failure disables that slot for the life of the router. A 429 cools down the entire account scope across models. The shared SQLite ledger stores these rows under provider `openrouter` with `*` in the model column. Success clears the unknown streak. The router pauses after two 429s by default and can wait inline once within 60 seconds when every usable scope is blocked.

| Evidence | Earliest next attempt |
| --- | --- |
| OpenRouter daily limit (RPD) of 50 or 1,000, or a daily message | Future millisecond-epoch reset, otherwise next 00:00 UTC |
| OpenRouter minute limit (RPM) of 20, or a per-minute message | Future reset, otherwise Retry-After or 60 seconds |
| Upstream provider 429 or unknown 429 | Retry-After or 60, 120, 240, 480, then 900 seconds on consecutive failures |

Retry-After can extend a reset-based cooldown, and every cooldown is capped at 26 hours. A 429 with `metadata.provider_code` uses the upstream capacity rule even if it contains quota-like evidence. [OpenRouter rate-limit response format](https://openrouter.ai/docs/api/reference/limits#handling-429-errors)

Run `python -m tools.llm_infra.openrouter_smoke` or `python -m tools.llm_infra.check_config` to inspect settings and active blocks offline. The owner's `--live` smoke opt-in reads public counts from `GET /key` and sends one synthetic JSON-mode chat using the first configured model or a free `--model`. Both calls use a 20-second timeout and the chat has a 512-token output cap, which leaves room for reasoning tokens. Requests send a generic `User-Agent`, because CDN edges can refuse the urllib default; a 403 without an API error body is reported as `EDGE_BLOCKED` and disables no key. The smoke test performs no retries or quota-state updates. Pipeline integration is planned for Phase 5. [OpenRouter Free setup guide](../guides/OPENROUTER_FREE_SETUP.md)

## Routing phases

| Phase | Work |
| --- | --- |
| 2 · Groq | Done. Free plan declarations, a production model allowlist, and organization quota handling. |
| 3 · OpenRouter | Done. Free model routing, post-response cost checks, and account-wide cooldowns. |
| 4 · Cloudflare Workers AI | Use a free-plan token with account-scoped permissions. Budget and track Neurons. |
| 5 · Unified routing | Route across eligible providers and benchmark script quality under the existing Script Quality Contract, preserving the frozen review criteria. |
