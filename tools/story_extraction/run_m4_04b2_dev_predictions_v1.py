"""Run locked P0 then P1 development extraction predictions without DEV gold access."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Optional
import uuid

from tools.story_extraction.durable_research_executor_v1 import (
    CheckpointIntegrityError,
    CooldownPending,
    DurableJobSpec,
    DurableResearchExecutor,
    DurableTransportFailure,
    JobState,
    PersistentRollingOperationPacer,
    summarize_job,
)
from tools.story_extraction.extraction_contract_v0 import (
    CANDIDATE_COLLECTIONS,
    validate_batch,
)
from tools.story_extraction.gemini_key_pool_v1 import GeminiKeyPool, load_runtime_config
from tools.story_extraction.gemini_resilience_v1 import ProjectLimit
from tools.story_extraction.gemini_resilience_v1_1 import (
    GeminiResilienceV11Error,
    GeminiResilientTransportV11,
    ResiliencePolicyV11,
)
from tools.story_extraction.gemini_transport_v1 import official_client_factory
from tools.story_extraction.m4_04b2_dev_protocol_v1 import (
    ALLOWED_CASE_FIELDS,
    CANDIDATES,
    CASE_IDS,
    CONCURRENCY,
    CREDENTIAL_SLOT,
    DEV_PACKAGE_SHA256,
    DURABLE_EXECUTOR_VERSION,
    EXPECTED_BASE_COMMIT,
    GLOBAL_MAX_PROVIDER_OPERATIONS,
    GLOBAL_ROLLING_WINDOW_SECONDS,
    MAX_OUTPUT_TOKENS,
    MODEL,
    PROTOCOL_ID,
    REPAIR_USER_TEMPLATE,
    RUNTIME_VERSION,
    SCHEMA_RESPONSE_MODE,
    TASK_ID,
    TEMPERATURE,
    USER_TEMPLATE,
    WINDOW_COOLDOWN_SECONDS,
    DevBenchmarkProtocolError,
    ValidatedProtocol,
    canonical_json_bytes,
    prompt_material,
    safe_case_projection,
    sha256_bytes,
    validate_protocol_file,
)
from tools.story_ingestion.light_novel_adapter_v0 import ingest_manifest_file


RUNNER_ID = "M4_04B2_DEV_PREDICTION_RUNNER_V1"
PREDICTION_MANIFEST_ID = "M4_04B2_DEV_PREDICTION_MANIFEST_V1"
LOCAL_RPM = 6
LOCAL_TPM = 1_000_000


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_bytes_atomic(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _write_bytes_atomic(path, canonical_json_bytes(value))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DevBenchmarkProtocolError(f"Input-only file is invalid: {path.name}") from error


def _find_named_values(value: Any, name: str) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == name and isinstance(item, str):
                found.add(item)
            found.update(_find_named_values(item, name))
    elif isinstance(value, list):
        for item in value:
            found.update(_find_named_values(item, name))
    return found


def load_dev_inputs(
    input_directory: Path,
    *,
    ingestion_manifest: Path,
    source_root: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]], Any]:
    """Load only allowlisted DEV input and resolve exact text through frozen M3."""
    try:
        base = json.loads(
            (input_directory / "base_canonical_document.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DevBenchmarkProtocolError("Base canonical DEV input is invalid") from error
    raw_cases = _load_jsonl(input_directory / "development_cases.jsonl")
    source_rows = _load_jsonl(input_directory / "source_passage_refs.jsonl")
    if [item.get("case_id") for item in raw_cases] != list(CASE_IDS):
        raise DevBenchmarkProtocolError("DEV case identity/order mismatch")
    cases = {item["case_id"]: safe_case_projection(item) for item in raw_cases}
    refs: dict[str, list[dict[str, Any]]] = {case_id: [] for case_id in CASE_IDS}
    for row in source_rows:
        case_id = row.get("case_id")
        if case_id not in refs or set(row) != {"case_id", "passage_ref", "use"}:
            raise DevBenchmarkProtocolError("Unexpected source passage record")
        if row["use"] not in {"EVIDENCE_ELIGIBLE", "CONTEXT_ONLY"}:
            raise DevBenchmarkProtocolError("Unexpected source passage use")
        refs[case_id].append({"use": row["use"], "passage_ref": row["passage_ref"]})
    if any(not refs[case_id] for case_id in CASE_IDS):
        raise DevBenchmarkProtocolError("DEV case lacks passage input")

    ingestion = ingest_manifest_file(ingestion_manifest, source_root)
    fingerprints = _find_named_values(base, "corpus_fingerprint_sha256")
    if fingerprints and fingerprints != {ingestion.fingerprint}:
        raise DevBenchmarkProtocolError("Base and M3 ingestion fingerprint mismatch")
    for case_id in CASE_IDS:
        for item in refs[case_id]:
            ingestion.verify_passage_ref(item["passage_ref"])
    return base, cases, refs, ingestion


def build_input_payload(
    *,
    candidate: str,
    case_id: str,
    case: Mapping[str, Any],
    refs: list[dict[str, Any]],
    base: Mapping[str, Any],
    ingestion: Any,
) -> dict[str, Any]:
    prior = any(base[name] for name in CANDIDATE_COLLECTIONS)
    required_envelope = {
        "batch_version": "STORY_EXTRACTION_BATCH/v0",
        "contract_version": "STORY_EXTRACTION/v0",
        "process": {
            "method": "AUTOMATED_EXTRACTION",
            "process_id": f"M4_04B2_{candidate}",
            "process_version": "v1",
            "run_id": f"{candidate}_{case_id}",
        },
        "scope": {
            "story_id": base["story"]["id"],
            "ingestion": {
                "contract_version": "LIGHT_NOVEL_INGESTION/v0",
                "corpus_fingerprint_sha256": ingestion.fingerprint,
            },
            "passage_inputs": refs,
            "as_of_position": case["as_of_position"],
            "prior_canonical_context": {
                "kind": "BASE_DOCUMENT_RECORDS" if prior else "NONE"
            },
            "profile_id": case["extraction_profile"],
        },
        "base_canonical_identity": case["base_canonical_identity"],
    }
    passage_texts = [
        {
            "passage_ref": item["passage_ref"],
            "text": ingestion.resolve_passage_text(item["passage_ref"]),
            "use": item["use"],
        }
        for item in refs
    ]
    prior_context = {
        name: base[name]
        for name in CANDIDATE_COLLECTIONS
        if base[name]
    }
    return {
        "case_definition": {key: case[key] for key in ALLOWED_CASE_FIELDS if key in case},
        "passages_in_fixed_order": passage_texts,
        "prior_canonical_context": prior_context,
        "required_envelope": required_envelope,
    }


class _GuardedClient:
    def __init__(self, client: Any, guard: Callable[[], None]) -> None:
        self.client = client
        self.guard = guard

    def generate(self, **kwargs: Any) -> Any:
        self.guard()
        response = self.client.generate(**kwargs)
        self.guard()
        return response


class GeminiDevWindowTransport:
    """Accepted V1.1 transport with persistent global pacing and protocol guards."""

    def __init__(self, credential: Any, pacer: PersistentRollingOperationPacer, guard) -> None:
        self.credential = credential
        self.pacer = pacer
        self.guard = guard

    def __call__(self, spec: DurableJobSpec, window: int, request_id: str) -> dict[str, Any]:
        del window
        self.guard()
        if spec.credential_slot != self.credential.slot_id:
            raise CheckpointIntegrityError("Credential lock mismatch")
        pool = GeminiKeyPool((self.credential,))
        global_waits: list[float] = []

        def client_factory(api_key: str):
            self.guard()
            wait = float(self.pacer.acquire())
            self.guard()
            global_waits.append(wait)
            return _GuardedClient(official_client_factory(api_key), self.guard)

        gate = GeminiResilientTransportV11(
            pool,
            client_factory=client_factory,
            policy=ResiliencePolicyV11(
                max_total_provider_attempts=3,
                max_transport_retries=2,
                max_credential_failovers=0,
                max_project_group_failovers=0,
                max_concurrency=CONCURRENCY,
                queue_capacity=2,
                queue_wait_timeout_seconds=300,
                default_project_limit=ProjectLimit(rpm=LOCAL_RPM, tpm=LOCAL_TPM),
                max_local_rate_wait_seconds=300,
                max_scheduler_wait_seconds=300,
                base_backoff_seconds=1,
                max_backoff_seconds=30,
                backoff_jitter_ratio=0.20,
                circuit_failure_threshold=3,
                circuit_open_cooldown_seconds=30,
                half_open_probe_requests=1,
            ),
        )
        try:
            result = gate.generate(
                spec.system_prompt,
                spec.user_prompt,
                spec.model,
                dict(spec.generation_config),
                request_id,
            )
        except GeminiResilienceV11Error as error:
            self.guard()
            attempts = [dict(item) for item in error.attempts]
            if len(attempts) != len(global_waits):
                raise CheckpointIntegrityError("Global pacing attempt accounting mismatch")
            for item, wait in zip(attempts, global_waits):
                item["global_safety_wait_seconds"] = round(wait, 6)
            retry_after = [
                float(item["retry_after_seconds"])
                for item in attempts
                if isinstance(item.get("retry_after_seconds"), (int, float))
            ]
            raise DurableTransportFailure(
                error.category.value,
                provider_attempts=error.provider_attempts,
                fingerprint=error.fingerprint,
                attempts=attempts,
                retry_after_seconds=max(retry_after, default=None),
            ) from None
        self.guard()
        attempts = [dict(item) for item in result.get("transport_attempts", [])]
        if len(attempts) != len(global_waits):
            raise CheckpointIntegrityError("Global pacing success accounting mismatch")
        for item, wait in zip(attempts, global_waits):
            item["global_safety_wait_seconds"] = round(wait, 6)
        result["transport_attempts"] = attempts
        return result


def _execute_to_terminal(
    executor: DurableResearchExecutor,
    spec: DurableJobSpec,
    transport: GeminiDevWindowTransport,
) -> dict[str, Any]:
    executor.ensure_job(spec)
    while True:
        record = executor.load_job(spec)
        state = JobState(record["state"])
        if state in {JobState.SUCCEEDED_LOCKED, JobState.TERMINAL_FAILED}:
            return record
        try:
            record = executor.execute_window(spec, transport)
            print(
                f"{spec.job_id} window={record['window_count']} state={record['state']}",
                flush=True,
            )
        except CooldownPending as pending:
            print(
                f"{spec.job_id} deferred cooldown wait={pending.remaining_seconds:.3f}s",
                flush=True,
            )
            time.sleep(max(0.001, pending.remaining_seconds))


def _validation(raw: str, base: Mapping[str, Any]) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    try:
        batch = json.loads(raw)
    except json.JSONDecodeError:
        return None, {"pass": False, "category": "JSON_PARSE_FAILURE", "errors": ["invalid JSON"]}
    report = validate_batch(batch, dict(base), ingestion=None)
    if report["pass"]:
        return batch, {"pass": True, "category": None, "errors": []}
    errors = [
        issue
        for section in report["checks"].values()
        for issue in section["issues"]
    ]
    category = (
        "STORY_EXTRACTION_BATCH_SCHEMA_FAILURE"
        if report["checks"]["envelope"]["issues"]
        else "CANONICAL_RECORD_STRUCTURAL_FAILURE"
    )
    return None, {"pass": False, "category": category, "errors": errors[:50]}


def _job_telemetry(record: Mapping[str, Any]) -> dict[str, Any]:
    summary = summarize_job(record)
    first = record.get("first_success") or {}
    usage = first.get("usage") or {}
    latency = sum(
        max(0.0, _iso_epoch(window["ended_at_utc"]) - _iso_epoch(window["started_at_utc"]))
        for window in record.get("windows", [])
    )
    summary.update(
        {
            "usage": usage,
            "provider_latency_seconds": round(latency, 6),
            "provider_reported_model_version": first.get("model_reported_version"),
        }
    )
    return summary


def _iso_epoch(value: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _spec(
    *,
    job_id: str,
    system: str,
    user: str,
) -> DurableJobSpec:
    return DurableJobSpec(
        job_id=job_id,
        model=MODEL,
        system_prompt=system,
        user_prompt=user,
        generation_config={"temperature": TEMPERATURE, "max_output_tokens": MAX_OUTPUT_TOKENS},
        schema_response_mode=SCHEMA_RESPONSE_MODE,
        credential_slot=CREDENTIAL_SLOT,
        research_task_id=TASK_ID,
    )


def execute(
    *,
    protocol_path: Path,
    protocol_validation_path: Path,
    expected_protocol_sha256: str,
    lock_commit: str,
    access_manifest_path: Path,
    input_directory: Path,
    input_extraction_result_path: Path,
    ingestion_manifest: Path,
    source_root: Path,
    checkpoint_directory: Path,
    artifact_directory: Path,
    result_path: Path,
    prediction_manifest_path: Path,
) -> dict[str, Any]:
    validated = validate_protocol_file(
        protocol_path,
        expected_sha256=expected_protocol_sha256,
        expected_base_commit=EXPECTED_BASE_COMMIT,
    )
    try:
        validation_record = json.loads(protocol_validation_path.read_text(encoding="utf-8"))
        access = json.loads(access_manifest_path.read_text(encoding="utf-8"))
        extraction = json.loads(input_extraction_result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DevBenchmarkProtocolError("Required pre-live private gate is invalid") from error
    required_checks = (
        "parse",
        "schema",
        "semantic_consistency",
        "prompt_hashes",
        "case_list",
        "execution_profile_binding",
        "evaluator_snapshot_binding",
        "holdout_prohibition",
        "secret_scan",
    )
    if (
        validation_record.get("protocol_sha256") != validated.sha256
        or any(validation_record.get(key) != "PASS" for key in required_checks)
    ):
        raise DevBenchmarkProtocolError("Protocol validation record mismatch")
    if access.get("dev_gold_opened") is not False or access.get("holdout_access") != "FORBIDDEN":
        raise DevBenchmarkProtocolError("Gold/holdout access barrier is not closed")
    if (
        extraction.get("dev_package_sha256") != DEV_PACKAGE_SHA256
        or extraction.get("dev_gold_opened") is not False
        or extraction.get("holdout_opened") is not False
    ):
        raise DevBenchmarkProtocolError("Input-only extraction gate mismatch")
    validated.assert_unchanged()

    base, cases, refs, ingestion = load_dev_inputs(
        input_directory,
        ingestion_manifest=ingestion_manifest,
        source_root=source_root,
    )
    validated.assert_unchanged()
    config = load_runtime_config()
    selected = [item for item in config.credentials if item.slot_id == CREDENTIAL_SLOT]
    if len(selected) != 1:
        raise DevBenchmarkProtocolError("Locked credential slot is unavailable")
    pacer = PersistentRollingOperationPacer(
        checkpoint_directory / "global_pacing.json",
        max_operations=GLOBAL_MAX_PROVIDER_OPERATIONS,
        window_seconds=GLOBAL_ROLLING_WINDOW_SECONDS,
    )
    executor = DurableResearchExecutor(
        checkpoint_directory / "jobs",
        protocol_id=f"{PROTOCOL_ID}:{validated.sha256}",
        window_cooldown_seconds=WINDOW_COOLDOWN_SECONDS,
        forbidden_secrets=tuple(item._api_key for item in config.credentials),
    )
    transport = GeminiDevWindowTransport(selected[0], pacer, validated.assert_unchanged)
    prompts = prompt_material()
    predictions: list[dict[str, Any]] = []

    for candidate in CANDIDATES:
        print(f"Starting candidate {candidate}", flush=True)
        system = prompts["p0_system" if candidate == "P0" else "p1_system"]
        for case_id in CASE_IDS:
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
            primary_spec = _spec(
                job_id=f"M4B2_{candidate}_{case_id}_PRIMARY",
                system=system,
                user=user,
            )
            primary = _execute_to_terminal(executor, primary_spec, transport)
            primary_summary = _job_telemetry(primary)
            raw_primary = (primary.get("first_success") or {}).get("raw_response")
            primary_validation = {
                "pass": False,
                "category": "NO_SUCCESSFUL_PROVIDER_RESPONSE",
                "errors": [],
            }
            final_batch: Optional[dict[str, Any]] = None
            repair_summary = None
            repair_validation = None
            repair_used = False
            if isinstance(raw_primary, str):
                _write_bytes_atomic(
                    artifact_directory / "raw" / candidate / f"{case_id}_primary.txt",
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
                            artifact_directory / "raw" / candidate / f"{case_id}_repair.txt",
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
                final_path = artifact_directory / "final" / candidate / f"{case_id}.json"
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
                        sha256_bytes(raw_primary.encode("utf-8"))
                        if isinstance(raw_primary, str)
                        else None
                    ),
                    "primary_transport": primary_summary,
                    "primary_validation": primary_validation,
                    "repair_used": repair_used,
                    "repair_transport": repair_summary,
                    "repair_validation": repair_validation,
                    "final_structural_valid": final_batch is not None,
                    "final_prediction_sha256": final_sha,
                }
            )
        print(f"Completed candidate {candidate}", flush=True)

    validated.assert_unchanged()
    candidate_hashes = {}
    for candidate in CANDIDATES:
        identities = [
            {
                "case_id": item["case_id"],
                "final_prediction_sha256": item["final_prediction_sha256"],
                "primary_raw_response_sha256": item["primary_raw_response_sha256"],
                "repair_used": item["repair_used"],
            }
            for item in predictions
            if item["candidate"] == candidate
        ]
        candidate_hashes[candidate] = sha256_bytes(canonical_json_bytes(identities))
    pacing = pacer.snapshot()
    protocol_invariants = {
        "candidate_order": "PASS",
        "case_order": "PASS",
        "credential_switch_count": 0,
        "model_switch_count": 0,
        "output_aware_transport_retry_count": 0,
        "provider_calls_after_success_lock": 0,
        "duplicate_success_calls": 0,
        "response_comparison_count": 0,
        "best_of_n_selection_count": 0,
        "repair_cap_violations": 0,
        "dev_gold_opened": False,
        "holdout_opened": False,
        "pacing": pacing["invariant"],
    }
    result = {
        "artifact": "M4_04B2_DEV_PREDICTION_RESULT_V1",
        "completed_at_utc": _utc_now(),
        "task_id": TASK_ID,
        "base_commit": EXPECTED_BASE_COMMIT,
        "protocol_sha256": validated.sha256,
        "protocol_lock_commit": lock_commit,
        "model": MODEL,
        "credential_slot": CREDENTIAL_SLOT,
        "runtime": RUNTIME_VERSION,
        "durable_executor": DURABLE_EXECUTOR_VERSION,
        "candidate_prediction_set_hashes": candidate_hashes,
        "predictions": predictions,
        "global_pacing": pacing,
        "protocol_invariants": protocol_invariants,
        "dev_gold_opened": False,
        "holdout_input_opened": False,
        "holdout_gold_opened": False,
    }
    _write_json(result_path, result)
    manifest = {
        "artifact": PREDICTION_MANIFEST_ID,
        "protocol_sha256": validated.sha256,
        "protocol_lock_commit": lock_commit,
        "model": MODEL,
        "execution_profile": "M4_DURABLE_RESEARCH_EXECUTION_PROFILE_V1",
        "prediction_set_hashes": candidate_hashes,
        "entries": [
            {
                "candidate": item["candidate"],
                "case_id": item["case_id"],
                "primary_raw_response_sha256": item["primary_raw_response_sha256"],
                "final_prediction_sha256": item["final_prediction_sha256"],
                "repair_used": item["repair_used"],
                "terminal_state": (
                    "STRUCTURAL_VALID"
                    if item["final_structural_valid"]
                    else "STRUCTURAL_FAILURE"
                ),
            }
            for item in predictions
        ],
        "dev_gold_opened": False,
        "holdout_input_opened": False,
        "holdout_gold_opened": False,
        "predictions_locked": True,
    }
    _write_json(prediction_manifest_path, manifest)
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


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--protocol-validation", required=True, type=Path)
    parser.add_argument("--expected-protocol-sha256", required=True)
    parser.add_argument("--lock-commit", required=True)
    parser.add_argument("--access-manifest", required=True, type=Path)
    parser.add_argument("--input-directory", required=True, type=Path)
    parser.add_argument("--input-extraction-result", required=True, type=Path)
    parser.add_argument("--ingestion-manifest", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--checkpoint-directory", required=True, type=Path)
    parser.add_argument("--artifact-directory", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--prediction-manifest", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        execute(
            protocol_path=args.protocol,
            protocol_validation_path=args.protocol_validation,
            expected_protocol_sha256=args.expected_protocol_sha256,
            lock_commit=args.lock_commit,
            access_manifest_path=args.access_manifest,
            input_directory=args.input_directory,
            input_extraction_result_path=args.input_extraction_result,
            ingestion_manifest=args.ingestion_manifest,
            source_root=args.source_root,
            checkpoint_directory=args.checkpoint_directory,
            artifact_directory=args.artifact_directory,
            result_path=args.result,
            prediction_manifest_path=args.prediction_manifest,
        )
    except (DevBenchmarkProtocolError, CheckpointIntegrityError) as error:
        print(f"M4_04B2_RUNTIME_DEFECT_FOUND: {type(error).__name__}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
