"""P4 structural runner core and synthetic native-schema smoke (M4-04B4B).

Runs the locked P4 protocol. A response is parsed, validated by the unchanged Draft V1.1
validator and compiled by the unchanged V1.1 compiler; a structural failure is described
by repair diagnostic V2 and may be repaired once. Requests are checked by the P4 job-spec
checker, never by the P3 one.

The only live entry point here is a synthetic capability smoke: one invented sentence,
one primary job, one execution window and a hard budget on real provider operations. It
reads no dataset. It accepts no gold path and imports no evaluator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Callable, Mapping, Optional

from tools.story_extraction import m4_04b4a_p4_output_contract_v1 as contract
from tools.story_extraction import m4_04b4b_p4_protocol_v1 as protocol
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import (
    DraftCompilationErrorV1_1,
    compile_story_extraction_draft_v1_1,
    prepare_story_extraction_draft_v1_1,
    validate_draft_v1_1,
)
from tools.story_extraction.durable_research_executor_v1 import (
    CheckpointIntegrityError,
    DurableJobSpec,
    DurableResearchExecutor,
    JobState,
    PersistentRollingOperationPacer,
)
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError, load_runtime_config
from tools.story_extraction.run_m4_04b2_dev_predictions_v1 import (
    GeminiDevWindowTransport,
    _job_telemetry,
    _write_bytes_atomic,
)
from tools.story_extraction.run_m4_04b3g_dev3_p3_predictions_v1 import (
    CaseInput,
    Dev3RunnerError,
    FirstSuccessLedger,
    FirstSuccessProvider,
    ProviderFirstSuccess,
)
from tools.story_extraction.run_m4_04b3h_dev3_p3_live_v1_1 import verify_execution_environment
from tools.story_ingestion import light_novel_adapter_v0 as ingestion_adapter


RUNNER_ID = "M4_04B4B_P4_STRUCTURAL_RUNNER_V1"
RUNNER_PATH = "tools/story_extraction/run_m4_04b4b_p4_structural_v1.py"
PROTOCOL_MODULE_PATH = "tools/story_extraction/m4_04b4b_p4_protocol_v1.py"
REPO_ROOT = protocol.REPO_ROOT
PROCESS_ID = "M4_04B4B_P4"
PROCESS_VERSION = "v1"

SMOKE_CASE_ID = "SYNTHETIC_SMOKE_01"
SMOKE_TEXT = "Tomas closed the window."
SMOKE_AUTHORIZATION_TOKEN = "M4-04B4B-SYNTHETIC-SMOKE"
SMOKE_OPERATION_BUDGET = 2
SMOKE_RESULT_ID = "M4_04B4B_P4_SYNTHETIC_SMOKE_RESULT_V1"
DEFAULT_SMOKE_ROOT = REPO_ROOT / ".local/m4_04b4b_p4_synthetic_smoke"


class P4RunnerError(RuntimeError):
    """A fail-closed runner, budget or artifact error with no private text."""


class OperationBudgetExhausted(CheckpointIntegrityError):
    """The hard limit on real provider operations was reached before another call."""


# ---------------------------------------------------------------------------
# Compilation and repair diagnostic V2
# ---------------------------------------------------------------------------

def _diagnostic(category: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "diagnostic": contract.REPAIR_DIAGNOSTIC_ID,
        "model_schema": contract.MODEL_SCHEMA_IDENTITY,
        "category": category,
        "finding_count": len(findings),
        "findings": findings,
    }


def compile_raw_response(raw: Any, case: CaseInput) -> tuple[Any, Any, dict[str, Any]]:
    """Parse, validate and compile one response; describe any failure with diagnostic V2."""
    try:
        draft = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None, None, {"pass": False, "category": "JSON_PARSE_FAILURE",
                            "diagnostic": contract.structural_diagnostic_v2(raw)}
    try:
        validate_draft_v1_1(draft)
    except DraftCompilationErrorV1_1:
        diagnostic = contract.structural_diagnostic_v2(raw)
        if diagnostic["category"] != "DRAFT_SCHEMA_FAILURE" or not diagnostic["findings"]:
            raise P4RunnerError("Canonical validator and model schema disagree")
        return draft, None, {"pass": False, "category": "DRAFT_SCHEMA_FAILURE", "diagnostic": diagnostic}
    try:
        batch = compile_story_extraction_draft_v1_1(draft, case.compiler_context)
    except DraftCompilationErrorV1_1 as error:
        findings = contract.compiler_findings([item.as_dict() for item in error.blockers])
        return draft, None, {"pass": False, "category": "DRAFT_COMPILER_FAILURE",
                             "diagnostic": _diagnostic("DRAFT_COMPILER_FAILURE", findings)}
    return draft, batch, {"pass": True, "category": None, "diagnostic": None}


class OfflineMockProvider:
    """In-memory provider for synthetic tests. It performs zero real operations."""

    actual_provider_operations = 0

    def __init__(self, responses: Mapping[str, str]) -> None:
        self._responses = dict(responses)
        self.calls: list[str] = []
        self.specs: list[DurableJobSpec] = []

    def first_success(self, spec: DurableJobSpec) -> ProviderFirstSuccess:
        protocol.assert_locked_job_spec(spec)
        if spec.job_id not in self._responses:
            raise P4RunnerError("Mock response is not preregistered")
        if spec.job_id in self.calls:
            raise P4RunnerError("A locked job cannot be invoked twice")
        self.calls.append(spec.job_id)
        self.specs.append(spec)
        raw = self._responses[spec.job_id]
        return ProviderFirstSuccess(raw, 0, hashlib.sha256(raw.encode("utf-8")).hexdigest())


def _invoke_first_success(
    provider: FirstSuccessProvider, ledger: FirstSuccessLedger, spec: DurableJobSpec, *, offline_only: bool
) -> str:
    protocol.assert_locked_job_spec(spec)
    before = provider.actual_provider_operations
    success = provider.first_success(spec)
    after = provider.actual_provider_operations
    if after - before != success.provider_operations:
        raise P4RunnerError("Provider operation telemetry mismatch")
    if offline_only and (success.provider_operations != 0 or after != 0):
        raise P4RunnerError("Offline execution forbids provider operations")
    try:
        return ledger.lock(spec, success)
    except Dev3RunnerError as error:
        raise P4RunnerError("Immutable first-success lock violated") from error


def execute_case(
    case: CaseInput,
    provider: FirstSuccessProvider,
    *,
    ledger: Optional[FirstSuccessLedger] = None,
    offline_only: bool = True,
    allow_repair: bool = True,
) -> dict[str, Any]:
    """One primary and, after a structural failure, at most one structural repair."""
    active_ledger = ledger or FirstSuccessLedger()
    before = provider.actual_provider_operations
    primary_spec = protocol.build_primary_spec(case.case_id, case.prepared_input)
    primary_raw = _invoke_first_success(provider, active_ledger, primary_spec, offline_only=offline_only)
    primary_draft, batch, primary_validation = compile_raw_response(primary_raw, case)
    attempts = [{"phase": "primary", "spec": primary_spec, "raw": primary_raw, "draft": primary_draft,
                 "validation": primary_validation}]
    if not primary_validation["pass"] and allow_repair:
        if primary_validation["category"] not in protocol.REPAIR_ELIGIBLE_CATEGORIES:
            raise P4RunnerError("Semantic or quality retry is forbidden")
        repair_spec = protocol.build_repair_spec(
            case.case_id, case.prepared_input, primary_raw, primary_validation["diagnostic"]
        )
        repair_raw = _invoke_first_success(provider, active_ledger, repair_spec, offline_only=offline_only)
        repair_draft, batch, repair_validation = compile_raw_response(repair_raw, case)
        attempts.append({"phase": "repair_1", "spec": repair_spec, "raw": repair_raw, "draft": repair_draft,
                         "validation": repair_validation})
    terminal = attempts[-1]["validation"]
    return {
        "case_id": case.case_id,
        "attempts": attempts,
        "repair_count": len(attempts) - 1,
        "repair_allowed": allow_repair,
        "terminal_status": "STRUCTURAL_VALID" if terminal["pass"] else "STRUCTURAL_FAILURE",
        "terminal_validation": terminal,
        "compiled_batch": batch if terminal["pass"] else None,
        "actual_provider_operations": provider.actual_provider_operations - before,
        "quality_or_coverage_retries": 0,
    }


# ---------------------------------------------------------------------------
# Durable runtime
# ---------------------------------------------------------------------------

class BudgetedPacer:
    """The accepted persistent pacer with a hard, restart-persistent operation budget.

    The transport reserves one pacing slot immediately before each real provider call, so
    refusing a reservation refuses the call. Pacing behaviour is otherwise unchanged.
    """

    def __init__(self, pacer: PersistentRollingOperationPacer, budget: int) -> None:
        if type(budget) is not int or budget < 1:
            raise P4RunnerError("Operation budget must be a positive integer")
        self._pacer = pacer
        self.budget = budget
        self.refusals = 0

    def acquire(self) -> float:
        if int(self._pacer.snapshot()["reservation_count"]) >= self.budget:
            self.refusals += 1
            raise OperationBudgetExhausted("Real provider operation budget is exhausted")
        return self._pacer.acquire()

    def snapshot(self) -> dict[str, Any]:
        return {**self._pacer.snapshot(), "operation_budget": self.budget}


def select_locked_credential(config: Any) -> Any:
    """Return the single credential of the locked slot. No other slot can be selected."""
    selected = [item for item in config.credentials if item.slot_id == protocol.CREDENTIAL_SLOT]
    if len(selected) != 1:
        raise P4RunnerError("Locked credential slot is unavailable or ambiguous")
    return selected[0]


def build_durable_stack(
    checkpoint_root: Path, *, forbidden_secrets: tuple[str, ...] = ()
) -> tuple[PersistentRollingOperationPacer, DurableResearchExecutor]:
    """The accepted pacer and executor with the locked P4 limits and checkpoint identity."""
    pacer = PersistentRollingOperationPacer(
        checkpoint_root / "global_pacing.json",
        max_operations=protocol.GLOBAL_MAX_PROVIDER_OPERATIONS,
        window_seconds=protocol.GLOBAL_ROLLING_WINDOW_SECONDS,
    )
    executor = DurableResearchExecutor(
        checkpoint_root / "jobs",
        protocol_id=protocol.executor_protocol_id(),
        window_cooldown_seconds=protocol.WINDOW_COOLDOWN_SECONDS,
        forbidden_secrets=forbidden_secrets,
    )
    return pacer, executor


def build_guard() -> Callable[[], None]:
    """Re-verify the locked protocol and its bound files before every provider operation."""

    def guard() -> None:
        try:
            protocol.locked_protocol()
        except (protocol.P4ProtocolError, contract.OutputContractError, OSError) as error:
            raise CheckpointIntegrityError("Locked P4 protocol or a bound file changed") from error

    return guard


# ---------------------------------------------------------------------------
# Synthetic native-schema capability smoke
# ---------------------------------------------------------------------------

def synthetic_smoke_case() -> CaseInput:
    """One invented sentence, ingested by the frozen M3 adapter. Independent of every dataset."""
    data = SMOKE_TEXT.encode("utf-8")
    with tempfile.TemporaryDirectory() as directory:
        (Path(directory) / "unit.txt").write_bytes(data)
        manifest = {
            "contract_version": "LIGHT_NOVEL_INGESTION/v0",
            "story_id": "story-synthetic-p4-smoke",
            "stream_id": "stream-synthetic-p4-smoke",
            "source_language": "en",
            "documents": [{"document_id": "srcdoc-synthetic-p4-smoke", "order": 1, "path": "unit.txt",
                           "expected_sha256": hashlib.sha256(data).hexdigest()}],
        }
        ingestion = ingestion_adapter.ingest(manifest, Path(directory))
    segments = ingestion.documents[0].segments
    last = segments[-1]
    context = DraftCompilerContext(
        base_document=ingestion.canonical_skeleton(),
        passage_inputs=[{"use": "EVIDENCE_ELIGIBLE", "passage_ref": ingestion.passage_ref(segment["id"])}
                        for segment in segments],
        as_of_position={"stream_id": last["position"]["stream_id"], "key": last["position"]["key"]},
        profile_id="synthetic-p4-smoke-profile-v0",
        process_id=PROCESS_ID,
        process_version=PROCESS_VERSION,
        run_id=f"P4_{SMOKE_CASE_ID}",
        ingestion=ingestion,
    )
    return CaseInput(SMOKE_CASE_ID, prepare_story_extraction_draft_v1_1(context), context)


def _attempt_history(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [step for window in record.get("windows", []) for step in window.get("attempt_history", [])]


def _acceptance(record: Mapping[str, Any], budget_exhausted: bool) -> tuple[Any, Optional[str]]:
    """Whether the provider accepted the request, from sanitized transport metadata only.

    The accepted transport keeps the class, HTTP status and structured reason of a failure
    and discards its message. A 400 is therefore reported as a rejected request; which part
    of the request was rejected is not recorded by the transport.
    """
    if record.get("state") == JobState.SUCCEEDED_LOCKED.value:
        return True, None
    if budget_exhausted:
        return "UNDETERMINED", "OPERATION_BUDGET_EXHAUSTED_BY_TRANSIENT_FAILURES"
    history = _attempt_history(record)
    if not history:
        return "UNDETERMINED", "NO_PROVIDER_ATTEMPT_RECORDED"
    last = history[-1]
    category = f"{last.get('classified_result')}:{last.get('http_status')}:{last.get('provider_reason')}"
    if last.get("http_status") == 400:
        return False, category
    return "UNDETERMINED", category


def run_synthetic_smoke(
    *,
    private_root: Path = DEFAULT_SMOKE_ROOT,
    transport_factory: Optional[Callable[[BudgetedPacer, Callable[[], None]], Any]] = None,
    operation_budget: int = SMOKE_OPERATION_BUDGET,
) -> dict[str, Any]:
    """One primary job in one execution window. Without an injected transport this is live.

    A test injects ``transport_factory(pacer, guard)``. The live path builds the accepted
    transport on the locked credential. Either way the pacer refuses a reservation beyond
    the budget, so no more than ``operation_budget`` provider calls can start.
    """
    real = transport_factory is None
    root = private_root.resolve()
    repository = REPO_ROOT.resolve()
    if root == repository or (repository in root.parents and root.relative_to(repository).parts[0] != ".local"):
        raise P4RunnerError("Private artifacts must live under ignored local storage")
    if operation_budget > SMOKE_OPERATION_BUDGET:
        raise P4RunnerError("The smoke never exceeds two real provider operations")
    environment = verify_execution_environment() if real else None
    protocol.locked_protocol()
    guard = build_guard()
    case = synthetic_smoke_case()
    spec = protocol.build_primary_spec(case.case_id, case.prepared_input)
    protocol.assert_locked_job_spec(spec)

    checkpoints = root / "checkpoints"
    if any(checkpoints.glob("jobs/*.json")):
        raise P4RunnerError("A smoke job already exists; the smoke is not repeated")
    secrets: tuple[str, ...] = ()
    credential = None
    if real:
        try:
            config = load_runtime_config()
        except GeminiConfigError as error:
            raise P4RunnerError("Runtime credential configuration is invalid") from error
        credential = select_locked_credential(config)
        secrets = tuple(item._api_key for item in config.credentials)
    pacer, executor = build_durable_stack(checkpoints, forbidden_secrets=secrets)
    budgeted = BudgetedPacer(pacer, operation_budget)
    transport = (GeminiDevWindowTransport(credential, budgeted, guard) if real
                 else transport_factory(budgeted, guard))

    guard()
    budget_exhausted = False
    try:
        record = executor.execute_window(spec, transport)
    except CheckpointIntegrityError:
        # A refused reservation reaches here as the transport's accounting error.
        if not budgeted.refusals:
            raise
        budget_exhausted = True
        record = executor.load_job(spec)
    reservations = int(pacer.snapshot()["reservation_count"])
    if reservations > operation_budget:
        raise P4RunnerError("Real provider operation budget was exceeded")
    telemetry = _job_telemetry(record)
    accepted, rejection_category = _acceptance(record, budget_exhausted)
    received = record["state"] == JobState.SUCCEEDED_LOCKED.value
    result = {
        "artifact": SMOKE_RESULT_ID,
        "runner_id": RUNNER_ID,
        "protocol_id": protocol.PROTOCOL_ID,
        "protocol_sha256": protocol.PROTOCOL_SHA256,
        "synthetic_only": True,
        "case_id": case.case_id,
        "transport": "ACCEPTED_GEMINI_DEV_WINDOW_TRANSPORT" if real else "INJECTED_MOCK",
        "execution_environment": None if environment is None else environment["method"],
        "source_commit": None if environment is None else environment["source_commit"],
        "runner_sha256": protocol.normalized_file_sha256(REPO_ROOT / RUNNER_PATH),
        "protocol_module_sha256": protocol.normalized_file_sha256(REPO_ROOT / PROTOCOL_MODULE_PATH),
        "request_fingerprint": spec.request_fingerprint,
        "model": spec.model,
        "credential_slot": spec.credential_slot,
        "native_schema_sha256": protocol.MODEL_SCHEMA_SHA256,
        "execution_windows": int(record["window_count"]),
        "job_state": record["state"],
        "provider_operations": reservations,
        "checkpointed_provider_operations": int(record["total_provider_operations"]),
        "operation_budget": operation_budget,
        "operation_budget_exhausted": budget_exhausted,
        "provider_schema_request_accepted": accepted,
        "provider_rejection_category": rejection_category,
        "provider_response_received": received,
        # Stages C to E are None when they were not reached.
        "response_sha256": None,
        "json_parse": None,
        "local_schema_validation": None,
        "compiler": None,
        "structural_failure_category": None,
        "structural_finding_count": None,
        "repair_used": False,
        "repair_policy": "NOT_RUN_BY_SMOKE_DESIGN",
        "usage": telemetry.get("usage") or {},
        "provider_latency_seconds": telemetry.get("provider_latency_seconds"),
        "provider_reported_model_version": telemetry.get("provider_reported_model_version"),
        "pacing_invariant": pacer.snapshot()["invariant"],
        "dataset_accessed": False,
    }
    if received:
        raw = record["first_success"]["raw_response"]
        response_sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if response_sha256 != record["first_success"]["response_sha256"]:
            raise P4RunnerError("Locked response identity mismatch")
        draft, batch, validation = compile_raw_response(raw, case)
        _write_bytes_atomic(root / "raw" / f"{case.case_id}_primary.txt", raw.encode("utf-8"))
        if draft is not None:
            _write_bytes_atomic(root / "drafts" / f"{case.case_id}_primary.json", protocol.canonical_json_bytes(draft))
        if batch is not None:
            _write_bytes_atomic(root / "compiled" / f"{case.case_id}.json", protocol.canonical_json_bytes(batch))
        category = validation["category"]
        result.update({
            "response_sha256": response_sha256,
            "json_parse": category != "JSON_PARSE_FAILURE",
            "local_schema_validation": (None if category == "JSON_PARSE_FAILURE"
                                        else category != "DRAFT_SCHEMA_FAILURE"),
            "compiler": (None if category in ("JSON_PARSE_FAILURE", "DRAFT_SCHEMA_FAILURE")
                         else validation["pass"]),
            "structural_failure_category": category,
            "structural_finding_count": 0 if validation["diagnostic"] is None else validation["diagnostic"]["finding_count"],
        })
        if validation["diagnostic"] is not None:
            _write_bytes_atomic(root / "failures" / f"{case.case_id}.json",
                                protocol.canonical_json_bytes(validation["diagnostic"]))
    _write_bytes_atomic(root / f"{SMOKE_RESULT_ID}.json", protocol.canonical_json_bytes(result))
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("verify", "synthetic-smoke"), required=True)
    parser.add_argument("--private-root", type=Path, default=DEFAULT_SMOKE_ROOT)
    parser.add_argument("--authorize-live-provider-operations", default="")
    args = parser.parse_args(argv)
    try:
        if args.mode == "verify":
            protocol.locked_protocol()
            case = synthetic_smoke_case()
            protocol.assert_locked_job_spec(protocol.build_primary_spec(case.case_id, case.prepared_input))
            print(json.dumps({"protocol_sha256": protocol.PROTOCOL_SHA256, "provider_operations": 0,
                              "status": "P4_PROTOCOL_VERIFIED"}, sort_keys=True))
            return 0
        if args.authorize_live_provider_operations != SMOKE_AUTHORIZATION_TOKEN:
            raise P4RunnerError("The live smoke requires its explicit authorization token")
        result = run_synthetic_smoke(private_root=args.private_root)
    except (P4RunnerError, protocol.P4ProtocolError, contract.OutputContractError, CheckpointIntegrityError,
            RuntimeError) as error:
        print(f"M4_04B4B_SMOKE_STOPPED_FAIL_CLOSED: {type(error).__name__}", flush=True)
        return 2
    public = {key: result[key] for key in (
        "job_state", "provider_operations", "provider_schema_request_accepted", "provider_rejection_category",
        "provider_response_received", "json_parse", "local_schema_validation", "compiler",
        "structural_failure_category", "repair_used")}
    print(json.dumps(public, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
