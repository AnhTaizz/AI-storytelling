"""Tests for the evaluation rules calibrated on real-source development cases (M4-02).

The rules were decided on private real-source cases; these tests pin each one on
synthetic text so they stay public and deterministic. No model, API or network.
"""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture_builder as fx  # noqa: E402
from fixture_builder import E, P, S, T, TOK, V, OPEN, POL, ROLE  # noqa: E402
from tools.story_extraction import evaluate_extraction_v0 as evaluator  # noqa: E402

REAL = {"mode": "REAL_SOURCE", "gold_completeness": "UNCERTAIN"}


def pair(text, function, variant="gold", gold_variant="gold"):
    """(ingestion, base, gold batch, predicted batch) for a custom case function."""
    ingestion, base = fx.ingest_text(text)
    gold = fx.Builder(ingestion, base, prefix="g", method="HUMAN_ANNOTATION")
    function(gold, gold_variant)
    predicted = fx.Builder(ingestion, base, prefix="auto", method="AUTOMATED_EXTRACTION")
    function(predicted, variant)
    return ingestion, base, gold.batch(), predicted.batch()


def score(text, function, variant="gold", gold_variant="gold", **spec):
    ingestion, base, gold, predicted = pair(text, function, variant, gold_variant)
    return evaluator.evaluate_case(base, gold, predicted, ingestion=ingestion, case_spec=spec or None)


def catalogue(case_id, variant="gold", **spec):
    text, function = fx.CASES[case_id]
    return score(text, function, variant, **spec)


# ------------------------------------------------------------------------------------- custom cases

def state_history(b, variant):
    """One proposition asserted over two intervals: held, given away, held again."""
    mira = b.named(1, "Mira")
    lantern = b.named(1, "the lantern", kind="OBJECT")
    give, t_give = b.event("TRANSFER")
    back, t_back = b.event("TRANSFER")
    b.occurred(give, 2)
    b.occurred(back, 3)
    holds = b.prop("Possesses", holder=E(mira), item=E(lantern))
    first = {"start": {"kind": "OPEN"}, "end": b.bound(t_give, [[b.ev(2)]])}
    second = {"start": b.bound(t_back, [[b.ev(3)]]), "end": {"kind": "OPEN"}}
    if variant == "second_interval_missing":
        b.claim(holds, [[b.ev(1)]], validity=first)
    elif variant == "swapped_order":
        b.claim(holds, [[b.ev(3)]], validity=second)
        b.claim(holds, [[b.ev(1)]], validity=first)
    else:
        b.claim(holds, [[b.ev(1)]], validity=first)
        b.claim(holds, [[b.ev(3)]], validity=second)


STATE_HISTORY = ("Mira held the lantern.\n\nShe gave it to Joren.\n\nJoren handed it back to her.", state_history)


def bound_only_referents(b, variant):
    """A state bounded by an event that has no assertion of its own, and by a named time."""
    mira = b.named(1, "Mira")
    start_event, t_start = b.event()
    named = b._id("t")
    b.records["temporal_anchors"].append({"id": named, "anchor_kind": "NAMED_TIME"})
    end = {"kind": "OPEN"} if variant == "end_missing" else b.bound(named, [[b.ev(2, role="RETROSPECTIVE")]])
    b.claim(b.prop("PhysicalCondition", entity=E(mira), condition=S("feverish")), [[b.ev(1, role="NARRATION_SUMMARY")]],
            validity={"start": b.bound(t_start, [[b.ev(1, role="NARRATION_SUMMARY")]]), "end": end})


BOUND_ONLY = ("Mira woke with a fever.\n\nBy the next morning she was well again.", bound_only_referents)


def placeholder_content(b, variant):
    joren = b.named(1, "Joren")
    hidden = b._id("p")
    b.records["propositions"].append({"id": hidden, "placeholder": True})
    b.claim(b.prop("Attitude", holder=E(joren), attitude=TOK("attitude_kind", "SUSPECTS"), content=P(hidden),
                   content_polarity=POL()), [[b.ev(1, role="NARRATION_SUMMARY")]], validity=OPEN)


