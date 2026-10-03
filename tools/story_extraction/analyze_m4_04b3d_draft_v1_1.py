"""Offline migration diagnostic for locked B3C drafts and authorized DEV2 input.

This tool has no provider, prompt, evaluator, or gold path. It verifies each locked
parsed-draft hash, mechanically removes mention evidence_handle, compiles V1.1
against the hash-locked input, and emits source-text-free structural counts only.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any

from tools.story_extraction.draft_compiler_v1_1 import (
    DraftCompilationErrorV1_1,
    bind_exact_mention_evidence_v1_1,
    compile_story_extraction_draft_v1_1,
    migrate_draft_v1_to_v1_1,
)
from tools.story_extraction.m4_04b3b2_dev2_protocol_v1 import CASE_IDS
from tools.story_extraction.run_m4_04b3c_dev2_predictions_v1 import load_case_inputs


ANALYZER_ID = "M4_04B3D_DRAFT_V1_1_OFFLINE_MIGRATION_DIAGNOSTIC_V1"


class MigrationDiagnosticError(RuntimeError):
    """An input binding failed without disclosing private content."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MigrationDiagnosticError("Locked JSON artifact is invalid") from error


def _guard_path(path: Path) -> None:
    if any(
        "gold" in part.lower() or "holdout" in part.lower()
        for part in path.resolve().parts
    ):
        raise MigrationDiagnosticError("Gold and holdout paths are forbidden")


def _attempt(
    case_id: str,
    phase: str,
    draft: Any,
    context: Any,
    old_validation: dict[str, Any],
) -> dict[str, Any]:
    before = deepcopy(draft)
    removed = sum("evidence_handle" in mention for mention in draft["mentions"])
    migrated = migrate_draft_v1_to_v1_1(draft)
    if draft != before:
        raise MigrationDiagnosticError("Mechanical migration mutated the V1 draft")
    expected = deepcopy(draft)
    expected["draft_version"] = "STORY_EXTRACTION_DRAFT_V1_1"
    for mention in expected["mentions"]:
        mention.pop("evidence_handle", None)
    if migrated != expected:
        raise MigrationDiagnosticError("Migration changed a non-interface field")

    migrated_context = replace(
        context,
        process_id="M4_04B3D_P2_MIGRATED",
        process_version="v1.1",
        run_id=f"P2_MIGRATED_{case_id}_{phase.upper()}",
    )
    binding = None
    try:
        _, binding = bind_exact_mention_evidence_v1_1(migrated, migrated_context)
        compile_story_extraction_draft_v1_1(migrated, migrated_context)
    except DraftCompilationErrorV1_1 as error:
        validation = {
            "pass": False,
            "category": "DRAFT_V1_1_STRUCTURAL_FAILURE",
            "codes": sorted({blocker.code for blocker in error.blockers}),
            "paths": sorted({blocker.path for blocker in error.blockers}),
            "blocker_count": len(error.blockers),
        }
    else:
        validation = {
            "pass": True,
            "category": None,
            "codes": [],
            "paths": [],
            "blocker_count": 0,
        }
    return {
        "case_id": case_id,
        "phase": phase,
        "old_validation": {
            "pass": old_validation.get("pass"),
            "category": old_validation.get("category"),
            "code": old_validation.get("code"),
        },
        "migration": {
            "removed_mention_evidence_handle_count": removed,
            "other_field_changes": 0,
        },
        "v1_1_validation": validation,
        "exact_mention_evidence_binding": binding,
    }


