"""Signed information semantics (M2-05): Proposition + polarity for Conceals / Conveys / secrets.

Synthetic data only; no model, API or network.
"""
import unittest

import tests.canonical_story._dependencies  # noqa: F401  (fails loudly if dependencies are missing)
from tests.canonical_story.fixture_builder import (
    INVALID_CASES, VALID_CASES, Doc, E, P, POL, ROLE, SPOL, SUF, TOK, V, occurred_with,
)
from tools.canonical_story.conformance_v0 import validate_document
from tools.canonical_story.view_v0 import project_as_of

END = 999


def attitude(d, holder, kind, content, polarity, unit, **kw):
    return d.assertion(d.prop("Attitude", holder=E(holder), attitude=TOK("attitude_kind", kind),
                              content=P(content), content_polarity=POL(polarity)), sets=[SUF(d.ev(unit))], **kw)


def secret_doc(concealed="AFFIRMED", target_belief=None, target_unaware=None, canonical=None):
    """A holds and conceals (P, concealed) from B; optional B belief / unawareness / canonical P."""
    d = Doc("story-signed")
    d.entity("ent-a", "CHARACTER")
    d.entity("ent-b", "CHARACTER")
    p = d.prop("LocatedAt", thing=E(d.entity("ent-key", "OBJECT")), location=E(d.entity("ent-garden", "LOCATION")))
    attitude(d, "ent-a", "HOLDS_TRUE", p, concealed, 3)
    d.assertion(d.prop("Conceals", concealer=E("ent-a"), content=P(p), content_polarity=SPOL(concealed),
                       concealed_from=E("ent-b")), sets=[SUF(d.ev(3))])
    if target_belief:
        attitude(d, "ent-b", "HOLDS_TRUE", p, target_belief, 5)
    if target_unaware:
        attitude(d, "ent-b", "UNAWARE", p, target_unaware, 4)
    if canonical:
        d.assertion(p, polarity=canonical, sets=[SUF(d.ev(6, "NARRATION_SUMMARY"))])
    return d.build()


def secret_at(doc, unit=10):
    [secret] = project_as_of(doc, [unit, END])["secrets"]
    return secret


class TestSignedSecretLearning(unittest.TestCase):
    """Matrix items 1-4: only a matching signed belief counts as learning the secret."""

    def test_1_affirmed_secret_matching_belief_ends_it(self):
        s = secret_at(secret_doc("AFFIRMED", target_belief="AFFIRMED"))
        self.assertEqual(s["status"], "ENDED")
        self.assertTrue(s["target_learned_evidence"])

    def test_2_affirmed_secret_opposite_belief_does_not_end_it(self):
        s = secret_at(secret_doc("AFFIRMED", target_belief="NEGATED"))
        self.assertEqual(s["status"], "ACTIVE")
        self.assertEqual(s["target_learned_evidence"], [])
        self.assertTrue(s["target_opposite_belief_evidence"])

    def test_3_negated_secret_matching_belief_ends_it(self):
        self.assertEqual(secret_at(secret_doc("NEGATED", target_belief="NEGATED"))["status"], "ENDED")

    def test_4_negated_secret_opposite_belief_does_not_end_it(self):
        s = secret_at(secret_doc("NEGATED", target_belief="AFFIRMED"))
        self.assertEqual(s["status"], "ACTIVE")
        self.assertEqual(s["content_polarity"], "NEGATED")


