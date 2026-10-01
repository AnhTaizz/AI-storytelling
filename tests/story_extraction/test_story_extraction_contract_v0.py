"""Tests for the STORY_EXTRACTION/v0 batch contract, merge utility and evaluator skeleton.

Synthetic fixtures only. No extraction, model, API or network.
"""
import copy
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture_builder as fx  # noqa: E402
from tools.canonical_story.conformance_v0 import validate_document  # noqa: E402
from tools.story_extraction import evaluate_extraction_v0 as evaluator  # noqa: E402
from tools.story_extraction import extraction_contract_v0 as contract  # noqa: E402
from tools.story_ingestion import light_novel_adapter_v0 as adapter  # noqa: E402

VALID_VARIANTS = ["gold"]
# case id -> {variant: expected evaluator failure codes (subset that must appear)}
NEGATIVE_VARIANTS = {
    "c02_two_mentions_one_entity": {"split_entity": {"WRONG_ENTITY_RESOLUTION", "MISSING_ENTITY_RESOLUTION"}},
    "c04_later_same_as": {"no_resolution": {"MISSED_REQUIRED_ASSERTION"}},
    "c05_event_occurred": {"event_without_occurred": {"MISSED_REQUIRED_ASSERTION"}},
    "c06_participant": {"wrong_role": {"UNSUPPORTED_ASSERTION", "MISSED_REQUIRED_ASSERTION"}},
    "c12_suggested_emotion": {"overstated": {"EPISTEMIC_OVERSTATEMENT"}},
    "c13_self_report": {"suggested_leak": {"HOLDER_RELATIVE_TRUTH_LEAK"}},
    "c14_reported_event": {"truth_leak": {"HOLDER_RELATIVE_TRUTH_LEAK"}},
    "c16_belief": {"truth_leak": {"HOLDER_RELATIVE_TRUTH_LEAK"}},
    "c19_adjacency_no_causality": {"invented_causality": {"INVENTED_CAUSALITY"}},
    "c20_state_open_end": {"invented_end": {"WRONG_VALIDITY_BOUND"}},
    "c21_state_end_learned_later": {"missing_end": {"WRONG_VALIDITY_BOUND"}},
    "c22_mixed_segment_roles": {"whole_segment_one_role": {"WRONG_EVIDENCE_SPAN"},
                                "paratext_as_depiction": {"WRONG_EVIDENCE_ROLE"}},
    "c24_partial_not_sufficient": {"partial_marked_sufficient": {"INSUFFICIENT_SUPPORT_MARKED_SUFFICIENT"}},
    "c25_negated_event": {"wrong_polarity": {"WRONG_POLARITY"}},
}
STRUCTURALLY_INVALID_VARIANTS = {
    "c13_self_report": "explicit_leak",                 # INTERNAL_STATE gate of the frozen model
    "c26_duplicate_proposition": "duplicate_proposition",
}


def gold(case_id):
    return fx.build(case_id, "gold", prefix="g", method="HUMAN_ANNOTATION")


def prediction(case_id, variant="gold"):
    """An automated prediction with different opaque ids than the gold."""
    return fx.build(case_id, variant, prefix="auto", method="AUTOMATED_EXTRACTION")


def score(case_id, variant="gold"):
    ingestion, base, gold_batch = gold(case_id)
    _, _, predicted = prediction(case_id, variant)
    return evaluator.evaluate_case(base, gold_batch, predicted, ingestion=ingestion)


class TestSyntheticFixtures(unittest.TestCase):
    def test_there_are_26_cases(self):
        self.assertEqual(len(fx.CASES), 26)

    def test_every_gold_batch_is_valid_and_merges_to_a_conforming_document(self):
        for case_id in fx.CASES:
            ingestion, base, batch = gold(case_id)
            report = contract.validate_batch(batch, base, ingestion)
            with self.subTest(case_id):
                self.assertTrue(report["pass"], report["checks"])
                self.assertTrue(validate_document(contract.merge(batch, base))["pass"])
                self.assertTrue(report["source_text_verified"])

    def test_gold_is_agent_authored_draft_not_human_confirmed(self):
        for case_id in fx.CASES:
            _, _, batch = gold(case_id)
            self.assertEqual(batch["process"]["method"], "HUMAN_ANNOTATION")
            self.assertNotIn("human_review_record", batch["process"])
            for assertion in batch["candidate_records"]["assertions"]:
                self.assertEqual(assertion["review"], {"state": "UNREVIEWED"}, case_id)

    def test_base_is_an_unmodified_m3_source_layer(self):
        ingestion, base, batch = gold("c04_later_same_as")
        self.assertEqual(base, ingestion.canonical_skeleton())
        merged = contract.merge(batch, base)
        for name in ("story", "source_documents", "source_segments"):
            self.assertEqual(merged[name], base[name])

    def test_only_canonical_record_collections_are_emitted(self):
        _, base, batch = gold("c17_conceal_convey")
        self.assertEqual(set(batch["candidate_records"]), set(contract.CANDIDATE_COLLECTIONS))
        self.assertEqual(set(contract.merge(batch, base)), set(base))


