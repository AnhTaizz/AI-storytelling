# M4 Gemini Transport Resilience V1.1 Remediation

Status: **RUNTIME CORRECT / PROVIDER GATE UNHEALTHY**

Task: `M4-04B1R-GEMINI-TRANSPORT-FAILURE-DIAGNOSIS-REMEDIATION-AND-REGATE`

## Historical result and scope

`GEMINI_TRANSPORT_RESILIENCE_V1` remains an immutable failed historical gate. Its
12-request live run produced 7 successes, 5 failures, 4 rate-limit events and 7
server-failure events. This remediation does not rewrite that result as a pass.

V1.1 is transport-only. It used synthetic status prompts and did not open development
story data, holdout input, or holdout gold. It selected no extraction model, locked no
extractor, and produced no holdout prediction. Transport-smoke model choice is separate
from the future M4-04B2 extraction-model decision.

## Failed-run diagnosis

The V1 private result retained request summaries and aggregate counters, but not the HTTP
code, structured provider reason, `Retry-After`, timestamp, local wait, latency, or circuit
transition for each attempt. A safe 18-attempt reconstruction therefore marks those
fields unknown instead of inferring them. Eight failed rows cannot be mapped individually,
although the aggregate proves they contain two 429 and six 5xx events in addition to the
known terminal failures.

Consequently, the historical 429 classification is `429_CAUSE_NOT_EXPOSED`, and no honest
predominant 500/502/503/504 code or temporal cluster can be recovered. All historical
retries used the same single unknown project group. The failed gate remains valid evidence
of provider 429/5xx behavior, but it is not evidence for a more specific quota cause.

The code audit found four justified V1 remediation points:

- Rate buckets were project-group-wide and could not represent model-specific limits.
- The 429 non-health path called the generic success reset and erased an earlier 5xx streak.
- 5xx backoff ignored provider `Retry-After` and did not use bounded jitter.
- Diagnostic records lacked message-free fingerprints and complete attempt timelines.

V1 already placed RPM/TPM reservation in its provider-attempt loop. V1.1 makes that
contract explicit and testable with separate reservation counters.

## Configuration and project labels

`.env.example` again contains blank numbered API-key/project-label pairs and no hard-coded
model. The runtime accepts arbitrary positive slot number `N`, not just 1 through 3.

Project labels are private local aliases:

```text
same Google project
-> same GEMINI_PROJECT_LABEL_N

different Google projects
-> different labels
```

A label does not need to equal the real Google project name or id. If independence is not
known, the label stays blank. Multiple unknown keys are never counted as independent quota
groups. At execution time all seven configured slots were unlabeled, so discovery,
precheck and regate used only `gemini_slot_1`; live multi-project failover is
`MULTI_PROJECT_FAILOVER_NOT_TESTABLE`.

## Model-aware limiter and configured limits

V1.1 keys rate and circuit state by `(project_group, model)`. Every real provider attempt,
including retries and failovers, receives a fresh RPM event and a fresh TPM reservation.
Successful usage metadata corrects that attempt's token reservation. A reservation is
removed only when circuit/admission logic prevents any provider attempt.

`GEMINI_DEFAULT_RPM` and `GEMINI_DEFAULT_TPM` can supply private local defaults. A private
JSON file selected by `GEMINI_PROJECT_MODEL_LIMITS_FILE` can override limits by local
project alias and model. The execution used research defaults RPM 10 and TPM 3000 with no
override. These values are conservative local controls, not a claim about Google's quota
for the user's account, project, tier, or model.

## Adaptive 429 protection

A real 429 updates only its `(project_group, model)` adaptive state:

- Provider `Retry-After` takes precedence; otherwise a five-second cooldown is used.
- Effective local RPM and TPM factors are halved down to a floor of 0.25.
- Two successful calls permit a 0.10 recovery step, capped at the configured limit.
- User configuration is never mutated.
- A second key in the same project shares the bucket and cannot bypass the cooldown.
- A healthy explicitly independent project is preferred on a later bounded attempt.

The provider error is reduced to structured metadata and a fixed cause vocabulary. Raw
messages are never persisted.

## 5xx backoff and retry/failover order

The global provider-attempt cap remains three. Supported 5xx `Retry-After` is honored
first. Without it, retries use bounded exponential backoff from one second, capped at 30
seconds, with uniform ±20% jitter. RNG is injectable so fault tests are deterministic.

On a later attempt, the scheduler first seeks another healthy explicitly labeled project
group. It falls back to the prior group only when no independent group is available. Slot,
project-group, transport-retry and total-attempt counters remain separate. Credential
rotation within one project is never reported as quota failover.

There is no semantic regeneration, structural repair, silent model switch, provider
fallback, or local-model fallback.

