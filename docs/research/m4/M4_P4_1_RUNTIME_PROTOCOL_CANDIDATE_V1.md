# M4 P4.1 Runtime Protocol Candidate V1

Task: M4-04B4E. Status: `M4_04B4E_PROTOCOL_VIOLATION`. Offline only.

Every offline safety, mock-runtime and regression gate of this task passes. The status is
a protocol violation for one reason, reported by the executor: before the commit, a
secret scan reused from earlier tasks read the local credential file once, to assert
that no key value appears in the files to be committed. The brief required zero
credentials loaded. No value was printed, stored or transmitted, no provider client was
created and no call was made. The protocol, the harness and the tests load no
credential, and nothing below depends on the read. The committed files were scanned
again with a pattern-only scan that opens no credential file. An Orchestrator ruling is
requested; the record has the details.

Every result in this note is `SYNTHETIC_MOCK_ONLY_NOT_PROVIDER_EVIDENCE`. No provider or
model was called. No DEV3 input, DEV3 gold, private B4C prediction, holdout file or
other private story content was opened. A live P4.1 result does not exist.

## 1. What this task produced

| Item | Identity |
| --- | --- |
| Runtime protocol candidate | `M4_P4_1_RUNTIME_PROTOCOL_CANDIDATE_V1` |
| Protocol candidate SHA-256 | `5917a012663963d1d9e15f3be00c38a9ea1306d4fe8ad1e01134a99dc3618ff7` |
| Standing | `PROPOSED_EXPERIMENTAL_PROTOCOL_NOT_A_LIVE_AUTHORIZATION` |
| Active P4.1 candidate | `P4_1_STORY_EXTRACTION_DRAFT_V1_1_COMPILER_AWARE_V1_1` |
| Active candidate SHA-256 | `5a102aa782f876dcbfc94d71fef238de0e712288ed4428a27df6984edfe23019` |
| Active diagnostic | `M4_P4_1_STRUCTURAL_REPAIR_DIAGNOSTIC_V3_1` |
| Diagnostic tool SHA-256 | `6cd81cb029baa48998cb2f4da9c75a17be6c984965584b8cedb52c721ae3ee33` |
| Retention metrics | `M4_P4_1_STRUCTURAL_RETENTION_METRICS_V1` |

Three new modules, all additive:

- `tools/story_extraction/m4_04b4e_p4_1_runtime_protocol_candidate_v1.py`: the protocol
  candidate, the request builders, the protocol checker and the repair-actionability
  rule.
- `tools/story_extraction/m4_04b4e_p4_1_retention_metrics_v1.py`: structural retention
  and empty-output metrics.
- `tools/story_extraction/run_m4_04b4e_p4_1_synthetic_mock_v1.py`: the offline mock
  harness.

The superseded candidate V1, diagnostic V3 and diagnostic V2 are rejected wherever a
binding or a request is checked, and the runtime never calls them. Protocol V2, the P4
prediction set and every historical record are unchanged.

## 2. The protocol candidate

The candidate keeps the runtime shape of P4 protocol V2 and changes the model-facing
contract and the repair path.

| Setting | Proposed value | Standing |
| --- | --- | --- |
| Model | `gemini-3.5-flash-lite` | proposed, same as protocol V2 |
| Credential slot | `gemini_slot_3` | proposed, a label only; nothing resolves it |
| Temperature | `0` | proposed |
| Max output tokens | `16384` | proposed |
| Response MIME | `application/json` | proposed |
| Native schema | exact accepted provider projection `89506def…b9bd` | proposed |
| Prompt schema | full model schema `5aa2ed6d…7f14`, complete, in the system prompt | bound |
| Concurrency | `1` | proposed |
| Pacing | 6 operations per rolling 60 seconds | proposed |
| Execution windows per job | 3, with 3 attempts each | accepted durable executor |
| Structural repairs per case | at most 1 | bound |
| Live operation budget | `REQUIRES_ORCHESTRATOR_AUTHORIZATION` | not set |

The 30-operation budget of M4-04B4C is not inherited. The generation settings are the
exact settings object of protocol V2.

