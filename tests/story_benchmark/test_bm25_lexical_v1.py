import unittest
from tools.story_benchmark.bm25_lexical_v1 import jp_simple_lexical_v1, BM25LexicalV1, calculate_metrics

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

if __name__ == '__main__':
    unittest.main()