PLACEHOLDER = ("Joren suspected that something was being kept from him.", placeholder_content)


def unmentioned_entities(b, variant):
    """Two same-kind entities with no mention at all: only their roles tell them apart."""
    giver, taker = b.entity(), b.entity()
    if variant == "roles_swapped":
        giver, taker = taker, giver
    item = b.entity("OBJECT")
    event, _ = b.event("TRANSFER")
    b.occurred(event, 1)
    for entity, role in ((giver, "SOURCE"), (taker, "RECIPIENT"), (item, "THEME")):
        b.claim(b.prop("Participates", event=V(event), participant=E(entity), role=ROLE(role)), [[b.ev(1)]])
    b.claim(b.prop("Owns", owner=E(giver), item=E(item)), [[b.ev(2, role="NARRATION_SUMMARY")]], validity=OPEN)


UNMENTIONED = ("One of them passed the parcel to the other.\n\nIt had belonged to the one who gave it.", unmentioned_entities)


def identity_forms(b, variant):
    """The same understanding as one entity with two mentions, or as two entities joined by SameAs."""
    mira = b.named(1, "Mira")
    if variant == "one_entity":
        b.named(2, "The captain", entity=mira)
    else:
        captain = b.named(2, "The captain")
        if variant == "split_with_same_as":
            b.claim(b.prop("SameAs", first=E(captain), second=E(mira)), [[b.ev(2)]])


IDENTITY = ("Mira opened the gate.\n\nThe captain, as everyone called Mira, smiled.", identity_forms)


def extra_detail(b, variant):
    event, _ = b.event()
    b.occurred(event, 1)
    if variant in ("extra_manner", "extra_cause"):
        other, _ = b.event()
        if variant == "extra_manner":
            b.claim(b.prop("Manner", event=V(event), manner=S("slowly")), [[b.ev(1)]])
        else:
            b.claim(b.prop("Causes", cause=V(event), effect=V(other)), [[b.ev(1)]], status="ENTAILED")


EXTRA = ("The gate opened at dawn.", extra_detail)


class TestSpanContainmentRule(unittest.TestCase):
    """Q1: a predicted span is accepted when it contains the gold span inside the same segment."""

    def test_wider_span_in_the_same_segment_is_accepted(self):
        def case(b, variant):
            event, _ = b.event()
            b.occurred(event, 1, None if variant == "whole_segment" else "the bell rang")
        text = "After a long silence the bell rang twice."
        self.assertTrue(score(text, case, "whole_segment")["full_canonical_case_success"])

    def test_narrower_span_than_gold_is_not_accepted(self):
        def case(b, variant):
            event, _ = b.event()
            b.occurred(event, 1, "the bell" if variant == "narrow" else "the bell rang twice")
        result = score("After a long silence the bell rang twice.", case, "narrow")
        self.assertIn("WRONG_EVIDENCE_SPAN", result["failure_codes"])

    def test_mixed_role_segment_requires_the_exact_span(self):
        result = catalogue("c22_mixed_segment_roles", "whole_segment_one_role")
        self.assertEqual(result["narrow_span_segments"], 1)            # detected from the gold roles
        self.assertIn("WRONG_EVIDENCE_SPAN", result["failure_codes"])

    def test_case_can_declare_a_narrow_segment(self):
        def case(b, variant):
            event, _ = b.event()
            b.occurred(event, 1, None if variant == "whole_segment" else "the bell rang")
        text = "After a long silence the bell rang twice."
        ingestion, base, gold, predicted = pair(text, case, "whole_segment")
        segment = base["source_segments"][0]["id"]
        result = evaluator.evaluate_case(base, gold, predicted, ingestion=ingestion,
                                         case_spec={"narrow_span_segments": [segment]})
        self.assertIn("WRONG_EVIDENCE_SPAN", result["failure_codes"])

    def test_span_matches_function(self):
        gold = ("seg-a", 10, 20)
        self.assertTrue(evaluator.span_matches(("seg-a", 10, 20), gold))
        self.assertTrue(evaluator.span_matches(("seg-a", 0, 40), gold))
        self.assertFalse(evaluator.span_matches(("seg-a", 12, 20), gold))
        self.assertFalse(evaluator.span_matches(("seg-b", 0, 40), gold))
        self.assertFalse(evaluator.span_matches(("seg-a", 0, 40), gold, frozenset({"seg-a"})))


