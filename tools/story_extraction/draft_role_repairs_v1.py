"""Role host repairs: mention evidence takes its sentence's role (Conventions V5, R-EVR-02), and
PATIENT becomes THEME where the event frame has no PATIENT (Conventions frames 4.2, R-ROLE-02)."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from tools.story_extraction.draft_mention_anchoring_v1 import _records, _references
from tools.story_extraction.draft_mention_evidence_v1 import PREDICATES, _by_handle, _located, _object
from tools.story_extraction.draft_sentence_evidence_v1 import _enclosing, _sentence_spans


MR_OUTCOMES = ("RETAGGED", "ALREADY_CONSISTENT", "NO_SENTENCE_ROLE", "MIXED_SENTENCE_ROLES", "IN_DIALOGUE",
               "NOT_LOCATED")
FR_OUTCOMES = ("PATIENT_TO_THEME", "REFUSED_DUPLICATE")
# Frames (conventions 4.2) that allow THEME but not PATIENT.
THEME_NOT_PATIENT = frozenset({"MOVEMENT", "TRANSFER", "ENCOUNTER", "REVEAL_DISCOVER"})


def _passages(prepared_input: Mapping[str, Any]) -> dict[str, str]:
    return {h: p["text"] for h, p in _by_handle(prepared_input.get("passages")).items()
            if p.get("use") == "EVIDENCE_ELIGIBLE" and isinstance(p.get("text"), str)}


def _sufficient_groups(assertion):
    for group in _records(_object(assertion.get("support")).get("evidence_sets")):
        handles = group.get("evidence_handles")
        if group.get("label") == "SUFFICIENT" and isinstance(handles, list):
            yield group


def retag_mention_roles(draft: Any, prepared_input: Mapping[str, Any]) -> tuple[Any, dict]:
    """Give each RefersTo/NamedAs evidence item outside dialogue the single role of the other
    SUFFICIENT evidence in its sentence. Items are never edited in place; one outcome per citation."""
    result = deepcopy(draft)
    report = {"outcomes": dict.fromkeys(MR_OUTCOMES, 0), "evidence_items_added": 0, "evidence_items_removed": 0}
    if not isinstance(result, dict):
        return result, report
    passages = _passages(prepared_input)
    sentences = {handle: _sentence_spans(text) for handle, text in passages.items()}
    propositions = _by_handle(result.get("propositions"))
    evidence = _by_handle(result.get("evidence"))

    def place(handle):
        item = evidence.get(handle) if isinstance(handle, str) else None
        span = _located(item or {}, passages)
        if span is None:
            return None
        passage, start, end = span
        dialogue, narration = sentences[passage]
        inside = _enclosing(dialogue, start, end)
        bounds = inside or _enclosing(narration, start, start + 1)
        return None if bounds is None else ((passage, *bounds), inside is not None, span)

    sentence_roles, mention_groups = {}, []
    for assertion in _records(result.get("assertions")):
        handle = assertion.get("proposition_handle")
        predicate = _object(propositions.get(handle) if isinstance(handle, str) else None).get("predicate")
        for group in _sufficient_groups(assertion):
            if predicate in PREDICATES:
                mention_groups.append(group)
                continue
            for cited in group["evidence_handles"]:
                where = place(cited)
                if where is not None and isinstance(evidence[cited].get("role"), str):
                    sentence_roles.setdefault(where[0], set()).add(evidence[cited]["role"])

    exact = {}
    for handle, item in evidence.items():
        span = _located(item, passages)
        if span is not None and isinstance(item.get("role"), str):
            exact.setdefault((span, item["role"]), handle)
    occupied = set(_references(result))
    for records in result.values():
        occupied.update(_by_handle(records))
    next_number, replaced = 1, set()
    for group in mention_groups:
        updated = []
        for cited in group["evidence_handles"]:
            replacement, where = cited, place(cited)
            if where is None:
                outcome = "NOT_LOCATED"
            elif where[1]:
                outcome = "IN_DIALOGUE"
            else:
                roles = sentence_roles.get(where[0], set())
                if not roles:
                    outcome = "NO_SENTENCE_ROLE"
                elif len(roles) > 1:
                    outcome = "MIXED_SENTENCE_ROLES"
                elif evidence[cited].get("role") in roles:
                    outcome = "ALREADY_CONSISTENT"
                else:
                    role = next(iter(roles))
                    replacement = exact.get((where[2], role))
                    if replacement is None:
                        while f"EV{next_number}" in occupied:
                            next_number += 1
                        replacement = f"EV{next_number}"
                        occupied.add(replacement)
                        result["evidence"].append({**evidence[cited], "handle": replacement, "role": role})
                        exact[(where[2], role)] = replacement
                        report["evidence_items_added"] += 1
                    replaced.add(cited)
                    outcome = "RETAGGED"
            report["outcomes"][outcome] += 1
            if replacement not in updated:
                updated.append(replacement)
        group["evidence_handles"] = updated
    if replaced:
        unused = replaced.difference(_references(result))
        result["evidence"] = [item for item in result["evidence"]
                              if not isinstance(_object(item).get("handle"), str) or item["handle"] not in unused]
        report["evidence_items_removed"] = len(unused)
    return result, report


def fix_frame_roles(draft: Any, prepared_input: Mapping[str, Any] | None = None) -> tuple[Any, dict]:
    """Turn a Participates PATIENT into THEME on events whose frame allows THEME but not PATIENT."""
    result = deepcopy(draft)
    report = {"outcomes": dict.fromkeys(FR_OUTCOMES, 0)}
    if not isinstance(result, dict):
        return result, report
    kinds = {h: e.get("event_kind") for h, e in _by_handle(result.get("events")).items()}
    participates = [p for p in _records(result.get("propositions")) if p.get("predicate") == "Participates"]

    def key(prop, role):
        args = _object(prop.get("args"))
        return (_object(args.get("event")).get("handle"), _object(args.get("participant")).get("handle"), role)

    existing = {key(p, _object(_object(p.get("args")).get("role")).get("value")) for p in participates}
    for prop in participates:
        args = _object(prop.get("args"))
        role = _object(args.get("role"))
        if role.get("kind") != "TOKEN" or role.get("value") != "PATIENT":
            continue
        if kinds.get(_object(args.get("event")).get("handle")) not in THEME_NOT_PATIENT:
            continue
        if key(prop, "THEME") in existing:
            report["outcomes"]["REFUSED_DUPLICATE"] += 1
            continue
        role["value"] = "THEME"
        existing.add(key(prop, "THEME"))
        report["outcomes"]["PATIENT_TO_THEME"] += 1
    return result, report
