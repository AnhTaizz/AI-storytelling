"""
DENSE_E5_LARGE_V1 (TASK M1-30CH-K)

Controlled model-capacity test: identical to DENSE_E5_SMALL_V1 (F) except the encoder is
intfloat/multilingual-e5-large at a frozen immutable snapshot.

Kept as a standalone class (duplicating F) so the frozen F implementation is untouched.
See benchmarks/m1_script_quality/long_range_probe/DENSE_E5_LARGE_V1_METHOD.md
"""
import hashlib
import os
from typing import List, Optional, Sequence, Set, Tuple

import numpy as np

MODEL_ID = "intfloat/multilingual-e5-large"
MODEL_REVISION = "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"
MODEL_WEIGHT_FILENAME = "model.safetensors"
MODEL_WEIGHT_SHA256 = "020afdebf2762b29fcaf286629a96c3b3b65af241f6a08226b1cfee60a21def6"
TOKENIZER_FILENAME = "tokenizer.json"
TOKENIZER_SHA256 = "62c24cdc13d4c9952d63718d6c9fa4c287974249e16b7ade6d5a85e7bbb75626"
EXPECTED_EMBEDDING_DIMENSION = 1024
MAX_SEQ_LENGTH = 512
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "
EXECUTION_DEVICE = "cpu"
# Infrastructure-only (memory); does not change retrieval semantics.
PASSAGE_ENCODE_BATCH_SIZE = 4

RANK_BUCKETS = ("1-10", "11-20", "21-50", ">50", "missing")
COMPLETENESS_KS = (10, 20, 30, 50)
HIT10_MAJOR_COLLAPSE_DELTA = -0.10
PARTIAL_MIN_DEEP_RESCUES = 3


class ModelIdentityError(RuntimeError):
    pass


def sha256_path(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 24), b""):
            h.update(block)
    return h.hexdigest()


def resolve_snapshot_dir(revision: str = MODEL_REVISION) -> str:
    """Locate the cached snapshot of the frozen revision (only the ST-required files are cached)."""
    from huggingface_hub import try_to_load_from_cache
    path = try_to_load_from_cache(MODEL_ID, MODEL_WEIGHT_FILENAME, revision=revision)
    if not isinstance(path, str):
        raise ModelIdentityError("frozen model snapshot is not in the local cache")
    return os.path.dirname(path)


def verify_model_identity(snapshot_dir: str) -> dict:
    """Mechanically checks the frozen snapshot files before the model is used."""
    if os.path.basename(os.path.normpath(snapshot_dir)) != MODEL_REVISION:
        raise ModelIdentityError("snapshot directory does not match frozen revision")
    weight = os.path.join(snapshot_dir, MODEL_WEIGHT_FILENAME)
    tok = os.path.join(snapshot_dir, TOKENIZER_FILENAME)
    if not os.path.exists(weight) or not os.path.exists(tok):
        raise ModelIdentityError("frozen snapshot files are missing")
    w_sha, t_sha = sha256_path(weight), sha256_path(tok)
    if w_sha != MODEL_WEIGHT_SHA256:
        raise ModelIdentityError(f"weight sha256 mismatch: {w_sha}")
    if t_sha != TOKENIZER_SHA256:
        raise ModelIdentityError(f"tokenizer sha256 mismatch: {t_sha}")
    return {"model_weight_sha256": w_sha, "tokenizer_sha256": t_sha}