class TestAlternativeGroundings(unittest.TestCase):
    """Q9: any one accepted SUFFICIENT set grounds the assertion; partial evidence does not."""

    def case(self, b, variant):
        event, _ = b.event()
        sets = {"gold": [[b.ev(1)], [b.ev(2, role="RETROSPECTIVE")]], "first_only": [[b.ev(1)]],
                "second_only": [[b.ev(2, role="RETROSPECTIVE")]]}[variant]
        b.claim(b.prop("Occurred", event=V(event)), sets)

    TEXT = "The gate opened at dawn.\n\nEveryone remembered that the gate had opened at dawn."

    def test_either_independent_sufficient_set_is_enough(self):
        for variant in ("first_only", "second_only"):
            self.assertTrue(score(self.TEXT, self.case, variant)["full_canonical_case_success"], variant)

    def test_one_reference_of_a_two_reference_set_is_insufficient(self):
        result = catalogue("c24_partial_not_sufficient", "partial_marked_sufficient")
        self.assertIn("INSUFFICIENT_SUPPORT_MARKED_SUFFICIENT", result["failure_codes"])


class TestStateHistoryAndBounds(unittest.TestCase):
    def test_same_proposition_over_two_intervals_is_matched_by_validity(self):
        for variant in ("gold", "swapped_order"):
            result = score(*STATE_HISTORY, variant)
            self.assertTrue(result["full_canonical_case_success"], result["failures"])
            self.assertNotIn("DUPLICATE_ASSERTION", result["failure_codes"])

    def test_missing_interval_is_a_missed_assertion(self):
        result = score(*STATE_HISTORY, "second_interval_missing")
        self.assertIn("MISSED_REQUIRED_ASSERTION", result["failure_codes"])

    def test_event_named_only_by_a_bound_and_named_time_anchor_are_aligned(self):
        result = score(*BOUND_ONLY)
        self.assertTrue(result["full_canonical_case_success"], result["failures"])
        self.assertIn("WRONG_VALIDITY_BOUND", score(*BOUND_ONLY, "end_missing")["failure_codes"])

    def test_placeholder_proposition_is_aligned_by_its_role(self):
        self.assertTrue(score(*PLACEHOLDER)["full_canonical_case_success"])


class TestEntitiesWithoutMentions(unittest.TestCase):
    """Q2: entities with no mention are aligned by the roles they play, never by labels."""

    def test_structural_alignment(self):
        result = score(*UNMENTIONED)
        self.assertTrue(result["full_canonical_case_success"], result["failures"])
        self.assertEqual(result["alignment_ambiguities"], [])

    def test_swapped_roles_are_the_same_understanding(self):
        # Entities carry no identity of their own here: swapping which record is giver and taker
        # in the WHOLE prediction describes the same situation.
        self.assertTrue(score(*UNMENTIONED, "roles_swapped")["full_canonical_case_success"])

    def test_labels_are_not_used(self):
        ingestion, base, gold, predicted = pair(*UNMENTIONED)
        for index, entity in enumerate(predicted["candidate_records"]["entities"]):
            entity["editorial_label"] = f"misleading label {index}"
        for entity in reversed(gold["candidate_records"]["entities"]):
            entity["editorial_label"] = "misleading label 0"
        result = evaluator.evaluate_case(base, gold, predicted, ingestion=ingestion)
        self.assertTrue(result["full_canonical_case_success"], result["failures"])


