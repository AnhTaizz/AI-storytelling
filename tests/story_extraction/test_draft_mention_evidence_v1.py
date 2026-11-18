"""Synthetic mention-evidence repairs and compiler compatibility."""
from copy import deepcopy
import json
import unittest

from tests.story_extraction import test_run_m4_p4_dev_v1 as runner_fixture
from tools.story_extraction.draft_mention_evidence_v1 import narrow_mention_evidence


OUTCOMES = ("NARROWED", "ALREADY_EXACT", "REFUSED_NOT_LOCATED", "REFUSED_AMBIGUOUS",
            "REFUSED_NOT_CONTAINED", "REFUSED_MULTI_ITEM_SET")


def evidence(handle, quote, *, role="IN_WORLD_REPORT", passage="P1", **fields):
    return {"handle": handle, "passage_handle": passage, "quote": quote, "role": role, **fields}


def group(*handles, label="SUFFICIENT"):
    return {"label": label, "evidence_handles": list(handles)}


def example():
    prepared = {"passages": [
        {"handle": "P1", "use": "EVIDENCE_ELIGIBLE", "text": "Mira called. Mira bowed."},
        {"handle": "P2", "use": "EVIDENCE_ELIGIBLE", "text": "Mira bowed."},
        {"handle": "P3", "use": "CONTEXT_ONLY", "text": "Mira bowed."},
    ]}
    entity = {"kind": "ENTITY", "handle": "E_NEW_1"}
    draft = {
        "evidence": [evidence("EV1", "Mira bowed.")],
        "mentions": [evidence("M1", "Mira", role="DEPICTION", occurrence=2)],
        "propositions": [
            {"handle": "PROP1", "predicate": "RefersTo", "args": {
                "mention": {"kind": "MENTION", "handle": "M1"}, "entity": entity}},
            {"handle": "PROP2", "predicate": "NamedAs", "args": {"entity": entity,
                "name": {"kind": "LITERAL", "value_type": "STRING", "value": "Mira"}}},
        ],
        "assertions": [
            {"handle": f"A{i}", "proposition_handle": f"PROP{i}",
             "support": {"evidence_sets": [group("EV1")], "derivations": []}}
            for i in (1, 2)
        ],
    }
    return draft, prepared


