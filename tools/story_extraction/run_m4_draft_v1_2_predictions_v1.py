"""Offline runner for the P4 STORY_EXTRACTION_DRAFT_V1_2 candidate.

Live execution is disabled in this version: ``execute`` accepts only transports that
subclass ``OfflineTransport`` and refuses anything else, whatever the caller passes. No
live transport factory exists here. A later, separately authorized runner version may
add one.

Model drafts (durable provider jobs) are kept separate from deterministic compilation
(``draft_compiler_v1_2``). Every started case leaves a case-status artifact, including
cases interrupted by the budget, provider drift or a runner error. The runner is serial
by design; the reused diagnostics observer is not safe for concurrent compilation.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Optional

from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_2 import (
    DRAFT_VERSION,
    DraftCompilationErrorV1_2,
    compile_story_extraction_draft_v1_2,
    prepare_story_extraction_draft_v1_2,
)
from tools.story_extraction.durable_research_executor_v1 import (
    DurableJobSpec,
    DurableResearchExecutor,
    JobState,
    summarize_job,
)
from tools.story_extraction.m4_draft_v1_2_candidate_p4_v1 import (
    CANDIDATE_ID,
    CASE_ID_PATTERN,
    MAX_PROVIDER_ATTEMPTS_PER_JOB,
    MAX_STRUCTURAL_REPAIRS_PER_CASE,
    MODEL,
    REPAIR_ELIGIBLE_CATEGORIES,
    WINDOW_COOLDOWN_SECONDS,
    CandidateError,
    build_primary_spec,
    build_repair_spec,
    candidate_definition,
    candidate_definition_sha256,
    canonical_json_bytes,
    environment_observed,
    estimated_job_tokens,
    sha256_bytes,
)
from tools.story_extraction.run_m4_draft_v1_1_predictions_v1 import (
    FORBIDDEN_PATH_MARKERS,
    INPUT_MANIFEST,
    _execute_to_terminal,
    _member_path,
    _read_json_member,
    _sha256_file,
    _write_bytes_atomic,
    _write_json,
    guard_path,
    verify_input_archive,
)
from tools.story_ingestion.light_novel_adapter_v0 import ingest_manifest_file


RUNNER_ID = "M4_DRAFT_V1_2_PREDICTION_RUNNER_V1"
RESULT_ID = "M4_DRAFT_V1_2_PREDICTION_RESULT_V1"
PREDICTION_MANIFEST_ID = "M4_DRAFT_V1_2_PREDICTION_MANIFEST_V1"


class RunnerError(RuntimeError):
    """Fail-closed input, lock or execution error carrying no private text."""


class LiveExecutionNotEnabled(RunnerError):
    """A non-offline transport was supplied; this runner version cannot run live."""


class _Stop(RuntimeError):
    """Pre-registered stop: budget insufficient or provider drift."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class OfflineTransport:
    """Base class for scripted or replay transports that never contact a provider."""

    offline = True

    def __call__(self, spec: DurableJobSpec, window: int, request_id: str) -> Mapping[str, Any]:
        raise NotImplementedError


