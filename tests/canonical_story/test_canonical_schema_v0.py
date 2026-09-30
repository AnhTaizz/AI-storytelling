"""Canonical Story Schema v0 conformance tests (synthetic; no model, API or network)."""
import json
import unittest

from jsonschema import Draft202012Validator

from tests.canonical_story import generate_fixtures as gen
from tests.canonical_story.fixture_builder import (
    E, INVALID_CASES, POL, SUF, TOK, V, VALID_CASES, Doc, P, occurred_with,
)
from tools.canonical_story.conformance_v0 import (
    SEMANTIC_SECTIONS, availability_map, load_registry, load_schema, validate_document,
)


def issues_of(report, layer):
    if layer == "structural":
        return report["structural"]["issues"]
    return report["semantic"][layer]["issues"]


class TestSchemaAndRegistry(unittest.TestCase):
    def test_schema_is_valid_draft_2020_12(self):
        Draft202012Validator.check_schema(load_schema())

    def test_epistemic_enum_excludes_reported_and_unknown(self):
        enum = load_schema()["$defs"]["Assertion"]["properties"]["epistemic_status"]["enum"]
        self.assertEqual(enum, ["EXPLICIT", "ENTAILED", "SUGGESTED"])

    def test_no_derived_concept_is_a_record_type(self):
        record_keys = set(load_schema()["properties"])
        for derived in ("relationships", "secrets", "story_claims", "aliases", "knowledge", "views"):
            self.assertNotIn(derived, record_keys)

    def test_registry_is_internally_consistent(self):
        reg = load_registry()
        vocab, preds = reg["vocabularies"], reg["predicates"]
        forbidden = {v.upper() for v in reg["forbidden_stored_verdicts"]}
        for name, spec in preds.items():
            self.assertNotIn(name.upper(), forbidden)
            for arg in spec["args"]:
                if arg["kind"] == "TOKEN":
                    self.assertIn(arg["vocabulary"], vocab, f"{name}.{arg['name']}")
            for fixed in spec.get("functional_on", []):
                self.assertIn(fixed, {a["name"] for a in spec["args"]})
        for value in vocab["attitude_kind"]:
            self.assertNotIn(value, forbidden)
        for rule_id, rule in reg["derivation_rules"].items():
            for pred in rule["conclusion_predicates"] + rule["required_premise_predicates"]:
                self.assertIn(pred, preds, f"{rule_id} references {pred}")
            self.assertIn(rule["max_status"], ("ENTAILED", "SUGGESTED"), rule_id)
        self.assertEqual(set(reg["holder_relative_predicates"]), {"Says", "Attitude"})

    def test_paratext_is_policy_not_ontology(self):
        roles = load_schema()["$defs"]["EvidenceRole"]["enum"]
        self.assertIn("PARATEXT", roles)
        policy = load_registry()["authority_policies"]["DEFAULT_V0"]
        self.assertIn("PARATEXT", policy["roles_not_sufficient_for_story_world"])


