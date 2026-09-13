import math
import unicodedata
from collections import Counter
from typing import List, Dict, Tuple, Set

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
    req_ev = set(probe["required_evidence_chunk_ids"])
    cutoff = probe["cutoff_chapter"]
    
    metrics = {}
    
    # K values: 1, 3, 5, 10
    for k in [1, 3, 5, 10]:
        top_k = ranked_results[:k]
        
        hit = 1 if any(c in req_ev for c in top_k) else 0
        recall = sum(1 for c in req_ev if c in top_k) / len(req_ev) if req_ev else 0
        success = 1 if recall == 1.0 else 0
        
        # We need chunk metadata to determine spoiler violations.
        # This will be passed from the runner logic or computed there.
        # So we defer Spoiler Violation logic to the caller, or just pass a dict of chunk_meta.
        
        metrics[f"hit@{k}"] = hit
        metrics[f"recall@{k}"] = recall
        metrics[f"success@{k}"] = success
        
    # MRR calculation
    mrr = 0.0
    for i, doc_id in enumerate(ranked_results):
        if doc_id in req_ev:
            mrr = 1.0 / (i + 1)
            break
            
    metrics["mrr"] = mrr
    return metrics