class TestBatchValidation(unittest.TestCase):
    def setUp(self):
        self.ingestion, self.base, self.batch = prediction("c07_location")

    def codes(self, batch, base=None, ingestion="default"):
        report = contract.validate_batch(batch, base or self.base,
                                         self.ingestion if ingestion == "default" else ingestion)
        return report, contract.issue_codes(report)

    def test_valid_batch_and_deterministic_report(self):
        first, codes = self.codes(self.batch)
        second, _ = self.codes(copy.deepcopy(self.batch))
        self.assertEqual(codes, [])
        self.assertEqual(first, second)
        self.assertRegex(first["merged_document_sha256"], r"^[0-9a-f]{64}$")

    def test_merge_is_independent_of_candidate_order(self):
        shuffled = copy.deepcopy(self.batch)
        for records in shuffled["candidate_records"].values():
            records.reverse()
        self.assertEqual(contract.merge(shuffled, self.base), contract.merge(self.batch, self.base))

    def test_envelope_violations(self):
        mutations = {
            "wrong batch version": lambda b: b.update(batch_version="STORY_EXTRACTION_BATCH/v9"),
            "missing scope": lambda b: b.pop("scope"),
            "source layer smuggled in": lambda b: b["candidate_records"].update(source_segments=[]),
            "parallel semantic record": lambda b: b["candidate_records"].update(relationship_objects=[]),
            "missing collection": lambda b: b["candidate_records"].pop("mentions"),
            "unknown method": lambda b: b["process"].update(method="LLM_SAYS_SO"),
            "no passage input": lambda b: b["scope"].update(passage_inputs=[]),
        }
        for name, mutate in mutations.items():
            batch = copy.deepcopy(self.batch)
            mutate(batch)
            report, _ = self.codes(batch)
            with self.subTest(name):
                self.assertFalse(report["checks"]["envelope"]["pass"])
                self.assertFalse(report["pass"])

    def test_id_collisions_are_rejected(self):
        batch = copy.deepcopy(self.batch)
        batch["candidate_records"]["entities"][0]["id"] = self.base["source_segments"][0]["id"]
        self.assertIn("ID_COLLISION", self.codes(batch)[1])
        batch = copy.deepcopy(self.batch)
        batch["candidate_records"]["entities"].append(copy.deepcopy(batch["candidate_records"]["entities"][0]))
        self.assertIn("ID_COLLISION", self.codes(batch)[1])

    def test_dangling_references_are_rejected(self):
        batch = copy.deepcopy(self.batch)
        batch["candidate_records"]["assertions"][0]["proposition_id"] = "auto-p-missing"
        self.assertIn("reference_integrity", self.codes(batch)[1])
        batch = copy.deepcopy(self.batch)
        batch["candidate_records"]["evidence_refs"][0]["segment_id"] = "seg-does-not-exist"
        self.assertIn("DANGLING_REFERENCE", self.codes(batch)[1])

    def test_batch_must_match_the_base_document(self):
        _, other_base, _ = prediction("c08_possession")
        _, codes = self.codes(self.batch, base=other_base, ingestion=None)
        self.assertIn("BASE_IDENTITY_MISMATCH", codes)

    def test_automated_assertions_must_be_unreviewed(self):
        for review in ({"state": "CONFIRMED"}, {"state": "CONFIRMED", "reviewer_kind": "AUTOMATED"},
                       {"state": "UNREVIEWED", "reviewer_kind": "HUMAN"}):
            batch = copy.deepcopy(self.batch)
            batch["candidate_records"]["assertions"][0]["review"] = review
            with self.subTest(review=review):
                self.assertIn("SELF_CERTIFICATION", self.codes(batch)[1])

    def test_automated_provenance_must_match_the_process(self):
        batch = copy.deepcopy(self.batch)
        batch["candidate_records"]["extraction_provenance"][0]["method"] = "HUMAN_ANNOTATION"
        self.assertIn("PROVENANCE_METHOD_MISMATCH", self.codes(batch)[1])
        batch = copy.deepcopy(self.batch)
        batch["candidate_records"]["extraction_provenance"][0]["process_id"] = "someone-else"
        self.assertIn("PROVENANCE_PROCESS_MISMATCH", self.codes(batch)[1])

    def test_confidence_does_not_change_review_state_or_acceptance(self):
        batch = copy.deepcopy(self.batch)
        batch["candidate_records"]["extraction_provenance"][0]["confidence"] = {
            "meaning": "EXTRACTION_CONFIDENCE", "scale": "unit_interval", "value": 0.99}
        report, codes = self.codes(batch)
        self.assertEqual(codes, [])
        batch["candidate_records"]["assertions"][0]["review"] = {"state": "CONFIRMED"}
        self.assertIn("SELF_CERTIFICATION", self.codes(batch)[1])

    def test_human_confirmation_needs_a_recorded_human_review(self):
        ingestion, base, batch = gold("c07_location")
        batch["candidate_records"]["assertions"][0]["review"] = {"state": "CONFIRMED", "reviewer_kind": "HUMAN"}
        self.assertIn("UNATTESTED_REVIEW", contract.issue_codes(contract.validate_batch(batch, base, ingestion)))
        batch["process"]["human_review_record"] = "synthetic sign-off reference"
        self.assertTrue(contract.validate_batch(batch, base, ingestion)["pass"])

    def test_assertion_without_support_is_rejected_by_the_frozen_validator(self):
        batch = copy.deepcopy(self.batch)
        batch["candidate_records"]["assertions"][0]["support"] = {"evidence_sets": [], "derivations": []}
        self.assertIn("support_path_integrity", self.codes(batch)[1])

    def test_unregistered_derivation_rule_is_rejected(self):
        ingestion, base, batch = prediction("c12_suggested_emotion")
        for assertion in batch["candidate_records"]["assertions"]:
            for derivation in assertion["support"]["derivations"]:
                derivation["rule_id"] = "LLM_INFERENCE"
        self.assertIn("derivation_integrity", contract.issue_codes(contract.validate_batch(batch, base, ingestion)))

    def test_invented_epistemic_status_is_rejected(self):
        for status in ("REPORTED", "UNKNOWN", "LIKELY", "CERTAIN"):
            batch = copy.deepcopy(self.batch)
            batch["candidate_records"]["assertions"][0]["epistemic_status"] = status
            self.assertIn("STRUCTURAL", self.codes(batch)[1], status)


