# M4 Gemini Credential Qualification V1

## Scope and outcome

M4-04B1K screened the seven configured Gemini credential slots independently, then
requalified the fixed transport-model candidates on one deterministically selected
credential. This was provider/transport qualification only. It did not evaluate story
extraction quality or select an extraction model.

The final result is `M4_04B1K_NO_STABLE_MODEL_ON_SELECTED_CREDENTIAL`. Six credential
slots passed the 3/3 health screen, but none of the three fixed models passed the 3/3
model Stage A gate. Profile S was therefore not executed, no
`M4_RESEARCH_EXECUTION_PROFILE_V1` was created, and M4-04B2 remains blocked and not
started.

## Why project labels were not required

Project labels are local scheduling aliases, not credential validators or proof of a
Google project identity. The task needed to compare the health of individual credentials,
so every block used exactly one slot and disabled credential/project failover. Missing
labels did not prevent this isolated test.

The consequence is an explicit claim limit: project topology and independent-project
count remain `UNKNOWN`. Seven credentials do not imply seven independent quota pools.
The screen must not be interpreted as quota pooling or permission to rotate credentials
after a 429 or 503.

## Global unknown-topology safety pacing

The private protocol was locked before live execution with SHA-256
`18f015edb6a56fc15961d1a57f2bddbc8a0d619d33346cc1547daff3d0185374`.
It added one task-level sliding-window limiter shared by every credential and model block:
at most six provider-operation reservations per rolling 60 seconds. The limiter reserved
immediately before each provider operation and did not reset when a fresh per-slot runtime
was created. Longer V1.1 Retry-After/backoff waits remained authoritative.

The task made 37 provider operations. The limiter waited seven times for 62.602229 seconds
in total, observed at most six reservations in a rolling window, and passed its invariant.
All execution was sequential. Cross-slot failover count was zero.

## Credential screen

Each configured slot received three deterministic synthetic requests against
`gemini-3.5-flash-lite`, with concurrency one, local RPM 6, local TPM 3000, and no manual
rerun.

| Slot | Result | Success | Provider attempts | Principal finding | Provider p95 |
|---|---:|---:|---:|---|---:|
| `gemini_slot_1` | PASS | 3/3 | 3 | clean | 8052.055 ms |
| `gemini_slot_2` | PASS | 3/3 | 3 | clean | 5925.060 ms |
| `gemini_slot_3` | PASS | 3/3 | 3 | clean | 5037.569 ms |
| `gemini_slot_4` | PASS | 3/3 | 3 | clean | 5828.535 ms |
| `gemini_slot_5` | FAIL | 0/3 | 1 | one sanitized `AUTH_FAILURE:403`; two safe circuit-blocked terminal states | 4018.631 ms |
| `gemini_slot_6` | PASS | 3/3 | 3 | clean | 5582.611 ms |
| `gemini_slot_7` | PASS | 3/3 | 3 | clean | 5450.276 ms |

All slot blocks passed runtime invariants. There were no 429, 5xx, timeout or network
events in the credential screen. Slot 5 failed the required zero-auth-failure rule; its
failure did not disqualify or trigger failover to another slot inside that block.

## Selected credential

The locked selection rule first required 3/3 success, then compared provider failures,
retries, 503, 429, provider-latency p95, and finally slot number. All six passing slots had
zero provider failures and retries. `gemini_slot_3` had the lowest provider-latency p95
(5037.569 ms), so it became `M4_GEMINI_RESEARCH_CREDENTIAL_V1` for the remainder of this
task. This selection says nothing about independent quota.

After a fixed 60-second quiet period, all later provider work used only
`gemini_slot_3`. The other slots were not eligible for failover.

## Model requalification

Provider model-get probes reported all three preregistered candidates available:

- `gemini-3.8-flash`, provider version `3.0`
- `gemini-3.7-flash`, provider version `3.7-flash-08-2026`
- `gemini-3.5-flash-lite`, provider version `3.5-flash-lite-07-2026`

Stage A used three synthetic semantic requests per model, concurrency one, and the same
accepted `GEMINI_TRANSPORT_RESILIENCE_V1_1` behavior.

| Model | Result | Success | Attempts | Failure evidence | Provider p95 |
|---|---:|---:|---:|---|---:|
| `gemini-3.8-flash` | FAIL | 2/3 | 7 | five `SERVER_FAILURE:503`, four retries, one circuit open | 10305.211 ms |
| `gemini-3.7-flash` | FAIL | 2/3 | 5 | two `SERVER_FAILURE:503`, one `PROVIDER_FAILURE:NO_PROVIDER_CODE`, two retries | 510341.349 ms |
| `gemini-3.5-flash-lite` | FAIL | 2/3 | 3 | one `PROVIDER_FAILURE:NO_PROVIDER_CODE` | 3641.989 ms |

All three blocks had bounded terminal states, zero cross-slot failover, zero 429, zero
timeout/network/auth failure, zero attempt-cap violation, and passing runtime invariants.
The provider outcomes failed the strict 3/3 Stage A threshold.

## Final research profile and state

No model advanced to Profile S. The task stopped at the preregistered short circuit, did
not run C2, did not create `M4_RESEARCH_EXECUTION_PROFILE_V1`, and did not rerun any block.
`M4_04B2_ELIGIBLE = false`.

The historical conclusions remain unchanged:

- M4-04B1: OFFLINE PASS / LIVE FAIL
- M4-04B1R: RUNTIME CORRECT / PROVIDER GATE UNHEALTHY
- M4-04B1Q: NO STABLE GEMINI MODEL PROFILE

Extraction model remains `NOT SELECTED FOR QUALITY`; extractor remains `NOT LOCKED`.
Holdout input was not opened, gold remains sealed/not opened, predictions were not run,
and contamination remains `CLEAN`.

## Limitations

This result measures a small, time-bounded synthetic transport sample. It does not prove
production SLA, future availability, extraction quality, quota ownership, project
independence, or production capacity. Credential health and model availability can change.
In particular, the six passing credentials must not be treated as six quota pools.