class TestIdentityRepresentation(unittest.TestCase):
    """Q3: identity classes are formed from SameAs assertions inside the scope."""

    def test_split_entities_joined_by_same_as_equal_one_entity(self):
        result = score(*IDENTITY, variant="split_with_same_as", gold_variant="one_entity")
        self.assertTrue(result["full_canonical_case_success"], result["failures"])
        self.assertEqual(result["counts"]["equivalent_representation"], 1)
        self.assertEqual(result["metrics"]["unsupported_assertion_count"], 0)

    def test_split_entities_without_same_as_are_a_different_information_state(self):
        result = score(*IDENTITY, variant="split_unresolved", gold_variant="one_entity")
        self.assertFalse(result["full_canonical_case_success"])
        self.assertIn("MISSING_ENTITY_RESOLUTION", result["failure_codes"])

    def test_explicit_gold_resolution_is_not_recovered_by_a_merged_entity(self):
        # Gold records "unknown, then identified" (two entities + SameAs). One merged entity loses that history.
        result = score(*IDENTITY, variant="one_entity", gold_variant="split_with_same_as")
        self.assertFalse(result["full_canonical_case_success"])
        self.assertEqual(result["failure_codes"], ["MISSED_REQUIRED_ASSERTION"])
        self.assertEqual(result["metrics"]["referent_resolution_accuracy"], 1.0)


class TestLiteralVariants(unittest.TestCase):
    """Q6: exact literal matching, plus variants a case declares explicitly."""

    def case(self, b, variant):
        mira, joren = b.named(1, "Mira"), b.named(1, "Joren")
        b.claim(b.prop("EmotionToward", holder=E(mira), target=E(joren),
                       emotion=S("rage" if variant == "other_word" else "anger")),
                [[b.ev(1, role="NARRATION_SUMMARY")]], validity=OPEN)

    TEXT = "Mira was furious at Joren."

    def test_other_wording_does_not_match_by_default(self):
        result = score(self.TEXT, self.case, "other_word")
        self.assertIn("MISSED_REQUIRED_ASSERTION", result["failure_codes"])

    def test_declared_variant_matches(self):
        variants = [{"predicate": "EmotionToward", "argument": "emotion", "values": ["anger", "rage"]}]
        self.assertTrue(score(self.TEXT, self.case, "other_word", literal_variants=variants)["full_canonical_case_success"])

    def test_variant_is_scoped_to_predicate_and_argument(self):
        variants = [{"predicate": "PhysicalCondition", "argument": "condition", "values": ["anger", "rage"]}]
        self.assertFalse(score(self.TEXT, self.case, "other_word", literal_variants=variants)["full_canonical_case_success"])


