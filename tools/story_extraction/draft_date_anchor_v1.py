"""Move an event's calendar date from a NAMED_TIME anchor to the event's own anchor (Conventions V4, R-TIME-03)."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from tools.story_extraction.draft_mention_anchoring_v1 import _records, _references
from tools.story_extraction.draft_mention_evidence_v1 import _by_handle, _located, _object
from tools.story_extraction.draft_sentence_evidence_v1 import _enclosing, _sentence_spans


OUTCOMES = ("MOVED", "ALREADY_EVENT_ANCHOR", "NOT_LOCATED", "NO_EVENT_IN_SENTENCE",
            "SEVERAL_EVENTS_IN_SENTENCE", "CONFLICTING_DATE")


def _argument_handle(args, name, kind):
    argument = _object(args.get(name))
    handle = argument.get("handle")
    return handle if argument.get("kind") == kind and isinstance(handle, str) else None


def _sentences(assertion, evidence, passages, sentences):
    """Sentences (passage, start, end) of the located SUFFICIENT evidence of an assertion, in citation order."""
    found = []
    for group in _records(_object(assertion.get("support")).get("evidence_sets")):
        handles = group.get("evidence_handles")
        if group.get("label") != "SUFFICIENT" or not isinstance(handles, list):
            continue
        for handle in handles:
            span = _located(evidence.get(handle, {}) if isinstance(handle, str) else {}, passages)
            if span is None:
                continue
            passage, start, end = span
            dialogue, narration = sentences[passage]
            bounds = _enclosing(dialogue, start, end) or _enclosing(narration, start, start + 1)
            if bounds is not None and (passage, *bounds) not in found:
                found.append((passage, *bounds))
    return found


def _redirect(value, old, new):
    """Point every ANCHOR argument and anchored bound at `new` instead of `old`, in place."""
    if isinstance(value, dict):
        if value.get("kind") == "ANCHOR":
            for key in ("handle", "anchor_handle"):
                if value.get(key) == old:
                    value[key] = new
        for child in value.values():
            _redirect(child, old, new)
    elif isinstance(value, list):
        for child in value:
            _redirect(child, old, new)


def anchor_dates_to_events(draft: Any, prepared_input: Mapping[str, Any]) -> tuple[Any, dict]:
    """Return a deep copy and one counts-only outcome per affirmed AnchorDate assertion.

    A date on a NAMED_TIME anchor moves to the EVENT_TIME anchor of the only event whose
    Occurred evidence lies in the same sentence as the date's evidence. Other references to
    the named anchor follow it; a TemporalRelation between the two anchors becomes degenerate
    and is dropped; a moved date equal to one already on the event anchor is dropped as a
    duplicate; the named anchor is removed once nothing references it.
    """
    result = deepcopy(draft)
    report = {"outcomes": dict.fromkeys(OUTCOMES, 0), "relations_dropped": 0, "anchors_removed": 0,
              "duplicates_dropped": 0}
    if not isinstance(result, dict):
        return result, report

    passages = {h: p["text"] for h, p in _by_handle(prepared_input.get("passages")).items()
                if p.get("use") == "EVIDENCE_ELIGIBLE" and isinstance(p.get("text"), str)}
    sentences = {handle: _sentence_spans(text) for handle, text in passages.items()}
    anchors = _by_handle(result.get("anchors"))
    events = _by_handle(result.get("events"))
    evidence = _by_handle(result.get("evidence"))
    propositions = _by_handle(result.get("propositions"))

    def proposition(assertion):
        handle = assertion.get("proposition_handle")
        return propositions.get(handle, {}) if isinstance(handle, str) else {}

    affirmed = [a for a in _records(result.get("assertions")) if a.get("polarity") == "AFFIRMED"]
    event_sentences = {}
    for assertion in affirmed:
        prop = proposition(assertion)
        event = _argument_handle(_object(prop.get("args")), "event", "EVENT")
        if prop.get("predicate") == "Occurred" and event in events:
            event_sentences.setdefault(event, []).extend(_sentences(assertion, evidence, passages, sentences))

    def dates_on(anchor):
        return {_object(_object(proposition(a).get("args")).get("date")).get("value")
                for a in affirmed if proposition(a).get("predicate") == "AnchorDate"
                and _argument_handle(_object(proposition(a).get("args")), "anchor", "ANCHOR") == anchor}

    dropped_assertions, moved_from = set(), set()
    for assertion in affirmed:
        prop = proposition(assertion)
        if prop.get("predicate") != "AnchorDate":
            continue
        args = _object(prop.get("args"))
        named = _argument_handle(args, "anchor", "ANCHOR")
        if _object(anchors.get(named)).get("anchor_kind") != "NAMED_TIME":
            report["outcomes"]["ALREADY_EVENT_ANCHOR" if named in anchors else "NOT_LOCATED"] += 1
            continue
        located = _sentences(assertion, evidence, passages, sentences)
        if not located:
            report["outcomes"]["NOT_LOCATED"] += 1
            continue
        in_sentence = sorted(e for e, found in event_sentences.items() if located[0] in found)
        if len(in_sentence) != 1:
            report["outcomes"]["SEVERAL_EVENTS_IN_SENTENCE" if in_sentence else "NO_EVENT_IN_SENTENCE"] += 1
            continue
        target = events[in_sentence[0]].get("anchor_handle")
        if _object(anchors.get(target)).get("anchor_kind") != "EVENT_TIME":
            report["outcomes"]["NOT_LOCATED"] += 1
            continue
        date = _object(args.get("date")).get("value")
        existing = dates_on(target)
        if existing - {date}:
            report["outcomes"]["CONFLICTING_DATE"] += 1
            continue
        if date in existing:
            dropped_assertions.add(assertion["handle"])
            report["duplicates_dropped"] += 1
        _redirect(result, named, target)
        moved_from.add(named)
        report["outcomes"]["MOVED"] += 1

    if not moved_from and not dropped_assertions:
        return result, report

    for assertion in affirmed:
        prop = proposition(assertion)
        if prop.get("predicate") == "TemporalRelation":
            args = _object(prop.get("args"))
            subject = _argument_handle(args, "subject", "ANCHOR")
            if subject is not None and subject == _argument_handle(args, "object", "ANCHOR"):
                dropped_assertions.add(assertion["handle"])
                report["relations_dropped"] += 1
    orphaned = {a.get("proposition_handle") for a in affirmed if a["handle"] in dropped_assertions}
    result["assertions"] = [a for a in result["assertions"]
                            if not (isinstance(a, dict) and a.get("handle") in dropped_assertions)]
    orphaned -= set(_references(result))
    result["propositions"] = [p for p in result.get("propositions", [])
                              if not (isinstance(p, dict) and p.get("handle") in orphaned)]
    referenced = set(_references(result))
    unused = moved_from - referenced
    result["anchors"] = [a for a in result.get("anchors", [])
                         if not (isinstance(a, dict) and a.get("handle") in unused)]
    report["anchors_removed"] = len(unused)
    return result, report
