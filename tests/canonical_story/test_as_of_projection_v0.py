"""As-of projection v0 tests (synthetic; no model, API or network)."""
import copy
import json
import unittest
from pathlib import Path

import tests.canonical_story._dependencies  # noqa: F401  (fails loudly if dependencies are missing)
from tests.canonical_story.fixture_builder import (
    EXTRA_VALID_CASES, POL, ROLE, SUF, TOK, VALID_CASES, Doc, E, M, P, S, V, occurred_with,
)
from tools.canonical_story.view_v0 import ProjectionError, project_as_of

HERE = Path(__file__).resolve().parent
END = 999  # position key [N, END] means "after every segment of unit N"


def at(doc, unit):
    return project_as_of(doc, [unit, END])


def props(doc, predicate, **args):
    out = []
    for p in doc["propositions"]:
        if p.get("predicate") != predicate:
            continue
        if all(p["args"][k].get("ref", p["args"][k].get("value")) == v for k, v in args.items()):
            out.append(p["id"])
    return out


def assertions_for(doc, predicate, **args):
    ids = set(props(doc, predicate, **args))
    return [a["id"] for a in doc["assertions"] if a["proposition_id"] in ids]


def verdicts(view):
    return {(v["holder_class"], v["attitude"], v["content"], v["verdict"]) for v in view["knowledge_verdicts"]}


class TestSnapshotConformance(unittest.TestCase):
    """M2-02 section 21 snapshots, checked against machine-readable expectations."""

    def test_expected_snapshots(self):
        spec = json.loads((HERE / "expected_snapshots_m2_02_s21.json").read_text(encoding="utf-8"))
        doc = EXTRA_VALID_CASES[spec["fixture"]]()
        alias = {"P_X": props(doc, "LocatedAt", thing="ent-key")[0],
                 "P_Y": props(doc, "LocatedAt", thing="ent-box")[0]}
        [identity_known] = props(doc, "IdentityKnown", entity="ent-u")
        [unaware] = [v for v in assertions_for(doc, "Attitude", holder="ent-b", attitude="UNAWARE")]
        for snap in spec["snapshots"]:
            view, exp = project_as_of(doc, snap["as_of"]), snap["expect"]
            with self.subTest(as_of=snap["as_of"]):
                cls = view["identity_equivalence"]["entity_class"]
                for x, y, same in exp["identity_equivalent"]:
                    self.assertEqual(cls[x] == cls[y], same)
                for mid, classes in exp["mention_classes"].items():
                    self.assertEqual(view["mention_resolution"][mid]["entity_classes"], classes)
                self.assertEqual(view["canonical_commitments"][identity_known]["status"], exp["identity_known_u"])
                [secret] = view["secrets"]
                self.assertEqual(secret["status"], exp["secret_status"])
                self.assertEqual(bool(secret["target_unaware_evidence"]), exp["secret_target_unaware_evidenced"])
                expected = {(cls[h], att, alias[c], verdict) for h, att, c, verdict in exp["verdicts"]}
                self.assertEqual(verdicts(view), expected)
                for name, status in exp["canonical"].items():
                    self.assertEqual(view["canonical_commitments"][alias[name]]["status"], status)
                reveals = {tuple(r["content_class"]): r["reader_reveal_position"] for r in view["reader_reveals"]}
                for name, position in exp["reader_reveal"].items():
                    self.assertEqual(reveals.get((alias[name],)), position, name)
                end = view["visible_assertions"][unaware]["validity"]["end"]
                self.assertEqual(end.get("anchor_id", end["kind"]), exp["unaware_end"])
                for ev, status in exp["events"].items():
                    got = view["event_occurrence"].get(ev)
                    self.assertEqual(got["occurrence_status"] if got else None, status)


