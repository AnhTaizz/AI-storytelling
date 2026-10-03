"""Offline terminal-draft migration diagnostic for locked B3C DEV2 artifacts.

Only hash-locked parsed terminal drafts and the authorized DEV2 input are read.
The diagnostic changes the Draft version tag, removes mention.evidence_handle,
and performs deterministic V1.1 compilation. It has no provider or gold path.
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
    DRAFT_VERSION,
    DraftCompilationErrorV1_1,
    compile_story_extraction_draft_v1_1,
)
from tools.story_extraction.m4_04b3b2_dev2_protocol_v1 import CASE_IDS
from tools.story_extraction.run_m4_04b3c_dev2_predictions_v1 import load_case_inputs


ANALYZER_ID = "M4_04B3D3_DEV2_V1_1_TERMINAL_DRAFT_MIGRATION_V1"


class MigrationDiagnosticError(RuntimeError):
    """A locked-input or mechanical-migration invariant failed."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MigrationDiagnosticError("Locked JSON artifact is invalid") from error


def _guard_path(path: Path) -> None:
    if any("gold" in part.lower() or "holdout" in part.lower() for part in path.resolve().parts):
        raise MigrationDiagnosticError("Gold and holdout paths are forbidden")


def migrate_terminal_draft_v1_to_v1_1(draft: Any) -> tuple[dict[str, Any], int]:
    """Apply only the preregistered interface migration, without mutating input."""
    if not isinstance(draft, dict) or draft.get("draft_version") != "STORY_EXTRACTION_DRAFT_V1":
        raise MigrationDiagnosticError("Terminal draft is not Draft V1")
    if not isinstance(draft.get("mentions"), list):
        raise MigrationDiagnosticError("Terminal draft mentions are invalid")
    before = deepcopy(draft)
    migrated = deepcopy(draft)
    migrated["draft_version"] = DRAFT_VERSION
    removed = 0
    for mention in migrated["mentions"]:
        if "evidence_handle" in mention:
            mention.pop("evidence_handle")
            removed += 1
    if draft != before:
        raise MigrationDiagnosticError("Migration mutated the locked Draft V1 input")
    expected = deepcopy(before)
    expected["draft_version"] = DRAFT_VERSION
    for mention in expected["mentions"]:
        mention.pop("evidence_handle", None)
    if migrated != expected:
        raise MigrationDiagnosticError("Migration changed a non-interface field")
    return migrated, removed


def _terminal_draft_path(artifact_root: Path, case_id: str, result: dict[str, Any]) -> Path:
    phase = "repair_1" if result.get("repair_used") is True else "primary"
    path = artifact_root / "drafts" / f"{case_id}_{phase}.json"
    expected = result.get("terminal_draft_sha256")
    if not isinstance(expected, str) or _sha256(path) != expected:
        raise MigrationDiagnosticError("Locked terminal-draft hash mismatch")
    attempt_key = "repair" if phase == "repair_1" else "primary"
    if result.get(attempt_key, {}).get("draft_sha256") != expected:
        raise MigrationDiagnosticError("Terminal attempt binding mismatch")
    return path


def analyze(artifact_root: Path, input_archive: Path, input_root: Path) -> dict[str, Any]:
    """Migrate exactly ten locked terminal drafts and return public-safe metadata."""
    for path in (artifact_root, input_archive, input_root):
        _guard_path(path)
    cases = load_case_inputs(input_archive, input_root)
    if [case.case_id for case in cases] != list(CASE_IDS):
        raise MigrationDiagnosticError("DEV2 case order mismatch")

    old_states: dict[str, str] = {}
    migrated_states: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    remaining_codes: Counter[str] = Counter()
    total_removed = 0
    for case in cases:
        result = _read_json(artifact_root / "case_results" / f"{case.case_id}.json")
        if result.get("case_id") != case.case_id:
            raise MigrationDiagnosticError("Locked per-case result mismatch")
        old_state = result.get("terminal_status")
        if old_state not in {"STRUCTURAL_VALID", "STRUCTURAL_FAILURE"}:
            raise MigrationDiagnosticError("Locked terminal state is invalid")
        old_states[case.case_id] = old_state
        terminal_path = _terminal_draft_path(artifact_root, case.case_id, result)
        migrated, removed = migrate_terminal_draft_v1_to_v1_1(_read_json(terminal_path))
        total_removed += removed
        context = replace(
            case.compiler_context,
            process_id="M4_04B3D3_P2_TERMINAL_MIGRATED",
            process_version="v1.1",
            run_id=f"P2_TERMINAL_MIGRATED_{case.case_id}",
        )
        try:
            compile_story_extraction_draft_v1_1(migrated, context)
        except DraftCompilationErrorV1_1 as error:
            codes = sorted({blocker.code for blocker in error.blockers})
            blocker_count = len(error.blockers)
            state = "STRUCTURAL_FAILURE"
            remaining_codes.update(blocker.code for blocker in error.blockers)
        else:
            codes = []
            blocker_count = 0
            state = "STRUCTURAL_VALID"
        migrated_states[case.case_id] = state
        rows.append({
            "case_id": case.case_id,
            "old_terminal": old_state,
            "migrated_terminal": state,
            "removed_mention_evidence_handle_count": removed,
            "remaining_failure_codes": codes,
            "remaining_blocker_count": blocker_count,
        })

    old_counts = Counter(old_states.values())
    if old_counts != Counter({"STRUCTURAL_VALID": 2, "STRUCTURAL_FAILURE": 8}):
        raise MigrationDiagnosticError("Old terminal baseline is not locked 2/10")
    migrated_counts = Counter(migrated_states.values())
    mismatch_count = remaining_codes["MENTION_EVIDENCE_MISMATCH"]
    gate_pass = migrated_counts["STRUCTURAL_VALID"] == 10 and mismatch_count == 0
    return {
        "artifact": ANALYZER_ID,
        "status": "PASS" if gate_pass else "FAIL",
        "data_classification": "TUNING_DATA_AFTER_INTERFACE_REDESIGN",
        "method": "MECHANICAL_TERMINAL_DRAFT_V1_TO_V1_1_NO_MODEL_NO_GOLD",
        "case_order": list(CASE_IDS),
        "terminal_drafts_verified": len(rows),
        "old_terminal_counts": dict(old_counts),
        "migrated_terminal_counts": dict(migrated_counts),
        "migrated_terminal_states": migrated_states,
        "migration_totals": {
            "mention_evidence_handles_removed": total_removed,
            "non_interface_field_changes": 0,
        },
        "remaining_failure_codes": dict(sorted(remaining_codes.items())),
        "mention_evidence_mismatch_remaining": mismatch_count,
        "mention_evidence_mismatch_eliminated": mismatch_count == 0,
        "cases": rows,
        "success_gate": {
            "requires_structural_valid": 10,
            "requires_mention_evidence_mismatch": 0,
            "pass": gate_pass,
            "queue_action": "CONTINUE" if gate_pass else "STOP",
        },
        "boundaries": {
            "provider_or_api_calls": 0,
            "prediction_reruns": 0,
            "gold_opened": False,
            "holdout_opened": False,
            "quality_scoring": False,
            "semantic_repair": False,
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
    return 0 if result["success_gate"]["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