The protocol hash binds: the candidate and diagnostic identities and hashes, the six
prompt hashes, the full schema and projection hashes, the validator and compiler, 31
files by content hash, the proposed model and settings, the durable executor identity
and limits, the one-repair policy, the exactly-once rules, the repair-actionability
classes and decisions, the request identity patterns and the retention metric
definitions. A change to any of them is a different protocol.

The candidate lists six open decisions. `assert_ready_for_live_lock()` fails while any is
open, so this candidate cannot be locked for a live run as it stands.

## 3. Requests and the checker

Requests are built without a provider client. The primary request carries the P4.1 V1.1
primary system prompt, which contains the complete model schema and the registry. The
native response schema is the projection, never the full schema. The repair request
carries the V1.1 repair prompt and diagnostic V3.1; the V1.1 repair contract rebuilds
the diagnostic from the response and the compiler context and compares it before it is
rendered.

The checker rejects, each with its own test: the superseded candidate V1; diagnostic V3
and V2, by prompt and by the diagnostic embedded in the request; a missing or altered
projection; the full model schema used as native schema; P4 prompts; any changed prompt;
a prompt without the complete schema; an altered model, setting or response mode; an
unexpected credential slot; a second repair; a request of another protocol; and a
request whose identity is not the one the builders produce for the same inputs. Text
inside a primary response cannot pose as the diagnostic section.

## 4. The mock harness

The transport is a scripted fake that is injected. It holds no credential and no
client. The harness imports no provider SDK, no credential loader and none of the
accepted Gemini transport modules; a test confirms this in fresh processes. It refuses
to run in a process that holds provider credential variables, refuses any transport
other than its own mock, and accepts no dataset or credential path. Time is a virtual
clock, so a run never waits and its artifacts are reproducible byte for byte.

The input is one invented sentence and hand-written drafts defined in the harness.
Twenty-one scenarios ran: the twenty required simulations, and one more that repeats
scenario 20 under the other branch of the one undecided policy.

| Scenario | Simulates | Outcome | Mock operations |
| --- | --- | --- | --- |
| S01 | valid primary | valid | 1 |
| S02 | invalid JSON primary | valid after repair | 2 |
| S03 | full-schema-invalid primary | valid after repair | 2 |
| S04 | projection-valid, full-schema-invalid primary | valid after repair | 2 |
| S05 | quote occurrence missing | valid after repair | 2 |
| S06 | entity-kind reference | valid after repair | 2 |
| S07 | derivation conclusion | valid after repair | 2 |
| S08 | duplicate proposition | valid after repair | 2 |
| S09 | several blockers | valid after repair | 2 |
| S10 | byte-identical repair | structural failure | 2 |
| S11 | repair changes the blocker | structural failure | 2 |
| S12 | transport retry, then success | valid | 5 |
| S13 | terminal transport failure | transport failure | 9 |
| S14 | interrupted checkpoint | run stopped, review required | 1 |
| S15 | duplicate terminal job attempt | valid; second attempt refused | 1 |
| S16 | budget exhaustion, synthetic limit 2 | run stopped at the limit | 2 |
| S17 | pacing saturation, four cases | all valid, one pacing wait | 8 |
| S18 | empty but compiler-valid output | valid, flagged empty | 1 |
| S19 | repair removes supported records | valid, flagged | 2 |
| S20 | unknown canonical error, refuse policy | structural failure, no repair | 1 |
| S21 | same response, allow policy | valid after repair | 2 |

These outcomes are scripted. They show that the runtime path does what the protocol
says. They say nothing about what a model would return.

## 5. Diagnostic V3.1 in the runtime

For every response the unchanged validator and compiler decide. Diagnostic V3.1 is then
built from the exact locked response and the compiler context.

- If the diagnostic disagrees with the compiler's verdict, the run stops. The compiler
  is never overruled.
- If the diagnostic fails its own safety assertion, the response keeps the compiler's
  verdict and no repair is sent.
- The host never edits a draft and never chooses an occurrence. Every stored draft
  equals the parsed raw response.
