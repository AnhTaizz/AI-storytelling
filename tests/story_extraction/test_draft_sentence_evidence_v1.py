"""Sentence evidence over synthetic passages."""
from copy import deepcopy
import json
import unittest

from tests.story_extraction import test_run_m4_p4_dev_v1 as runner_tests
from tools.story_extraction.draft_sentence_evidence_v1 import OUTCOMES, widen_to_sentence
from tools.story_extraction.run_m4_04b3g_fv1_predictions_v1 import validate_raw


def prepared(text, use="EVIDENCE_ELIGIBLE"):
    return {"passages": [{"handle": "P1", "text": text, "use": use}]}


def item(number, quote, **fields):
    return {"handle": f"EV{number}", "passage_handle": "P1", "quote": quote,
            "role": "DEPICTION", **fields}


def draft_with(evidence, *claims):
    return {"evidence": evidence,
            "propositions": [{"handle": f"PROP{i}", "predicate": predicate}
                             for i, (predicate, _) in enumerate(claims, 1)],
            "assertions": [{"proposition_handle": f"PROP{i}", "support": {"evidence_sets": [
                {"label": "SUFFICIENT", "evidence_handles": handles}]}}
                for i, (_, handles) in enumerate(claims, 1)]}


class SentenceEvidenceTests(unittest.TestCase):
    def test_enclosing_sentence_boundaries(self):
        cases = (
            ("音がした。ミラが走った。次へ。", "走った", "ミラが走った。", 1, 1, "WIDENED"),
            ("「来て！」とミラが呼んだ。", "来て", "「来て！」", 1, 1, "WIDENED"),
            ("「来て！」とミラが呼んだ。", "「来て", "「来て！」", 1, 1, "WIDENED"),
            ("「来て！」とミラが呼んだ。", "て！」", "「来て！」", 1, 1, "WIDENED"),
            ("「A。『B』に「C？」と聞く」と言った。", "C", "「A。『B』に「C？」と聞く」", 1, 1, "WIDENED"),
            ("前！「A。B」と言った。", "言った", "「A。B」と言った。", 1, 1, "WIDENED"),
            ("前！「A。B」と言った。", "B」と言った", "「A。B」と言った。", 1, 1, "WIDENED"),
            ("先?\u3000 \tミラが走った！次", "走った", "ミラが走った！", 1, 1, "WIDENED"),
            ("前\r\n\u3000灯りが消えた\n暗い夜", "消えた", "灯りが消えた", 1, 1, "WIDENED"),
            ("前\r\n\u3000灯りが消えた\n暗い夜", "暗い", "暗い夜", 1, 1, "WIDENED"),
            ("走った。走った。", "走った", "走った。", 2, 2, "WIDENED"),
            ("走った。去った。", "走った。去った", "走った。去った", 1, 1, "REFUSED_MULTI_SENTENCE"),
            ("「走った\n逃げた」", "走った\n逃げた", "走った\n逃げた", 1, 1, "REFUSED_MULTI_SENTENCE"),
            ("走った。去った。", "走った。", "走った。", 1, 1, "ALREADY_SENTENCE"),
            ("走った。\n\u3000", "\u3000", "\u3000", 1, 1, "REFUSED_NOT_LOCATED"),
        )
        for text, quote, target, occurrence, target_occurrence, outcome in cases:
            with self.subTest(text=text, quote=quote):
                draft = draft_with([item(1, quote, occurrence=occurrence)], ("Occurred", ["EV1"]))
                result, report = widen_to_sentence(draft, prepared(text))
                self.assertEqual([(e["quote"], e["occurrence"]) for e in result["evidence"]],
                                 [(target, target_occurrence)])
                self.assertEqual(report["by_predicate"]["Occurred"], {k: int(k == outcome) for k in OUTCOMES})
                widened = int(outcome == "WIDENED")
                self.assertEqual((report["evidence_items_added"], report["evidence_items_removed"]),
                                 (widened, widened))

    def test_set_deduplication_reuse_and_shared_references(self):
        evidence = [item(1, "ミラ"), item(2, "走った"), item(3, "ミラが走った。"),
                    item(4, "先の雨", role="NARRATION"), item(5, "先の雨")]
        draft = draft_with(evidence, ("Occurred", ["EV2", "EV1", "EV4", "EV5", "EV3"]),
                           ("RefersTo", ["EV1"]), ("NamedAs", ["EV1"]), ("Participates", ["EV2"]))
        last = draft["assertions"][-1]
        last["support"]["evidence_sets"].append({"label": "PARTIAL", "evidence_handles": ["EV2"]})
        # A dangling reference reserves EV6 even though it has no definition.
        last["validity"] = {"start": {"support": {"evidence_sets": [
            {"label": "SUFFICIENT", "evidence_handles": ["EV5", "EV6"]}]}}}
        inputs = prepared("先の雨！ミラが走った。")
        original = deepcopy((draft, inputs))
        result, report = widen_to_sentence(draft, inputs)
        self.assertEqual((draft, inputs), original)
        self.assertEqual(widen_to_sentence(draft, inputs), (result, report))
        evidence_after = [*evidence[:3], evidence[4], item(7, "先の雨！", role="NARRATION", occurrence=1),
                          item(8, "先の雨！", occurrence=1)]
        self.assertEqual(result["evidence"], evidence_after)
        claims = result["assertions"]
        self.assertEqual(claims[0]["support"]["evidence_sets"][0]["evidence_handles"], ["EV3", "EV7", "EV8"])
        self.assertEqual(claims[1:3], draft["assertions"][1:3])
        self.assertEqual(claims[3]["support"]["evidence_sets"], [
            {"label": "SUFFICIENT", "evidence_handles": ["EV3"]},
            last["support"]["evidence_sets"][1]])
        self.assertEqual(claims[3]["validity"], last["validity"])
        expected = {key: int(key == "WIDENED") for key in OUTCOMES}
        self.assertEqual(report, {"by_predicate": {"Occurred": expected, "Participates": expected},
                                  "evidence_items_added": 2, "evidence_items_removed": 1})
        self.assertEqual(list(report["by_predicate"]), ["Occurred", "Participates"])
        self.assertEqual(json.loads(json.dumps(report)), report)
        included, _ = widen_to_sentence(draft, inputs, excluded_predicates=("Occurred", "Participates"))
        self.assertEqual(included["assertions"][1]["support"]["evidence_sets"][0]["evidence_handles"], ["EV3"])

    def test_refusals_and_precedence_across_sets(self):
        evidence = [item(1, "同じ"), item(2, "同じ。同じ"), item(3, "同じ。", occurrence=1),
                    item(4, "先頭"), item(5, "末尾", passage_handle="P2")]
        inputs = prepared("先頭。同じ。同じ。")
        inputs["passages"] += [{"handle": "P2", "text": "末尾。", "use": "CONTEXT_ONLY"}]
        for cited, expected in (([["EV2"]], "REFUSED_MULTI_SENTENCE"),
                                ([["EV2"], ["EV1", "EV5"]], "REFUSED_NOT_LOCATED"),
                                ([["EV2"], ["EV9"], ["EV3"]], "ALREADY_SENTENCE"),
                                ([["EV2"], ["EV9"], ["EV3"], ["EV4"]], "WIDENED"),
                                ([[]], "REFUSED_NOT_LOCATED"), ([], "REFUSED_NOT_LOCATED")):
            with self.subTest(cited=cited):
                draft = draft_with(evidence, ("TemporalRelation", []))
                draft["assertions"][0]["support"]["evidence_sets"] = [
                    {"label": "SUFFICIENT", "evidence_handles": handles} for handles in cited]
                result, report = widen_to_sentence(draft, inputs)
                self.assertEqual(report["by_predicate"]["TemporalRelation"][expected], 1)
                if expected != "WIDENED":
                    self.assertEqual(result, draft)
        self.assertEqual(widen_to_sentence(None, inputs),
                         (None, {"by_predicate": {}, "evidence_items_added": 0, "evidence_items_removed": 0}))

    def test_widened_draft_validates(self):
        fixture = runner_tests.DevelopmentRunnerTests
        fixture.setUpClass()
        draft = deepcopy(fixture.draft)
        verb = next(e for e in draft["evidence"] if e["quote"] == "Mira opened the gate.")
        verb["quote"] = "opened"
        context = fixture.context
        prepared_input = runner_tests.runner.prepare_story_extraction_draft_v1_1(context)
        result, report = widen_to_sentence(draft, prepared_input)
        self.assertEqual(report["by_predicate"]["Occurred"]["WIDENED"], 1)
        _, batch, validation = validate_raw(json.dumps(result), context)
        self.assertIsNotNone(batch, validation)
        self.assertTrue(validation["pass"], validation)