class TestStressCases(unittest.TestCase):
    def test_a_names_and_address_respect_boundaries(self):
        doc = VALID_CASES["case_a_multiple_names.json"]()
        [family] = assertions_for(doc, "AddressesAs", form="FAMILY_NAME")
        [given] = assertions_for(doc, "AddressesAs", form="GIVEN_NAME")
        v3, v8 = at(doc, 3), at(doc, 8)
        self.assertEqual(v3["visible_assertions"][family]["validity"]["end"], {"kind": "OPEN"})
        self.assertNotIn(given, v3["visible_assertions"])
        self.assertEqual(v8["visible_assertions"][family]["validity"]["end"],
                         {"kind": "ANCHOR", "anchor_id": "t-evt-rename"})
        self.assertIn(given, v8["visible_assertions"])
        self.assertEqual(len(assertions_for(doc, "NamedAs")), 3)
        self.assertEqual(sum(1 for a in at(doc, 1)["visible_assertions"].values() if a["predicate"] == "NamedAs"), 1)
        self.assertEqual(v8["mention_resolution"]["men-2"]["entity_classes"], ["ent-a"])

    def test_b_flashback_does_not_use_discourse_order(self):
        doc = VALID_CASES["case_b_flashback.json"]()
        v19, v20 = at(doc, 19), at(doc, 20)
        self.assertEqual(v19["temporal_relations"], [])
        self.assertNotIn("evt-old", v19["event_occurrence"])
        [rel] = v20["temporal_relations"]
        self.assertEqual((rel["subject"], rel["relation"], rel["object"]), ("t-evt-old", "BEFORE", "t-evt-opening"))
        self.assertEqual(v20["event_occurrence"]["evt-old"]["occurrence_status"], "OCCURRED")

    def test_c_possession_history_is_not_overwritten(self):
        doc = VALID_CASES["case_c_possession.json"]()
        poss = assertions_for(doc, "Possesses")
        v5, v9 = at(doc, 5), at(doc, 9)
        self.assertEqual(sorted(a for a in poss if a in v9["visible_assertions"]), sorted(poss))
        visible5 = [a for a in poss if a in v5["visible_assertions"]]
        self.assertEqual(len(visible5), 2)
        b_holds = [a for a in assertions_for(doc, "Possesses", holder="ent-b")][0]
        self.assertEqual(v5["visible_assertions"][b_holds]["validity"]["end"], {"kind": "OPEN"})
        self.assertEqual(v9["visible_assertions"][b_holds]["validity"]["end"]["anchor_id"], "t-evt-return")
        self.assertFalse([d for d in v9["diagnostics"] if d["code"] == "POTENTIAL_FUNCTIONAL_CONFLICT"])

    def test_d_relationship_progression_changes_across_views(self):
        doc = VALID_CASES["case_d_relationship_progression.json"]()

        def stages(view):
            [rel] = view["relationships"]
            self.assertEqual((rel["subject_class"], rel["object_class"], rel["key_tokens"]),
                             ("ent-a", "ent-b", {"dimension": "TRUST"}))
            return [(s["value"]["level"], s["epistemic_status"]) for s in rel["stages"]]
        self.assertEqual(stages(at(doc, 2)), [("NEGATIVE", "EXPLICIT")])
        self.assertEqual(stages(at(doc, 6)), [("NEGATIVE", "EXPLICIT"), ("NEUTRAL", "SUGGESTED")])
        self.assertEqual(stages(at(doc, 11)),
                         [("NEGATIVE", "EXPLICIT"), ("NEUTRAL", "SUGGESTED"), ("POSITIVE", "EXPLICIT")])
        self.assertNotIn("score", json.dumps(at(doc, 11)["relationships"]))

    def test_e_secret_reader_and_character_reveals(self):
        doc = VALID_CASES["case_e_secret_and_reveals.json"]()
        [p_x] = props(doc, "LocatedAt")
        v3, v7, v15 = at(doc, 3), at(doc, 7), at(doc, 15)
        self.assertIn(("ent-a", "HOLDS_TRUE", p_x, "UNRESOLVED_BELIEF"), verdicts(v3))
        self.assertEqual(v3["secrets"][0]["status"], "ACTIVE")
        self.assertFalse(v3["secrets"][0]["reader_has_canonical_content"])
        self.assertIn(("ent-a", "HOLDS_TRUE", p_x, "KNOWS"), verdicts(v7))
        self.assertTrue(v7["secrets"][0]["reader_has_canonical_content"])
        self.assertEqual(v7["secrets"][0]["status"], "ACTIVE")
        self.assertNotIn(("ent-b", "HOLDS_TRUE", p_x, "KNOWS"), verdicts(v7))
        self.assertIn(("ent-b", "HOLDS_TRUE", p_x, "KNOWS"), verdicts(v15))
        self.assertEqual(v15["secrets"][0]["status"], "ENDED")
        # placeholder content resolves only when SameContent is visible (7)
        [hidden] = [p["id"] for p in doc["propositions"] if p.get("placeholder")]
        self.assertEqual(at(doc, 6)["content_resolution"]["placeholders"][hidden]["status"], "UNRESOLVED")
        self.assertEqual(v7["content_resolution"]["placeholders"][hidden]["resolved_to"], [p_x])
        self.assertIn(("ent-a", "HOLDS_TRUE", hidden, "KNOWS"), verdicts(v7))
        self.assertIn(("ent-a", "HOLDS_TRUE", hidden, "UNRESOLVED_BELIEF"), verdicts(at(doc, 6)))

    def test_f_mistaken_belief_is_unresolved_until_negation(self):
        doc = VALID_CASES["case_f_mistaken_belief.json"]()
        [p_y] = props(doc, "LocatedAt")
        self.assertIn(("ent-b", "HOLDS_TRUE", p_y, "UNRESOLVED_BELIEF"), verdicts(at(doc, 17)))
        self.assertIn(("ent-b", "HOLDS_TRUE", p_y, "MISTAKEN"), verdicts(at(doc, 18)))

    def test_g_reported_claim_stays_uncommitted(self):
        doc = VALID_CASES["case_g_reported_claim.json"]()
        [p_x] = props(doc, "LocatedAt")
        view = at(doc, 30)
        self.assertEqual(view["canonical_commitments"][p_x]["status"], "UNCOMMITTED")
        [claim] = view["reported_claims"]["claims"]
        self.assertEqual((claim["speaker_class"], claim["relation_to_canonical"]), ("ent-a", "UNRESOLVED"))
        self.assertEqual(view["event_occurrence"]["evt-say"]["occurrence_status"], "OCCURRED")
        self.assertFalse(any(r["content_class"] == [p_x] for r in view["reader_reveals"]))

    def test_h_multi_path_visible_from_earliest_path(self):
        doc = VALID_CASES["case_h_multi_path.json"]()
        [occ] = assertions_for(doc, "Occurred")
        self.assertNotIn(occ, at(doc, 7)["visible_assertions"])
        v8, v20 = at(doc, 8), at(doc, 20)
        self.assertEqual(v8["visible_assertions"][occ]["availability"], [8, 1])
        self.assertEqual(len(v8["visible_assertions"][occ]["visible_support"]["sufficient_evidence_sets"]), 1)
        self.assertEqual(len(v20["visible_assertions"][occ]["visible_support"]["sufficient_evidence_sets"]), 2)

    def test_i_partial_retrospective_does_not_reveal_detail(self):
        d = Doc("story-i2")
        d.entity("ent-a", "CHARACTER")
        carry = d.event("evt-carry", "MOVEMENT")
        occ = d.assertion(d.prop("Occurred", event=V(carry)), sets=[SUF(d.ev(12, "RETROSPECTIVE"))])
        manner = d.assertion(d.prop("Manner", event=V(carry), manner=S("by cart")),
                             sets=[("PARTIAL", [d.ev(12, "RETROSPECTIVE")]), SUF(d.ev(30))])
        doc = d.build()
        v12 = at(doc, 12)
        self.assertIn(occ, v12["visible_assertions"])
        self.assertNotIn(manner, v12["visible_assertions"])
        self.assertIn(manner, at(doc, 30)["visible_assertions"])
        fixture = VALID_CASES["case_i_partial_retrospective.json"]()
        [m] = assertions_for(fixture, "Manner")
        support = at(fixture, 12)["visible_assertions"][m]["visible_support"]
        self.assertEqual(len(support["sufficient_evidence_sets"]), 1)
        self.assertEqual(len(support["non_grounding_evidence_sets"]), 1)

    def test_j_unknown_identity_resolves_late(self):
        doc = VALID_CASES["case_j_unknown_identity.json"]()
        v21, v22 = at(doc, 21), at(doc, 22)
        self.assertNotEqual(v21["identity_equivalence"]["entity_class"]["ent-u"], "ent-a")
        self.assertNotIn("ent-a", v21["visible_referents"]["entities"])
        self.assertEqual(v22["identity_equivalence"]["classes"], [["ent-a", "ent-u"]])
        self.assertEqual(v22["mention_resolution"]["men-u"]["entity_classes"], ["ent-a"])
        self.assertTrue(next(e for e in doc["entities"] if e["id"] == "ent-u")["placeholder"])


