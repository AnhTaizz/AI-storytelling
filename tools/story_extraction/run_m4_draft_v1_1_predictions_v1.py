"""Run the P3 Draft V1.1 candidate on an authorized prepared-input archive.

The runner separates model draft generation (durable provider jobs) from deterministic
compilation (the unchanged V1.1 compiler). It accepts no gold path and imports no
evaluator, so it cannot score. Every provider call goes through an injected transport:
tests inject offline transports, and a live transport is built only in ``run-live`` mode
with a matching execution authorization record. Without that record nothing is sent.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import time
from typing import Any, Callable, Mapping, Optional
import zipfile

from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import (
    DRAFT_VERSION,
    prepare_story_extraction_draft_v1_1,
)
from tools.story_extraction.draft_v1_1_conformance_diagnostics_v1 import (
    compile_with_diagnostics_v1_1,
)
from tools.story_extraction.durable_research_executor_v1 import (
    CheckpointIntegrityError,
    CooldownPending,
    DurableJobSpec,
    DurableResearchExecutor,
    JobState,
    summarize_job,
)
from tools.story_extraction.m4_draft_v1_1_candidate_p3_v1 import (
    CANDIDATE_ID,
    CASE_ID_PATTERN,
    FORBIDDEN_ARCHIVE_SHA256,
    MAX_PROVIDER_ATTEMPTS_PER_JOB,
    MAX_STRUCTURAL_REPAIRS_PER_CASE,
    MODEL,
    REPAIR_ELIGIBLE_CATEGORIES,
    WINDOW_COOLDOWN_SECONDS,
    CandidateError,
    build_primary_spec,
    build_repair_spec,
    canonical_json_bytes,
    candidate_definition,
    candidate_definition_sha256,
    sha256_bytes,
    validate_candidate_definition,
)
from tools.story_ingestion.light_novel_adapter_v0 import ingest_manifest_file


RUNNER_ID = "M4_DRAFT_V1_1_PREDICTION_RUNNER_V1"
INPUT_MANIFEST = "INPUT_MANIFEST.json"
RESULT_ID = "M4_DRAFT_V1_1_PREDICTION_RESULT_V1"
PREDICTION_MANIFEST_ID = "M4_DRAFT_V1_1_PREDICTION_MANIFEST_V1"
FORBIDDEN_PATH_MARKERS = ("gold", "holdout")
AUTHORIZATION_FIELDS = (
    "authorization_id",
    "research_task_id",
    "dataset_id",
    "input_archive_sha256",
    "case_ids",
    "candidate_definition_sha256",
    "live_provider_calls_authorized",
    "max_provider_operations",
    "max_total_tokens",
    "approved_by",
    "approved_at_utc",
)

Transport = Callable[[DurableJobSpec, int, str], Mapping[str, Any]]


class RunnerError(RuntimeError):
    """A fail-closed input, lock or execution error carrying no private text."""


class BudgetExceeded(RunnerError):
    """The pre-registered provider-operation or token cap would be exceeded."""


class ProviderDriftError(RunnerError):
    """The provider reported more than one model version within one run."""


@dataclass(frozen=True)
class CaseInput:
    case_id: str
    prepared_input: Mapping[str, Any]
    context: DraftCompilerContext


@dataclass(frozen=True)
class ExecutionAuthorization:
    value: Mapping[str, Any]
    sha256: str

    @property
    def research_task_id(self) -> str:
        return str(self.value["research_task_id"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_bytes_atomic(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "wb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_json(path: Path, value: Any) -> str:
    payload = canonical_json_bytes(value)
    _write_bytes_atomic(path, payload)
    return sha256_bytes(payload)


def guard_path(path: Path) -> None:
    """Reject any path that names gold or holdout material."""
    for part in Path(path).resolve().parts:
        if any(marker in part.lower() for marker in FORBIDDEN_PATH_MARKERS):
            raise RunnerError("Gold and holdout paths are forbidden")


def _member_path(root: Path, member: str) -> Path:
    pure = PurePosixPath(member)
    if pure.is_absolute() or ".." in pure.parts or any(
        marker in part.lower() for part in pure.parts for marker in FORBIDDEN_PATH_MARKERS
    ):
        raise RunnerError("Input member path is forbidden")
    target = (root / Path(*pure.parts)).resolve()
    resolved = root.resolve()
    if target != resolved and resolved not in target.parents:
        raise RunnerError("Input member escapes the authorized root")
    return target


def load_authorization(path: Path) -> ExecutionAuthorization:
    guard_path(path)
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RunnerError("Execution authorization is missing or invalid") from error
    if not isinstance(value, dict) or set(value) != set(AUTHORIZATION_FIELDS):
        raise RunnerError("Execution authorization fields differ from the required set")
    if value["input_archive_sha256"] in FORBIDDEN_ARCHIVE_SHA256:
        raise RunnerError("Execution authorization names a sealed or gold archive")
    if (
        not isinstance(value["case_ids"], list)
        or not value["case_ids"]
        or len(set(value["case_ids"])) != len(value["case_ids"])
        or not all(isinstance(item, str) and CASE_ID_PATTERN.fullmatch(item)
                   for item in value["case_ids"])
    ):
        raise RunnerError("Execution authorization case list is invalid")
    for key in ("max_provider_operations", "max_total_tokens"):
        if type(value[key]) is not int or value[key] <= 0:
            raise RunnerError("Execution authorization budget is invalid")
    if value["candidate_definition_sha256"] != candidate_definition_sha256():
        raise RunnerError("Execution authorization names a different candidate")
    return ExecutionAuthorization(value, sha256_bytes(raw))


def validate_candidate_lock(path: Path, expected_sha256: str) -> dict[str, Any]:
    """The private lock must equal the current candidate definition byte for byte."""
    try:
        locked = path.read_bytes()
        value = json.loads(locked.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RunnerError("Candidate lock is missing or invalid") from error
    if sha256_bytes(locked) != expected_sha256:
        raise RunnerError("Candidate lock hash mismatch")
    try:
        validate_candidate_definition(value)
    except CandidateError as error:
        raise RunnerError(str(error)) from error
    if locked != canonical_json_bytes(value):
        raise RunnerError("Candidate lock is not canonical JSON")
    return value


def verify_input_archive(archive: Path, input_root: Path, expected_sha256: str) -> dict[str, Any]:
    guard_path(archive)
    guard_path(input_root)
    actual = _sha256_file(archive)
    if actual in FORBIDDEN_ARCHIVE_SHA256:
        raise RunnerError("Input archive is a sealed or gold archive")
    if actual != expected_sha256:
        raise RunnerError("Input archive hash mismatch")
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = [item for item in bundle.infolist() if not item.is_dir()]
            names = [item.filename for item in infos]
            if len(names) != len(set(names)):
                raise RunnerError("Input archive has duplicate members")
            extracted = sorted(
                path.relative_to(input_root).as_posix()
                for path in input_root.rglob("*")
                if path.is_file()
            )
            if sorted(names) != extracted:
                raise RunnerError("Extracted input inventory mismatch")
            for info in infos:
                target = _member_path(input_root, info.filename)
                if sha256_bytes(bundle.read(info)) != _sha256_file(target):
                    raise RunnerError("Extracted input byte mismatch")
    except (OSError, zipfile.BadZipFile) as error:
        raise RunnerError("Input archive is unreadable") from error
    try:
        return json.loads(_member_path(input_root, INPUT_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RunnerError("Input manifest is invalid") from error


def _read_json_member(input_root: Path, member: str) -> Any:
    try:
        return json.loads(_member_path(input_root, member).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RunnerError("Input member is invalid") from error


def process_version() -> str:
    return "p3v11-" + candidate_definition_sha256()[:16]


def load_case_inputs(archive: Path, input_root: Path,
                     expected_sha256: str) -> tuple[str, list[CaseInput]]:
    manifest = verify_input_archive(archive, input_root, expected_sha256)
    dataset_id = manifest.get("artifact")
    rows = manifest.get("cases")
    if (
        not isinstance(dataset_id, str)
        or any(marker in dataset_id.lower() for marker in FORBIDDEN_PATH_MARKERS)
        or manifest.get("draft_interface") != DRAFT_VERSION
        or not isinstance(rows, list)
        or manifest.get("case_count") != len(rows)
        or not rows
    ):
        raise RunnerError("Input manifest identity mismatch")
    case_ids = [row.get("case_id") for row in rows]
    if len(set(case_ids)) != len(case_ids) or not all(
        isinstance(item, str) and CASE_ID_PATTERN.fullmatch(item) for item in case_ids
    ):
        raise RunnerError("Input case ids are invalid")
    version = process_version()
    loaded = []
    for row in rows:
        case_id = row["case_id"]
        base = _read_json_member(input_root, row["base_document_member"])
        prepared = _read_json_member(input_root, row["prepared_input_member"])
        manifest_path = _member_path(input_root, row["m3_manifest_member"])
        ingestion = ingest_manifest_file(manifest_path, manifest_path.parent)
        context = DraftCompilerContext(
            base_document=base,
            passage_inputs=row["passage_inputs"],
            as_of_position=row["as_of_position"],
            profile_id=row["profile_id"],
            process_id=CANDIDATE_ID,
            process_version=version,
            run_id=f"P3V11_{case_id}",
            ingestion=ingestion,
        )
        if prepare_story_extraction_draft_v1_1(context) != prepared:
            raise RunnerError("Prepared Draft V1.1 input does not reproduce exactly")
        loaded.append(CaseInput(case_id, prepared, context))
    return dataset_id, loaded


def mention_advisories(draft: Mapping[str, Any]) -> list[dict[str, str]]:
    """Non-blocking grounding signals the compiler does not enforce."""
    advisories = []
    resolved = set()
    for proposition in draft.get("propositions", []):
        if proposition.get("predicate") == "RefersTo":
            mention = proposition.get("args", {}).get("mention", {})
            if mention.get("kind") == "MENTION":
                resolved.add(mention.get("handle"))
    for mention in draft.get("mentions", []):
        if "surface_form" in mention and mention["surface_form"] != mention["quote"]:
            advisories.append({"code": "SURFACE_FORM_DIFFERS_FROM_QUOTE",
                               "subject": mention["handle"]})
        if mention["handle"] not in resolved:
            advisories.append({"code": "MENTION_WITHOUT_REFERSTO", "subject": mention["handle"]})
    return sorted(advisories, key=lambda item: (item["code"], item["subject"]))


def _provenance_issues(batch: Mapping[str, Any], case: CaseInput) -> list[str]:
    issues = []
    process = batch.get("process", {})
    if process != {
        "method": "AUTOMATED_EXTRACTION",
        "process_id": CANDIDATE_ID,
        "process_version": case.context.process_version,
        "run_id": case.context.run_id,
    }:
        issues.append("PROCESS_IDENTITY_MISMATCH")
    if batch.get("scope", {}).get("passage_inputs") != case.context.passage_inputs:
        issues.append("PASSAGE_SCOPE_MISMATCH")
    if batch.get("scope", {}).get("as_of_position") != case.context.as_of_position:
        issues.append("AS_OF_MISMATCH")
    for assertion in batch.get("candidate_records", {}).get("assertions", []):
        if assertion.get("review") != {"state": "UNREVIEWED"}:
            issues.append("REVIEW_STATE_NOT_UNREVIEWED")
            break
    return issues


def compile_attempt(raw: str, case: CaseInput) -> tuple[Any, Optional[dict[str, Any]], dict[str, Any]]:
    """Parse and compile one response; never repairs, normalizes or infers."""
    try:
        draft = json.loads(raw)
    except json.JSONDecodeError:
        return None, None, {"pass": False, "category": "JSON_PARSE_FAILURE",
                            "blockers": [{"phase": "JSON", "code": "INVALID_JSON", "path": ""}],
                            "canonical_issue_classes": []}
    try:
        batch, diagnostics = compile_with_diagnostics_v1_1(draft, case.context)
    except Exception:  # an unexpected exception is a deterministic-code defect
        return draft, None, {"pass": False, "category": "COMPILER_INTERNAL_EXCEPTION",
                             "blockers": [], "canonical_issue_classes": []}
    if batch is None:
        schema = any(item["phase"] == "SCHEMA" for item in diagnostics["blockers"])
        return draft, None, {
            "pass": False,
            "category": "DRAFT_SCHEMA_FAILURE" if schema else "DRAFT_COMPILER_FAILURE",
            "blockers": diagnostics["blockers"],
            "canonical_issue_classes": diagnostics["canonical_issue_classes"],
        }
    again, _ = compile_with_diagnostics_v1_1(deepcopy(draft), case.context)
    if again is None or canonical_json_bytes(again) != canonical_json_bytes(batch):
        raise RunnerError("NONDETERMINISTIC_COMPILATION")
    provenance = _provenance_issues(batch, case)
    if provenance:
        raise RunnerError("PROVENANCE_INVARIANT_VIOLATION")
    return draft, batch, {"pass": True, "category": None, "blockers": [],
                          "canonical_issue_classes": [],
                          "advisories": mention_advisories(draft)}


def repair_feedback(validation: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "category": validation["category"],
        "blockers": list(validation.get("blockers", [])),
        "canonical_issue_classes": list(validation.get("canonical_issue_classes", [])),
    }


class _Ledger:
    """Provider operations, tokens and reported model versions for one run."""

    def __init__(self, max_operations: int, max_tokens: int) -> None:
        self.max_operations = max_operations
        self.max_tokens = max_tokens
        self.operations = 0
        self.tokens = Counter()
        self.versions: set[str] = set()
        self.counted_jobs: set[str] = set()

    def before_job(self) -> None:
        if self.operations + MAX_PROVIDER_ATTEMPTS_PER_JOB > self.max_operations:
            raise BudgetExceeded("PROVIDER_OPERATION_CAP")
        if self.tokens["total_token_count"] >= self.max_tokens:
            raise BudgetExceeded("TOKEN_CAP")

    def record(self, record: Mapping[str, Any]) -> dict[str, Any]:
        summary = summarize_job(record)
        if record["job_id"] not in self.counted_jobs:
            self.counted_jobs.add(record["job_id"])
            self.operations += int(record["total_provider_operations"])
            usage = (record.get("first_success") or {}).get("usage") or {}
            for key in ("prompt_token_count", "candidates_token_count", "total_token_count",
                        "thoughts_token_count", "cached_content_token_count"):
                value = usage.get(key)
                if isinstance(value, int):
                    self.tokens[key] += value
            version = summary.get("model_reported_version")
            if version:
                self.versions.add(str(version))
        summary["usage"] = (record.get("first_success") or {}).get("usage") or {}
        if len(self.versions) > 1:
            raise ProviderDriftError("PROVIDER_REPORTED_MODEL_VERSION_CHANGED")
        if self.tokens["total_token_count"] > self.max_tokens:
            raise BudgetExceeded("TOKEN_CAP")
        return summary

    def snapshot(self) -> dict[str, Any]:
        return {
            "provider_operations": self.operations,
            "max_provider_operations": self.max_operations,
            "tokens": dict(sorted(self.tokens.items())),
            "max_total_tokens": self.max_tokens,
            "provider_reported_model_versions": sorted(self.versions),
        }


def _execute_to_terminal(executor: DurableResearchExecutor, spec: DurableJobSpec,
                         transport: Transport, sleep: Callable[[float], None]) -> dict[str, Any]:
    executor.ensure_job(spec)
    while True:
        record = executor.load_job(spec)
        if JobState(record["state"]) in {JobState.SUCCEEDED_LOCKED, JobState.TERMINAL_FAILED}:
            return record
        try:
            executor.execute_window(spec, transport)
        except CooldownPending as pending:
            sleep(max(0.001, pending.remaining_seconds))


def _persist(artifact_root: Path, case_id: str, phase: str, raw: str,
             draft: Any) -> tuple[str, Optional[str]]:
    raw_bytes = raw.encode("utf-8")
    _write_bytes_atomic(artifact_root / "raw" / f"{case_id}_{phase}.txt", raw_bytes)
    draft_sha = None
    if draft is not None:
        draft_sha = _write_json(artifact_root / "drafts" / f"{case_id}_{phase}.json", draft)
    return sha256_bytes(raw_bytes), draft_sha


def _attempt(executor, spec, transport, ledger, sleep, artifact_root, case, phase):
    existing = executor.ensure_job(spec)
    if JobState(existing["state"]) not in {JobState.SUCCEEDED_LOCKED, JobState.TERMINAL_FAILED}:
        ledger.before_job()
    record = _execute_to_terminal(executor, spec, transport, sleep)
    summary = ledger.record(record)
    raw = (record.get("first_success") or {}).get("raw_response")
    entry: dict[str, Any] = {
        "job_id": spec.job_id,
        "request_fingerprint": spec.request_fingerprint,
        "transport": summary,
        "raw_response_sha256": None,
        "draft_sha256": None,
        "validation": None,
    }
    if not isinstance(raw, str):
        entry["validation"] = {"pass": False, "category": "TRANSPORT_FAILURE",
                               "code": record.get("terminal_failure_category")
                               or record["state"]}
        return entry, None, None, None
    draft, batch, validation = compile_attempt(raw, case)
    entry["raw_response_sha256"], entry["draft_sha256"] = _persist(
        artifact_root, case.case_id, phase, raw, draft)
    entry["validation"] = validation
    return entry, raw, draft, batch


def run_case(case: CaseInput, *, executor, transport, ledger, sleep, artifact_root: Path,
             research_task_id: str) -> dict[str, Any]:
    primary_spec = build_primary_spec(case.case_id, case.prepared_input, research_task_id)
    primary, primary_raw, _, batch = _attempt(
        executor, primary_spec, transport, ledger, sleep, artifact_root, case, "primary")
    repair = None
    if primary_raw is None:
        terminal = "NOT_EVALUATED_TRANSPORT"
    elif batch is not None:
        terminal = "STRUCTURAL_VALID"
    elif (primary["validation"]["category"] in REPAIR_ELIGIBLE_CATEGORIES
          and MAX_STRUCTURAL_REPAIRS_PER_CASE >= 1):
        repair_spec = build_repair_spec(case.case_id, case.prepared_input, primary_raw,
                                        repair_feedback(primary["validation"]), research_task_id)
        repair, repair_raw, _, batch = _attempt(
            executor, repair_spec, transport, ledger, sleep, artifact_root, case, "repair_1")
        if repair_raw is None:
            terminal = "NOT_EVALUATED_TRANSPORT_AT_REPAIR"
        elif batch is not None:
            terminal = "STRUCTURAL_VALID"
        elif repair["validation"]["category"] == "COMPILER_INTERNAL_EXCEPTION":
            terminal = "DETERMINISTIC_DEFECT_SUSPECTED"
        else:
            terminal = "STRUCTURAL_FAILURE"
    elif primary["validation"]["category"] == "COMPILER_INTERNAL_EXCEPTION":
        terminal = "DETERMINISTIC_DEFECT_SUSPECTED"
    else:
        terminal = "STRUCTURAL_FAILURE"
    compiled_sha = None
    if batch is not None:
        compiled_sha = _write_json(artifact_root / "compiled" / f"{case.case_id}.json", batch)
    item = {
        "case_id": case.case_id,
        "primary": primary,
        "repair_used": repair is not None,
        "repair": repair,
        "terminal_status": terminal,
        "compiled_batch_sha256": compiled_sha,
    }
    _write_json(artifact_root / "case_results" / f"{case.case_id}.json", item)
    return item


def execute(*, candidate_lock: Path, candidate_lock_sha256: str, input_archive: Path,
            input_root: Path, input_archive_sha256: str, checkpoint_root: Path,
            artifact_root: Path, result_path: Path, prediction_manifest_path: Path,
            transport: Transport, research_task_id: str, max_provider_operations: int,
            max_total_tokens: int, case_ids: Optional[list[str]] = None,
            clock: Callable[[], float] = time.time,
            sleep: Callable[[float], None] = time.sleep,
            forbidden_secrets: tuple[str, ...] = ()) -> dict[str, Any]:
    """Run every case to a terminal state; the transport is always injected."""
    for path in (checkpoint_root, artifact_root, result_path, prediction_manifest_path):
        guard_path(path)
    definition = validate_candidate_lock(candidate_lock, candidate_lock_sha256)
    definition_sha = candidate_definition_sha256()
    dataset_id, cases = load_case_inputs(input_archive, input_root, input_archive_sha256)
    if case_ids is not None and [case.case_id for case in cases] != list(case_ids):
        raise RunnerError("Input case ids differ from the authorized case list")

    def guard() -> None:
        if candidate_definition() != definition:
            raise CheckpointIntegrityError("Candidate definition changed during the run")
        if _sha256_file(input_archive) != input_archive_sha256:
            raise CheckpointIntegrityError("Input archive changed during the run")

    def guarded_transport(spec: DurableJobSpec, window: int, request_id: str):
        guard()
        response = transport(spec, window, request_id)
        guard()
        return response

    guard()
    executor = DurableResearchExecutor(
        checkpoint_root / "jobs",
        protocol_id=f"{CANDIDATE_ID}:{definition_sha}",
        window_cooldown_seconds=WINDOW_COOLDOWN_SECONDS,
        clock=clock,
        forbidden_secrets=forbidden_secrets,
    )
    ledger = _Ledger(max_provider_operations, max_total_tokens)
    results: list[dict[str, Any]] = []
    stop_reason = None
    try:
        for case in cases:
            guard()
            results.append(run_case(
                case, executor=executor, transport=guarded_transport, ledger=ledger,
                sleep=sleep, artifact_root=artifact_root, research_task_id=research_task_id,
            ))
    except BudgetExceeded as error:
        stop_reason = "INCONCLUSIVE_INFRASTRUCTURE_" + str(error)
    except ProviderDriftError as error:
        stop_reason = "INCONCLUSIVE_INFRASTRUCTURE_" + str(error)

    identities = [
        {
            "case_id": item["case_id"],
            "primary_request_fingerprint": item["primary"]["request_fingerprint"],
            "primary_raw_response_sha256": item["primary"]["raw_response_sha256"],
            "repair_request_fingerprint": None if item["repair"] is None
            else item["repair"]["request_fingerprint"],
            "repair_raw_response_sha256": None if item["repair"] is None
            else item["repair"]["raw_response_sha256"],
            "terminal_status": item["terminal_status"],
            "compiled_batch_sha256": item["compiled_batch_sha256"],
        }
        for item in results
    ]
    statuses = Counter(item["terminal_status"] for item in results)
    run_status = stop_reason or (
        "COMPLETE" if len(results) == len(cases) else "INCOMPLETE")
    result = {
        "artifact": RESULT_ID,
        "runner_id": RUNNER_ID,
        "research_task_id": research_task_id,
        "candidate_id": CANDIDATE_ID,
        "candidate_definition_sha256": definition_sha,
        "candidate_lock_sha256": candidate_lock_sha256,
        "dataset_id": dataset_id,
        "input_archive_sha256": input_archive_sha256,
        "model": MODEL,
        "case_order": [case.case_id for case in cases],
        "run_status": run_status,
        "terminal_status_counts": dict(sorted(statuses.items())),
        "primary_structural_valid_count": sum(
            item["primary"]["validation"].get("pass") is True for item in results),
        "repair_count": sum(item["repair_used"] for item in results),
        "accounting": ledger.snapshot(),
        "prediction_set_sha256": sha256_bytes(canonical_json_bytes(identities)),
        "predictions": results,
        "gold_opened": False,
        "holdout_opened": False,
        "scoring_performed": False,
        "completed_at_utc": _utc_now(),
    }
    _write_json(result_path, result)
    _write_json(prediction_manifest_path, {
        "artifact": PREDICTION_MANIFEST_ID,
        "candidate_definition_sha256": definition_sha,
        "dataset_id": dataset_id,
        "input_archive_sha256": input_archive_sha256,
        "entries": identities,
        "prediction_set_sha256": result["prediction_set_sha256"],
        "run_status": run_status,
        "gold_opened": False,
        "scoring_performed": False,
    })
    return result


def _live_transport(checkpoint_root: Path, guard_secret_sink: list[str]) -> Transport:
    """Construct the accepted live Gemini window transport. Imported lazily."""
    from tools.story_extraction.durable_research_executor_v1 import (
        PersistentRollingOperationPacer,
    )
    from tools.story_extraction.gemini_key_pool_v1 import load_runtime_config
    from tools.story_extraction.m4_draft_v1_1_candidate_p3_v1 import (
        CREDENTIAL_SLOT,
        GLOBAL_MAX_PROVIDER_OPERATIONS,
        GLOBAL_ROLLING_WINDOW_SECONDS,
    )
    from tools.story_extraction.run_m4_04b2_dev_predictions_v1 import GeminiDevWindowTransport

    config = load_runtime_config()
    selected = [item for item in config.credentials if item.slot_id == CREDENTIAL_SLOT]
    if len(selected) != 1:
        raise RunnerError("Locked credential slot is unavailable or ambiguous")
    guard_secret_sink.extend(item._api_key for item in config.credentials)
    pacer = PersistentRollingOperationPacer(
        checkpoint_root / "global_pacing.json",
        max_operations=GLOBAL_MAX_PROVIDER_OPERATIONS,
        window_seconds=GLOBAL_ROLLING_WINDOW_SECONDS,
    )
    return GeminiDevWindowTransport(selected[0], pacer, lambda: None)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preflight", "run-live"), required=True)
    parser.add_argument("--candidate-lock", required=True, type=Path)
    parser.add_argument("--candidate-lock-sha256", required=True)
    parser.add_argument("--input-archive", required=True, type=Path)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--input-archive-sha256", required=True)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--checkpoint-root", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--prediction-manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        validate_candidate_lock(args.candidate_lock, args.candidate_lock_sha256)
        dataset_id, cases = load_case_inputs(
            args.input_archive, args.input_root, args.input_archive_sha256)
        if args.mode == "preflight":
            print(json.dumps({"cases": len(cases), "dataset_id": dataset_id,
                              "status": "PREFLIGHT_PASS"}, sort_keys=True))
            return 0
        if args.authorization is None:
            raise RunnerError("Live execution requires an execution authorization record")
        authorization = load_authorization(args.authorization)
        value = authorization.value
        if (
            value["live_provider_calls_authorized"] is not True
            or value["dataset_id"] != dataset_id
            or value["input_archive_sha256"] != args.input_archive_sha256
        ):
            raise RunnerError("Execution authorization does not cover this run")
        if any(item is None for item in (args.checkpoint_root, args.artifact_root,
                                         args.result, args.prediction_manifest)):
            raise RunnerError("Live execution requires all private output paths")
        secrets: list[str] = []
        transport = _live_transport(args.checkpoint_root, secrets)
        execute(
            candidate_lock=args.candidate_lock,
            candidate_lock_sha256=args.candidate_lock_sha256,
            input_archive=args.input_archive,
            input_root=args.input_root,
            input_archive_sha256=args.input_archive_sha256,
            checkpoint_root=args.checkpoint_root,
            artifact_root=args.artifact_root,
            result_path=args.result,
            prediction_manifest_path=args.prediction_manifest,
            transport=transport,
            research_task_id=authorization.research_task_id,
            max_provider_operations=value["max_provider_operations"],
            max_total_tokens=value["max_total_tokens"],
            case_ids=list(value["case_ids"]),
            forbidden_secrets=tuple(secrets),
        )
    except (RunnerError, CandidateError, CheckpointIntegrityError) as error:
        print(f"M4_DRAFT_V1_1_RUNNER_STOPPED: {type(error).__name__}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