def validate_candidate_lock(path: Path, expected_sha256: str) -> dict[str, Any]:
    guard_path(path)
    try:
        locked = path.read_bytes()
        value = json.loads(locked.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RunnerError("Candidate lock is missing or invalid") from error
    if sha256_bytes(locked) != expected_sha256 or locked != canonical_json_bytes(value):
        raise RunnerError("Candidate lock hash or canonical form mismatch")
    if value != candidate_definition():
        raise RunnerError("Candidate lock differs from the current candidate definition")
    return value


def process_version() -> str:
    return "p4v12-" + candidate_definition_sha256()[:16]


class CaseInput:
    def __init__(self, case_id: str, prepared_input: Mapping[str, Any],
                 context: DraftCompilerContext) -> None:
        self.case_id, self.prepared_input, self.context = case_id, prepared_input, context


def load_case_inputs(archive: Path, input_root: Path,
                     expected_sha256: str) -> tuple[str, list[CaseInput]]:
    manifest = verify_input_archive(archive, input_root, expected_sha256)
    dataset_id, rows = manifest.get("artifact"), manifest.get("cases")
    if (not isinstance(dataset_id, str)
            or any(marker in dataset_id.lower() for marker in FORBIDDEN_PATH_MARKERS)
            or manifest.get("draft_interface") != DRAFT_VERSION
            or not isinstance(rows, list) or not rows
            or manifest.get("case_count") != len(rows)):
        raise RunnerError("Input manifest identity mismatch")
    ids = [row.get("case_id") for row in rows]
    if len(set(ids)) != len(ids) or not all(
            isinstance(item, str) and CASE_ID_PATTERN.fullmatch(item) for item in ids):
        raise RunnerError("Input case ids are invalid")
    version, loaded = process_version(), []
    for row in rows:
        case_id = row["case_id"]
        base = _read_json_member(input_root, row["base_document_member"])
        prepared = _read_json_member(input_root, row["prepared_input_member"])
        manifest_path = _member_path(input_root, row["m3_manifest_member"])
        context = DraftCompilerContext(
            base, row["passage_inputs"], row["as_of_position"], row["profile_id"],
            CANDIDATE_ID, version, f"P4V12_{case_id}",
            ingest_manifest_file(manifest_path, manifest_path.parent))
        if prepare_story_extraction_draft_v1_2(context) != prepared:
            raise RunnerError("Prepared Draft V1.2 input does not reproduce exactly")
        loaded.append(CaseInput(case_id, prepared, context))
    return dataset_id, loaded


def compile_attempt(raw: str, case: CaseInput) -> tuple[Any, Optional[dict], dict[str, Any]]:
    """Parse and compile one response; reports locator outcomes separately."""
    try:
        draft = json.loads(raw)
    except json.JSONDecodeError:
        return None, None, {"pass": False, "category": "JSON_PARSE_FAILURE",
                            "blockers": [{"phase": "JSON", "code": "INVALID_JSON", "path": ""}],
                            "locator_counts": {}, "declared_unresolved": [],
                            "canonical_issue_classes": []}
    try:
        batch, report = compile_story_extraction_draft_v1_2(draft, case.context)
    except DraftCompilationErrorV1_2 as error:
        blockers = [item.as_dict() for item in error.blockers]
        schema = any(item["phase"] == "SCHEMA" for item in blockers)
        invariant = any(item["phase"] == "POST_INVARIANT" for item in blockers)
        return draft, None, {
            "pass": False,
            "category": ("DETERMINISTIC_INVARIANT_FAILURE" if invariant else
                         "DRAFT_SCHEMA_FAILURE" if schema else "DRAFT_COMPILER_FAILURE"),
            "blockers": blockers,
            "locator_counts": error.report.get("counts", {}),
            "declared_unresolved": error.report.get("declared_unresolved", []),
            "canonical_issue_classes": error.report.get("canonical_issue_classes", []),
        }
    except Exception:
        return draft, None, {"pass": False, "category": "COMPILER_INTERNAL_EXCEPTION",
                             "blockers": [], "locator_counts": {}, "declared_unresolved": [],
                             "canonical_issue_classes": []}
    again, _ = compile_story_extraction_draft_v1_2(deepcopy(draft), case.context)
    if canonical_json_bytes(again) != canonical_json_bytes(batch):
        raise RunnerError("NONDETERMINISTIC_COMPILATION")
    return draft, batch, {"pass": True, "category": None, "blockers": [],
                          "locator_counts": report["counts"],
                          "declared_unresolved": report["declared_unresolved"],
                          "advisories": report["advisories"], "canonical_issue_classes": []}


def repair_feedback(validation: Mapping[str, Any]) -> dict[str, Any]:
    return {"category": validation["category"],
            "blockers": list(validation.get("blockers", [])),
            "canonical_issue_classes": list(validation.get("canonical_issue_classes", []))}


class Ledger:
    """Provider operations, tokens and reported model versions; fail-closed budget."""

    def __init__(self, max_operations: int, max_tokens: int) -> None:
        self.max_operations, self.max_tokens = max_operations, max_tokens
        self.operations = 0
        self.tokens: Counter = Counter()
        self.versions: set[str] = set()
        self.counted: set[str] = set()

    def admit(self, spec: DurableJobSpec) -> None:
        if self.operations + MAX_PROVIDER_ATTEMPTS_PER_JOB > self.max_operations:
            raise _Stop("BUDGET_INSUFFICIENT_PROVIDER_OPERATIONS")
        if self.tokens["total_token_count"] + estimated_job_tokens(spec) > self.max_tokens:
            raise _Stop("BUDGET_INSUFFICIENT_TOKENS")

    def record(self, record: Mapping[str, Any]) -> dict[str, Any]:
        summary = summarize_job(record)
        if record["job_id"] not in self.counted:
            self.counted.add(record["job_id"])
            self.operations += int(record["total_provider_operations"])
            usage = (record.get("first_success") or {}).get("usage") or {}
            for key, value in usage.items():
                if isinstance(value, int):
                    self.tokens[key] += value
            if summary.get("model_reported_version"):
                self.versions.add(str(summary["model_reported_version"]))
        summary["usage"] = (record.get("first_success") or {}).get("usage") or {}
        if len(self.versions) > 1:
            raise _Stop("PROVIDER_REPORTED_MODEL_VERSION_CHANGED")
        return summary

    def snapshot(self) -> dict[str, Any]:
        return {"provider_operations": self.operations,
                "max_provider_operations": self.max_operations,
                "tokens": dict(sorted(self.tokens.items())), "max_total_tokens": self.max_tokens,
                "provider_reported_model_versions": sorted(self.versions)}


def _attempt(state: dict[str, Any], key: str, spec: DurableJobSpec, *, executor, transport,
             ledger: Ledger, sleep, artifact_root: Path, case: CaseInput, phase: str):
    entry: dict[str, Any] = {"job_id": spec.job_id, "request_fingerprint": spec.request_fingerprint,
                             "transport": None, "raw_response_sha256": None,
                             "draft_sha256": None, "validation": None}
    state[key] = entry
    existing = executor.ensure_job(spec)
    if JobState(existing["state"]) not in {JobState.SUCCEEDED_LOCKED, JobState.TERMINAL_FAILED}:
        ledger.admit(spec)
    record = _execute_to_terminal(executor, spec, transport, sleep)
    entry["transport"] = ledger.record(record)
    raw = (record.get("first_success") or {}).get("raw_response")
    if not isinstance(raw, str):
        entry["validation"] = {"pass": False, "category": "TRANSPORT_FAILURE",
                               "code": record.get("terminal_failure_category") or record["state"]}
        return None, None
    draft, batch, validation = compile_attempt(raw, case)
    raw_bytes = raw.encode("utf-8")
    _write_bytes_atomic(artifact_root / "raw" / f"{case.case_id}_{phase}.txt", raw_bytes)
    entry["raw_response_sha256"] = sha256_bytes(raw_bytes)
    if draft is not None:
        entry["draft_sha256"] = _write_json(artifact_root / "drafts" / f"{case.case_id}_{phase}.json",
                                            draft)
    entry["validation"] = validation
    return raw, batch


def _terminal_for(validation: Mapping[str, Any], batch: Optional[dict]) -> str:
    if batch is not None:
        declared = validation.get("locator_counts", {}).get("declared_unresolved", 0)
        return "STRUCTURAL_VALID_WITH_DECLARED_UNRESOLVED" if declared else "STRUCTURAL_VALID"
    if validation["category"] in {"COMPILER_INTERNAL_EXCEPTION",
                                  "DETERMINISTIC_INVARIANT_FAILURE"}:
        return "DETERMINISTIC_DEFECT_SUSPECTED"
    return "STRUCTURAL_FAILURE"


def run_case(case: CaseInput, state: dict[str, Any], *, executor, transport, ledger, sleep,
             artifact_root: Path, research_task_id: str) -> None:
    common = dict(executor=executor, transport=transport, ledger=ledger, sleep=sleep,
                  artifact_root=artifact_root, case=case)
    primary_spec = build_primary_spec(case.case_id, case.prepared_input, research_task_id)
    primary_raw, batch = _attempt(state, "primary", primary_spec, phase="primary", **common)
    validation = state["primary"]["validation"]
    if primary_raw is None:
        state["terminal_status"] = "NOT_EVALUATED_TRANSPORT"
    elif batch is None and validation["category"] in REPAIR_ELIGIBLE_CATEGORIES \
            and MAX_STRUCTURAL_REPAIRS_PER_CASE >= 1:
        repair_spec = build_repair_spec(case.case_id, case.prepared_input, primary_raw,
                                        repair_feedback(validation), research_task_id)
        repair_raw, batch = _attempt(state, "repair", repair_spec, phase="repair_1", **common)
        state["terminal_status"] = ("NOT_EVALUATED_TRANSPORT_AT_REPAIR" if repair_raw is None
                                    else _terminal_for(state["repair"]["validation"], batch))
    else:
        state["terminal_status"] = _terminal_for(validation, batch)
    if batch is not None:
        state["compiled_batch_sha256"] = _write_json(
            artifact_root / "compiled" / f"{case.case_id}.json", batch)


def execute(*, candidate_lock: Path, candidate_lock_sha256: str, input_archive: Path,
            input_root: Path, input_archive_sha256: str, checkpoint_root: Path,
            artifact_root: Path, result_path: Path, prediction_manifest_path: Path,
            transport: OfflineTransport, research_task_id: str, max_provider_operations: int,
            max_total_tokens: int, clock: Callable[[], float] = time.time,
            sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Run every case to a terminal or interrupted state with an offline transport."""
    if not isinstance(transport, OfflineTransport) or getattr(transport, "offline", False) is not True:
        raise LiveExecutionNotEnabled("Only OfflineTransport instances are accepted")
    for path in (checkpoint_root, artifact_root, result_path, prediction_manifest_path):
        guard_path(path)
    definition = validate_candidate_lock(candidate_lock, candidate_lock_sha256)
    definition_sha = candidate_definition_sha256()
    dataset_id, cases = load_case_inputs(input_archive, input_root, input_archive_sha256)

    def guard() -> None:
        if candidate_definition() != definition:
            raise RunnerError("Candidate definition changed during the run")
        if _sha256_file(input_archive) != input_archive_sha256:
            raise RunnerError("Input archive changed during the run")

    def guarded(spec: DurableJobSpec, window: int, request_id: str):
        guard()
        response = transport(spec, window, request_id)
        guard()
        return response

    executor = DurableResearchExecutor(checkpoint_root / "jobs",
                                       protocol_id=f"{CANDIDATE_ID}:{definition_sha}",
                                       window_cooldown_seconds=WINDOW_COOLDOWN_SECONDS,
                                       clock=clock)
    ledger = Ledger(max_provider_operations, max_total_tokens)
    results: list[dict[str, Any]] = []
    run_status = "COMPLETE"
    for case in cases:
        state: dict[str, Any] = {"case_id": case.case_id, "primary": None, "repair": None,
                                 "terminal_status": None, "compiled_batch_sha256": None}
        try:
            guard()
            run_case(case, state, executor=executor, transport=guarded, ledger=ledger,
                     sleep=sleep, artifact_root=artifact_root,
                     research_task_id=research_task_id)
        except _Stop as stop:
            state["terminal_status"] = "INTERRUPTED_" + stop.reason
            run_status = "INCONCLUSIVE_INFRASTRUCTURE_" + stop.reason
        except Exception as error:  # recorded, never silently lost
            state["terminal_status"] = "INTERRUPTED_RUNNER_ERROR"
            state["error_type"] = type(error).__name__
            run_status = "INTERRUPTED_RUNNER_ERROR"
        state["repair_used"] = state["repair"] is not None
        _write_json(artifact_root / "case_results" / f"{case.case_id}.json", state)
        results.append(state)
        if run_status != "COMPLETE":
            break
    started = {item["case_id"] for item in results}
    not_started = [case.case_id for case in cases if case.case_id not in started]
    identities = [{
        "case_id": item["case_id"],
        "primary_request_fingerprint": (item["primary"] or {}).get("request_fingerprint"),
        "primary_raw_response_sha256": (item["primary"] or {}).get("raw_response_sha256"),
        "repair_request_fingerprint": (item["repair"] or {}).get("request_fingerprint"),
        "repair_raw_response_sha256": (item["repair"] or {}).get("raw_response_sha256"),
        "terminal_status": item["terminal_status"],
        "compiled_batch_sha256": item["compiled_batch_sha256"],
    } for item in results]
    locator_totals: Counter = Counter()
    for item in results:
        final = item["repair"] if item["repair"] is not None else item["primary"]
        for key, value in ((final or {}).get("validation") or {}).get("locator_counts", {}).items():
            locator_totals[key] += value
    placed = locator_totals["emitted_locators"] + locator_totals["declared_unresolved"]
    result = {
        "artifact": RESULT_ID, "runner_id": RUNNER_ID, "research_task_id": research_task_id,
        "candidate_id": CANDIDATE_ID, "candidate_definition_sha256": definition_sha,
        "dataset_id": dataset_id, "input_archive_sha256": input_archive_sha256, "model": MODEL,
        "case_order": [case.case_id for case in cases], "run_status": run_status,
        "terminal_status_counts": dict(sorted(Counter(i["terminal_status"] for i in results).items())),
        "not_started_cases": not_started,
        "locator_totals": dict(sorted(locator_totals.items())),
        "declared_unresolved_rate": None if placed == 0
        else locator_totals["declared_unresolved"] / placed,
        "accounting": ledger.snapshot(), "environment": environment_observed(),
        "prediction_set_sha256": sha256_bytes(canonical_json_bytes(identities)),
        "predictions": results, "live_execution": False, "gold_opened": False,
        "holdout_opened": False, "scoring_performed": False,
    }
    _write_json(result_path, result)
    _write_json(prediction_manifest_path, {
        "artifact": PREDICTION_MANIFEST_ID, "candidate_definition_sha256": definition_sha,
        "dataset_id": dataset_id, "input_archive_sha256": input_archive_sha256,
        "entries": identities, "not_started_cases": not_started,
        "prediction_set_sha256": result["prediction_set_sha256"], "run_status": run_status,
        "gold_opened": False, "scoring_performed": False,
    })
    return result


def main(argv: Optional[list[str]] = None) -> int:
    """Preflight only. This runner version has no live mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preflight",), required=True)
    parser.add_argument("--candidate-lock", required=True, type=Path)
    parser.add_argument("--candidate-lock-sha256", required=True)
    parser.add_argument("--input-archive", required=True, type=Path)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--input-archive-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        validate_candidate_lock(args.candidate_lock, args.candidate_lock_sha256)
        dataset_id, cases = load_case_inputs(args.input_archive, args.input_root,
                                             args.input_archive_sha256)
    except (RunnerError, CandidateError) as error:
        print(f"M4_DRAFT_V1_2_PREFLIGHT_FAILED: {type(error).__name__}", flush=True)
        return 2
    print(json.dumps({"cases": len(cases), "dataset_id": dataset_id, "input_manifest": INPUT_MANIFEST,
                      "status": "PREFLIGHT_PASS"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
