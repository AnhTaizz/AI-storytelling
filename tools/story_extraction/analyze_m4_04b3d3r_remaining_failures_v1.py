"""Attribute the five remaining D3 DEV2 blockers without repair or scoring.

The analyzer reads only locked terminal P2 drafts and the authorized DEV2 input.
It emits structural metadata and reason codes, never source text or quotes.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from typing import Any

from tools.story_extraction.analyze_m4_04b3d3_dev2_migration_v1 import (
    MigrationDiagnosticError,
    _read_json,
    _sha256,
    migrate_terminal_draft_v1_to_v1_1,
)
from tools.story_extraction.draft_compiler_v1 import (
    DraftCompilationError,
    _context_maps,
    _occurrences,
    _quote_ref,
    compile_story_extraction_draft_v1,
)
from tools.story_extraction.draft_compiler_v1_1 import (
    DraftCompilationErrorV1_1,
    collect_draft_structural_blockers_v1_1,
    compile_story_extraction_draft_v1_1,
)
from tools.story_extraction.run_m4_04b3c_dev2_predictions_v1 import load_case_inputs


ANALYZER_ID = "M4_04B3D3R_REMAINING_FAILURE_ATTRIBUTION_V1"
CASE_IDS = ("DEV2_03", "DEV2_04", "DEV2_05", "DEV2_07")


def _guard_path(path: Path) -> None:
    if any("gold" in part.lower() or "holdout" in part.lower() for part in path.resolve().parts):
        raise MigrationDiagnosticError("Gold and holdout paths are forbidden")


def _terminal_draft(artifact_root: Path, case_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    result = _read_json(artifact_root / "case_results" / f"{case_id}.json")
    if result.get("case_id") != case_id or result.get("repair_used") is not True:
        raise MigrationDiagnosticError("Locked terminal result mismatch")
    path = artifact_root / "drafts" / f"{case_id}_repair_1.json"
    expected = result.get("terminal_draft_sha256")
    if (
        not isinstance(expected, str)
        or _sha256(path) != expected
        or result.get("repair", {}).get("draft_sha256") != expected
    ):
        raise MigrationDiagnosticError("Locked terminal-draft hash mismatch")
    return result, _read_json(path)


def _v1_control_code(draft: dict[str, Any], context: Any) -> tuple[str | None, str]:
    """Expose latent structure through unchanged V1's optional mention binding path."""
    control = deepcopy(draft)
    for mention in control["mentions"]:
        mention.pop("evidence_handle", None)
    try:
        compile_story_extraction_draft_v1(control, context)
    except DraftCompilationError as error:
        return error.code, error.path
    return None, ""


def _event_anchor_defect_count(draft: dict[str, Any]) -> int:
    anchors = {record["handle"]: record for record in draft["anchors"]}
    count = 0
    for event in draft["events"]:
        anchor = anchors.get(event.get("anchor_handle"))
        if anchor is None:
            continue
        if anchor.get("anchor_kind") != "EVENT_TIME" or anchor.get("event_handle") != event["handle"]:
            count += 1
    return count