class TestSpoilerLeaks(unittest.TestCase):
    """An earlier view must not see anything that becomes available later."""

    def setUp(self):
        self.d = Doc("story-leak")
        self.d.entity("ent-a", "CHARACTER")
        self.d.entity("ent-b", "CHARACTER")
        self.ev = self.d.event("evt-x", "TRANSFER")

    def test_1_later_direct_evidence(self):
        aid = self.d.assertion(self.d.prop("Occurred", event=V(self.ev)), sets=[SUF(self.d.ev(10))])
        doc = self.d.build()
        self.assertNotIn(aid, at(doc, 9)["visible_assertions"])
        self.assertNotIn("evt-x", at(doc, 9)["visible_referents"]["events"])

    def test_2_later_alternative_path(self):
        aid = self.d.assertion(self.d.prop("Occurred", event=V(self.ev)),
                               sets=[SUF(self.d.ev(5)), SUF(self.d.ev(10, "RETROSPECTIVE"))])
        doc = self.d.build()
        support = at(doc, 7)["visible_assertions"][aid]["visible_support"]
        self.assertEqual(len(support["sufficient_evidence_sets"]), 1)

    def test_3_later_derivation_premise(self):
        item = self.d.entity("ent-item", "OBJECT")
        occ = self.d.assertion(self.d.prop("Occurred", event=V(self.ev)), sets=[SUF(self.d.ev(3))])
        part = self.d.assertion(self.d.prop("Participates", event=V(self.ev), participant=E("ent-b"),
                                            role=ROLE("RECIPIENT")), sets=[SUF(self.d.ev(10))])
        derived = self.d.assertion(self.d.prop("Possesses", holder=E("ent-b"), item=E(item)), status="ENTAILED",
                                   derivations=[("TRANSFER_RESULT", [occ, part])])
        doc = self.d.build()
        v9 = at(doc, 9)
        self.assertNotIn(derived, v9["visible_assertions"])
        self.assertNotIn(part, v9["visible_assertions"])
        self.assertIn(derived, at(doc, 10)["visible_assertions"])

    def test_4_later_same_as(self):
        doc = VALID_CASES["case_j_unknown_identity.json"]()
        self.assertEqual(at(doc, 21)["identity_equivalence"]["classes"], [])

    def test_5_later_same_content(self):
        doc = VALID_CASES["case_e_secret_and_reveals.json"]()
        self.assertEqual(at(doc, 6)["content_resolution"]["classes"], [])

    def test_6_later_refers_to(self):
        mention = self.d.mention("men-1", self.d.ev(4), "someone")
        self.d.assertion(self.d.prop("RefersTo", mention=M(mention), entity=E("ent-a")), sets=[SUF(self.d.ev(10))])
        doc = self.d.build()
        self.assertEqual(at(doc, 5)["mention_resolution"]["men-1"]["status"], "UNRESOLVED")
        self.assertEqual(at(doc, 10)["mention_resolution"]["men-1"]["entity_classes"], ["ent-a"])
        self.assertNotIn("men-1", at(doc, 3)["visible_mentions"])

    def test_7_later_state_end_bound(self):
        doc = VALID_CASES["case_e_secret_and_reveals.json"]()
        [unaware] = assertions_for(doc, "Attitude", holder="ent-b", attitude="UNAWARE")
        self.assertEqual(at(doc, 14)["visible_assertions"][unaware]["validity"]["end"], {"kind": "OPEN"})
        self.assertEqual(at(doc, 15)["visible_assertions"][unaware]["validity"]["end"]["anchor_id"], "t-evt-tell")

    def test_7b_later_start_bound(self):
        item = self.d.entity("ent-item", "OBJECT")
        start = self.d.anchor("t-start")
        aid = self.d.assertion(self.d.prop("Possesses", holder=E("ent-a"), item=E(item)), sets=[SUF(self.d.ev(2))],
                               validity={"start": self.d.bound(start, sets=[SUF(self.d.ev(9))]),
                                         "end": self.d.bound()})
        doc = self.d.build()
        self.assertEqual(at(doc, 5)["visible_assertions"][aid]["validity"]["start"], {"kind": "OPEN"})
        self.assertNotIn("t-start", at(doc, 5)["visible_referents"]["anchors"])
        self.assertEqual(at(doc, 9)["visible_assertions"][aid]["validity"]["start"]["anchor_id"], "t-start")

    def test_8_later_canonical_resolution_of_belief(self):
        doc = VALID_CASES["case_f_mistaken_belief.json"]()
        self.assertFalse(any(v["verdict"] == "MISTAKEN" for v in at(doc, 17)["knowledge_verdicts"]))

    def test_9_later_reader_reveal(self):
        doc = VALID_CASES["case_e_secret_and_reveals.json"]()
        [p_x] = props(doc, "LocatedAt")
        self.assertFalse(any(p_x in r["content_class"] for r in at(doc, 6)["reader_reveals"]))
        self.assertTrue(any(p_x in r["content_class"] for r in at(doc, 7)["reader_reveals"]))

    def test_10_rejected_assertion_never_visible(self):
        aid = self.d.assertion(self.d.prop("Occurred", event=V(self.ev)), sets=[SUF(self.d.ev(1))],
                               review={"state": "REJECTED", "reason": "UNSUPPORTED"})
        doc = self.d.build()
        view = at(doc, 99)
        self.assertNotIn(aid, view["visible_assertions"])
        self.assertEqual(view["event_occurrence"], {})

    def test_later_referents_are_not_exposed(self):
        doc = VALID_CASES["case_e_secret_and_reveals.json"]()
        self.assertNotIn("evt-tell", at(doc, 10)["visible_referents"]["events"])
        self.assertIn("evt-tell", at(doc, 15)["visible_referents"]["events"])


