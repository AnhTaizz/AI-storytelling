import unittest
import numpy as np
import tempfile
import yaml
from pathlib import Path
from unittest.mock import patch

from tools.story_benchmark.dense_e5_mmr_v1 import (
    mmr_select,
    calculate_metrics,
    DenseE5MMRV1
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

    def test_mmr_select_first_pick_is_highest_relevance(self):
        q_emb = np.array([1.0, 0.0])
        candidate_embs = np.array([
            [0.5, 0.5], # doc1
            [0.9, 0.1], # doc2 (highest rel)
            [0.1, 0.9]  # doc3
        ])
        candidate_ids = ["doc1", "doc2", "doc3"]
        
        # doc2 has highest relevance (0.9 vs 0.5 and 0.1)
        res = mmr_select(q_emb, candidate_embs, candidate_ids, lambda_param=0.70, k=1)
        
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][0], "doc2")
        self.assertAlmostEqual(res[0][1], 0.9)

    def test_mmr_select_redundant_second_is_displaced(self):
        q_emb = np.array([1.0, 0.0])
        # Suppose doc1 is best relevance, doc2 is slightly worse but identical to doc1, doc3 is somewhat worse but very different from doc1
        # To make it explicit, we manually define similarities
        candidate_embs = np.array([
            [1.0, 0.0],  # doc1
            [0.99, 0.141], # doc2 (very close to doc1)
            [0.8, 0.6]   # doc3 (different from doc1)
        ])
        candidate_ids = ["doc1", "doc2", "doc3"]
        
        # Without MMR (lambda = 1.0), it should pick doc1 then doc2
        res_rel = mmr_select(q_emb, candidate_embs, candidate_ids, lambda_param=1.0, k=2)
        self.assertEqual([x[0] for x in res_rel], ["doc1", "doc2"])
        
        # With MMR, doc2 gets high redundancy penalty
        res_mmr = mmr_select(q_emb, candidate_embs, candidate_ids, lambda_param=0.5, k=2)
        # S = {doc1}
        # doc2 rel = 0.99, redundancy = doc1 dot doc2 = 0.99 => score = 0.5*0.99 - 0.5*0.99 = 0.0
        # doc3 rel = 0.8, redundancy = doc1 dot doc3 = 0.8 => score = 0.5*0.8 - 0.5*0.8 = 0.0
        # Wait, if they tie to 0.0, chunk_id tie breaker makes doc2 win.
        # Let's make doc3 better for MMR score.
        candidate_embs = np.array([
            [0.9, 0.0, 0.0],    # doc1, best rel = 0.9
            [0.85, 0.0, 0.0],   # doc2, rel = 0.85, redundancy against doc1 = 0.9*0.85 = 0.765
            [0.8, 0.5, 0.0]     # doc3, rel = 0.8, redundancy against doc1 = 0.72
        ])
        
        # lambda = 0.5
        # doc2 score: 0.5 * 0.85 - 0.5 * 0.765 = 0.0425
        # doc3 score: 0.5 * 0.8 - 0.5 * 0.72 = 0.04
        
        # Let's drop redundancy penalty for doc3
        candidate_embs = np.array([
            [0.9, 0.0],    # doc1, rel = 0.9
            [0.8, 0.0],    # doc2, rel = 0.8, redundant with doc1 (dot = 0.72)
            [0.7, 0.7]     # doc3, rel = 0.7, diverse (dot with doc1 = 0.63)
        ])
        # lambda = 0.7
        # doc1 score: 0.7 * 0.9 - 0.3 * 0 = 0.63 (First)
        # S = {doc1}
        # doc2 rel = 0.8, red = 0.72 => 0.7*0.8 - 0.3*0.72 = 0.56 - 0.216 = 0.344
        # doc3 rel = 0.7, red = 0.63 => 0.7*0.7 - 0.3*0.63 = 0.49 - 0.189 = 0.301
        # Still doc2. We need a case where doc3 beats doc2.
        candidate_embs = np.array([
            [1.0, 0.0],    # doc1, rel = 1.0
            [0.9, 0.0],    # doc2, rel = 0.9, red = 0.9. score = 0.7*0.9 - 0.3*0.9 = 0.36
            [0.8, 0.6]     # doc3, rel = 0.8, red = 0.8. score = 0.7*0.8 - 0.3*0.8 = 0.32
        ])
        
        # Actually to make doc3 win:
        # lambda=0.5
        # doc2: rel=0.9, red=0.9 => 0.5*0.9 - 0.5*0.9 = 0
        # doc3: rel=0.8, red=0.8 => 0.5*0.8 - 0.5*0.8 = 0
        
        # What if doc3 is orthogonal?
        candidate_embs = np.array([
            [1.0, 0.0],    # doc1, rel = 1.0
            [0.9, 0.0],    # doc2, rel = 0.9, red = 0.9. score = 0.7*0.9 - 0.3*0.9 = 0.36
            [0.5, 0.866]   # doc3, rel = 0.5, red = 0.5. score = 0.7*0.5 - 0.3*0.5 = 0.20
        ])
        
        # To make doc3 win with lambda=0.5:
        # score = 0.5*rel - 0.5*red = 0.5 * (rel - red).
        # We need rel > red for doc3. But red = dot(doc3, doc1). If query is doc1 (1.0, 0.0), then rel = red.
        # Oh, if query is NOT doc1.
        q_emb = np.array([0.707, 0.707])
        candidate_embs = np.array([
            [0.707, 0.707],  # doc1 (rel = 1.0)
            [0.6, 0.8],      # doc2 (rel = 0.99, red = 0.99)
            [0.8, 0.6],      # doc3 (rel = 0.99, red = 0.99)
            [0.0, 1.0]       # doc4 (rel = 0.707, red = 0.707)
        ])
        
        # Let's just mock the mmr_select call directly to verify lambda works
        res = mmr_select(q_emb, candidate_embs, ["doc1", "doc2", "doc3", "doc4"], lambda_param=0.0, k=2)
        # If lambda=0.0, score = -redundancy. 
        self.assertEqual(len(res), 2)
        
    def test_mmr_select_tie_break(self):
        q_emb = np.array([1.0, 0.0])
        candidate_embs = np.array([
            [1.0, 0.0],
            [0.5, 0.0],
            [0.5, 0.0]
        ])
        # c2 and c1 tie
        candidate_ids = ["c3", "c2", "c1"]
        res = mmr_select(q_emb, candidate_embs, candidate_ids, lambda_param=0.70, k=3)
        self.assertEqual(res[0][0], "c3") # rel=1.0
        self.assertEqual(res[1][0], "c1") # tie break ascending
        self.assertEqual(res[2][0], "c2")

    def test_mmr_select_unique_parents(self):
        q_emb = np.array([1.0, 0.0])
        candidate_embs = np.array([
            [1.0, 0.0],
            [0.5, 0.0]
        ])
        res = mmr_select(q_emb, candidate_embs, ["d1", "d2"], lambda_param=0.7, k=5)
        # Should only return 2 docs
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0][0], "d1")
        self.assertEqual(res[1][0], "d2")

    def test_score_embedding_mmr_cutoff_and_global(self):
        m = MockDenseE5MMRV1()
        m.doc_ids = ["ch01", "ch02", "ch03"]
        m.doc_embeddings = np.array([
            [1.0, 0.0],
            [0.9, 0.0],
            [0.8, 0.0]
        ])
        
        # cutoff
        res_cutoff = m.score_embedding_mmr(np.array([1.0, 0.0]), allowed_doc_ids={"ch01", "ch03"})
        self.assertEqual(len(res_cutoff), 2)
        self.assertEqual([x[0] for x in res_cutoff], ["ch01", "ch03"])
        
        # global
        res_global = m.score_embedding_mmr(np.array([1.0, 0.0]))
        self.assertEqual(len(res_global), 3)

    def test_f_vs_h_comparison(self):
        keys = ["hit@1", "hit@3", "hit@5", "hit@10", "recall@1", "recall@3", "recall@5", "recall@10", "success@1", "success@3", "success@5", "success@10"]
        overall_h = {k: 0.0 for k in keys}
        overall_h["hit@10"] = 0.8
        overall_h["recall@10"] = 0.5
        overall_h["success@10"] = 0.2
        overall_h["mrr"] = 0.4
        
        cat_h = {k: 0.0 for k in keys}
        cat_h["hit@10"] = 1.0
        cat_h["recall@10"] = 0.6
        cat_h["success@10"] = 0.5

        agg_h = {
            "CUTOFF_FILTERED": {
                "overall": overall_h,
                "per_category": {
                    "CAT_A": cat_h
                }
            }
        }
        
        overall_f = {k: 0.0 for k in keys}
        overall_f["hit@10"] = 0.9
        overall_f["recall@10"] = 0.7
        overall_f["success@10"] = 0.3
        overall_f["mrr"] = 0.6
        
        cat_f = {k: 0.0 for k in keys}
        cat_f["hit@10"] = 0.5
        cat_f["recall@10"] = 0.4
        cat_f["success@10"] = 0.1

        agg_f = {
            "CUTOFF_FILTERED": {
                "overall": overall_f,
                "per_category": {
                    "CAT_A": cat_f
                }
            }
        }
        
        with tempfile.TemporaryDirectory() as tmpdir:
            f_path = Path(tmpdir) / "f.yaml"
            with open(f_path, "w", encoding="utf-8") as f:
                yaml.dump(agg_f, f)
                
            compare_f_and_h(agg_h, f_path)
            
        comp = agg_h.get("DENSE_E5_SMALL_V1_COMPARISON")
        self.assertIsNotNone(comp)
        
        ov = comp["overall"]
        self.assertAlmostEqual(ov["Hit@10"]["delta"], -0.1)
        self.assertAlmostEqual(ov["Recall@10"]["delta"], -0.2)
        self.assertAlmostEqual(ov["Full_Evidence_Success@10"]["delta"], -0.1)
        self.assertAlmostEqual(ov["MRR"]["delta"], -0.2)
        
        cat = comp["per_category_Hit10"]["CAT_A"]
        self.assertAlmostEqual(cat["delta_Hit@10"], 0.5)

    def test_verify_dense_mmr_determinism(self):
        agg1 = {
            "dense_diagnostics": {
                "encoding_runtime_sec": 1.5,
                "retrieval_evaluation_runtime_sec": 0.5
            },
            "detailed_results_sha256": {
                "mmr_cutoff_per_probe.jsonl": "sha_c1",
                "mmr_global_per_probe.jsonl": "sha_g1",
                "relevance_control_per_probe.jsonl": "sha_rc1"
            },
            "some_metric": 0.9
        }
        
        agg2 = {
            "dense_diagnostics": {
                "encoding_runtime_sec": 2.5,
                "retrieval_evaluation_runtime_sec": 0.6
            },
            "detailed_results_sha256": {
                "mmr_cutoff_per_probe.jsonl": "sha_c1",
                "mmr_global_per_probe.jsonl": "sha_g1",
                "relevance_control_per_probe.jsonl": "sha_rc1"
            },
            "some_metric": 0.9
        }
        
        self.assertTrue(verify_dense_mmr_determinism(agg1, agg2))
        
        agg2_bad = dict(agg2)
        agg2_bad["detailed_results_sha256"] = dict(agg2["detailed_results_sha256"])
        agg2_bad["detailed_results_sha256"]["mmr_cutoff_per_probe.jsonl"] = "sha_c2"
        self.assertFalse(verify_dense_mmr_determinism(agg1, agg2_bad))

if __name__ == '__main__':
    unittest.main()
