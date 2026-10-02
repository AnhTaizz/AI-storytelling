# M4 Gemini Transport Resilience V1

Status: **OFFLINE PASS / LIVE GATE FAIL**

Task: `M4-04B1-GEMINI-TRANSPORT-RESILIENCE-AND-LOAD-SAFETY-GATE`

## Scope

`GEMINI_TRANSPORT_RESILIENCE_V1` hardens the Gemini transport before any extraction
quality work. It queues requests, bounds concurrency, applies local project-group RPM
and TPM budgets, separates retry and failover counters, enforces a global attempt cap,
tracks project circuit state, and publishes only sanitized health metrics.

This gate used synthetic prompts only. It did not open development extraction data,
holdout input, or holdout gold. It selected no extraction baseline and performed no
structural repair or semantic regeneration.

**This is not a production-scale throughput benchmark.** Twelve tiny live requests
cannot establish production capacity, latency, cost, or availability.

## Architecture and load safety

The resilience layer sits above the single-attempt official `google-genai` adapter and
below future extraction orchestration:

```text
semantic request
  -> bounded FIFO admission / concurrency controller
  -> project-group RPM and TPM reservation
  -> project circuit breaker
  -> deterministic credential/project scheduler
  -> one Gemini provider attempt
  -> usage correction, health metrics, bounded retry/failover
```

The research defaults are concurrency 2, a bounded queue, local project RPM 10 and TPM
3000, and finite queue/rate/scheduler waits. Queue saturation raises a sanitized
`QUEUE_REJECTED` terminal error. No request may bypass admission.

Input tokens are estimated locally as `ceil(UTF-8 bytes / 3)`. The reservation includes
the requested maximum output tokens and is corrected after success using provider usage
metadata. This avoids one remote `countTokens` call per request, but it is an approximate
multilingual estimator and not a billing tokenizer.

## Attempt and failover contract

One semantic request has a hard maximum of three provider attempts:

```yaml
max_total_provider_attempts: 3
max_transport_retries: 2
max_credential_failovers: 2
max_project_group_failovers: 2
```

These budgets do not add together; the global cap always wins. Transport retries,
credential failovers, project-group failovers, and total attempts have separate counters.
Structural repair remains zero and outside this transport layer.

There is no Gemini-model switch, provider switch, or local-model fallback. Invalid JSON,
bad extraction quality, hallucination, or semantic validation failure never triggers a
transport retry.

## Error classification and handling

Provider classification is centralized in `gemini_errors_v1.py`: `SUCCESS`,
`RATE_LIMIT`, `AUTH_FAILURE`, `SERVER_FAILURE`, `TIMEOUT`, `NETWORK_FAILURE`,
`PROVIDER_FAILURE`, `LOCAL_RATE_LIMIT_WAIT`, `QUEUE_REJECTED`, and `CIRCUIT_OPEN`.
Raw provider messages never become public errors.

- A 429 respects `Retry-After` when supplied, cools the project group, and does not count
  as a transport-health circuit failure.
- A 401/403 or structured invalid-key response disables only the affected slot.
- A 5xx, timeout, or network failure uses bounded exponential backoff and contributes to
  the project transport-failure streak.
- Exhausted slots, budgets, queue, or wait bounds fail closed.

## Project circuit breaker

`GEMINI_PROJECT_CIRCUIT_BREAKER_V1` is maintained per project group. Defaults are three
consecutive transport-health failures, 30 seconds OPEN cooldown, and one HALF_OPEN probe.
An OPEN circuit blocks provider calls. After cooldown exactly one probe may enter. Probe
success closes and resets the circuit; a transient failure reopens it. A 429 uses the
rate-limit cooldown path instead of being double-counted as circuit failure.

## Credential-label safety

Seven credential slots were configured without project labels. The gate therefore did
not claim seven independent quotas and did not fan out. The live smoke selected one
unknown slot conservatively. Offline tests used fake labels to verify same-project shared
RPM/TPM/cooldown and explicitly independent project failover.

## Sanitized health and metrics

The runtime reports semantic requests, provider attempts, successes/failures, classified
provider events, retry/failover counters, circuit transitions, queue distributions,
provider latency distributions, estimated/actual tokens, and local RPM/TPM waits. Health
snapshots contain group labels, state, active/queued counts, available-slot counts,
cooldowns, and recent request counts. They contain no API key, key hash, prefix, or suffix.

## Offline fault injection

Thirty-five deterministic resilience tests passed. The matrix includes 200, 400 invalid
key, 401/403, 429 and `Retry-After`, repeated 429, 500/502/503/504, timeout, connection
reset, network error, slow success, disabled/cooling pools, independent failover, shared
project limits, RPM/TPM waits, queue saturation, every circuit transition, hard attempt
cap, separated budgets, unknown-label restriction, no semantic regeneration, and secret
leakage surfaces.

A 500-semantic-request concurrent offline simulation passed with fake time/provider:
500 successes, 500 provider attempts, no deadlock or counter corruption, maximum active
calls 2, bounded queue, maximum attempt count 1, and fair 250/250 scheduling across two
fake independent project groups. Live API calls during offline verification: zero.

## Preregistered live smoke

Before live results, the private protocol was locked with SHA-256
`627a26c072bf6057ef8604a3f621af255b616e623b71cb4143314f824f220316`.
It bound the implementation hashes, configured policies, synthetic prompt hash, transport
smoke model rule, 12-request count, concurrency 2, output cap 128, theoretical maximum 36
provider calls, and success threshold 11/12.

The configured `gemini-3.7-flash` was used only as `TRANSPORT_SMOKE_MODEL`; this does not
select or lock it as the extraction baseline. No model discovery was performed.

## Live result

All 12 semantic requests reached a bounded terminal state. The run made 18 provider
attempts: 7 requests succeeded and 5 failed cleanly. Provider-attempt observations were
4 rate-limit events and 7 server failures, with no auth disable, timeout, network failure,
uncontrolled retry, secret leak, or model fallback. The circuit opened once; two semantic
requests were blocked without provider calls. Maximum provider attempts for one request
was 3 and maximum active calls was 2.

Successful-request latency was 5,510.593 ms minimum, 17,967.205 ms p50, 28,130.097 ms p95,
and 28,246.549 ms maximum. Provider-attempt latency was 7,961.036 ms p50 and 22,252.346 ms
p95. Queue wait was 4,132.332 ms p50 and 28,034.949 ms p95. These observations describe
only this small smoke run.

The required success threshold was 11/12. Actual success was 7/12, so the live gate
failed. The infrastructure and offline contract remain valid, but extraction quality
work is prohibited pending Orchestrator review and provider/live-environment remediation.
The live smoke was not rerun or tuned after observing results.

## Remaining production gaps

- No production-scale sustained-load, soak, process-restart, multi-host, or distributed
  limiter test.
- Circuit and limiter state are process-local and reset on restart.
- The token estimator is approximate.
- Unknown project labels prevent safe multi-project quota claims and live failover.
- Twelve requests do not calibrate availability or latency.
- Persistent metrics export, alerting, cancellation propagation, graceful shutdown, and
  cross-process coordination remain future work.