class TestReaderSignedKnowledge(unittest.TestCase):
    """Matrix items 5-6 and Phase 9 cases 1-4."""

    def check(self, concealed, canonical, signed_status, knows_signed, knows_resolution):
        s = secret_at(secret_doc(concealed, canonical=canonical))
        self.assertEqual(s["reader_signed_content_status"], signed_status)
        self.assertEqual(s["reader_knows_signed_content"], knows_signed)
        self.assertEqual(s["reader_knows_content_resolution"], knows_resolution)

    def test_case1_affirmed_secret_affirmed_truth(self):
        self.check("AFFIRMED", "AFFIRMED", "MATCHES_CANONICAL", True, True)

    def test_case2_affirmed_secret_negated_truth(self):
        self.check("AFFIRMED", "NEGATED", "OPPOSES_CANONICAL", False, True)

    def test_case3_negated_secret_negated_truth(self):
        self.check("NEGATED", "NEGATED", "MATCHES_CANONICAL", True, True)

    def test_case4_unresolved_truth(self):
        self.check("AFFIRMED", None, "UNRESOLVED", False, False)

    def test_reader_knowledge_respects_as_of(self):
        doc = secret_doc("AFFIRMED", canonical="AFFIRMED")
        self.assertEqual(secret_at(doc, 5)["reader_signed_content_status"], "UNRESOLVED")
        self.assertEqual(secret_at(doc, 6)["reader_signed_content_status"], "MATCHES_CANONICAL")


class TestUnawarePolarity(unittest.TestCase):
    """V0 interpretation: attitudes target signed information, so UNAWARE is polarity-specific."""

    def test_matching_unaware_is_evidence(self):
        self.assertTrue(secret_at(secret_doc("AFFIRMED", target_unaware="AFFIRMED"))["target_unaware_evidence"])

    def test_opposite_unaware_is_not_evidence(self):
        s = secret_at(secret_doc("AFFIRMED", target_unaware="NEGATED"))
        self.assertEqual(s["target_unaware_evidence"], [])

    def test_missing_attitude_is_never_unawareness(self):
        s = secret_at(secret_doc("AFFIRMED"))
        self.assertEqual((s["target_unaware_evidence"], s["status"]), ([], "ACTIVE"))


class TestSameContentKeepsPolarity(unittest.TestCase):
    """Matrix item 7: resolution by SameContent never changes the signed polarity."""

    def build(self, target_belief):
        d = Doc("story-signed-placeholder")
        d.entity("ent-a", "CHARACTER")
        d.entity("ent-b", "CHARACTER")
        hidden = d.placeholder_prop("what A hides")
        real = d.prop("LocatedAt", thing=E(d.entity("ent-key", "OBJECT")), location=E(d.entity("ent-shed", "LOCATION")))
        attitude(d, "ent-a", "HOLDS_TRUE", hidden, "NEGATED", 2)
        d.assertion(d.prop("Conceals", concealer=E("ent-a"), content=P(hidden), content_polarity=SPOL("NEGATED"),
                           concealed_from=E("ent-b")), sets=[SUF(d.ev(2))])
        attitude(d, "ent-b", "HOLDS_TRUE", real, target_belief, 5)
        d.assertion(d.prop("SameContent", placeholder=P(hidden), concrete=P(real)), sets=[SUF(d.ev(7))])
        d.assertion(real, polarity="NEGATED", sets=[SUF(d.ev(8, "NARRATION_SUMMARY"))])
        return d.build()

    def test_resolution_matches_only_same_signed_content(self):
        opposite = self.build("AFFIRMED")
        self.assertEqual(secret_at(opposite, 6)["status"], "ACTIVE")
        s7 = secret_at(opposite, 7)
        self.assertEqual((s7["status"], s7["content_polarity"]), ("ACTIVE", "NEGATED"))
        self.assertTrue(s7["target_opposite_belief_evidence"])
        matching = self.build("NEGATED")
        self.assertEqual(secret_at(matching, 6)["status"], "ACTIVE")  # not yet linked to the placeholder
        self.assertEqual(secret_at(matching, 7)["status"], "ENDED")

    def test_reader_signed_status_through_resolution(self):
        doc = self.build("AFFIRMED")
        self.assertEqual(secret_at(doc, 7)["reader_signed_content_status"], "UNRESOLVED")
        self.assertEqual(secret_at(doc, 8)["reader_signed_content_status"], "MATCHES_CANONICAL")


