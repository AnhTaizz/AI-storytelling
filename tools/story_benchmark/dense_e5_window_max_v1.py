import torch
import numpy as np
from typing import List, Dict, Tuple, Set
from sentence_transformers import SentenceTransformer

class DenseE5WindowMaxV1:
    """
    DENSE_E5_WINDOW_MAX_V1 Implementation
    - Model: intfloat/multilingual-e5-small
    - Device: CPU
    - Max sequence length: 512
    - Asymmetric formatting (query: / passage: )
    - Cosine similarity ranking with MAX pooling over parent chunks
    - Windowing: 448 token window, 64 token overlap (stride = 384)
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
        
        # Window constants
        self.MAX_MODEL_TOKENS = 512
        self.CONTENT_WINDOW_TOKENS = 448
        self.CONTENT_OVERLAP_TOKENS = 64
        self.STRIDE = 384
        
        # Diagnostics
        self.passage_truncation_count = 0
        self.query_truncation_count = 0
        self.window_truncation_count = 0
        
        self.parent_count = 0
        self.window_count = 0
        self.parents_with_multiple_windows = 0
        self.single_window_parent_count = 0
        self.max_windows_per_parent = 0
        
        # Parent mapping: doc_id -> list of child_ids
        self.parent_to_windows = {}
        
        # Flat windows list
        self.window_ids = []
        self.window_embeddings = None
        
    def get_model_info(self):
        import sentence_transformers
        import transformers
        import torch
        
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

    def _chunk_text(self, text: str) -> List[str]:
        # Fast tokenizer allows offset mapping
        tok = self.model.tokenizer
        encoded = tok(text, return_offsets_mapping=True, add_special_tokens=False)
        input_ids = encoded["input_ids"]
        offsets = encoded["offset_mapping"]
        
        total_tokens = len(input_ids)
        
        if total_tokens == 0:
            return []
            
        if total_tokens <= self.CONTENT_WINDOW_TOKENS:
            return [text]
            
        windows = []
        start_idx = 0
        
        while start_idx < total_tokens:
            end_idx = min(start_idx + self.CONTENT_WINDOW_TOKENS, total_tokens)
            
            # Extract substring
            char_start = offsets[start_idx][0]
            # Handle empty offset at the end if any
            char_end = offsets[end_idx - 1][1]
            
            window_text = text[char_start:char_end]
            windows.append(window_text)
            
            if end_idx == total_tokens:
                break
                
            start_idx += self.STRIDE
            
        return windows

    def _check_truncation(self, texts, is_query=False, is_window=False):
        tok = self.model.tokenizer
        if hasattr(tok, "__call__"):
            encoded = tok(texts, add_special_tokens=True, truncation=False)
            lengths = [len(seq) for seq in encoded["input_ids"]]
            trunc_count = sum(1 for l in lengths if l > 512)
            if is_query:
                self.query_truncation_count += trunc_count
            elif is_window:
                self.window_truncation_count += trunc_count
            else:
                self.passage_truncation_count += trunc_count

    def encode_documents(self, doc_ids: List[str], texts: List[str]) -> Tuple[List[dict], List[str]]:
        self.parent_count = len(doc_ids)
        self.parent_to_windows = {}
        
        # Check original passage truncation for diagnostic comparison
        original_prefixed = [f"passage: {t}" for t in texts]
        self._check_truncation(original_prefixed, is_query=False, is_window=False)
        
        flat_window_texts = []
        flat_window_ids = []
        
        windows_manifest = []
        
        for parent_id, text in zip(doc_ids, texts):
            windows = self._chunk_text(text)
            num_windows = len(windows)
            
            if num_windows == 1:
                self.single_window_parent_count += 1
            elif num_windows > 1:
                self.parents_with_multiple_windows += 1
                
            if num_windows > self.max_windows_per_parent:
                self.max_windows_per_parent = num_windows
                
            child_ids = []
            for i, w_text in enumerate(windows):
                w_id = f"{parent_id}_w{i+1:04d}"
                child_ids.append(w_id)
                flat_window_ids.append(w_id)
                prefixed_w = f"passage: {w_text}"
                flat_window_texts.append(prefixed_w)
                
                windows_manifest.append({
                    "parent_chunk_id": parent_id,
                    "window_id": w_id,
                    "window_index": i,
                    "text": w_text
                })
                
            self.parent_to_windows[parent_id] = child_ids
            
        self.window_count = len(flat_window_ids)
        
        # Verify 0 truncation for generated windows
        self._check_truncation(flat_window_texts, is_query=False, is_window=True)
        if self.window_truncation_count > 0:
            raise ValueError(f"Window truncation verification failed: {self.window_truncation_count} windows exceed 512 tokens.")
            
        with torch.no_grad():
            emb = self.model.encode(flat_window_texts, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
            
        self.window_ids = flat_window_ids
        self.window_embeddings = emb
        return windows_manifest, flat_window_texts
        
    def encode_queries(self, queries: List[str]):
        prefixed = [f"query: {q}" for q in queries]
        self._check_truncation(prefixed, is_query=True, is_window=False)
        
        with torch.no_grad():
            return self.model.encode(prefixed, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
            
    def score_embedding(self, q_emb: np.ndarray, allowed_doc_ids: Set[str] = None) -> List[Tuple[str, float]]:
        # Dot product against all windows
        sims = np.dot(self.window_embeddings, q_emb)
        
        # Map child -> similarity
        child_sims = {w_id: float(sims[i]) for i, w_id in enumerate(self.window_ids)}
        
        # Aggregate to parent (MAX pooling)
        parent_scores = {}
        for parent_id, child_ids in self.parent_to_windows.items():
            if allowed_doc_ids is None or parent_id in allowed_doc_ids:
                max_sim = max([child_sims[c] for c in child_ids]) if child_ids else -1.0
                parent_scores[parent_id] = max_sim
                
        # Ranked by similarity descending, doc_id ascending for tie breaks
        ranked = sorted(parent_scores.items(), key=lambda x: (-x[1], x[0]))
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
