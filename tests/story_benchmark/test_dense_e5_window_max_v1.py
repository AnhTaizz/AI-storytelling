import unittest
import numpy as np
from tools.story_benchmark.dense_e5_window_max_v1 import (
    calculate_metrics,
    build_token_windows,
    validate_token_coverage,
    DenseE5WindowMaxV1
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
        super().__init__()
        self.model = MockModel()
        self.CONTENT_WINDOW_TOKENS = 2
        self.STRIDE = 1

    def encode_documents(self, doc_ids, texts, embeddings=None):
        res = super().encode_documents(doc_ids, texts)
        if embeddings is not None:
            self.window_embeddings = embeddings
        return res

class TestDenseE5WindowMaxV1(unittest.TestCase):

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

if __name__ == '__main__':
    unittest.main()