class DenseE5LargeV1:
    """
    - Model: intfloat/multilingual-e5-large @ frozen revision, CPU, fp32
    - Max sequence length: 512 (default truncation, same as F)
    - Asymmetric formatting (query: / passage: )
    - Unit-normalized embeddings, cosine (dot) ranking
    - Tie break: chunk_id ascending
    """

    def __init__(self):
        import torch
        from sentence_transformers import SentenceTransformer

        torch.manual_seed(42)
        np.random.seed(42)
        torch.use_deterministic_algorithms(True, warn_only=True)

        snapshot_dir = resolve_snapshot_dir()
        self.identity = verify_model_identity(snapshot_dir)

        self.model_name = MODEL_ID
        self.model_revision = MODEL_REVISION
        self.device = EXECUTION_DEVICE
        # Load from the hash-verified snapshot directory of the frozen revision.
        self.model = SentenceTransformer(snapshot_dir, device=EXECUTION_DEVICE, local_files_only=True)
        self.model.max_seq_length = MAX_SEQ_LENGTH
        self.model.eval()
        self._reset_state()

    def _reset_state(self):
        self.passage_truncation_count = 0
        self.query_truncation_count = 0
        self.doc_ids: List[str] = []
        self.doc_embeddings: Optional[np.ndarray] = None

    def embedding_dimension(self) -> int:
        getter = getattr(self.model, "get_embedding_dimension", None) or self.model.get_sentence_embedding_dimension
        return int(getter())

    def get_model_info(self) -> dict:
        import sentence_transformers
        import torch
        import transformers
        return {
            "model_id": self.model_name,
            "model_revision": self.model_revision,
            "model_weight_filename": MODEL_WEIGHT_FILENAME,
            "model_weight_sha256": self.identity["model_weight_sha256"],
            "tokenizer_filename": TOKENIZER_FILENAME,
            "tokenizer_sha256": self.identity["tokenizer_sha256"],
            "tokenizer_class": type(self.model.tokenizer).__name__,
            "embedding_dimension": self.embedding_dimension(),
            "max_seq_length": int(self.model.max_seq_length),
            "sentence_transformers_version": str(sentence_transformers.__version__),
            "transformers_version": str(transformers.__version__),
            "torch_version": str(torch.__version__),
            "torch_default_dtype": str(torch.get_default_dtype()),
            "execution_device": self.device,
        }

    def _check_truncation(self, texts: Sequence[str], is_query: bool):
        encoded = self.model.tokenizer(list(texts), add_special_tokens=True, truncation=False)
        count = sum(1 for seq in encoded["input_ids"] if len(seq) > MAX_SEQ_LENGTH)
        if is_query:
            self.query_truncation_count += count
        else:
            self.passage_truncation_count += count

    def encode_documents(self, doc_ids: Sequence[str], texts: Sequence[str]) -> np.ndarray:
        import torch
        prefixed = [f"{PASSAGE_PREFIX}{t}" for t in texts]
        self._check_truncation(prefixed, is_query=False)
        with torch.no_grad():
            emb = self.model.encode(prefixed, batch_size=PASSAGE_ENCODE_BATCH_SIZE, convert_to_numpy=True,
                                    normalize_embeddings=True, show_progress_bar=False)
        self.doc_ids = list(doc_ids)
        self.doc_embeddings = emb
        return emb

    def encode_queries(self, queries: Sequence[str]) -> np.ndarray:
        import torch
        prefixed = [f"{QUERY_PREFIX}{q}" for q in queries]
        self._check_truncation(prefixed, is_query=True)
        with torch.no_grad():
            return self.model.encode(prefixed, convert_to_numpy=True, normalize_embeddings=True,
                                     show_progress_bar=False)

    def score_embedding(self, q_emb: np.ndarray, allowed_doc_ids: Set[str] = None) -> List[Tuple[str, float]]:
        return rank_by_cosine(self.doc_ids, self.doc_embeddings, q_emb, allowed_doc_ids)


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def rank_by_cosine(doc_ids: Sequence[str], doc_embeddings: np.ndarray, q_emb: np.ndarray,
                   allowed_doc_ids: Set[str] = None) -> List[Tuple[str, float]]:
    sims = np.dot(doc_embeddings, q_emb)
    scores = {d: float(sims[i]) for i, d in enumerate(doc_ids) if allowed_doc_ids is None or d in allowed_doc_ids}
    return sorted(scores.items(), key=lambda x: (-x[1], x[0]))


def eligible_doc_ids(chunk_meta, cutoff_chapter) -> Set[str]:
    if cutoff_chapter is None:
        return set(chunk_meta)
    return {cid for cid, chap in chunk_meta.items() if chap <= cutoff_chapter}


def calculate_metrics(probe: dict, ranked_results: Sequence[str]) -> dict:
    """Identical definitions to DENSE_E5_SMALL_V1.calculate_metrics."""
    req_ev = set(probe["required_evidence_chunk_ids"])
    metrics = {}
    for k in (1, 3, 5, 10):
        top_k = ranked_results[:k]
        hit = 1 if any(c in req_ev for c in top_k) else 0
        recall = sum(1 for c in req_ev if c in top_k) / len(req_ev) if req_ev else 0
        metrics[f"hit@{k}"] = hit
        metrics[f"recall@{k}"] = recall
        metrics[f"success@{k}"] = 1 if recall == 1.0 else 0
    mrr = 0.0
    for i, doc_id in enumerate(ranked_results):
        if doc_id in req_ev:
            mrr = 1.0 / (i + 1)
            break
    metrics["mrr"] = mrr
    return metrics


def rank_of(chunk_id: str, ranking: Sequence[str]) -> Optional[int]:
    try:
        return list(ranking).index(chunk_id) + 1
    except ValueError:
        return None


