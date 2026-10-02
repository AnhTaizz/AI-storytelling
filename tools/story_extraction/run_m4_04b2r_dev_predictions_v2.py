"""Resume M4-04B2 after Guard V1 without reexecuting historical jobs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Optional

from tools.story_extraction.durable_research_executor_v1 import (
    AtomicIntegrityJsonStore,
    CheckpointIntegrityError,
    DurableResearchExecutor,
    PersistentRollingOperationPacer,
)
from tools.story_extraction.extraction_contract_guard_v1 import (
    UnexpectedValidatorInternalError,
    validate_batch_guarded,
)
from tools.story_extraction.gemini_key_pool_v1 import GeminiKeyPool, load_runtime_config
from tools.story_extraction.m4_04b2_dev_protocol_v1 import (
    CANDIDATES,
    CASE_IDS,
    CREDENTIAL_SLOT,
    GLOBAL_MAX_PROVIDER_OPERATIONS,
    GLOBAL_ROLLING_WINDOW_SECONDS,
    PROTOCOL_ID,
    REPAIR_USER_TEMPLATE,
    USER_TEMPLATE,
    WINDOW_COOLDOWN_SECONDS,
    DevBenchmarkProtocolError,
    canonical_json_bytes,
    prompt_material,
    sha256_bytes,
    validate_protocol_file as validate_original_protocol,
)
from tools.story_extraction.m4_04b2r_continuation_v2 import (
    PRIMARY_SHA256,
    REPAIR_SHA256,
    ContinuationProtocolError,
    validate_protocol_file as validate_continuation_protocol,
)
from tools.story_extraction.run_m4_04b2_dev_predictions_v1 import (
    GeminiDevWindowTransport,
    _execute_to_terminal,
    _job_telemetry,
    _spec,
    _utc_now,
    _write_bytes_atomic,
    _write_json,
    build_input_payload,
    load_dev_inputs,
)


RUNNER_ID = "M4_04B2R_DEV_PREDICTION_RUNNER_V2"


def _validation(raw: str, base: Mapping[str, Any]) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    try:
        batch = json.loads(raw)
    except json.JSONDecodeError:
        return None, {"pass": False, "category": "JSON_PARSE_FAILURE", "errors": ["invalid JSON"]}
    report = validate_batch_guarded(batch, dict(base), ingestion=None)
    if report["pass"]:
        return batch, {"pass": True, "category": None, "errors": []}
    errors = [issue for section in report["checks"].values() for issue in section["issues"]]
    category = (
        "STORY_EXTRACTION_BATCH_SCHEMA_FAILURE"
        if report["checks"]["envelope"]["issues"]
        or any(issue.startswith("MALFORMED_PASSAGE_INPUT:") for issue in errors)
        else "CANONICAL_RECORD_STRUCTURAL_FAILURE"
    )
    return None, {"pass": False, "category": category, "errors": errors[:50]}


def _load_locked_job(path: Path, expected_job_id: str, expected_response_sha256: str) -> dict[str, Any]:
    record = AtomicIntegrityJsonStore().read(path)
    success = record.get("first_success")
    if (
        record.get("job_id") != expected_job_id
        or record.get("state") != "SUCCEEDED_LOCKED"
        or not isinstance(success, dict)
        or success.get("response_sha256") != expected_response_sha256
        or sha256_bytes(success.get("raw_response", "").encode("utf-8")) != expected_response_sha256
    ):
        raise CheckpointIntegrityError(f"Historical success identity mismatch: {expected_job_id}")
    return record


def _historical_audit(
    *,
    base: Mapping[str, Any],
    checkpoint_directory: Path,
    primary_raw_path: Path,
    repair_raw_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    primary_bytes = primary_raw_path.read_bytes()
    repair_bytes = repair_raw_path.read_bytes()
    if sha256_bytes(primary_bytes) != PRIMARY_SHA256 or sha256_bytes(repair_bytes) != REPAIR_SHA256:
        raise CheckpointIntegrityError("Historical raw-response hash mismatch")
    primary_record = _load_locked_job(
        checkpoint_directory / "jobs" / "M4B2_P0_M4DEV_01_PRIMARY.json",
        "M4B2_P0_M4DEV_01_PRIMARY",
        PRIMARY_SHA256,
    )
    repair_record = _load_locked_job(
        checkpoint_directory / "jobs" / "M4B2_P0_M4DEV_01_REPAIR_1.json",
        "M4B2_P0_M4DEV_01_REPAIR_1",
        REPAIR_SHA256,
    )
    primary_batch, primary_validation = _validation(primary_bytes.decode("utf-8"), base)
    repair_batch, repair_validation = _validation(repair_bytes.decode("utf-8"), base)
    if primary_batch is not None or repair_batch is not None:
        raise CheckpointIntegrityError("Guard V1 unexpectedly rescued historical malformed output")
    audit = {
        "artifact": "M4_04B2R_HISTORICAL_RESPONSE_REVALIDATION_V2",
        "completed_at_utc": _utc_now(),
        "primary_response_sha256": PRIMARY_SHA256,
        "primary_v2_result": primary_validation,
        "repair_response_sha256": REPAIR_SHA256,
        "repair_v2_result": repair_validation,
        "repair_consumed": True,
        "final_state": "STRUCTURAL_FAILURE",
        "historical_provider_operations_before_resume": {
            "primary": primary_record["total_provider_operations"],
            "repair": repair_record["total_provider_operations"],
        },
        "provider_operations_after_resume_authorization": {"primary": 0, "repair": 0},
        "provider_rerun_allowed": False,
        "dev_gold_opened": False,
        "holdout_opened": False,
    }
    prediction = {
        "candidate": "P0",
        "case_id": "M4DEV_01",
        "primary_job_id": "M4B2_P0_M4DEV_01_PRIMARY",
        "primary_request_fingerprint": primary_record["request_fingerprint"],
        "primary_raw_response_sha256": PRIMARY_SHA256,
        "primary_transport": _job_telemetry(primary_record),
        "primary_validation": primary_validation,
        "repair_used": True,
        "repair_transport": _job_telemetry(repair_record),
        "repair_validation": repair_validation,
        "final_structural_valid": False,
        "final_prediction_sha256": None,
        "historical_immutable": True,
    }
    return audit, prediction


def execute(args: argparse.Namespace) -> dict[str, Any]:
    original = validate_original_protocol(
        args.original_protocol,
        expected_sha256=args.expected_original_protocol_sha256,
        expected_base_commit="aeb26d363694c337bb2b30170629be0d94ed090c",
    )
    continuation_paths = {
        "snapshot_v2_path": args.snapshot_v2,
        "impact_path": args.impact,
        "guard_path": args.guard,
        "guard_test_path": args.guard_tests,
        "guarded_evaluator_path": args.guarded_evaluator,
        "resume_runner_path": Path(__file__),
    }
    continuation = validate_continuation_protocol(
        args.continuation_protocol,
        expected_sha256=args.expected_continuation_protocol_sha256,
        **continuation_paths,
    )
    validation = json.loads(args.continuation_validation.read_text(encoding="utf-8"))
    required = (
        "parse",
        "schema",
        "snapshot_v1_identity",
        "snapshot_v2_identity",
        "impact_analysis",
        "prompt_identity",
        "generation_settings",
        "historical_response_hashes",
        "repair_consumed_state",
        "dev_gold_barrier",
        "holdout_barrier",
    )
    if validation.get("protocol_sha256") != args.expected_continuation_protocol_sha256 or any(
        validation.get(name) != "PASS" for name in required
    ):
        raise ContinuationProtocolError("Continuation validation record mismatch")
    access = json.loads(args.access_manifest.read_text(encoding="utf-8"))
    extraction = json.loads(args.input_extraction_result.read_text(encoding="utf-8"))
    if access.get("dev_gold_opened") is not False or access.get("holdout_access") != "FORBIDDEN":
        raise ContinuationProtocolError("Blindness access barrier is not closed")
    if extraction.get("dev_gold_opened") is not False or extraction.get("holdout_opened") is not False:
        raise ContinuationProtocolError("Input extraction barrier mismatch")

    base, cases, refs, ingestion = load_dev_inputs(
        args.input_directory,
        ingestion_manifest=args.ingestion_manifest,
        source_root=args.source_root,
    )
    audit, historical_prediction = _historical_audit(
        base=base,
        checkpoint_directory=args.checkpoint_directory,
        primary_raw_path=args.historical_primary_raw,
        repair_raw_path=args.historical_repair_raw,
    )
    _write_json(args.historical_audit, audit)
    if args.offline_historical_only:
        print(json.dumps({"final_state": audit["final_state"], "status": "OFFLINE_REVALIDATION_PASS"}, sort_keys=True))
        return audit

    config = load_runtime_config()
    selected = [item for item in config.credentials if item.slot_id == CREDENTIAL_SLOT]
    if len(selected) != 1:
        raise ContinuationProtocolError("Locked credential slot is unavailable")
    pacer = PersistentRollingOperationPacer(
        args.checkpoint_directory / "global_pacing.json",
        max_operations=GLOBAL_MAX_PROVIDER_OPERATIONS,
        window_seconds=GLOBAL_ROLLING_WINDOW_SECONDS,
    )
    executor = DurableResearchExecutor(
        args.checkpoint_directory / "jobs",
        protocol_id=f"{PROTOCOL_ID}:{original.sha256}",
        window_cooldown_seconds=WINDOW_COOLDOWN_SECONDS,
        forbidden_secrets=tuple(item._api_key for item in config.credentials),
    )
    transport = GeminiDevWindowTransport(selected[0], pacer, original.assert_unchanged)
    prompts = prompt_material()
    predictions = [historical_prediction]

    resume = [("P0", case_id) for case_id in CASE_IDS[1:]] + [("P1", case_id) for case_id in CASE_IDS]
    current_candidate = None
    for candidate, case_id in resume:
        if candidate != current_candidate:
            print(f"Starting/resuming candidate {candidate}", flush=True)
            current_candidate = candidate
        system = prompts["p0_system" if candidate == "P0" else "p1_system"]
        payload = build_input_payload(
            candidate=candidate,
            case_id=case_id,
            case=cases[case_id],
            refs=refs[case_id],
            base=base,
            ingestion=ingestion,
        )
        payload_text = canonical_json_bytes(payload).decode("utf-8")
        user = USER_TEMPLATE.replace("{CASE_ID}", case_id).replace(
            "{ID_PREFIX}", f"m4b2-{candidate.lower()}-{case_id.lower()}"
        ).replace("{INPUT_PAYLOAD_JSON}", payload_text)
        primary_spec = _spec(job_id=f"M4B2_{candidate}_{case_id}_PRIMARY", system=system, user=user)
        primary = _execute_to_terminal(executor, primary_spec, transport)
        raw_primary = (primary.get("first_success") or {}).get("raw_response")
        primary_validation = {
            "pass": False,
            "category": "NO_SUCCESSFUL_PROVIDER_RESPONSE",
            "errors": [],
        }
        final_batch = None
        repair_summary = None
        repair_validation = None
        repair_used = False
        if isinstance(raw_primary, str):
            _write_bytes_atomic(
                args.artifact_directory / "raw" / candidate / f"{case_id}_primary.txt",
                raw_primary.encode("utf-8"),
            )
            final_batch, primary_validation = _validation(raw_primary, base)
            if not primary_validation["pass"]:
                repair_used = True
                repair_user = (
                    REPAIR_USER_TEMPLATE.replace("{CASE_ID}", case_id)
                    .replace("{CANDIDATE}", candidate)
                    .replace("{INPUT_PAYLOAD_JSON}", payload_text)
                    .replace("{ORIGINAL_RESPONSE}", raw_primary)
                    .replace(
                        "{VALIDATOR_ERRORS_JSON}",
                        canonical_json_bytes(primary_validation).decode("utf-8"),
                    )
                )
                repair_spec = _spec(
                    job_id=f"M4B2_{candidate}_{case_id}_REPAIR_1",
                    system=prompts["repair_system"],
                    user=repair_user,
                )
                repair = _execute_to_terminal(executor, repair_spec, transport)
                repair_summary = _job_telemetry(repair)
                raw_repair = (repair.get("first_success") or {}).get("raw_response")
                if isinstance(raw_repair, str):
                    _write_bytes_atomic(
                        args.artifact_directory / "raw" / candidate / f"{case_id}_repair.txt",
                        raw_repair.encode("utf-8"),
                    )
                    final_batch, repair_validation = _validation(raw_repair, base)
                else:
                    repair_validation = {
                        "pass": False,
                        "category": "NO_SUCCESSFUL_PROVIDER_RESPONSE",
                        "errors": [],
                    }
        if final_batch is not None:
            final_path = args.artifact_directory / "final" / candidate / f"{case_id}.json"
            _write_json(final_path, final_batch)
            final_sha = sha256_bytes(final_path.read_bytes())
        else:
            final_sha = None
        predictions.append(
            {
                "candidate": candidate,
                "case_id": case_id,
                "primary_job_id": primary_spec.job_id,
                "primary_request_fingerprint": primary_spec.request_fingerprint,
                "primary_raw_response_sha256": (
                    sha256_bytes(raw_primary.encode("utf-8")) if isinstance(raw_primary, str) else None
                ),
                "primary_transport": _job_telemetry(primary),
                "primary_validation": primary_validation,
                "repair_used": repair_used,
                "repair_transport": repair_summary,
                "repair_validation": repair_validation,
                "final_structural_valid": final_batch is not None,
                "final_prediction_sha256": final_sha,
                "historical_immutable": False,
            }
        )

    if [(item["candidate"], item["case_id"]) for item in predictions] != [
        *(("P0", case_id) for case_id in CASE_IDS),
        *(("P1", case_id) for case_id in CASE_IDS),
    ]:
        raise CheckpointIntegrityError("Final candidate/case order mismatch")
    post_audit, _ = _historical_audit(
        base=base,
        checkpoint_directory=args.checkpoint_directory,
        primary_raw_path=args.historical_primary_raw,
        repair_raw_path=args.historical_repair_raw,
    )
    if post_audit["historical_provider_operations_before_resume"] != audit[
        "historical_provider_operations_before_resume"
    ]:
        raise CheckpointIntegrityError("Historical provider operation count changed")

    candidate_hashes: dict[str, str] = {}
    for candidate in CANDIDATES:
        identities = [
            {
                "case_id": item["case_id"],
                "final_prediction_sha256": item["final_prediction_sha256"],
                "primary_raw_response_sha256": item["primary_raw_response_sha256"],
                "repair_used": item["repair_used"],
                "terminal_state": (
                    "STRUCTURAL_VALID" if item["final_structural_valid"] else "STRUCTURAL_FAILURE"
                ),
            }
            for item in predictions
            if item["candidate"] == candidate
        ]
        candidate_hashes[candidate] = sha256_bytes(canonical_json_bytes(identities))
    pacing = pacer.snapshot()
    result = {
        "artifact": "M4_04B2R_DEV_PREDICTION_RESULT_V2",
        "completed_at_utc": _utc_now(),
        "continuation_protocol_sha256": args.expected_continuation_protocol_sha256,
        "continuation_lock_commit": args.continuation_lock_commit,
        "snapshot_v2_sha256": continuation["snapshots"]["v2_sha256"],
        "candidate_prediction_set_hashes": candidate_hashes,
        "predictions": predictions,
        "global_pacing": pacing,
        "historical_no_rerun": True,
        "dev_gold_opened": False,
        "holdout_input_opened": False,
        "holdout_gold_opened": False,
    }
    _write_json(args.result, result)
    manifest = {
        "artifact": "M4_04B2R_DEV_PREDICTION_MANIFEST_V2",
        "original_protocol_sha256": args.expected_original_protocol_sha256,
        "continuation_protocol_sha256": args.expected_continuation_protocol_sha256,
        "snapshot_v2_sha256": continuation["snapshots"]["v2_sha256"],
        "continuation_lock_commit": args.continuation_lock_commit,
        "prediction_set_hashes": candidate_hashes,
        "entries": [
            {
                "candidate": item["candidate"],
                "case_id": item["case_id"],
                "primary_raw_response_sha256": item["primary_raw_response_sha256"],
                "final_prediction_sha256": item["final_prediction_sha256"],
                "repair_used": item["repair_used"],
                "terminal_state": (
                    "STRUCTURAL_VALID" if item["final_structural_valid"] else "STRUCTURAL_FAILURE"
                ),
            }
            for item in predictions
        ],
        "historical_no_rerun": True,
        "dev_gold_opened": False,
        "holdout_input_opened": False,
        "holdout_gold_opened": False,
        "predictions_locked": True,
    }
    _write_json(args.prediction_manifest, manifest)
    print(
        json.dumps(
            {
                "P0": candidate_hashes["P0"],
                "P1": candidate_hashes["P1"],
                "predictions": len(predictions),
                "status": "PREDICTIONS_LOCKED_PRIVATE",
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-protocol", required=True, type=Path)
    parser.add_argument("--expected-original-protocol-sha256", required=True)
    parser.add_argument("--continuation-protocol", required=True, type=Path)
    parser.add_argument("--continuation-validation", required=True, type=Path)
    parser.add_argument("--expected-continuation-protocol-sha256", required=True)
    parser.add_argument("--continuation-lock-commit", required=True)
    parser.add_argument("--snapshot-v2", required=True, type=Path)
    parser.add_argument("--impact", required=True, type=Path)
    parser.add_argument("--guard", required=True, type=Path)
    parser.add_argument("--guard-tests", required=True, type=Path)
    parser.add_argument("--guarded-evaluator", required=True, type=Path)
    parser.add_argument("--access-manifest", required=True, type=Path)
    parser.add_argument("--input-directory", required=True, type=Path)
    parser.add_argument("--input-extraction-result", required=True, type=Path)
    parser.add_argument("--ingestion-manifest", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--checkpoint-directory", required=True, type=Path)
    parser.add_argument("--artifact-directory", required=True, type=Path)
    parser.add_argument("--historical-primary-raw", required=True, type=Path)
    parser.add_argument("--historical-repair-raw", required=True, type=Path)
    parser.add_argument("--historical-audit", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--prediction-manifest", required=True, type=Path)
    parser.add_argument("--offline-historical-only", action="store_true")
    args = parser.parse_args()
    try:
        execute(args)
    except (
        ContinuationProtocolError,
        DevBenchmarkProtocolError,
        CheckpointIntegrityError,
        UnexpectedValidatorInternalError,
    ) as error:
        print(f"M4_04B2R_RUNTIME_DEFECT_FOUND: {type(error).__name__}: {error}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
