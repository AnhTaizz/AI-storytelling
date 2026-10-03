"""Synthetic, offline compiler tests; no DEV or holdout content is embedded."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixture_builder as fx

from tools.story_extraction.draft_compiler_v1 import (
    COLLECTIONS, DraftCompilerContext, DraftCompilationError,
    compile_story_extraction_draft_v1, prepare_story_extraction_draft_v1, validate_draft_v1,
)
from tools.story_extraction.draft_coverage_v1 import (
    canonical_gold_to_draft_v1, canonical_representation_signature,
)
from tools.story_extraction.extraction_contract_v0 import document_sha256
from tools.story_extraction.extraction_contract_guard_v1 import validate_batch_guarded


def context(ingestion, base, gold):
    s = gold["scope"]
    return DraftCompilerContext(base, s["passage_inputs"], s["as_of_position"], s["profile_id"],
                                "synthetic-compiler", "v1", "synthetic-run", ingestion)


def fixture(name="c06_participant"):
    ingestion, base, gold = fx.build(name)
    ctx = context(ingestion, base, gold)
    draft, mapping = canonical_gold_to_draft_v1(gold, ctx)
    return ctx, draft, gold, mapping


class DraftCompilerTests(unittest.TestCase):
    def assert_rejected(self, draft, ctx, code):
        with self.assertRaises(DraftCompilationError) as raised:
            compile_story_extraction_draft_v1(draft, ctx)
        self.assertEqual(raised.exception.code, code)

    def test_all_26_authored_synthetic_graphs_round_trip(self):
        for name in fx.CASES:
            with self.subTest(name=name):
                ctx, draft, gold, mapping = fixture(name)
                compiled = compile_story_extraction_draft_v1(draft, ctx)
                reverse = {r["id"]: next(h for h in mapping.values() if r["id"].endswith("-" + h))
                           for coll in COLLECTIONS.values() for r in compiled["candidate_records"][coll]}
                self.assertEqual(canonical_representation_signature(gold, mapping),
                                 canonical_representation_signature(compiled, reverse))
                self.assertTrue(validate_batch_guarded(compiled, ctx.base_document, ctx.ingestion)["pass"])

    def test_deterministic_and_no_input_mutation(self):
        ctx, draft, _, _ = fixture()
        before, base_before = deepcopy(draft), deepcopy(ctx.base_document)
        first = compile_story_extraction_draft_v1(draft, ctx)
        for field in COLLECTIONS:
            draft[field].reverse()
        self.assertEqual(first, compile_story_extraction_draft_v1(draft, ctx))
        for field in COLLECTIONS:
            draft[field].reverse()
        self.assertEqual(before, draft)
        self.assertEqual(base_before, ctx.base_document)

    def test_owns_envelope_provenance_and_review(self):
        ctx, draft, _, _ = fixture()
        batch = compile_story_extraction_draft_v1(draft, ctx)
        self.assertEqual(batch["base_canonical_identity"]["base_document_sha256"], document_sha256(ctx.base_document))
        self.assertEqual(batch["scope"]["passage_inputs"], ctx.passage_inputs)
        self.assertEqual(batch["process"]["method"], "AUTOMATED_EXTRACTION")
        for assertion in batch["candidate_records"]["assertions"]:
            self.assertEqual(assertion["review"], {"state": "UNREVIEWED"})
        self.assertEqual(len(batch["candidate_records"]["extraction_provenance"]), 1)

    def test_rejects_model_metadata_injection(self):
        for key, value in (("process", {}), ("scope", {}), ("base_canonical_identity", {}),
                           ("source_sha256", "0" * 64), ("char_start", 1), ("candidate_records", {})):
            with self.subTest(key=key):
                ctx, draft, _, _ = fixture()
                draft[key] = value
                self.assert_rejected(draft, ctx, "DRAFT_SCHEMA_FAILURE")

    def test_rejects_review_and_provenance_and_record_ids(self):
        for key in ("review", "extraction_provenance_id", "id"):
            with self.subTest(key=key):
                ctx, draft, _, _ = fixture()
                draft["assertions"][0][key] = "self-confirmed"
                self.assert_rejected(draft, ctx, "DRAFT_SCHEMA_FAILURE")

    def test_rejects_canonical_id_as_argument_handle(self):
        ctx, draft, _, _ = fixture()
        draft["propositions"][0]["args"]["mention"]["handle"] = "canonical-opaque-id"
        self.assert_rejected(draft, ctx, "DRAFT_SCHEMA_FAILURE")

    def test_missing_exact_source(self):
        ctx, draft, _, _ = fixture()
        self.assert_rejected(draft, replace(ctx, ingestion=None), "EXACT_SOURCE_REQUIRED")

    def test_unknown_quote_no_normalization_and_private_safe_error(self):
        ctx, draft, _, _ = fixture()
        draft["evidence"][0]["quote"] = "MIRA"
        with self.assertRaises(DraftCompilationError) as raised:
            compile_story_extraction_draft_v1(draft, ctx)
        self.assertEqual(raised.exception.code, "QUOTE_NOT_FOUND")
        self.assertNotIn("MIRA", str(raised.exception))

    def test_unknown_passage(self):
        ctx, draft, _, _ = fixture()
        draft["evidence"][0]["passage_handle"] = "P999"
        self.assert_rejected(draft, ctx, "UNKNOWN_PASSAGE_HANDLE")

    def test_context_only_not_evidence(self):
        ctx, draft, _, _ = fixture()
        inputs = deepcopy(ctx.passage_inputs)
        inputs[0]["use"] = "CONTEXT_ONLY"
        self.assert_rejected(draft, replace(ctx, passage_inputs=inputs), "CONTEXT_ONLY_EVIDENCE")

    def test_partial_passage_does_not_match_outside_window(self):
        ctx, draft, _, _ = fixture()
        ref = ctx.ingestion.passage_ref(ctx.passage_inputs[0]["passage_ref"]["segment_id"], 0, 4)
        draft["evidence"][0]["quote"] = "gate"
        self.assert_rejected(draft, replace(ctx, passage_inputs=[{"use": "EVIDENCE_ELIGIBLE", "passage_ref": ref}]), "QUOTE_NOT_FOUND")

    def test_repeated_quote_requires_occurrence(self):
        ing, base = fx.ingest_text("Mira saw Mira.")
        b = fx.Builder(ing, base)
        b.ev(1, "Mira")
        ctx = context(ing, base, b.batch())
        draft, _ = canonical_gold_to_draft_v1(b.batch(), ctx)
        draft["evidence"][0].pop("occurrence")
        self.assert_rejected(draft, ctx, "AMBIGUOUS_QUOTE")
        draft["evidence"][0]["occurrence"] = 2
        out = compile_story_extraction_draft_v1(draft, ctx)
        span = out["candidate_records"]["evidence_refs"][0]["span"]
        self.assertEqual(span["char_start"], 9)
        draft["evidence"][0]["occurrence"] = 3
        self.assert_rejected(draft, ctx, "OCCURRENCE_OUT_OF_RANGE")

    def test_unicode_offsets_are_source_exact(self):
        ing, base = fx.ingest_text("😀 ミラは門を開けた。")
        b = fx.Builder(ing, base)
        b.named(1, "ミラ")
        ctx = context(ing, base, b.batch())
        draft, _ = canonical_gold_to_draft_v1(b.batch(), ctx)
        out = compile_story_extraction_draft_v1(draft, ctx)
        self.assertEqual(out["candidate_records"]["evidence_refs"][0]["span"]["char_start"], 2)

    def test_bool_is_not_occurrence(self):
        ctx, draft, _, _ = fixture()
        draft["evidence"][0]["occurrence"] = True
        self.assert_rejected(draft, ctx, "DRAFT_SCHEMA_FAILURE")

    def test_duplicate_handle(self):
        ctx, draft, _, _ = fixture()
        draft["entities"].append(deepcopy(draft["entities"][0]))
        self.assert_rejected(draft, ctx, "DUPLICATE_HANDLE")

    def test_dangling_handle(self):
        ctx, draft, _, _ = fixture()
        draft["propositions"][0]["args"]["entity"]["handle"] = "E_NEW_999"
        self.assert_rejected(draft, ctx, "UNKNOWN_HANDLE")

    def test_wrong_handle_type(self):
        ctx, draft, _, _ = fixture()
        draft["propositions"][0]["args"]["entity"]["handle"] = "EVT1"
        self.assert_rejected(draft, ctx, "HANDLE_TYPE_MISMATCH")

    def test_rejects_unregistered_predicate_without_repair(self):
        ctx, draft, _, _ = fixture()
        draft["propositions"][0]["predicate"] = "InventedPredicate"
        self.assert_rejected(draft, ctx, "CANONICAL_CONFORMANCE_FAILURE")

    def test_stale_passage_context(self):
        ctx, draft, _, _ = fixture()
        inputs = deepcopy(ctx.passage_inputs)
        inputs[0]["passage_ref"]["span"]["source_sha256"] = "0" * 64
        self.assert_rejected(draft, replace(ctx, passage_inputs=inputs), "INVALID_PASSAGE_INPUT")

    def test_as_of_boundary(self):
        ctx, draft, _, _ = fixture()
        self.assert_rejected(draft, replace(ctx, as_of_position={"stream_id": ctx.as_of_position["stream_id"], "key": [0]}), "INVALID_PASSAGE_INPUT")

    def test_mention_direct_quote_materializes_evidence_only(self):
        ctx, draft, _, _ = fixture("c01_named_character")
        draft = {"draft_version": draft["draft_version"], **{k: [] for k in COLLECTIONS}}
        draft["mentions"] = [{"handle": "M1", "passage_handle": "P1", "quote": "Mira", "role": "DEPICTION"}]
        result = compile_story_extraction_draft_v1(draft, ctx)["candidate_records"]
        self.assertEqual(len(result["mentions"]), 1)
        self.assertEqual(len(result["evidence_refs"]), 1)
        self.assertEqual(result["entities"], [])
        self.assertEqual(result["assertions"], [])

    def test_no_semantic_truth_decision_or_upgrade(self):
        ctx, draft, _, _ = fixture("c25_negated_event")
        occurrence = next(r for r in draft["propositions"] if r.get("predicate") == "Occurred")
        assertion = next(r for r in draft["assertions"] if r["proposition_handle"] == occurrence["handle"])
        assertion["polarity"] = "AFFIRMED"  # Semantically wrong for the invented text.
        output = compile_story_extraction_draft_v1(draft, ctx)
        self.assertEqual(next(a for a in output["candidate_records"]["assertions"]
                              if a["id"].endswith("-" + assertion["handle"]))["polarity"], "AFFIRMED")

    def test_existing_entity_handle_reuses_without_copying_record(self):
        ctx, draft, _, _ = fixture("c01_named_character")
        entity = deepcopy(ctx.base_document)
        entity["entities"].append({"id": "prior-entity", "kind": "CHARACTER"})
        ctx = replace(ctx, base_document=entity)
        draft["entities"] = []
        for prop in draft["propositions"]:
            for arg in prop["args"].values():
                if arg.get("handle") == "E_NEW_1":
                    arg["handle"] = "E_EXISTING_1"
        output = compile_story_extraction_draft_v1(draft, ctx)
        self.assertEqual(output["candidate_records"]["entities"], [])
        self.assertEqual(output["scope"]["prior_canonical_context"]["kind"], "BASE_DOCUMENT_RECORDS")

    def test_prepared_input_excludes_mechanical_metadata(self):
        ctx, _, _, _ = fixture()
        inp = prepare_story_extraction_draft_v1(ctx)
        self.assertEqual(inp["passages"][0]["handle"], "P1")
        self.assertEqual(set(inp["passages"][0]), {"handle", "use", "text"})
        self.assertNotIn("source_sha256", repr(inp))

    def test_run_namespace_changes_generated_ids(self):
        ctx, draft, _, _ = fixture()
        one = compile_story_extraction_draft_v1(draft, ctx)
        two = compile_story_extraction_draft_v1(draft, replace(ctx, run_id="other-run"))
        self.assertNotEqual(one["candidate_records"]["entities"][0]["id"], two["candidate_records"]["entities"][0]["id"])

    def test_prior_context_cannot_supply_new_direct_evidence(self):
        ctx, draft, gold, _ = fixture()
        prior = deepcopy(ctx.base_document)
        prior["evidence_refs"] = deepcopy(gold["candidate_records"]["evidence_refs"])
        ctx = replace(ctx, base_document=prior)
        draft["assertions"][0]["support"]["evidence_sets"][0]["evidence_handles"] = ["EV_EXISTING_1"]
        self.assert_rejected(draft, ctx, "PRIOR_CONTEXT_NOT_EVIDENCE")

    def test_named_anchor_placeholder_content_and_ambiguity_survive(self):
        ctx, draft, _, _ = fixture("c01_named_character")
        draft["anchors"] = [{"handle": "T1", "anchor_kind": "NAMED_TIME"}]
        draft["propositions"].append({"handle": "PROP99", "placeholder": True})
        draft["assertions"][0]["textual_ambiguity"] = {"alternative_proposition_handles": ["PROP99"]}
        output = compile_story_extraction_draft_v1(draft, ctx)["candidate_records"]
        self.assertEqual(output["temporal_anchors"][0]["anchor_kind"], "NAMED_TIME")
        self.assertTrue(next(p for p in output["propositions"] if p["id"].endswith("-PROP99"))["placeholder"])
        self.assertEqual(len(output["assertions"][0]["textual_ambiguity"]["alternative_proposition_ids"]), 1)

    def test_mention_evidence_conflict_fails(self):
        ctx, draft, _, _ = fixture("c01_named_character")
        draft["mentions"][0]["quote"] = "gate"
        self.assert_rejected(draft, ctx, "MENTION_EVIDENCE_MISMATCH")


if __name__ == "__main__":
    unittest.main()