class TestConformanceFixtures(unittest.TestCase):
    def test_valid_cases_a_to_j_pass_both_layers(self):
        self.assertEqual(len(VALID_CASES), 10)
        for name, build in VALID_CASES.items():
            with self.subTest(fixture=name):
                report = validate_document(build())
                self.assertTrue(report["structural"]["pass"], report["structural"]["issues"])
                for section in SEMANTIC_SECTIONS:
                    self.assertTrue(report["semantic"][section]["pass"],
                                    (section, report["semantic"][section]["issues"]))

    def test_negative_fixtures_are_rejected_for_the_right_reason(self):
        for name, (build, layer, fragment) in INVALID_CASES.items():
            with self.subTest(fixture=name):
                report = validate_document(build())
                self.assertFalse(report["pass"])
                found = issues_of(report, layer)
                self.assertTrue(any(fragment in issue for issue in found), (layer, fragment, found))

    def test_committed_fixtures_match_builder(self):
        for path, text in gen.expected_files().items():
            with self.subTest(fixture=path.name):
                self.assertTrue(path.is_file(), f"missing fixture {path}; run generate_fixtures")
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), json.loads(text))

    def test_committed_report_matches_regeneration(self):
        committed = json.loads(gen.REPORT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(committed, json.loads(gen.dump(gen.build_report())))
        self.assertTrue(all(v["rejected"] for v in committed["invalid_fixtures"].values()))
        self.assertTrue(all(v["pass"] for v in committed["valid_fixtures"].values()))


def pos(chapter):
    return [chapter, 1]


class TestAvailability(unittest.TestCase):
    def setUp(self):
        self.d = Doc("story-avail")
        self.d.entity("ent-a", "CHARACTER")
        self.d.entity("ent-b", "CHARACTER")
        self.item = self.d.entity("ent-item", "OBJECT")
        self.ev = self.d.event("evt-x", "TRANSFER")

    def occ(self, *sets):
        return self.d.assertion(self.d.prop("Occurred", event=V(self.ev)), sets=list(sets))

    def avail(self, aid):
        doc = self.d.build()
        report = validate_document(doc)
        self.assertTrue(report["pass"], report)
        return availability_map(doc)[aid]

    def test_single_evidence_path(self):
        self.assertEqual(self.avail(self.occ(SUF(self.d.ev(4)))), pos(4))

    def test_two_independent_paths_take_the_earliest(self):
        aid = self.occ(SUF(self.d.ev(9)), SUF(self.d.ev(3, "RETROSPECTIVE")))
        self.assertEqual(self.avail(aid), pos(3))

    def test_multi_evidence_sufficient_set_takes_its_latest_ref(self):
        aid = self.occ(SUF(self.d.ev(2), self.d.ev(7), self.d.ev(5)))
        self.assertEqual(self.avail(aid), pos(7))

    def test_derived_path_takes_latest_premise(self):
        occ = self.occ(SUF(self.d.ev(3)))
        p1 = self.d.assertion(self.d.prop("Participates", event=V(self.ev), participant=E("ent-b"),
                                          role=TOK("participant_role", "RECIPIENT")), sets=[SUF(self.d.ev(6))])
        derived = self.d.assertion(self.d.prop("Possesses", holder=E("ent-b"), item=E(self.item)),
                                   status="ENTAILED", derivations=[("TRANSFER_RESULT", [occ, p1])])
        self.assertEqual(self.avail(derived), pos(6))

    def test_earlier_direct_path_beats_later_derivation(self):
        occ = self.occ(SUF(self.d.ev(8)))
        part = self.d.assertion(self.d.prop("Participates", event=V(self.ev), participant=E("ent-b"),
                                            role=TOK("participant_role", "RECIPIENT")), sets=[SUF(self.d.ev(8))])
        aid = self.d.assertion(self.d.prop("Possesses", holder=E("ent-b"), item=E(self.item)),
                               status="ENTAILED", sets=[SUF(self.d.ev(2))],
                               derivations=[("TRANSFER_RESULT", [occ, part])])
        self.assertEqual(self.avail(aid), pos(2))

    def test_partial_and_corroborating_evidence_are_ignored(self):
        aid = self.occ(("PARTIAL", [self.d.ev(1)]), ("CORROBORATING", [self.d.ev(2)]), SUF(self.d.ev(10)))
        self.assertEqual(self.avail(aid), pos(10))

    def test_only_partial_evidence_gives_no_availability(self):
        aid = self.occ(("PARTIAL", [self.d.ev(1)]))
        doc = self.d.build()
        self.assertIsNone(availability_map(doc)[aid])
        self.assertFalse(validate_document(doc)["pass"])

    def test_rejected_assertion_is_retained_but_unavailable(self):
        aid = self.d.assertion(self.d.prop("Occurred", event=V(self.ev)), sets=[SUF(self.d.ev(4))],
                               review={"state": "REJECTED", "reason": "WRONG_EVIDENCE"})
        doc = self.d.build()
        self.assertTrue(validate_document(doc)["pass"])
        self.assertIn(aid, [a["id"] for a in doc["assertions"]])
        self.assertIsNone(availability_map(doc)[aid])


class TestCaseSemantics(unittest.TestCase):
    """Availability facts that later as-of views (M2-04) rely on."""

    def report(self, name):
        return validate_document(VALID_CASES[name]())

    def find(self, doc, predicate, **arg_values):
        props = {p["id"]: p for p in doc["propositions"]}
        out = []
        for a in doc["assertions"]:
            p = props[a["proposition_id"]]
            if p.get("predicate") != predicate:
                continue
            if all(p["args"][k].get("value", p["args"][k].get("ref")) == v for k, v in arg_values.items()):
                out.append(a["id"])
        return out

    def test_case_e_reader_and_character_reveals_differ(self):
        doc = VALID_CASES["case_e_secret_and_reveals.json"]()
        av = self.report("case_e_secret_and_reveals.json")["availability"]
        [content] = self.find(doc, "LocatedAt")
        self.assertEqual(av[content]["assertion"], pos(7))                 # reader reveal
        [b_learns] = self.find(doc, "Attitude", holder="ent-b", attitude="HOLDS_TRUE")
        self.assertEqual(av[b_learns]["assertion"], pos(15))               # character learns
        [unaware] = self.find(doc, "Attitude", holder="ent-b", attitude="UNAWARE")
        self.assertEqual(av[unaware]["assertion"], pos(4))
        self.assertEqual(av[unaware]["validity_end"], pos(15))             # end bound not visible before 15

    def test_case_f_belief_does_not_assert_content(self):
        doc = VALID_CASES["case_f_mistaken_belief.json"]()
        av = self.report("case_f_mistaken_belief.json")["availability"]
        [belief] = self.find(doc, "Attitude")
        [truth] = self.find(doc, "LocatedAt")
        self.assertEqual(av[belief]["assertion"], pos(5))
        self.assertEqual(av[truth]["assertion"], pos(18))
        self.assertEqual(next(a for a in doc["assertions"] if a["id"] == truth)["polarity"], "NEGATED")

    def test_case_g_reported_content_is_never_asserted(self):
        doc = VALID_CASES["case_g_reported_claim.json"]()
        self.assertEqual(self.find(doc, "LocatedAt"), [])
        self.assertEqual(len(self.find(doc, "Says")), 1)

    def test_case_h_and_i_multi_path_and_partial(self):
        doc_h = VALID_CASES["case_h_multi_path.json"]()
        [occ] = self.find(doc_h, "Occurred")
        self.assertEqual(self.report("case_h_multi_path.json")["availability"][occ]["assertion"], pos(8))
        doc_i = VALID_CASES["case_i_partial_retrospective.json"]()
        av_i = self.report("case_i_partial_retrospective.json")["availability"]
        [manner] = self.find(doc_i, "Manner")
        self.assertEqual(av_i[manner]["assertion"], pos(5))

    def test_case_j_identity_resolution_is_late_and_non_destructive(self):
        doc = VALID_CASES["case_j_unknown_identity.json"]()
        av = self.report("case_j_unknown_identity.json")["availability"]
        [same] = self.find(doc, "SameAs")
        self.assertEqual(av[same]["assertion"], pos(22))
        self.assertTrue(next(e for e in doc["entities"] if e["id"] == "ent-u")["placeholder"])

    def test_case_c_state_history_is_appended(self):
        doc = VALID_CASES["case_c_possession.json"]()
        self.assertEqual(len(self.find(doc, "Possesses")), 3)
        av = self.report("case_c_possession.json")["availability"]
        [first] = [a for a in self.find(doc, "Possesses", holder="ent-a")
                   if av[a]["assertion"] == pos(1)]
        self.assertEqual(av[first]["validity_end"], pos(4))

    def test_event_record_alone_does_not_mean_occurred(self):
        d = Doc("story-evt")
        d.event("evt-planned", "GENERIC")
        doc = d.build()
        self.assertTrue(validate_document(doc)["pass"])
        self.assertEqual(doc["assertions"], [])
        self.assertNotIn("occurred", doc["events"][0])


if __name__ == "__main__":
    unittest.main()