def analyze(
    artifact_root: Path,
    input_archive: Path,
    input_root: Path,
) -> dict[str, Any]:
    for path in (artifact_root, input_archive, input_root):
        _guard_path(path)
    cases = load_case_inputs(input_archive, input_root)
    if [case.case_id for case in cases] != list(CASE_IDS):
        raise MigrationDiagnosticError("DEV2 case order mismatch")

    attempts: list[dict[str, Any]] = []
    old_terminal: dict[str, str] = {}
    migrated_terminal: dict[str, str] = {}
    for case in cases:
        result = _read_json(artifact_root / "case_results" / f"{case.case_id}.json")
        if result.get("case_id") != case.case_id or result.get("repair_used") is not True:
            raise MigrationDiagnosticError("Locked per-case result mismatch")
        old_terminal[case.case_id] = result["terminal_status"]
        case_attempts = []
        for phase, result_key, filename in (
            ("primary", "primary", f"{case.case_id}_primary.json"),
            ("repair_1", "repair", f"{case.case_id}_repair_1.json"),
        ):
            path = artifact_root / "drafts" / filename
            if _sha256(path) != result[result_key]["draft_sha256"]:
                raise MigrationDiagnosticError("Locked parsed-draft hash mismatch")
            item = _attempt(
                case.case_id,
                phase,
                _read_json(path),
                case.compiler_context,
                result[result_key]["validation"],
            )
            attempts.append(item)
            case_attempts.append(item)
        migrated_terminal[case.case_id] = (
            "STRUCTURAL_VALID"
            if case_attempts[-1]["v1_1_validation"]["pass"]
            else "STRUCTURAL_FAILURE"
        )

    if Counter(old_terminal.values()) != {
        "STRUCTURAL_VALID": 2,
        "STRUCTURAL_FAILURE": 8,
    }:
        raise MigrationDiagnosticError("Old terminal baseline is not the locked 2/10 result")

    phase_counts: dict[str, Any] = {}
    for phase in ("primary", "repair_1"):
        selected = [item for item in attempts if item["phase"] == phase]
        phase_counts[phase] = {
            "attempts": len(selected),
            "structural_valid": sum(
                item["v1_1_validation"]["pass"] for item in selected
            ),
            "structural_failure": sum(
                not item["v1_1_validation"]["pass"] for item in selected
            ),
            "remaining_failure_codes": dict(
                Counter(
                    code
                    for item in selected
                    for code in item["v1_1_validation"]["codes"]
                )
            ),
            "remaining_blocker_count": sum(
                item["v1_1_validation"]["blocker_count"] for item in selected
            ),
        }

    all_codes = Counter(
        code
        for item in attempts
        for code in item["v1_1_validation"]["codes"]
    )
    bindings = [
        item["exact_mention_evidence_binding"]
        for item in attempts
        if item["exact_mention_evidence_binding"] is not None
    ]
    return {
        "artifact": ANALYZER_ID,
        "data_classification": "TUNING_DATA_AFTER_INTERFACE_REDESIGN",
        "method": "MECHANICAL_V1_TO_V1_1_MIGRATION_NO_MODEL_NO_GOLD",
        "case_order": list(CASE_IDS),
        "draft_attempt_count": len(attempts),
        "locked_draft_hashes_verified": len(attempts),
        "old_terminal_counts": dict(Counter(old_terminal.values())),
        "migrated_terminal_counts": dict(Counter(migrated_terminal.values())),
        "migrated_terminal_states": migrated_terminal,
        "phase_counts": phase_counts,
        "migration_totals": {
            "mention_evidence_handles_removed": sum(
                item["migration"]["removed_mention_evidence_handle_count"]
                for item in attempts
            ),
            "non_interface_field_changes": 0,
        },
        "exact_mention_evidence_binding_totals": {
            key: sum(item[key] for item in bindings)
            for key in (
                "mention_count",
                "reused_exact_model_evidence",
                "reused_exact_prior_mention_evidence",
                "created_exact_mention_evidence",
            )
        },
        "remaining_failure_codes_all_attempts": dict(all_codes),
        "mention_evidence_mismatch_remaining": all_codes.get(
            "MENTION_EVIDENCE_MISMATCH", 0
        ),
        "attempts": attempts,
        "boundaries": {
            "provider_or_api_calls": 0,
            "prediction_reruns": 0,
            "gold_opened": False,
            "holdout_opened": False,
            "quality_scoring": False,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
