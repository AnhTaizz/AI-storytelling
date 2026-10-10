"""Offline tests for the structural retention metrics (M4-04B4E). Hand-made JSON only."""
import copy
import json
from pathlib import Path
import unittest

from tools.story_extraction import m4_04b4e_p4_1_retention_metrics_v1 as retention


def record(handle, **fields):
    return {"handle": handle, **fields}


def draft(**collections):
    base = {"draft_version": "STORY_EXTRACTION_DRAFT_V1_1"}
    base.update({name: [] for name in retention.COLLECTIONS})
    base.update(collections)
    return base


def sample():
    """Two mentions, two entities, two propositions that refer to them, two assertions."""
    return draft(
        evidence=[record("EV1", quote="a")],
        mentions=[record("M1", quote="a"), record("M2", quote="b")],
        entities=[record("E_NEW_1", kind="CHARACTER"), record("E_NEW_2", kind="LOCATION")],
        propositions=[
            record("PROP1", predicate="RefersTo", args={"mention": {"kind": "MENTION", "handle": "M1"},
                                                        "entity": {"kind": "ENTITY", "handle": "E_NEW_1"}}),
            record("PROP2", predicate="RefersTo", args={"mention": {"kind": "MENTION", "handle": "M2"},
                                                        "entity": {"kind": "ENTITY", "handle": "E_NEW_2"}}),
        ],
        assertions=[
            record("A1", proposition_handle="PROP1", support={"evidence_sets": [{"evidence_handles": ["EV1"]}]}),
            record("A2", proposition_handle="PROP2", support={"derivations": [{"premise_handles": ["A1"]}]}),
        ],
    )


def raw(value):
    return json.dumps(value, sort_keys=True)


def finding(code, collection=None, handle=None, path=None, locator=None, **detail):
    return {"code": code, "record_collection": collection, "record_handle": handle, "schema_path": path,
            "record_locator": locator or ("VERIFIED_UNIQUE_RECORD" if handle else "NOT_RECORD_SCOPED"),
            "structural_detail": detail}


def diagnostic(*findings):
    return {"findings": list(findings)} if findings else None


def without(value, **removed):
    result = copy.deepcopy(value)
    for collection, handles in removed.items():
        result[collection] = [item for item in result[collection] if item["handle"] not in handles]
    return result


class DraftProfileTests(unittest.TestCase):
    def test_an_empty_draft_is_an_empty_output(self):
        profile = retention.draft_profile(True, draft())
        self.assertEqual(retention.PROFILE_FIELDS, tuple(profile))
        self.assertEqual((True, 0, list(retention.COLLECTIONS), [retention.WARNING_EMPTY_OUTPUT]),
                         (profile["empty_output"], profile["total_records"], profile["empty_collections"],
                          retention.output_warnings(profile)))
        self.assertEqual({name: 0 for name in retention.COLLECTIONS}, profile["record_counts"])

    def test_counts_by_each_of_the_seven_collections(self):
        profile = retention.draft_profile(True, sample())
        self.assertEqual({"evidence": 1, "mentions": 2, "entities": 2, "events": 0, "anchors": 0, "propositions": 2,
                          "assertions": 2}, profile["record_counts"])
        self.assertEqual((9, False, ["events", "anchors"], []),
                         (profile["total_records"], profile["empty_output"], profile["empty_collections"],
                          retention.output_warnings(profile)))
        self.assertEqual(7, len(retention.COLLECTIONS))

    def test_a_response_that_is_not_a_draft_is_not_called_empty(self):
        for parsed, value in ((False, None), (True, []), (True, "text"), (True, {}), (True, {"mentions": []}),
                              (True, {**draft(), "events": "none"}), (True, None)):
            profile = retention.draft_profile(parsed, value)
            self.assertFalse(profile["empty_output"], repr(value)[:40])
        partial = retention.draft_profile(True, {**draft(), "events": {"handle": "EVT1"}})
        self.assertEqual((["events"], None), (partial["collections_not_arrays"], partial["record_counts"]["events"]))
        self.assertEqual((False, False), (retention.draft_profile(False, None)["parsed"],
                                          retention.draft_profile(True, [])["is_draft_object"]))

    def test_unusable_and_duplicated_handles_are_counted(self):
        value = draft(mentions=[record("M1"), record("M1"), {"quote": "x"}, record(""), record(7), "M9"])
        profile = retention.draft_profile(True, value)
        self.assertEqual((6, 4, 1), (profile["record_counts"]["mentions"], profile["records_without_a_usable_handle"],
                                     profile["duplicated_handles"]))


