"""Canonical gold-evidence normalization and retrieval metrics.

The v2 representation is ``gold_evidence_sets: list[list[str]]``.  Historical
fixtures containing only ``required_evidence_chunk_ids`` normalize to one gold
set, so existing single-gold metric behavior remains unchanged.
"""
from collections.abc import Mapping, Sequence
from typing import Dict, List, Tuple


DEFAULT_K_VALUES = (1, 3, 5, 10)


class GoldEvidenceValidationError(ValueError):
    """Raised when a probe's gold evidence representation is invalid."""


def normalize_gold_evidence_sets(probe: Mapping) -> Tuple[Tuple[str, ...], ...]:
    """Return the one canonical immutable representation for a probe.

    New and legacy fields are intentionally mutually exclusive.  Duplicate
    chunks and duplicate sets fail validation because both normally indicate
    fixture corruption rather than meaningful relevance judgments.
    """
    has_v2 = "gold_evidence_sets" in probe
    has_legacy = "required_evidence_chunk_ids" in probe
    if has_v2 and has_legacy:
        raise GoldEvidenceValidationError(
            "probe must use either gold_evidence_sets or "
            "required_evidence_chunk_ids, not both"
        )
    if has_v2:
        raw_sets = probe["gold_evidence_sets"]
    elif has_legacy:
        raw_sets = [probe["required_evidence_chunk_ids"]]
    else:
        raise GoldEvidenceValidationError("probe has no gold evidence field")

    if isinstance(raw_sets, (str, bytes)) or not isinstance(raw_sets, Sequence):
        raise GoldEvidenceValidationError("gold evidence sets must be a sequence")
    if not raw_sets:
        raise GoldEvidenceValidationError("at least one gold evidence set is required")

    normalized: List[Tuple[str, ...]] = []
    seen_sets = set()
    for set_index, raw_set in enumerate(raw_sets):
        if isinstance(raw_set, (str, bytes)) or not isinstance(raw_set, Sequence):
            raise GoldEvidenceValidationError(
                f"gold evidence set {set_index} must be a sequence of chunk IDs"
            )
        if not raw_set:
            raise GoldEvidenceValidationError(
                f"gold evidence set {set_index} must not be empty"
            )
        chunks = tuple(raw_set)
        if any(not isinstance(chunk_id, str) or not chunk_id for chunk_id in chunks):
            raise GoldEvidenceValidationError(
                f"gold evidence set {set_index} contains an invalid chunk ID"
            )
        if len(chunks) != len(set(chunks)):
            raise GoldEvidenceValidationError(
                f"gold evidence set {set_index} contains duplicate chunks"
            )
        canonical_identity = frozenset(chunks)
        if canonical_identity in seen_sets:
            raise GoldEvidenceValidationError("duplicate gold evidence sets are not allowed")
        seen_sets.add(canonical_identity)
        normalized.append(chunks)
    return tuple(normalized)


def calculate_probe_metrics(
    probe: Mapping,
    ranked_results: Sequence[str],
    k_values: Sequence[int] = DEFAULT_K_VALUES,
) -> Dict[str, float]:
    """Calculate union-hit/MRR and best-path recall/completion metrics."""
    gold_sets = normalize_gold_evidence_sets(probe)
    gold_sets_as_sets = tuple(frozenset(gold_set) for gold_set in gold_sets)
    gold_union = frozenset().union(*gold_sets_as_sets)
    metrics: Dict[str, float] = {}

    for k in k_values:
        if not isinstance(k, int) or k < 1:
            raise ValueError(f"K must be a positive integer, got {k!r}")
        retrieved = frozenset(ranked_results[:k])
        metrics[f"hit@{k}"] = int(bool(retrieved & gold_union))
        metrics[f"recall@{k}"] = max(
            len(retrieved & gold_set) / len(gold_set)
            for gold_set in gold_sets_as_sets
        )
        metrics[f"success@{k}"] = int(
            any(gold_set <= retrieved for gold_set in gold_sets_as_sets)
        )

    metrics["mrr"] = next(
        (1.0 / rank for rank, chunk_id in enumerate(ranked_results, 1)
         if chunk_id in gold_union),
        0.0,
    )
    return metrics
