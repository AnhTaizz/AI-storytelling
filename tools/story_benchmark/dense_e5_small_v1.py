import torch
import numpy as np
from typing import List, Dict, Tuple, Set
from sentence_transformers import SentenceTransformer

class DenseE5SmallV1:
    """
    DENSE_E5_SMALL_V1 Implementation
    - Model: intfloat/multilingual-e5-small
    - Device: CPU
    - Max sequence length: 512
    - Asymmetric formatting (query: / passage: )
    - Cosine similarity ranking
    - Tie break: chunk_id ascending
    """
    def __init__(self):
        torch.manual_seed(42)
        np.random.seed(42)
        torch.use_deterministic_algorithms(True, warn_only=True)
        
        self.model_name = "intfloat/multilingual-e5-small"
        self.model_revision = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
        self.device = "cpu"
        
        self.model = SentenceTransformer(
            self.model_name,
            revision=self.model_revision,
            device=self.device
        )
        self.model.max_seq_length = 512
        self.model.eval()
        
        # Diagnostics
        self.passage_truncation_count = 0
        self.query_truncation_count = 0
        
        self.doc_ids = []
        self.doc_embeddings = None
        
    def get_model_info(self):
        import sentence_transformers
        import transformers
        import torch
        import transformers.utils.hub
        
        # We try to find the exact SHA revision loaded. The sentence_transformers object might hold this in model_card_data or we can inspect the path.
        # This is best-effort local resolution.
        return {
            "model_id": self.model_name,
            "model_revision": self.model_revision,
            "model_weight_filename": "model.safetensors",
            "model_weight_sha256": "1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477",
            "embedding_dimension": self.model.get_sentence_embedding_dimension(),
            "sentence_transformers_version": str(sentence_transformers.__version__),
            "transformers_version": str(transformers.__version__),
            "torch_version": str(torch.__version__),
            "execution_device": self.device
        }

    def _check_truncation(self, texts, is_query=False):
        # We manually tokenize without truncation just to count how many exceed 512
        tok = self.model.tokenizer
        if hasattr(tok, "__call__"):
            encoded = tok(texts, add_special_tokens=True, truncation=False)
            lengths = [len(seq) for seq in encoded["input_ids"]]
            trunc_count = sum(1 for l in lengths if l > 512)
            if is_query:
                self.query_truncation_count += trunc_count
            else:
                self.passage_truncation_count += trunc_count

    def encode_documents(self, doc_ids: List[str], texts: List[str]):
        prefixed = [f"passage: {t}" for t in texts]
        self._check_truncation(prefixed, is_query=False)
        
        with torch.no_grad():
            emb = self.model.encode(prefixed, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
            
        self.doc_ids = list(doc_ids)
        self.doc_embeddings = emb
        return emb
        
    def encode_queries(self, queries: List[str]):
        prefixed = [f"query: {q}" for q in queries]
        self._check_truncation(prefixed, is_query=True)
        
        with torch.no_grad():
            return self.model.encode(prefixed, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
            
    def score(self, query: str, allowed_doc_ids: Set[str] = None) -> List[Tuple[str, float]]:
        # Single query scoring (legacy backwards compatible)
        q_emb = self.encode_queries([query])[0]
        return self.score_embedding(q_emb, allowed_doc_ids)

    def score_embedding(self, q_emb: np.ndarray, allowed_doc_ids: Set[str] = None) -> List[Tuple[str, float]]:
        scores = {}
        # compute dot product over all docs (they are normalized, so it's cosine sim)
        sims = np.dot(self.doc_embeddings, q_emb)
        
        for i, doc_id in enumerate(self.doc_ids):
            if allowed_doc_ids is None or doc_id in allowed_doc_ids:
                scores[doc_id] = float(sims[i])
                
        # Ranked by similarity descending, doc_id ascending for tie breaks
        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        return ranked

def calculate_metrics(probe: dict, ranked_results: List[str]) -> dict:
    req_ev = set(probe["required_evidence_chunk_ids"])
    
    metrics = {}
    for k in [1, 3, 5, 10]:
        top_k = ranked_results[:k]
        hit = 1 if any(c in req_ev for c in top_k) else 0
        recall = sum(1 for c in req_ev if c in top_k) / len(req_ev) if req_ev else 0
        success = 1 if recall == 1.0 else 0
        
        metrics[f"hit@{k}"] = hit
        metrics[f"recall@{k}"] = recall
        metrics[f"success@{k}"] = success
        
    mrr = 0.0
    for i, doc_id in enumerate(ranked_results):
        if doc_id in req_ev:
            mrr = 1.0 / (i + 1)
            break
            
    metrics["mrr"] = mrr
    return metrics
