import torch
import numpy as np
from typing import List, Tuple, Set
from sentence_transformers import SentenceTransformer

MMR_LAMBDA_V1 = 0.70

def mmr_select(
    query_emb: np.ndarray,
    candidate_embs: np.ndarray,
    candidate_ids: List[str],
    lambda_param: float = 0.70,
    k: int = 10
) -> List[Tuple[str, float]]:
    """
    Select documents using Maximal Marginal Relevance.
    relevance = cosine(q, d)
    redundancy = max(cosine(d, s) for s in S)
    score = lambda * relevance - (1 - lambda) * redundancy
    """
    N = len(candidate_ids)
    if N == 0:
        return []
        
    # Assume query_emb shape is (D,) and candidate_embs is (N, D), both normalized.
    relevance = np.dot(candidate_embs, query_emb)
    
    # Precompute pairwise similarities between all candidates
    sim_matrix = np.dot(candidate_embs, candidate_embs.T)
    
    selected_indices = []
    unselected_indices = list(range(N))
    
    results = []
    
    while len(selected_indices) < k and unselected_indices:
        best_score = -float('inf')
        best_idx = -1
        best_rel = 0.0
        
        for idx in unselected_indices:
            rel = relevance[idx]
            if not selected_indices:
                redundancy = 0.0
            else:
                redundancy = max(sim_matrix[idx, s_idx] for s_idx in selected_indices)
                
            mmr_score = lambda_param * rel - (1.0 - lambda_param) * redundancy
            
            # Tie breaking
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = idx
                best_rel = rel
            elif abs(mmr_score - best_score) < 1e-9:
                if candidate_ids[idx] < candidate_ids[best_idx]:
                    best_score = mmr_score
                    best_idx = idx
                    best_rel = rel
                    
        selected_indices.append(best_idx)
        unselected_indices.remove(best_idx)
        results.append((candidate_ids[best_idx], float(best_rel)))
        
    return results

class DenseE5MMRV1:
    """
    DENSE_E5_MMR_V1 Implementation
    - Uses exact DENSE_E5_SMALL_V1 representations.
    - Selects final top-K via MMR.
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
        
        return {
            "model_id": self.model_name,
            "model_revision": self.model_revision,
            "model_weight_filename": "model.safetensors",
            "model_weight_sha256": "1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477",
            "embedding_dimension": self.model.get_sentence_embedding_dimension() if hasattr(self.model, 'get_sentence_embedding_dimension') else self.model.get_embedding_dimension(),
            "sentence_transformers_version": str(sentence_transformers.__version__),
            "transformers_version": str(transformers.__version__),
            "torch_version": str(torch.__version__),
            "execution_device": self.device
        }

    def _check_truncation(self, texts, is_query=False):
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
            
    def score_embedding_relevance(self, q_emb: np.ndarray, allowed_doc_ids: Set[str] = None) -> List[Tuple[str, float]]:
        """
        Pure cosine relevance scoring, identical to DENSE_E5_SMALL_V1.
        Used for the relevance control gate.
        """
        scores = {}
        if len(self.doc_embeddings) == 0:
            return []
            
        sims = np.dot(self.doc_embeddings, q_emb)
        
        for i, doc_id in enumerate(self.doc_ids):
            if allowed_doc_ids is None or doc_id in allowed_doc_ids:
                scores[doc_id] = float(sims[i])
                
        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        return ranked

    def score_embedding_mmr(self, q_emb: np.ndarray, allowed_doc_ids: Set[str] = None, lambda_param: float = 0.70, k: int = 10) -> List[Tuple[str, float]]:
        """
        MMR selection over the allowed candidate pool.
        """
        if allowed_doc_ids is not None:
            indices = [i for i, d in enumerate(self.doc_ids) if d in allowed_doc_ids]
        else:
            indices = list(range(len(self.doc_ids)))
            
        if not indices:
            return []
            
        candidate_ids = [self.doc_ids[i] for i in indices]
        candidate_embs = self.doc_embeddings[indices]
        
        return mmr_select(q_emb, candidate_embs, candidate_ids, lambda_param, k)

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

def calculate_diversity_diagnostics(metrics_list: List[Tuple[dict, dict, List[Tuple[str, float]]]], chunk_meta: dict, doc_ids: List[str], doc_embeddings: np.ndarray) -> dict:
    """
    Calculate diversity diagnostics across all probes.
    metrics_list contains (probe, metrics_dict, ranked_results).
    """
    chaps_top3 = []
    chaps_top5 = []
    chaps_top10 = []
    
    pairwise_sims_top10 = []
    query_rels_top10 = []
    
    for _, _, ranked in metrics_list:
        ranked_ids = [x[0] for x in ranked]
        chaps = [chunk_meta[rid] for rid in ranked_ids]
        
        chaps_top3.append(len(set(chaps[:3])))
        chaps_top5.append(len(set(chaps[:5])))
        chaps_top10.append(len(set(chaps[:10])))
        
        if len(ranked_ids) > 1:
            embs = []
            for rid in ranked_ids[:10]:
                idx = doc_ids.index(rid)
                embs.append(doc_embeddings[idx])
            embs = np.array(embs)
            sim_matrix = np.dot(embs, embs.T)
            upper = sim_matrix[np.triu_indices(len(embs), k=1)]
            pairwise_sims_top10.extend(upper)
            
        query_rels_top10.extend([float(x[1]) for x in ranked[:10]])
        
    return {
        "mean_unique_chapters_top3": float(np.mean(chaps_top3)) if chaps_top3 else 0.0,
        "mean_unique_chapters_top5": float(np.mean(chaps_top5)) if chaps_top5 else 0.0,
        "mean_unique_chapters_top10": float(np.mean(chaps_top10)) if chaps_top10 else 0.0,
        "mean_pairwise_similarity_top10": float(np.mean(pairwise_sims_top10)) if pairwise_sims_top10 else 0.0,
        "mean_query_relevance_top10": float(np.mean(query_rels_top10)) if query_rels_top10 else 0.0
    }
