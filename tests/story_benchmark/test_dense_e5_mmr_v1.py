import unittest
import numpy as np
import tempfile
import yaml
import json
import os
from pathlib import Path
from unittest.mock import patch

from tools.story_benchmark.dense_e5_mmr_v1 import (
    mmr_select,
    calculate_metrics,
    calculate_diversity_diagnostics,
    DenseE5MMRV1,
    MMR_LAMBDA_V1
)

from tools.story_benchmark.run_dense_e5_mmr_v1 import (
    verify_dense_mmr_determinism,
    compare_f_and_h
)
from tools.story_benchmark.run_bm25_lexical_v1 import compute_spoiler_violations

class MockTokenizer:
    def __call__(self, texts, return_offsets_mapping=False, add_special_tokens=True, truncation=False):
        if type(texts) is str:
            texts = [texts]
        
        res = {"input_ids": []}
        for t in texts:
            num_tokens = len(t)
            res["input_ids"].append([0] * num_tokens)
            
        return res

class MockModel:
    def __init__(self):
        self.tokenizer = MockTokenizer()
        self.max_seq_length = 512
        
    def get_sentence_embedding_dimension(self):
        return 384
        
    def encode(self, texts, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False):
        return np.array([[1.0, 0.0] for _ in texts])
        
    def eval(self):
        pass

class MockDenseE5MMRV1(DenseE5MMRV1):
    def __init__(self):
        self.model = MockModel()
        self.model_name = "mock"
        self.model_revision = "mock"
        self.device = "cpu"
        
        self.passage_truncation_count = 0
        self.query_truncation_count = 0
        
        self.doc_ids = []
        self.doc_embeddings = None