class TestEvidenceDiscipline(unittest.TestCase):
    def test_evidence_role_must_be_supplied_explicitly(self):
        ingestion, base, _ = gold("c05_event_occurred")
        ref = ingestion.passage_ref(ingestion.documents[0].segments[0]["id"])
        with self.assertRaises(TypeError):
            adapter.materialize_evidence_ref(ref)                         # there is no default role
        with self.assertRaises(adapter.IngestionError):
            adapter.materialize_evidence_ref(ref, None, "ev-x")
        _, _, batch = prediction("c05_event_occurred")
        del batch["candidate_records"]["evidence_refs"][0]["role"]
        self.assertIn("ROLE_REQUIRED", contract.issue_codes(contract.validate_batch(batch, base, ingestion)))

    def test_exact_span_is_required_and_checked_against_the_source(self):
        ingestion, base, batch = prediction("c05_event_occurred")
        broken = copy.deepcopy(batch)
        del broken["candidate_records"]["evidence_refs"][0]["span"]
        self.assertIn("SPAN_REQUIRED", contract.issue_codes(contract.validate_batch(broken, base, ingestion)))
        broken = copy.deepcopy(batch)
        broken["candidate_records"]["evidence_refs"][0]["span"]["char_end_exclusive"] += 500
        self.assertIn("SPAN_OUTSIDE_SEGMENT", contract.issue_codes(contract.validate_batch(broken, base, ingestion)))
        broken = copy.deepcopy(batch)
        broken["candidate_records"]["evidence_refs"][0]["span"]["span_text_sha256"] = "0" * 64
        self.assertIn("SPAN_MISMATCH", contract.issue_codes(contract.validate_batch(broken, base, ingestion)))
        self.assertTrue(contract.validate_batch(broken, base, None)["pass"])   # undetectable without the source

    def test_context_only_passages_cannot_become_evidence(self):
        text, function = fx.CASES["c23_multi_evidence_sufficient"]
        ingestion, base = fx.ingest_text(text)
        builder = fx.Builder(ingestion, base, prefix="auto", method="AUTOMATED_EXTRACTION", context_only={1})
        function(builder, "gold")
        report = contract.validate_batch(builder.batch(), base, ingestion)
        self.assertIn("EVIDENCE_OUTSIDE_SCOPE", contract.issue_codes(report))

    def test_evidence_after_the_as_of_boundary_is_rejected(self):
        text, function = fx.CASES["c21_state_end_learned_later"]
        ingestion, base = fx.ingest_text(text)
        builder = fx.Builder(ingestion, base, prefix="auto", method="AUTOMATED_EXTRACTION")
        function(builder, "gold")
        codes = contract.issue_codes(contract.validate_batch(builder.batch(as_of_segment=1), base, ingestion))
        self.assertIn("EVIDENCE_AFTER_AS_OF", codes)
        self.assertIn("EVIDENCE_OUTSIDE_SCOPE", codes)

    def test_mixed_segment_uses_role_specific_sub_spans(self):
        ingestion, base, batch = gold("c22_mixed_segment_roles")
        self.assertEqual(len(base["source_segments"]), 1)                 # heading + prose + author note
        refs = batch["candidate_records"]["evidence_refs"]
        self.assertEqual({r["segment_id"] for r in refs}, {base["source_segments"][0]["id"]})
        self.assertEqual(sorted(r["role"] for r in refs), ["DEPICTION", "PARATEXT"])
        texts = {r["role"]: ingestion.documents[0].text[r["span"]["char_start"]:r["span"]["char_end_exclusive"]]
                 for r in refs}
        self.assertEqual(texts, {"DEPICTION": "Mira opened the gate.", "PARATEXT": "Author note: thanks for reading."})

    def test_paratext_cannot_ground_a_story_assertion(self):
        text, _ = fx.CASES["c22_mixed_segment_roles"]
        ingestion, base = fx.ingest_text(text)
        b = fx.Builder(ingestion, base, prefix="auto", method="AUTOMATED_EXTRACTION")
        event, _ = b.event()
        b.claim(b.prop("Occurred", event=fx.V(event)), [[b.ev(1, "Author note: thanks for reading.", "PARATEXT")]])
        self.assertIn("evidence_set_integrity", contract.issue_codes(contract.validate_batch(b.batch(), base, ingestion)))


