"""Pre-freeze hardening (M2-07): registry v0.1, AddressesAs correction, proposition uniqueness.

Synthetic data only; no model, API or network.
"""
import unittest

import tests.canonical_story._dependencies  # noqa: F401  (fails loudly if dependencies are missing)
from tests.canonical_story.fixture_builder import (
    Doc, E, P, POL, ROLE, S, SPOL, SUF, TOK, V, occurred_with,
)
from tools.canonical_story.conformance_v0 import load_registry, proposition_signature, validate_document
from tools.canonical_story.view_v0 import project_as_of

END = 999
OPEN = {"start": {"kind": "OPEN"}, "end": {"kind": "OPEN"}}


def issues(doc, section="predicate_integrity"):
    return validate_document(doc)["semantic"][section]["issues"]


def base():
    d = Doc("story-hardening")
    d.entity("ent-a", "CHARACTER")
    d.entity("ent-b", "CHARACTER")
    d.entity("ent-item", "OBJECT")
    d.entity("ent-l1", "LOCATION")
    d.entity("ent-l2", "LOCATION")
    return d


class TestRegistryV01(unittest.TestCase):
    def setUp(self):
        self.reg = load_registry()

    def test_version_and_compatibility_are_explicit(self):
        self.assertEqual(self.reg["registry_version"], "predicate_registry/v0.1")
        self.assertEqual(self.reg["compatible_schema_versions"], ["canonical_story/v0"])

    def test_only_real_source_proven_predicates_were_promoted(self):
        promoted = {"PhysicalCondition", "EmotionToward", "Intends", "Owns", "Habitually"}
        self.assertTrue(promoted <= set(self.reg["predicates"]))
        self.assertNotIn("AddressesAsInSetting", self.reg["predicates"])
        self.assertNotIn("address_setting", self.reg["vocabularies"])
        for name in promoted:
            self.assertTrue(self.reg["predicates"][name]["stative"], name)
        self.assertEqual(self.reg["predicates"]["Owns"]["functional_on"], ["item"])
        for gated in ("EmotionToward", "Intends"):
            self.assertEqual(self.reg["predicates"][gated]["epistemic_gate"], "INTERNAL_STATE")

    def test_addresses_as_is_not_functional(self):
        self.assertNotIn("functional_on", self.reg["predicates"]["AddressesAs"])


class TestAddressesAsCorrection(unittest.TestCase):
    def test_coexisting_address_forms_raise_no_functional_diagnostic(self):
        d = base()
        for form, unit in (("FAMILY_NAME", 2), ("GIVEN_NAME", 5)):
            d.assertion(d.prop("AddressesAs", speaker=E("ent-a"), addressee=E("ent-b"), form=TOK("address_form", form)),
                        sets=[SUF(d.ev(unit))], validity=dict(OPEN))
        doc = d.build()
        self.assertTrue(validate_document(doc)["pass"])
        view = project_as_of(doc, [9, END])
        self.assertEqual([x for x in view["diagnostics"] if x.get("predicate") == "AddressesAs"], [])
        [rel] = view["relationships"]
        self.assertEqual([s["value"]["form"] for s in rel["stages"]], ["FAMILY_NAME", "GIVEN_NAME"])

    def test_functional_diagnostic_still_works_for_functional_predicates(self):
        d = base()
        d.assertion(d.prop("LocatedAt", thing=E("ent-item"), location=E("ent-l1")), sets=[SUF(d.ev(1))])
        d.assertion(d.prop("LocatedAt", thing=E("ent-item"), location=E("ent-l2")), sets=[SUF(d.ev(2))])
        codes = [x["code"] for x in project_as_of(d.build(), [9, END])["diagnostics"]]
        self.assertIn("POTENTIAL_FUNCTIONAL_CONFLICT", codes)


