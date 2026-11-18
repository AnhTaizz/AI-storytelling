"""Narrow assertion evidence to a located mention or a verbatim name."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from tools.story_extraction.draft_mention_anchoring_v1 import _records, _references
from tools.story_extraction.draft_quote_resolution_v1 import _starts


PREDICATES = ("RefersTo", "NamedAs")
# Each assertion contributes its first applicable outcome in this order.
OUTCOMES = ("NARROWED", "ALREADY_EXACT", "REFUSED_AMBIGUOUS", "REFUSED_NOT_LOCATED",
            "REFUSED_NOT_CONTAINED", "REFUSED_MULTI_ITEM_SET")


def _by_handle(records):
    return {record["handle"]: record for record in _records(records)
            if isinstance(record.get("handle"), str)}


def _object(value):
    return value if isinstance(value, dict) else {}


def _located(item, passages):
    """Use the same eligible-passage and occurrence checks as mention anchoring."""
    handle, quote = item.get("passage_handle"), item.get("quote")
    text = passages.get(handle) if isinstance(handle, str) else None
    if text is None or not isinstance(quote, str) or not quote:
        return None
    starts = _starts(text, quote)
    occurrence = item.get("occurrence", 1 if len(starts) == 1 else None)
    if type(occurrence) is not int or not 1 <= occurrence <= len(starts):
        return None
    start = starts[occurrence - 1]
    return handle, start, start + len(quote)


def _target(predicate, args, mentions, passages, cited_span):
    if predicate == "RefersTo":
        argument = _object(args.get("mention"))
        handle = argument.get("handle")
        if argument.get("kind") != "MENTION" or not isinstance(handle, str):
            return None, "REFUSED_NOT_LOCATED"
        return _located(mentions.get(handle, {}), passages), "REFUSED_NOT_LOCATED"

    argument = _object(args.get("name"))
    name = argument.get("value")
    if (argument.get("kind") != "LITERAL" or argument.get("value_type") != "STRING"
            or not isinstance(name, str) or not name):
        return None, "REFUSED_NOT_LOCATED"
    passage, start, end = cited_span
    starts = _starts(passages[passage][start:end], name)
    if len(starts) != 1:
        return None, "REFUSED_AMBIGUOUS" if starts else "REFUSED_NOT_CONTAINED"
    at = start + starts[0]
    return (passage, at, at + len(name)), None


def narrow_mention_evidence(draft: Any, prepared_input: Mapping[str, Any], *,
                            predicates: Sequence[str] = PREDICATES) -> tuple[Any, dict]:
    """Return a deep copy and one counts-only outcome per selected assertion.

    A replacement takes precedence over an exact set or a refusal on another
    set. An assertion with no sufficient evidence set is counted as not contained.
    """
    result = deepcopy(draft)
    report = {"by_predicate": {p: dict.fromkeys(OUTCOMES, 0) for p in PREDICATES if p in predicates},
              "evidence_items_added": 0, "evidence_items_removed": 0}
    if not isinstance(result, dict):
        return result, report

    passages = {handle: p["text"] for handle, p in _by_handle(prepared_input.get("passages")).items()
                if p.get("use") == "EVIDENCE_ELIGIBLE" and isinstance(p.get("text"), str)}
    mentions = _by_handle(result.get("mentions"))
    propositions = _by_handle(result.get("propositions"))
    evidence = _by_handle(result.get("evidence"))
    located = {}
    exact_items = {}
    for handle, item in evidence.items():
        span, role = _located(item, passages), item.get("role")
        if span is not None and isinstance(role, str):
            located[handle] = span
            exact_items.setdefault((span, role), handle)

    # Reserve definitions and references, including malformed dangling references.
    occupied = set(_references(result))
    for records in result.values():
        occupied.update(_by_handle(records))
    next_number = 1
    replaced = set()
    for assertion in _records(result.get("assertions")):
        handle = assertion.get("proposition_handle")
        proposition = propositions.get(handle, {}) if isinstance(handle, str) else {}
        predicate = proposition.get("predicate")
        if not isinstance(predicate, str) or predicate not in report["by_predicate"]:
            continue
        args = _object(proposition.get("args"))
        support = _object(assertion.get("support"))
        outcomes = set()
        for group in _records(support.get("evidence_sets")):
            if group.get("label") != "SUFFICIENT":
                continue
            cited = group.get("evidence_handles")
            if not isinstance(cited, list) or not cited:
                outcomes.add("REFUSED_NOT_LOCATED")
                continue
            if len(cited) > 1:
                outcomes.add("REFUSED_MULTI_ITEM_SET")
                continue
            old = cited[0]
            span = located.get(old) if isinstance(old, str) else None
            if span is None:
                outcomes.add("REFUSED_NOT_LOCATED")
                continue
            target, refusal = _target(predicate, args, mentions, passages, span)
            if target is None:
                outcomes.add(refusal)
                continue
            passage, start, end = target
            if target == span:
                outcomes.add("ALREADY_EXACT")
            elif passage != span[0] or start < span[1] or end > span[2]:
                outcomes.add("REFUSED_NOT_CONTAINED")
            else:
                item = evidence[old]
                key = (target, item["role"])
                replacement = exact_items.get(key)
                if replacement is None:
                    while f"EV{next_number}" in occupied:
                        next_number += 1
                    replacement = f"EV{next_number}"
                    occupied.add(replacement)
                    quote = passages[passage][start:end]
                    result["evidence"].append({**item, "handle": replacement, "quote": quote,
                        "occurrence": _starts(passages[passage], quote).index(start) + 1})
                    exact_items[key] = replacement
                    report["evidence_items_added"] += 1
                group["evidence_handles"] = [replacement]
                replaced.add(old)
                outcomes.add("NARROWED")
        outcome = next((code for code in OUTCOMES if code in outcomes), "REFUSED_NOT_CONTAINED")
        report["by_predicate"][predicate][outcome] += 1

    if replaced:
        unused = replaced.difference(_references(result))
        result["evidence"] = [item for item in result["evidence"]
                              if not isinstance(_object(item).get("handle"), str)
                              or item["handle"] not in unused]
        report["evidence_items_removed"] = len(unused)
    return result, report