class TestPriorCanonicalContext(unittest.TestCase):
    def test_second_batch_builds_on_prior_records_without_rewriting_them(self):
        text, _ = fx.CASES["c04_later_same_as"]
        ingestion, base = fx.ingest_text(text)
        first = fx.Builder(ingestion, base, prefix="b1", method="AUTOMATED_EXTRACTION")
        stranger = first.named(1, "A hooded stranger", placeholder=True)
        batch_one = first.batch(as_of_segment=1)
        self.assertTrue(contract.validate_batch(batch_one, base, ingestion)["pass"])
        prior = contract.merge(batch_one, base)

        second = fx.Builder(ingestion, prior, prefix="b2", method="AUTOMATED_EXTRACTION")
        mira = second.named(2, "Mira")
        second.claim(second.prop("SameAs", first=fx.E(stranger), second=fx.E(mira)), [[second.ev(2)]])
        batch_two = second.batch()
        self.assertEqual(batch_two["scope"]["prior_canonical_context"], {"kind": "BASE_DOCUMENT_RECORDS"})
        report = contract.validate_batch(batch_two, prior, ingestion)
        self.assertTrue(report["pass"], report["checks"])
        merged = contract.merge(batch_two, prior)
        for name in contract.CANDIDATE_COLLECTIONS:                      # history is appended to, never rewritten
            self.assertEqual(merged[name][:len(prior[name])], prior[name])
        self.assertTrue(next(e for e in merged["entities"] if e["id"] == stranger)["placeholder"])

        batch_two["scope"]["prior_canonical_context"] = {"kind": "NONE"}
        self.assertIn("PRIOR_CONTEXT_MISDECLARED",
                      contract.issue_codes(contract.validate_batch(batch_two, prior, ingestion)))


