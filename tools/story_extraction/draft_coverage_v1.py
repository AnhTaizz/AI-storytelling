"""OFFLINE ONLY: project authored canonical gold to a draft for coverage testing.

This is an oracle projection, never a model prediction or fresh validation.
It is not imported by the compiler and has no provider integration.
"""
from copy import deepcopy
from typing import Any

from tools.story_extraction.draft_compiler_v1 import (
    COLLECTIONS, DRAFT_VERSION, DraftCompilationError, _context_maps, _occurrences,
)

PREFIXES = {"evidence": "EV", "mentions": "M", "entities": "E_NEW_",
            "events": "EVT", "anchors": "T", "propositions": "PROP", "assertions": "A"}
RENAMES = {"ref": "handle", "anchor_id": "anchor_handle", "event_id": "event_handle",
           "proposition_id": "proposition_handle", "evidence_ref_ids": "evidence_handles",
           "premise_assertion_ids": "premise_handles",
           "alternative_proposition_ids": "alternative_proposition_handles"}


def canonical_gold_to_draft_v1(gold, context):
    """Return (draft-like oracle, original-id -> handle mapping)."""
    passages, existing = _context_maps(context)
    mapping = {rid: h for h, (_, rid) in existing.items()}
    records = gold["candidate_records"]
    ordered = {field: sorted(records[coll], key=lambda r: r["id"])
               for field, coll in COLLECTIONS.items()}
    for field, rows in ordered.items():
        for i, r in enumerate(rows, 1):
            mapping[r["id"]] = f"{PREFIXES[field]}{i}"

    reference_keys = set(RENAMES)

    def transform(value, key=""):
        if isinstance(value, list):
            return [transform(v, key) for v in value]
        if not isinstance(value, dict):
            return mapping.get(value, value) if key in reference_keys and isinstance(value, str) else value
        return {RENAMES.get(k, k): transform(v, k) for k, v in value.items()
                if k not in {"id", "extraction_provenance_id", "review"}}

    def quote_selector(ev):
        span = ev["span"]
        for h, (item, text) in passages.items():
            ref = item["passage_ref"]
            outer = ref["span"]
            if (item["use"] == "EVIDENCE_ELIGIBLE" and ev["segment_id"] == ref["segment_id"]
                    and outer["char_start"] <= span["char_start"]
                    and span["char_end_exclusive"] <= outer["char_end_exclusive"]):
                start = span["char_start"] - outer["char_start"]
                quote = text[start:span["char_end_exclusive"] - outer["char_start"]]
                starts = _occurrences(text, quote)
                if not quote or start not in starts:
                    raise DraftCompilationError("GOLD_QUOTE_NOT_EXACT")
                return {"passage_handle": h, "quote": quote,
                        "occurrence": starts.index(start) + 1, "role": ev["role"]}
        raise DraftCompilationError("GOLD_EVIDENCE_OUTSIDE_SCOPE")

    draft = {"draft_version": DRAFT_VERSION, **{field: [] for field in COLLECTIONS}}
    evidence = {r["id"]: r for r in records["evidence_refs"]}
    for field, rows in ordered.items():
        for r in rows:
            out = {"handle": mapping[r["id"]]}
            if field == "evidence":
                out.update(quote_selector(r))
            elif field == "mentions":
                out.update(quote_selector(evidence[r["evidence_ref_id"]]))
                out["evidence_handle"] = mapping[r["evidence_ref_id"]]
                out["surface_form"] = r["surface_form"]
            else:
                out.update(transform(r))
            draft[field].append(out)
    return draft, mapping


def canonical_representation_signature(batch: dict[str, Any], id_to_handle: dict[str, str]):
    """Independent graph comparison, modulo only machine-owned record/support IDs.

    Semantic strings (including literals that happen to resemble an ID) are
    never rewritten. Review/provenance/process are explicitly out of scope.
    Exact evidence offsets/hashes/positions remain part of this comparison.
    """
    reference_keys = {"id", "ref", "anchor_id", "event_id", "proposition_id", "evidence_ref_id"}
    reference_arrays = {"evidence_ref_ids", "premise_assertion_ids", "alternative_proposition_ids"}

    def normalize(value, key=""):
        if isinstance(value, list):
            return [normalize(v, key) for v in value]
        if not isinstance(value, dict):
            if key in reference_keys | reference_arrays and isinstance(value, str):
                return id_to_handle.get(value, value)
            return value
        return {k: normalize(v, k) for k, v in value.items()
                if k not in {"extraction_provenance_id", "review"}
                and not (k == "id" and v not in id_to_handle)}

    return {coll: sorted([normalize(r) for r in batch["candidate_records"][coll]],
                        key=lambda r: r["id"])
            for coll in COLLECTIONS.values()}