- In the mock, 13 primaries were rejected and 12 repairs were sent. Each of the 12
  repair requests has the fingerprint the protocol rebuilds from the stored primary and
  its stored diagnostic.

## 6. Answers to the design questions

### 6.1 When is an incomplete Diagnostic V3.1 still actionable?

`complete: false` alone refuses nothing. It is false for every rejected draft, because
the frozen compiler never lists every canonical issue.

A diagnostic is `ACTIONABLE` when every finding is repairable by the model, names a
recognized rule, and, if it is about one record, has a verified locator or a position
from the schema validator's path. It may still be incomplete in three statements, which
say what the compiler has not looked at yet and not that a finding is unusable:

- `compiler_structural_rules_checked`
- `canonical_validation_reached`
- `downstream_canonical_issues_enumerated`

All four mechanisms observed in M4-04B4CR produce actionable diagnostics, as do JSON
and schema failures.

### 6.2 When must the repair be refused for safety?

Decided, with a reason:

| Class | Decision | Reason |
| --- | --- | --- |
| Accepted response | no repair | nothing to repair |
| Invalid or unsafe diagnostic | no repair | it failed the safety assertion, is not V3.1, or is not the diagnostic of this response and context |
| Host-side failure | no repair | the model cannot correct a host context or compiler binding failure; a repair would ask it to change a draft that is not at fault |
| Empty primary response | no repair | the repair request cannot be built |

Not decided: a `PARTIALLY_DESCRIBED` diagnostic, where a finding about one record names
no record (for example a duplicated handle), or a finding names no recognized rule (a
canonical failure outside the three checked rule classes). Such a diagnostic is safe to
send: it contains nothing unverified. The open question is whether sending it is
useful or harmful.

- For repairing: P4 always repaired, with less information than V3.1 gives.
- Against: the model is told little, and the public M4-04B4CR record shows that the two
  canonical failures sent to repair under the generic diagnostic V2 both came back
  byte-identical. V2 is not V3.1, so this is a caution and not a prediction.

The protocol records this policy as `UNRESOLVED_REQUIRES_ORCHESTRATOR_DECISION`. No
default exists: a caller must state `REFUSE_REPAIR` or `ALLOW_REPAIR` on every call. The
mock exercises both (S20 and S21) so each behaviour is visible. Neither is proposed as
the answer here.

### 6.3 Can the runtime distinguish a genuinely corrected draft from a draft that simply deletes content?

Partly, and only structurally. S05 (occurrence added) and S19 (records deleted) both end
`STRUCTURAL_VALID`. The retention metrics separate them:

| Signal | S05, corrected | S19, deleted |
| --- | --- | --- |
| Finding cleared with its record kept | 1 | 0 |
| Finding cleared with its record removed | 0 | 1 |
| Records removed | 0 | 10 |
| Removed and named by a finding | 0 | 1 |
| Removed and dependent on a named record | 0 | 2 |
| Removed and explained by no finding | 0 | 7 |
| Records, primary to repair | 26 to 26 | 26 to 16 |

What this cannot show: whether a kept record still means the same thing, whether the
removed content was supported by the passages, or whether any record is correct. Those
need gold. A removal is also not always a loss: S08 removes one record, and it is the
duplicate that the finding named.

### 6.4 Which retention metrics are possible without gold?

All of these are computed from the two responses and their diagnostics alone:

- record counts by each of the seven collections, and the empty-output indicator;
- primary-to-repair count difference by collection;
- retained, removed and added handles, where every handle of a collection is used once;
- unchanged records and records changed in place, by comparing content under the same
  handle;
- whether the repair is byte-identical;
- which primary findings were cleared, which remain and which are new;
- whether a cleared finding's record was kept or removed;
- removed records by explanation: named by a finding, dependent on a named record, or
  neither;
- changed records that no finding named;
- whether structural validity rose while the record count fell.

Handle reuse is a structural identity signal, not proof that meaning was kept. Equal
counts do not mean equal content. Every metric is a research warning. There is no
threshold and no score, the metrics never change a terminal status, and nothing rewrites
or pads a prediction.

