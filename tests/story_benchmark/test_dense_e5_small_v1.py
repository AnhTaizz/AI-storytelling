import unittest
import numpy as np
from tools.story_benchmark.dense_e5_small_v1 import calculate_metrics, DenseE5SmallV1
from tools.story_benchmark.run_bm25_lexical_v1 import compute_spoiler_violations
from tools.story_benchmark.run_dense_e5_small_v1 import verify_dense_determinism, compare_bm25_dense

class MockDenseE5SmallV1:
    # A mock class mimicking DenseE5SmallV1 but overriding encode methods
    def __init__(self):
        self.doc_ids = []
        self.doc_embeddings = None
        self.passage_truncation_count = 0
        self.query_truncation_count = 0
        
    def add_documents(self, doc_ids, embeddings):
        self.doc_ids = doc_ids
        self.doc_embeddings = embeddings
        
    def score_embedding(self, q_emb, allowed_doc_ids=None):
        scores = {}
        sims = np.dot(self.doc_embeddings, q_emb)
        for i, doc_id in enumerate(self.doc_ids):
            if allowed_doc_ids is None or doc_id in allowed_doc_ids:
                scores[doc_id] = float(sims[i])
        return sorted(scores.items(), key=lambda x: (-x[1], x[0]))

class TestDenseE5SmallV1(unittest.TestCase):
    def test_ranking_and_tie_break(self):
        m = MockDenseE5SmallV1()
        docs = ["z_doc", "a_doc", "b_doc"]
        # Normalize vectors for pure cosine sim
        v1 = np.array([1.0, 0.0])
        v2 = np.array([1.0, 0.0])
        v3 = np.array([0.0, 1.0])
        m.add_documents(docs, np.array([v1, v2, v3]))
        
        q_emb = np.array([1.0, 0.0])
        res = m.score_embedding(q_emb)
        
        # z_doc and a_doc have score 1.0. a_doc should come first due to tie-break.
        self.assertEqual(len(res), 3)
        self.assertEqual(res[0][0], "a_doc")
        self.assertEqual(res[0][1], 1.0)
        self.assertEqual(res[1][0], "z_doc")
        self.assertEqual(res[1][1], 1.0)
        self.assertEqual(res[2][0], "b_doc")
        self.assertEqual(res[2][1], 0.0)

    def test_cutoff_filtering(self):
        m = MockDenseE5SmallV1()
        docs = ["ch01", "ch02"]
        m.add_documents(docs, np.array([[1.0], [1.0]]))
        
        # Only allow ch01
        res_cutoff = m.score_embedding(np.array([1.0]), allowed_doc_ids={"ch01"})
        self.assertEqual(len(res_cutoff), 1)
        self.assertEqual(res_cutoff[0][0], "ch01")
        
        # Unfiltered allows both
        res_global = m.score_embedding(np.array([1.0]), allowed_doc_ids=None)
        self.assertEqual(len(res_global), 2)

    def test_metrics(self):
        probe = {
            "cutoff_chapter": 1,
            "required_evidence_chunk_ids": ["doc2", "doc3"]
        }
        
        ranked = ["doc1", "doc2", "doc4", "doc3", "doc5"]
        m = calculate_metrics(probe, ranked)
        
        self.assertEqual(m["hit@1"], 0)
        self.assertEqual(m["recall@1"], 0.0)
        
        self.assertEqual(m["hit@3"], 1)
        self.assertEqual(m["recall@3"], 0.5)
        self.assertEqual(m["success@3"], 0)
        
        self.assertEqual(m["hit@5"], 1)
        self.assertEqual(m["recall@5"], 1.0)
        self.assertEqual(m["success@5"], 1)
        
        self.assertEqual(m["mrr"], 0.5)

    def test_spoiler_violations(self):
        probe = {"cutoff_chapter": 5}
        chunk_meta = {"d1": 1, "d2": 6, "d3": 5}
        ranked = ["d1", "d3", "d2"]
        v = compute_spoiler_violations(probe, ranked, chunk_meta)
        self.assertEqual(v["spoiler_violation@1"], 0)
        self.assertEqual(v["spoiler_violation@3"], 1)
        
    def test_determinism_checks(self):
        agg1 = {
            "detailed_results_sha256": {
                "cutoff_filtered_per_probe.jsonl": "abc",
                "global_diagnostic_per_probe.jsonl": "def"
            },
            "dense_diagnostics": {
                "encoding_runtime_sec": 1.0,
                "retrieval_evaluation_runtime_sec": 0.5
            },
            "some_metric": 10
        }
        import copy
        agg2 = copy.deepcopy(agg1)
        
        # Equal results (runtimes diff ignored)
        agg2["dense_diagnostics"]["encoding_runtime_sec"] = 2.0
        self.assertTrue(verify_dense_determinism(agg1, agg2))
        
        # Diff detailed SHA
        agg3 = copy.deepcopy(agg1)
        agg3["detailed_results_sha256"]["cutoff_filtered_per_probe.jsonl"] = "xxx"
        self.assertFalse(verify_dense_determinism(agg1, agg3))
        
        # Diff metric
        agg4 = copy.deepcopy(agg1)
        agg4["some_metric"] = 20
        self.assertFalse(verify_dense_determinism(agg1, agg4))

    def test_metadata_safety(self):
        # We test that no fields in get_model_info() return objects that would trigger !!python/object
        m = DenseE5SmallV1()
        info = m.get_model_info()
        self.assertTrue(isinstance(info["torch_version"], str))
        self.assertTrue(isinstance(info["sentence_transformers_version"], str))
        self.assertTrue(isinstance(info["transformers_version"], str))
        
        self.assertIn("model_revision", info)
        self.assertNotIn(info["model_revision"], [None, "", "main", "latest"])
        
    def test_bm25_dense_comparison(self):
        agg_dense = {
            "CUTOFF_FILTERED": {
                "overall": {
                    "hit@1": 0.0, "hit@3": 0.0, "hit@5": 0.0, "hit@10": 0.9,
                    "recall@1": 0.0, "recall@3": 0.0, "recall@5": 0.0, "recall@10": 0.5,
                    "success@1": 0.0, "success@3": 0.0, "success@5": 0.0, "success@10": 0.2,
                    "mrr": 0.3
                },
                "per_category": {"catA": {"hit@10": 1.0}}
            }
        }
        import tempfile, yaml
        with tempfile.NamedTemporaryFile("w+", suffix=".yaml", delete=False) as f:
            yaml.dump({
                "CUTOFF_FILTERED": {
                    "overall": {
                        "hit@1": 0.0, "hit@3": 0.0, "hit@5": 0.0, "hit@10": 0.2,
                        "recall@1": 0.0, "recall@3": 0.0, "recall@5": 0.0, "recall@10": 0.1,
                        "success@1": 0.0, "success@3": 0.0, "success@5": 0.0, "success@10": 0.0,
                        "mrr": 0.1
                    },
                    "per_category": {"catA": {"hit@10": 0.0}}
                }
            }, f)
            fname = f.name
            
        compare_bm25_dense(agg_dense, fname)
        c = agg_dense["BM25_COMPARISON"]["overall"]
        self.assertAlmostEqual(c["Hit@10"]["delta"], 0.7)
        self.assertAlmostEqual(c["Recall@10"]["delta"], 0.4)
        self.assertAlmostEqual(c["MRR"]["delta"], 0.2)

if __name__ == '__main__':
    unittest.main()