def rank_bucket(rank: Optional[int]) -> str:
    if rank is None:
        return "missing"
    if rank < 1:
        raise ValueError("ranks are 1-based")
    if rank <= 10:
        return "1-10"
    if rank <= 20:
        return "11-20"
    if rank <= 50:
        return "21-50"
    return ">50"


def within(rank: Optional[int], k: int) -> bool:
    return rank is not None and rank <= k


def median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    if not s:
        return 0.0
    m = len(s) // 2
    return float(s[m]) if len(s) % 2 else float((s[m - 1] + s[m]) / 2)


def f_missed_population(probes, f_rankings: dict) -> List[dict]:
    """J population: required units ranked outside F Top-10 (gold + F ranking only)."""
    pop = []
    for p in probes:
        ranking = f_rankings[p["probe_id"]]
        for cid in p["required_evidence_chunk_ids"]:
            r = rank_of(cid, ranking)
            if not within(r, 10):
                pop.append({"probe_id": p["probe_id"], "category": p["category"],
                            "required_chunk_id": cid, "f_rank": r})
    return pop


def rank_shift_rows(population: Sequence[dict], k_rankings: dict) -> List[dict]:
    rows = []
    for u in population:
        k_rank = rank_of(u["required_chunk_id"], k_rankings[u["probe_id"]])
        delta = (u["f_rank"] - k_rank) if (u["f_rank"] is not None and k_rank is not None) else None
        rows.append({**u, "k_rank": k_rank, "rank_delta_f_minus_k": delta,
                     "f_bucket": rank_bucket(u["f_rank"]), "k_bucket": rank_bucket(k_rank)})
    return rows


def rank_shift_aggregate(rows: Sequence[dict]) -> dict:
    n = len(rows)
    improved = sum(1 for r in rows if r["rank_delta_f_minus_k"] is not None and r["rank_delta_f_minus_k"] > 0)
    same = sum(1 for r in rows if r["rank_delta_f_minus_k"] == 0)
    worse = sum(1 for r in rows if r["rank_delta_f_minus_k"] is not None and r["rank_delta_f_minus_k"] < 0)
    dist = {b: sum(1 for r in rows if r["k_bucket"] == b) for b in RANK_BUCKETS}
    return {
        "population_size": n,
        "rank_improved": improved,
        "rank_same": same,
        "rank_worsened": worse,
        "f_gt10_to_k_le10": sum(1 for r in rows if not within(r["f_rank"], 10) and within(r["k_rank"], 10)),
        "f_gt20_to_k_le20": sum(1 for r in rows if not within(r["f_rank"], 20) and within(r["k_rank"], 20)),
        "f_gt50_to_k_le50": sum(1 for r in rows if not within(r["f_rank"], 50) and within(r["k_rank"], 50)),
        "f_gt20_units": sum(1 for r in rows if not within(r["f_rank"], 20)),
        "f_gt50_units": sum(1 for r in rows if not within(r["f_rank"], 50)),
        "median_f_rank": median([r["f_rank"] for r in rows if r["f_rank"] is not None]),
        "median_k_rank": median([r["k_rank"] for r in rows if r["k_rank"] is not None]),
        "k_rank_distribution": {b: {"count": dist[b], "fraction": dist[b] / n if n else 0.0} for b in RANK_BUCKETS},
    }


def completeness_curve(probes, rankings: dict, ks: Sequence[int] = COMPLETENESS_KS) -> dict:
    out = {}
    n = len(probes)
    for k in ks:
        recall = success = 0.0
        for p in probes:
            ranks = [rank_of(c, rankings[p["probe_id"]]) for c in p["required_evidence_chunk_ids"]]
            got = sum(1 for r in ranks if within(r, k))
            recall += got / len(ranks)
            success += 1 if got == len(ranks) else 0
        out[f"K{k}"] = {"recall": recall / n, "full_evidence_success": success / n}
    return out


def interpret_verdict(delta_recall10: float, delta_success10: float, delta_hit10: float,
                      f_gt20_to_k_le20: int, gates_passed: bool) -> str:
    if not gates_passed:
        return "NOT_EVALUABLE"
    eps = 1e-12
    recall_up = delta_recall10 > eps
    success_up = delta_success10 > eps
    no_collapse = delta_hit10 >= HIT10_MAJOR_COLLAPSE_DELTA - eps
    if recall_up and success_up and no_collapse and f_gt20_to_k_le20 >= 1:
        return "SUPPORTED"
    if recall_up or success_up or f_gt20_to_k_le20 >= PARTIAL_MIN_DEEP_RESCUES:
        return "PARTIALLY_SUPPORTED"
    return "NOT_SUPPORTED"