class TestHolderRelativeSafety(unittest.TestCase):
    def setUp(self):
        self.d = Doc("story-holder")
        self.d.entity("ent-a", "CHARACTER")
        self.thing, self.place = self.d.entity("ent-thing", "OBJECT"), self.d.entity("ent-place", "LOCATION")
        self.p = self.d.prop("LocatedAt", thing=E(self.thing), location=E(self.place))

    def test_says_does_not_make_content_canonical(self):
        self.d.assertion(self.d.prop("Says", speaker=E("ent-a"), content=P(self.p), content_polarity=POL()),
                         sets=[SUF(self.d.ev(2))])
        view = at(self.d.build(), 5)
        self.assertEqual(view["canonical_commitments"][self.p]["status"], "UNCOMMITTED")
        self.assertFalse(any(self.p in r["content_class"] for r in view["reader_reveals"]))

    def test_belief_does_not_make_content_canonical_or_known(self):
        self.d.assertion(self.d.prop("Attitude", holder=E("ent-a"), attitude=TOK("attitude_kind", "HOLDS_TRUE"),
                                     content=P(self.p), content_polarity=POL()), sets=[SUF(self.d.ev(2))])
        self.d.assertion(self.p, sets=[SUF(self.d.ev(8, "NARRATION_SUMMARY"))])
        doc = self.d.build()
        v5, v8 = at(doc, 5), at(doc, 8)
        self.assertEqual(v5["canonical_commitments"][self.p]["status"], "UNCOMMITTED")
        self.assertEqual([v["verdict"] for v in v5["knowledge_verdicts"]], ["UNRESOLVED_BELIEF"])
        self.assertEqual([v["verdict"] for v in v8["knowledge_verdicts"]], ["KNOWS"])

    def test_event_only_inside_holder_content_is_not_occurred(self):
        rumoured = self.d.event("evt-rumour", "GENERIC")
        occ_content = self.d.prop("Occurred", event=V(rumoured))
        self.d.assertion(self.d.prop("Says", speaker=E("ent-a"), content=P(occ_content), content_polarity=POL()),
                         sets=[SUF(self.d.ev(3))])
        view = at(self.d.build(), 5)
        entry = view["event_occurrence"]["evt-rumour"]
        self.assertEqual(entry["occurrence_status"], "NOT_ESTABLISHED")
        self.assertTrue(entry["referenced_in_holder_relative_content"])

    def test_negated_belief_content(self):
        self.d.assertion(self.d.prop("Attitude", holder=E("ent-a"), attitude=TOK("attitude_kind", "HOLDS_TRUE"),
                                     content=P(self.p), content_polarity=POL("NEGATED")), sets=[SUF(self.d.ev(2))])
        negated = copy.deepcopy(self.d)
        negated.assertion(self.p, polarity="NEGATED", sets=[SUF(negated.ev(6, "NARRATION_SUMMARY"))])
        affirmed = copy.deepcopy(self.d)
        affirmed.assertion(self.p, sets=[SUF(affirmed.ev(6, "NARRATION_SUMMARY"))])
        self.assertEqual([v["verdict"] for v in at(negated.build(), 6)["knowledge_verdicts"]], ["KNOWS"])
        self.assertEqual([v["verdict"] for v in at(affirmed.build(), 6)["knowledge_verdicts"]], ["MISTAKEN"])
        self.assertEqual([v["verdict"] for v in at(affirmed.build(), 5)["knowledge_verdicts"]], ["UNRESOLVED_BELIEF"])