class MentionEvidenceTests(unittest.TestCase):
    def test_narrowing_is_pure_deterministic_and_reuses_new_exact_item(self):
        draft, prepared = example()
        original = deepcopy((draft, prepared))
        resolved, report = narrow_mention_evidence(draft, prepared)
        self.assertEqual((draft, prepared), original)
        self.assertEqual((resolved, report), narrow_mention_evidence(draft, prepared))
        self.assertEqual(resolved["evidence"], [evidence("EV2", "Mira", occurrence=2)])
        for assertion in resolved["assertions"]:
            self.assertEqual(assertion["support"]["evidence_sets"], [group("EV2")])
        self.assertEqual(report, {
            "by_predicate": {p: dict.fromkeys(OUTCOMES, 0) | {"NARROWED": 1}
                             for p in ("RefersTo", "NamedAs")},
            "evidence_items_added": 1, "evidence_items_removed": 1,
        })
        self.assertEqual(json.loads(json.dumps(report)), report)
        exact, exact_report = narrow_mention_evidence(resolved, prepared)
        self.assertEqual(exact, resolved)
        self.assertEqual(exact_report, {
            "by_predicate": {p: dict.fromkeys(OUTCOMES, 0) | {"ALREADY_EXACT": 1}
                             for p in ("RefersTo", "NamedAs")},
            "evidence_items_added": 0, "evidence_items_removed": 0,
        })
        resolved["mentions"][0]["quote"] = "changed"
        self.assertEqual((draft, prepared), original)

    def test_selected_predicate_keeps_shared_wide_item_and_reuses_existing_exact_role(self):
        for selected_index, predicate in enumerate(("RefersTo", "NamedAs")):
            with self.subTest(predicate=predicate):
                draft, prepared = example()
                draft["evidence"] += [evidence("EV2", "Mira", occurrence=1),
                                      evidence("EV3", "Mira", role="DEPICTION", occurrence=2),
                                      evidence("EV4", "Mira", occurrence=2)]
                narrowed, report = narrow_mention_evidence(draft, prepared, predicates=(predicate,))
                self.assertEqual(narrowed["evidence"], draft["evidence"])
                self.assertEqual(narrowed["assertions"][selected_index]["support"]["evidence_sets"], [group("EV4")])
                self.assertEqual(narrowed["assertions"][1 - selected_index], draft["assertions"][1 - selected_index])
                self.assertEqual(report, {"by_predicate": {predicate: dict.fromkeys(OUTCOMES, 0) | {"NARROWED": 1}},
                                         "evidence_items_added": 0, "evidence_items_removed": 0})

    def test_refusals_preserve_cited_evidence(self):
        cases = (
            ("RefersTo", "unlocated mention", "REFUSED_NOT_LOCATED"),
            ("RefersTo", "unknown mention handle", "REFUSED_NOT_LOCATED"),
            ("NamedAs", "unlocated evidence", "REFUSED_NOT_LOCATED"),
            ("NamedAs", "ineligible passage", "REFUSED_NOT_LOCATED"),
            ("NamedAs", "invalid name", "REFUSED_NOT_LOCATED"),
            ("NamedAs", "repeated name", "REFUSED_AMBIGUOUS"),
            ("NamedAs", "absent name", "REFUSED_NOT_CONTAINED"),
            ("RefersTo", "wrong occurrence", "REFUSED_NOT_CONTAINED"),
            ("RefersTo", "different passage", "REFUSED_NOT_CONTAINED"),
            ("RefersTo", "target wider than evidence", "REFUSED_NOT_CONTAINED"),
            ("RefersTo", "multiple items", "REFUSED_MULTI_ITEM_SET"),
            ("NamedAs", "no sufficient set", "REFUSED_NOT_CONTAINED"),
        )
        for predicate, scenario, expected in cases:
            with self.subTest(scenario=scenario):
                draft, prepared = example()
                item = draft["evidence"][0]
                mention = draft["mentions"][0]
                refers, named = (prop["args"] for prop in draft["propositions"])
                if scenario == "unlocated mention":
                    del mention["occurrence"]
                elif scenario == "unknown mention handle":
                    refers["mention"]["handle"] = "M_EXISTING_1"
                elif scenario == "unlocated evidence":
                    item["occurrence"] = 2
                elif scenario == "ineligible passage":
                    item["passage_handle"] = "P3"
                elif scenario == "invalid name":
                    named["name"]["value"] = ""
                elif scenario == "repeated name":
                    item["quote"] = prepared["passages"][0]["text"]
                elif scenario == "absent name":
                    named["name"]["value"] = "mira"
                elif scenario == "wrong occurrence":
                    mention["occurrence"] = 1
                elif scenario == "different passage":
                    item["passage_handle"] = "P2"
                elif scenario == "target wider than evidence":
                    mention.update(quote="Mira bowed.", occurrence=1)
                    item.update(quote="bowed.")
                elif scenario == "multiple items":
                    draft["evidence"].append(evidence("EV2", "called."))
                    draft["assertions"][0]["support"]["evidence_sets"] = [group("EV1", "EV2")]
                elif scenario == "no sufficient set":
                    draft["assertions"][1]["support"]["evidence_sets"] = [group("EV1", label="PARTIAL")]
                narrowed, report = narrow_mention_evidence(draft, prepared, predicates=(predicate,))
                self.assertEqual(narrowed, draft)
                self.assertEqual(report, {"by_predicate": {predicate: dict.fromkeys(OUTCOMES, 0) | {expected: 1}},
                                         "evidence_items_added": 0, "evidence_items_removed": 0})

    def test_all_eligible_sets_are_narrowed_and_other_support_keeps_original_items(self):
        draft, prepared = example()
        prepared["passages"][0]["text"] += " Later Mira left."
        draft["evidence"] += [evidence("EV2", "Mira left."), evidence("EV3", "Mira", occurrence=1)]
        unchanged = [group("EV1", "EV3"), group("EV1", label="CORROBORATING"),
                     group("EV1", label="CONTEXT"), group("EV1", label="PARTIAL"), group("EV3")]
        draft["assertions"][1]["support"]["evidence_sets"] = [group("EV1"), group("EV2"), *unchanged]
        draft["assertions"][1]["validity"] = {"start": {"support": {
            "evidence_sets": [group("EV2")], "derivations": []}}}
        # An invalid existing reference also reserves its handle during allocation.
        draft["assertions"][0]["support"]["evidence_sets"].append(group("EV4", label="PARTIAL"))
        narrowed, report = narrow_mention_evidence(draft, prepared, predicates=("NamedAs",))
        self.assertEqual(narrowed["evidence"], draft["evidence"] + [
            evidence("EV5", "Mira", occurrence=2), evidence("EV6", "Mira", occurrence=3)])
        self.assertEqual(narrowed["assertions"][1]["support"]["evidence_sets"],
                         [group("EV5"), group("EV6"), *unchanged])
        self.assertEqual(narrowed["assertions"][1]["validity"], draft["assertions"][1]["validity"])
        self.assertEqual(report["by_predicate"]["NamedAs"]["NARROWED"], 1)
        self.assertEqual((report["evidence_items_added"], report["evidence_items_removed"]), (2, 0))

    def test_non_object_draft_and_malformed_records_reach_validation(self):
        for draft in ([], None, "invalid"):
            with self.subTest(draft=draft):
                self.assertEqual(narrow_mention_evidence(draft, {}, predicates=()), (draft, {
                    "by_predicate": {}, "evidence_items_added": 0, "evidence_items_removed": 0}))
        draft, prepared = example()
        draft["evidence"].append({"handle": []})
        draft["assertions"][0]["support"]["evidence_sets"].append(group())
        draft["assertions"].append({"proposition_handle": []})
        narrowed, report = narrow_mention_evidence(draft, prepared)
        self.assertIn({"handle": []}, narrowed["evidence"])
        self.assertEqual(narrowed["assertions"][-1], draft["assertions"][-1])
        self.assertEqual(report["evidence_items_removed"], 1)

    def test_narrowed_runner_fixture_passes_validate_raw(self):
        fixture = runner_fixture.DevelopmentRunnerTests
        fixture.setUpClass()
        draft = runner_fixture.widened_mention_draft(fixture.draft)
        runner = runner_fixture.runner
        prepared = runner.prepare_story_extraction_draft_v1_1(fixture.context)
        narrowed, report = narrow_mention_evidence(draft, prepared)
        self.assertEqual(report["by_predicate"]["RefersTo"]["NARROWED"], 1)
        self.assertEqual((report["evidence_items_added"], report["evidence_items_removed"]), (1, 1))
        _, batch, validation = runner.validate_raw(json.dumps(narrowed), fixture.context)
        self.assertTrue(validation["pass"], validation)
        records = batch["candidate_records"]
        ref = records["assertions"][0]["support"]["evidence_sets"][0]["evidence_ref_ids"][0]
        self.assertEqual(ref, records["mentions"][0]["evidence_ref_id"])