class TestPropositionUniqueness(unittest.TestCase):
    def test_1_exact_duplicate_is_rejected_and_names_both_ids(self):
        d = base()
        first = d.prop("LocatedAt", thing=E("ent-item"), location=E("ent-l1"))
        second = d.prop_new("LocatedAt", thing=E("ent-item"), location=E("ent-l1"))
        d.assertion(first, sets=[SUF(d.ev(1))])
        found = [i for i in issues(d.build()) if "duplicate concrete proposition content" in i]
        self.assertEqual(len(found), 1)
        self.assertIn(first, found[0])
        self.assertIn(second, found[0])

    def test_2_different_literal_is_allowed(self):
        d = base()
        d.assertion(d.prop("PhysicalCondition", entity=E("ent-a"), condition=S("has a cold")), sets=[SUF(d.ev(1))])
        d.assertion(d.prop("PhysicalCondition", entity=E("ent-a"), condition=S("recovered")), sets=[SUF(d.ev(2))])
        self.assertTrue(validate_document(d.build())["pass"])

    def test_3_different_referent_is_allowed(self):
        d = base()
        d.assertion(d.prop("LocatedAt", thing=E("ent-item"), location=E("ent-l1")), sets=[SUF(d.ev(1))],
                    validity={"start": d.bound(), "end": d.bound(d.anchor("t-move"), sets=[SUF(d.ev(2))])})
        d.assertion(d.prop("LocatedAt", thing=E("ent-item"), location=E("ent-l2")), sets=[SUF(d.ev(2))],
                    validity={"start": d.bound("t-move"), "end": d.bound()})
        self.assertTrue(validate_document(d.build())["pass"])

    def test_4_key_order_does_not_hide_a_duplicate(self):
        d = base()
        d.prop("LocatedAt", thing=E("ent-item"), location=E("ent-l1"))
        d.prop_new("LocatedAt", location=E("ent-l1"), thing=E("ent-item"))
        props = d.build()["propositions"]
        self.assertNotEqual(list(props[0]["args"]), list(props[1]["args"]))  # different serialized order
        self.assertEqual(proposition_signature(props[0]), proposition_signature(props[1]))
        self.assertTrue(any("duplicate concrete proposition content" in i for i in issues(d.build())))

    def test_5_two_placeholders_are_allowed(self):
        d = base()
        one, two = d.placeholder_prop("unknown"), d.placeholder_prop("unknown")
        self.assertIsNone(proposition_signature(d.build()["propositions"][0]))
        for ph, unit in ((one, 1), (two, 2)):
            d.assertion(d.prop("Attitude", holder=E("ent-a"), attitude=TOK("attitude_kind", "SUSPECTS"),
                               content=P(ph), content_polarity=POL()), sets=[SUF(d.ev(unit))])
        self.assertTrue(validate_document(d.build())["pass"])

    def test_6_propositions_embedding_different_placeholders_are_allowed(self):
        d = base()
        one, two = d.placeholder_prop("x"), d.placeholder_prop("x")
        a = d.prop("Conceals", concealer=E("ent-a"), content=P(one), content_polarity=SPOL(), concealed_from=E("ent-b"))
        b = d.prop("Conceals", concealer=E("ent-a"), content=P(two), content_polarity=SPOL(), concealed_from=E("ent-b"))
        self.assertNotEqual(a, b)
        self.assertEqual([i for i in issues(d.build()) if "duplicate" in i], [])

    def test_7_one_proposition_reused_by_many_assertions_is_allowed(self):
        d = base()
        p = d.prop("LocatedAt", thing=E("ent-item"), location=E("ent-l1"))
        self.assertEqual(p, d.prop("LocatedAt", thing=E("ent-item"), location=E("ent-l1")))
        d.assertion(p, sets=[SUF(d.ev(1))])
        d.assertion(d.prop("Says", speaker=E("ent-a"), content=P(p), content_polarity=POL()), sets=[SUF(d.ev(2))])
        d.assertion(d.prop("Attitude", holder=E("ent-b"), attitude=TOK("attitude_kind", "HOLDS_TRUE"),
                           content=P(p), content_polarity=POL()), sets=[SUF(d.ev(3))])
        doc = d.build()
        self.assertTrue(validate_document(doc)["pass"])
        view = project_as_of(doc, [3, END])
        self.assertEqual([k["verdict"] for k in view["knowledge_verdicts"]], ["KNOWS"])

    def test_signature_ignores_id_and_distinguishes_token_and_literal(self):
        base_prop = {"id": "x", "predicate": "NamedAs", "args": {
            "entity": {"kind": "ENTITY", "ref": "e1"},
            "name": {"kind": "LITERAL", "value_type": "STRING", "value": "N"},
            "name_kind": {"kind": "TOKEN", "vocabulary": "name_kind", "value": "FORMAL"}}}
        other_id = dict(base_prop, id="y")
        self.assertEqual(proposition_signature(base_prop), proposition_signature(other_id))
        changed = {"id": "z", "predicate": "NamedAs", "args": dict(base_prop["args"], name_kind={
            "kind": "TOKEN", "vocabulary": "name_kind", "value": "NICKNAME"})}
        self.assertNotEqual(proposition_signature(base_prop), proposition_signature(changed))


