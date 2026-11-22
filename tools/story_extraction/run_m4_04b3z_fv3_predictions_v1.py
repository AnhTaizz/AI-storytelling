"""Blind FV3 runner: preflight is offline; run requires a separately pinned protocol hash.

The runner never hashes or opens gold. Only prepared input reaches the transport.
Keep the printed prediction-lock digest independently for the offline scorer.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from tools.story_extraction import m4_04b3z_fv3_protocol_v1 as lock
from tools.story_extraction import run_m4_04b3o_fv2_predictions_v1 as fv2_runner
from tools.story_extraction import run_m4_04b3g_fv1_predictions_v1 as shared
from tools.story_extraction.durable_research_executor_v1 import (
    DurableResearchExecutor, PersistentRollingOperationPacer, CheckpointIntegrityError,
)
from tools.story_extraction.fresh_validation_seal_v1 import load_input_cases

RUNNER_ID = "M4_04B3Z_FV3_PREDICTION_RUNNER_V1"
RESULT_NAME = "M4_04B3Z_FV3_PREDICTION_RESULT_V1.json"
MANIFEST_NAME = "M4_04B3Z_FV3_PREDICTION_MANIFEST_V1.json"
PREDICTION_LOCK_NAME = "M4_04B3Z_FV3_PREDICTION_LOCK_V1.json"
SMOKE_JOB_ID = "M4B3Z_P4R8_B1K_SMOKE_" + lock.CREDENTIAL_SLOT.upper()
Fv3PredictionError = shared.Fv1PredictionError
CaseInput = shared.CaseInput


def verify_lock(protocol_path: Path, protocol_sha256: str, fv3_directory: Path):
    validated = lock.validate_protocol_file(protocol_path, protocol_sha256)
    lock.verify_fv3_packages(fv3_directory)
    return validated


def load_cases(fv3_directory: Path) -> list[CaseInput]:
    lock.verify_fv3_packages(fv3_directory)
    rows = load_input_cases(Path(fv3_directory) / lock.FV3_INPUT_NAME)
    if [r["case_id"] for r in rows] != list(lock.CASE_IDS):
        raise Fv3PredictionError("FV3 case identity or order mismatch")
    return [CaseInput(r["case_id"], r["prepared_input"], r["context"]) for r in rows]


def qualify_credential(executor, transport, wait):
    # The FV1 smoke spec carries the FV1 slot; the FV3 lock's slot must qualify.
    spec = replace(shared.smoke_spec(), job_id=SMOKE_JOB_ID, research_task_id=lock.TASK_ID,
                   credential_slot=lock.CREDENTIAL_SLOT)
    record = shared._run_job(executor, spec, transport, wait)
    raw = (record.get("first_success") or {}).get("raw_response")
    try:
        qualified = isinstance(raw, str) and json.loads(raw) == {"status": "ok"}
    except ValueError:
        qualified = False
    return {"credential_slot": lock.CREDENTIAL_SLOT, "qualified": qualified, "transport": shared._telemetry(record)}


def run_cases(cases, executor, transport, artifact_root: Path, guard, wait, *,
              validated: lock.ValidatedProtocol) -> list[dict[str, Any]]:
    """Reuse durable transport and structural validation; one primary and at most one repair."""
    if [c.case_id for c in cases] != list(lock.CASE_IDS):
        raise Fv3PredictionError("Full ordered FV3 set required")
    repairs = tuple(validated.value["host_repairs"])
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
                _, draft, batch, validation = lock.dev.validate_attempt(
                    raw, case, quote_resolution="QR" in repairs, anchor_mentions="AM" in repairs,
                    mention_evidence="ME" in repairs,
                    mention_evidence_predicates=tuple(validated.value["mention_evidence_predicates"]),
                    sentence_evidence="SE" in repairs, transfer_bounds="TB" in repairs,
                    date_anchor="DA" in repairs, vocabulary_guard="VG" in repairs)
                attempt["raw_response_sha256"] = shared._write_text(artifact_root / "raw" / f"{case.case_id}_{phase}.txt", raw)
                if draft is not None:
                    attempt["draft_sha256"] = shared._write_json(artifact_root / "drafts" / f"{case.case_id}_{phase}.json", draft)
            else:
                validation = {"pass": False, "category": "TRANSPORT_FAILURE", "blockers": []}
            reports = ("quote_resolution", "mention_anchoring", "mention_evidence", "sentence_evidence",
                       "transfer_bounds", "date_anchor", "vocabulary_guard")
            attempt["host_repairs"] = [code for code, key in zip(lock.HOST_REPAIRS, reports, strict=True)
                                       if key in validation]
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
        item = {"case_id": case.case_id, "host_repairs": list(repairs),
                "attempts": attempts, "repair_used": len(attempts) == 2,
                "terminal_status": status, "compiled_batch_sha256": compiled, "terminal_failure_sha256": failure}
        shared._write_json(artifact_root / "case_results" / f"{case.case_id}.json", item)
        results.append(item)
    return results


def prediction_identities(results) -> list[dict]:
    identities = fv2_runner.prediction_identities(results)
    for identity, result in zip(identities, results, strict=True):
        for entry, attempt in zip(identity["attempts"], result["attempts"], strict=True):
            entry["host_repairs"] = attempt["host_repairs"]
    return identities


def summarize(results, smoke, protocol_sha256: str, *, host_repairs) -> tuple[dict, dict]:
    identities = prediction_identities(results)
    common = {"protocol_sha256": protocol_sha256, "host_repairs": list(host_repairs),
              "fv3_bindings": {k: h for k, _, h in lock.package_bindings()},
              "prediction_set_sha256": lock.sha256_bytes(lock.canonical_json_bytes(identities)),
              "terminal_counts": {s: sum(r["terminal_status"] == s for r in results)
                                  for s in ("STRUCTURAL_VALID", "STRUCTURAL_FAILURE", "TRANSPORT_FAILURE")},
              "repair_count": sum(r["repair_used"] for r in results),
              "semantic_jobs": sum(len(r["attempts"]) for r in results), "fv3_gold_opened": False}
    result = {"artifact": RUNNER_ID, "completed_at_utc": shared._utc_now(), "smoke": smoke,
              "predictions": results, **common}
    manifest = {"artifact": MANIFEST_NAME[:-5], "predictions_locked": True, "entries": identities, **common}
    return result, manifest


def execute(*, protocol_path: Path, protocol_sha256: str, fv3_directory: Path, output_root: Path,
            transport=None, wait=time.sleep) -> dict:
    # Durable checkpoints support restarts, but two processes cannot share a job.
    # An OS-backed SQLite lock is released even if the running process crashes.
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(output_root / "run-ownership.sqlite", timeout=0)) as ownership:
        try:
            ownership.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:
            raise Fv3PredictionError("Cannot acquire exclusive prediction directory") from exc
        return _execute_locked(protocol_path, protocol_sha256, fv3_directory, output_root, transport, wait)


def _execute_locked(protocol_path, protocol_sha256, fv3_directory, output_root, transport, wait):
    if (output_root / PREDICTION_LOCK_NAME).exists():
        raise Fv3PredictionError("Predictions already locked; rerun forbidden")

    validated = verify_lock(protocol_path, protocol_sha256, fv3_directory)
    cases = load_cases(fv3_directory)

    def guard():
        validated.assert_unchanged()
        lock.validate_public_bindings(validated.value)
        lock.verify_fv3_packages(fv3_directory)

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
            raise Fv3PredictionError("Locked slot unavailable or ambiguous")
        transport = GeminiDevWindowTransport(selected[0], pacer, guard)
        secrets = tuple(c._api_key for c in config.credentials)
    executor = DurableResearchExecutor(output_root / "checkpoints/jobs",
        protocol_id=f"{lock.PROTOCOL_ID}:{protocol_sha256}",
        window_cooldown_seconds=profile["window_cooldown_seconds"], forbidden_secrets=secrets)
    smoke = qualify_credential(executor, transport, wait)
    shared._write_json(output_root / "smoke.json", smoke)
    if not smoke["qualified"]:
        raise Fv3PredictionError("Credential qualification failed")
    results = run_cases(cases, executor, transport, output_root / "artifacts", guard, wait, validated=validated)
    guard()
    result, manifest = summarize(results, smoke, protocol_sha256,
                                 host_repairs=validated.value["host_repairs"])
    result_hash = shared._write_json(output_root / RESULT_NAME, result)
    manifest_hash = shared._write_json(output_root / MANIFEST_NAME, manifest)
    # Bind every saved prediction artifact, including case_results and telemetry.
    files = {p.relative_to(output_root).as_posix(): lock.file_sha256(p)
             for p in sorted((output_root / "artifacts").rglob("*")) if p.is_file()}
    files.update({RESULT_NAME: result_hash, MANIFEST_NAME: manifest_hash})
    prediction_lock = {"artifact": PREDICTION_LOCK_NAME[:-5], "protocol_sha256": protocol_sha256,
                       "files": files, "prediction_set_sha256": manifest["prediction_set_sha256"]}
    digest = lock.sha256_bytes(lock.canonical_json_bytes(prediction_lock))
    (output_root / (PREDICTION_LOCK_NAME + ".sha256")).write_bytes((digest + "\n").encode("ascii"))
    shared._write_json(output_root / PREDICTION_LOCK_NAME, prediction_lock)
    return {**result, "prediction_lock_sha256": digest}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preflight", "run"), required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--fv3-dir", dest="fv3_directory", type=Path, required=True)
    parser.add_argument("--out", dest="output_root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.mode == "preflight":
            verify_lock(args.protocol, args.protocol_sha256, args.fv3_directory)
            print(json.dumps({"status": "PREFLIGHT_PASS", "cases": len(load_cases(args.fv3_directory))}))
        else:
            if args.output_root is None:
                raise Fv3PredictionError("Run requires --out")
            result = execute(protocol_path=args.protocol, protocol_sha256=args.protocol_sha256,
                             fv3_directory=args.fv3_directory, output_root=args.output_root)
            print(json.dumps({k: result[k] for k in ("prediction_lock_sha256", "terminal_counts")}))
        return 0
    except (OSError, ValueError, lock.Fv3ProtocolError, Fv3PredictionError, CheckpointIntegrityError):
        print("FV3 prediction refused")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
