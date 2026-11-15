"""Untuned deterministic ko/zh baseline: NFKC/casefold words and script bigrams.

Alphanumeric whitespace/punctuation-delimited words are retained (including Korean
words). CJK ideograph and Hangul runs additionally emit adjacent bigrams, or a
unigram for a singleton. No morphology, translation or dictionary is involved.
Tokens are hex-encoded as ASCII words before using the frozen BM25 scorer.
"""

import re
import unicodedata

from tools.story_benchmark.bm25_lexical_v1 import BM25LexicalV1


def cjk_words_bigrams_v1(text: str) -> list[str]:
    text = unicodedata.normalize('NFKC', text).casefold()
    words = re.findall(r'[^\W_]+', text)
    tokens = list(words)
    for run in re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002fa1f]+|'
                          r'[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]+', text):
        tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
        if len(run) == 1 and run not in words:
            tokens.append(run)
    return tokens


class CjkBm25V1(BM25LexicalV1):
    """Reuse frozen scoring with lossless, collision-free token serialization."""

    @staticmethod
    def _render(text):
        return ' '.join('t' + token.encode('utf-8').hex()
                        for token in cjk_words_bigrams_v1(text))

    def add_document(self, doc_id, text):
        super().add_document(doc_id, self._render(text))

    def score(self, query, allowed_doc_ids=None):
        return super().score(self._render(query), allowed_doc_ids)
