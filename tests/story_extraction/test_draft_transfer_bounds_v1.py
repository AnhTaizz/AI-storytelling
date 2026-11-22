"""Transfer bounds over synthetic possession assertions."""
from copy import deepcopy
import json
import unittest

from tests.story_extraction.test_run_m4_p4_dev_v1 import transfer_case
from tools.story_extraction.draft_transfer_bounds_v1 import OUTCOMES, bound_by_transfer
from tools.story_extraction.run_m4_04b3g_fv1_predictions_v1 import validate_raw


def associated(draft, predicate):
    handles = {p["handle"] for p in draft["propositions"] if p["predicate"] == predicate}
    return [a for a in draft["assertions"] if a["proposition_handle"] in handles]


def anchored(event):
    return {"kind": "ANCHOR", "anchor_handle": event["anchor_handle"]}


class TransferBoundsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.draft, cls.case, _ = transfer_case()

    def test_matching_roles_polarity_and_existing_bounds(self):
        cases = (
            ("both", "BOTH_SET", ("first", "second")),
            ("receive", "START_SET", ("first", "open")),
            ("give", "END_SET", ("open", "second")),
            ("wrong item", "NO_TRANSFER", ("open", "open")),
            ("negated theme", "NO_TRANSFER", ("open", "open")),
            ("missing theme", "NO_TRANSFER", ("open", "open")),
            ("already bounded", "ALREADY_BOUND", ("second", "open")),
            ("ambiguous receive", "REFUSED_AMBIGUOUS", ("open", "open")),
            ("ambiguous give", "REFUSED_AMBIGUOUS", ("open", "open")),
            ("negated possession", None, ("open", "open")),
        )
        for scenario, outcome, (start, end) in cases:
            with self.subTest(scenario=scenario):
                draft = deepcopy(self.draft)
                first, second = draft["events"]
                possess, = associated(draft, "Possesses")
                owns, owns_giver = associated(draft, "Owns")
                props = {p["handle"]: p for p in draft["propositions"]}
                if scenario == "receive":
                    second["event_kind"] = "MANIPULATION"
                elif scenario == "give":
                    first["event_kind"] = "MANIPULATION"
                elif scenario == "wrong item":
                    props[possess["proposition_handle"]]["args"]["item"]["handle"] = "E_NEW_99"
                elif scenario in ("negated theme", "missing theme"):
                    for claim in associated(draft, "Participates"):
                        role = props[claim["proposition_handle"]]["args"]["role"]
                        if role["value"] == "THEME":
                            if scenario == "negated theme":
                                claim["polarity"] = "NEGATED"
                            else:
                                role["value"] = "PATIENT"
                elif scenario == "already bounded":
                    possess["validity"]["start"] = anchored(second)
                elif scenario.startswith("ambiguous"):
                    duplicated = first if scenario.endswith("receive") else second
                    draft["events"].append({**duplicated, "handle": "EVT3"})
                    for claim in associated(draft, "Participates"):
                        proposition = props[claim["proposition_handle"]]
                        if proposition["args"]["event"]["handle"] == duplicated["handle"]:
                            duplicate = deepcopy(proposition)
                            duplicate["handle"] += "0"
                            duplicate["args"]["event"]["handle"] = "EVT3"
                            draft["propositions"].append(duplicate)
                            draft["assertions"].append({**claim, "proposition_handle": duplicate["handle"]})
                elif scenario == "negated possession":
                    possess["polarity"] = "NEGATED"
                bounds = {"open": {"kind": "OPEN"}, "first": anchored(first), "second": anchored(second)}
                snapshot = deepcopy((draft, self.case.prepared_input))
                result, report = bound_by_transfer(draft, self.case.prepared_input)
                self.assertEqual((draft, self.case.prepared_input), snapshot)
                self.assertEqual(result["assertions"][draft["assertions"].index(owns_giver)], owns_giver)
                self.assertEqual(report["by_predicate"]["Possesses"], {k: int(k == outcome) for k in OUTCOMES})
                self.assertEqual(associated(result, "Possesses")[0]["validity"],
                                 {"start": bounds[start], "end": bounds[end]})
                if scenario == "both":
                    self.assertEqual(associated(result, "Owns")[0]["validity"],
                                     {"start": anchored(first), "end": {"kind": "OPEN"}})
                    self.assertEqual(report["by_predicate"]["Owns"],
                                     {k: int(k in ("START_SET", "NO_TRANSFER")) for k in OUTCOMES})
                    self.assertEqual(bound_by_transfer(draft, self.case.prepared_input), (result, report))
                    self.assertEqual(json.loads(json.dumps(report)), report)
        _, report = bound_by_transfer(None, {})
        self.assertEqual(report, {"by_predicate": {p: dict.fromkeys(OUTCOMES, 0)
                                                  for p in ("Possesses", "Owns")}})

    def test_two_bounds_require_located_sufficient_occurrence_in_text_order(self):
        for scenario in ("reverse", "tie", "missing", "unlocatable", "passage order", "earliest located"):
            with self.subTest(scenario=scenario):
                draft = deepcopy(self.draft)
                prepared = deepcopy(self.case.prepared_input)
                first, second = associated(draft, "Occurred")
                first_set, second_set = (a["support"]["evidence_sets"][0] for a in (first, second))
                receive, give = (group["evidence_handles"][0] for group in (first_set, second_set))
                if scenario == "reverse":
                    first_set["evidence_handles"], second_set["evidence_handles"] = [give], [receive]
                elif scenario == "tie":
                    first_set["evidence_handles"] = [give]
                elif scenario == "missing":
                    first_set["label"] = "CORROBORATING"
                elif scenario == "unlocatable":
                    first_set["evidence_handles"] = ["EV99"]
                elif scenario == "passage order":
                    source = prepared["passages"][0]
                    prepared["passages"].insert(0, {**source, "handle": "P2"})
                    next(e for e in draft["evidence"] if e["handle"] == give)["passage_handle"] = "P2"
                elif scenario == "earliest located":
                    first_set["evidence_handles"] = ["EV99", give, receive]
                    first["support"]["evidence_sets"].append(
                        {"label": "SUFFICIENT", "evidence_handles": [give]})
                result, report = bound_by_transfer(draft, prepared)
                outcome = "BOTH_SET" if scenario == "earliest located" else "REFUSED_ORDER"
                self.assertEqual(report["by_predicate"]["Possesses"][outcome], 1)
                if outcome == "REFUSED_ORDER":
                    self.assertEqual(associated(result, "Possesses"), associated(draft, "Possesses"))
                self.assertEqual(associated(result, "Owns")[0]["validity"]["start"], anchored(draft["events"][0]))

    def test_bounded_draft_validates(self):
        result, report = bound_by_transfer(self.draft, self.case.prepared_input)
        self.assertEqual(report["by_predicate"]["Possesses"]["BOTH_SET"], 1)
        _, batch, validation = validate_raw(json.dumps(result), self.case.compiler_context)
        self.assertIsNotNone(batch, validation)
        self.assertTrue(validation["pass"], validation)
        self.assertTrue(any(a.get("validity", {}).get("start", {}).get("anchor_id")
                            for a in batch["candidate_records"]["assertions"]))
