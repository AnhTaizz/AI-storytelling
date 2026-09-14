import unittest
import numpy as np
import tempfile
import yaml
import json
from pathlib import Path
from unittest.mock import patch

from tools.story_benchmark.dense_e5_window_max_v1 import (
    calculate_metrics,
    build_token_windows,
    validate_token_coverage,
    DenseE5WindowMaxV1
)

from tools.story_benchmark.run_dense_e5_window_max_v1 import (
    compute_spoiler_violations,
    verify_dense_determinism,
    compare_f_and_g
)

class MockTokenizer:
    def __call__(self, texts, return_offsets_mapping=False, add_special_tokens=True, truncation=False):
        if type(texts) is str:
            texts = [texts]
        
        res = {"input_ids": [], "offset_mapping": []}
        for t in texts:
            num_tokens = max(1, len(t) // 10 + (1 if len(t) % 10 != 0 else 0))
            if len(t) == 0:
                num_tokens = 0
            res["input_ids"].append([0] * num_tokens)
            
            if return_offsets_mapping:
                offsets = []
                for i in range(num_tokens):
                    offsets.append((i*10, min((i+1)*10, len(t))))
                res["offset_mapping"].append(offsets)
        if not return_offsets_mapping:
            return res
        if len(res["input_ids"]) == 0:
            return {"input_ids": [], "offset_mapping": []}
        return {"input_ids": res["input_ids"][0], "offset_mapping": res["offset_mapping"][0]}

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

class MockDenseE5WindowMaxV1(DenseE5WindowMaxV1):
    def __init__(self):
        # DO NOT call super().__init__() to avoid loading real SentenceTransformer
        # We manually initialize only what is required
        self.model = MockModel()
        self.model_name = "mock"
        self.model_revision = "mock"
        self.device = "cpu"
        
        self.MAX_MODEL_TOKENS = 512
        self.CONTENT_WINDOW_TOKENS = 2
        self.CONTENT_OVERLAP_TOKENS = 1
        self.STRIDE = 1
        
        self.passage_truncation_count = 0
        self.query_truncation_count = 0
        self.window_truncation_count = 0
        self.coverage_failure_count = 0
        
        self.parent_count = 0
        self.window_count = 0
        self.parents_with_multiple_windows = 0
        self.single_window_parent_count = 0
        self.max_windows_per_parent = 0
        self.total_parent_tokens = 0
        self.total_covered_token_positions = 0
        
        self.parent_to_windows = {}
        self.window_ids = []
        self.window_embeddings = None

    def encode_documents(self, doc_ids, texts, embeddings=None):
        res = super().encode_documents(doc_ids, texts)
        if embeddings is not None:
            self.window_embeddings = embeddings
        return res

class TestDenseE5WindowMaxV1(unittest.TestCase):

    @patch('tools.story_benchmark.dense_e5_window_max_v1.SentenceTransformer')
    def test_offline_proof(self, mock_st):
        mock_st.side_effect = RuntimeError("SentenceTransformer should not be instantiated during unit tests")
        # Ensure that our test mock does NOT instantiate the real model
        m = MockDenseE5WindowMaxV1()
        self.assertIsInstance(m.model, MockModel)
        
        # Test that instantiating real model raises our patched exception
        with self.assertRaises(RuntimeError):
            DenseE5WindowMaxV1()

    def test_short_parent_exactly_one_window(self):
        tok = MockTokenizer()
        text = "123456789012345" # 15 chars = 2 tokens
        cov = build_token_windows(text, tok, 2, 1)
        self.assertEqual(len(cov["windows"]), 1)
        
    def test_long_parent_multiple_windows(self):
        tok = MockTokenizer()
        text = "1234567890123456789012345" # 25 chars = 3 tokens
        cov = build_token_windows(text, tok, 2, 1)
        self.assertEqual(len(cov["windows"]), 2)
        
    def test_coverage_validation_passes(self):
        tok = MockTokenizer()
        text = "1234567890123456789012345" # 3 tokens
        cov = build_token_windows(text, tok, 2, 1)
        
        # first token starts at 0
        self.assertEqual(cov["windows"][0]["token_start"], 0)
        
        # final window reaches final token
        self.assertEqual(cov["windows"][-1]["token_end"], 3)
        
        # character offsets produce exact source substring
        self.assertEqual(cov["windows"][0]["text"], "12345678901234567890")
        self.assertEqual(cov["windows"][1]["text"], "123456789012345")
        
        ev = validate_token_coverage("parent_1", cov, 2, 1)
        self.assertEqual(ev["status"], "PASS")

    def test_coverage_validation_fails_on_gap(self):
        cov = {
            "total_token_count": 3,
            "windows": [
                {"token_start": 0, "token_end": 1, "text": "1"},
                {"token_start": 2, "token_end": 3, "text": "3"}
            ]
        }
        ev = validate_token_coverage("parent_1", cov, 2, 2)
        self.assertEqual(ev["status"], "FAIL")
        self.assertIn("Gap detected", ev["reason"])
        
    def test_coverage_validation_fails_on_uncovered_tail(self):
        cov = {
            "total_token_count": 4,
            "windows": [
                {"token_start": 0, "token_end": 2, "text": "12"},
                {"token_start": 1, "token_end": 3, "text": "23"}
            ]
        }
        ev = validate_token_coverage("parent_1", cov, 2, 1)
        self.assertEqual(ev["status"], "FAIL")
        self.assertIn("Last window does not end", ev["reason"])
        
    def test_coverage_validation_fails_on_bad_stride(self):
        cov = {
            "total_token_count": 4,
            "windows": [
                {"token_start": 0, "token_end": 2, "text": "12"},
                {"token_start": 2, "token_end": 4, "text": "34"}
            ]
        }
        # expected stride is 1, here it jumped to 2
        ev = validate_token_coverage("parent_1", cov, 2, 1)
        self.assertEqual(ev["status"], "FAIL")
        self.assertIn("does not follow stride contract", ev["reason"])

    def test_overlap_is_64_tokens(self):
        # We can simulate a real sizing
        tok = MockTokenizer()
        text = "x" * (448*10 + 1) # ~449 tokens
        cov = build_token_windows(text, tok, 448, 384)
        
        # W0: 0 -> 448
        # W1: 384 -> 449
        self.assertEqual(len(cov["windows"]), 2)
        overlap = cov["windows"][0]["token_end"] - cov["windows"][1]["token_start"]
        self.assertEqual(overlap, 64)
        
    def test_empty_parent_validation(self):
        tok = MockTokenizer()
        cov = build_token_windows("", tok, 2, 1)
        ev = validate_token_coverage("parent_1", cov, 2, 1)
        self.assertEqual(ev["status"], "PASS")
        self.assertEqual(ev["reason"], "Valid empty parent")
        
    def test_max_pooling_and_tie_breaking(self):
        m = MockDenseE5WindowMaxV1()
        docs = ["ch01", "ch02", "ch03"]
        texts = ["123456789012345", "1234567890123456789012345", "1234567890"]
        # ch01: 1 window
        # ch02: 2 windows
        # ch03: 1 window
        emb = np.array([
            [0.5, 0.0], # ch01_w1
            [0.3, 0.0], # ch02_w1
            [0.9, 0.0], # ch02_w2 (strongest child -> max pooling)
            [0.9, 0.0]  # ch03_w1 (tie with ch02)
        ])
        m.encode_documents(docs, texts, embeddings=emb)
        
        # multiple children still produce one parent in ranking
        # max-pooling chooses strongest child window
        # parent similarity tie -> parent chunk ID ascending (ch02 beats ch03)
        
        res = m.score_embedding(np.array([1.0, 0.0]))
        self.assertEqual(len(res), 3)
        self.assertEqual(res[0][0], "ch02")
        self.assertEqual(res[0][1], 0.9)
        self.assertEqual(res[1][0], "ch03")
        self.assertEqual(res[1][1], 0.9)
        self.assertEqual(res[2][0], "ch01")
        
    def test_cutoff_excludes_future_parent(self):
        m = MockDenseE5WindowMaxV1()
        m.encode_documents(["ch01", "ch02"], ["a", "b"], embeddings=np.array([[0.5,0.0], [0.9,0.0]]))
        # cutoff excludes future parent
        res = m.score_embedding(np.array([1.0, 0.0]), allowed_doc_ids={"ch01"})
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][0], "ch01")
        
        # global mode permits future parent
        res_global = m.score_embedding(np.array([1.0, 0.0]))
        self.assertEqual(len(res_global), 2)
        
    def test_parent_level_metrics(self):
        probe = {
            "required_evidence_chunk_ids": ["ch02", "ch04"]
        }
        res = ["ch01", "ch02", "ch03", "ch04"]
        metrics = calculate_metrics(probe, res)
        # ch02 is rank 2, ch04 is rank 4
        # hit@1 = 0
        self.assertEqual(metrics["hit@1"], 0)
        # hit@3 = 1 (ch02)
        self.assertEqual(metrics["hit@3"], 1)
        # recall@3 = 0.5 (1/2)
        self.assertEqual(metrics["recall@3"], 0.5)
        # success@3 = 0
        self.assertEqual(metrics["success@3"], 0)
        # success@5 = 1 (ch02, ch04)
        self.assertEqual(metrics["success@5"], 1)
        # MRR = 1/2 = 0.5
        self.assertEqual(metrics["mrr"], 0.5)

    def test_zero_truncation_fail_oversized(self):
        m = MockDenseE5WindowMaxV1()
        # force tokenizer to produce > 512 tokens
        class OversizedTokenizer(MockTokenizer):
            def __call__(self, texts, return_offsets_mapping=False, add_special_tokens=True, truncation=False):
                res = super().__call__(texts, return_offsets_mapping, add_special_tokens, truncation)
                if not return_offsets_mapping:
                    # check truncation phase
                    res["input_ids"] = [ [0]*513 for _ in texts ]
                return res
                
        m.model.tokenizer = OversizedTokenizer()
        
        with self.assertRaises(ValueError) as context:
            m.encode_documents(["ch1"], ["1234567890"])
            
        self.assertIn("Window truncation verification failed", str(context.exception))

    def test_spoiler_violation(self):
        probe = {
            "cutoff_chapter": 2
        }
        ranked_ids = ["chunk_c1", "chunk_c2", "chunk_c3", "chunk_c4", "chunk_c5"]
        chunk_meta = {
            "chunk_c1": 1,
            "chunk_c2": 2,
            "chunk_c3": 3, # spoiler!
            "chunk_c4": 1,
            "chunk_c5": 4  # spoiler!
        }
        
        violations = compute_spoiler_violations(probe, ranked_ids, chunk_meta)
        
        # @1 -> chunk_c1 (chap 1 <= 2) -> no spoiler
        self.assertEqual(violations["spoiler_violation@1"], 0.0)
        
        # @3 -> chunk_c1, c2, c3. c3 is chap 3 > 2 -> spoiler!
        self.assertEqual(violations["spoiler_violation@3"], 1.0)
        
        # @5 -> chunk_c5 is also spoiler, but already violated
        self.assertEqual(violations["spoiler_violation@5"], 1.0)
        self.assertEqual(violations["spoiler_violation@10"], 1.0)

    def test_f_vs_g_comparison(self):
        keys = ["hit@1", "hit@3", "hit@5", "hit@10", "recall@1", "recall@3", "recall@5", "recall@10", "success@1", "success@3", "success@5", "success@10"]
        overall_g = {k: 0.0 for k in keys}
        overall_g["hit@10"] = 0.8
        overall_g["recall@10"] = 0.5
        overall_g["success@10"] = 0.2
        overall_g["mrr"] = 0.4
        
        cat_g = {k: 0.0 for k in keys}
        cat_g["hit@10"] = 1.0
        cat_g["recall@10"] = 0.6
        cat_g["success@10"] = 0.5

        agg_g = {
            "CUTOFF_FILTERED": {
                "overall": overall_g,
                "per_category": {
                    "CAT_A": cat_g
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
                
            compare_f_and_g(agg_g, f_path)
            
        comp = agg_g.get("DENSE_E5_SMALL_V1_COMPARISON")
        self.assertIsNotNone(comp)
        
        # Check overall deltas
        ov = comp["overall"]
        # G (0.8) - F (0.9) = -0.1
        self.assertAlmostEqual(ov["Hit@10"]["delta"], -0.1)
        self.assertAlmostEqual(ov["Recall@10"]["delta"], -0.2)
        self.assertAlmostEqual(ov["Full_Evidence_Success@10"]["delta"], -0.1)
        self.assertAlmostEqual(ov["MRR"]["delta"], -0.2)
        
        # Check per category delta
        cat = comp["per_category_Hit10"]["CAT_A"]
        # G (1.0) - F (0.5) = 0.5
        self.assertAlmostEqual(cat["delta_Hit@10"], 0.5)

    def test_verify_dense_determinism(self):
        agg1 = {
            "window_diagnostics": {
                "encoding_runtime_sec": 1.5,
                "retrieval_evaluation_runtime_sec": 0.5
            },
            "detailed_results_sha256": {
                "cutoff_filtered_per_probe.jsonl": "sha_c1",
                "global_diagnostic_per_probe.jsonl": "sha_g1",
                "window_manifest.jsonl": "sha_w1"
            },
            "some_metric": 0.9
        }
        
        agg2 = {
            "window_diagnostics": {
                "encoding_runtime_sec": 2.5, # Different runtime
                "retrieval_evaluation_runtime_sec": 0.6
            },
            "detailed_results_sha256": {
                "cutoff_filtered_per_probe.jsonl": "sha_c1",
                "global_diagnostic_per_probe.jsonl": "sha_g1",
                "window_manifest.jsonl": "sha_w1"
            },
            "some_metric": 0.9
        }
        
        # Should pass despite different runtimes
        self.assertTrue(verify_dense_determinism(agg1, agg2))
        
        # Fail on different cutoff SHA
        agg2_bad_c = dict(agg2)
        agg2_bad_c["detailed_results_sha256"] = dict(agg2["detailed_results_sha256"])
        agg2_bad_c["detailed_results_sha256"]["cutoff_filtered_per_probe.jsonl"] = "sha_c2"
        self.assertFalse(verify_dense_determinism(agg1, agg2_bad_c))
        
        # Fail on different global SHA
        agg2_bad_g = dict(agg2)
        agg2_bad_g["detailed_results_sha256"] = dict(agg2["detailed_results_sha256"])
        agg2_bad_g["detailed_results_sha256"]["global_diagnostic_per_probe.jsonl"] = "sha_g2"
        self.assertFalse(verify_dense_determinism(agg1, agg2_bad_g))
        
        # Fail on different manifest SHA
        agg2_bad_w = dict(agg2)
        agg2_bad_w["detailed_results_sha256"] = dict(agg2["detailed_results_sha256"])
        agg2_bad_w["detailed_results_sha256"]["window_manifest.jsonl"] = "sha_w2"
        self.assertFalse(verify_dense_determinism(agg1, agg2_bad_w))
        
        # Fail on different metric (JSON serialization differs)
        agg2_bad_m = dict(agg2)
        agg2_bad_m["some_metric"] = 0.8
        self.assertFalse(verify_dense_determinism(agg1, agg2_bad_m))

if __name__ == '__main__':
    unittest.main()
