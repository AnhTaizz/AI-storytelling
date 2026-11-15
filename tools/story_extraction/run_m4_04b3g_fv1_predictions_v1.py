"""M4-04B3G: run the locked P3 Draft V1.1 extractor on Fresh Validation V1, blind.

Bound to the M4-04B3F lock (`m4_04b3f_fv1_protocol_v1`): requests come only from
`build_primary_spec` / `build_repair_spec`, the model sees only each case's
`prepared_draft_input.json`, and the runner has no gold path, evaluator or scorer.

Order of work, each step fail-closed:
1. the private protocol must hash to the lock and validate; the FV1 input package and the
   blindness manifest must hash to the seal; prompt material must be unchanged;
2. one M4-04B1K smoke call qualifies the locked credential slot, or the run stops;
3. FV1_01..FV1_10 in order: one primary job each, and at most one structural repair
   (JSON, schema or compiler blockers only, as phase/code/path) — at most 20 semantic jobs;
4. raw responses, drafts, compiled batches and terminal failures are written to the private
   artifact root; the result and a prediction manifest (hashes only) lock the predictions.

    python -m tools.story_extraction.run_m4_04b3g_fv1_predictions_v1 --mode preflight|run \
        --protocol P --protocol-validation V --fv1-directory D [--output-root O]
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from tools.story_extraction.draft_compiler_v1 import DraftCompilationError, DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import (
    DraftCompilationErrorV1_1,
    collect_draft_structural_blockers_v1_1,
    compile_story_extraction_draft_v1_1,
    validate_draft_v1_1,
)
from tools.story_extraction.durable_research_executor_v1 import (
    CheckpointIntegrityError,
    DurableJobSpec,
    DurableResearchExecutor,
    PersistentRollingOperationPacer,
)
from tools.story_extraction import m4_04b3f_fv1_protocol_v1 as lock
from tools.story_extraction.run_gemini_resilience_smoke_v1_1 import (
    OUTPUT_TOKEN_CAP as SMOKE_OUTPUT_TOKEN_CAP,
    SYSTEM_INSTRUCTION as SMOKE_SYSTEM,
    USER_CONTENT as SMOKE_USER,
)

RUNNER_ID = "M4_04B3G_FV1_PREDICTION_RUNNER_V1"
TASK_ID = "M4-04B3G-BLIND-FV1-PREDICTION-AND-LOCK"
RESULT_ID = "M4_04B3G_FV1_PREDICTION_RESULT_V1"
MANIFEST_ID = "M4_04B3G_FV1_PREDICTION_MANIFEST_V1"
LOCK_COMMIT = "11a6ac622405709c0729b8ddf22cb4b7af91ce18"
LOCKED_PROTOCOL_SHA256 = "b33d2c4d2ca9e1d6a482789b330ba151cd46c836c527b8245499586caa3c243a"
LOCKED_VALIDATION_SHA256 = "2ee8633539990472df4d69d21d6ab916df5232077f5ab287a3a6740e3564d638"
MAX_SEMANTIC_JOBS = len(lock.CASE_IDS) * 2
SMOKE_JOB_ID = "M4B3G_B1K_SMOKE_" + lock.CREDENTIAL_SLOT.upper()

Transport = Callable[[DurableJobSpec, int, str], Mapping[str, Any]]


class Fv1PredictionError(RuntimeError):
    """A fail-closed lock, input or execution error; never carries private text."""


@dataclass(frozen=True)
class CaseInput:
    case_id: str
    prepared_input: Mapping[str, Any]
    compiler_context: DraftCompilerContext


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> str:
    """Write canonical JSON atomically and return its sha256."""
    payload = lock.canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)
    return lock.sha256_bytes(payload)


def _write_text(path: Path, value: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value.encode("utf-8"))
    return lock.sha256_text(value)


# --------------------------------------------------------------------------- lock and input

def verify_lock(protocol_path: Path, validation_path: Path, fv1_directory: Path) -> lock.ValidatedProtocol:
    """The protocol, its validation record, the public bindings and the FV1 input/manifest
    hashes must all match the M4-04B3F lock before anything else happens."""
    validated = lock.validate_protocol_file(protocol_path, LOCKED_PROTOCOL_SHA256)
    if _sha256_file(validation_path) != LOCKED_VALIDATION_SHA256:
        raise Fv1PredictionError("Protocol validation record hash mismatch")
    if lock.prompt_hashes() != validated.value["prompt_hashes"]:
        raise Fv1PredictionError("Locked prompt material changed")
    lock.verify_fv1_packages(fv1_directory)
    return validated


def load_cases(fv1_directory: Path) -> list[CaseInput]:
    """The FV1 cases from the sealed input package (never the gold package)."""
    from tools.story_extraction.fresh_validation_seal_v1 import load_input_cases

    path = Path(fv1_directory) / lock.FV1_INPUT_NAME
    if _sha256_file(path) != lock.FV1_INPUT_SHA256:
        raise Fv1PredictionError("FV1 input package hash mismatch")
    rows = load_input_cases(path)
    if [row["case_id"] for row in rows] != list(lock.CASE_IDS):
        raise Fv1PredictionError("FV1 case identity or order mismatch")
    return [CaseInput(row["case_id"], row["prepared_input"], row["context"]) for row in rows]


# --------------------------------------------------------------------------- validation

def _blockers(error: DraftCompilationError, phase: str) -> list[dict[str, str]]:
    if isinstance(error, DraftCompilationErrorV1_1):
        return [blocker.as_dict() for blocker in error.blockers]
    return [{"phase": phase, "code": error.code, "path": error.path}]


def validate_raw(raw: str, context: DraftCompilerContext) -> tuple[Any, Optional[dict], dict[str, Any]]:
    """(draft, compiled batch, validation). A failure carries every structural blocker as
    phase/code/path, never a value from the draft or the source."""
    try:
        draft = json.loads(raw)
    except json.JSONDecodeError:
        return None, None, {"pass": False, "category": "JSON_PARSE_FAILURE",
                            "blockers": [{"phase": "JSON", "code": "INVALID_JSON", "path": ""}]}
    try:
        validate_draft_v1_1(draft)
    except DraftCompilationError as error:
        return draft, None, {"pass": False, "category": "DRAFT_SCHEMA_FAILURE",
                             "blockers": _blockers(error, "SCHEMA")}
    blockers = collect_draft_structural_blockers_v1_1(draft, context)
    if blockers:
        return draft, None, {"pass": False, "category": "DRAFT_COMPILER_FAILURE",
                             "blockers": [b.as_dict() for b in blockers]}
    try:
        batch = compile_story_extraction_draft_v1_1(draft, context)
    except DraftCompilationError as error:
        return draft, None, {"pass": False, "category": "DRAFT_COMPILER_FAILURE",
                             "blockers": _blockers(error, "CANONICAL_COMPILER")}
    return draft, batch, {"pass": True, "category": None, "blockers": []}


# --------------------------------------------------------------------------- execution

def _run_job(executor: DurableResearchExecutor, spec: DurableJobSpec, transport: Transport,
             wait: Callable[[float], None]) -> dict[str, Any]:
    from tools.story_extraction.durable_research_executor_v1 import CooldownPending, JobState

    executor.ensure_job(spec)
    while True:
        record = executor.load_job(spec)
        if JobState(record["state"]) in {JobState.SUCCEEDED_LOCKED, JobState.TERMINAL_FAILED}:
            return record
        try:
            executor.execute_window(spec, transport)
        except CooldownPending as pending:
            wait(max(0.001, pending.remaining_seconds))


def _telemetry(record: Mapping[str, Any]) -> dict[str, Any]:
    first = record.get("first_success") or {}
    return {"state": record.get("state"), "windows": record.get("window_count"),
            "provider_operations": record.get("total_provider_operations"),
            "terminal_failure_category": record.get("terminal_failure_category"),
            "usage": first.get("usage") or {}}


def smoke_spec() -> DurableJobSpec:
    return DurableJobSpec(
        job_id=SMOKE_JOB_ID, model=lock.MODEL, system_prompt=SMOKE_SYSTEM, user_prompt=SMOKE_USER,
        generation_config={"temperature": 0, "max_output_tokens": SMOKE_OUTPUT_TOKEN_CAP},
        schema_response_mode="PROVIDER_JSON_MIME_SMOKE", credential_slot=lock.CREDENTIAL_SLOT,
        research_task_id=TASK_ID)


def qualify_credential(executor: DurableResearchExecutor, transport: Transport,
                       wait: Callable[[float], None] = lambda s: None) -> dict[str, Any]:
    """The one M4-04B1K smoke call: the slot qualifies only on exactly {"status":"ok"}."""
    record = _run_job(executor, smoke_spec(), transport, wait)
    raw = (record.get("first_success") or {}).get("raw_response")
    try:
        qualified = isinstance(raw, str) and json.loads(raw) == {"status": "ok"}
    except json.JSONDecodeError:
        qualified = False
    return {"credential_slot": lock.CREDENTIAL_SLOT, "model": lock.MODEL, "qualified": qualified,
            "transport": _telemetry(record)}


def run_cases(cases: Sequence[CaseInput], executor: DurableResearchExecutor, transport: Transport,
              artifact_root: Path, guard: Callable[[], None] = lambda: None,
              wait: Callable[[float], None] = lambda s: None) -> list[dict[str, Any]]:
    """Primary job per case in order, plus at most one structural repair."""
    results: list[dict[str, Any]] = []
    semantic_jobs = 0
    for case in cases:
        guard()
        attempts: list[dict[str, Any]] = []
        validation: dict[str, Any] = {}
        batch = None
        primary_raw = None
        for phase in ("primary", "repair_1"):
            if phase == "primary":
                spec = lock.build_primary_spec(case.case_id, case.prepared_input)
            else:
                spec = lock.build_repair_spec(case.case_id, case.prepared_input, primary_raw,
                                              {"category": validation["category"],
                                               "blockers": validation["blockers"]})
            semantic_jobs += 1
            if semantic_jobs > MAX_SEMANTIC_JOBS:
                raise Fv1PredictionError("Semantic job budget exceeded")
            record = _run_job(executor, spec, transport, wait)
            raw = (record.get("first_success") or {}).get("raw_response")
            attempt = {"phase": phase, "job_id": spec.job_id, "request_fingerprint": spec.request_fingerprint,
                       "transport": _telemetry(record), "raw_response_sha256": None, "draft_sha256": None}
            if not isinstance(raw, str):
                validation = {"pass": False, "category": f"{phase.upper()}_TRANSPORT_FAILURE",
                              "blockers": []}
                attempt["validation"] = validation
                attempts.append(attempt)
                break
            draft, batch, validation = validate_raw(raw, case.compiler_context)
            attempt["raw_response_sha256"] = _write_text(artifact_root / "raw" / f"{case.case_id}_{phase}.txt", raw)
            if draft is not None:
                attempt["draft_sha256"] = _write_json(artifact_root / "drafts" / f"{case.case_id}_{phase}.json", draft)
            attempt["validation"] = validation
            attempts.append(attempt)
            if validation["pass"] or phase == "repair_1":
                break
            primary_raw = raw  # eligible: a successful primary response failed structurally
        if batch is not None:
            status = "STRUCTURAL_VALID"
            compiled = _write_json(artifact_root / "compiled" / f"{case.case_id}.json", batch)
            failure = None
        else:
            status = ("TRANSPORT_FAILURE" if validation.get("category", "").endswith("TRANSPORT_FAILURE")
                      and len(attempts) == 1 else "STRUCTURAL_FAILURE")
            compiled = None
            failure = _write_json(artifact_root / "failures" / f"{case.case_id}.json",
                                  {"case_id": case.case_id, "terminal_status": status, "validation": validation})
        item = {"case_id": case.case_id, "attempts": attempts, "repair_used": len(attempts) > 1,
                "terminal_status": status, "compiled_batch_sha256": compiled, "terminal_failure_sha256": failure}
        _write_json(artifact_root / "case_results" / f"{case.case_id}.json", item)
        results.append(item)
        print(json.dumps({"case_id": case.case_id, "repair_used": item["repair_used"], "terminal_status": status},
                         sort_keys=True), flush=True)
    return results


def summarize(results: Sequence[Mapping[str, Any]], smoke: Mapping[str, Any]) -> tuple[dict, dict]:
    """The private result and the hash-only prediction manifest that locks the predictions."""
    identities = [{"case_id": r["case_id"], "terminal_status": r["terminal_status"],
                   "compiled_batch_sha256": r["compiled_batch_sha256"],
                   "terminal_failure_sha256": r["terminal_failure_sha256"],
                   "attempts": [{key: a[key] for key in ("phase", "request_fingerprint", "raw_response_sha256",
                                                          "draft_sha256")} for a in r["attempts"]]}
                  for r in results]
    usage: dict[str, int] = {}
    for result in [smoke, *(a for r in results for a in r["attempts"])]:
        for key, value in ((result.get("transport") or {}).get("usage") or {}).items():
            if isinstance(value, int):
                usage[key] = usage.get(key, 0) + value
    counts = {status: sum(r["terminal_status"] == status for r in results)
              for status in ("STRUCTURAL_VALID", "STRUCTURAL_FAILURE", "TRANSPORT_FAILURE")}
    common = {
        "protocol_lock_commit": LOCK_COMMIT, "protocol_sha256": LOCKED_PROTOCOL_SHA256,
        "fv1_input_sha256": lock.FV1_INPUT_SHA256, "fv1_blindness_manifest_sha256": lock.FV1_MANIFEST_SHA256,
        "model": lock.MODEL, "credential_slot": lock.CREDENTIAL_SLOT,
        "case_order": [r["case_id"] for r in results],
        "prediction_set_sha256": lock.sha256_bytes(lock.canonical_json_bytes(identities)),
        "terminal_counts": counts, "repair_count": sum(r["repair_used"] for r in results),
        "semantic_jobs": sum(len(r["attempts"]) for r in results),
        "provider_operations": sum((a["transport"].get("provider_operations") or 0)
                                   for r in results for a in r["attempts"]),
        "smoke_provider_operations": (smoke.get("transport") or {}).get("provider_operations"),
        "usage_totals": usage,
        "fv1_gold_opened": False, "dev2_gold_opened": False, "holdout_accessed": False, "scoring_performed": False,
    }
    result = {"artifact": RESULT_ID, "task_id": TASK_ID, "runner_id": RUNNER_ID, "completed_at_utc": _utc_now(),
              "smoke": dict(smoke), "predictions": list(results), **common}
    manifest = {"artifact": MANIFEST_ID, "entries": identities, "predictions_locked": True, **common}
    return result, manifest


def execute(*, protocol_path: Path, validation_path: Path, fv1_directory: Path, output_root: Path,
            transport: Optional[Transport] = None, wait: Optional[Callable[[float], None]] = None,
            forbidden_secrets: Sequence[str] = ()) -> dict[str, Any]:
    """Verify the lock, qualify the credential, run FV1 blind, write result and manifest.
    `transport` defaults to the accepted Gemini V1.1 transport on the locked slot."""
    import time

    validated = verify_lock(protocol_path, validation_path, fv1_directory)
    cases = load_cases(fv1_directory)

    def guard() -> None:
        validated.assert_unchanged()
        lock.validate_public_bindings()
        if lock.prompt_hashes() != validated.value["prompt_hashes"]:
            raise CheckpointIntegrityError("Locked prompt material changed")
        if _sha256_file(Path(fv1_directory) / lock.FV1_INPUT_NAME) != lock.FV1_INPUT_SHA256:
            raise CheckpointIntegrityError("FV1 input package changed")

    guard()
    pacer = PersistentRollingOperationPacer(output_root / "checkpoints" / "global_pacing.json",
                                            max_operations=lock.GLOBAL_MAX_PROVIDER_OPERATIONS,
                                            window_seconds=lock.GLOBAL_ROLLING_WINDOW_SECONDS)
    if transport is None:  # pragma: no cover - live provider path
        from tools.story_extraction.gemini_key_pool_v1 import load_runtime_config
        from tools.story_extraction.run_m4_04b2_dev_predictions_v1 import GeminiDevWindowTransport

        config = load_runtime_config()
        selected = [item for item in config.credentials if item.slot_id == lock.CREDENTIAL_SLOT]
        if len(selected) != 1:
            raise Fv1PredictionError("Locked credential slot is unavailable or ambiguous")
        transport = GeminiDevWindowTransport(selected[0], pacer, guard)
        forbidden_secrets = tuple(item._api_key for item in config.credentials)
    executor = DurableResearchExecutor(output_root / "checkpoints" / "jobs",
                                       protocol_id=f"{lock.PROTOCOL_ID}:{LOCKED_PROTOCOL_SHA256}",
                                       window_cooldown_seconds=lock.WINDOW_COOLDOWN_SECONDS,
                                       forbidden_secrets=tuple(forbidden_secrets))
    wait = wait or time.sleep
    smoke = qualify_credential(executor, transport, wait)
    _write_json(output_root / "smoke.json", smoke)
    if not smoke["qualified"]:
        raise Fv1PredictionError("Credential slot did not qualify; a new task is required")
    results = run_cases(cases, executor, transport, output_root / "artifacts", guard, wait)
    guard()
    result, manifest = summarize(results, smoke)
    _write_json(output_root / "M4_04B3G_FV1_PREDICTION_RESULT_V1.json", result)
    manifest_sha = _write_json(output_root / "M4_04B3G_FV1_PREDICTION_MANIFEST_V1.json", manifest)
    result["prediction_manifest_sha256"] = manifest_sha
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("preflight", "run"), required=True)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--protocol-validation", required=True, type=Path)
    parser.add_argument("--fv1-directory", required=True, type=Path)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args(argv)
    try:
        verify_lock(args.protocol, args.protocol_validation, args.fv1_directory)
        if args.mode == "preflight":
            cases = load_cases(args.fv1_directory)
            print(json.dumps({"cases": len(cases), "status": "PREFLIGHT_PASS"}, sort_keys=True))
            return 0
        if args.output_root is None:
            raise Fv1PredictionError("Run mode requires --output-root")
        result = execute(protocol_path=args.protocol, validation_path=args.protocol_validation,
                         fv1_directory=args.fv1_directory, output_root=args.output_root)
        print(json.dumps({key: result[key] for key in ("prediction_set_sha256", "terminal_counts", "repair_count",
                                                       "semantic_jobs", "prediction_manifest_sha256")},
                         sort_keys=True))
    except (Fv1PredictionError, lock.Fv1ProtocolError, CheckpointIntegrityError) as error:
        print(f"M4_04B3G_STOPPED: {type(error).__name__}: {error}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
