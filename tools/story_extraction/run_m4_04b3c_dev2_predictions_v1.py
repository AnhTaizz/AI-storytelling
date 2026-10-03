"""Run the locked P2 extractor on DEV2 input without opening DEV2 gold.

The runner accepts only the hash-locked input archive and extracted input tree.  It
does not accept a gold path or an evaluator and cannot score predictions.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional
import zipfile

from tools.story_extraction.draft_compiler_v1 import (
    DraftCompilationError,
    DraftCompilerContext,
    compile_story_extraction_draft_v1,
    prepare_story_extraction_draft_v1,
    validate_draft_v1,
)
from tools.story_extraction.durable_research_executor_v1 import (
    CheckpointIntegrityError,
    DurableResearchExecutor,
    PersistentRollingOperationPacer,
)
from tools.story_extraction.gemini_key_pool_v1 import load_runtime_config
from tools.story_extraction.m4_04b3b2_dev2_protocol_v1 import (
    CASE_IDS,
    CONCURRENCY,
    CREDENTIAL_SLOT,
    DEV2_INPUT_SHA256,
    DURABLE_EXECUTOR_VERSION,
    EXPECTED_BASE_COMMIT,
    GLOBAL_MAX_PROVIDER_OPERATIONS,
    GLOBAL_ROLLING_WINDOW_SECONDS,
    MODEL,
    PROTOCOL_ID,
    RUNTIME_VERSION,
    WINDOW_COOLDOWN_SECONDS,
    Dev2ProtocolError,
    build_primary_spec,
    build_repair_spec,
    canonical_json_bytes,
    prompt_hashes,
    sha256_bytes,
    validate_protocol_file,
    validate_public_bindings,
)
from tools.story_extraction.run_m4_04b2_dev_predictions_v1 import (
    GeminiDevWindowTransport,
    _execute_to_terminal,
    _job_telemetry,
    _write_bytes_atomic,
    _write_json,
)
from tools.story_ingestion.light_novel_adapter_v0 import ingest_manifest_file


RUNNER_ID = "M4_04B3C_DEV2_PREDICTION_RUNNER_V1"
TASK_ID = "M4-04B3C-BLIND-DEV2-PREDICTION-AND-LOCK"
PREDICTION_RESULT_ID = "M4_04B3C_DEV2_PREDICTION_RESULT_V1"
PREDICTION_MANIFEST_ID = "M4_04B3C_DEV2_PREDICTION_MANIFEST_V1"
LOCK_COMMIT = "1c005b936a7131ad68d13d608712d023ef4929f7"
LOCKED_PROTOCOL_SHA256 = "9dea83083e082e80eb350b71cad9a552f620b67f2235056d89788c9b0a23a3a4"
INPUT_MANIFEST = "M4_04B3_DEV2_INPUT_MANIFEST_V1.json"
EXPECTED_ARCHIVE_MEMBERS = 51


class Dev2PredictionError(RuntimeError):
    """A fail-closed input, lock, or execution error with no private text."""


@dataclass(frozen=True)
class CaseInput:
    case_id: str
    prepared_input: Mapping[str, Any]
    compiler_context: DraftCompilerContext


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _member_path(root: Path, member: str) -> Path:
    pure = PurePosixPath(member)
    if pure.is_absolute() or ".." in pure.parts or any("gold" in part.lower() for part in pure.parts):
        raise Dev2PredictionError("Input member path is forbidden")
    target = (root / Path(*pure.parts)).resolve()
    resolved_root = root.resolve()
    if target != resolved_root and resolved_root not in target.parents:
        raise Dev2PredictionError("Input member escapes the authorized root")
    return target


def verify_authorized_input(archive: Path, input_root: Path) -> dict[str, Any]:
    """Bind extracted input bytes to the one authorized archive; never accept gold."""
    if _sha256_file(archive) != DEV2_INPUT_SHA256:
        raise Dev2PredictionError("DEV2 input archive hash mismatch")
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            names = [item.filename for item in infos if not item.is_dir()]
            if len(names) != EXPECTED_ARCHIVE_MEMBERS or len(names) != len(set(names)):
                raise Dev2PredictionError("DEV2 input archive inventory mismatch")
            if any("gold" in part.lower() for name in names for part in PurePosixPath(name).parts):
                raise Dev2PredictionError("Gold marker found in authorized input archive")
            extracted = sorted(
                path.relative_to(input_root).as_posix()
                for path in input_root.rglob("*")
                if path.is_file()
            )
            if sorted(names) != extracted:
                raise Dev2PredictionError("Extracted DEV2 input inventory mismatch")
            for info in infos:
                if info.is_dir():
                    continue
                target = _member_path(input_root, info.filename)
                if sha256_bytes(bundle.read(info)) != _sha256_file(target):
                    raise Dev2PredictionError("Extracted DEV2 input byte mismatch")
    except (OSError, zipfile.BadZipFile) as error:
        raise Dev2PredictionError("Authorized DEV2 input archive is unreadable") from error
    manifest_path = _member_path(input_root, INPUT_MANIFEST)
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Dev2PredictionError("DEV2 input manifest is invalid") from error


def _read_json_member(input_root: Path, member: str) -> Any:
    path = _member_path(input_root, member)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Dev2PredictionError("Authorized DEV2 input member is invalid") from error


def load_case_inputs(archive: Path, input_root: Path) -> list[CaseInput]:
    manifest = verify_authorized_input(archive, input_root)
    if (
        manifest.get("artifact") != "M4_04B3_DEV2_INPUT_V1"
        or manifest.get("case_count") != len(CASE_IDS)
        or manifest.get("draft_interface") != "STORY_EXTRACTION_DRAFT_V1"
        or manifest.get("extractor_surface") != "prepared_draft_input.json members only"
    ):
        raise Dev2PredictionError("DEV2 input manifest identity mismatch")
    rows = manifest.get("cases")
    if not isinstance(rows, list) or [row.get("case_id") for row in rows] != list(CASE_IDS):
        raise Dev2PredictionError("DEV2 case identity or order mismatch")

    loaded: list[CaseInput] = []
    for row in rows:
        case_id = row["case_id"]
        base = _read_json_member(input_root, row["base_document_member"])
        prepared = _read_json_member(input_root, row["prepared_input_member"])
        manifest_path = _member_path(input_root, row["m3_manifest_member"])
        ingestion = ingest_manifest_file(manifest_path, manifest_path.parent)
        ingestion_report = _read_json_member(
            input_root, f"cases/{case_id}/ingestion_report.json"
        )
        if (
            ingestion_report.get("corpus_fingerprint_sha256") != ingestion.fingerprint
            or ingestion_report.get("round_trip_verified") is not True
        ):
            raise Dev2PredictionError("M3 ingestion binding mismatch")
        context = DraftCompilerContext(
            base_document=base,
            passage_inputs=row["passage_inputs"],
            as_of_position=row["as_of_position"],
            profile_id=row["profile_id"],
            process_id="M4_04B3C_P2",
            process_version="v1",
            run_id=f"P2_{case_id}",
            ingestion=ingestion,
        )
        if prepare_story_extraction_draft_v1(context) != prepared:
            raise Dev2PredictionError("Prepared Draft V1 input does not reproduce exactly")
        loaded.append(CaseInput(case_id, prepared, context))
    return loaded


def _compile_raw_response(raw: str, case: CaseInput) -> tuple[Any, Any, dict[str, Any]]:
    try:
        draft = json.loads(raw)
    except json.JSONDecodeError:
        return None, None, {
            "pass": False,
            "category": "JSON_PARSE_FAILURE",
            "code": "INVALID_JSON",
            "path": "",
        }
    try:
        validate_draft_v1(draft)
    except DraftCompilationError as error:
        return draft, None, {
            "pass": False,
            "category": "DRAFT_SCHEMA_FAILURE",
            "code": error.code,
            "path": error.path,
        }
    try:
        batch = compile_story_extraction_draft_v1(draft, case.compiler_context)
    except DraftCompilationError as error:
        return draft, None, {
            "pass": False,
            "category": "DRAFT_COMPILER_FAILURE",
            "code": error.code,
            "path": error.path,
        }
    return draft, batch, {
        "pass": True,
        "category": None,
        "code": None,
        "path": "",
    }


def _persist_attempt(
    artifact_root: Path,
    case_id: str,
    phase: str,
    raw: str,
    draft: Any,
) -> tuple[str, Optional[str]]:
    raw_path = artifact_root / "raw" / f"{case_id}_{phase}.txt"
    _write_bytes_atomic(raw_path, raw.encode("utf-8"))
    raw_sha = sha256_bytes(raw.encode("utf-8"))
    draft_sha = None
    if draft is not None:
        draft_path = artifact_root / "drafts" / f"{case_id}_{phase}.json"
        _write_json(draft_path, draft)
        draft_sha = _sha256_file(draft_path)
    return raw_sha, draft_sha


def _failure_artifact(
    artifact_root: Path, case_id: str, terminal_status: str, validation: Mapping[str, Any]
) -> str:
    value = {
        "case_id": case_id,
        "terminal_status": terminal_status,
        "validation": dict(validation),
    }
    path = artifact_root / "failures" / f"{case_id}.json"
    _write_json(path, value)
    return _sha256_file(path)


def _validate_private_protocol_record(path: Path) -> None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Dev2PredictionError("Private protocol validation record is invalid") from error
    required = (
        "parse",
        "schema",
        "semantic_consistency",
        "prompt_hashes",
        "case_list_and_order",
        "dev2_hash_bindings",
        "execution_profile_binding",
        "draft_compiler_binding",
        "snapshot_v2_binding",
        "repair_policy",
        "prediction_lock_before_gold",
        "holdout_prohibition",
        "secret_scan",
    )
    if value.get("protocol_sha256") != LOCKED_PROTOCOL_SHA256 or any(
        value.get(key) != "PASS" for key in required
    ):
        raise Dev2PredictionError("Private protocol validation record mismatch")


def preflight(
    *,
    protocol_path: Path,
    protocol_validation_path: Path,
    input_archive: Path,
    input_root: Path,
) -> list[CaseInput]:
    validate_protocol_file(
        protocol_path,
        expected_sha256=LOCKED_PROTOCOL_SHA256,
        expected_base_commit=EXPECTED_BASE_COMMIT,
    )
    _validate_private_protocol_record(protocol_validation_path)
    cases = load_case_inputs(input_archive, input_root)
    if [case.case_id for case in cases] != list(CASE_IDS):
        raise Dev2PredictionError("Preflight case order mismatch")
    return cases


def execute(
    *,
    protocol_path: Path,
    protocol_validation_path: Path,
    input_archive: Path,
    input_root: Path,
    checkpoint_root: Path,
    artifact_root: Path,
    result_path: Path,
    prediction_manifest_path: Path,
) -> dict[str, Any]:
    validated = validate_protocol_file(
        protocol_path,
        expected_sha256=LOCKED_PROTOCOL_SHA256,
        expected_base_commit=EXPECTED_BASE_COMMIT,
    )
    _validate_private_protocol_record(protocol_validation_path)
    cases = load_case_inputs(input_archive, input_root)

    def guard() -> None:
        validated.assert_unchanged()
        validate_public_bindings()
        if prompt_hashes() != validated.value["prompt_hashes"]:
            raise CheckpointIntegrityError("Locked prompt material changed")
        if _sha256_file(input_archive) != DEV2_INPUT_SHA256:
            raise CheckpointIntegrityError("Authorized DEV2 input archive changed")

    guard()
    config = load_runtime_config()
    selected = [item for item in config.credentials if item.slot_id == CREDENTIAL_SLOT]
    if len(selected) != 1:
        raise Dev2PredictionError("Locked credential slot is unavailable or ambiguous")
    pacer = PersistentRollingOperationPacer(
        checkpoint_root / "global_pacing.json",
        max_operations=GLOBAL_MAX_PROVIDER_OPERATIONS,
        window_seconds=GLOBAL_ROLLING_WINDOW_SECONDS,
    )
    executor = DurableResearchExecutor(
        checkpoint_root / "jobs",
        protocol_id=f"{PROTOCOL_ID}:{LOCKED_PROTOCOL_SHA256}",
        window_cooldown_seconds=WINDOW_COOLDOWN_SECONDS,
        forbidden_secrets=tuple(item._api_key for item in config.credentials),
    )
    transport = GeminiDevWindowTransport(selected[0], pacer, guard)
    results: list[dict[str, Any]] = []

    for case in cases:
        guard()
        primary_spec = build_primary_spec(case.case_id, case.prepared_input)
        primary_record = _execute_to_terminal(executor, primary_spec, transport)
        primary_raw = (primary_record.get("first_success") or {}).get("raw_response")
        primary_validation: dict[str, Any] = {
            "pass": False,
            "category": "PRIMARY_TRANSPORT_FAILURE",
            "code": primary_record.get("terminal_failure_category"),
            "path": "",
        }
        primary_raw_sha = None
        primary_draft_sha = None
        repair_used = False
        repair_spec = None
        repair_record = None
        repair_raw_sha = None
        repair_draft_sha = None
        repair_validation = None
        terminal_draft_sha = None
        final_batch = None

        if isinstance(primary_raw, str):
            draft, final_batch, primary_validation = _compile_raw_response(primary_raw, case)
            primary_raw_sha, primary_draft_sha = _persist_attempt(
                artifact_root, case.case_id, "primary", primary_raw, draft
            )
            terminal_draft_sha = primary_draft_sha
            if not primary_validation["pass"]:
                repair_used = True
                repair_spec = build_repair_spec(
                    case.case_id,
                    case.prepared_input,
                    primary_raw,
                    primary_validation,
                )
                repair_record = _execute_to_terminal(executor, repair_spec, transport)
                repair_raw = (repair_record.get("first_success") or {}).get("raw_response")
                repair_validation = {
                    "pass": False,
                    "category": "REPAIR_TRANSPORT_FAILURE",
                    "code": repair_record.get("terminal_failure_category"),
                    "path": "",
                }
                final_batch = None
                if isinstance(repair_raw, str):
                    repair_draft, final_batch, repair_validation = _compile_raw_response(
                        repair_raw, case
                    )
                    repair_raw_sha, repair_draft_sha = _persist_attempt(
                        artifact_root, case.case_id, "repair_1", repair_raw, repair_draft
                    )
                    terminal_draft_sha = repair_draft_sha

        final_batch_sha = None
        terminal_failure_sha = None
        if final_batch is not None:
            terminal_status = "STRUCTURAL_VALID"
            final_path = artifact_root / "compiled" / f"{case.case_id}.json"
            _write_json(final_path, final_batch)
            final_batch_sha = _sha256_file(final_path)
        else:
            terminal_status = (
                "STRUCTURAL_FAILURE"
                if isinstance(primary_raw, str)
                and (not repair_used or repair_record is not None)
                and (
                    (repair_validation or primary_validation).get("category")
                    in {
                        "JSON_PARSE_FAILURE",
                        "DRAFT_SCHEMA_FAILURE",
                        "DRAFT_COMPILER_FAILURE",
                        "REPAIR_TRANSPORT_FAILURE",
                    }
                )
                else "TRANSPORT_FAILURE"
            )
            terminal_failure_sha = _failure_artifact(
                artifact_root,
                case.case_id,
                terminal_status,
                repair_validation or primary_validation,
            )

        item = {
            "case_id": case.case_id,
            "primary": {
                "job_id": primary_spec.job_id,
                "request_fingerprint": primary_spec.request_fingerprint,
                "raw_response_sha256": primary_raw_sha,
                "draft_sha256": primary_draft_sha,
                "transport": _job_telemetry(primary_record),
                "validation": primary_validation,
            },
            "repair_used": repair_used,
            "repair": (
                None
                if repair_spec is None
                else {
                    "job_id": repair_spec.job_id,
                    "request_fingerprint": repair_spec.request_fingerprint,
                    "raw_response_sha256": repair_raw_sha,
                    "draft_sha256": repair_draft_sha,
                    "transport": _job_telemetry(repair_record),
                    "validation": repair_validation,
                }
            ),
            "terminal_status": terminal_status,
            "terminal_draft_sha256": terminal_draft_sha,
            "compiled_batch_sha256": final_batch_sha,
            "terminal_failure_sha256": terminal_failure_sha,
        }
        _write_json(artifact_root / "case_results" / f"{case.case_id}.json", item)
        results.append(item)
        print(
            json.dumps(
                {
                    "case_id": case.case_id,
                    "repair_used": repair_used,
                    "terminal_status": terminal_status,
                },
                sort_keys=True,
            ),
            flush=True,
        )

    guard()
    identities = [
        {
            "case_id": item["case_id"],
            "primary_request_fingerprint": item["primary"]["request_fingerprint"],
            "primary_raw_response_sha256": item["primary"]["raw_response_sha256"],
            "repair_used": item["repair_used"],
            "repair_request_fingerprint": (
                None if item["repair"] is None else item["repair"]["request_fingerprint"]
            ),
            "repair_raw_response_sha256": (
                None if item["repair"] is None else item["repair"]["raw_response_sha256"]
            ),
            "terminal_status": item["terminal_status"],
            "terminal_draft_sha256": item["terminal_draft_sha256"],
            "compiled_batch_sha256": item["compiled_batch_sha256"],
            "terminal_failure_sha256": item["terminal_failure_sha256"],
        }
        for item in results
    ]
    prediction_set_sha = sha256_bytes(canonical_json_bytes(identities))
    pacing = pacer.snapshot()
    structural_valid = sum(item["terminal_status"] == "STRUCTURAL_VALID" for item in results)
    structural_failure = sum(item["terminal_status"] == "STRUCTURAL_FAILURE" for item in results)
    transport_failure = sum(item["terminal_status"] == "TRANSPORT_FAILURE" for item in results)
    repair_count = sum(item["repair_used"] for item in results)
    repair_success = sum(
        item["repair_used"] and item["terminal_status"] == "STRUCTURAL_VALID"
        for item in results
    )
    result = {
        "artifact": PREDICTION_RESULT_ID,
        "completed_at_utc": _utc_now(),
        "task_id": TASK_ID,
        "runner_id": RUNNER_ID,
        "protocol_lock_commit": LOCK_COMMIT,
        "protocol_sha256": LOCKED_PROTOCOL_SHA256,
        "dev2_input_sha256": DEV2_INPUT_SHA256,
        "model": MODEL,
        "credential_slot": CREDENTIAL_SLOT,
        "concurrency": CONCURRENCY,
        "runtime": RUNTIME_VERSION,
        "durable_executor": DURABLE_EXECUTOR_VERSION,
        "case_count": len(results),
        "case_order": list(CASE_IDS),
        "terminal_states": [
            {"case_id": item["case_id"], "status": item["terminal_status"]}
            for item in results
        ],
        "structural_valid_count": structural_valid,
        "structural_failure_count": structural_failure,
        "transport_failure_count": transport_failure,
        "repair_count": repair_count,
        "repair_success_count": repair_success,
        "prediction_set_sha256": prediction_set_sha,
        "predictions": results,
        "global_pacing": pacing,
        "dev2_gold_opened": False,
        "holdout_input_opened": False,
        "holdout_gold_opened": False,
        "scoring_performed": False,
    }
    _write_json(result_path, result)
    manifest = {
        "artifact": PREDICTION_MANIFEST_ID,
        "protocol_lock_commit": LOCK_COMMIT,
        "protocol_sha256": LOCKED_PROTOCOL_SHA256,
        "dev2_input_sha256": DEV2_INPUT_SHA256,
        "prediction_set_sha256": prediction_set_sha,
        "case_order": list(CASE_IDS),
        "entries": identities,
        "terminal_count": len(results),
        "structural_valid_count": structural_valid,
        "structural_failure_count": structural_failure,
        "transport_failure_count": transport_failure,
        "repair_count": repair_count,
        "dev2_gold_opened": False,
        "holdout_input_opened": False,
        "holdout_gold_opened": False,
        "scoring_performed": False,
        "predictions_locked": True,
    }
    _write_json(prediction_manifest_path, manifest)
    print(
        json.dumps(
            {
                "prediction_set_sha256": prediction_set_sha,
                "repairs": repair_count,
                "structural_failure": structural_failure,
                "structural_valid": structural_valid,
                "terminal": len(results),
                "transport_failure": transport_failure,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preflight", "run"), required=True)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--protocol-validation", required=True, type=Path)
    parser.add_argument("--input-archive", required=True, type=Path)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--checkpoint-root", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--prediction-manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.mode == "preflight":
            cases = preflight(
                protocol_path=args.protocol,
                protocol_validation_path=args.protocol_validation,
                input_archive=args.input_archive,
                input_root=args.input_root,
            )
            print(json.dumps({"cases": len(cases), "status": "PREFLIGHT_PASS"}, sort_keys=True))
            return 0
        required = (
            args.checkpoint_root,
            args.artifact_root,
            args.result,
            args.prediction_manifest,
        )
        if any(value is None for value in required):
            raise Dev2PredictionError("Run mode requires all private output paths")
        execute(
            protocol_path=args.protocol,
            protocol_validation_path=args.protocol_validation,
            input_archive=args.input_archive,
            input_root=args.input_root,
            checkpoint_root=args.checkpoint_root,
            artifact_root=args.artifact_root,
            result_path=args.result,
            prediction_manifest_path=args.prediction_manifest,
        )
    except (Dev2PredictionError, Dev2ProtocolError, CheckpointIntegrityError) as error:
        print(f"M4_04B3C_RUNTIME_DEFECT_FOUND: {type(error).__name__}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
