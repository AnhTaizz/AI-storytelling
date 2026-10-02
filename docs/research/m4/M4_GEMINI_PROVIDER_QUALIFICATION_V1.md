# M4 Gemini Provider Capacity Qualification V1

Status: **NO STABLE PROVIDER PROFILE**

Task: `M4-04B1Q-GEMINI-PROVIDER-CAPACITY-QUALIFICATION`

## Purpose and claim boundary

This task asked whether the current Gemini environment could support a conservative
research execution profile through the accepted `GEMINI_TRANSPORT_RESILIENCE_V1_1`
runtime. It measured provider availability, transport reliability, latency and
rate-limit behavior using tiny synthetic JSON prompts.

It did not measure extraction quality, select an extraction model, lock an extractor,
open story data, or run holdout predictions. A transport-qualified model would only have
been eligible for later M4-04B2 quality evaluation; it would not have been an extraction
winner or production model.

## Why project labels were optional

The Project Owner explicitly chose not to require labels for this qualification. Seven
credential slots were configured and all seven were unlabeled, so Google-project topology
and independent quota count remained `UNKNOWN`. No inference such as “seven keys equal
seven quotas” was made.

All official discovery and qualification traffic used only the lowest-numbered valid
credential, `gemini_slot_1`. It succeeded during discovery and was locked for the task.
The other six credentials were never used. Credential rotation for 429, 503, quota
pressure, or latency was disabled, as was multi-project failover.

These choices make the result a single-credential provider observation rather than a
multi-project capacity claim.

## Candidate discovery

Provider `models.list` returned 61 accessible models, of which 18 passed the stable
text-generation filter. Before any qualification outcome, the deterministic selection
rule locked three candidates:

1. Candidate A — latest stable Flash: `gemini-3.8-flash`.
2. Candidate B — previous stable Flash generation: `gemini-3.7-flash`.
3. Candidate C — stable Flash-Lite: `gemini-3.5-flash-lite`.

All three advertised `generateContent`; preview, experimental, deprecated,
embedding-only and image-only models were excluded. Selection did not use output quality.

## Preregistered method

The private protocol was locked before the first candidate request with SHA-256
`e9a448fcb4629d69e76a9c721d1599afe58a3ce67867e401adb2e20bb0c8183a`.
It bound the base commit, runtime/tool hashes, SDK 2.27.0, locked slot, candidate order,
synthetic prompt template, RPM 6, TPM 3000, retry/circuit settings, exact stage rules,
30-second quiet intervals, short-circuit rules, request/attempt budgets and profile
selection order. It was not edited after live results began.

Each semantic request allowed at most three provider attempts through normal runtime
behavior. No manual retry was allowed. Provider `Retry-After` retained precedence over
bounded exponential backoff and jitter. Local RPM/TPM values were conservative safety
settings, not claims about Google quota.

Stage A ran three requests sequentially for every candidate and required exactly 3/3
success plus all runtime invariants. Only a Stage-A-passing candidate could run the
12-request sequential Profile S. Profile C2 at concurrency two was permitted only after
Profile S achieved at least 11/12 successes.

## Stage A results

`gemini-3.8-flash` failed Stage A with 0/3 semantic successes. Its first request consumed
the allowed three provider attempts, all `SERVER_FAILURE:503`; the circuit then blocked
the remaining two requests. Runtime invariants passed. Request latency was 0.331 ms
minimum, 0.677 ms p50, 43,242.767 ms p95 and 48,047.444 ms maximum; the near-zero values
are circuit-blocked terminals rather than provider responses. Provider latency was
5,149.408 ms p50 and 31,317.444 ms p95.

`gemini-3.7-flash` also failed with 0/3 successes, three `SERVER_FAILURE:503` attempts and
two circuit-blocked requests. Runtime invariants passed. Request latency was 0.327 ms
minimum, 0.617 ms p50, 170,271.159 ms p95 and 189,190.108 ms maximum. Provider latency was
76,992.908 ms p50 and 100,780.643 ms p95.

`gemini-3.5-flash-lite` passed Stage A cleanly with 3/3 successes, three provider attempts,
no retry, 429, 5xx, circuit event or local rate wait. Provider responses reported the
requested model. Request latency was 7,499.024 ms minimum, 7,927.670 ms p50, 9,042.207 ms
p95 and 9,166.044 ms maximum. Provider latency was 7,916.023 ms p50 and 9,032.880 ms p95.

Only `gemini-3.5-flash-lite` advanced to Stage B.

## Profile S result

The Flash-Lite sequential profile used concurrency one, local RPM 6 and local TPM 3000.
It reached 9/12 successes, below the required 11/12. Fourteen provider attempts observed
five `SERVER_FAILURE:503` events, four transport retries, one circuit-open transition and
two circuit-blocked semantic requests. The local RPM limiter waited seven times; there
were no TPM waits, 429s, timeouts, network failures, auth failures, model switches,
uncaught exceptions or attempt-cap violations.

All runtime invariants passed. Request latency was 0.442 ms minimum, 10,410.966 ms p50,
28,975.682 ms p95 and 32,771.683 ms maximum. Provider latency was 6,428.587 ms p50 and
11,362.044 ms p95. Queue wait was zero at p50 and p95 because execution was sequential.

Because Profile S failed, Profile C2 was not executed. Candidates A and B never reached
Profile S because they failed Stage A. No block was rerun to improve an outcome.

## Failure fingerprints and runtime observations

The only provider failure fingerprint observed was `SERVER_FAILURE:503`, eleven times
across all blocks. There were zero 429 events, so this task provides no new rate-limit
cause evidence. Total execution comprised 21 semantic requests, 23 provider attempts,
12 successes, nine failures, eight transport retries, three circuit-open events, six
circuit-blocked requests, seven local RPM waits and zero invariant failures.

The results reinforce the distinction already recorded by M4-04B1R: bounded runtime
behavior can remain correct while provider reliability is insufficient for a research
gate. Provider failures alone did not authorize redesign of the accepted V1.1 runtime.

## Qualification decision

No model passed Profile S. Therefore:

```text
transport-qualified models: none
M4_RESEARCH_EXECUTION_PROFILE_V1: not created
M4_04B2_ELIGIBLE: false
M4-04B2: BLOCKED / NOT STARTED
```

The historical M4-04B1 live failure and M4-04B1R provider-unhealthy result remain intact.
Extraction model is `NOT SELECTED`, extractor is `NOT LOCKED`, holdout input is `NOT
OPENED`, gold is `SEALED / NOT OPENED`, holdout predictions are `NOT RUN`, and
contamination remains `CLEAN`.

## Limitations

Results apply only to this credential, provider, model set and execution time window.
They do not establish a production SLA, sustained throughput, independent-project quota,
multi-key capacity, extraction quality, cost efficiency, or future provider availability.
The candidate blocks are deliberately small and conservative, and circuit-blocked request
latencies should not be interpreted as provider response latency.

