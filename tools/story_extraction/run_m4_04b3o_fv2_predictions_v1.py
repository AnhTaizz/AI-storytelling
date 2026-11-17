"""Blind FV2 runner: preflight is offline; run requires a separately pinned protocol hash.

The runner never hashes or opens gold. Only prepared input reaches the transport.
Keep the printed prediction-lock digest independently for the offline scorer.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import time
from typing import Any, Mapping

from tools.story_extraction import m4_04b3n_fv2_protocol_v1 as lock
from tools.story_extraction import run_m4_04b3g_fv1_predictions_v1 as shared
from tools.story_extraction.durable_research_executor_v1 import (
    DurableResearchExecutor, PersistentRollingOperationPacer, CheckpointIntegrityError,
)
from tools.story_extraction.fresh_validation_seal_v1 import load_input_cases

RUNNER_ID = "M4_04B3O_FV2_PREDICTION_RUNNER_V1"
RESULT_NAME = "M4_04B3O_FV2_PREDICTION_RESULT_V1.json"
MANIFEST_NAME = "M4_04B3O_FV2_PREDICTION_MANIFEST_V1.json"
PREDICTION_LOCK_NAME = "M4_04B3O_FV2_PREDICTION_LOCK_V1.json"
SMOKE_JOB_ID = "M4B3O_B1K_SMOKE_" + lock.CREDENTIAL_SLOT.upper()
Fv2PredictionError = shared.Fv1PredictionError
CaseInput = shared.CaseInput


def verify_lock(protocol_path: Path, protocol_sha256: str, fv2_directory: Path):
    validated = lock.validate_protocol_file(protocol_path, protocol_sha256)
    lock.verify_fv2_packages(fv2_directory)
    return validated


def load_cases(fv2_directory: Path) -> list[CaseInput]:
    lock.verify_fv2_packages(fv2_directory)
    rows = load_input_cases(Path(fv2_directory) / lock.FV2_INPUT_NAME)
    if [r["case_id"] for r in rows] != list(lock.CASE_IDS):
        raise Fv2PredictionError("FV2 case identity or order mismatch")
    return [CaseInput(r["case_id"], r["prepared_input"], r["context"]) for r in rows]


def qualify_credential(executor, transport, wait):
    spec = replace(shared.smoke_spec(), job_id=SMOKE_JOB_ID, research_task_id=RUNNER_ID)
    record = shared._run_job(executor, spec, transport, wait)
    raw = (record.get("first_success") or {}).get("raw_response")
    try:
        qualified = isinstance(raw, str) and json.loads(raw) == {"status": "ok"}
    except ValueError:
        qualified = False
    return {"credential_slot": lock.CREDENTIAL_SLOT, "qualified": qualified, "transport": shared._telemetry(record)}


def run_cases(cases, executor, transport, artifact_root: Path, guard, wait) -> list[dict[str, Any]]:
    """Reuse durable transport and structural validation; one primary and at most one repair."""
    if [c.case_id for c in cases] != list(lock.CASE_IDS):
        raise Fv2PredictionError("Full ordered FV2 set required")
    results = []
    for case in cases:
        attempts, batch, primary_raw, validation = [], None, None, {}
        for phase in ("primary", "repair_1"):
            guard()
            spec = (lock.build_primary_spec(case.case_id, case.prepared_input) if phase == "primary" else
                    lock.build_repair_spec(case.case_id, case.prepared_input, primary_raw,
                                           {k: validation[k] for k in ("category", "blockers")}))
            record = shared._run_job(executor, spec, transport, wait)
            raw = (record.get("first_success") or {}).get("raw_response")
            attempt = {"phase": phase, "job_id": spec.job_id, "request_fingerprint": spec.request_fingerprint,
                       "transport": shared._telemetry(record), "raw_response_sha256": None, "draft_sha256": None}
            if isinstance(raw, str):
                draft, batch, validation = shared.validate_raw(raw, case.compiler_context)
                attempt["raw_response_sha256"] = shared._write_text(artifact_root / "raw" / f"{case.case_id}_{phase}.txt", raw)
                if draft is not None:
                    attempt["draft_sha256"] = shared._write_json(artifact_root / "drafts" / f"{case.case_id}_{phase}.json", draft)
            else:
                validation = {"pass": False, "category": "TRANSPORT_FAILURE", "blockers": []}
            attempt["validation"] = validation
            attempts.append(attempt)
            if batch is not None or not isinstance(raw, str) or phase == "repair_1":
                break
            primary_raw = raw
        status = "STRUCTURAL_VALID" if batch is not None else validation["category"]
        if status not in ("STRUCTURAL_VALID", "TRANSPORT_FAILURE"):
            status = "STRUCTURAL_FAILURE"
        compiled = failure = None
        if batch is not None:
            compiled = shared._write_json(artifact_root / "compiled" / f"{case.case_id}.json", batch)
        else:
            failure = shared._write_json(artifact_root / "failures" / f"{case.case_id}.json",
                                         {"terminal_status": status, "validation": validation})
        item = {"case_id": case.case_id, "attempts": attempts, "repair_used": len(attempts) == 2,
                "terminal_status": status, "compiled_batch_sha256": compiled, "terminal_failure_sha256": failure}
        shared._write_json(artifact_root / "case_results" / f"{case.case_id}.json", item)
        results.append(item)
    return results


def prediction_identities(results) -> list[dict]:
    return [{**{k: r[k] for k in ("case_id", "terminal_status", "compiled_batch_sha256", "terminal_failure_sha256")},
             "attempts": [{k: a[k] for k in ("phase", "request_fingerprint", "raw_response_sha256", "draft_sha256")}
                          for a in r["attempts"]]} for r in results]


def summarize(results, smoke, protocol_sha256: str) -> tuple[dict, dict]:
    identities = prediction_identities(results)
    common = {"protocol_sha256": protocol_sha256, "fv2_bindings": {k: h for k, _, h in lock.package_bindings()},
              "prediction_set_sha256": lock.sha256_bytes(lock.canonical_json_bytes(identities)),
              "terminal_counts": {s: sum(r["terminal_status"] == s for r in results)
                                  for s in ("STRUCTURAL_VALID", "STRUCTURAL_FAILURE", "TRANSPORT_FAILURE")},
              "repair_count": sum(r["repair_used"] for r in results),
              "semantic_jobs": sum(len(r["attempts"]) for r in results), "fv2_gold_opened": False}
    result = {"artifact": RUNNER_ID, "completed_at_utc": shared._utc_now(), "smoke": smoke,
              "predictions": results, **common}
    manifest = {"artifact": MANIFEST_NAME[:-5], "predictions_locked": True, "entries": identities, **common}
    return result, manifest


def execute(*, protocol_path: Path, protocol_sha256: str, fv2_directory: Path, output_root: Path,
            transport=None, wait=time.sleep) -> dict:
    validated = verify_lock(protocol_path, protocol_sha256, fv2_directory)
    cases = load_cases(fv2_directory)
    output_root = Path(output_root)
    if (output_root / PREDICTION_LOCK_NAME).exists():
        raise Fv2PredictionError("Predictions already locked; rerun forbidden")

    def guard():
        validated.assert_unchanged()
        lock.validate_public_bindings(validated.value)
        lock.verify_fv2_packages(fv2_directory)

    guard()
    profile = validated.value["durable_execution"]
    pacer = PersistentRollingOperationPacer(output_root / "checkpoints/global_pacing.json",
        max_operations=profile["global_pacing_max_operations"],
        window_seconds=profile["global_pacing_rolling_window_seconds"])
    secrets = ()
    if transport is None:  # pragma: no cover - live provider branch
        from tools.story_extraction.gemini_key_pool_v1 import load_runtime_config
        from tools.story_extraction.run_m4_04b2_dev_predictions_v1 import GeminiDevWindowTransport
        config = load_runtime_config()
        selected = [c for c in config.credentials if c.slot_id == lock.CREDENTIAL_SLOT]
        if len(selected) != 1:
            raise Fv2PredictionError("Locked slot unavailable or ambiguous")
        transport = GeminiDevWindowTransport(selected[0], pacer, guard)
        secrets = tuple(c._api_key for c in config.credentials)
    executor = DurableResearchExecutor(output_root / "checkpoints/jobs",
        protocol_id=f"{lock.PROTOCOL_ID}:{protocol_sha256}",
        window_cooldown_seconds=profile["window_cooldown_seconds"], forbidden_secrets=secrets)
    smoke = qualify_credential(executor, transport, wait)
    shared._write_json(output_root / "smoke.json", smoke)
    if not smoke["qualified"]:
        raise Fv2PredictionError("Credential qualification failed")
    results = run_cases(cases, executor, transport, output_root / "artifacts", guard, wait)
    guard()
    result, manifest = summarize(results, smoke, protocol_sha256)
    result_hash = shared._write_json(output_root / RESULT_NAME, result)
    manifest_hash = shared._write_json(output_root / MANIFEST_NAME, manifest)
    # Bind every saved prediction artifact, including case_results and telemetry.
    files = {p.relative_to(output_root).as_posix(): lock.file_sha256(p)
             for p in sorted((output_root / "artifacts").rglob("*")) if p.is_file()}
    files.update({RESULT_NAME: result_hash, MANIFEST_NAME: manifest_hash})
    prediction_lock = {"artifact": PREDICTION_LOCK_NAME[:-5], "protocol_sha256": protocol_sha256,
                       "files": files, "prediction_set_sha256": manifest["prediction_set_sha256"]}
    digest = shared._write_json(output_root / PREDICTION_LOCK_NAME, prediction_lock)
    return {**result, "prediction_lock_sha256": digest}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preflight", "run"), required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--fv2-directory", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args(argv)
    try:
        verify_lock(args.protocol, args.protocol_sha256, args.fv2_directory)
        if args.mode == "preflight":
            print(json.dumps({"status": "PREFLIGHT_PASS", "cases": len(load_cases(args.fv2_directory))}))
        else:
            if args.output_root is None:
                raise Fv2PredictionError("Run requires --output-root")
            result = execute(protocol_path=args.protocol, protocol_sha256=args.protocol_sha256,
                             fv2_directory=args.fv2_directory, output_root=args.output_root)
            print(json.dumps({k: result[k] for k in ("prediction_lock_sha256", "terminal_counts")}))
        return 0
    except (OSError, ValueError, lock.Fv2ProtocolError, Fv2PredictionError, CheckpointIntegrityError):
        print("FV2 prediction refused")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
