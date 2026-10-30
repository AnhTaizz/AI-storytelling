"""Deterministic contextual anchor resolution for STORY_EXTRACTION_DRAFT_V1_2.

An anchor is an exact quote plus optional exact context immediately before and after
it, all inside one passage text. Resolution never normalizes, never counts on the
model's behalf and never breaks ties by position: it returns RESOLVED only when
exactly one candidate satisfies every supplied constraint.

Positions are Unicode code-point offsets into the passage string, the same unit the
M3 adapter uses for ``char_start``. Byte offsets are derived by the adapter from the
exact UTF-8 source, so this module never computes or reports bytes for provenance.
"""
from __future__ import annotations

from dataclasses import dataclass
import unicodedata
from typing import Optional


RESOLVER_VERSION = "CONTEXTUAL_ANCHOR_RESOLVER_V1"
MAX_CONTEXT_CODE_POINTS = 32

RESOLVED = "RESOLVED"
NOT_FOUND = "NOT_FOUND"
AMBIGUOUS = "AMBIGUOUS"
INVALID = "INVALID"


@dataclass(frozen=True)
class AnchorResolution:
    status: str
    detail: str
    start: Optional[int]
    end: Optional[int]
    candidate_count: int
    surviving_count: int
    hints: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "detail": self.detail,
            "start": self.start,
            "end": self.end,
            "candidate_count": self.candidate_count,
            "surviving_count": self.surviving_count,
            "hints": list(self.hints),
        }


def candidate_starts(text: str, quote: str) -> list[int]:
    """Every start of ``quote`` in ``text``, overlapping matches included."""
    starts, at = [], 0
    while True:
        at = text.find(quote, at)
        if at < 0:
            return starts
        starts.append(at)
        at += 1


def _valid_text(value: object, *, allow_none: bool, max_length: Optional[int]) -> bool:
    if value is None:
        return allow_none
    if not isinstance(value, str) or not value:
        return False
    if max_length is not None and len(value) > max_length:
        return False
    # A lone surrogate cannot come from valid UTF-8 source text.
    return not any(0xD800 <= ord(char) <= 0xDFFF for char in value)


def _hints(text: str, quote: str) -> tuple[str, ...]:
    """Diagnostic hints for a missing quote. Hints never resolve anything."""
    hints = []
    if unicodedata.normalize("NFC", quote) in unicodedata.normalize("NFC", text):
        hints.append("NORMALIZATION_VARIANT_PRESENT")
    elif unicodedata.normalize("NFKC", quote) in unicodedata.normalize("NFKC", text):
        hints.append("COMPATIBILITY_VARIANT_PRESENT")
    return tuple(hints)


def resolve_anchor(text: str, quote: str, context_before: Optional[str] = None,
                   context_after: Optional[str] = None) -> AnchorResolution:
    """Resolve one anchor against one exact passage text."""
    if not isinstance(text, str) or not _valid_text(quote, allow_none=False, max_length=None):
        return AnchorResolution(INVALID, "INVALID_QUOTE", None, None, 0, 0)
    for context in (context_before, context_after):
        if not _valid_text(context, allow_none=True, max_length=MAX_CONTEXT_CODE_POINTS):
            return AnchorResolution(INVALID, "INVALID_CONTEXT", None, None, 0, 0)
    starts = candidate_starts(text, quote)
    if not starts:
        return AnchorResolution(NOT_FOUND, "QUOTE_ABSENT", None, None, 0, 0, _hints(text, quote))
    survivors = []
    for start in starts:
        end = start + len(quote)
        if context_before is not None:
            if start < len(context_before) or text[start - len(context_before):start] != context_before:
                continue
        if context_after is not None:
            if text[end:end + len(context_after)] != context_after:
                continue
        survivors.append(start)
    if not survivors:
        return AnchorResolution(NOT_FOUND, "CONTEXT_MISMATCH", None, None, len(starts), 0)
    if len(survivors) > 1:
        return AnchorResolution(AMBIGUOUS, "MULTIPLE_CANDIDATES", None, None,
                                len(starts), len(survivors))
    start = survivors[0]
    return AnchorResolution(RESOLVED, "UNIQUE", start, start + len(quote), len(starts), 1)


def occurrence_of(text: str, quote: str, start: int) -> int:
    """1-based index of ``start`` among all overlapping candidates (host-computed)."""
    starts = candidate_starts(text, quote)
    if start not in starts:
        raise ValueError("start is not a candidate of quote")
    return starts.index(start) + 1


def minimal_unique_context(text: str, start: int, end: int,
                           max_length: int = MAX_CONTEXT_CODE_POINTS
                           ) -> Optional[tuple[Optional[str], Optional[str]]]:
    """Shortest exact context that makes [start, end) unique, or None if none exists.

    Search order is deterministic: no context; then for k = 1..max_length the
    before-only, after-only and both-sides contexts of length k (clipped at the
    passage boundary). A context is accepted only if it resolves to ``start``.
    """
    quote = text[start:end]
    if not quote:
        return None
    options: list[tuple[Optional[str], Optional[str]]] = [(None, None)]
    for k in range(1, max_length + 1):
        before = text[max(0, start - k):start] or None
        after = text[end:end + k] or None
        options.extend(((before, None), (None, after), (before, after)))
    seen = set()
    for before, after in options:
        if (before, after) in seen:
            continue
        seen.add((before, after))
        result = resolve_anchor(text, quote, before, after)
        if result.status == RESOLVED and result.start == start:
            return before, after
    return None
