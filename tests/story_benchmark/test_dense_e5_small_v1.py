import unittest
import numpy as np
from tools.story_benchmark.dense_e5_small_v1 import calculate_metrics

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
        
    def score(self, q_emb, allowed_doc_ids=None):
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
        res = m.score(q_emb)
        
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
        res = m.score(np.array([1.0]), allowed_doc_ids={"ch01"})
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][0], "ch01")
        
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

if __name__ == '__main__':
    unittest.main()
