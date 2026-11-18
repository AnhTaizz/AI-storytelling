"""Pure evidence-based mention anchoring and conservative RefersTo pruning.

Only exact, located evidence spans can anchor a mention. Reports contain counts
only; malformed records remain the schema validator's responsibility.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from tools.story_extraction.draft_quote_resolution_v1 import _starts


OUTCOMES = ("ANCHORED_TO_EVIDENCE", "PRUNED_UNLOCATABLE", "LEFT_UNLOCATED", "ALREADY_LOCATED")


def _records(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _references(value):
    """Yield schema reference fields, excluding definitions and literal values.

    This includes nested validity supports, derivations and textual ambiguity.
    Argument handles are distinguished from record definitions by their kind.
    """
    if isinstance(value, dict):
        for key, child in value.items():
            if (key.endswith("_handle") or
                    (key == "handle" and value.get("kind") in
                     ("ENTITY", "EVENT", "ANCHOR", "MENTION", "PROPOSITION"))):
                if isinstance(child, str):
                    yield child
            elif key.endswith("_handles") and isinstance(child, list):
                yield from (handle for handle in child if isinstance(handle, str))
            else:
                yield from _references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _references(child)


def anchor_mentions(draft: Any, prepared_input: dict) -> tuple[Any, dict]:
    """Return a deep copy with only eligible mention repairs/removals applied."""
    result = deepcopy(draft)
    report = {"mentions": dict.fromkeys(OUTCOMES, 0),
              "removed": dict.fromkeys(("propositions", "assertions", "mentions"), 0)}
    if not isinstance(result, dict):
        return result, report
    passages = {p["handle"]: p for p in _records(prepared_input.get("passages"))
                if isinstance(p.get("handle"), str) and isinstance(p.get("text"), str)}

    def starts(item):
        handle, quote = item.get("passage_handle"), item.get("quote")
        passage = passages.get(handle) if isinstance(handle, str) else None
        if (passage is None or passage.get("use") != "EVIDENCE_ELIGIBLE" or
                not isinstance(quote, str) or not quote):
            return []
        return _starts(passage["text"], quote)

    def span(item):
        positions = starts(item)
        occurrence = item.get("occurrence", 1 if len(positions) == 1 else None)
        if type(occurrence) is int and 1 <= occurrence <= len(positions):
            start = positions[occurrence - 1]
            return item["passage_handle"], start, start + len(item["quote"])
        return None

    evidence = {e["handle"]: e for e in _records(result.get("evidence"))
                if isinstance(e.get("handle"), str)}
    for mention in (result.get("mentions") if isinstance(result.get("mentions"), list) else []):
        code = "LEFT_UNLOCATED"
        if isinstance(mention, dict) and span(mention) is not None:
            code = "ALREADY_LOCATED"
        elif (isinstance(mention, dict) and isinstance(mention.get("handle"), str) and
                isinstance(mention.get("quote"), str) and mention["quote"]):
            users = [p for p in _records(result.get("propositions"))
                     if isinstance(p.get("args"), dict) and any(
                         isinstance(arg, dict) and arg.get("handle") == mention["handle"]
                         for arg in p["args"].values())]
            if users and all(p.get("predicate") == "RefersTo" for p in users):
                handles = {p.get("handle") for p in users if isinstance(p.get("handle"), str)}
                assertions = [a for a in _records(result.get("assertions"))
                              if isinstance(a.get("proposition_handle"), str) and
                              a["proposition_handle"] in handles]
                spans = set()
                for assertion in assertions:
                    support = assertion.get("support")
                    for group in _records(support.get("evidence_sets") if isinstance(support, dict) else None):
                        cited = group.get("evidence_handles")
                        for handle in cited if isinstance(cited, list) else []:
                            item = evidence.get(handle) if isinstance(handle, str) else None
                            located = span(item) if item is not None else None
                            if located is not None:
                                spans.add(located)
                matches = [(handle, start, _starts(passages[handle]["text"][start:end], mention["quote"]))
                           for handle, start, end in sorted(spans)]
                matches = [(handle, start, positions) for handle, start, positions in matches if positions]
                if len(matches) == 1 and len(matches[0][2]) == 1:
                    handle, start, positions = matches[0]
                    mention["passage_handle"] = handle
                    mention["occurrence"] = _starts(passages[handle]["text"], mention["quote"]).index(
                        start + positions[0]) + 1
                    code = "ANCHORED_TO_EVIDENCE"
                elif not matches and not starts(mention):
                    removed = users + assertions
                    targets = handles | {a["handle"] for a in assertions if isinstance(a.get("handle"), str)}
                    # Internal references within the proposed deletion are safe.
                    remaining = {key: [item for item in value if not any(item is r for r in removed)]
                                 if isinstance(value, list) else value for key, value in result.items()}
                    if targets.isdisjoint(_references(remaining)):
                        for kind, items in (("propositions", users), ("assertions", assertions)):
                            if items:
                                result[kind] = [item for item in result[kind]
                                                if not any(item is r for r in items)]
                            report["removed"][kind] += len(items)
                        # Filtering below leaves the loop's original list intact.
                        code = "PRUNED_UNLOCATABLE"
                        report["removed"]["mentions"] += 1
        report["mentions"][code] += 1
        if code == "PRUNED_UNLOCATABLE":
            result["mentions"] = [item for item in result["mentions"] if item is not mention]
    return result, report
