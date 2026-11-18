"""Offline FV2 protocol lock. No packages need to be opened to create this lock.

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
from tools.story_extraction.fresh_validation_seal_v1 import BOUND_FILES

REPO_ROOT = fv1.REPO_ROOT
# Owner decision DEC-027 (2026-11-18): lock P4R6 with host repairs QR and AM for the FV2 run.
PROMPT_VARIANT = "P4R6"
HOST_REPAIRS: tuple[str, ...] = ("QR", "AM")
PROTOCOL_ID = "M4_04B3N_FV2_PROTOCOL_V1"
TASK_ID = "M4-04B3N-FV2-PROTOCOL-LOCK"
FV2_SET_ID = "M4_04B3M_FRESH_VALIDATION_V2"
FV2_INPUT_NAME = FV2_SET_ID + "_INPUT.zip"
FV2_GOLD_NAME = FV2_SET_ID + "_GOLD.zip"
FV2_MANIFEST_NAME = FV2_SET_ID + "_BLINDNESS_MANIFEST.json"
FV2_INPUT_SHA256 = "e9d4ec2462d00922a3cf075bbbc5bd650707a38425c94eff0b626f57eac46353"
FV2_GOLD_SHA256 = "ca82f09c599e8a5d4386cc23ce76a9e7eed902b0bb51a8ea8546fa63dcce1977"
FV2_MANIFEST_SHA256 = "9595d44c4e41e50038d6f64466f2dd5415799321e86baea0878c9e3e89eda89d"
# Public records omit identifiers; the parameterized seal tool imposes no scheme.
# Assume the FV1 author's scheme with the FV2 prefix; refuse any discrepancy.
CASE_IDS = tuple(f"FV2_{i:02d}" for i in range(1, 13))
MODEL = fv1.MODEL
CREDENTIAL_SLOT = "gemini_slot_40"  # DEC-027: slot 33 was out of daily quota
PROTOCOL_NAME = PROTOCOL_ID + ".json"
VALIDATION_NAME = "M4_04B3N_FV2_PROTOCOL_VALIDATION_V1.json"
Fv2ProtocolError = fv1.Fv1ProtocolError
canonical_json_bytes = fv1.canonical_json_bytes
sha256_bytes = fv1.sha256_bytes
file_sha256 = fv1.file_sha256
sanitized_failure = fv1.sanitized_failure
ValidatedProtocol = fv1.ValidatedProtocol


def _host_repairs(value: Any) -> tuple[str, ...]:
    """Require a JSON list containing a canonical subset of the host repairs."""
    if not isinstance(value, list) or value != [r for r in ("QR", "AM") if r in value]:
        raise Fv2ProtocolError("Invalid host_repairs: expected a canonical subset of QR, AM")
    return tuple(value)


def bound_paths() -> tuple[str, ...]:
    """All public inputs, including delegated implementations and the selected preamble."""
    extra = (
        "tools/story_extraction/m4_04b3f_fv1_protocol_v1.py",
        "tools/story_extraction/run_m4_04b3g_fv1_predictions_v1.py",
        "tools/story_extraction/score_m4_04b3h_fv1_v1.py",
        "tools/story_extraction/run_m4_p4_dev_v1.py",
        "tools/story_extraction/fresh_validation_seal_v1.py",
        "tools/story_extraction/gemini_resilience_v1_1.py",
        "tools/story_extraction/durable_research_executor_v1.py",
        "tools/story_extraction/run_gemini_resilience_smoke_v1_1.py",
        "tools/story_extraction/run_m4_04b2_dev_predictions_v1.py",
        "tools/story_extraction/evaluate_extraction_guarded_v1.py",
        "tools/story_extraction/evaluate_extraction_v0.py",
        "tools/story_extraction/evaluate_m4_04b2r_dev_v2.py",
        "tools/story_extraction/check_annotation_conventions_v1.py",
        "tools/story_extraction/m4_04b3n_fv2_protocol_v1.py",
        "tools/story_extraction/run_m4_04b3o_fv2_predictions_v1.py",
        "tools/story_extraction/score_m4_04b3p_fv2_v1.py",
        "docs/research/m4/M4_ANNOTATION_CONVENTIONS_V2.md",
        "docs/research/m4/M4_FRESH_VALIDATION_V2_PROTOCOL.md",
        "benchmarks/m4_extraction/M4_04B3M_FRESH_VALIDATION_V2_SEAL_RESULT.yaml",
    )
    prompts = (fv1.SYSTEM_PREAMBLE_PATH, fv1.USER_TEMPLATE_PATH, fv1.REPAIR_USER_TEMPLATE_PATH,
               dev.PROMPT_ROOT / f"story_extraction_draft_{PROMPT_VARIANT.lower()}_system_v1_1.txt")
    repairs = _host_repairs(list(HOST_REPAIRS))
    # AM locates spans with QR's _starts helper even when QR is not selected.
    used_repairs = (*repairs, "QR") if "AM" in repairs else repairs
    repair_paths = tuple("tools/story_extraction/" + name for repair, name in (
        ("QR", "draft_quote_resolution_v1.py"), ("AM", "draft_mention_anchoring_v1.py")) if repair in used_repairs)
    return tuple(sorted(set((*BOUND_FILES, *extra, *repair_paths,
                             *(p.relative_to(REPO_ROOT).as_posix() for p in prompts)))))


def prompt_material() -> dict[str, str]:
    return dev.prompt_material(PROMPT_VARIANT)


def prompt_hashes() -> dict[str, str]:
    return {key: fv1.sha256_text(value) for key, value in prompt_material().items()}


def _adapt(value: Any, replacements: Mapping[str, str]) -> Any:
    """Retain the FV1 policy structure while rebinding its identities and byte hashes."""
    if isinstance(value, dict):
        return {_adapt(k, replacements): _adapt(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [_adapt(v, replacements) for v in value]
    if isinstance(value, str):
        if value in replacements:
            return replacements[value]
        for old, new in (("FV1", "FV2"), ("fv1", "fv2"), ("B3F", "B3N"), ("P3", PROMPT_VARIANT)):
            value = value.replace(old, new)
    return value


def build_protocol() -> dict[str, Any]:
    hashes = {name: file_sha256(REPO_ROOT / name) for name in bound_paths()}
    replacements = {getattr(fv1, key): file_sha256(path) for key, path in (
        ("DRAFT_SCHEMA_SHA256", fv1.DRAFT_SCHEMA_PATH), ("V1_SCHEMA_SHA256", fv1.V1_SCHEMA_PATH),
        ("COMPILER_SHA256", fv1.COMPILER_PATH), ("V1_COMPILER_SHA256", fv1.V1_COMPILER_PATH),
        ("PREDICATE_REGISTRY_SHA256", fv1.PREDICATE_REGISTRY_PATH),
        ("RUNTIME_SHA256", fv1.RUNTIME_PATH), ("DURABLE_EXECUTOR_SHA256", fv1.DURABLE_EXECUTOR_PATH),
        ("SNAPSHOT_V2_FILE_SHA256", fv1.SNAPSHOT_V2_PATH))}
    replacements.update({fv1.FV1_INPUT_SHA256: FV2_INPUT_SHA256, fv1.FV1_GOLD_SHA256: FV2_GOLD_SHA256,
                         fv1.FV1_MANIFEST_SHA256: FV2_MANIFEST_SHA256, fv1.FV1_SET_ID: FV2_SET_ID})
    value = _adapt(fv1.build_protocol(), replacements)
    value.update(protocol_id=PROTOCOL_ID, protocol_schema_version=PROTOCOL_ID + "_SCHEMA",
                 task_id=TASK_ID, authorization="Explicit offline tooling task; provider run requires separate invocation",
                 base_commit="NOT_PINNED_PUBLIC_BYTES_BOUND_AT_LOCK", prompt_variant=PROMPT_VARIANT,
                 public_bindings=hashes, prompt_hashes=prompt_hashes(),
                 case_count=len(CASE_IDS), case_ids=list(CASE_IDS), case_execution_order=list(CASE_IDS))
    value["prompt_source_sha256"] = {n: h for n, h in hashes.items() if "/prompts/" in n}
    value["generation"]["credential_slot"] = CREDENTIAL_SLOT
    value["generation"]["credential_qualification"] = "ONE_M4_04B1K_SMOKE_AT_B3O_START_BEFORE_ANY_FV2_CALL_ELSE_STOP"
    value["request_construction"]["primary_jobs"] = len(CASE_IDS)
    value["stop_rules"]["maximum_semantic_jobs"] = 2 * len(CASE_IDS)
    value["prediction_lock"].update(manifest_case_count=len(CASE_IDS),
        fv2_gold_may_open_only_after="PREDICTIONS_TERMINAL_LOCKED_AND_HASHED")
    value["access_policy"]["fv2_gold"] = "FORBIDDEN_UNTIL_PREDICTIONS_TERMINAL_LOCKED_AND_HASHED"
    # Omit the empty selection to preserve the original protocol serialization.
    if HOST_REPAIRS:
        value["host_repairs"] = list(_host_repairs(list(HOST_REPAIRS)))
    return value


def validate_public_bindings(protocol: Mapping[str, Any]) -> dict[str, str]:
    expected = protocol.get("public_bindings", {})
    if set(expected) != set(bound_paths()):
        raise Fv2ProtocolError("Public binding inventory mismatch")
    for name, digest in expected.items():
        if file_sha256(REPO_ROOT / name) != digest:
            raise Fv2ProtocolError("Public binding mismatch: " + name)
    snapshot = yaml.safe_load(fv1.SNAPSHOT_V2_PATH.read_text(encoding="utf-8"))
    if (snapshot.get("snapshot_id"), snapshot.get("snapshot_sha256")) != (fv1.SNAPSHOT_V2_ID, fv1.SNAPSHOT_V2_SHA256):
        raise Fv2ProtocolError("Snapshot V2 identity mismatch")
    seal = yaml.safe_load((REPO_ROOT / "benchmarks/m4_extraction/M4_04B3M_FRESH_VALIDATION_V2_SEAL_RESULT.yaml")
                          .read_text(encoding="utf-8"))["private_packages"]
    for key, name, digest in package_bindings():
        if seal[key]["name"] != name or seal[key]["sha256"] != digest:
            raise Fv2ProtocolError("FV2 seal record mismatch")
    if seal["input"]["contains_gold"]:
        raise Fv2ProtocolError("FV2 input contains gold")
    return {name: "PASS" for name in expected}


def package_bindings() -> tuple[tuple[str, str, str], ...]:
    return (("input", FV2_INPUT_NAME, FV2_INPUT_SHA256), ("gold", FV2_GOLD_NAME, FV2_GOLD_SHA256),
            ("blindness_manifest", FV2_MANIFEST_NAME, FV2_MANIFEST_SHA256))


def verify_fv2_packages(directory: Path, *, include_gold: bool = False) -> None:
    for key, name, digest in package_bindings():
        if key == "gold" and not include_gold:
            continue
        if file_sha256(Path(directory) / name) != digest:
            raise Fv2ProtocolError("FV2 package hash mismatch: " + key)


def validate_protocol(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise Fv2ProtocolError("Protocol root must be an object")
    _host_repairs(value.get("host_repairs", []))
    validate_public_bindings(value)
    expected = build_protocol()
    # Today's keyless lock and an explicit empty list have the same semantics.
    if {**value, "host_repairs": value.get("host_repairs", [])} != {
            **expected, "host_repairs": expected.get("host_repairs", [])}:
        raise Fv2ProtocolError("Protocol semantic mismatch")
    return {"semantic_consistency": "PASS", "public_bindings": "PASS"}


def validate_protocol_file(path: Path, expected_sha256: str) -> ValidatedProtocol:
    payload = Path(path).read_bytes()
    if sha256_bytes(payload) != expected_sha256:
        raise Fv2ProtocolError("Protocol hash mismatch")
    try:
        value = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise Fv2ProtocolError("Invalid protocol JSON") from exc
    checks = validate_protocol(value)
    if payload != canonical_json_bytes(value):
        raise Fv2ProtocolError("Protocol must be canonical JSON")
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
        raise Fv2ProtocolError("Unknown FV2 case or draft version")
    if any(isinstance(r, Mapping) and "evidence_handle" in r for r in (prepared.get("existing_context") or {}).values()):
        raise Fv2ProtocolError("Prepared context carries a mention evidence_handle")
    return dev.CaseInput(case_id, prepared, None, (), "FV2")


def build_primary_spec(case_id: str, prepared_input: Mapping[str, Any]):
    spec = dev.build_primary_spec(PROMPT_VARIANT, _case(case_id, prepared_input), MODEL, CREDENTIAL_SLOT)
    return replace(spec, job_id=f"M4B3N_{PROMPT_VARIANT}_{case_id}_PRIMARY", research_task_id=TASK_ID)


def build_repair_spec(case_id: str, prepared_input: Mapping[str, Any], primary_response: str, failure: Mapping[str, Any]):
    if set(failure) != {"category", "blockers"} or not isinstance(primary_response, str) or not primary_response:
        raise Fv2ProtocolError("Invalid structural repair payload")
    sanitized_failure(failure["category"], failure["blockers"])
    spec = dev.build_repair_spec(PROMPT_VARIANT, _case(case_id, prepared_input), primary_response, failure,
                                 MODEL, CREDENTIAL_SLOT)
    return replace(spec, job_id=f"M4B3N_{PROMPT_VARIANT}_{case_id}_REPAIR_1", research_task_id=TASK_ID)


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
    except (OSError, ValueError, Fv2ProtocolError):
        print("FV2 protocol refused")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