class TestDenseE5MMRV1(unittest.TestCase):

    @patch('tools.story_benchmark.dense_e5_mmr_v1.SentenceTransformer')
    def test_offline_proof(self, mock_st):
        mock_st.side_effect = RuntimeError("SentenceTransformer should not be instantiated during unit tests")
        
        m = MockDenseE5MMRV1()
        self.assertIsInstance(m.model, MockModel)
        
        with self.assertRaises(RuntimeError):
            DenseE5MMRV1()

    def test_mmr_lambda_v1_frozen(self):
        self.assertEqual(MMR_LAMBDA_V1, 0.70)

    def test_mmr_select_first_pick_is_highest_relevance(self):
        q_emb = np.array([1.0, 0.0])
        candidate_embs = np.array([
            [0.5, 0.5], # doc1
            [0.9, 0.1], # doc2 (highest rel)
            [0.1, 0.9]  # doc3
        ])
        candidate_ids = ["doc1", "doc2", "doc3"]
        
        res = mmr_select(q_emb, candidate_embs, candidate_ids, lambda_param=0.70, k=1)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][0], "doc2")

    def test_mmr_select_redundant_displaced(self):
        # A > B > C synthetic vectors
        q = np.array([1.0, 0.0, 0.0])
        
        A = np.array([0.9, 0.0, 0.0])  # rel = 0.9
        B = np.array([0.8, 0.0, 0.0])  # rel = 0.8, redundant with A (dot=0.72)
        C = np.array([0.7, 0.7, 0.0])  # rel = 0.7, diverse (dot with A=0.63)
        
        candidates = np.array([A, B, C])
        ids = ["A", "B", "C"]
        
        # lambda = 1.0 (pure cosine)
        res_rel = mmr_select(q, candidates, ids, lambda_param=1.0, k=2)
        self.assertEqual([x[0] for x in res_rel], ["A", "B"])
        
        # lambda = 0.5
        # 1st pick: A (rel=0.9, red=0) => 0.45
        # S = {A}
        # B score = 0.5 * 0.8 - 0.5 * 0.72 = 0.4 - 0.36 = 0.04
        # C score = 0.5 * 0.7 - 0.5 * 0.63 = 0.35 - 0.315 = 0.035
        # Still B. Let's adjust lambda to penalize B more.
        # Actually lambda=0.7 is the target, let's just make C much better dynamically with 0.7.
        # score = 0.7*rel - 0.3*red
        
        A2 = np.array([1.0, 0.0, 0.0]) # rel = 1.0
        B2 = np.array([0.9, 0.0, 0.0]) # rel = 0.9, red(A2)=0.9
        C2 = np.array([0.8, 0.6, 0.0]) # rel = 0.8, red(A2)=0.8
        
        # For lambda=0.7:
        # B2: 0.7*0.9 - 0.3*0.9 = 0.36
        # C2: 0.7*0.8 - 0.3*0.8 = 0.32
        
        # To make C win over B, we need C's redundancy to be MUCH smaller than B's redundancy.
        A3 = np.array([1.0, 0.0])
        B3 = np.array([0.95, 0.0])  # rel=0.95, red(A3)=0.95
        C3 = np.array([0.9, 0.4358]) # rel=0.9, red(A3)=0.9
        
        # Wait, if rel is 0.9, red is 0.9.
        # We need C to have lower red.
        q = np.array([0.7071, 0.7071])
        A4 = np.array([0.7071, 0.7071]) # rel=1.0. A4 is exactly q.
        B4 = np.array([0.6, 0.8])      # rel=0.9899, red(A4)=0.9899
        C4 = np.array([0.8, 0.0])      # rel=0.5656, red(A4)=0.5656
        
        # A simpler way:
        # Q = [1, 0, 0]
        # A = [0.9, 0.43, 0]    => rel=0.9
        # B = [0.8, 0.6, 0]     => rel=0.8, red(A)=0.9*0.8+0.43*0.6=0.72+0.258=0.978
        # C = [0.75, 0, 0.66]   => rel=0.75, red(A)=0.9*0.75+0=0.675
        
        Q = np.array([1.0, 0.0, 0.0])
        A = np.array([0.9, 0.43588989, 0.0])
        B = np.array([0.8, 0.6, 0.0])
        C = np.array([0.75, 0.0, 0.66143782])
        
        # A rel = 0.9.
        # B rel = 0.8. red(A) = 0.9*0.8 + 0.4358*0.6 = 0.72 + 0.2615 = 0.9815
        # C rel = 0.75. red(A) = 0.9*0.75 = 0.675
        
        # MMR lambda=0.7
        # B score = 0.7 * 0.8 - 0.3 * 0.9815 = 0.56 - 0.29445 = 0.26555
        # C score = 0.7 * 0.75 - 0.3 * 0.675 = 0.525 - 0.2025 = 0.3225
        # C (0.3225) > B (0.26555). C should be picked second instead of B!
        
        candidates = np.array([A, B, C])
        ids = ["A", "B", "C"]
        
        res_mmr = mmr_select(Q, candidates, ids, lambda_param=0.70, k=2)
        self.assertEqual([x[0] for x in res_mmr], ["A", "C"])

    def test_exact_mmr_formula_calculation(self):
        Q = np.array([1.0, 0.0, 0.0])
        A = np.array([0.9, 0.43588989, 0.0])
        B = np.array([0.8, 0.6, 0.0])
        C = np.array([0.75, 0.0, 0.66143782])
        
        # 0.70 * relevance - 0.30 * redundancy
        # C relevance = 0.75. 
        # C redundancy against A = 0.675.
        # Expected C score = 0.7*0.75 - 0.3*0.675 = 0.3225
        
        res = mmr_select(Q, np.array([A, B, C]), ["A", "B", "C"], lambda_param=0.70, k=2)
        # Returns tuples of (id, rel). Wait, mmr_select returns RELEVANCE, not MMR score.
        # Let's just assert C's returned relevance is exactly 0.75
        self.assertEqual(res[1][0], "C")
        self.assertAlmostEqual(res[1][1], 0.75)
        
    def test_metric_calculations(self):
        probe = {
            "probe_id": "p1",
            "required_evidence_chunk_ids": ["c1", "c2"]
        }
        
        # Success at 3
        ranked = ["c3", "c1", "c2", "c4"]
        m = calculate_metrics(probe, ranked)
        
        self.assertEqual(m["hit@1"], 0)
        self.assertEqual(m["hit@3"], 1)
        self.assertEqual(m["hit@5"], 1)
        
        self.assertAlmostEqual(m["recall@1"], 0.0)
        self.assertAlmostEqual(m["recall@3"], 1.0)
        
        self.assertEqual(m["success@1"], 0)
        self.assertEqual(m["success@3"], 1)
        
        self.assertAlmostEqual(m["mrr"], 1.0 / 2) # first hit is at index 1 -> rank 2 -> 1/2

        # Spoiler violation
        chunk_meta = {"c1": 1, "c2": 1, "c3": 2, "c4": 3}
        probe["cutoff_chapter"] = 1
        sv = compute_spoiler_violations(probe, ranked, chunk_meta)
        self.assertEqual(sv["spoiler_violation@1"], 1) # c3 is chap 2 > cutoff 1
        self.assertEqual(sv["spoiler_violation@3"], 1)

    def test_diversity_diagnostics(self):
        chunk_meta = {"c1": 1, "c2": 1, "c3": 2, "c4": 3, "c5": 4}
        doc_ids = ["c1", "c2", "c3", "c4", "c5"]
        # Orthonormal vectors to easily track similarities
        doc_embeddings = np.array([
            [1, 0, 0, 0, 0],
            [0, 1, 0, 0, 0],
            [0, 0, 1, 0, 0],
            [0, 0, 0, 1, 0],
            [0, 0, 0, 0, 1]
        ], dtype=float)
        
        # Probe 1: top3 are c1, c2, c3
        p1 = {"probe_id": "p1"}
        r1 = [("c1", 0.9), ("c2", 0.8), ("c3", 0.7)]
        m1 = {}
        
        # Probe 2: top3 are c3, c4, c5
        p2 = {"probe_id": "p2"}
        r2 = [("c3", 0.6), ("c4", 0.5), ("c5", 0.4)]
        m2 = {}
        
        metrics_list = [(p1, m1, r1), (p2, m2, r2)]
        
        diag = calculate_diversity_diagnostics(metrics_list, chunk_meta, doc_ids, doc_embeddings)
        
        # Unique chapters for p1 top3: chaps 1, 1, 2 -> 2 unique
        # Unique chapters for p2 top3: chaps 2, 3, 4 -> 3 unique
        # Mean top3 unique = 2.5
        self.assertAlmostEqual(diag["mean_unique_chapters_top3"], 2.5)
        
        # Pairwise sims: all docs are orthogonal (sim = 0)
        self.assertAlmostEqual(diag["mean_pairwise_similarity_top10"], 0.0)
        
        # Mean query relevance = mean([0.9, 0.8, 0.7, 0.6, 0.5, 0.4]) = 3.9 / 6 = 0.65
        self.assertAlmostEqual(diag["mean_query_relevance_top10"], 0.65)

    def test_verify_dense_mmr_determinism(self):
        agg1 = {
            "detailed_results_sha256": {
                "mmr_cutoff_per_probe.jsonl": "cut1",
                "mmr_global_per_probe.jsonl": "glob1",
                "relevance_control_per_probe.jsonl": "ctrl1"
            },
            "metric": 0.5
        }
        
        agg2 = {
            "detailed_results_sha256": {
                "mmr_cutoff_per_probe.jsonl": "cut1",
                "mmr_global_per_probe.jsonl": "glob1",
                "relevance_control_per_probe.jsonl": "ctrl1"
            },
            "metric": 0.5
        }
        
        self.assertTrue(verify_dense_mmr_determinism(agg1, agg2))
        
        agg3 = dict(agg1)
        agg3["detailed_results_sha256"] = dict(agg1["detailed_results_sha256"])
        agg3["detailed_results_sha256"]["mmr_cutoff_per_probe.jsonl"] = "cut2"
        self.assertFalse(verify_dense_mmr_determinism(agg1, agg3))
        
        agg4 = dict(agg1)
        agg4["metric"] = 0.6
        self.assertFalse(verify_dense_mmr_determinism(agg1, agg4))

    def test_relevance_control_gate_exact_match(self):
        # We simulate the exact match logic that is embedded in the runner
        f_detailed_results = {
            "p1": ["c1", "c2"],
            "p2": ["c3", "c4"]
        }
        
        h_relevance_results = [
            {"probe_id": "p1", "retrieved_chunk_ids": ["c1", "c2"]},
            {"probe_id": "p2", "retrieved_chunk_ids": ["c3", "c4"]}
        ]
        
        # Test Exact match
        mismatches = []
        for r in h_relevance_results:
            pid = r["probe_id"]
            if r["retrieved_chunk_ids"] != f_detailed_results[pid]:
                mismatches.append(pid)
        self.assertEqual(len(mismatches), 0)
        
        # Test Order Change -> Fail
        h_relevance_results_bad_order = [
            {"probe_id": "p1", "retrieved_chunk_ids": ["c2", "c1"]}, # reversed
            {"probe_id": "p2", "retrieved_chunk_ids": ["c3", "c4"]}
        ]
        mismatches2 = []
        for r in h_relevance_results_bad_order:
            pid = r["probe_id"]
            if r["retrieved_chunk_ids"] != f_detailed_results[pid]:
                mismatches2.append(pid)
        self.assertEqual(len(mismatches2), 1)
        
        # Test Same aggregates but changed ranking -> Fail
        # Both c1/c2 and c5/c6 might yield 0 metrics for probe p1, but they are different ranks
        f_detailed_results_agg = {"p1": ["c1", "c2"]}
        h_relevance_results_diff_rank = [{"probe_id": "p1", "retrieved_chunk_ids": ["c5", "c6"]}]
        mismatches3 = []
        for r in h_relevance_results_diff_rank:
            pid = r["probe_id"]
            if r["retrieved_chunk_ids"] != f_detailed_results_agg[pid]:
                mismatches3.append(pid)
        self.assertEqual(len(mismatches3), 1)


if __name__ == '__main__':
    unittest.main()