### 6.5 Does the runtime preserve all historical exactly-once guarantees?

For the guarantees that live in the accepted durable executor and pacer, yes, because
they are the same components, and the mock exercises each one: first-success lock,
request fingerprint bound into the checkpoint, write-once raw response, no retry of a
successful response, no second repair, a terminal case never executed again, an
in-flight checkpoint failing closed on restart, a new run on existing state refused,
and a budget and pacing state that survive a restart and cannot be reset.

Three qualifications:

1. This is shown on a mock transport. The accepted transport's own retry, backoff and
   circuit logic is not exercised here.
2. The harness writes its own execute-to-terminal loop, budget wrapper and write-once
   helper. The accepted versions live in modules that import the provider transport and
   the credential loader, and importing those would have made a provider call possible
   from this harness. A future live runner must either use the accepted live glue or
   have this glue reviewed.
3. An accounting note inherited from the accepted executor: a window that ends
   abnormally records no operations in its own checkpoint, while the pacer has already
   counted the operations that started. The pacer's persisted count is the authority,
   as it was in M4-04B4C. S14 and S16 show the two counts side by side.

### 6.6 What must be locked before the first future P4.1 provider operation?

- The six open decisions of the candidate, each resolved by the Orchestrator: the live
  operation budget; the repair policy for a partially described diagnostic; the model,
  credential slot and generation settings; the dataset and case list; the private root
  and result artifact contract; the live transport binding and execution environment.
- A new protocol identity and hash with no open decision.
- An experiment lock that binds that protocol hash, the input identity, the budget, the
  stop and resume policy and the reporting contract, committed and pushed before any
  input is opened or any provider is called.
- The reporting contract of the candidate: structural validity together with record
  retention by collection, the empty-output rate and the count of repairs identical to
  their primary. No threshold.
- A fresh private root that no earlier experiment used.

### 6.7 What would a future synthetic live smoke actually prove?

It would show that the provider accepts a request with the P4.1 system prompt and the
accepted projection, on one invented input, and that the response can be carried through
parsing, validation, compilation and, if the smoke is designed to reach it, one repair
with diagnostic V3.1. The P4.1 system prompt is longer than the P4 prompt that the
earlier smoke tested, so acceptance is not already established.

It would not show a structural validity rate, the effect of the P4.1 instructions,
whether repairs work, or anything about extraction quality. One request on one sentence
measures no rate.

### 6.8 What evidence must exist before authorizing P4.1 tuning on DEV3?

- This task accepted, and the open decisions resolved.
- A locked protocol with no open decision, and a pre-live experiment lock committed
  before DEV3 input is opened.
- If the Orchestrator requires it, a live synthetic smoke showing the request path
  works.
- An authorized operation budget.
- The reporting contract above bound into the lock.
- An explicit statement in the lock that DEV3 is tuning data for P4.1. P4.1 was designed
  from failures observed on DEV3, so a P4.1 result on DEV3 is a tuning comparison and
  never validation. Validation needs a fresh DEV4, which does not exist.
- The P4 prediction set and its records unchanged.

## 7. Limitations

- Nothing here is provider evidence, and no model behaviour was observed.
- The scenarios are scripted, so their outcomes hold by construction.
- The only input is one invented sentence.
- The retention metrics are structural.
- The repair policy for a partially described diagnostic is undecided.

## 8. Decisions that need the Orchestrator

First, a ruling on the credential file read described at the top of this note. Then:

1. The live operation budget.
2. The repair policy for a partially described diagnostic.
3. Confirmation of the proposed model, credential slot and generation settings.
4. The dataset and case list for any live run.
5. The private root and result artifact contract for any live run.
6. The live transport binding and execution environment.
7. Whether a live synthetic smoke is required before any tuning run.
8. Whether a future live runner reuses the accepted live glue or the glue of this
   harness.

Record: `benchmarks/m4_extraction/M4_04B4E_P4_1_RUNTIME_PREPARATION_AND_SYNTHETIC_MOCK.yaml`.
