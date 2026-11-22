# FV3 locked blind run (DEC-030)

The public seal fixes 16 cases in order from `fv3-01` through `fv3-16` and the
SHA-256 of each member of the sealed package set (input ZIP, gold ZIP and
blindness manifest). The protocol checks the seal and the V4 conventions digest.
All module names below are relative to `tools.story_extraction` for invocation with `python -m`.

1. Write the protocol with `m4_04b3z_fv3_protocol_v1 --directory DIR`. Preserve
   the printed SHA-256 independently. This offline step hashes the public files
   listed below. It uses the same model, temperature, durable executor, pacing
   profile and retry limits as DEC-027.
2. Run `run_m4_04b3z_fv3_predictions_v1 --mode preflight --protocol FILE --protocol-sha256 DIGEST --fv3-dir SEALED`.
   This verifies the protocol, public byte bindings, blindness manifest, input
   digest and case order, and reconstructs the trusted compiler contexts.
3. Invoke the same runner with `--mode run` and `--out PREDICTIONS`. Use a single
   prediction directory throughout the experiment. The runner takes an exclusive
   process lock on that directory before qualification. The first durable job is
   the B1K smoke using `gemini_slot_40`. A failed qualification stops the run.
4. For each case, send only its prepared input with P4R8. On a parsed response
   the dev validator runs QR, AM, ME (RefersTo and NamedAs), SE, TB, DA and VG
   in order. Each attempt records the repairs that ran and their reports.
   A successful transport with structural blockers permits one repair request
   with the original response and sanitized blockers. Transport exhaustion is
   terminal. Checkpoints preserve the first successful response across restarts.
5. After every case is terminal, the runner writes private artifacts, the
   manifest and the prediction lock. Retain the printed prediction-lock
   SHA-256 independently. A matching digest sidecar is written before the
   terminal lock is published. An existing lock forbids a second run. The runner
   never opens or hashes the gold archive.
6. Run `score_m4_04b3z_fv3_v1 --fv3-directory SEALED --prediction-directory PREDICTIONS --output-directory SCORE --protocol FILE --protocol-sha256 DIGEST --prediction-lock-sha256 LOCK_DIGEST`.
   The offline scorer verifies the protocol, terminal inventory, case order,
   prediction lock and all three package hashes before recording gold access.
   It scores the original V4 gold with the Snapshot V2 evaluator and checks
   compiled predictions with checker V3. Gold alignment is forbidden. Provider
   operations after gold opens are zero. Keep the evaluation and access record
   private. `PUBLIC_SUMMARY.json` contains only aggregate counts.

A changed digest, changed protocol semantics, ambiguous live credential, failed
smoke, inconsistent terminal artifact or unexpected case order refuses the
affected step. Gold must declare every case complete for profile. FV3 becomes
development data after scoring. A new blind evaluation requires a fresh seal.

## Public files bound by SHA-256

The inherited FV2 inventory is included because FV3 delegates policy construction
to that implementation. Each line is a repository-relative path.

```text
benchmarks/m4_extraction/M4_04B3M_FRESH_VALIDATION_V2_SEAL_RESULT.yaml
benchmarks/m4_extraction/M4_04B3Y_FRESH_VALIDATION_V3_SEAL_RESULT.yaml
benchmarks/m4_extraction/M4_EVALUATION_PROTOCOL_SNAPSHOT_V2.yaml
docs/research/m4/M4_ANNOTATION_CONVENTIONS_V2.md
docs/research/m4/M4_ANNOTATION_CONVENTIONS_V4.md
docs/research/m4/M4_FRESH_VALIDATION_V2_PROTOCOL.md
docs/research/m4/M4_FRESH_VALIDATION_V3_PROTOCOL.md
docs/research/m4/M4_FV3_LOCKED_RUN_PROTOCOL.md
schemas/canonical_story/canonical_story_v0.schema.json
schemas/canonical_story/predicate_registry_v0.yaml
schemas/story_extraction/story_extraction_batch_v0.schema.json
schemas/story_extraction/story_extraction_draft_v1.schema.json
schemas/story_extraction/story_extraction_draft_v1_1.schema.json
tools/canonical_story/conformance_v0.py
tools/story_extraction/check_annotation_conventions_v1.py
tools/story_extraction/check_annotation_conventions_v2.py
tools/story_extraction/check_annotation_conventions_v3.py
tools/story_extraction/diagnose_m4_04b3i_fv1_v1.py
tools/story_extraction/diagnose_m4_p4_dev_v1.py
tools/story_extraction/draft_compiler_v1.py
tools/story_extraction/draft_compiler_v1_1.py
tools/story_extraction/draft_coverage_v1.py
tools/story_extraction/draft_date_anchor_v1.py
tools/story_extraction/draft_mention_anchoring_v1.py
tools/story_extraction/draft_mention_evidence_v1.py
tools/story_extraction/draft_quote_resolution_v1.py
tools/story_extraction/draft_sentence_evidence_v1.py
tools/story_extraction/draft_transfer_bounds_v1.py
tools/story_extraction/draft_vocabulary_guard_v1.py
tools/story_extraction/durable_research_executor_v1.py
tools/story_extraction/evaluate_extraction_guarded_v1.py
tools/story_extraction/evaluate_extraction_v0.py
tools/story_extraction/evaluate_m4_04b2r_dev_v2.py
tools/story_extraction/extraction_contract_guard_v1.py
tools/story_extraction/extraction_contract_v0.py
tools/story_extraction/fresh_validation_seal_v1.py
tools/story_extraction/gemini_errors_v1.py
tools/story_extraction/gemini_key_pool_v1.py
tools/story_extraction/gemini_resilience_v1.py
tools/story_extraction/gemini_resilience_v1_1.py
tools/story_extraction/gemini_transport_v1.py
tools/story_extraction/holdout_seal_v1.py
tools/story_extraction/m4_04b2_dev_protocol_v1.py
tools/story_extraction/m4_04b3b2_dev2_protocol_v1.py
tools/story_extraction/m4_04b3f_fv1_protocol_v1.py
tools/story_extraction/m4_04b3n_fv2_protocol_v1.py
tools/story_extraction/m4_04b3z_fv3_protocol_v1.py
tools/story_extraction/prompts/story_extraction_draft_p3_repair_user_v1_1.txt
tools/story_extraction/prompts/story_extraction_draft_p3_system_v1_1.txt
tools/story_extraction/prompts/story_extraction_draft_p3_user_v1_1.txt
tools/story_extraction/prompts/story_extraction_draft_p4r6_system_v1_1.txt
tools/story_extraction/prompts/story_extraction_draft_p4r8_system_v1_1.txt
tools/story_extraction/run_gemini_resilience_smoke_v1_1.py
tools/story_extraction/run_m4_04b2_dev_predictions_v1.py
tools/story_extraction/run_m4_04b3c_dev2_predictions_v1.py
tools/story_extraction/run_m4_04b3g_fv1_predictions_v1.py
tools/story_extraction/run_m4_04b3o_fv2_predictions_v1.py
tools/story_extraction/run_m4_04b3z_fv3_predictions_v1.py
tools/story_extraction/run_m4_p4_dev_v1.py
tools/story_extraction/score_m4_04b3h_fv1_v1.py
tools/story_extraction/score_m4_04b3p_fv2_v1.py
tools/story_extraction/score_m4_04b3z_fv3_v1.py
tools/story_ingestion/light_novel_adapter_v0.py
```
