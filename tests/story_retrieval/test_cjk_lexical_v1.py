"""Deterministic untuned CJK/Hangul baseline tokenization."""

import unittest

from tools.story_retrieval.cjk_lexical_v1 import CjkBm25V1, cjk_words_bigrams_v1


class CjkLexicalV1Tests(unittest.TestCase):
    def test_normalization_words_and_script_runs(self):
        for text, expected in [('', []), ('ＦＯＯ 123!', ['foo', '123']),
                               ('한국어 단어', ['한국어', '단어', '한국', '국어', '단어']),
                               ('苹果，梨', ['苹果', '梨', '苹果']),
                               ('a中b', ['a中b', '中']),
                               (chr(0x20000) + '果', [chr(0x20000) + '果'] * 2)]:
            with self.subTest(text=text):
                self.assertEqual(cjk_words_bigrams_v1(text), expected)

    def test_scoring_preserves_tokens_without_cross_punctuation_bigrams(self):
        model = CjkBm25V1()
        model.add_document('1', '미라의 苹果汁')
        model.add_document('2', '미 라 苹 果')
        model.build()
        for query, ids in [('미라', ['1']), ('苹果', ['1']), ('unknown', [])]:
            with self.subTest(query=query):
                self.assertEqual([pid for pid, score in model.score(query)], ids)
                self.assertEqual(model.score(query, {'2'}), [])


if __name__ == '__main__':
    unittest.main()
