import unittest

from tools.story_benchmark.bm25_lexical_v1 import calculate_metrics
from tools.story_benchmark.multi_gold_metrics import (
    GoldEvidenceValidationError,
    calculate_probe_metrics,
    normalize_gold_evidence_sets,
)


def legacy_calculate_metrics(probe, ranked_results):
    required = set(probe["required_evidence_chunk_ids"])
    metrics = {}
    for k in (1, 3, 5, 10):
        top_k = ranked_results[:k]
        recall = sum(chunk_id in top_k for chunk_id in required) / len(required)
        metrics[f"hit@{k}"] = int(any(chunk_id in required for chunk_id in top_k))
        metrics[f"recall@{k}"] = recall
        metrics[f"success@{k}"] = int(recall == 1.0)
    metrics["mrr"] = next(
        (
            1.0 / rank
            for rank, chunk_id in enumerate(ranked_results, 1)
            if chunk_id in required
        ),
        0.0,
    )
    return metrics


class TestMultiGoldMetrics(unittest.TestCase):
    def test_complete_alternative_succeeds(self):
        probe = {
            "gold_evidence_sets": [["A", "B", "C"], ["A", "B", "D"]]
        }
        metrics = calculate_probe_metrics(probe, ["A", "B", "D"])
        self.assertEqual(metrics["hit@5"], 1)
        self.assertEqual(metrics["recall@5"], 1.0)
        self.assertEqual(metrics["success@5"], 1)

    def test_shorter_complete_best_path_succeeds(self):
        probe = {"gold_evidence_sets": [["A", "B", "C"], ["A", "D"]]}
        metrics = calculate_probe_metrics(probe, ["A", "D"])
        self.assertEqual(metrics["recall@5"], 1.0)
        self.assertEqual(metrics["success@5"], 1)

    def test_partial_paths_use_best_recall(self):
        probe = {"gold_evidence_sets": [["A", "B", "C"], ["D", "E"]]}
        metrics = calculate_probe_metrics(probe, ["A", "B", "D"])
        self.assertAlmostEqual(metrics["recall@5"], 2 / 3)
        self.assertEqual(metrics["success@5"], 0)

    def test_single_gold_is_exactly_legacy_equivalent(self):
        legacy_probe = {
            "required_evidence_chunk_ids": ["A", "B", "C"],
            "cutoff_chapter": 30,
        }
        rankings = [
            ["X", "A", "Y", "B", "Z", "C"],
            ["X", "Y", "Z"],
            ["C", "B", "A"],
        ]
        for ranking in rankings:
            with self.subTest(ranking=ranking):
                legacy = legacy_calculate_metrics(legacy_probe, ranking)
                new = calculate_probe_metrics(legacy_probe, ranking)
                wrapper = calculate_metrics(legacy_probe, ranking)
                self.assertEqual(new, legacy)
                self.assertEqual(wrapper, legacy)

    def test_duplicate_gold_sets_are_rejected(self):
        with self.assertRaises(GoldEvidenceValidationError):
            normalize_gold_evidence_sets(
                {"gold_evidence_sets": [["A", "B"], ["A", "B"]]}
            )

    def test_empty_gold_set_is_rejected(self):
        with self.assertRaises(GoldEvidenceValidationError):
            normalize_gold_evidence_sets({"gold_evidence_sets": [[]]})

    def test_duplicate_chunks_inside_gold_set_are_rejected(self):
        with self.assertRaises(GoldEvidenceValidationError):
            normalize_gold_evidence_sets(
                {"gold_evidence_sets": [["A", "A", "B"]]}
            )


if __name__ == "__main__":
    unittest.main()
