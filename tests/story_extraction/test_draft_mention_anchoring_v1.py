"""Synthetic exact-span anchoring and dependency-safe ghost pruning."""
from copy import deepcopy
import json
import unittest

from tools.story_extraction import draft_mention_anchoring_v1 as anchoring


def fixture(text="Ada spoke.", quote="Ada", **locator):
    """Small V1.1-shaped graph; all prose is invented here."""
    draft = {"draft_version": "STORY_EXTRACTION_DRAFT_V1_1",
        "evidence": [{"handle": "EV1", "passage_handle": "P2", "quote": text, "role": "DEPICTION"}],
        "mentions": [{"handle": "M1", "passage_handle": "P1", "quote": quote,
                      "role": "DEPICTION", **locator}],
        "entities": [{"handle": "E_NEW_1", "kind": "CHARACTER"}], "events": [], "anchors": [],
        "propositions": [{"handle": "PROP1", "predicate": "RefersTo", "args": {
            "mention": {"kind": "MENTION", "handle": "M1"},
            "entity": {"kind": "ENTITY", "handle": "E_NEW_1"}}}],
        "assertions": [{"handle": "A1", "proposition_handle": "PROP1", "polarity": "AFFIRMED",
            "epistemic_status": "EXPLICIT", "support": {"evidence_sets": [
                {"label": "SUFFICIENT", "evidence_handles": ["EV1"]}], "derivations": []}}]}
    prepared = {"passages": [{"handle": "P1", "text": "Elsewhere.", "use": "EVIDENCE_ELIGIBLE"},
                              {"handle": "P2", "text": text, "use": "EVIDENCE_ELIGIBLE"}]}
    return draft, prepared


