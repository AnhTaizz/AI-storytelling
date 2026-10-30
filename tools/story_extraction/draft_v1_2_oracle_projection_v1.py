"""Offline oracle projection: canonical gold batch -> STORY_EXTRACTION_DRAFT_V1_2.

For synthetic or explicitly authorized development fixtures only; it never opens a
sealed package. Every gold span keeps its exact location: the projection derives the
shortest exact context that makes the span unique within its passage. A span with no
unique context of at most 32 code points, or a mention whose surface form is not its
source text, is UNREPRESENTABLE. It is declared in ``unresolved_locators`` and every
record that depends on it is pruned. Both are reported and counted; nothing is hidden.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from tools.story_extraction.contextual_anchor_resolver_v1 import (
    candidate_starts,
    minimal_unique_context,
)
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext, _context_maps
from tools.story_extraction.draft_compiler_v1_2 import DRAFT_VERSION
from tools.story_extraction.draft_coverage_v1 import canonical_gold_to_draft_v1


PROJECTION_VERSION = "DRAFT_V1_2_ORACLE_PROJECTION_V1"


def _references(value: Any) -> set[str]:
    """Every handle string referenced anywhere inside a record (not its own handle)."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "handle" and isinstance(item, str) and value.get("kind") is not None:
                found.add(item)
            elif key in {"proposition_handle", "anchor_handle", "event_handle"}:
                found.add(item)
            elif key in {"evidence_handles", "premise_handles", "alternative_proposition_handles"}:
                found.update(item)
            else:
                found |= _references(item)
    elif isinstance(value, list):
        for item in value:
            found |= _references(item)
    return found


def project_gold_to_draft_v1_2(gold: dict[str, Any], context: DraftCompilerContext
                               ) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    v1, mapping = canonical_gold_to_draft_v1(gold, context)
    passages, _ = _context_maps(context)
    draft: dict[str, Any] = {"draft_version": DRAFT_VERSION}
    for field in ("entities", "events", "anchors", "propositions", "assertions"):
        draft[field] = deepcopy(v1[field])
    draft["evidence"], draft["mentions"], draft["unresolved_locators"] = [], [], []
    unrepresentable: list[dict[str, str]] = []
    total = 0
    for field in ("evidence", "mentions"):
        for record in v1[field]:
            total += 1
            text = passages[record["passage_handle"]][1]
            starts = candidate_starts(text, record["quote"])
            start = starts[record.get("occurrence", 1) - 1]
            end = start + len(record["quote"])
            reason = None
            if field == "mentions" and record.get("surface_form", record["quote"]) != record["quote"]:
                reason = "SURFACE_FORM_NOT_SOURCE_TEXT"
            context_pair = None if reason else minimal_unique_context(text, start, end)
            if reason is None and context_pair is None:
                reason = "NO_UNIQUE_CONTEXT_WITHIN_LIMIT"
            if reason:
                unrepresentable.append({"handle": record["handle"], "reason": reason})
                draft["unresolved_locators"].append({
                    "handle": record["handle"], "passage_handle": record["passage_handle"],
                    "quote": record["quote"],
                    "reason": ("REPEATED_IDENTICAL_CONTEXT"
                               if reason == "NO_UNIQUE_CONTEXT_WITHIN_LIMIT" else "OTHER_DECLARED"),
                })
                continue
            out = {"handle": record["handle"], "passage_handle": record["passage_handle"],
                   "quote": record["quote"], "role": record["role"]}
            before, after = context_pair
            if before is not None:
                out["context_before"] = before
            if after is not None:
                out["context_after"] = after
            draft[field].append(out)

    removed = {item["handle"] for item in unrepresentable}
    pruned: list[str] = []
    changed = True
    while changed:
        changed = False
        for field in ("mentions", "evidence", "entities", "events", "anchors",
                      "propositions", "assertions"):
            keep = []
            for record in draft[field]:
                own = {key: value for key, value in record.items() if key != "handle"}
                if _references(own) & removed:
                    removed.add(record["handle"])
                    pruned.append(record["handle"])
                    changed = True
                else:
                    keep.append(record)
            draft[field] = keep
    representable = total - len(unrepresentable)
    report = {
        "projection": PROJECTION_VERSION,
        "locators_total": total,
        "representable": representable,
        "unrepresentable": sorted(unrepresentable, key=lambda item: item["handle"]),
        "pruned_dependants": sorted(pruned),
        "representability_coverage": None if total == 0 else representable / total,
    }
    return draft, mapping, report