class TestAdjudicationOfUnmatchedPredictions(unittest.TestCase):
    """Q7, Q8: on real-source cases 'not in gold' is not 'hallucinated'."""

    def unmatched(self, variant="extra_manner", **spec):
        return score(*EXTRA, variant, **spec)

    def key(self, variant="extra_manner"):
        return self.unmatched(variant, **REAL)["unmatched_predictions"][0]["content_key"]

    def test_unmatched_prediction_is_pending_on_incomplete_gold(self):
        result = self.unmatched(**REAL)
        self.assertEqual(result["case_outcome"], "PENDING_ADJUDICATION")
        self.assertIsNone(result["full_canonical_case_success"])
        self.assertEqual(result["unmatched_predictions"][0]["state"], "GOLD_UNMATCHED_PENDING_ADJUDICATION")
        self.assertEqual(result["metrics"]["gold_unmatched_pending_adjudication"], 1)
        for metric in ("assertion_precision", "unsupported_assertion_rate", "unsupported_assertion_count"):
            self.assertIsNone(result["metrics"][metric], metric)       # not reportable before adjudication
        self.assertEqual(result["metrics"]["assertion_recall"], 1.0)
        self.assertEqual(result["failures"], [])

    def test_pending_does_not_hide_a_real_failure(self):
        def case(b, variant):
            event, _ = b.event()
            if variant != "missing":
                b.occurred(event, 1)
            if variant == "missing":
                b.claim(b.prop("Manner", event=V(event), manner=S("slowly")), [[b.ev(1)]])
        result = score("The gate opened at dawn.", case, "missing", **REAL)
        self.assertEqual(result["case_outcome"], "FAIL")
        self.assertEqual(result["metrics"]["gold_unmatched_pending_adjudication"], 1)

    def test_adjudication_states(self):
        key = self.key()
        expected = {"VALID_ADDITIONAL_ASSERTION": "valid_additional", "OUT_OF_SCOPE_ASSERTION": "out_of_scope",
                    "EQUIVALENT_REPRESENTATION": "equivalent_representation"}
        for state, counter in expected.items():
            result = self.unmatched(adjudications=[{"content_key": key, "state": state}], **REAL)
            with self.subTest(state):
                self.assertEqual(result["case_outcome"], "SUCCESS")
                self.assertEqual(result["counts"][counter], 1)
                self.assertEqual(result["metrics"]["unsupported_assertion_count"], 0)
                self.assertEqual(result["metrics"]["assertion_precision"], 1.0)

    def test_materiality_follows_severity_not_the_code(self):
        key = self.key()
        outcomes = {}
        for severity in evaluator.SEVERITIES:
            result = self.unmatched(adjudications=[{"content_key": key, "state": "UNSUPPORTED_ASSERTION",
                                                    "severity": severity}], **REAL)
            outcomes[severity] = result["case_outcome"]
            self.assertEqual(result["metrics"]["unsupported_assertion_count"], 1)
            self.assertGreater(result["metrics"]["unsupported_assertion_rate"], 0)
        self.assertEqual(outcomes, {"CRITICAL": "FAIL", "HIGH": "FAIL", "MEDIUM": "SUCCESS", "LOW": "SUCCESS"})

    def test_mechanical_hint_is_kept_and_can_be_relabelled(self):
        pending = self.unmatched("extra_cause", **REAL)
        self.assertEqual(pending["unmatched_predictions"][0]["mechanical_hint"], "INVENTED_CAUSALITY")
        key = pending["unmatched_predictions"][0]["content_key"]
        confirmed = self.unmatched("extra_cause", adjudications=[
            {"content_key": key, "state": "UNSUPPORTED_ASSERTION", "severity": "HIGH"}], **REAL)
        self.assertEqual(confirmed["failure_codes"], ["INVENTED_CAUSALITY"])
        relabelled = self.unmatched("extra_cause", adjudications=[
            {"content_key": key, "state": "UNSUPPORTED_ASSERTION", "severity": "HIGH",
             "failure_code": "WRONG_EVENT_GRANULARITY"}], **REAL)
        self.assertEqual(relabelled["failure_codes"], ["WRONG_EVENT_GRANULARITY"])
        self.assertIn("WRONG_EVENT_GRANULARITY", evaluator.FAILURE_CODES)

    def test_complete_gold_reads_unmatched_as_unsupported(self):
        result = self.unmatched(mode="REAL_SOURCE", gold_completeness="COMPLETE_FOR_PROFILE")
        self.assertEqual(result["case_outcome"], "FAIL")
        self.assertEqual(result["unmatched_predictions"][0]["severity"], "UNRATED")
        rated = self.unmatched(mode="REAL_SOURCE", gold_completeness="COMPLETE_FOR_PROFILE", adjudications=[
            {"content_key": self.key(), "state": "UNSUPPORTED_ASSERTION", "severity": "LOW"}])
        self.assertEqual(rated["case_outcome"], "SUCCESS")

    def test_synthetic_mode_is_unchanged(self):
        result = self.unmatched()
        self.assertEqual(result["mode"], "SYNTHETIC_COMPLETE")
        self.assertFalse(result["full_canonical_case_success"])
        self.assertEqual(result["failure_codes"], ["UNSUPPORTED_ASSERTION"])

    def test_invalid_case_specs_are_refused(self):
        for spec in ({"mode": "GUESS"}, {"gold_completeness": "MOSTLY"},
                     {"adjudications": [{"content_key": "x", "state": "HALLUCINATION"}]},
                     {"adjudications": [{"content_key": "x", "state": "UNSUPPORTED_ASSERTION"}]}):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                self.unmatched(**spec)

    def test_aggregate_does_not_report_rates_while_cases_are_pending(self):
        pending, clean = self.unmatched(**REAL), score(*EXTRA, **REAL)
        summary = evaluator.aggregate([pending, clean])
        self.assertEqual(summary["cases_pending_adjudication"], 1)
        self.assertIsNone(summary["full_canonical_case_success_rate"])
        self.assertIsNone(summary["unsupported_assertion_rate"])
        self.assertEqual(summary["assertion_recall"], 1.0)
        self.assertEqual(evaluator.aggregate([clean])["full_canonical_case_success_rate"], 1.0)


