"""Offline FV3 protocol lock. No packages need to be opened to create this lock.

Create once with --directory D; preserve the printed SHA256 independently. Consumers
require that digest rather than trusting a digest beside a mutable protocol file.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from tools.story_extraction import m4_04b3f_fv1_protocol_v1 as fv1
from tools.story_extraction import run_m4_p4_dev_v1 as dev
from tools.story_extraction import m4_04b3n_fv2_protocol_v1 as fv2

REPO_ROOT = fv1.REPO_ROOT
PROMPT_VARIANT = "P4R8"
HOST_REPAIRS = ("QR", "AM", "ME", "SE", "TB", "DA", "VG")
PROTOCOL_ID = "M4_04B3Z_FV3_PROTOCOL_V1"
TASK_ID = "M4-04B3Z-FV3-PROTOCOL-LOCK"
FV3_SET_ID = "M4_04B3Y_FRESH_VALIDATION_V3"
FV3_INPUT_NAME = FV3_SET_ID + "_INPUT.zip"
FV3_GOLD_NAME = FV3_SET_ID + "_GOLD.zip"
FV3_MANIFEST_NAME = FV3_SET_ID + "_BLINDNESS_MANIFEST.json"
FV3_INPUT_SHA256 = "784f0276087795635aedd452a50cadbae761194bb3b9e55a176c758c457791be"
FV3_GOLD_SHA256 = "24cb19e083eb34cbeaa4278c7e20aa733e62c7089ab82bd3717950ab8d3dfb12"
FV3_MANIFEST_SHA256 = "56586433c2d86a4b4e0b064f7af3be51412a1b045627c29d0d23215b049ab1f3"
SEAL_RECORD = f"benchmarks/m4_extraction/{FV3_SET_ID}_SEAL_RESULT.yaml"
CONVENTIONS = "docs/research/m4/M4_ANNOTATION_CONVENTIONS_V4.md"
CASE_IDS = tuple(f"fv3-{i:02d}" for i in range(1, 17))
MODEL = fv1.MODEL
CREDENTIAL_SLOT = "gemini_slot_40"
PROTOCOL_NAME = PROTOCOL_ID + ".json"
VALIDATION_NAME = "M4_04B3Z_FV3_PROTOCOL_VALIDATION_V1.json"
Fv3ProtocolError = fv1.Fv1ProtocolError
canonical_json_bytes = fv1.canonical_json_bytes
sha256_bytes = fv1.sha256_bytes
file_sha256 = fv1.file_sha256
sanitized_failure = fv1.sanitized_failure
ValidatedProtocol = fv1.ValidatedProtocol


def bound_paths() -> tuple[str, ...]:
    """Include every FV2 protocol-construction input and the FV3 implementation."""
    modules = (
        "m4_04b3z_fv3_protocol_v1", "run_m4_04b3z_fv3_predictions_v1", "score_m4_04b3z_fv3_v1",
        "draft_mention_evidence_v1", "draft_sentence_evidence_v1", "draft_transfer_bounds_v1",
        "draft_date_anchor_v1", "draft_vocabulary_guard_v1",
        "check_annotation_conventions_v2", "check_annotation_conventions_v3",
        "gemini_errors_v1", "gemini_resilience_v1", "gemini_transport_v1", "holdout_seal_v1",
        "diagnose_m4_04b3i_fv1_v1", "diagnose_m4_p4_dev_v1", "m4_04b3b2_dev2_protocol_v1",
        "gemini_key_pool_v1", "run_m4_04b3c_dev2_predictions_v1", "m4_04b2_dev_protocol_v1",
    )
    paths = {*fv2.bound_paths(), CONVENTIONS, SEAL_RECORD,
             "docs/research/m4/M4_FRESH_VALIDATION_V3_PROTOCOL.md",
             "docs/research/m4/M4_FV3_LOCKED_RUN_PROTOCOL.md",
             "tools/canonical_story/conformance_v0.py",
             (dev.PROMPT_ROOT / "story_extraction_draft_p4r8_system_v1_1.txt").relative_to(REPO_ROOT).as_posix()}
    paths.update(f"tools/story_extraction/{module}.py" for module in modules)
    return tuple(sorted(paths))


def build_protocol() -> dict[str, Any]:
    value = fv2.build_protocol()
    hashes = {name: file_sha256(REPO_ROOT / name) for name in bound_paths()}
    value.pop("fv2_bindings")
    value.update(protocol_id=PROTOCOL_ID, protocol_schema_version=PROTOCOL_ID + "_SCHEMA", task_id=TASK_ID,
                 extractor_id=value["extractor_id"].replace("P4R6", PROMPT_VARIANT),
                 prompt_variant=PROMPT_VARIANT, host_repairs=list(HOST_REPAIRS),
                 mention_evidence_predicates=list(dev.MENTION_EVIDENCE_PREDICATES),
                 fv3_bindings={f"{k}_sha256": h for k, _, h in package_bindings()} | {"set_id": FV3_SET_ID},
                 public_bindings=hashes, case_count=len(CASE_IDS), case_ids=list(CASE_IDS),
                 case_execution_order=list(CASE_IDS),
                 prompt_hashes={k: fv1.sha256_text(v) for k, v in dev.prompt_material(PROMPT_VARIANT).items()},
                 prompt_source_sha256={n: h for n, h in hashes.items() if "/prompts/" in n})
    access = value["access_policy"]
    for key in list(access):
        if key.startswith("fv2_"):
            access[key.replace("fv2_", "fv3_", 1)] = access.pop(key)
    access["prompt_tuning_material"] = "DEV1_DEV2_FV2_DEV_ONLY_NEVER_FV3_TEXT"
    prediction = value["prediction_lock"]
    prediction["fv3_gold_may_open_only_after"] = prediction.pop("fv2_gold_may_open_only_after")
    prediction["manifest_case_count"] = len(CASE_IDS)
    value["generation"].update(credential_slot=CREDENTIAL_SLOT,
        credential_qualification="ONE_M4_04B1K_SMOKE_AT_B3Z_START_BEFORE_ANY_FV3_CALL_ELSE_STOP")
    value["request_construction"].update(primary_jobs=len(CASE_IDS), passage_handles="P1_THROUGH_PN_ORDERED",
                                         job_id_pattern="M4B3Z_P4R8_{CASE_ID}_PRIMARY")
    value["repair_policy"]["job_id_pattern"] = "M4B3Z_P4R8_{CASE_ID}_REPAIR_1"
    value["stop_rules"]["maximum_semantic_jobs"] = 2 * len(CASE_IDS)
    return value


def validate_public_bindings(protocol: Mapping[str, Any]) -> dict[str, str]:
    expected = protocol.get("public_bindings", {})
    if set(expected) != set(bound_paths()):
        raise Fv3ProtocolError("Public binding inventory mismatch")
    for name, digest in expected.items():
        if file_sha256(REPO_ROOT / name) != digest:
            raise Fv3ProtocolError("Public binding mismatch: " + name)
    snapshot = yaml.safe_load(fv1.SNAPSHOT_V2_PATH.read_text(encoding="utf-8"))
    if (snapshot.get("snapshot_id"), snapshot.get("snapshot_sha256")) != (fv1.SNAPSHOT_V2_ID, fv1.SNAPSHOT_V2_SHA256):
        raise Fv3ProtocolError("Snapshot V2 identity mismatch")
    seal = yaml.safe_load((REPO_ROOT / SEAL_RECORD).read_text(encoding="utf-8"))
    if (seal["status"] != "SEALED" or seal["set_id"] != FV3_SET_ID or seal["case_ids"] != list(CASE_IDS)
            or seal["gold"]["annotation_conventions_sha256"] != expected[CONVENTIONS]):
        raise Fv3ProtocolError("FV3 seal identity mismatch")
    for key, _, digest in package_bindings():
        if seal["private_packages"][key + "_sha256"] != digest:
            raise Fv3ProtocolError("FV3 seal record mismatch")
    return {name: "PASS" for name in expected}


def package_bindings() -> tuple[tuple[str, str, str], ...]:
    return (("input", FV3_INPUT_NAME, FV3_INPUT_SHA256), ("gold", FV3_GOLD_NAME, FV3_GOLD_SHA256),
            ("blindness_manifest", FV3_MANIFEST_NAME, FV3_MANIFEST_SHA256))


def verify_fv3_packages(directory: Path, *, include_gold: bool = False) -> None:
    for key, name, digest in package_bindings():
        if key == "gold" and not include_gold:
            continue
        if file_sha256(Path(directory) / name) != digest:
            raise Fv3ProtocolError("FV3 package hash mismatch: " + key)


def validate_protocol(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise Fv3ProtocolError("Protocol root must be an object")
    validate_public_bindings(value)
    if value != build_protocol():
        raise Fv3ProtocolError("Protocol semantic mismatch")
    return {"semantic_consistency": "PASS", "public_bindings": "PASS"}


def validate_protocol_file(path: Path, expected_sha256: str) -> ValidatedProtocol:
    payload = Path(path).read_bytes()
    if sha256_bytes(payload) != expected_sha256:
        raise Fv3ProtocolError("Protocol hash mismatch")
    try:
        value = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise Fv3ProtocolError("Invalid protocol JSON") from exc
    checks = validate_protocol(value)
    if payload != canonical_json_bytes(value):
        raise Fv3ProtocolError("Protocol must be canonical JSON")
    return ValidatedProtocol(Path(path), deepcopy(value), expected_sha256, payload, checks)


def write_protocol(path: Path) -> tuple[dict[str, Any], str]:
    value = build_protocol()
    validate_protocol(value)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("xb") as stream:
        stream.write(canonical_json_bytes(value))
    return value, sha256_bytes(canonical_json_bytes(value))


def _case(case_id: str, prepared: Mapping[str, Any]) -> dev.CaseInput:
    if case_id not in CASE_IDS or prepared.get("draft_version") != fv1.DRAFT_VERSION:
        raise Fv3ProtocolError("Unknown FV3 case or draft version")
    if any(isinstance(r, Mapping) and "evidence_handle" in r for r in (prepared.get("existing_context") or {}).values()):
        raise Fv3ProtocolError("Prepared context carries a mention evidence_handle")
    return dev.CaseInput(case_id, prepared, None, (), "FV3")


def build_primary_spec(case_id: str, prepared_input: Mapping[str, Any]):
    spec = dev.build_primary_spec(PROMPT_VARIANT, _case(case_id, prepared_input), MODEL, CREDENTIAL_SLOT)
    return replace(spec, job_id=f"M4B3Z_{PROMPT_VARIANT}_{case_id}_PRIMARY", research_task_id=TASK_ID)


def build_repair_spec(case_id: str, prepared_input: Mapping[str, Any], primary_response: str, failure: Mapping[str, Any]):
    if set(failure) != {"category", "blockers"} or not isinstance(primary_response, str) or not primary_response:
        raise Fv3ProtocolError("Invalid structural repair payload")
    sanitized_failure(failure["category"], failure["blockers"])
    spec = dev.build_repair_spec(PROMPT_VARIANT, _case(case_id, prepared_input), primary_response, failure,
                                 MODEL, CREDENTIAL_SLOT)
    return replace(spec, job_id=f"M4B3Z_{PROMPT_VARIANT}_{case_id}_REPAIR_1", research_task_id=TASK_ID)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        _, digest = write_protocol(args.directory / PROTOCOL_NAME)
        validated = validate_protocol_file(args.directory / PROTOCOL_NAME, digest)
        with (args.directory / VALIDATION_NAME).open("xb") as stream:
            stream.write(canonical_json_bytes({"protocol_sha256": digest, "checks": dict(validated.checks)}))
        print(json.dumps({"protocol_sha256": digest, "status": "PASS"}, sort_keys=True))
        return 0
    except (OSError, ValueError, Fv3ProtocolError):
        print("FV3 protocol refused")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
