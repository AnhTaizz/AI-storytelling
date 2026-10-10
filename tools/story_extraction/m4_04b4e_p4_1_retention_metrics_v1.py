"""Structural retention metrics for a primary response and its repair (M4-04B4E). Offline only.

An empty Draft V1.1 compiles. A repair can therefore become structurally valid by
deleting records instead of correcting them, and structural validity alone cannot see
that. These metrics describe, without gold, what a repair kept, removed, added and
changed, and whether a blocker went away because its record was corrected or because
its record is gone.

What the metrics are not. A handle that is kept is a structural identity signal, not
proof that the meaning was kept. Unchanged counts do not mean unchanged content. A
removal is not evidence that the removed content was correct or supported. Every
warning here is a research warning to look at, never a verdict on a prediction. There
is no threshold and no score, and nothing here edits a draft.

Pure functions over parsed JSON. No model, provider, dataset or file is touched.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Optional


METRICS_ID = "M4_P4_1_STRUCTURAL_RETENTION_METRICS_V1"
METRICS_PATH = "tools/story_extraction/m4_04b4e_p4_1_retention_metrics_v1.py"
COLLECTIONS = ("evidence", "mentions", "entities", "events", "anchors", "propositions", "assertions")

PROFILE_FIELDS = (
    "parsed", "is_draft_object", "record_counts", "total_records", "empty_output", "empty_collections",
    "collections_not_arrays", "records_without_a_usable_handle", "duplicated_handles",
)
COLLECTION_COMPARISON_FIELDS = (
    "comparable", "primary_count", "repair_count", "count_difference", "retained_handles", "removed_handles",
    "added_handles", "unchanged_records", "changed_in_place_records",
)
COMPARISON_FIELDS = (
    "metrics", "comparable", "identical_bytes", "identical_parsed_content", "by_collection", "totals",
    "record_count_decreased", "counts_unchanged_but_content_changed", "repair_is_empty_output",
    "primary_is_empty_output",
)
TOTAL_FIELDS = (
    "primary_records", "repair_records", "count_difference", "retained", "removed", "added", "unchanged",
    "changed_in_place",
)
REMOVAL_CLASSES = (
    "NAMED_BY_A_PRIMARY_FINDING",        # the removed record is one a primary finding named
    "DEPENDS_ON_A_NAMED_RECORD",         # it referenced, directly or through other records, a named record
    "NOT_EXPLAINED_BY_ANY_FINDING",      # no primary finding named it and it depended on no named record
)
EFFECT_FIELDS = (
    "metrics", "repair_attempted", "identical_bytes", "primary_structurally_valid", "repair_structurally_valid",
    "structural_validity_increased", "primary_findings", "primary_findings_cleared",
    "primary_findings_remaining", "new_findings", "all_primary_findings_cleared", "new_findings_appeared",
    "located_primary_findings", "cleared_with_the_record_kept", "cleared_with_the_record_removed",
    "removed_records_by_explanation", "changed_records_not_named_by_a_finding",
    "structural_validity_increased_while_record_count_decreased", "warnings",
)
WARNING_EMPTY_OUTPUT = "EMPTY_OUTPUT"
WARNING_REPAIR_EMPTY = "REPAIR_IS_EMPTY_OUTPUT"
WARNING_IDENTICAL = "REPAIR_IDENTICAL_TO_PRIMARY"
WARNING_VALID_WITH_FEWER_RECORDS = "STRUCTURAL_VALIDITY_INCREASED_WHILE_RECORD_COUNT_DECREASED"
WARNING_UNEXPLAINED_REMOVAL = "RECORDS_REMOVED_THAT_NO_FINDING_EXPLAINS"
WARNING_CLEARED_BY_REMOVAL = "A_FINDING_WAS_CLEARED_BY_REMOVING_ITS_RECORD"
WARNING_UNEXPLAINED_CHANGE = "RECORDS_CHANGED_THAT_NO_FINDING_NAMED"
WARNING_CONTENT_CHANGED_COUNTS_SAME = "COUNTS_UNCHANGED_BUT_CONTENT_CHANGED"
WARNING_NOT_COMPARABLE = "PRIMARY_AND_REPAIR_ARE_NOT_COMPARABLE_BY_HANDLE"
WARNINGS = (
    WARNING_EMPTY_OUTPUT, WARNING_REPAIR_EMPTY, WARNING_IDENTICAL, WARNING_VALID_WITH_FEWER_RECORDS,
    WARNING_UNEXPLAINED_REMOVAL, WARNING_CLEARED_BY_REMOVAL, WARNING_UNEXPLAINED_CHANGE,
    WARNING_CONTENT_CHANGED_COUNTS_SAME, WARNING_NOT_COMPARABLE,
)
INTERPRETATION = "RESEARCH_WARNING_METRICS_NOT_EVIDENCE_OF_SEMANTIC_ERROR_NO_THRESHOLD"


def parse_response(raw: Any) -> tuple[bool, Any]:
    """(parsed, value). A response that is not one JSON value is not parsed."""
    try:
        return True, json.loads(raw)
    except (TypeError, ValueError):
        return False, None


def _records(draft: Any, collection: str) -> Optional[list]:
    value = draft.get(collection) if isinstance(draft, dict) else None
    return value if isinstance(value, list) else None


def _handle(record: Any) -> Optional[str]:
    handle = record.get("handle") if isinstance(record, dict) else None
    return handle if isinstance(handle, str) and handle else None


def _by_handle(draft: Any, collection: str) -> tuple[dict[str, Any], int, int]:
    """Records of a collection keyed by handle, with the count of unusable and of duplicated handles."""
    records = _records(draft, collection) or []
    seen: dict[str, int] = {}
    for record in records:
        handle = _handle(record)
        if handle is not None:
            seen[handle] = seen.get(handle, 0) + 1
    unique = {_handle(record): record for record in records if _handle(record) is not None and seen[_handle(record)] == 1}
    return unique, sum(_handle(record) is None for record in records), sum(count > 1 for count in seen.values())


def draft_profile(parsed: bool, draft: Any) -> dict[str, Any]:
    """Counts of one response by collection, and whether it is an empty output."""
    is_object = parsed and isinstance(draft, dict)
    counts: dict[str, Optional[int]] = {}
    not_arrays, without_handle, duplicated = [], 0, 0
    for collection in COLLECTIONS:
        records = _records(draft, collection)
        counts[collection] = None if records is None else len(records)
        if records is None:
            not_arrays.append(collection)
        _, missing, repeated = _by_handle(draft, collection)
        without_handle += missing
        duplicated += repeated
    known = [count for count in counts.values() if count is not None]
    return {
        "parsed": bool(parsed),
        "is_draft_object": bool(is_object),
        "record_counts": counts,
        "total_records": sum(known),
        # Empty output: a draft object whose seven collections are all present and all empty.
        "empty_output": bool(is_object and not not_arrays and sum(known) == 0),
        "empty_collections": [collection for collection in COLLECTIONS if counts[collection] == 0],
        "collections_not_arrays": not_arrays,
        "records_without_a_usable_handle": without_handle,
        "duplicated_handles": duplicated,
    }


def _same(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, ensure_ascii=True) == json.dumps(right, sort_keys=True, ensure_ascii=True)


def compare_drafts(primary_raw: Any, repair_raw: Any) -> dict[str, Any]:
    """What the repair kept, removed, added and changed, by collection. Records are matched by handle.

    A collection is comparable only when both sides hold an array whose records all have
    a handle used once. Otherwise handle lists are empty and the collection is marked not
    comparable; counts are still reported.
    """
    primary_parsed, primary = parse_response(primary_raw)
    repair_parsed, repair = parse_response(repair_raw)
    primary_profile, repair_profile = draft_profile(primary_parsed, primary), draft_profile(repair_parsed, repair)
    by_collection: dict[str, dict[str, Any]] = {}
    for collection in COLLECTIONS:
        left, left_missing, left_repeated = _by_handle(primary, collection)
        right, right_missing, right_repeated = _by_handle(repair, collection)
        comparable = (
            _records(primary, collection) is not None and _records(repair, collection) is not None
            and not (left_missing or left_repeated or right_missing or right_repeated)
        )
        primary_count = primary_profile["record_counts"][collection]
        repair_count = repair_profile["record_counts"][collection]
        retained = sorted(set(left) & set(right)) if comparable else []
        by_collection[collection] = {
            "comparable": comparable,
            "primary_count": primary_count,
            "repair_count": repair_count,
            "count_difference": None if primary_count is None or repair_count is None else repair_count - primary_count,
            "retained_handles": retained,
            "removed_handles": sorted(set(left) - set(right)) if comparable else [],
            "added_handles": sorted(set(right) - set(left)) if comparable else [],
            "unchanged_records": [handle for handle in retained if _same(left[handle], right[handle])],
            "changed_in_place_records": [handle for handle in retained if not _same(left[handle], right[handle])],
        }
    totals = {
        "primary_records": primary_profile["total_records"],
        "repair_records": repair_profile["total_records"],
        "count_difference": repair_profile["total_records"] - primary_profile["total_records"],
        "retained": sum(len(item["retained_handles"]) for item in by_collection.values()),
        "removed": sum(len(item["removed_handles"]) for item in by_collection.values()),
        "added": sum(len(item["added_handles"]) for item in by_collection.values()),
        "unchanged": sum(len(item["unchanged_records"]) for item in by_collection.values()),
        "changed_in_place": sum(len(item["changed_in_place_records"]) for item in by_collection.values()),
    }
    comparable = primary_profile["is_draft_object"] and repair_profile["is_draft_object"] and all(
        item["comparable"] for item in by_collection.values())
    counts_equal = all(item["count_difference"] == 0 for item in by_collection.values())
    identical_content = bool(primary_parsed and repair_parsed and _same(primary, repair))
    return {
        "metrics": METRICS_ID,
        "comparable": bool(comparable),
        "identical_bytes": isinstance(primary_raw, str) and primary_raw == repair_raw,
        "identical_parsed_content": identical_content,
        "by_collection": by_collection,
        "totals": totals,
        "record_count_decreased": totals["count_difference"] < 0,
        "counts_unchanged_but_content_changed": bool(
            primary_parsed and repair_parsed and counts_equal and not identical_content),
        "repair_is_empty_output": repair_profile["empty_output"],
        "primary_is_empty_output": primary_profile["empty_output"],
    }


def _references(record: Any) -> set[str]:
    """Handles a record points at: values of *_handle and *_handles fields, and argument handles."""
    found: set[str] = set()

    def walk(node: Any, key: Optional[str], depth: int) -> None:
        if isinstance(node, dict):
            for name, value in node.items():
                walk(value, name, depth + 1)
        elif isinstance(node, list):
            for value in node:
                walk(value, key, depth)
        elif isinstance(node, str) and key is not None and key != "passage_handle":
            if key.endswith("_handle") or key.endswith("_handles") or (key == "handle" and depth > 1):
                found.add(node)

    walk(record, None, 0)
    return found


def classify_removals(primary_raw: Any, comparison: Mapping[str, Any], named_handles: set[str]) -> dict[str, list[str]]:
    """Why each removed record may have gone: named by a finding, dependent on a named record, or neither."""
    _, primary = parse_response(primary_raw)
    records = {}
    for collection in COLLECTIONS:
        records.update(_by_handle(primary, collection)[0])
    removed = {handle for item in comparison["by_collection"].values() for handle in item["removed_handles"]}
    named = removed & set(named_handles)
    dependent: set[str] = set()
    frontier = set(named)
    while frontier:
        reached = {handle for handle in removed - named - dependent if _references(records.get(handle)) & frontier}
        dependent |= reached
        frontier = reached
    return {
        REMOVAL_CLASSES[0]: sorted(named),
        REMOVAL_CLASSES[1]: sorted(dependent),
        REMOVAL_CLASSES[2]: sorted(removed - named - dependent),
    }


def finding_signatures(diagnostic: Optional[Mapping[str, Any]]) -> list[tuple]:
    """One signature per finding of a structural diagnostic V3.1: code, collection and verified handle.

    A record index is left out because indices shift when records are removed. A finding
    with no verified handle is identified by its code, collection and path.
    """
    if not diagnostic:
        return []
    signatures = []
    for finding in diagnostic["findings"]:
        handle = finding["record_handle"]
        signatures.append((finding["code"], finding["record_collection"], handle,
                           None if handle is not None else finding["schema_path"]))
    return signatures


def named_handles(diagnostic: Optional[Mapping[str, Any]], primary_raw: Any) -> set[str]:
    """Handles of the primary response that a finding points at.

    The verified record of a finding, a record its detail references, and the record a
    schema finding positions by index. A record no finding points at is not named.
    """
    if not diagnostic:
        return set()
    _, primary = parse_response(primary_raw)
    named: set[str] = set()
    for finding in diagnostic["findings"]:
        if finding["record_handle"] is not None:
            named.add(finding["record_handle"])
        for key in ("referenced_record_handle", "identical_to_record_handle"):
            if isinstance(finding["structural_detail"].get(key), str):
                named.add(finding["structural_detail"][key])
        if finding["record_locator"] == "SCHEMA_PATH_INDEX":
            parts = (finding["schema_path"] or "").split("/")
            records = _records(primary, parts[0])
            if records is not None and len(parts) > 1 and parts[1].isdigit() and int(parts[1]) < len(records):
                handle = _handle(records[int(parts[1])])
                if handle is not None:
                    named.add(handle)
    return named


def repair_effect(primary_raw: Any, repair_raw: Any, primary_diagnostic: Optional[Mapping[str, Any]],
                  repair_diagnostic: Optional[Mapping[str, Any]], *, primary_valid: bool,
                  repair_valid: bool) -> dict[str, Any]:
    """What one repair did to the structural findings and to the records. Warnings, never verdicts."""
    comparison = compare_drafts(primary_raw, repair_raw)
    before, after = finding_signatures(primary_diagnostic), finding_signatures(repair_diagnostic)
    remaining_pool = list(after)
    cleared, remaining = [], []
    for signature in before:
        if signature in remaining_pool:
            remaining_pool.remove(signature)
            remaining.append(signature)
        else:
            cleared.append(signature)
    removed = {handle for item in comparison["by_collection"].values() for handle in item["removed_handles"]}
    located = [signature for signature in before if signature[2] is not None]
    cleared_located = [signature for signature in cleared if signature[2] is not None]
    named = named_handles(primary_diagnostic, primary_raw)
    removals = classify_removals(primary_raw, comparison, named)
    changed = {handle for item in comparison["by_collection"].values() for handle in item["changed_in_place_records"]}
    validity_increased = bool(repair_valid and not primary_valid)
    effect = {
        "metrics": METRICS_ID,
        "repair_attempted": True,
        "identical_bytes": comparison["identical_bytes"],
        "primary_structurally_valid": bool(primary_valid),
        "repair_structurally_valid": bool(repair_valid),
        "structural_validity_increased": validity_increased,
        "primary_findings": len(before),
        "primary_findings_cleared": len(cleared),
        "primary_findings_remaining": len(remaining),
        "new_findings": len(remaining_pool),
        "all_primary_findings_cleared": bool(before) and not remaining,
        "new_findings_appeared": bool(remaining_pool),
        "located_primary_findings": len(located),
        "cleared_with_the_record_kept": sum(signature[2] not in removed for signature in cleared_located),
        "cleared_with_the_record_removed": sum(signature[2] in removed for signature in cleared_located),
        "removed_records_by_explanation": {name: len(handles) for name, handles in removals.items()},
        "changed_records_not_named_by_a_finding": len(changed - named),
        "structural_validity_increased_while_record_count_decreased": bool(
            validity_increased and comparison["record_count_decreased"]),
        "warnings": [],
    }
    warnings = {
        WARNING_REPAIR_EMPTY: comparison["repair_is_empty_output"],
        WARNING_IDENTICAL: comparison["identical_bytes"],
        WARNING_VALID_WITH_FEWER_RECORDS: effect["structural_validity_increased_while_record_count_decreased"],
        WARNING_UNEXPLAINED_REMOVAL: bool(removals[REMOVAL_CLASSES[2]]),
        WARNING_CLEARED_BY_REMOVAL: effect["cleared_with_the_record_removed"] > 0,
        WARNING_UNEXPLAINED_CHANGE: effect["changed_records_not_named_by_a_finding"] > 0,
        WARNING_CONTENT_CHANGED_COUNTS_SAME: comparison["counts_unchanged_but_content_changed"],
        WARNING_NOT_COMPARABLE: not comparison["comparable"],
    }
    effect["warnings"] = [name for name in WARNINGS if warnings.get(name)]
    return {"comparison": comparison, "removals": removals, "effect": effect}


def output_warnings(profile: Mapping[str, Any]) -> list[str]:
    """Warnings for one response on its own."""
    return [WARNING_EMPTY_OUTPUT] if profile["empty_output"] else []


def public_comparison(comparison: Mapping[str, Any]) -> dict[str, Any]:
    """Counts only. Handle lists stay in the private result."""
    return {
        "metrics": comparison["metrics"],
        "comparable": comparison["comparable"],
        "identical_bytes": comparison["identical_bytes"],
        "by_collection": {
            collection: {
                "comparable": item["comparable"],
                "primary_count": item["primary_count"],
                "repair_count": item["repair_count"],
                "count_difference": item["count_difference"],
                "retained": len(item["retained_handles"]),
                "removed": len(item["removed_handles"]),
                "added": len(item["added_handles"]),
                "unchanged": len(item["unchanged_records"]),
                "changed_in_place": len(item["changed_in_place_records"]),
            } for collection, item in comparison["by_collection"].items()
        },
        "totals": dict(comparison["totals"]),
        "record_count_decreased": comparison["record_count_decreased"],
        "counts_unchanged_but_content_changed": comparison["counts_unchanged_but_content_changed"],
        "repair_is_empty_output": comparison["repair_is_empty_output"],
        "primary_is_empty_output": comparison["primary_is_empty_output"],
    }


def definition() -> dict[str, Any]:
    """What these metrics are. Bound by the runtime protocol candidate."""
    return {
        "metrics": METRICS_ID,
        "collections": list(COLLECTIONS),
        "profile_fields": list(PROFILE_FIELDS),
        "collection_comparison_fields": list(COLLECTION_COMPARISON_FIELDS),
        "comparison_fields": list(COMPARISON_FIELDS),
        "total_fields": list(TOTAL_FIELDS),
        "effect_fields": list(EFFECT_FIELDS),
        "removal_classes": list(REMOVAL_CLASSES),
        "warnings": list(WARNINGS),
        "record_matching": "BY_HANDLE_WITHIN_A_COLLECTION_ONLY_WHEN_EVERY_HANDLE_IS_USED_ONCE",
        "empty_output": "A_DRAFT_OBJECT_WHOSE_SEVEN_COLLECTIONS_ARE_ALL_PRESENT_AND_ALL_EMPTY",
        "interpretation": INTERPRETATION,
        "gold_used": False,
        "threshold": "NONE_DEFINED",
        "edits_or_pads_predictions": False,
    }
