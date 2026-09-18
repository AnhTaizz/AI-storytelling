"""
BGE_RERANKER_V2_M3_TOP30_V1 (TASK M1-30CH-M)

Cross-encoder reranking of the frozen DENSE_E5_LARGE_V1 (K) CUTOFF_FILTERED Top-30 candidates
with BAAI/bge-reranker-v2-m3. The candidate set is frozen; the reranker only reorders it.

See benchmarks/m1_script_quality/long_range_probe/BGE_RERANKER_V2_M3_TOP30_V1_METHOD.md
"""
import hashlib
import os
from typing import Dict, List, Optional, Sequence, Tuple

MODEL_ID = "BAAI/bge-reranker-v2-m3"
MODEL_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
MODEL_WEIGHT_FILENAME = "model.safetensors"
MODEL_WEIGHT_SHA256 = "d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286"
TOKENIZER_FILENAME = "tokenizer.json"
TOKENIZER_SHA256 = "69564b696052886ed0ac63fa393e928384e0f8caada38c1f4864a9bfbf379c15"
EXECUTION_DEVICE = "cpu"
DTYPE = "float32"

CANDIDATE_DEPTH = 30
QUERY_MAX_LENGTH = 256
PASSAGE_MAX_LENGTH = 512
SCORING_BATCH_SIZE = 1  # one pair per forward pass: no padding, batch-independent scores
# Public provenance of the pair layout actually built by build_pair_input().
PAIR_FORMAT = ("manual XLM-R pair serialization [CLS] query [SEP][SEP] passage [SEP] "
               "built from tokenizer special-token IDs (cls_token_id, sep_token_id)")


class ModelIdentityError(RuntimeError):
    pass


class CandidateSetError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def sha256_path(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 24), b""):
            h.update(block)
    return h.hexdigest()


def resolve_snapshot_dir(revision: str = MODEL_REVISION) -> str:
    from huggingface_hub import try_to_load_from_cache
    path = try_to_load_from_cache(MODEL_ID, MODEL_WEIGHT_FILENAME, revision=revision)
    if not isinstance(path, str):
        raise ModelIdentityError("frozen reranker snapshot is not in the local cache")
    return os.path.dirname(path)


def verify_model_identity(snapshot_dir: str) -> dict:
    if os.path.basename(os.path.normpath(snapshot_dir)) != MODEL_REVISION:
        raise ModelIdentityError("snapshot directory does not match frozen revision")
    weight = os.path.join(snapshot_dir, MODEL_WEIGHT_FILENAME)
    tok = os.path.join(snapshot_dir, TOKENIZER_FILENAME)
    if not (os.path.exists(weight) and os.path.exists(tok)):
        raise ModelIdentityError("frozen snapshot files are missing")
    w, t = sha256_path(weight), sha256_path(tok)
    if w != MODEL_WEIGHT_SHA256:
        raise ModelIdentityError(f"weight sha256 mismatch: {w}")
    if t != TOKENIZER_SHA256:
        raise ModelIdentityError(f"tokenizer sha256 mismatch: {t}")
    return {"model_weight_sha256": w, "tokenizer_sha256": t}


# ---------------------------------------------------------------------------
# Candidate contract
# ---------------------------------------------------------------------------

def extract_candidates(k_ranking: Sequence[str], depth: int = CANDIDATE_DEPTH) -> List[str]:
    """First `depth` ids of the frozen K ranking; the full pool if it is smaller. Never padded."""
    if len(set(k_ranking)) != len(k_ranking):
        raise CandidateSetError("K ranking contains duplicate ids")
    return list(k_ranking[:depth])


def check_candidate_equality(before: Sequence[str], after: Sequence[str], pool_size: int,
                             depth: int = CANDIDATE_DEPTH) -> None:
    expected_len = min(depth, pool_size)
    if len(before) != expected_len or len(after) != expected_len:
        raise CandidateSetError("candidate count mismatch")
    if len(set(after)) != len(after) or set(before) != set(after):
        raise CandidateSetError("reranked candidate set differs from frozen K Top-30")


def rerank_order(candidates: Sequence[str], scores: Dict[str, float]) -> List[Tuple[str, float]]:
    """Score DESC, then original K rank ASC, then chunk_id ASC."""
    orig = {cid: i + 1 for i, cid in enumerate(candidates)}
    ordered = sorted(candidates, key=lambda c: (-scores[c], orig[c], c))
    return [(c, scores[c]) for c in ordered]