class TestContradictions(unittest.TestCase):
    def build(self, canonical_at=None):
        d = Doc("story-contra")
        d.entity("ent-a", "CHARACTER")
        d.entity("ent-b", "CHARACTER")
        p = d.prop("LocatedAt", thing=E(d.entity("ent-thing", "OBJECT")), location=E(d.entity("ent-place", "LOCATION")))
        a_says = d.assertion(d.prop("Says", speaker=E("ent-a"), content=P(p), content_polarity=POL()),
                             sets=[SUF(d.ev(5))])
        b_says = d.assertion(d.prop("Says", speaker=E("ent-b"), content=P(p), content_polarity=POL("NEGATED")),
                             sets=[SUF(d.ev(7))])
        if canonical_at:
            d.assertion(p, sets=[SUF(d.ev(canonical_at, "NARRATION_SUMMARY"))])
        return d.build(), p, a_says, b_says

    def test_reported_conflict_then_canonical_resolution(self):
        doc, p, a_says, b_says = self.build(canonical_at=12)
        v8, v12 = at(doc, 8), at(doc, 12)
        self.assertEqual(v8["canonical_commitments"][p]["status"], "UNCOMMITTED")
        [conflict] = v8["reported_claims"]["conflicts"]
        self.assertEqual((conflict["affirming_reports"], conflict["negating_reports"]), ([a_says], [b_says]))
        self.assertEqual(v12["canonical_commitments"][p]["status"], "AFFIRMED")
        relations = {c["assertion_id"]: c["relation_to_canonical"] for c in v12["reported_claims"]["claims"]}
        self.assertEqual(relations, {a_says: "CONSISTENT", b_says: "CONTRADICTED"})
        self.assertEqual(at(doc, 8), v8)  # earlier view unchanged after later projection

    def test_conflicting_canonical_assertions_are_contested_not_resolved(self):
        d = Doc("story-contested")
        ev = d.event("evt-x")
        occurred = d.prop("Occurred", event=V(ev))
        first = d.assertion(occurred, sets=[SUF(d.ev(5))])
        second = d.assertion(occurred, polarity="NEGATED", sets=[SUF(d.ev(9, "NARRATION_SUMMARY"))])
        doc = d.build()
        self.assertEqual(at(doc, 6)["event_occurrence"]["evt-x"]["occurrence_status"], "OCCURRED")
        v9 = at(doc, 9)
        self.assertEqual(v9["event_occurrence"]["evt-x"]["occurrence_status"], "CONTESTED")
        commitment = v9["canonical_commitments"][occurred]
        self.assertEqual(commitment["status"], "CONTESTED")
        self.assertEqual((commitment["affirmed"], commitment["negated"]), ([first], [second]))


