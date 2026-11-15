# M4-04B3F/G proposal: lock a Draft V1.1 protocol, then run it blind on Fresh Validation V1

Status: PROPOSAL, authorized on the owner's delegation of 2026-11-15. M4-04B3F is done:
see `benchmarks/m4_extraction/M4_04B3F_FV1_PROTOCOL_LOCK.yaml` for the locked protocol and
the decisions taken. M4-04B3G (the blind run) has not started.

## Why this is the next step

- Draft V1.1 removed the mention/evidence ambiguity behind 8 of 10 DEV2 failures
  (`docs/research/m4/M4_DRAFT_INTERFACE_V1_1.md`).
- The mechanical migration lifted the DEV2 structural result from 2/10 to 6/10. That is a
  tuning diagnostic, not evidence about a model.
- M4-04B3E sealed a fresh set for V1.1 (`docs/research/m4/M4_FRESH_VALIDATION_V1_PROTOCOL.md`):
  10 cases, input SHA-256 `724041283cde55ccbce27844c9297cf66eed857c96cf18989dc97997fef55729`.
- The open question is whether a model writing V1.1 directly produces drafts that compile.
- Until an extractor is chosen, the story pipeline writes its own briefs and cannot use M4
  facts (the `story_facts/v0` seam is unused).

## Two tasks, each needing its own authorization

| Task | Does | Provider calls | Opens gold |
|---|---|---|---|
| **M4-04B3F** protocol lock | Writes versioned V1.1 prompts and the protocol; binds every hash; offline tests | 0 | no |
| **M4-04B3G** blind run | Runs the locked protocol on the 10 FV1 inputs, then locks and hashes the predictions | ≤ 20 | no |

Scoring is a third task (M4-04B3H). Only it opens the gold, and only after the M4-04B3G
predictions are committed.

## Proposed protocol (M4-04B3F)

- **Interface:** `STORY_EXTRACTION_DRAFT_V1_1`, compiled by the unchanged
  `compile_story_extraction_draft_v1_1`.
- **Prompts:** new files, so the B3B2 prompts stay byte-identical:
  - `story_extraction_draft_p3_system_v1_1.txt`;
  - `…_p3_user_v1_1.txt`;
  - `…_p3_repair_user_v1_1.txt`.

  They copy P2 except where V1.1 differs:
  - The model-facing mention has `handle`, `passage_handle`, `quote`, `occurrence`, `role` and
    `surface_form`, and no `evidence_handle`.
  - The prompt says that the host binds mention evidence itself.
  - The repair prompt shows all V1.1 structural blockers, by phase, code and path, without
    source text.

  No other wording changes. The P3 prompts are written against DEV1/DEV2 tuning material
  only, never against FV1 text.
- **Model and settings:**
  - Model: `gemini-3.5-flash-lite`, the same model as DEV2, so the two results can be
    compared.
  - Settings: temperature 0, provider JSON mode, concurrency 1, global pacing of 6
    operations per 60 s, and the durable executor profile accepted in M4-04B1D2.
- **Repair:** at most one structural repair per case. It is allowed only for
  JSON / schema / compiler failures, never for coverage or quality. A failed repair is
  terminal.
- **Binding:** the protocol binds:
  - the FV1 input hash and its blindness manifest;
  - the prompt and materialized-prompt hashes;
  - the model and settings, the runtime profile and the compiler hashes;
  - Snapshot V2.
- **Prediction lock:** raw responses, parsed drafts, compiled batches or terminal failures,
  and per-case results are hashed and committed before anyone opens the FV1 gold.

## Decisions needed from the owner

1. **Authorize M4-04B3F** (offline; no calls).
2. **Model for the primary arm:**
   - **Recommended:** `gemini-3.5-flash-lite`, for comparability with DEV2.
   - **Alternative:** `gemini-3.6-flash`, the model the story pipeline now uses successfully,
     as a second, separately locked arm.
   - Running both doubles the calls (≤ 40).
3. **Credential:** the B3B2 lock named `gemini_slot_3`. The keys now configured in the cloud
   environment are different, so B3F must re-qualify one credential (one smoke call is
   allowed under the M4-04B1K procedure), or name a new slot.
4. **Storage:** the FV1 input and gold packages exist only in a cloud session and were sent
   to the owner as files. B3G needs the input package in a git-ignored path, checked against
   its hash. The gold stays unopened until B3H.

## What this does not claim

- A good structural result on FV1 shows that V1.1 is writable. It does not show extraction
  accuracy; that is B3H's job, against agent-draft gold that is not human-confirmed.
- No result from this set can be used to select an extractor without the sealed holdout
  (M4-03), which stays closed.
