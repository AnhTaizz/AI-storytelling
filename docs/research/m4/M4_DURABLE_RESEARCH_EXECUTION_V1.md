# M4 Durable Research Execution V1

## Scope and integrity result

`DURABLE_RESEARCH_EXECUTOR_V1` is a research orchestration layer above the accepted
`GEMINI_TRANSPORT_RESILIENCE_V1_1`. It makes intermittent provider failure survivable
without changing the semantic request, rotating credentials, choosing among multiple
successful responses, or retrying because of output quality.

The live run observed `gemini-3.5-flash-lite` complete all six synthetic jobs as
`SUCCEEDED_LOCKED` in their first execution window. However, final integrity verification
found that the already-locked private protocol contains an invalid YAML indentation in its
`job_states` section. The protocol was not edited after live execution and the live gate was
not rerun. Consequently, the observed pass and generated private profile are provisional
evidence only: no durable research profile is qualified, M4-04B2 remains blocked, and the
honest task status is `M4_04B1D_FIX_REQUIRED`.

## Bounded transport retry versus deferred execution

V1.1 remains responsible for one execution window. Within a window it may make at most
three provider attempts using its existing retry, circuit, and RPM/TPM policy. The durable
executor does not alter that machinery.

If a window ends without any successful provider response and its sanitized category is
transport/provider-related, the job may become `DEFERRED_TRANSPORT`. A later window uses
the identical request fingerprint after a minimum 60-second cooldown. Retry-After takes
precedence when longer. Each job has at most three windows and therefore at most nine
provider attempts.

This is different from a semantic retry. Invalid JSON, schema/canonical validation failure,
missing assertions, hallucination, low confidence, evaluation score, gold comparison, or
reviewer preference cannot trigger a durable window. A successful provider response ends
transport responsibility regardless of its semantic quality.

## Identity and checkpoint semantics

Each request fingerprint is SHA-256 over canonical JSON containing the model, system and
user prompts, generation configuration, response mode, credential slot, and research task
identity. A checkpoint with a different fingerprint, model, credential, task, protocol
hash, or accounting limit fails closed.

Every job has an integrity-checked private JSON checkpoint with explicit state:
`PENDING`, `IN_FLIGHT`, `DEFERRED_TRANSPORT`, `SUCCEEDED_LOCKED`, or `TERMINAL_FAILED`.
State transitions are appended rather than silently overwritten. Writes use a flushed,
fsynced temporary file followed by atomic replacement.

The global unknown-topology pacing state is also persistent. Restarting the process does
not reset the rolling ceiling of six provider operations per 60 seconds.

## First-success lock and crash safety

The first successful provider response is stored with its raw response, response hash,
provider metadata, reported model version, usage, and attempt history before the executor
returns it to the caller. `SUCCEEDED_LOCKED` is terminal. Resuming that job performs zero
new provider calls.

This closes the required crash case where a process stops after the success checkpoint but
before final summary generation. An ambiguous crash while a call is still `IN_FLIGHT`
fails closed for manual investigation, avoiding an automatic duplicate-success call.

The live audit recorded 16 success locks, zero provider calls after a success lock, zero
response comparison, and zero output-aware retry. Deferred execution therefore did not
act as best-of-N sampling.

## Live qualification evidence

All candidates used only `gemini_slot_3`, concurrency one, synthetic prompts, and the
persistent 6/60 limiter.

| Model | Result | Eventual success | Windows | Provider attempts | 503 | 429 | Deferred/resumed |
|---|---:|---:|---:|---:|---:|---:|---:|
| `gemini-3.8-flash` | FAIL | 5/6 | 11 | 26 | 11 | 10 | 5/5 |
| `gemini-3.7-flash` | FAIL | 5/6 | 10 | 22 | 14 | 3 | 4/4 |
| `gemini-3.5-flash-lite` | PASS | 6/6 | 6 | 6 | 0 | 0 | 0/0 |

For 3.8 Flash, one job used all three windows and nine attempts, observing seven 429 and
two 503 responses. For 3.7 Flash, one job likewise exhausted three windows and nine
attempts, observing three 429 and six 503 responses. Both candidates therefore failed the
strict 6/6 rule even though five jobs eventually succeeded.

Flash-Lite completed all six jobs cleanly in their first window with one provider attempt
per job. It was the first observed passing candidate in the locked text order. The
post-execution YAML parse defect prevents promoting that observation to a qualified profile.

Across the task, the durable layer used 27 windows and 54 provider attempts, with 25 503
and 13 429 events. Nine jobs were deferred and resumed. Persistent global pacing waited
eight times for 77.704956 seconds, observed a maximum of six reservations in its rolling
window, and passed its invariant.

## Why this does not contaminate quality research

No story development or holdout content was opened. No gold or evaluation metric was
available. A new window was permitted only when no successful provider response existed,
and the first successful response became irrevocable. Provider availability—not response
content—controlled deferral.

## Limitations

The immutable protocol defect requires a new explicitly authorized, preregistered task; it
cannot be repaired retroactively and the live workload was not rerun. Apart from that
integrity blocker, the evidence covers only a small synthetic workload at one point in
time. It does not
prove extraction quality, future provider availability, production capacity, quota
ownership, independent project topology, or production reliability. M4-04B2 remains
blocked pending Master Orchestrator review.
