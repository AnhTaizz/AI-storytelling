"""Deterministic fresh-holdout selection for Story Extraction (M4_FRESH_HOLDOUT_SELECTION_V1).

Pure functions over segment ids. No source text is read here, no randomness is used,
and nothing is selected by a person: the order comes from a hash, and exclusions come
from a semantic exposure registry built before any candidate is looked at.

Protocol: docs/research/m4/M4_FRESH_HOLDOUT_PROTOCOL_V1.md
"""
import hashlib
from typing import Dict, Iterable, List, Optional, Sequence, Set

PROTOCOL_ID = "M4_FRESH_HOLDOUT_SELECTION_V1"
HALO = 2                     # segments excluded on each side of a semantically exposed segment
WINDOW_BEFORE = 3
WINDOW_AFTER = 3
MIN_WINDOW_SEGMENTS = 5
TARGET_CASES = 12
REJECTION_REASONS = ("NO_STORY_CONTENT", "PURE_PARATEXT", "SOURCE_CORRUPTION",
                     "WINDOW_HAS_NO_IN_PROFILE_ASSERTION",
                     "WINDOW_DEPENDS_ON_EXCLUDED_CONTEXT_TO_BE_INTERPRETABLE")


def anchor_hash(corpus_fingerprint: str, segment_id: str, protocol_id: str = PROTOCOL_ID) -> str:
    return hashlib.sha256((protocol_id + corpus_fingerprint + segment_id).encode("utf-8")).hexdigest()


def exposure_halo(documents: Dict[str, Sequence[str]], exposed: Set[str], halo: int = HALO) -> Set[str]:
    """Segments within `halo` positions of an exposed segment in the same document (exposed ones excluded)."""
    out: Set[str] = set()
    for segments in documents.values():
        for index, segment_id in enumerate(segments):
            if segment_id in exposed:
                out.update(segments[max(0, index - halo):index + halo + 1])
    return out - exposed


def build_window(segments: Sequence[str], anchor: str, excluded: Set[str],
                 before: int = WINDOW_BEFORE, after: int = WINDOW_AFTER) -> List[str]:
    """Up to `before` segments before and `after` after the anchor, in one document.

    The window is clipped at the document boundary and at the first excluded segment on
    either side, so it is always a run of consecutive, non-excluded segments.
    """
    index = segments.index(anchor)
    low = index
    while low > 0 and index - low < before and segments[low - 1] not in excluded:
        low -= 1
    high = index
    while high < len(segments) - 1 and high - index < after and segments[high + 1] not in excluded:
        high += 1
    return list(segments[low:high + 1])


def eligible_anchors(documents: Dict[str, Sequence[str]], excluded: Set[str],
                     min_window: int = MIN_WINDOW_SEGMENTS) -> Dict[str, List[str]]:
    """Anchor -> window for every segment that is not excluded and has a large enough window."""
    out: Dict[str, List[str]] = {}
    for segments in documents.values():
        for segment_id in segments:
            if segment_id not in excluded:
                window = build_window(segments, segment_id, excluded)
                if len(window) >= min_window:
                    out[segment_id] = window
    return out


def ordered_anchors(anchors: Iterable[str], corpus_fingerprint: str) -> List[str]:
    return sorted(anchors, key=lambda s: (anchor_hash(corpus_fingerprint, s), s))


def _take(order: Sequence[str], document_of: Dict[str, str], windows: Dict[str, List[str]],
          selected: List[str], skip: Set[str], limit: int, target: int, trace: Optional[List[dict]] = None,
          pass_name: str = "") -> None:
    for rank, anchor in enumerate(order, start=1):
        if len(selected) >= target:
            return
        if anchor in selected or anchor in skip:
            continue
        document = document_of[anchor]
        if sum(1 for s in selected if document_of[s] == document) >= limit:
            continue
        taken = {seg for s in selected for seg in windows[s]}
        if taken & set(windows[anchor]):
            continue                          # windows of two cases never share a segment
        selected.append(anchor)
        if trace is not None:
            trace.append({"hash_rank": rank, "pass": pass_name})


def select_cases(order: Sequence[str], document_of: Dict[str, str], windows: Dict[str, List[str]],
                 target: int = TARGET_CASES) -> Dict[str, list]:
    """First pass: at most one anchor per document, in hash order. Second pass (only if the target
    is not reached): at most one more per document, in hash order."""
    selected: List[str] = []
    trace: List[dict] = []
    _take(order, document_of, windows, selected, set(), 1, target, trace, "FIRST_PASS")
    _take(order, document_of, windows, selected, set(), 2, target, trace, "SECOND_PASS")
    return {"selected": selected, "trace": trace}


def replace_rejected(order: Sequence[str], document_of: Dict[str, str], windows: Dict[str, List[str]],
                     selected: Sequence[str], rejections: Dict[str, str], target: int = TARGET_CASES) -> Dict[str, list]:
    """Replace rejected anchors by the next unused anchors in the preregistered hash order.

    `rejections` maps a rejected anchor to its reason. A rejected anchor is never reused. The
    document-diversity limits are the same as at selection time.
    """
    for reason in rejections.values():
        if reason not in REJECTION_REASONS:
            raise ValueError(f"not a preregistered rejection reason: {reason}")
    rank = {anchor: i for i, anchor in enumerate(order, start=1)}
    kept = [s for s in selected if s not in rejections]
    final = list(kept)
    skip = set(rejections) | set(selected)
    trace = []
    for rejected in [s for s in selected if s in rejections]:
        before = list(final)
        _take(order, document_of, windows, final, skip, 1, len(before) + 1)
        if len(final) == len(before):
            _take(order, document_of, windows, final, skip, 2, len(before) + 1)
        replacement = final[-1] if len(final) > len(before) else None
        if replacement is not None:
            skip.add(replacement)
        trace.append({"rejected_hash_rank": rank[rejected], "reason": rejections[rejected],
                      "replacement_hash_rank": rank.get(replacement)})
    return {"selected": final, "replacement_trace": trace, "complete": len(final) >= min(target, len(selected))}
