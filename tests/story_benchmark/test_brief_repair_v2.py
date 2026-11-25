import copy
import json
import unittest

from tools.story_benchmark import brief_repair_v2 as experiment


class RepairExperimentTests(unittest.TestCase):
    def test_held_back_gold_and_full_repair_preflight(self):
        cases = list(experiment.held_back_cases())
        self.assertEqual(len({case["name"] for case in cases}), 8)
        initial_strata = []
        for case in cases:
            with self.subTest(case=case["name"]):
                chapter = case["chapter"]
                self.assertEqual(experiment.validate(case["reference"], chapter), ([], []))
                hard, soft = experiment.validate(case["initial"], chapter)
                initial_strata.append("hard" if hard else "soft" if soft else "clean")
        self.assertCountEqual(initial_strata, ["clean", "soft"] + ["hard"] * 6)
        report = experiment.preflight()
        estimates = [count for row in report["cases"] for count in row["c0_echo_input_estimates"]]
        self.assertEqual(len(estimates), 14)
        self.assertLessEqual(max(estimates), report["input_estimate_limit"])
        self.assertLessEqual(report["input_estimate_limit"] + report["output_reserve"], 8_000)

    def test_matched_offline_arms_and_full_validation(self):
        rows = experiment.demo()
        for row in rows:
            with self.subTest(case=row["case"], arm=row["arm"]):
                self.assertEqual(row["hard_errors"], [])
                self.assertEqual(row["evidence_coverage"], 1)
                self.assertEqual(row["event_semantic_accuracy"], 1)
                self.assertEqual(row["tokens"], None if row["requests"] else 0)
        calls = {(r["case"], r["arm"]): len(r["requests"]) for r in rows}
        summaries = experiment.summarize(rows)
        self.assertEqual([row["model_calls"] for row in summaries], [4, 5, 3, 2])
        self.assertEqual([row["hard_error_rate"] for row in summaries], [0, 0, 0, 0])
        self.assertEqual(calls["structure", "C1"], 1)
        self.assertEqual(calls["structure", "C2"], 0)
        self.assertEqual(calls["atomicity", "C2"], 1)
        self.assertEqual(calls["atomicity", "C3"], 0)
        self.assertEqual(calls["uncertainty", "C3"], 1)

    def test_bad_patch_cannot_escape_scope_or_replace_usable_prior(self):
        case = experiment.fixture("atomicity")
        original = copy.deepcopy(case["initial"])
        def corrupt(request):
            self.assertIn("source", request["user"])
            self.assertIn("dependencies", request["user"])
            return {"raw_content": '{"chapter_summary":"changed"}'}
        best, metrics = experiment.compare(case, "C1", corrupt)
        self.assertEqual(original, best)
        self.assertEqual(case["initial"], original)
        self.assertEqual(metrics["rollbacks"], 2)
        self.assertTrue(metrics["soft_errors"])

    def test_revalidates_evidence_and_preserves_original_candidate(self):
        case = experiment.fixture("atomicity")
        invalid = copy.deepcopy(case["reference"]["characters"][0]["facts"])
        invalid[0]["evidence"] = ["1.99"]
        best, metrics = experiment.compare(
            case, "C2",
            lambda _: {"raw_content": json.dumps({"/characters/0/facts": invalid})},
        )
        self.assertEqual(best, case["initial"])
        self.assertTrue(all(request["hard"] for request in metrics["requests"]))
        self.assertEqual(metrics["rollback_rate"], 1)

    def test_lossless_structure_repair_does_not_skip_semantic_check(self):
        case = experiment.fixture("combined")
        for usage, reasoning, total in (
            ({"prompt_token_count": 13}, None, None),
            ({"prompt_tokens": 13, "completion_tokens_details": {"reasoning_tokens": 3},
              "completion_tokens": 9, "total_tokens": 22}, 6, 44),
        ):
            with self.subTest(usage=usage):
                best, metrics = experiment.compare(
                    case, "C2", lambda _: {"raw_content": "{}", "usage_metadata": usage},
                )
                self.assertIsNone(best)
                self.assertTrue(metrics["normalized"])
                self.assertFalse(metrics["recovered"])
                self.assertEqual(metrics["token_totals"]["input"], 26)
                self.assertEqual(metrics["token_totals"]["reasoning"], reasoning)
                self.assertEqual(metrics["token_totals"]["total"], total)
                self.assertTrue(all(request["paths"] == ["/events/1"] for request in metrics["requests"]))

    def test_semantic_and_evidence_metrics_detect_regressions(self):
        case = experiment.fixture("uncertainty")
        obj = copy.deepcopy(case["reference"])
        obj["events"][1]["participants"] = []
        obj["events"][1]["evidence"] = ["1.1"]
        self.assertLess(experiment.score(obj, case)[0], 1)
        self.assertLess(experiment.score(obj, case)[1], 1)
