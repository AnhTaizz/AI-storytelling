"""
KM_CONSENSUS_RANK_SUM_V1 (TASK M1-30CH-O)

Equal-weight rank consensus of frozen DENSE_E5_LARGE_V1 (K) Top-30 candidates
and BGE_RERANKER_V2_M3_TOP30_V1 (M) reranked candidates.

See benchmarks/m1_script_quality/long_range_probe/KM_CONSENSUS_RANK_SUM_V1_METHOD.md
"""
from typing import Dict, List, Optional, Sequence, Tuple

CANDIDATE_DEPTH = 30
TRANSITIONS = (
    "STAY_TOP10",
    "M_TOP10_LOST_BY_CONSENSUS",
    "CONSENSUS_TOP10_GAIN_FROM_M",
    "STAY_OUTSIDE_TOP10",
)


class CandidateSetError(RuntimeError):
    pass


class AntiLeakageError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Pure Consensus Selector (Gold-Blind)
# ---------------------------------------------------------------------------

def select_consensus(
    k_candidate_ids: Sequence[str],
    m_candidate_ids: Sequence[str],
    expected_depth: int = CANDIDATE_DEPTH,
) -> List[str]:
    """
    Pure selector function operating strictly on candidate chunk IDs and their positions in K and M.

    Inputs MUST NOT contain gold labels, probe IDs, queries, answers, or categories.

    Consensus rule:
      rank_sum = k_rank + m_rank (1-based)
      Tie-break (symmetric between K and M):
        1. lower max(k_rank, m_rank)
        2. lower min(k_rank, m_rank)
        3. chunk_id ASC
    """
    k_list = list(k_candidate_ids)
    m_list = list(m_candidate_ids)

    if len(k_list) != len(set(k_list)):
        raise CandidateSetError("K candidate list contains duplicates")
    if len(m_list) != len(set(m_list)):
        raise CandidateSetError("M candidate list contains duplicates")
    if set(k_list) != set(m_list):
        raise CandidateSetError("K and M candidate sets do not match exactly")
    if len(k_list) != expected_depth:
        raise CandidateSetError(f"Candidate count {len(k_list)} does not match expected depth {expected_depth}")

    k_ranks = {cid: idx + 1 for idx, cid in enumerate(k_list)}
    m_ranks = {cid: idx + 1 for idx, cid in enumerate(m_list)}

    # Sorter key: (rank_sum, max_rank, min_rank, chunk_id)
    def sort_key(cid: str) -> Tuple[int, int, int, str]:
        kr = k_ranks[cid]
        mr = m_ranks[cid]
        return (kr + mr, max(kr, mr), min(kr, mr), cid)

    sorted_cands = sorted(k_list, key=sort_key)
    return sorted_cands


def rank_sum_details(
    k_candidate_ids: Sequence[str],
    m_candidate_ids: Sequence[str],
    expected_depth: int = CANDIDATE_DEPTH,
) -> Dict[str, dict]:
    """
    Returns diagnostic rank information for each candidate chunk ID.
    Operates strictly on candidate lists without gold labels.
    """
    ordered = select_consensus(k_candidate_ids, m_candidate_ids, expected_depth=expected_depth)
    k_ranks = {cid: idx + 1 for idx, cid in enumerate(k_candidate_ids)}
    m_ranks = {cid: idx + 1 for idx, cid in enumerate(m_candidate_ids)}

    out = {}
    for consensus_idx, cid in enumerate(ordered):
        kr = k_ranks[cid]
        mr = m_ranks[cid]
        out[cid] = {
            "chunk_id": cid,
            "k_rank": kr,
            "m_rank": mr,
            "rank_sum": kr + mr,
            "max_rank": max(kr, mr),
            "min_rank": min(kr, mr),
            "consensus_rank": consensus_idx + 1,
        }
    return out


def evaluated_ranking(consensus_top: Sequence[str], k_ranking: Sequence[str]) -> List[str]:
    """Consensus Top-30 followed by the unchanged K tail (ranks > 30)."""
    head = set(consensus_top)
    return list(consensus_top) + [c for c in k_ranking if c not in head]


# ---------------------------------------------------------------------------
# Evaluator Helpers
# ---------------------------------------------------------------------------

def within(rank: Optional[int], k: int) -> bool:
    return rank is not None and rank <= k


def rank_of(chunk_id: str, ranking: Sequence[str]) -> Optional[int]:
    try:
        return list(ranking).index(chunk_id) + 1
    except ValueError:
        return None


def transition_type(m_rank: Optional[int], c_rank: Optional[int]) -> str:
    """Classify transition of a required unit from M Top-10 to Consensus Top-10."""
    m_in = within(m_rank, 10)
    c_in = within(c_rank, 10)
    if m_in and c_in:
        return "STAY_TOP10"
    if m_in and not c_in:
        return "M_TOP10_LOST_BY_CONSENSUS"
    if not m_in and c_in:
        return "CONSENSUS_TOP10_GAIN_FROM_M"
    return "STAY_OUTSIDE_TOP10"


def rank_bucket(rank: Optional[int]) -> str:
    if rank is None:
        return "missing"
    if rank <= 10:
        return "<=10"
    if rank <= 15:
        return "11-15"
    if rank <= 20:
        return "16-20"
    if rank <= 30:
        return "21-30"
    return ">30"


def interpret_verdict(
    delta_success10: float,
    delta_recall10: float,
    delta_hit10: float,
    full_success_gained: int,
    full_success_lost: int,
    gates_passed: bool,
) -> str:
    """
    Frozen verdict rule:
    SUPPORTED:
      delta_success10 > 0 AND delta_recall10 >= 0 AND delta_hit10 >= 0
      AND full_success_gained > full_success_lost
    PARTIALLY_SUPPORTED:
      at least one delta > 0 (success, recall, or hit)
    NOT_SUPPORTED:
      all deltas <= 0
    NOT_EVALUABLE:
      critical gates failed
    """
    if not gates_passed:
        return "NOT_EVALUABLE"

    eps = 1e-12
    success_up = delta_success10 > eps
    recall_up = delta_recall10 > eps
    hit_up = delta_hit10 > eps

    recall_nonneg = delta_recall10 >= -eps
    hit_nonneg = delta_hit10 >= -eps

    if (
        success_up
        and recall_nonneg
        and hit_nonneg
        and full_success_gained > full_success_lost
    ):
        return "SUPPORTED"

    if success_up or recall_up or hit_up:
        return "PARTIALLY_SUPPORTED"

    if (
        delta_success10 <= eps
        and delta_recall10 <= eps
        and delta_hit10 <= eps
    ):
        return "NOT_SUPPORTED"

    return "NOT_SUPPORTED"