class TestPromotedPredicates(unittest.TestCase):
    def test_ownership_is_distinct_from_custody(self):
        d = base()
        d.assertion(d.prop("Owns", owner=E("ent-a"), item=E("ent-item")), sets=[SUF(d.ev(1))], validity=dict(OPEN))
        d.assertion(d.prop("Possesses", holder=E("ent-b"), item=E("ent-item")), sets=[SUF(d.ev(2))], validity=dict(OPEN))
        doc = d.build()
        self.assertTrue(validate_document(doc)["pass"])
        self.assertEqual(project_as_of(doc, [9, END])["diagnostics"], [])

    def test_two_owners_of_one_item_are_flagged_not_resolved(self):
        d = base()
        for owner, unit in (("ent-a", 1), ("ent-b", 2)):
            d.assertion(d.prop("Owns", owner=E(owner), item=E("ent-item")), sets=[SUF(d.ev(unit))], validity=dict(OPEN))
        codes = [x["code"] for x in project_as_of(d.build(), [9, END])["diagnostics"]]
        self.assertIn("POTENTIAL_FUNCTIONAL_CONFLICT", codes)

    def test_condition_with_late_end_bound(self):
        d = base()
        ill = d.assertion(d.prop("PhysicalCondition", entity=E("ent-a"), condition=S("has a cold")), sets=[SUF(d.ev(2))],
                          validity={"start": d.bound(), "end": d.bound(d.anchor("t-recovered"),
                                                                       sets=[SUF(d.ev(5, "RETROSPECTIVE"))])})
        doc = d.build()
        self.assertEqual(project_as_of(doc, [4, END])["visible_assertions"][ill]["validity"]["end"], {"kind": "OPEN"})
        self.assertEqual(project_as_of(doc, [5, END])["visible_assertions"][ill]["validity"]["end"]["anchor_id"],
                         "t-recovered")

    def test_emotion_gate_rejects_self_report_as_explicit(self):
        d = base()
        d.assertion(d.prop("EmotionToward", holder=E("ent-a"), target=E("ent-b"), emotion=S("dislike")),
                    sets=[SUF(d.ev(1, "IN_WORLD_REPORT"))], validity=dict(OPEN))
        self.assertTrue(any("self-report" in i for i in issues(d.build(), "epistemic_integrity")))

    def test_behaviour_based_emotion_is_suggested(self):
        d = base()
        smile = d.event("evt-smile")
        occ, _ = occurred_with(d, smile, 3, [("ent-a", "AGENT")])
        emotion = d.assertion(d.prop("EmotionToward", holder=E("ent-a"), target=E("ent-b"), emotion=S("affection")),
                              status="SUGGESTED", derivations=[("BEHAVIOUR_SUGGESTS_STATE", [occ])], validity=dict(OPEN))
        doc = d.build()
        self.assertTrue(validate_document(doc)["pass"])
        self.assertEqual(project_as_of(doc, [3, END])["visible_assertions"][emotion]["epistemic_status"], "SUGGESTED")
        d2 = base()
        occ2, _ = occurred_with(d2, d2.event("evt-smile"), 3, [("ent-a", "AGENT")])
        d2.assertion(d2.prop("EmotionToward", holder=E("ent-a"), target=E("ent-b"), emotion=S("affection")),
                     status="ENTAILED", derivations=[("BEHAVIOUR_SUGGESTS_STATE", [occ2])], validity=dict(OPEN))
        self.assertFalse(validate_document(d2.build())["pass"])

    def test_intention_is_holder_relative(self):
        d = base()
        p = d.prop("Possesses", holder=E("ent-a"), item=E("ent-item"))
        intends = d.assertion(d.prop("Intends", holder=E("ent-a"), content=P(p), content_polarity=SPOL()),
                              status="SUGGESTED", sets=[SUF(d.ev(2))], validity=dict(OPEN))
        doc = d.build()
        self.assertTrue(validate_document(doc)["pass"])
        self.assertEqual(project_as_of(doc, [9, END])["canonical_commitments"][p]["status"], "UNCOMMITTED")
        d.assertion(p, status="SUGGESTED", derivations=[("BEHAVIOUR_SUGGESTS_STATE", [intends])])
        self.assertTrue(any("never establishes its content" in i
                            for i in issues(d.build(), "derivation_integrity")))

    def test_habitual_activity_is_a_time_scoped_state(self):
        d = base()
        habit = d.assertion(d.prop("Habitually", agent=E("ent-a"), activity=S("cooks dinner for"), beneficiary=E("ent-b")),
                            sets=[SUF(d.ev(6, "NARRATION_SUMMARY"))],
                            validity={"start": d.bound(d.anchor("t-start")), "end": d.bound()})
        doc = d.build()
        self.assertTrue(validate_document(doc)["pass"])
        self.assertNotIn(habit, project_as_of(doc, [5, END])["visible_assertions"])
        self.assertIn(habit, project_as_of(doc, [6, END])["visible_assertions"])


if __name__ == "__main__":
    unittest.main()
