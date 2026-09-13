import unittest
from tools.story_benchmark.bm25_lexical_v1 import jp_simple_lexical_v1, BM25LexicalV1, calculate_metrics
from tools.story_benchmark.run_bm25_lexical_v1 import compute_spoiler_violations, verify_determinism
import copy

class TestBM25LexicalV1(unittest.TestCase):
    def test_latin_tokenization(self):
        tokens = jp_simple_lexical_v1("Hello World 123! test_case")
        self.assertEqual(tokens, ["hello", "world", "123", "test", "case"])
        
    def test_japanese_tokenization(self):
        # わた (Hiragana) -> unigrams: わ, た. bigram: わた
        tokens = jp_simple_lexical_v1("わたし")
        self.assertEqual(set(tokens), {"わ", "わた", "た", "たし", "し"})
        
        # Mixed
        tokens2 = jp_simple_lexical_v1("AねこB")
        self.assertEqual(set(tokens2), {"a", "ね", "ねこ", "こ", "b"})
        
        # NFKC
        tokens3 = jp_simple_lexical_v1("１２３") # Fullwidth digits
        self.assertEqual(tokens3, ["123"])
        
    def test_bm25_ranking(self):
        bm25 = BM25LexicalV1()
        bm25.add_document("doc1", "apple banana")
        bm25.add_document("doc2", "apple apple cherry")
        bm25.add_document("doc3", "date fig")
        bm25.build()
        
        res = bm25.score("apple")
        # doc2 has more apples, should rank higher
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0][0], "doc2")
        self.assertEqual(res[1][0], "doc1")
        
    def test_tie_break(self):
        bm25 = BM25LexicalV1()
        bm25.add_document("z_doc", "apple")
        bm25.add_document("a_doc", "apple")
        bm25.build()
        
        res = bm25.score("apple")
        self.assertEqual(len(res), 2)
        # Same text, score should be identical. Tie break by doc_id ascending.
        self.assertEqual(res[0][0], "a_doc")
        self.assertEqual(res[1][0], "z_doc")
        
    def test_zero_overlap(self):
        bm25 = BM25LexicalV1()
        bm25.add_document("doc1", "apple")
        bm25.build()
        
        res = bm25.score("banana")
        self.assertEqual(len(res), 0)
        
    def test_cutoff_filtering(self):
        bm25 = BM25LexicalV1()
        bm25.add_document("ch01_c1", "apple")
        bm25.add_document("ch02_c1", "apple")
        bm25.build()
        
        # Only allow ch01_c1
        res = bm25.score("apple", allowed_doc_ids={"ch01_c1"})
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][0], "ch01_c1")
        
    def test_metrics(self):
        probe = {
            "cutoff_chapter": 1,
            "required_evidence_chunk_ids": ["doc2", "doc3"]
        }
        
        # retrieved: doc1 (no), doc2 (yes), doc4 (no), doc3 (yes)
        ranked = ["doc1", "doc2", "doc4", "doc3", "doc5"]
        
        m = calculate_metrics(probe, ranked)
        # K=1 -> top is doc1 -> hit=0, recall=0, success=0
        self.assertEqual(m["hit@1"], 0)
        self.assertEqual(m["recall@1"], 0.0)
        
        # K=3 -> top is doc1, doc2, doc4 -> hit=1, recall=0.5, success=0
        self.assertEqual(m["hit@3"], 1)
        self.assertEqual(m["recall@3"], 0.5)
        self.assertEqual(m["success@3"], 0)
        
        # K=5 -> top 5 -> hit=1, recall=1.0, success=1
        self.assertEqual(m["hit@5"], 1)
        self.assertEqual(m["recall@5"], 1.0)
        self.assertEqual(m["success@5"], 1)
        
        # MRR -> doc2 is at index 1 (rank 2) -> 0.5
        self.assertEqual(m["mrr"], 0.5)

    def test_spoiler_violation(self):
        probe = {"cutoff_chapter": 1}
        ranked = ["ch01", "ch02"]
        chunk_meta = {"ch01": 1, "ch02": 2}
        
        m = compute_spoiler_violations(probe, ranked, chunk_meta)
        self.assertEqual(m["spoiler_violation@1"], 0)
        self.assertEqual(m["spoiler_violation@3"], 1)
        
    def test_global_diagnostic_future_retrieval(self):
        bm25 = BM25LexicalV1()
        bm25.add_document("c1", "apple") # chapter 1
        bm25.add_document("c2", "apple apple") # chapter 2
        bm25.build()
        
        # GLOBAL_DIAGNOSTIC returns future chunk because it matches better
        res_global = bm25.score("apple")
        self.assertEqual(res_global[0][0], "c2")
        
        # CUTOFF_FILTERED restricts allowed docs
        res_cutoff = bm25.score("apple", allowed_doc_ids={"c1"})
        self.assertEqual(len(res_cutoff), 1)
        self.assertEqual(res_cutoff[0][0], "c1")
        
    def test_determinism_failure_gate(self):
        agg1 = {
            "detailed_results_sha256": {
                "cutoff_filtered_per_probe.jsonl": "abc",
                "global_diagnostic_per_probe.jsonl": "def"
            },
            "other_metric": 1.0
        }
        
        # Exact identical -> True
        self.assertTrue(verify_determinism(agg1, agg1))
        
        # Cutoff mismatch -> False
        agg2 = copy.deepcopy(agg1)
        agg2["detailed_results_sha256"]["cutoff_filtered_per_probe.jsonl"] = "zzz"
        self.assertFalse(verify_determinism(agg1, agg2))
        
        # Global mismatch -> False
        agg3 = copy.deepcopy(agg1)
        agg3["detailed_results_sha256"]["global_diagnostic_per_probe.jsonl"] = "zzz"
        self.assertFalse(verify_determinism(agg1, agg3))
        
        # Metric mismatch -> False
        agg4 = copy.deepcopy(agg1)
        agg4["other_metric"] = 2.0
        self.assertFalse(verify_determinism(agg1, agg4))

if __name__ == '__main__':
    unittest.main()