class ComparisonTests(unittest.TestCase):
    def test_identical_bytes(self):
        text = raw(sample())
        comparison = retention.compare_drafts(text, text)
        self.assertEqual(retention.COMPARISON_FIELDS, tuple(comparison))
        self.assertEqual((True, True, True, False, False),
                         (comparison["identical_bytes"], comparison["identical_parsed_content"], comparison["comparable"],
                          comparison["record_count_decreased"], comparison["counts_unchanged_but_content_changed"]))
        self.assertEqual({"primary_records": 9, "repair_records": 9, "count_difference": 0, "retained": 9, "removed": 0,
                          "added": 0, "unchanged": 9, "changed_in_place": 0}, comparison["totals"])
        for item in comparison["by_collection"].values():
            self.assertEqual(retention.COLLECTION_COMPARISON_FIELDS, tuple(item))

    def test_same_content_in_other_bytes_is_not_identical_bytes(self):
        comparison = retention.compare_drafts(json.dumps(sample()), json.dumps(sample(), indent=3))
        self.assertEqual((False, True, 9), (comparison["identical_bytes"], comparison["identical_parsed_content"],
                                            comparison["totals"]["unchanged"]))

    def test_partial_deletion_is_reported_by_collection(self):
        repaired = without(sample(), mentions=["M2"], propositions=["PROP2"], assertions=["A2"])
        comparison = retention.compare_drafts(raw(sample()), raw(repaired))
        mentions = comparison["by_collection"]["mentions"]
        self.assertEqual((2, 1, -1, ["M1"], ["M2"], [], ["M1"], []),
                         tuple(mentions[name] for name in retention.COLLECTION_COMPARISON_FIELDS[1:]))
        self.assertEqual((-3, 6, 3, 0, True), (comparison["totals"]["count_difference"], comparison["totals"]["retained"],
                                               comparison["totals"]["removed"], comparison["totals"]["added"],
                                               comparison["record_count_decreased"]))
        self.assertEqual(0, comparison["by_collection"]["entities"]["count_difference"])

    def test_extensive_deletion_and_an_all_empty_repair(self):
        comparison = retention.compare_drafts(raw(sample()), raw(draft()))
        self.assertEqual((True, False, 9, 0, -9), (comparison["repair_is_empty_output"], comparison["primary_is_empty_output"],
                                                   comparison["totals"]["removed"], comparison["totals"]["retained"],
                                                   comparison["totals"]["count_difference"]))
        for name in ("evidence", "mentions", "entities", "propositions", "assertions"):
            self.assertEqual(0, comparison["by_collection"][name]["repair_count"])
        both_empty = retention.compare_drafts(raw(draft()), raw(draft()))
        self.assertEqual((True, True, False), (both_empty["primary_is_empty_output"], both_empty["repair_is_empty_output"],
                                               both_empty["record_count_decreased"]))

    def test_unchanged_counts_do_not_mean_unchanged_content(self):
        replaced = copy.deepcopy(sample())
        replaced["mentions"][0]["quote"] = "something else entirely"
        replaced["entities"][1]["kind"] = "OBJECT"
        comparison = retention.compare_drafts(raw(sample()), raw(replaced))
        self.assertEqual((0, 9, 7, 2, True, False),
                         (comparison["totals"]["count_difference"], comparison["totals"]["retained"],
                          comparison["totals"]["unchanged"], comparison["totals"]["changed_in_place"],
                          comparison["counts_unchanged_but_content_changed"], comparison["record_count_decreased"]))
        self.assertEqual(["M1"], comparison["by_collection"]["mentions"]["changed_in_place_records"])
        self.assertEqual(["E_NEW_2"], comparison["by_collection"]["entities"]["changed_in_place_records"])

    def test_a_record_replaced_under_a_new_handle_is_one_removal_and_one_addition(self):
        swapped = copy.deepcopy(sample())
        swapped["mentions"][1] = record("M7", quote="b")
        comparison = retention.compare_drafts(raw(sample()), raw(swapped))
        mentions = comparison["by_collection"]["mentions"]
        self.assertEqual((0, ["M2"], ["M7"], ["M1"]), (mentions["count_difference"], mentions["removed_handles"],
                                                       mentions["added_handles"], mentions["retained_handles"]))
        self.assertTrue(comparison["counts_unchanged_but_content_changed"])
        added = copy.deepcopy(sample())
        added["mentions"].append(record("M3", quote="c"))
        self.assertEqual((1, 1, False), (retention.compare_drafts(raw(sample()), raw(added))["totals"]["added"],
                                         retention.compare_drafts(raw(sample()), raw(added))["totals"]["count_difference"],
                                         retention.compare_drafts(raw(sample()), raw(added))["record_count_decreased"]))

    def test_records_are_not_matched_when_handles_cannot_identify_them(self):
        ambiguous = copy.deepcopy(sample())
        ambiguous["mentions"][1]["handle"] = "M1"
        comparison = retention.compare_drafts(raw(ambiguous), raw(sample()))
        mentions = comparison["by_collection"]["mentions"]
        self.assertEqual((False, 2, 2, 0, [], [], [], [], []),
                         tuple(mentions[name] for name in retention.COLLECTION_COMPARISON_FIELDS))
        self.assertFalse(comparison["comparable"])
        self.assertTrue(comparison["by_collection"]["entities"]["comparable"])
        for bad in ("{", "", None, "[]", "\"text\""):
            other = retention.compare_drafts(bad, raw(sample()))
            self.assertEqual((False, False, 9), (other["comparable"], other["identical_bytes"],
                                                 other["totals"]["repair_records"]))
        self.assertFalse(retention.compare_drafts(None, None)["identical_bytes"])

    def test_inputs_are_never_changed_and_results_are_deterministic(self):
        primary, repaired = sample(), without(sample(), mentions=["M2"])
        before = (copy.deepcopy(primary), copy.deepcopy(repaired))
        first = retention.repair_effect(raw(primary), raw(repaired), None, None, primary_valid=False, repair_valid=True)
        second = retention.repair_effect(raw(primary), raw(repaired), None, None, primary_valid=False, repair_valid=True)
        self.assertEqual(before, (primary, repaired))
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_public_comparison_holds_counts_only(self):
        comparison = retention.compare_drafts(raw(sample()), raw(without(sample(), mentions=["M2"])))
        public = retention.public_comparison(comparison)
        text = json.dumps(public)
        for handle in ("M1", "M2", "PROP1", "E_NEW_1", "EV1", "A1"):
            self.assertNotIn(f'"{handle}"', text)
        self.assertEqual(1, public["by_collection"]["mentions"]["removed"])
        self.assertEqual(comparison["totals"], public["totals"])
        self.assertNotIn("removed_handles", text)


