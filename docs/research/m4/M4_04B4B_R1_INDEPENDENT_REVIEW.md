# M4-04B4B-R1 — Independent Review of the Draft V1.1 Candidate

Status: `M4_04B4B_R1_REVIEW_COMPLETE_PENDING_PROJECT_OWNER_DECISION`.

Date: 2026-10-30. Reviewed commit: `786d1c1`. Authorization: offline review only.

Companion documents:

- `M4_DRAFT_V1_2_GROUNDING_DECISION_PROPOSAL.md`: threat model, options, invariants, proposed contract, impact.
- `M4_DRAFT_V1_2_ADVERSARIAL_TEST_SPEC.md`.

Labels: **[VERIFIED]** checked in this task; **[INFERRED]** reasoned but not observed; **[RECOMMENDATION]**.

## 1. Status vocabulary

These statuses are not equivalent. Each is granted separately.

| Status | Meaning | M4-04B4B |
|---|---|---|
| Implementation complete | Code and artifacts exist as specified | **Yes** |
| Offline verified | Behaviour reproduced by offline tests; no model involved | **Yes, with findings R1–R7** |
| Development candidate accepted | Project Owner accepts it as the candidate for development runs on tuning data | **Not granted**; recommendation below |
| Independent validation approved | Gate C for a sealed, fresh validation set | **No** |
| Production-qualified | Proven extraction quality for downstream use | **No** |

## 2. Review checklist

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | P3 complies with Draft V1.1 | **Pass with one defect (R1)** | No V1 tokens, no `evidence_handle` and no DEV wording in P3 or the materialized schema section (tests). The text "Emit all eight required top-level arrays" is wrong: V1.1 requires seven arrays plus the `draft_version` string. Inherited from P2 (`story_extraction_draft_p2_system_v1.txt:31`). |
| 2 | Bundle preserves constraints | **Pass, proven structurally** | After `$ref` rewriting, every bundled definition and the root equal the authoritative V1 and V1.1 definitions once three annotation keys (`$id`, `$comment`, `description`) are removed. This is equality, not sampling. The earlier 38-draft verdict equivalence is consistent with it. |
| 3 | Runner deterministic where required | **Pass** | Double compile must give equal canonical JSON; prediction-set hash is stable across reruns; record order is invariant; compiler output is identical with CRLF schema copies. |
| 4 | No live inference without authorization | **Pass at the CLI; gap programmatically (R2)** | `run-live` needs a candidate-bound authorization record, and without one the live transport is never built (tested). `execute()` accepts any injected transport, so a Python caller could pass a live transport without a record. No such caller exists in the repository. |
| 5 | Checkpoint, resume and repair accounting | **Pass, with two semantics to note (R3, R4)** | Rerun makes zero calls; a crash resumes without a duplicate success; at most one repair per case; transport failures are kept separate. R3: the token cap is checked after a job, so a run can exceed it by at most one job's usage before stopping. R4: a budget or drift stop in the middle of a case leaves that case's primary artifacts on disk but no case result; the run status is `INCONCLUSIVE_*`. |
| 6 | Manifest binds all dependencies | **Fail (R5)** | The import closure of the runner plus the live transport loads `tools/story_extraction/gemini_errors_v1.py` (provider-error classification, which decides deferral versus terminal) and `tools/story_extraction/m4_04b2_dev_protocol_v1.py` (live-wrapper constants). Neither is in `BOUND_FILES`. Third-party versions (`jsonschema`, `referencing`, `PyYAML`, `google-genai`) and the Python version are not recorded (R6). |
| 7 | Reported offline results reproducible | **Pass** | Rerun in this task gives the same counts as in M4-04B4B (§3). |

Additional findings:

- **R7.** `draft_v1_1_conformance_diagnostics_v1` swaps a module-global function while it observes. It is serialized by its own lock but is not safe if another thread compiles at the same time outside the observer. The runner's concurrency is 1, so this is acceptable for now and is recorded.

## 3. Reproduced test results [VERIFIED]

| Suite | Result |
|---|---|
| New M4-04B4B tests | 53/53 pass |
| New R1 silent-grounding tests | 14/14 pass |
| story_extraction | 423/429 pass; the 6 failures are pre-existing D1 failures (two CRLF-form V1 locks) |
| canonical_story | 99/99 |
| script_quality | 64/64 |
| story_ingestion | 78/79 (`.local/`) |
| story_benchmark | unchanged pre-existing environment failures |

## 4. Verdict on M4-04B4B

**[RECOMMENDATION] CONDITIONAL ACCEPT**, as offline-verified extraction *infrastructure*: the runner, observer, schema bundle, manifest tooling and hash policy.

**Do not accept P3 / Draft V1.1 as the candidate for independent validation.** The reasons are in the grounding proposal:

- A wrong but in-range `occurrence` compiles into a structurally valid, provenance-consistent canonical record that points at the wrong source span.
- Only gold-based evaluation detects it.
- Spending fresh validation data on an interface with a known silent-corruption path would measure a defect already known offline.

Conditions before any model run, even on tuning data:

1. **R5.** Bind `gemini_errors_v1.py` and `m4_04b2_dev_protocol_v1.py`, or move the live window transport out of the B2 runner into a bound module, in a versioned manifest.
2. **R1.** Correct the array-count sentence in the next prompt version. P3 stays as recorded.
3. **R6.** Record third-party package versions and the Python version in the manifest.
4. **R2.** Require an authorization object in `execute()` whenever the transport is not explicitly marked offline.

## 5. Conformance diagnostics: proven versus hypothesized

**Proven [VERIFIED]:**

- `CANONICAL_CONFORMANCE_FAILURE` is the single code for every invariant enforced only by the canonical validator: registry, support path, epistemic, temporal and derivation.
- Seven synthetic classes reproduce it.
- The observer leaves compile outcomes unchanged.

**Hypothesized [INFERRED]:** the five DEV2 failures (DEV2_03, DEV2_04, DEV2_07) are model-authored registry or epistemic violations. Confidence: low for the specific class, medium for model ownership.

**Unknown:** which check section failed for each of the five, and whether any of them is a compiler-owned section. The original evidence (the private drafts and the blocker paths) is not available here.

**None of the five has been individually diagnosed.**

## 6. Hashing: migration policy [RECOMMENDATION]

**Facts [VERIFIED]:**

- All 397 tracked text files are stored LF in the index (`git ls-files --eol`), so `git add --renormalize .` would change no content.
- An LF checkout fails the two CRLF-form historical locks.
- A simulated CRLF checkout fails at least five LF-form locks.

**Policy:**

1. Historical lock values are immutable evidence of what was hashed. They are never rewritten.
2. New locks record `content_sha256_lf` and `git_blob_sha1_lf`. Raw hashes are kept as observations only.
3. A verification helper accepts a historical raw lock only when either:
   - the raw bytes match; or
   - an **entry-specific** record in `M4_HASH_NORMALIZATION_RECORD_V1.yaml` declares the CRLF form and `sha256(crlf(lf_content))` equals the recorded value while `content_sha256_lf` equals the entry.

   There is no blanket CRLF acceptance.
4. Add `.gitattributes` with `* text=auto eol=lf`, `*.zip binary`, `data/**/raw/** -text`. Source text is evidence and is never converted.
5. Update the two historical lock tests to use the helper in a separate versioned change with an impact note. Expected values are not edited.

This is not applied here.

## 7. Approval requests

Listed in full in the decision proposal §9. In brief: conditional acceptance of M4-04B4B; the V1.2 direction; an offline V1.2 implementation task; the grounding invariants; the hash migration; the four pending reviews.