def _duplicate_concrete_proposition_pair_count(draft: dict[str, Any]) -> int:
    groups: dict[str, int] = defaultdict(int)
    for proposition in draft["propositions"]:
        if "predicate" not in proposition:
            continue
        signature = json.dumps(
            {"predicate": proposition["predicate"], "args": proposition["args"]},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        groups[signature] += 1
    return sum(count * (count - 1) // 2 for count in groups.values() if count > 1)


def _canonical_attribution(
    case_id: str,
    locked: dict[str, Any],
    migrated: dict[str, Any],
    context: Any,
) -> dict[str, Any]:
    relevant_fields = ("entities", "events", "anchors", "propositions", "assertions")
    semantics_unchanged = all(locked[field] == migrated[field] for field in relevant_fields)
    control_code, control_path = _v1_control_code(locked, context)
    try:
        compile_story_extraction_draft_v1_1(migrated, context)
    except DraftCompilationErrorV1_1 as error:
        v1_1_codes = sorted({blocker.code for blocker in error.blockers})
    else:
        v1_1_codes = []

    if case_id in {"DEV2_03", "DEV2_07"}:
        root_cause = "EVENT_REFERENCES_NON_EVENT_TIME_ANCHOR"
        defect_instances = _event_anchor_defect_count(locked)
    elif case_id == "DEV2_04":
        root_cause = "DUPLICATE_CONCRETE_PROPOSITION_CONTENT"
        defect_instances = _duplicate_concrete_proposition_pair_count(locked)
    else:
        raise MigrationDiagnosticError("Unexpected canonical-failure case")

    inherited = (
        semantics_unchanged
        and control_code == "CANONICAL_CONFORMANCE_FAILURE"
        and control_path == "canonical"
        and v1_1_codes == ["CANONICAL_CONFORMANCE_FAILURE"]
        and defect_instances > 0
    )
    return {
        "failure_code": "CANONICAL_CONFORMANCE_FAILURE",
        "classification": "A_INHERITED_LOCKED_P2_MODEL_DEFECT" if inherited else "D_UNCERTAIN",
        "root_cause": root_cause,
        "locked_v1_defect_instances": defect_instances,
        "migration_changed_relevant_semantics": not semantics_unchanged,
        "unchanged_v1_compiler_control_reproduced": control_code == "CANONICAL_CONFORMANCE_FAILURE",
        "v1_1_only_behavior_required_for_failure": False if inherited else None,
    }


def _ambiguous_quote_attributions(
    locked: dict[str, Any],
    migrated: dict[str, Any],
    context: Any,
) -> list[dict[str, Any]]:
    blockers = [
        blocker
        for blocker in collect_draft_structural_blockers_v1_1(migrated, context)
        if blocker.code == "AMBIGUOUS_QUOTE"
    ]
    passages, _ = _context_maps(context)
    rows = []
    for blocker in blockers:
        field, handle = blocker.path.split("/", 1)
        locked_record = next(record for record in locked[field] if record["handle"] == handle)
        migrated_record = next(record for record in migrated[field] if record["handle"] == handle)
        locator_fields = ("passage_handle", "quote", "occurrence", "role")
        locator_unchanged = all(
            locked_record.get(name) == migrated_record.get(name) for name in locator_fields
        )
        try:
            _quote_ref(locked_record, passages, context)
        except DraftCompilationError as error:
            locked_v1_code = error.code
        else:
            locked_v1_code = None
        _, text = passages[locked_record["passage_handle"]]
        match_count = len(_occurrences(text, locked_record["quote"]))
        inherited = (
            locator_unchanged
            and "occurrence" not in locked_record
            and match_count > 1
            and locked_v1_code == "AMBIGUOUS_QUOTE"
        )
        rows.append({
            "failure_code": "AMBIGUOUS_QUOTE",
            "classification": "A_INHERITED_LOCKED_P2_MODEL_DEFECT" if inherited else "D_UNCERTAIN",
            "root_cause": "REPEATED_QUOTE_WITHOUT_OCCURRENCE",
            "record_path": blocker.path,
            "locked_v1_quote_match_count": match_count,
            "locked_v1_occurrence_present": "occurrence" in locked_record,
            "migration_changed_quote_locator": not locator_unchanged,
            "unchanged_v1_quote_resolver_reproduced": locked_v1_code == "AMBIGUOUS_QUOTE",
            "v1_1_only_behavior_required_for_failure": False if inherited else None,
        })
    return rows


def analyze(artifact_root: Path, input_archive: Path, input_root: Path) -> dict[str, Any]:
    for path in (artifact_root, input_archive, input_root):
        _guard_path(path)
    cases = {case.case_id: case for case in load_case_inputs(input_archive, input_root)}
    if any(case_id not in cases for case_id in CASE_IDS):
        raise MigrationDiagnosticError("Required DEV2 input case is missing")

    rows = []
    for case_id in CASE_IDS:
        result, locked = _terminal_draft(artifact_root, case_id)
        if result.get("terminal_status") != "STRUCTURAL_FAILURE":
            raise MigrationDiagnosticError("Expected locked terminal failure")
        migrated, _ = migrate_terminal_draft_v1_to_v1_1(locked)
        context = replace(
            cases[case_id].compiler_context,
            process_id="M4_04B3D3R_ATTRIBUTION",
            process_version="v1.1",
            run_id=f"ATTRIBUTION_{case_id}",
        )
        if case_id == "DEV2_05":
            attributions = _ambiguous_quote_attributions(locked, migrated, context)
            if len(attributions) != 2:
                raise MigrationDiagnosticError("Expected two ambiguous-quote blockers")
        else:
            attributions = [_canonical_attribution(case_id, locked, migrated, context)]
        rows.append({"case_id": case_id, "blockers": attributions})

    all_blockers = [blocker for row in rows for blocker in row["blockers"]]
    classification_counts = dict(Counter(blocker["classification"] for blocker in all_blockers))
    all_inherited = classification_counts == {"A_INHERITED_LOCKED_P2_MODEL_DEFECT": 5}
    compiler_defects = classification_counts.get("C_V1_1_COMPILER_DEFECT", 0)
    authorize_dev3 = all_inherited and compiler_defects == 0
    return {
        "artifact": ANALYZER_ID,
        "status": (
            "M4_04B3D3R_V1_1_READY_FOR_FRESH_DEV3"
            if authorize_dev3 else "M4_04B3D3R_V1_1_FIX_REQUIRED"
        ),
        "method": "LOCKED_V1_CAUSAL_COUNTERFACTUAL_AND_SEMANTIC_INVARIANT_CHECK",
        "case_order": list(CASE_IDS),
        "terminal_draft_hashes_verified": len(rows),
        "blocker_count": len(all_blockers),
        "classification_counts": classification_counts,
        "cases": rows,
        "decision": {
            "all_remaining_blockers_inherited_p2_model_defects": all_inherited,
            "migration_introduced_defect_count": classification_counts.get(
                "B_MECHANICAL_MIGRATION_DEFECT", 0
            ),
            "v1_1_compiler_defect_count": compiler_defects,
            "uncertain_count": classification_counts.get("D_UNCERTAIN", 0),
            "authorize_fresh_dev3_construction": authorize_dev3,
        },
        "boundaries": {
            "provider_or_api_calls": 0,
            "prediction_reruns": 0,
            "gold_opened": False,
            "holdout_opened": False,
            "repairs": 0,
            "schema_compiler_prompt_changes": 0,
        },
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--input-archive", required=True, type=Path)
    parser.add_argument("--input-root", required=True, type=Path)
    args = parser.parse_args()
    result = analyze(args.artifact_root, args.input_archive, args.input_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["decision"]["authorize_fresh_dev3_construction"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
