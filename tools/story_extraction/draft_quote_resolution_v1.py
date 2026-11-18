"""Pure, conservative quote-copy repair; reports contain counts only.

Offsets are Unicode code-point offsets, just as in the draft compiler. Normalized
characters retain their original source intervals, including NFKC expansions and
compositions. A candidate is accepted only if its entire original substring
normalizes back to the requested quote (partial expansions are never accepted).
"""
from __future__ import annotations

from copy import deepcopy
import re
import unicodedata as ud
from typing import Any


OUTCOMES = ("EXACT", "RESOLVED_NORMALIZED", "RESOLVED_OTHER_PASSAGE", "RESOLVED_ORDERED",
            "UNRESOLVED_NO_MATCH", "UNRESOLVED_MULTIPLE")
_QUOTES = frozenset('「」『』“”‘’"\'')
_DASHES = frozenset("—―–‐-")


def _normalized(text: str) -> tuple[str, list[tuple[int, int]]]:
    """NFKC with source intervals; keep interacting code points in one cluster."""
    clusters: list[tuple[str, int, int]] = []
    for i, char in enumerate(text):
        if clusters:
            previous, start, _ = clusters[-1]
            decomposed = ud.normalize("NFKD", char)
            if (ud.combining(decomposed[0]) or
                    ud.normalize("NFKC", previous + char) !=
                    ud.normalize("NFKC", previous) + ud.normalize("NFKC", char)):
                clusters[-1] = (previous + char, start, i + 1)
                continue
        clusters.append((char, i, i + 1))
    chars, positions = [], []
    for cluster, start, end in clusters:
        for char in ud.normalize("NFKC", cluster):
            if char.isspace():
                continue
            char = '"' if char in _QUOTES else "-" if char in _DASHES else char
            chars.append("~" if char in "〜～" else char)
            positions.append((start, end))
    # NFKC expands … to three dots and ‥ to two. Treat either as one token.
    value = "".join(chars)
    out, index, at = [], [], 0
    for match in re.finditer(r"\.{2,3}", value):
        out.append(value[at:match.start()])
        index.extend(positions[at:match.start()])
        out.append("…")
        index.append((positions[match.start()][0], positions[match.end() - 1][1]))
        at = match.end()
    out.append(value[at:])
    index.extend(positions[at:])
    return "".join(out), index


def _starts(text: str, quote: str) -> list[int]:
    starts, at = [], 0
    while quote:
        at = text.find(quote, at)
        if at < 0:
            break
        starts.append(at)
        at += 1
    return starts


def resolve_quotes(draft: Any, prepared_input: dict) -> tuple[Any, dict]:
    """Repair unambiguous copies, passage handles and ordered mention occurrences.

    Passes run in order: exact, normalization, other passage, ordered mentions.
    Malformed drafts are left for schema validation. Each item contributes one
    final outcome (the last applicable pass), including zero counts per kind.
    """
    result = deepcopy(draft)
    report = {kind: dict.fromkeys(OUTCOMES, 0) for kind in ("evidence", "mentions")}
    passages = {p["handle"]: p["text"] for p in prepared_input.get("passages", [])}
    uses = {p["handle"]: p.get("use") for p in prepared_input.get("passages", [])}
    cache = {}

    def normalized_spans(text, quote):
        if text not in cache:
            cache[text] = _normalized(text)
        normalized, index = cache[text]
        needle, _ = _normalized(quote)
        spans = set()
        for at in _starts(normalized, needle):
            start, end = index[at][0], index[at + len(needle) - 1][1]
            if _normalized(text[start:end])[0] == needle:
                spans.add((start, end))
        return spans

    def set_copy(item, text, start, end):
        exact = text[start:end]
        starts = _starts(text, exact)
        occurrence = item.get("occurrence")
        if len(starts) == 1 or (type(occurrence) is int and
                1 <= occurrence <= len(starts) and starts[occurrence - 1] == start):
            item["quote"] = exact
            if len(starts) == 1:
                item.pop("occurrence", None)
            else:
                item["occurrence"] = starts.index(start) + 1
            return True
        return False

    if not isinstance(result, dict):
        return result, report
    records = []
    for kind in report:
        items = result.get(kind, [])
        if not isinstance(items, list):
            continue
        for item in items:
            code = "UNRESOLVED_NO_MATCH"
            if not isinstance(item, dict):
                records.append([kind, item, code])
                continue
            quote = item.get("quote")
            handle = item.get("passage_handle")
            text = passages.get(handle) if isinstance(handle, str) else None
            if isinstance(quote, str) and quote and isinstance(text, str):
                if _starts(text, quote):
                    records.append([kind, item, "EXACT"])
                    continue
                spans = normalized_spans(text, quote)
                if len(spans) > 1:
                    code = "UNRESOLVED_MULTIPLE"
                elif spans:
                    if set_copy(item, text, *next(iter(spans))):
                        code = "RESOLVED_NORMALIZED"
                    else:
                        code = "UNRESOLVED_MULTIPLE"
            records.append([kind, item, code])

    # Count matching passages before eligibility: an ineligible second match is
    # still doubt about which passage the author meant. Never leave a passage
    # containing even ambiguous normalized matches, or repair malformed handles.
    for record in records:
        kind, item, code = record
        if code != "UNRESOLVED_NO_MATCH" or not isinstance(item, dict):
            continue
        quote, handle = item.get("quote"), item.get("passage_handle")
        if (not isinstance(quote, str) or not quote or not isinstance(handle, str)
                or not isinstance(passages.get(handle), str)):
            continue
        candidates = []
        for target, text in passages.items():
            if target == handle or not isinstance(text, str):
                continue
            starts = _starts(text, quote)
            spans = set() if starts else normalized_spans(text, quote)
            if starts or spans:
                candidates.append((target, text, starts, spans))
        if len(candidates) != 1:
            continue
        target, text, starts, spans = candidates[0]
        if uses[target] != "EVIDENCE_ELIGIBLE":
            continue
        if starts:
            occurrence = item.get("occurrence")
            if len(starts) == 1:
                item.pop("occurrence", None)
            elif "occurrence" in item and (type(occurrence) is not int or
                    not 1 <= occurrence <= len(starts)):
                continue
        elif len(spans) != 1 or not set_copy(item, text, *next(iter(spans))):
            continue
        item["passage_handle"] = target
        record[2] = "RESOLVED_OTHER_PASSAGE"

    groups = {}
    for record in records:
        kind, item, _ = record
        if kind != "mentions" or not isinstance(item, dict):
            continue
        handle, quote = item.get("passage_handle"), item.get("quote")
        if isinstance(handle, str) and isinstance(quote, str) and quote:
            groups.setdefault((handle, quote), []).append(record)
    for (handle, quote), group in groups.items():
        if any("occurrence" in record[1] for record in group):
            continue
        text = passages.get(handle)
        if not isinstance(text, str) or uses[handle] != "EVIDENCE_ELIGIBLE":
            continue
        starts = _starts(text, quote)
        if len(starts) == len(group):
            for occurrence, record in enumerate(group, 1):
                record[1]["occurrence"] = occurrence
                record[2] = "RESOLVED_ORDERED"

    for kind, _, code in records:
        report[kind][code] += 1
    return result, report