class TestConveysPreservesPolarity(unittest.TestCase):
    """Matrix item 8 and Phase 6."""

    def build(self, conveyed, concluded):
        d = Doc("story-conveys")
        d.entity("ent-a", "CHARACTER")
        d.entity("ent-b", "CHARACTER")
        p = d.prop("LocatedAt", thing=E(d.entity("ent-key", "OBJECT")), location=E(d.entity("ent-garden", "LOCATION")))
        attitude(d, "ent-a", "HOLDS_TRUE", p, conveyed, 2)
        d.assertion(d.prop("Conceals", concealer=E("ent-a"), content=P(p), content_polarity=SPOL(conveyed),
                           concealed_from=E("ent-b")), sets=[SUF(d.ev(2))])
        tell = d.event("evt-tell", "REVEAL_TELL")
        occ, parts = occurred_with(d, tell, 6, [("ent-a", "SOURCE"), ("ent-b", "RECIPIENT")])
        conveys = d.assertion(d.prop("Conveys", event=V(tell), content=P(p), content_polarity=SPOL(conveyed)),
                              sets=[SUF(d.ev(6))])
        d.assertion(d.prop("Attitude", holder=E("ent-b"), attitude=TOK("attitude_kind", "HOLDS_TRUE"),
                           content=P(p), content_polarity=POL(concluded)), status="ENTAILED",
                    derivations=[("REVEAL_RESULT", [occ] + parts + [conveys])])
        return d.build()

    def test_reveal_preserving_negated_polarity_is_valid_and_ends_secret(self):
        doc = self.build("NEGATED", "NEGATED")
        self.assertTrue(validate_document(doc)["pass"])
        self.assertEqual(secret_at(doc, 5)["status"], "ACTIVE")
        self.assertEqual(secret_at(doc, 6)["status"], "ENDED")

    def test_reveal_flipping_polarity_is_rejected(self):
        report = validate_document(self.build("NEGATED", "AFFIRMED"))
        self.assertFalse(report["pass"])
        self.assertTrue(any("does not preserve the signed content" in i
                            for i in report["semantic"]["derivation_integrity"]["issues"]))

    def test_open_polarity_cannot_be_concealed_or_conveyed(self):
        build, layer, fragment = INVALID_CASES["neg_18_conceals_open_polarity.json"]
        report = validate_document(build())
        self.assertTrue(any(fragment in i for i in report["semantic"][layer]["issues"]))


class TestRegressions(unittest.TestCase):
    """Matrix item 9 and Phase 7."""

    def test_case_e_intended_behaviour_unchanged(self):
        doc = VALID_CASES["case_e_secret_and_reveals.json"]()
        statuses = {unit: secret_at(doc, unit)["status"] for unit in (3, 7, 14, 15)}
        self.assertEqual(statuses, {3: "ACTIVE", 7: "ACTIVE", 14: "ACTIVE", 15: "ENDED"})
        self.assertEqual(secret_at(doc, 7)["reader_signed_content_status"], "MATCHES_CANONICAL")

    def test_says_and_says_not(self):
        d = Doc("story-says")
        d.entity("ent-a", "CHARACTER")
        p = d.prop("LocatedAt", thing=E(d.entity("ent-key", "OBJECT")), location=E(d.entity("ent-garden", "LOCATION")))
        yes = d.assertion(d.prop("Says", speaker=E("ent-a"), content=P(p), content_polarity=POL()), sets=[SUF(d.ev(2))])
        no = d.assertion(d.prop("Says", speaker=E("ent-a"), content=P(p), content_polarity=POL("NEGATED")),
                         sets=[SUF(d.ev(3))])
        d.assertion(p, sets=[SUF(d.ev(4, "NARRATION_SUMMARY"))])
        doc = d.build()
        v3 = project_as_of(doc, [3, END])
        self.assertEqual(v3["canonical_commitments"][p]["status"], "UNCOMMITTED")
        self.assertEqual(len(v3["reported_claims"]["conflicts"]), 1)
        v4 = project_as_of(doc, [4, END])
        relations = {c["assertion_id"]: c["relation_to_canonical"] for c in v4["reported_claims"]["claims"]}
        self.assertEqual(relations, {yes: "CONSISTENT", no: "CONTRADICTED"})


if __name__ == "__main__":
    unittest.main()