## Circuit semantics

`GEMINI_PROJECT_MODEL_CIRCUIT_BREAKER_V1_1` retains `CLOSED`, `OPEN`, and `HALF_OPEN`, with
three transient failures, a 30-second open cooldown, and one half-open probe by default.

A 429 is not a transport-health failure. In `CLOSED`, it preserves the prior 5xx failure
streak. Thus `503, 503, 429, 503` opens the circuit at the final 503. A 429 during a
half-open probe is inconclusive: it reopens for a cooldown without incrementing the
transport-health streak. Only provider success resets the streak and closes the circuit.

## Sanitized diagnostics

V1.1 records message-free fingerprints such as `SERVER_FAILURE:503`,
`RATE_LIMIT:RESOURCE_EXHAUSTED`, and `AUTH_FAILURE:401`. Each attempt records only semantic
request id, attempt number, relative time, slot id, local project alias, model, classified
result, HTTP family/code, structured reason, `Retry-After`, provider latency, local waits,
and circuit/adaptive state. API keys, key fragments, key hashes, raw provider messages,
and authorization headers are excluded.

## Offline verification

All 35 historical V1 fault tests and 20 new V1.1 remediation tests passed. New coverage
proves fresh RPM/TPM reservation per retry/failover, model-specific buckets, adaptive 429
throttling and recovery, both `Retry-After` paths, bounded injectable jitter, mixed
503/429 circuit semantics, same-project non-bypass, explicit-project failover, conservative
unknown keys, safe fingerprints, and the hard attempt cap.

The V1.1 500-request offline simulation passed with 500 successes, 500 provider attempts,
500 RPM reservations and 500 TPM reservations. It had no deadlock or counter corruption,
kept active calls at two and queue depth within 16, and scheduled exactly 250 requests to
each of two explicitly independent fake projects. It made no live API call.

The complete deterministic suites passed: story extraction 207, story ingestion 79,
canonical story 99, script quality 64, and story benchmark 298. Benchmark tests were run
with Hugging Face/Transformers offline against the existing local cache.

## Transport-smoke model

Provider discovery listed six accessible non-preview stable Flash candidates. The locked
rule selected the newest non-Lite candidate, `gemini-3.8-flash`; successful responses also
reported `gemini-3.8-flash`. This is only the transport-smoke identity. The extraction
model remains `NOT SELECTED`.

## Four-request precheck

The sequential precheck reached four successes and zero request failures in eight provider
attempts. It observed four `503 UNAVAILABLE` events, all recovered by bounded retry. RPM
and TPM reservation counts were both eight, maximum active calls was one, and no uncaught
exception occurred. Request latency was 14,747.914 ms p50 and 36,137.536 ms p95; provider
latency was 8,261.580 ms p50 and 14,902.797 ms p95. The preregistered stop condition of at
least two failed semantic requests was not triggered.

## Locked regate and result

Before the first regate request, `M4_04B1R_RESILIENCE_REGATE_PROTOCOL_V1` was locked with
SHA-256 `2ea4d8d5c5df0692d261de3b21798a6e836ab99c4a51857c900935a1ab45bc33`.
It bound the base, V1 evidence, V1.1 implementation hashes, credential policy, model,
limits, adaptive/retry/circuit policies, prompt hash, 12-request count, concurrency two,
output cap 128, attempt cap three, and success threshold 11/12. It was not edited after
results.

The one permitted regate reached all 12 bounded terminal states. It made 14 provider
attempts and produced four successes and eight failures. Provider attempts observed eight
`503 UNAVAILABLE` failures and two `429 RESOURCE_EXHAUSTED` failures. Structured quota
metadata supported `MODEL_SPECIFIC_QUOTA` for the new 429 events; neither supplied
`Retry-After`. The circuit opened twice and safely blocked five semantic requests.

Runtime invariants passed: zero uncaught exceptions, maximum three attempts per request,
14 RPM and 14 TPM reservations for 14 provider attempts, maximum active calls two, queue
depth two, no uncontrolled retry, and no model/provider/local fallback. Successful calls
reported the requested model.

All-terminal request latency was 18,077.721 ms p50, 64,163.940 ms p95, and 105,567.706 ms
maximum. Provider-attempt latency was 5,719.913 ms p50 and 16,493.314 ms p95. Admission
queue wait was 0 ms p50 and 22,746.019 ms p95.

The 11/12 threshold was not met, so the provider reliability gate remains unhealthy. The
honest status is `M4_04B1R_RUNTIME_CORRECT_PROVIDER_GATE_UNHEALTHY`. Do not start M4-04B2,
open story packages, select an extraction baseline, or run holdout predictions pending
Orchestrator review.
