"""Repair out-of-vocabulary TOKEN arguments in development drafts."""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from typing import Any

from tools.canonical_story.conformance_v0 import load_registry
from tools.story_extraction.draft_mention_anchoring_v1 import _records, _references
from tools.story_extraction.draft_mention_evidence_v1 import _object


OUTCOMES = ("NORMALIZED", "DROPPED", "REFUSED_REFERENCED", "UNKNOWN_VOCABULARY")


def guard_vocabulary(draft: Any, prepared_input=None) -> tuple[Any, dict]:
    """Return a repaired copy and counts, using only the draft and canonical registry.

    Count normalizations and unknown vocabularies per token. Count a drop or
    refusal once per proposition, using registry argument order to break ties.
    Decide removals against the original reference graph, independent of record order.
    """
    result = deepcopy(draft)
    report = {"outcomes": dict.fromkeys(OUTCOMES, 0), "by_vocabulary": {},
              "assertions_dropped": 0, "evidence_items_removed": 0}
    if not isinstance(result, dict):
        return result, report

    def count(vocabulary, outcome):
        report["outcomes"][outcome] += 1
        counts = report["by_vocabulary"].setdefault(vocabulary, dict.fromkeys(OUTCOMES, 0))
        counts[outcome] += 1

    registry = load_registry()
    vocabularies = registry["vocabularies"]
    references = Counter(_references(result))
    claims = defaultdict(list)
    for assertion in _records(result.get("assertions")):
        handle = assertion.get("proposition_handle")
        if isinstance(handle, str):
            claims[handle].append(assertion)

    removed = set()
    for prop in _records(result.get("propositions")):
        handle = prop.get("handle")
        if not isinstance(handle, str):
            continue
        predicate = prop.get("predicate")
        spec = registry["predicates"].get(predicate, {}) if isinstance(predicate, str) else {}
        expected = {a["name"]: a["vocabulary"] for a in spec.get("args", ()) if a["kind"] == "TOKEN"}
        changes = []
        invalid = set()
        for name, arg in _object(prop.get("args")).items():
            if _object(arg).get("kind") != "TOKEN":
                continue
            vocabulary, value = arg.get("vocabulary"), arg.get("value")
            if not isinstance(vocabulary, str) or not isinstance(value, str):
                continue
            if vocabulary not in vocabularies:
                count(vocabulary, "UNKNOWN_VOCABULARY")
                continue
            members = vocabularies[vocabulary]
            if vocabulary != expected.get(name) or value in members:
                continue
            normalized = value.upper()
            if normalized not in members:
                normalized = normalized.replace(" ", "_").replace("-", "_")
            if normalized in members:
                changes.append((arg, normalized))
            else:
                invalid.add(name)

        if invalid:
            vocabulary = next(expected[name] for name in expected if name in invalid)
            group = [prop, *claims[handle]]
            internal = Counter(_references(group))
            handles = (record.get("handle") for record in group)
            if any(references[h] > internal[h] for h in handles if isinstance(h, str)):
                count(vocabulary, "REFUSED_REFERENCED")
            else:
                count(vocabulary, "DROPPED")
                removed.update(map(id, group))
                report["assertions_dropped"] += len(claims[handle])
        else:
            for arg, normalized in changes:
                arg["value"] = normalized
                count(arg["vocabulary"], "NORMALIZED")

    if removed:
        for field in ("propositions", "assertions"):
            if isinstance(result.get(field), list):
                result[field] = [record for record in result[field] if id(record) not in removed]
        orphaned = references.keys() - set(_references(result))
        evidence = result.get("evidence")
        if isinstance(evidence, list):
            result["evidence"] = [item for item in evidence
                                  if not isinstance(handle := _object(item).get("handle"), str)
                                  or handle not in orphaned]
            report["evidence_items_removed"] = len(evidence) - len(result["evidence"])
    return result, report
