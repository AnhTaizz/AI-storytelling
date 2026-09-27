import math
import unicodedata
from collections import Counter
from typing import List, Dict, Tuple, Set

from tools.story_benchmark.multi_gold_metrics import calculate_probe_metrics

def is_japanese_char(c: str) -> bool:
    """
    Check if a character falls into common Japanese ranges:
    - Hiragana: \u3040-\u309F
    - Katakana: \u30A0-\u30FF
    - CJK Unified Ideographs: \u4E00-\u9FFF
    """
    o = ord(c)
    return (0x3040 <= o <= 0x309F) or (0x30A0 <= o <= 0x30FF) or (0x4E00 <= o <= 0x9FFF)

def jp_simple_lexical_v1(text: str) -> List[str]:
    """
    Tokenizer: JP_SIMPLE_LEXICAL_V1
    - Unicode NFKC normalization
    - casefold Latin text
    - Latin letters/digits are grouped into contiguous word tokens
    - Japanese scripts (Hiragana, Katakana, CJK) emit unigrams and bigrams
    - Ignores whitespace and punctuation
    """
    text = unicodedata.normalize('NFKC', text).casefold()
    tokens = []
    
    current_latin = []
    prev_jp = None
    
    for c in text:
        if c.isalnum() and not is_japanese_char(c):
            current_latin.append(c)
            prev_jp = None
        else:
            if current_latin:
                tokens.append("".join(current_latin))
                current_latin = []
                
            if is_japanese_char(c):
                tokens.append(c) # unigram
                if prev_jp is not None:
                    tokens.append(prev_jp + c) # bigram
                prev_jp = c
            else:
                # ignore punctuation/whitespace, reset bigram chain
                prev_jp = None
                
    if current_latin:
        tokens.append("".join(current_latin))
        
    return tokens

class BM25LexicalV1:
    """
    BM25_LEXICAL_V1 implementation:
    - k1 = 1.2
    - b = 0.75
    - IDF: ln(1 + (N - df + 0.5) / (df + 0.5))
    - Zero-score policy: chunk is retrievable only if score > 0
    - Tie-breaking: if scores are equal and > 0, tie-break by chunk_id ascending
    """
    def __init__(self, k1: float = 1.2, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_tokens = {}
        self.doc_len = {}
        self.df = Counter()
        self.N = 0
        self.avgdl = 0.0
        
    def add_document(self, doc_id: str, text: str):
        tokens = jp_simple_lexical_v1(text)
        self.doc_tokens[doc_id] = tokens
        self.doc_len[doc_id] = len(tokens)
        for t in set(tokens):
            self.df[t] += 1
        self.N += 1
        
    def build(self):
        if self.N > 0:
            self.avgdl = sum(self.doc_len.values()) / self.N
            
    def score(self, query: str, allowed_doc_ids: Set[str] = None) -> List[Tuple[str, float]]:
        q_tokens = jp_simple_lexical_v1(query)
        q_counts = Counter(q_tokens)
        
        scores = {}
        target_docs = allowed_doc_ids if allowed_doc_ids is not None else self.doc_tokens.keys()
        
        for doc_id in target_docs:
            if doc_id not in self.doc_tokens:
                continue
                
            d_len = self.doc_len[doc_id]
            d_counts = Counter(self.doc_tokens[doc_id])
            
            s = 0.0
            for qt, q_freq in q_counts.items():
                if qt not in d_counts:
                    continue
                df = self.df.get(qt, 0)
                idf = math.log(1.0 + (self.N - df + 0.5) / (df + 0.5))
                tf = d_counts[qt]
                num = tf * (self.k1 + 1)
                den = tf + self.k1 * (1.0 - self.b + self.b * (d_len / self.avgdl))
                s += idf * (num / den)
                
            if s > 0:
                scores[doc_id] = s
                
        # Zero-score policy: only > 0
        # Equal score tie break: doc_id ascending
        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        return ranked

def calculate_metrics(probe: dict, ranked_results: List[str]) -> dict:
    return calculate_probe_metrics(probe, ranked_results)