def evaluated_ranking(reranked_top: Sequence[str], k_ranking: Sequence[str]) -> List[str]:
    """Reranked Top-30 followed by the unchanged K tail (ranks > 30)."""
    head = set(reranked_top)
    return list(reranked_top) + [c for c in k_ranking if c not in head]


# ---------------------------------------------------------------------------
# Pair serialization
# ---------------------------------------------------------------------------

def build_pair_input(tokenizer, query: str, passage: str,
                     query_max_length: int = QUERY_MAX_LENGTH,
                     passage_max_length: int = PASSAGE_MAX_LENGTH) -> dict:
    """Standard BGE cross-encoder pair: <s> query </s></s> passage </s>.
    Query and passage are truncated independently to their frozen token budgets."""
    q_ids = tokenizer(query, add_special_tokens=False)["input_ids"]
    p_ids = tokenizer(passage, add_special_tokens=False)["input_ids"]
    cls_id, sep_id = tokenizer.cls_token_id, tokenizer.sep_token_id
    ids = [cls_id] + list(q_ids[:query_max_length]) + [sep_id, sep_id] + list(p_ids[:passage_max_length]) + [sep_id]
    return {"input_ids": ids, "attention_mask": [1] * len(ids),
            "query_truncated": len(q_ids) > query_max_length,
            "passage_truncated": len(p_ids) > passage_max_length,
            "query_tokens": len(q_ids), "passage_tokens": len(p_ids)}


class BgeRerankerV2M3:
    def __init__(self):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        torch.manual_seed(42)
        torch.use_deterministic_algorithms(True, warn_only=True)
        snapshot_dir = resolve_snapshot_dir()
        self.identity = verify_model_identity(snapshot_dir)
        self.tokenizer = AutoTokenizer.from_pretrained(snapshot_dir, local_files_only=True)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            snapshot_dir, local_files_only=True, dtype=torch.float32)
        self.model.to(EXECUTION_DEVICE)
        self.model.eval()

    def get_model_info(self) -> dict:
        import torch
        import transformers
        return {
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "model_weight_filename": MODEL_WEIGHT_FILENAME,
            "model_weight_sha256": self.identity["model_weight_sha256"],
            "tokenizer_filename": TOKENIZER_FILENAME,
            "tokenizer_sha256": self.identity["tokenizer_sha256"],
            "tokenizer_class": type(self.tokenizer).__name__,
            "architecture": type(self.model).__name__,
            "num_labels": int(self.model.config.num_labels),
            "transformers_version": str(transformers.__version__),
            "flagembedding_version": None,
            "torch_version": str(torch.__version__),
            "execution_device": EXECUTION_DEVICE,
            "dtype": str(next(self.model.parameters()).dtype),
        }

    def score(self, query: str, passage: str) -> Tuple[float, dict]:
        import torch
        pair = build_pair_input(self.tokenizer, query, passage)
        ids = torch.tensor([pair["input_ids"]], dtype=torch.long)
        mask = torch.tensor([pair["attention_mask"]], dtype=torch.long)
        with torch.no_grad():
            logit = self.model(input_ids=ids, attention_mask=mask).logits.view(-1)[0]
        return float(logit), pair


# ---------------------------------------------------------------------------
# Diagnostics / verdict
# ---------------------------------------------------------------------------

def within(rank: Optional[int], k: int) -> bool:
    return rank is not None and rank <= k


def rank_of(chunk_id: str, ranking: Sequence[str]) -> Optional[int]:
    try:
        return list(ranking).index(chunk_id) + 1
    except ValueError:
        return None


def transition_type(k_rank: Optional[int], r_rank: Optional[int]) -> str:
    k_in, r_in = within(k_rank, 10), within(r_rank, 10)
    if k_in and r_in:
        return "STAY_TOP10"
    if k_in:
        return "K_TOP10_LOST_BY_RERANK"
    if r_in:
        return "RERANK_TOP10_GAIN_FROM_K"
    return "STAY_OUTSIDE_TOP10"


def interpret_verdict(delta_success10: float, delta_recall10: float, delta_hit10: float,
                      full_success_probes_k: int, full_success_probes_r: int, gates_passed: bool) -> str:
    if not gates_passed:
        return "NOT_EVALUABLE"
    eps = 1e-12
    success_up, recall_up = delta_success10 > eps, delta_recall10 > eps
    hit_up, hit_not_down = delta_hit10 > eps, delta_hit10 >= -eps
    extra_full_probe = full_success_probes_r > full_success_probes_k
    if success_up and recall_up and hit_not_down and extra_full_probe:
        return "SUPPORTED"
    if success_up or recall_up or hit_up:
        return "PARTIALLY_SUPPORTED"
    return "NOT_SUPPORTED"
