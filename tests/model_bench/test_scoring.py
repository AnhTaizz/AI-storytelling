import unittest

from tools.model_bench.scoring import score


class ScoringTests(unittest.TestCase):
    def test_deterministic_scores(self):
        for method, gold, answer, expected in (
            ("exact", {"x": False, "y": 1}, {"y": 1, "x": False}, 1),
            ("exact", False, 0, 0),
            ("set_f1", [], [], 1),
            ("set_f1", ["A", "B"], ["A", "A", "C"], 0.5),
            ("set_f1", ["A"], "A", 0),
            ("order_kendall", [], [], 1),
            ("order_kendall", ["A"], ["A"], 1),
            ("order_kendall", ["A", "B", "C"], ["B", "A", "C"], 2 / 3),
            ("order_kendall", ["A", "B"], ["B", "A"], 0),
            ("order_kendall", ["A", "B"], ["A", "A"], 0),
            ("order_kendall", ["A", "B"], ["A", "X"], 0),
            ("order_kendall", ["A", "B"], ["A"], 0),
            ("json_schema", {"schema": {"type": "integer"}}, 2, 1),
            ("json_schema", {"schema": {"type": "integer"}}, True, 0),
        ):
            with self.subTest(method=method, gold=gold, answer=answer):
                result = score({"scoring_method": method, "gold": gold}, answer)
                expected_result = {"score": expected, "review": None}
                if method in {"set_f1", "order_kendall"}:
                    duplicates = [{"item": "A", "count": 2}] if isinstance(answer, list) and answer.count("A") == 2 else []
                    expected_result["duplicate_predictions"] = duplicates
                self.assertEqual(result, expected_result)

    def test_human_row_remains_unscored(self):
        case = {"id": "review-1", "scoring_method": "rubric_human", "gold": None, "rubric": ["grounding"]}
        result = score(case, "candidate")
        self.assertIsNone(result["score"])
        self.assertEqual(result["review"], {"case_id": "review-1", "candidate": "candidate",
                                             "rubric": ["grounding"], "human_score": None, "notes": ""})