class MentionAnchoringTests(unittest.TestCase):
    def apply(self, draft, prepared):
        before = deepcopy((draft, prepared))
        result, report = anchoring.anchor_mentions(draft, prepared)
        self.assertEqual((draft, prepared), before)
        self.assertEqual(anchoring.anchor_mentions(draft, prepared), (result, report))
        self.assertEqual(json.loads(json.dumps(report)), report)
        self.assertEqual(set(report), {"mentions", "removed"})
        self.assertEqual(set(report["mentions"]), set(anchoring.OUTCOMES))
        self.assertEqual(set(report["removed"]), {"propositions", "assertions", "mentions"})
        self.assertTrue(all(type(n) is int for group in report.values() for n in group.values()))
        if isinstance(draft, dict):
            self.assertEqual(sum(report["mentions"].values()), len(draft.get("mentions", [])))
        return result, report

    def test_anchor_uses_evidence_position_and_local_overlapping_occurrences(self):
        for case in ("global occurrence", "wrong passage", "context only", "repeated local", "overlap"):
            with self.subTest(case=case):
                draft, prepared = fixture(occurrence=7)
                expected = 1
                if case == "global occurrence":
                    draft["mentions"][0]["passage_handle"] = "P2"
                    prepared["passages"][0]["text"] = "Ada Ada Ada"
                elif case == "context only":
                    prepared["passages"][0].update(text="Ada", use="CONTEXT_ONLY")
                elif case in ("repeated local", "overlap"):
                    text, quote, evidence = (("Ada left. Ada spoke.", "Ada", "Ada spoke.")
                        if case == "repeated local" else ("aaaa", "aa", "aa"))
                    draft, prepared = fixture(text, quote, occurrence=7)
                    draft["evidence"][0]["quote"] = evidence
                    if case == "overlap":
                        draft["evidence"][0]["occurrence"] = 3
                        expected = 3
                    else:
                        expected = 2
                # Repeated citations and duplicate evidence records count as one span.
                draft["evidence"].append({**draft["evidence"][0], "handle": "EV2"})
                draft["assertions"][0]["support"]["evidence_sets"] += [
                    {"label": "PARTIAL", "evidence_handles": ["EV2", "EV1"]}]
                result, report = self.apply(draft, prepared)
                wanted = deepcopy(draft)
                wanted["mentions"][0].update(passage_handle="P2", occurrence=expected)
                self.assertEqual(result, wanted)
                self.assertEqual(report["mentions"]["ANCHORED_TO_EVIDENCE"], 1)

    def test_multiple_matching_spans_or_occurrences_and_non_reference_users_stay(self):
        for case in ("twice", "two spans", "nested spans", "non RefersTo", "mixed users", "no users"):
            with self.subTest(case=case):
                draft, prepared = fixture("Ada Ada" if case == "twice" else "Ada spoke.")
                if case in ("two spans", "nested spans"):
                    draft["evidence"].append({**draft["evidence"][0], "handle": "EV2",
                        **({"quote": "Ada"} if case == "nested spans" else {"passage_handle": "P3"})})
                    prepared["passages"].append({"handle": "P3", "text": "Ada spoke.", "use": "EVIDENCE_ELIGIBLE"})
                    draft["assertions"][0]["support"]["evidence_sets"].append(
                        {"label": "CORROBORATING", "evidence_handles": ["EV2"]})
                elif case in ("non RefersTo", "mixed users"):
                    if case == "mixed users":
                        draft["propositions"].append(deepcopy(draft["propositions"][0]))
                    draft["propositions"][-1]["predicate"] = "Other"
                elif case == "no users":
                    draft["propositions"] = []
                result, report = self.apply(draft, prepared)
                self.assertEqual(result, draft)
                self.assertEqual(report["mentions"]["LEFT_UNLOCATED"], 1)

    def test_location_requires_eligibility_and_valid_occurrence(self):
        for text, occurrence, located in (("Ada", None, True), ("Ada", 1, True),
                ("Ada Ada", 2, True), ("Ada Ada", None, False), ("Ada", 0, False),
                ("Ada", True, False), ("Ada", 2, False), ("Ada", "1", False)):
            with self.subTest(text=text, occurrence=occurrence):
                draft, prepared = fixture(text, **({} if occurrence is None else {"occurrence": occurrence}))
                draft["mentions"][0]["passage_handle"] = "P2"
                draft["assertions"][0]["support"]["evidence_sets"] = []
                result, report = self.apply(draft, prepared)
                self.assertEqual(result, draft)
                self.assertEqual(report["mentions"]["ALREADY_LOCATED" if located else "LEFT_UNLOCATED"], 1)

    def test_ghost_pruning_keeps_other_records_and_handles_multiple_users(self):
        draft, prepared = fixture(quote="Ghost")
        draft["mentions"].append({**draft["mentions"][0], "handle": "M2", "quote": "Ada", "passage_handle": "P2"})
        draft["propositions"].append({**deepcopy(draft["propositions"][0]), "handle": "PROP2"})
        draft["assertions"].append({**deepcopy(draft["assertions"][0]), "handle": "A2", "proposition_handle": "PROP2"})
        # A second ghost ensures removals do not skip subsequent mentions.
        draft["mentions"].append({**draft["mentions"][0], "handle": "M3"})
        draft["propositions"].append({"handle": "PROP3", "predicate": "RefersTo", "args": {
            "mention": {"kind": "MENTION", "handle": "M3"}}})
        result, report = self.apply(draft, prepared)
        self.assertEqual(result, {**draft, "mentions": [draft["mentions"][1]], "propositions": [], "assertions": []})
        self.assertEqual(report, {"mentions": {"ANCHORED_TO_EVIDENCE": 0, "PRUNED_UNLOCATABLE": 2,
            "LEFT_UNLOCATED": 0, "ALREADY_LOCATED": 1}, "removed": {"propositions": 3, "assertions": 2, "mentions": 2}})
        self.assertIsNot(result["entities"], draft["entities"])

    def test_pruning_checks_all_schema_reference_fields_but_not_literals(self):
        for case in ("non RefersTo", "argument", "assertion", "derivation", "validity derivation", "alternative", "event", "anchor", "evidence", "literal", "internal"):
            with self.subTest(case=case):
                draft, prepared = fixture(quote="Ghost")
                other = {"handle": "A2", "proposition_handle": "PROP9", "support": {}}
                if case == "non RefersTo":
                    draft["propositions"].append({**deepcopy(draft["propositions"][0]),
                                                   "handle": "PROP2", "predicate": "Other"})
                elif case == "argument":
                    draft["propositions"].append({"handle": "PROP2", "args": {"p": {"kind": "PROPOSITION", "handle": "PROP1"}}})
                elif case == "assertion":
                    # Every assertion on the removed proposition is itself removed;
                    # reference that assertion through another support's premises.
                    other["support"] = {"derivations": [{"premise_handles": ["A1"]}]}
                elif case in ("derivation", "validity derivation"):
                    support = {"derivations": [{"premise_handles": ["PROP1"]}]}
                    if case == "derivation":
                        other["support"] = support
                    else:
                        other["validity"] = {"start": {"kind": "ANCHOR", "anchor_handle": "T1", "support": support}}
                elif case == "alternative":
                    other["textual_ambiguity"] = {"alternative_proposition_handles": ["PROP1"]}
                elif case in ("event", "anchor"):
                    draft["events" if case == "event" else "anchors"].append(
                        {"handle": "EVT1", "anchor_handle" if case == "event" else "event_handle": "PROP1"})
                elif case == "evidence":
                    other["support"] = {"evidence_sets": [{"evidence_handles": ["A1"]}]}
                elif case == "literal":
                    draft["propositions"].append({"handle": "PROP2", "args": {
                        "label": {"kind": "LITERAL", "value": "PROP1"}}})
                else:
                    draft["assertions"][0]["support"]["derivations"] = [{"premise_handles": ["A1", "PROP1"]}]
                draft["assertions"].append(other)
                result, report = self.apply(draft, prepared)
                allowed = case in ("literal", "internal")
                self.assertEqual(report["mentions"]["PRUNED_UNLOCATABLE"], int(allowed))
                if not allowed:
                    self.assertEqual(result, draft)

    def test_only_located_cited_evidence_counts_and_own_ambiguity_never_prunes(self):
        for case in ("context evidence", "missing evidence", "ambiguous evidence", "bad occurrence", "uncited", "own ambiguous", "own bad occurrence", "context ghost"):
            with self.subTest(case=case):
                draft, prepared = fixture()
                if case == "context evidence":
                    prepared["passages"][1]["use"] = "CONTEXT_ONLY"
                elif case == "missing evidence":
                    draft["evidence"][0]["quote"] = "Absent"
                elif case in ("ambiguous evidence", "bad occurrence"):
                    prepared["passages"][1]["text"] *= 2
                    if case == "bad occurrence":
                        draft["evidence"][0]["occurrence"] = 3
                elif case == "uncited":
                    draft["assertions"][0]["support"]["evidence_sets"] = []
                elif case in ("own ambiguous", "own bad occurrence"):
                    prepared["passages"][0]["text"] = "Ada Ada"
                    draft["evidence"][0]["quote"] = "Absent"
                    if case == "own bad occurrence":
                        draft["mentions"][0]["occurrence"] = 7
                else:
                    prepared["passages"][0].update(text="Ada", use="CONTEXT_ONLY")
                    draft["evidence"][0]["quote"] = "Absent"
                result, report = self.apply(draft, prepared)
                pruned = not case.startswith("own")
                self.assertEqual(report["mentions"]["PRUNED_UNLOCATABLE"], int(pruned))
                if not pruned:
                    self.assertEqual(result, draft)

    def test_malformed_inputs_are_left_to_validation(self):
        for draft in (None, [], {}, {"mentions": None}, {"mentions": [None, {},
                {"handle": "M1", "quote": "", "passage_handle": "P1"},
                {"handle": "M2", "quote": "Ada", "passage_handle": []},
                {"handle": "M3", "quote": 3, "passage_handle": "P1"}]}):
            with self.subTest(draft=draft):
                before = deepcopy(draft)
                result, report = anchoring.anchor_mentions(draft, {"passages": [None, {}, {"handle": []}]})
                self.assertEqual(draft, before)
                self.assertEqual(result, before)
                self.assertEqual(report["removed"], {"propositions": 0, "assertions": 0, "mentions": 0})


if __name__ == "__main__":
    unittest.main()
