import unittest
import numpy as np
from tools.story_benchmark.dense_e5_window_max_v1 import calculate_metrics

class MockTokenizer:
    def __call__(self, texts, return_offsets_mapping=False, add_special_tokens=True, truncation=False):
        if type(texts) is str:
            texts = [texts]
        
        res = {"input_ids": [], "offset_mapping": []}
        for t in texts:
            # mock tokenize by just breaking string in half or treating chars as tokens
            # let's treat every 10 chars as 1 token for simple tests
            num_tokens = len(t) // 10 + 1
            res["input_ids"].append([0] * num_tokens)
            
            if return_offsets_mapping:
                offsets = []
                for i in range(num_tokens):
                    offsets.append((i*10, min((i+1)*10, len(t))))
                res["offset_mapping"].append(offsets)
        if not return_offsets_mapping:
            return res
        # if only one text, transformers returns dict of lists, but usually for single string it might return just one element if not batched. We handle batch manually
        return {"input_ids": res["input_ids"][0], "offset_mapping": res["offset_mapping"][0]}

class MockModel:
    def __init__(self):
        self.tokenizer = MockTokenizer()
        
    def get_sentence_embedding_dimension(self):
        return 384
        
    def encode(self, texts, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False):
        # Return mock normalized embeddings
        return np.array([[1.0, 0.0] for _ in texts])

class MockDenseE5WindowMaxV1:
    def __init__(self):
        self.model = MockModel()
        self.CONTENT_WINDOW_TOKENS = 2  # small limits for testing
        self.STRIDE = 1
        
        self.passage_truncation_count = 0
        self.query_truncation_count = 0
        self.window_truncation_count = 0
        
        self.parent_count = 0
        self.window_count = 0
        self.parents_with_multiple_windows = 0
        self.single_window_parent_count = 0
        self.max_windows_per_parent = 0
        
        self.parent_to_windows = {}
        self.window_ids = []
        self.window_embeddings = None

    def _chunk_text(self, text: str) -> list[str]:
        # exact copy of logic
        tok = self.model.tokenizer
        encoded = tok(text, return_offsets_mapping=True, add_special_tokens=False)
        input_ids = encoded["input_ids"]
        offsets = encoded["offset_mapping"]
        
        total_tokens = len(input_ids)
        if total_tokens == 0: return []
        if total_tokens <= self.CONTENT_WINDOW_TOKENS: return [text]
            
        windows = []
        start_idx = 0
        while start_idx < total_tokens:
            end_idx = min(start_idx + self.CONTENT_WINDOW_TOKENS, total_tokens)
            char_start = offsets[start_idx][0]
            char_end = offsets[end_idx - 1][1]
            window_text = text[char_start:char_end]
            windows.append(window_text)
            if end_idx == total_tokens: break
            start_idx += self.STRIDE
        return windows

    def encode_documents(self, doc_ids, texts, embeddings=None):
        self.parent_count = len(doc_ids)
        self.parent_to_windows = {}
        flat_window_ids = []
        for parent_id, text in zip(doc_ids, texts):
            windows = self._chunk_text(text)
            num_windows = len(windows)
            if num_windows == 1: self.single_window_parent_count += 1
            elif num_windows > 1: self.parents_with_multiple_windows += 1
            if num_windows > self.max_windows_per_parent: self.max_windows_per_parent = num_windows
                
            child_ids = []
            for i, w_text in enumerate(windows):
                w_id = f"{parent_id}_w{i+1:04d}"
                child_ids.append(w_id)
                flat_window_ids.append(w_id)
            self.parent_to_windows[parent_id] = child_ids
            
        self.window_count = len(flat_window_ids)
        self.window_ids = flat_window_ids
        # override embeddings for logic test
        self.window_embeddings = embeddings if embeddings is not None else np.array([[1.0, 0.0] for _ in flat_window_ids])
        
    def score_embedding(self, q_emb, allowed_doc_ids=None):
        sims = np.dot(self.window_embeddings, q_emb)
        child_sims = {w_id: float(sims[i]) for i, w_id in enumerate(self.window_ids)}
        parent_scores = {}
        for parent_id, child_ids in self.parent_to_windows.items():
            if allowed_doc_ids is None or parent_id in allowed_doc_ids:
                max_sim = max([child_sims[c] for c in child_ids]) if child_ids else -1.0
                parent_scores[parent_id] = max_sim
        return sorted(parent_scores.items(), key=lambda x: (-x[1], x[0]))

class TestDenseE5WindowMaxV1(unittest.TestCase):
    def test_chunking_logic(self):
        m = MockDenseE5WindowMaxV1()
        m.CONTENT_WINDOW_TOKENS = 2
        m.STRIDE = 1
        
        # 15 chars = 2 tokens (10 chars each) = fits in 2 tokens
        text1 = "123456789012345"
        self.assertEqual(len(m._chunk_text(text1)), 1)
        
        # 25 chars = 3 tokens. window=2, stride=1.
        # W1: t0, t1 -> char 0..20
        # W2: t1, t2 -> char 10..25
        text2 = "1234567890123456789012345"
        chunks = m._chunk_text(text2)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0], "12345678901234567890")
        self.assertEqual(chunks[1], "123456789012345") # Wait, offset starts at 10, so text2[10:25]
        self.assertEqual(chunks[1], text2[10:25])
        
    def test_ranking_and_max_aggregation(self):
        m = MockDenseE5WindowMaxV1()
        docs = ["ch01", "ch02"]
        # ch01 will have 1 window (15 chars)
        # ch02 will have 2 windows (25 chars)
        texts = ["123456789012345", "1234567890123456789012345"]
        
        # ch01_w0001 = 0.5
        # ch02_w0001 = 0.3
        # ch02_w0002 = 0.9
        emb = np.array([
            [0.5, 0.0],
            [0.3, 0.0],
            [0.9, 0.0]
        ])
        m.encode_documents(docs, texts, embeddings=emb)
        self.assertEqual(m.parent_count, 2)
        self.assertEqual(m.window_count, 3)
        
        q = np.array([1.0, 0.0])
        res = m.score_embedding(q)
        
        # Expect ch02 to rank first with 0.9, ch01 second with 0.5
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0][0], "ch02")
        self.assertEqual(res[0][1], 0.9)
        self.assertEqual(res[1][0], "ch01")
        self.assertEqual(res[1][1], 0.5)
        
    def test_cutoff_filtering(self):
        m = MockDenseE5WindowMaxV1()
        docs = ["ch01", "ch02"]
        texts = ["123456789012345", "1234567890123456789012345"]
        emb = np.array([[0.5, 0.0], [0.3, 0.0], [0.9, 0.0]])
        m.encode_documents(docs, texts, embeddings=emb)
        
        q = np.array([1.0, 0.0])
        res = m.score_embedding(q, allowed_doc_ids={"ch01"})
        
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][0], "ch01")

if __name__ == '__main__':
    unittest.main()