class TestEvaluator(unittest.TestCase):
    def test_perfect_prediction_with_different_ids_succeeds_on_every_case(self):
        results = []
        for case_id in fx.CASES:
            _, _, gold_batch = gold(case_id)
            _, _, predicted = prediction(case_id)
            gold_ids = {r["id"] for records in gold_batch["candidate_records"].values() for r in records}
            pred_ids = {r["id"] for records in predicted["candidate_records"].values() for r in records}
            self.assertFalse(gold_ids & pred_ids, case_id)
            result = score(case_id)
            results.append(result)
            with self.subTest(case_id):
                self.assertTrue(result["full_canonical_case_success"], result["failures"])
                self.assertEqual(result["metrics"]["assertion_recall"], 1.0)
                self.assertEqual(result["metrics"]["assertion_precision"], 1.0)
                self.assertEqual(result["metrics"]["unsupported_assertion_count"], 0)
                self.assertEqual(result["metrics"]["evidence_grounding_recall"], 1.0)
        summary = evaluator.aggregate(results)
        self.assertEqual(summary["full_canonical_case_success_rate"], 1.0)
        self.assertEqual(summary["unsupported_assertion_rate"], 0.0)

    def test_argument_order_and_symmetric_argument_order_do_not_matter(self):
        ingestion, base, gold_batch = gold("c04_later_same_as")
        _, _, predicted = prediction("c04_later_same_as")
        for prop in predicted["candidate_records"]["propositions"]:
            prop["args"] = dict(reversed(list(prop["args"].items())))
            if prop["predicate"] == "SameAs":
                prop["args"]["first"], prop["args"]["second"] = prop["args"]["second"], prop["args"]["first"]
        result = evaluator.evaluate_case(base, gold_batch, predicted, ingestion=ingestion)
        self.assertTrue(result["full_canonical_case_success"], result["failures"])

    def test_negative_variants_fail_with_the_expected_codes(self):
        for case_id, variants in NEGATIVE_VARIANTS.items():
            for variant, expected in variants.items():
                result = score(case_id, variant)
                with self.subTest(case=case_id, variant=variant):
                    self.assertTrue(result["l0_structural_validity"], result["failures"])
                    self.assertFalse(result["full_canonical_case_success"])
                    self.assertLessEqual(expected, set(result["failure_codes"]), result["failures"])
                    self.assertLessEqual(set(result["failure_codes"]), set(evaluator.FAILURE_CODES))

    def test_structurally_invalid_predictions_fail_at_layer_0(self):
        for case_id, variant in STRUCTURALLY_INVALID_VARIANTS.items():
            result = score(case_id, variant)
            with self.subTest(case_id):
                self.assertFalse(result["l0_structural_validity"])
                self.assertEqual(result["failure_codes"], ["CANONICAL_CONFORMANCE_FAILURE"])
                self.assertFalse(result["full_canonical_case_success"])
                self.assertIsNone(result["metrics"])

    def test_holder_relative_content_is_not_canonical_truth(self):
        for case_id, variant in (("c13_self_report", "suggested_leak"), ("c14_reported_event", "truth_leak"),
                                 ("c16_belief", "truth_leak")):
            clean, leaked = score(case_id), score(case_id, variant)
            with self.subTest(case_id):
                self.assertEqual(clean["metrics"]["unsupported_assertion_count"], 0)
                self.assertEqual(leaked["metrics"]["unsupported_assertion_count"], 1)
                self.assertEqual(leaked["metrics"]["assertion_recall"], 1.0)      # nothing missed, one invented
                self.assertIn("HOLDER_RELATIVE_TRUTH_LEAK", leaked["failure_codes"])

    def test_event_record_alone_is_not_an_occurrence(self):
        _, base, gold_batch = gold("c14_reported_event")
        merged = contract.merge(gold_batch, base)
        self.assertEqual(len(merged["events"]), 2)                               # utterance + reported event
        occurred = [a for a in merged["assertions"]
                    if next(p for p in merged["propositions"] if p["id"] == a["proposition_id"])["predicate"]
                    == "Occurred"]
        self.assertEqual(len(occurred), 1)                                       # only the utterance occurred
        missing = score("c05_event_occurred", "event_without_occurred")
        self.assertEqual(missing["metrics"]["assertion_recall"], 0.0)

    def test_unsupported_assertions_are_separate_from_missing_ones(self):
        invented = score("c19_adjacency_no_causality", "invented_causality")
        self.assertEqual(invented["metrics"]["assertion_recall"], 1.0)
        self.assertGreater(invented["metrics"]["unsupported_assertion_rate"], 0)
        self.assertLess(invented["metrics"]["assertion_precision"], 1.0)
        missed = score("c04_later_same_as", "no_resolution")
        self.assertLess(missed["metrics"]["assertion_recall"], 1.0)
        self.assertEqual(missed["metrics"]["unsupported_assertion_count"], 0)

    def test_partial_evidence_marked_sufficient_breaks_grounding_not_matching(self):
        result = score("c24_partial_not_sufficient", "partial_marked_sufficient")
        self.assertEqual(result["metrics"]["assertion_recall"], 1.0)
        self.assertLess(result["metrics"]["evidence_grounding_recall"], 1.0)
        self.assertLess(result["metrics"]["evidence_grounding_precision"], 1.0)

    def test_metric_values_for_role_epistemic_and_resolution(self):
        self.assertLess(score("c22_mixed_segment_roles", "paratext_as_depiction")["metrics"]["evidence_role_accuracy"], 1.0)
        self.assertLess(score("c12_suggested_emotion", "overstated")["metrics"]["epistemic_accuracy"], 1.0)
        self.assertLess(score("c02_two_mentions_one_entity", "split_entity")["metrics"]["referent_resolution_accuracy"], 1.0)
        self.assertEqual(score("c02_two_mentions_one_entity")["metrics"]["referent_resolution_accuracy"], 1.0)

    def test_acceptable_optional_gold_assertions_are_not_required(self):
        ingestion, base, gold_batch = gold("c06_participant")
        _, _, predicted = prediction("c06_participant")
        gold_props = {p["id"]: p for p in gold_batch["candidate_records"]["propositions"]}
        optional = [a["id"] for a in gold_batch["candidate_records"]["assertions"]
                    if gold_props[a["proposition_id"]]["predicate"] == "Participates"]
        pred_props = {p["id"]: p for p in predicted["candidate_records"]["propositions"]}
        predicted["candidate_records"]["assertions"] = [
            a for a in predicted["candidate_records"]["assertions"]
            if pred_props[a["proposition_id"]]["predicate"] != "Participates"]
        strict = evaluator.evaluate_case(base, gold_batch, predicted, ingestion=ingestion)
        lenient = evaluator.evaluate_case(base, gold_batch, predicted, acceptable_gold_assertion_ids=optional,
                                          ingestion=ingestion)
        self.assertFalse(strict["full_canonical_case_success"])
        self.assertTrue(lenient["full_canonical_case_success"], lenient["failures"])

    def test_duplicate_assertion_is_reported_but_not_material(self):
        ingestion, base, gold_batch = gold("c05_event_occurred")
        _, _, predicted = prediction("c05_event_occurred")
        duplicate = copy.deepcopy(predicted["candidate_records"]["assertions"][0])
        duplicate["id"] = "auto-a-dup"
        for evidence_set in duplicate["support"]["evidence_sets"]:
            evidence_set["id"] = "auto-es-dup"
        predicted["candidate_records"]["assertions"].append(duplicate)
        result = evaluator.evaluate_case(base, gold_batch, predicted, ingestion=ingestion)
        self.assertIn("DUPLICATE_ASSERTION", result["failure_codes"])
        self.assertTrue(result["full_canonical_case_success"])

    def test_evaluation_does_not_mutate_review_state(self):
        ingestion, base, gold_batch = gold("c08_possession")
        _, _, predicted = prediction("c08_possession")
        before = copy.deepcopy(predicted)
        evaluator.evaluate_case(base, gold_batch, predicted, ingestion=ingestion)
        self.assertEqual(predicted, before)
        self.assertTrue(all(a["review"] == {"state": "UNREVIEWED"}
                            for a in predicted["candidate_records"]["assertions"]))

    def test_invalid_gold_is_refused(self):
        ingestion, base, gold_batch = gold("c05_event_occurred")
        gold_batch["candidate_records"]["assertions"][0]["proposition_id"] = "g-p-missing"
        with self.assertRaises(ValueError):
            evaluator.evaluate_case(base, gold_batch, prediction("c05_event_occurred")[2], ingestion=ingestion)


class TestNoExtractionOrModelInTooling(unittest.TestCase):
    def test_tools_contain_no_model_or_network_calls(self):
        for name in ("extraction_contract_v0.py", "evaluate_extraction_v0.py"):
            source = (REPO / "tools/story_extraction" / name).read_text(encoding="utf-8").lower()
            for word in ("import requests", "openai", "anthropic", "google.generativeai", "urllib.request",
                         "http://", "https://", "subprocess"):
                self.assertNotIn(word, source, f"{name}: {word}")


if __name__ == "__main__":
    unittest.main()