class TestIdentityAndDiagnostics(unittest.TestCase):
    def test_same_as_chain_and_conflict(self):
        d = Doc("story-chain")
        for e in ("ent-a", "ent-u", "ent-x"):
            d.entity(e, "CHARACTER")
        d.assertion(d.prop("SameAs", first=E("ent-u"), second=E("ent-x")), sets=[SUF(d.ev(3))])
        d.assertion(d.prop("SameAs", first=E("ent-x"), second=E("ent-a")), sets=[SUF(d.ev(6))])
        d.assertion(d.prop("SameAs", first=E("ent-u"), second=E("ent-a")), polarity="NEGATED", sets=[SUF(d.ev(8))])
        doc = d.build()
        self.assertEqual(at(doc, 3)["identity_equivalence"]["classes"], [["ent-u", "ent-x"]])
        self.assertEqual(at(doc, 6)["identity_equivalence"]["classes"], [["ent-a", "ent-u", "ent-x"]])
        codes = [x["code"] for x in at(doc, 8)["diagnostics"]]
        self.assertIn("IDENTITY_CONFLICT", codes)

    def test_potential_functional_conflict_is_surfaced_not_resolved(self):
        d = Doc("story-func")
        d.entity("ent-a", "CHARACTER")
        box = d.entity("ent-box", "OBJECT")
        p1 = d.prop("LocatedAt", thing=E(box), location=E(d.entity("ent-l1", "LOCATION")))
        p2 = d.prop("LocatedAt", thing=E(box), location=E(d.entity("ent-l2", "LOCATION")))
        a1 = d.assertion(p1, sets=[SUF(d.ev(2))])
        a2 = d.assertion(p2, sets=[SUF(d.ev(3))])
        view = at(d.build(), 3)
        conflicts = [x for x in view["diagnostics"] if x["code"] == "POTENTIAL_FUNCTIONAL_CONFLICT"]
        self.assertEqual(conflicts[0]["assertions"], [a1, a2])
        self.assertIn(a1, view["visible_assertions"])
        self.assertIn(a2, view["visible_assertions"])

    def test_no_false_functional_conflict_in_stress_cases(self):
        for name in ("case_a_multiple_names.json", "case_c_possession.json", "case_d_relationship_progression.json"):
            doc = VALID_CASES[name]()
            for unit in (1, 4, 6, 8, 9, 11, 30):
                codes = [x["code"] for x in at(doc, unit)["diagnostics"]]
                self.assertNotIn("POTENTIAL_FUNCTIONAL_CONFLICT", codes, (name, unit))


