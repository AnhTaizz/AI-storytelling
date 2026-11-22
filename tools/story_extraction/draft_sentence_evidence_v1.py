"""Widen sufficient assertion evidence to a single enclosing sentence."""
from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
import re
from typing import Any, Mapping, Sequence

from tools.story_extraction.draft_mention_anchoring_v1 import _records, _references
from tools.story_extraction.draft_mention_evidence_v1 import PREDICATES, _by_handle, _located, _object
from tools.story_extraction.draft_quote_resolution_v1 import _starts


OUTCOMES = ("WIDENED", "ALREADY_SENTENCE", "REFUSED_NOT_LOCATED", "REFUSED_MULTI_SENTENCE")
_TERMINATOR = re.compile(r"[。！？!?]")


def _sentence_spans(text):
    """Index balanced outer dialogue regions and narration on each line."""
    dialogues, narration = [], []
    for line in re.finditer(r"[^\r\n]+", text):
        quotes = []
        depth = 0
        for match in re.finditer(r"[「」]", line[0]):
            if match[0] == "「":
                if depth == 0:
                    opening = line.start() + match.start()
                depth += 1
            elif depth:
                depth -= 1
                if depth == 0:
                    quotes.append((opening, line.start() + match.end()))
        dialogues.extend(quotes)

        start = cursor = line.start()
        for opening, closing in (*quotes, (line.end(), line.end())):
            for match in _TERMINATOR.finditer(text, cursor, opening):
                narration.append((start, match.end()))
                start = match.end()
            cursor = closing
        if start < line.end():
            narration.append((start, line.end()))
    return dialogues, narration


def _enclosing(spans, start, end):
    index = bisect_right(spans, start, key=lambda span: span[0]) - 1
    if index >= 0 and end <= spans[index][1]:
        return spans[index]
    return None


def _sentence(span, passages, sentences):
    if span is None:
        return None, "REFUSED_NOT_LOCATED"
    passage, start, end = span
    dialogue, narration = sentences[passage]
    bounds = _enclosing(dialogue, start, end) or _enclosing(narration, start, end)
    if bounds is None:
        return None, "REFUSED_MULTI_SENTENCE"
    left, right = bounds
    quote = passages[passage][left:right].lstrip()
    if not quote:
        return None, "REFUSED_NOT_LOCATED"
    target = (passage, right - len(quote), right)
    return target, "ALREADY_SENTENCE" if target == span else "WIDENED"


def widen_to_sentence(draft: Any, prepared_input: Mapping[str, Any], *,
                      excluded_predicates: Sequence[str] = PREDICATES) -> tuple[Any, dict]:
    """Return a deep copy and one counts-only outcome per selected assertion."""
    result = deepcopy(draft)
    report = {"by_predicate": {}, "evidence_items_added": 0, "evidence_items_removed": 0}
    if not isinstance(result, dict):
        return result, report

    passages = {h: p["text"] for h, p in _by_handle(prepared_input.get("passages")).items()
                if p.get("use") == "EVIDENCE_ELIGIBLE" and isinstance(p.get("text"), str)}
    sentences = {handle: _sentence_spans(text) for handle, text in passages.items()}
    propositions = _by_handle(result.get("propositions"))
    evidence = _by_handle(result.get("evidence"))
    located, exact_items = {}, {}
    for handle, item in evidence.items():
        span, role = _located(item, passages), item.get("role")
        if span is not None and isinstance(role, str):
            located[handle] = span
            exact_items.setdefault((span, role), handle)

    occupied = set(_references(result))
    for records in result.values():
        occupied.update(_by_handle(records))
    next_number = 1
    replaced = set()
    for assertion in _records(result.get("assertions")):
        handle = assertion.get("proposition_handle")
        proposition = propositions.get(handle, {}) if isinstance(handle, str) else {}
        predicate = proposition.get("predicate")
        if not isinstance(predicate, str) or predicate in excluded_predicates:
            continue
        outcomes = set()
        for group in _records(_object(assertion.get("support")).get("evidence_sets")):
            if group.get("label") != "SUFFICIENT":
                continue
            cited = group.get("evidence_handles")
            if not isinstance(cited, list) or not cited:
                outcomes.add("REFUSED_NOT_LOCATED")
                continue
            updated = []
            for old in cited:
                replacement = old
                span = located.get(old) if isinstance(old, str) else None
                target, outcome = _sentence(span, passages, sentences)
                outcomes.add(outcome)
                if target is not None:
                    passage, left, right = target
                    item = evidence[old]
                    key = (target, item["role"])
                    replacement = exact_items.get(key)
                    if replacement is None:
                        while f"EV{next_number}" in occupied:
                            next_number += 1
                        replacement = f"EV{next_number}"
                        occupied.add(replacement)
                        text = passages[passage]
                        quote = text[left:right]
                        result["evidence"].append({**item, "handle": replacement, "quote": quote,
                            "occurrence": _starts(text, quote).index(left) + 1})
                        exact_items[key] = replacement
                        report["evidence_items_added"] += 1
                    if replacement != old:
                        replaced.add(old)
                if replacement not in updated:
                    updated.append(replacement)
            group["evidence_handles"] = updated
        outcome = next((code for code in OUTCOMES if code in outcomes), "REFUSED_NOT_LOCATED")
        report["by_predicate"].setdefault(predicate, dict.fromkeys(OUTCOMES, 0))[outcome] += 1

    if replaced:
        unused = replaced.difference(_references(result))
        result["evidence"] = [item for item in result["evidence"]
                              if not isinstance(_object(item).get("handle"), str)
                              or item["handle"] not in unused]
        report["evidence_items_removed"] = len(unused)
    report["by_predicate"] = dict(sorted(report["by_predicate"].items()))
    return result, report