class TestRequiredAndAcceptable(unittest.TestCase):
    def gold_and_optional(self):
        text, function = fx.CASES["c06_participant"]
        ingestion, base, gold, predicted = pair(text, function)
        props = {p["id"]: p for p in gold["candidate_records"]["propositions"]}
        optional = [a["id"] for a in gold["candidate_records"]["assertions"]
                    if props[a["proposition_id"]]["predicate"] == "Participates"]
        return ingestion, base, gold, predicted, optional

    def test_optional_assertion_adds_no_recall_denominator_and_is_not_unsupported(self):
        ingestion, base, gold, predicted, optional = self.gold_and_optional()
        result = evaluator.evaluate_case(base, gold, predicted, ingestion=ingestion,
                                         case_spec={**REAL, "acceptable_assertion_ids": optional})
        self.assertEqual(result["case_outcome"], "SUCCESS")
        self.assertEqual(result["counts"]["gold_acceptable"], 1)
        self.assertEqual(result["counts"]["gold_required"], len(gold["candidate_records"]["assertions"]) - 1)
        self.assertEqual(result["unmatched_predictions"], [])

    def test_optional_assertion_must_still_be_grounded_when_predicted(self):
        ingestion, base, gold, predicted, optional = self.gold_and_optional()
        props = {p["id"]: p for p in predicted["candidate_records"]["propositions"]}
        target = next(a for a in predicted["candidate_records"]["assertions"]
                      if props[a["proposition_id"]]["predicate"] == "Participates")
        mention_ref = predicted["candidate_records"]["mentions"][0]["evidence_ref_id"]
        target["support"]["evidence_sets"][0]["evidence_ref_ids"] = [mention_ref]     # a name is not the event
        result = evaluator.evaluate_case(base, gold, predicted, ingestion=ingestion,
                                         case_spec={**REAL, "acceptable_assertion_ids": optional})
        self.assertEqual(result["case_outcome"], "FAIL")
        self.assertIn("WRONG_EVIDENCE_SPAN", result["failure_codes"])


class TestCatalogueStillPasses(unittest.TestCase):
    def test_every_synthetic_case_succeeds_in_real_source_mode_too(self):
        for case_id in fx.CASES:
            result = catalogue(case_id, **REAL)
            with self.subTest(case_id):
                self.assertEqual(result["case_outcome"], "SUCCESS", result["failures"])
                self.assertEqual(result["alignment_ambiguities"], [])


if __name__ == "__main__":
    unittest.main()