class TestPurity(unittest.TestCase):
    def test_projection_does_not_mutate_document(self):
        for name, build in {**VALID_CASES, **EXTRA_VALID_CASES}.items():
            doc = build()
            before = copy.deepcopy(doc)
            for unit in (1, 5, 10, 22, 99):
                at(doc, unit)
            self.assertEqual(doc, before, name)

    def test_projection_is_deterministic(self):
        doc = EXTRA_VALID_CASES["snapshot_m2_02_s21.json"]()
        for unit in (5, 20, 22):
            outputs = {json.dumps(at(doc, unit), sort_keys=True) for _ in range(3)}
            self.assertEqual(len(outputs), 1)

    def test_view_is_marked_derived_and_not_a_schema_record(self):
        view = at(VALID_CASES["case_b_flashback.json"](), 20)
        self.assertTrue(view["derived"])
        self.assertEqual(view["view_format"], "canonical_story_view/v0")
        from tools.canonical_story.conformance_v0 import load_schema
        self.assertNotIn("view_format", load_schema()["properties"])

    def test_invalid_document_is_refused(self):
        doc = VALID_CASES["case_b_flashback.json"]()
        doc["assertions"][0]["epistemic_status"] = "REPORTED"
        with self.assertRaises(ProjectionError):
            project_as_of(doc, [5])


if __name__ == "__main__":
    unittest.main()
