"""Build and validate the M4-04B2R benchmark-continuation protocol."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from tools.story_extraction.m4_04b2_dev_protocol_v1 import (
    CANDIDATES,
    CASE_IDS,
    CREDENTIAL_SLOT,
    MAX_OUTPUT_TOKENS,
    MODEL,
    TEMPERATURE,
    canonical_json_bytes,
    file_sha256,
    prompt_hashes,
    sha256_bytes,
)


TASK_ID = "M4-04B2R-VALIDATOR-ROBUSTNESS-CORRECTION-AND-BENCHMARK-RESUME"
PROTOCOL_ID = "M4_04B2R_DEV_BENCHMARK_CONTINUATION_PROTOCOL_V2"
ORIGINAL_PROTOCOL_SHA256 = "5232e334be6612db13056d14448740d34c830595324e118bbe56655b4dcda922"
ORIGINAL_COMMIT_A = "23e2f8c5ebb02680671d360069f6b86d19f2399d"
SNAPSHOT_V1_ID = "M4_EVALUATION_PROTOCOL_SNAPSHOT_V1"
SNAPSHOT_V1_SHA256 = "a9ac816fe8e20d6ed0d2a4e078c37a89a63dc10660b11d9c754b8038d71c29a6"
PRIMARY_SHA256 = "9dd429a0cb9ce88c22956b80b22f4f8a68f18c1b0f564ebbdc0e4366fd5564bf"
REPAIR_SHA256 = "5d8c7d502f05ab4efe712829d925e7e91bdc428200d3b6c46ddfe15666a7f2f5"
SNAPSHOT_V2_ID = "M4_EVALUATION_PROTOCOL_SNAPSHOT_V2"
GUARD_ID = "M4_EXTRACTION_VALIDATION_GUARD_V1"


class ContinuationProtocolError(RuntimeError):
    """Continuation protocol identity or invariant failure."""


def snapshot_identity_material(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    names = (
        "snapshot_id",
        "parent_snapshot",
        "correction_type",
        "semantic_change",
        "monotonicity",
        "dev_gold_used_to_design_correction",
        "holdout_used",
        "files",
    )
    return {name: snapshot[name] for name in names}


def load_snapshot_v2(path: Path) -> tuple[dict[str, Any], str]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ContinuationProtocolError("Snapshot V2 cannot be decoded") from error
    expected = sha256_bytes(canonical_json_bytes(snapshot_identity_material(value)))
    if value.get("snapshot_sha256") != expected:
        raise ContinuationProtocolError("Snapshot V2 identity mismatch")
    if (
        value.get("snapshot_id") != SNAPSHOT_V2_ID
        or value.get("parent_snapshot") != SNAPSHOT_V1_ID
        or value.get("correction_type") != "ROBUSTNESS_ONLY"
        or value.get("semantic_change") != "NONE_INTENDED"
        or value.get("monotonicity") != "FAIL_CLOSED_ONLY"
        or value.get("dev_gold_used_to_design_correction") is not False
        or value.get("holdout_used") is not False
    ):
        raise ContinuationProtocolError("Snapshot V2 semantics mismatch")
    for name, expected_hash in value.get("files", {}).items():
        if file_sha256(Path(name)) != expected_hash:
            raise ContinuationProtocolError(f"Snapshot V2 file mismatch: {name}")
    return value, expected


def build_protocol(
    *,
    snapshot_v2_path: Path,
    impact_path: Path,
    guard_path: Path,
    guard_test_path: Path,
    guarded_evaluator_path: Path,
    resume_runner_path: Path,
) -> dict[str, Any]:
    snapshot, snapshot_sha = load_snapshot_v2(snapshot_v2_path)
    impact = yaml.safe_load(impact_path.read_text(encoding="utf-8"))
    if impact.get("status") != "PASS" or impact.get("snapshot_v2_sha256") != snapshot_sha:
        raise ContinuationProtocolError("Impact analysis is not a V2 PASS")
    return {
        "artifact": PROTOCOL_ID,
        "task_id": TASK_ID,
        "original_b2": {
            "protocol_sha256": ORIGINAL_PROTOCOL_SHA256,
            "commit_a": ORIGINAL_COMMIT_A,
        },
        "snapshots": {
            "v1_id": SNAPSHOT_V1_ID,
            "v1_sha256": SNAPSHOT_V1_SHA256,
            "v2_id": snapshot["snapshot_id"],
            "v2_sha256": snapshot_sha,
            "impact_analysis_sha256": file_sha256(impact_path),
        },
        "tooling": {
            "guard_id": GUARD_ID,
            "guard_sha256": file_sha256(guard_path),
            "guard_tests_sha256": file_sha256(guard_test_path),
            "guarded_evaluator_sha256": file_sha256(guarded_evaluator_path),
            "resume_runner_sha256": file_sha256(resume_runner_path),
        },
        "prompt_hashes": prompt_hashes(),
        "generation_settings": {
            "model": MODEL,
            "credential_slot": CREDENTIAL_SLOT,
            "temperature": TEMPERATURE,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "provider_json_mode": True,
            "seed": "NOT_SUPPORTED_NOT_USED",
            "concurrency": 1,
        },
        "execution": {
            "candidate_order": list(CANDIDATES),
            "case_order": list(CASE_IDS),
            "resume_order": [
                *[f"P0/{case_id}" for case_id in CASE_IDS[1:]],
                *[f"P1/{case_id}" for case_id in CASE_IDS],
            ],
            "durable_profile": "M4_DURABLE_RESEARCH_EXECUTION_PROFILE_V1",
            "maximum_windows_per_job": 3,
            "maximum_provider_attempts_per_window": 3,
            "global_pacing": "6_PROVIDER_OPERATIONS_PER_ROLLING_60_SECONDS",
            "maximum_structural_repairs_per_case_candidate": 1,
            "first_success": "IMMUTABLE_LOCK",
            "output_aware_transport_retry": "FORBIDDEN",
        },
        "historical_p0_m4dev_01": {
            "primary_response_sha256": PRIMARY_SHA256,
            "repair_response_sha256": REPAIR_SHA256,
            "repair_consumed": True,
            "provider_rerun_allowed": False,
            "expected_v2_terminal_state": "STRUCTURAL_FAILURE",
        },
        "barriers": {
            "dev_gold_opened": False,
            "holdout_access": "FORBIDDEN",
        },
    }


def validate_protocol(
    value: Mapping[str, Any],
    *,
    snapshot_v2_path: Path,
    impact_path: Path,
    guard_path: Path,
    guard_test_path: Path,
    guarded_evaluator_path: Path,
    resume_runner_path: Path,
) -> None:
    expected = build_protocol(
        snapshot_v2_path=snapshot_v2_path,
        impact_path=impact_path,
        guard_path=guard_path,
        guard_test_path=guard_test_path,
        guarded_evaluator_path=guarded_evaluator_path,
        resume_runner_path=resume_runner_path,
    )
    if dict(value) != expected:
        raise ContinuationProtocolError("Continuation protocol semantic mismatch")


def validate_protocol_file(
    path: Path,
    *,
    expected_sha256: str,
    **paths: Path,
) -> dict[str, Any]:
    locked = path.read_bytes()
    if sha256_bytes(locked) != expected_sha256:
        raise ContinuationProtocolError("Continuation protocol byte identity mismatch")
    try:
        value = json.loads(locked)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ContinuationProtocolError("Continuation protocol parse failure") from error
    validate_protocol(value, **paths)
    return value


def write_protocol(path: Path, **paths: Path) -> tuple[dict[str, Any], str]:
    value = build_protocol(**paths)
    data = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return value, sha256_bytes(data)
