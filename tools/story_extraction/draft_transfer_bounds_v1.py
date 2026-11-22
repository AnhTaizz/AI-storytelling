"""Set open possession bounds from matching transfer participants."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any, Mapping

from tools.story_extraction.draft_mention_anchoring_v1 import _records
from tools.story_extraction.draft_mention_evidence_v1 import _by_handle, _located, _object


OUTCOMES = ("START_SET", "END_SET", "BOTH_SET", "ALREADY_BOUND", "NO_TRANSFER",
            "REFUSED_AMBIGUOUS", "REFUSED_ORDER")
_HOLDER_ARGUMENT = {"Possesses": "holder", "Owns": "owner"}


def _argument(args, name, kind, field):
    arg = _object(args.get(name))
    value = arg.get(field)
    return value if arg.get("kind") == kind and isinstance(value, str) else None


def _occurrence_position(assertion, evidence, passages, passage_order):
    positions = []
    for group in _records(_object(assertion.get("support")).get("evidence_sets")):
        handles = group.get("evidence_handles")
        if group.get("label") != "SUFFICIENT" or not isinstance(handles, list):
            continue
        for handle in handles:
            item = evidence.get(handle, {}) if isinstance(handle, str) else {}
            span = _located(item, passages)
            if span is not None:
                passage, start, _ = span
                positions.append((passage_order[passage], start))
    return min(positions, default=None)


def _set_bounds(assertion, candidates, events, positions):
    if not candidates:
        return "NO_TRANSFER"
    if any(len(matches) > 1 for matches in candidates.values()):
        return "REFUSED_AMBIGUOUS"
    validity = _object(assertion.get("validity"))
    if any(_object(validity.get(side)).get("kind") != "OPEN" for side in candidates):
        return "ALREADY_BOUND"

    selected = {side: next(iter(matches)) for side, matches in candidates.items()}
    if len(selected) == 2:
        start, end = positions.get(selected["start"]), positions.get(selected["end"])
        if start is None or end is None or start >= end:
            return "REFUSED_ORDER"
        outcome = "BOTH_SET"
    else:
        outcome = "START_SET" if "start" in selected else "END_SET"
    for side, event in selected.items():
        validity[side] = {"kind": "ANCHOR", "anchor_handle": events[event]["anchor_handle"]}
    return outcome


def bound_by_transfer(draft: Any, prepared_input: Mapping[str, Any]) -> tuple[Any, dict]:
    """Return a deep copy and one counts-only outcome per affirmed possession assertion."""
    result = deepcopy(draft)
    report = {"by_predicate": {p: dict.fromkeys(OUTCOMES, 0) for p in _HOLDER_ARGUMENT}}
    if not isinstance(result, dict):
        return result, report

    passages = {h: p["text"] for h, p in _by_handle(prepared_input.get("passages")).items()
                if p.get("use") == "EVIDENCE_ELIGIBLE" and isinstance(p.get("text"), str)}
    passage_order = {handle: index for index, handle in enumerate(passages)}
    events = {h: e for h, e in _by_handle(result.get("events")).items()
              if e.get("event_kind") == "TRANSFER" and isinstance(e.get("anchor_handle"), str)}
    propositions = _by_handle(result.get("propositions"))
    evidence = _by_handle(result.get("evidence"))
    participants = defaultdict(set)
    positions = {}
    possessions = []
    for assertion in _records(result.get("assertions")):
        handle = assertion.get("proposition_handle")
        if assertion.get("polarity") != "AFFIRMED" or not isinstance(handle, str):
            continue
        proposition = propositions.get(handle, {})
        predicate = proposition.get("predicate")
        args = _object(proposition.get("args"))
        if predicate in ("Possesses", "Owns"):
            possessions.append((assertion, predicate, args))
            continue
        event = _argument(args, "event", "EVENT", "handle")
        if event not in events:
            continue
        if predicate == "Participates":
            participant = _argument(args, "participant", "ENTITY", "handle")
            role = _argument(args, "role", "TOKEN", "value")
            if participant is not None and role in ("THEME", "RECIPIENT", "SOURCE"):
                participants[participant, role].add(event)
        elif predicate == "Occurred":
            position = _occurrence_position(assertion, evidence, passages, passage_order)
            if position is not None and (event not in positions or position < positions[event]):
                positions[event] = position

    for assertion, predicate, args in possessions:
        holder = _argument(args, _HOLDER_ARGUMENT[predicate], "ENTITY", "handle")
        item = _argument(args, "item", "ENTITY", "handle")
        theme_events = participants[item, "THEME"]
        candidates = {"start": theme_events & participants[holder, "RECIPIENT"]}
        if predicate == "Possesses":
            candidates["end"] = theme_events & participants[holder, "SOURCE"]
        outcome = _set_bounds(assertion, {side: matches for side, matches in candidates.items() if matches},
                              events, positions)
        report["by_predicate"][predicate][outcome] += 1
    return result, report