class RepairEffectTests(unittest.TestCase):
    def effect(self, repaired, primary_findings, repair_findings=(), repair_valid=True, primary=None):
        primary = sample() if primary is None else primary
        return retention.repair_effect(raw(primary), raw(repaired), diagnostic(*primary_findings),
                                       diagnostic(*repair_findings), primary_valid=False, repair_valid=repair_valid)

    def test_a_finding_cleared_with_its_record_kept(self):
        corrected = copy.deepcopy(sample())
        corrected["mentions"][0]["occurrence"] = 2
        result = self.effect(corrected, [finding("AMBIGUOUS_QUOTE", "mentions", "M1")])
        effect = result["effect"]
        self.assertEqual(retention.EFFECT_FIELDS, tuple(effect))
        self.assertEqual((1, 1, 0, 0, True, False, 1, 0, 0, True, False),
                         (effect["primary_findings"], effect["primary_findings_cleared"],
                          effect["primary_findings_remaining"], effect["new_findings"],
                          effect["all_primary_findings_cleared"], effect["new_findings_appeared"],
                          effect["cleared_with_the_record_kept"], effect["cleared_with_the_record_removed"],
                          effect["changed_records_not_named_by_a_finding"], effect["structural_validity_increased"],
                          effect["structural_validity_increased_while_record_count_decreased"]))
        self.assertEqual([retention.WARNING_CONTENT_CHANGED_COUNTS_SAME], effect["warnings"])

    def test_a_finding_cleared_by_removing_its_record_and_what_depended_on_it(self):
        removed = without(sample(), mentions=["M1"], propositions=["PROP1"], assertions=["A1", "A2"])
        result = self.effect(removed, [finding("AMBIGUOUS_QUOTE", "mentions", "M1")])
        effect = result["effect"]
        self.assertEqual((0, 1, True), (effect["cleared_with_the_record_kept"], effect["cleared_with_the_record_removed"],
                                        effect["structural_validity_increased_while_record_count_decreased"]))
        # PROP1 refers to M1, A1 to PROP1, A2 to A1: a chain of dependents, none of them unexplained.
        self.assertEqual({"NAMED_BY_A_PRIMARY_FINDING": ["M1"], "DEPENDS_ON_A_NAMED_RECORD": ["A1", "A2", "PROP1"],
                          "NOT_EXPLAINED_BY_ANY_FINDING": []}, result["removals"])
        self.assertEqual([retention.WARNING_VALID_WITH_FEWER_RECORDS, retention.WARNING_CLEARED_BY_REMOVAL],
                         effect["warnings"])

    def test_removals_that_no_finding_explains(self):
        removed = without(sample(), mentions=["M1", "M2"], propositions=["PROP1", "PROP2"], assertions=["A1", "A2"],
                          entities=["E_NEW_2"], evidence=["EV1"])
        result = self.effect(removed, [finding("AMBIGUOUS_QUOTE", "mentions", "M1")])
        self.assertEqual(["M1"], result["removals"]["NAMED_BY_A_PRIMARY_FINDING"])
        self.assertEqual(["A1", "A2", "PROP1"], result["removals"]["DEPENDS_ON_A_NAMED_RECORD"])
        self.assertEqual(["EV1", "E_NEW_2", "M2", "PROP2"], result["removals"]["NOT_EXPLAINED_BY_ANY_FINDING"])
        self.assertEqual({"NAMED_BY_A_PRIMARY_FINDING": 1, "DEPENDS_ON_A_NAMED_RECORD": 3,
                          "NOT_EXPLAINED_BY_ANY_FINDING": 4}, result["effect"]["removed_records_by_explanation"])
        self.assertIn(retention.WARNING_UNEXPLAINED_REMOVAL, result["effect"]["warnings"])
        everything = self.effect(draft(), [finding("AMBIGUOUS_QUOTE", "mentions", "M1")])
        self.assertIn(retention.WARNING_REPAIR_EMPTY, everything["effect"]["warnings"])
        self.assertEqual(9, sum(everything["effect"]["removed_records_by_explanation"].values()))

    def test_records_a_finding_references_or_positions_count_as_named(self):
        corrected = copy.deepcopy(sample())
        corrected["entities"][1]["kind"] = "CHARACTER"
        by_reference = self.effect(corrected, [finding("ARGUMENT_ENTITY_KIND_NOT_ALLOWED", "propositions", "PROP2",
                                                       referenced_record_handle="E_NEW_2")])
        self.assertEqual(0, by_reference["effect"]["changed_records_not_named_by_a_finding"])
        unnamed = self.effect(corrected, [finding("ARGUMENT_ENTITY_KIND_NOT_ALLOWED", "propositions", "PROP2")])
        self.assertEqual(1, unnamed["effect"]["changed_records_not_named_by_a_finding"])
        self.assertIn(retention.WARNING_UNEXPLAINED_CHANGE, unnamed["effect"]["warnings"])
        primary = sample()
        primary["mentions"][1]["handle"] = "M02"
        positioned = [finding("DRAFT_SCHEMA_FAILURE", "mentions", None, "mentions/1/handle", "SCHEMA_PATH_INDEX")]
        self.assertEqual({"M02"}, retention.named_handles(diagnostic(*positioned), raw(primary)))
        renamed = self.effect(sample(), positioned, primary=primary)
        self.assertEqual(["M02"], renamed["removals"]["NAMED_BY_A_PRIMARY_FINDING"])
        self.assertEqual(set(), retention.named_handles(None, raw(primary)))
        self.assertEqual({"PROP2", "PROP1"}, retention.named_handles(diagnostic(
            finding("DUPLICATE_CONCRETE_PROPOSITION_CONTENT", "propositions", "PROP2",
                    identical_to_record_handle="PROP1")), raw(sample())))

    def test_an_identical_repair_clears_nothing(self):
        blocked = [finding("AMBIGUOUS_QUOTE", "mentions", "M1")]
        effect = self.effect(sample(), blocked, blocked, repair_valid=False)["effect"]
        self.assertEqual((True, 0, 1, 0, False, False, [retention.WARNING_IDENTICAL]),
                         (effect["identical_bytes"], effect["primary_findings_cleared"],
                          effect["primary_findings_remaining"], effect["new_findings"],
                          effect["all_primary_findings_cleared"], effect["structural_validity_increased"],
                          effect["warnings"]))

    def test_a_repair_that_trades_one_blocker_for_another(self):
        changed = copy.deepcopy(sample())
        changed["mentions"][0]["occurrence"] = 1
        changed["entities"][1]["kind"] = "OBJECT"
        effect = self.effect(changed, [finding("AMBIGUOUS_QUOTE", "mentions", "M1")],
                             [finding("ARGUMENT_ENTITY_KIND_NOT_ALLOWED", "propositions", "PROP2"),
                              finding("CANONICAL_CONFORMANCE_FAILURE")], repair_valid=False)["effect"]
        self.assertEqual((1, 0, 2, True, True, False),
                         (effect["primary_findings_cleared"], effect["primary_findings_remaining"], effect["new_findings"],
                          effect["all_primary_findings_cleared"], effect["new_findings_appeared"],
                          effect["structural_validity_increased"]))
        self.assertEqual(1, effect["changed_records_not_named_by_a_finding"])

    def test_repeated_look_alike_findings_are_counted_one_by_one(self):
        twice = [finding("DUPLICATE_HANDLE", "mentions", None, "mentions/<UNVERIFIED>", "UNAVAILABLE")] * 2
        effect = self.effect(sample(), twice, twice[:1], repair_valid=False)["effect"]
        self.assertEqual((2, 1, 1, 0), (effect["primary_findings"], effect["primary_findings_cleared"],
                                        effect["primary_findings_remaining"], effect["new_findings"]))
        self.assertEqual(2, len(retention.finding_signatures(diagnostic(*twice))))
        self.assertEqual([], retention.finding_signatures(None))

    def test_warnings_are_not_verdicts_and_there_is_no_threshold(self):
        definition = retention.definition()
        self.assertEqual(("M4_P4_1_STRUCTURAL_RETENTION_METRICS_V1", "NONE_DEFINED", False, False),
                         (definition["metrics"], definition["threshold"], definition["gold_used"],
                          definition["edits_or_pads_predictions"]))
        self.assertEqual("RESEARCH_WARNING_METRICS_NOT_EVIDENCE_OF_SEMANTIC_ERROR_NO_THRESHOLD", definition["interpretation"])
        result = self.effect(without(sample(), mentions=["M2"]), [finding("AMBIGUOUS_QUOTE", "mentions", "M1")])
        text = json.dumps(result)
        for forbidden in ("score", "threshold", "pass", "fail", "ratio", "percent", "semantic_error", "wrong"):
            self.assertNotIn(forbidden, text.lower())
        for value in result["effect"].values():
            self.assertNotIsInstance(value, float)
        self.assertEqual(set(result["effect"]["warnings"]) | set(retention.WARNINGS), set(retention.WARNINGS))
        source = Path(retention.__file__).read_text(encoding="utf-8")
        for forbidden in ("gold_archive", "evaluate_", "import os", "open(", "Path(", "requests", "random"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
