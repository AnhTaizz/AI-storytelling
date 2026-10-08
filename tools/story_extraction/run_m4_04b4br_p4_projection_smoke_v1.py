"""Protocol V2 runner core and the two-stage native-schema capability smoke (M4-04B4BR).

Stage 1 asks whether the locked model and transport path accept a native response schema
at all, using a minimal schema of documented constructs. Stage 2 runs only if stage 1 is
accepted. It sends the exact provider projection as the native schema while the prompt
carries the full model schema.

Both stages are synthetic. Each may use one real provider operation; the total never
exceeds two. There is no repair call. The interpretation of every outcome is fixed in
this file and hash-locked before any request. Nothing here reads a dataset, accepts a
gold path or imports an evaluator. The historical protocol V1 runner is not modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from jsonschema import Draft202012Validator

from tools.story_extraction import m4_04b4b_p4_protocol_v1 as protocol_v1
from tools.story_extraction import m4_04b4br_p4_protocol_v2 as protocol
from tools.story_extraction import project_draft_v1_1_model_schema_to_gemini_v1 as projection
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
from tools.story_extraction.run_m4_04b4b_p4_structural_v1 import (
    BudgetedPacer,
    P4RunnerError,
    compile_raw_response,
    synthetic_smoke_case,
)


RUNNER_ID = "M4_04B4BR_P4_PROJECTION_SMOKE_RUNNER_V1"
RUNNER_PATH = "tools/story_extraction/run_m4_04b4br_p4_projection_smoke_v1.py"
PROTOCOL_MODULE_PATH = "tools/story_extraction/m4_04b4br_p4_protocol_v2.py"
PROJECTION_TOOL_PATH = "tools/story_extraction/project_draft_v1_1_model_schema_to_gemini_v1.py"
REPO_ROOT = protocol.REPO_ROOT
DEFAULT_SMOKE_ROOT = REPO_ROOT / ".local/m4_04b4br_p4_projection_smoke"
HISTORICAL_V1_SMOKE_ROOT_NAME = "m4_04b4b_p4_synthetic_smoke"
SMOKE_AUTHORIZATION_TOKEN = "M4-04B4BR-TWO-STAGE-SMOKE"
SMOKE_RESULT_ID = "M4_04B4BR_TWO_STAGE_SMOKE_RESULT_V1"

EXPERIMENT_ID = "M4_04B4BR_TWO_STAGE_NATIVE_SCHEMA_CAPABILITY_EXPERIMENT_V1"
# SHA-256 of canonical_json_bytes(build_experiment()). Fixed before any live request.
EXPERIMENT_SHA256 = "71cea1f4e603995ffd7466e16fd2fbb3034fed7935c581f890cc81f13f01cdc0"
TOTAL_OPERATION_BUDGET = 2
STAGE_OPERATION_BUDGET = 1

STAGE1_JOB_ID = "M4B4BR_STAGE1_MINIMAL_NATIVE_SCHEMA"
STAGE1_RESPONSE_MODE = "PROVIDER_JSON_MIME_PLUS_NATIVE_MINIMAL_BASELINE_SCHEMA_V1"
STAGE1_SYSTEM = "Return one JSON object with exactly one field named status. Its value is the string OK."
STAGE1_USER = "Synthetic capability check. Return the status object."
STAGE1_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status"],
    "properties": {"status": {"type": "string", "enum": ["OK"]}},
}

ACCEPTED = "ACCEPTED"
REJECTED = "REJECTED_HTTP_400"
UNDETERMINED = "UNDETERMINED"
NOT_RUN = "NOT_RUN"
_DASH = chr(0x2014)
STATUS_READY = "M4_04B4BR_PROVIDER_PROJECTION_READY"
STATUS_MINIMAL_REJECTED = "M4_04B4BR_MINIMAL_NATIVE_SCHEMA_REJECTED"
STATUS_PROJECTION_REJECTED = "M4_04B4BR_P4_PROJECTION_REJECTED"
NEXT_READY = (
    f"M4-04B4C {_DASH} P4 STRUCTURAL TUNING RUN ON DEV3 INPUT USING PROTOCOL V2 AND EXACT PROVIDER PROJECTION"
)
NEXT_MINIMAL_REJECTED = f"ORCHESTRATOR REVIEW {_DASH} P4 JSON-MIME-ONLY RUNTIME"
NEXT_PROJECTION_REJECTED = f"ORCHESTRATOR REVIEW {_DASH} PROVIDER PROJECTION INCOMPATIBILITY"
NEXT_UNDETERMINED = f"ORCHESTRATOR REVIEW {_DASH} CAPABILITY SMOKE UNDETERMINED"

INTERPRETATION_MATRIX = {
    "stage_outcomes": {
        ACCEPTED: "The provider accepted the request and returned a response. The job is locked as a first success.",
        REJECTED: "The provider answered HTTP 400 and the transport classified it as a provider failure, "
                  "not as an authentication failure.",
        UNDETERMINED: "Anything else: a transient, rate-limit, timeout, network or authentication outcome, "
                      "or an exhausted operation budget. No capability claim follows.",
    },
    "stage2_runs_only_if_stage1_is": ACCEPTED,
    "stage2_local_stages_do_not_change_the_capability_verdict": True,
    "stage2_projection_pass_with_full_validation_fail_means_projection_is_defective": False,
    "cases": {
        "CASE_A": {
            "when": {"stage1": REJECTED, "stage2": NOT_RUN},
            "status": STATUS_MINIMAL_REJECTED,
            "conclusion": "NATIVE_SCHEMA_PARAMETER_OR_MINIMAL_SCHEMA_NOT_ACCEPTED_ON_LOCKED_MODEL_PATH",
            "native_schema_runtime_capability": "NOT_ESTABLISHED",
            "provider_projection_compatible": "NOT_TESTED",
            "ready_for_DEV3_tuning": False,
            "next_action": NEXT_MINIMAL_REJECTED,
        },
        "CASE_B": {
            "when": {"stage1": ACCEPTED, "stage2": REJECTED},
            "status": STATUS_PROJECTION_REJECTED,
            "conclusion": "NATIVE_SCHEMA_WORKS_IN_PRINCIPLE_BUT_P4_PROVIDER_PROJECTION_IS_PROVIDER_INCOMPATIBLE",
            "native_schema_runtime_capability": "ESTABLISHED_FOR_MINIMAL_SCHEMA",
            "provider_projection_compatible": False,
            "ready_for_DEV3_tuning": False,
            "next_action": NEXT_PROJECTION_REJECTED,
        },
        "CASE_C": {
            "when": {"stage1": ACCEPTED, "stage2": ACCEPTED},
            "status": STATUS_READY,
            "conclusion": "PROVIDER_PROJECTION_RUNTIME_PATH_ESTABLISHED",
            "native_schema_runtime_capability": "ESTABLISHED",
            "provider_projection_compatible": True,
            "ready_for_DEV3_tuning": True,
            "next_action": NEXT_READY,
        },
        "UNDETERMINED": {
            "when": "ANY_OTHER_COMBINATION",
            "status": None,
            "conclusion": "CAPABILITY_NOT_DETERMINED_BY_THIS_SMOKE",
            "native_schema_runtime_capability": "NOT_DETERMINED",
            "provider_projection_compatible": "NOT_DETERMINED",
            "ready_for_DEV3_tuning": False,
            "next_action": NEXT_UNDETERMINED,
        },
    },
    "no_outcome_is_an_extraction_quality_result": True,
}


class OperationBudgetViolation(P4RunnerError):
    """More real provider operations were observed than a stage or the task allows."""


# ---------------------------------------------------------------------------
# Experiment lock
# ---------------------------------------------------------------------------

def stage1_generation_config() -> dict[str, Any]:
    """Protocol V2 settings with the minimal baseline schema as the native schema."""
    return {
        "temperature": protocol.TEMPERATURE,
        "max_output_tokens": protocol.MAX_OUTPUT_TOKENS,
        "response_json_schema": json.loads(json.dumps(STAGE1_SCHEMA)),
    }


def build_stage1_spec() -> DurableJobSpec:
    return DurableJobSpec(
        job_id=STAGE1_JOB_ID,
        model=protocol.MODEL,
        system_prompt=STAGE1_SYSTEM,
        user_prompt=STAGE1_USER,
        generation_config=stage1_generation_config(),
        schema_response_mode=STAGE1_RESPONSE_MODE,
        credential_slot=protocol.CREDENTIAL_SLOT,
        research_task_id=EXPERIMENT_ID,
    )


def assert_stage1_spec(spec: DurableJobSpec) -> None:
    """The stage 1 request is one fixed request. Any difference fails closed."""
    expected = build_stage1_spec()
    if (
        spec.job_id != expected.job_id
        or spec.identity_payload() != expected.identity_payload()
        or type(spec.generation_config.get("temperature")) is not int
    ):
        raise P4RunnerError("Stage 1 request differs from the locked minimal baseline request")


def build_stage2_spec() -> tuple[CaseInput, DurableJobSpec]:
    """The projected P4 request on the synthetic fixture of the historical V1 smoke."""
    case = synthetic_smoke_case()
    spec = protocol.build_primary_spec(case.case_id, case.prepared_input)
    protocol.assert_locked_job_spec(spec)
    return case, spec


def stage2_isolation() -> dict[str, bool]:
    """Stage 2 differs from the request protocol V1 had rejected only in its native schema."""
    case, spec = build_stage2_spec()
    rejected = protocol_v1.build_primary_spec(case.case_id, case.prepared_input)
    ours, theirs = dict(spec.generation_config), dict(rejected.generation_config)
    native = ours.pop("response_json_schema")
    full = theirs.pop("response_json_schema")
    return {
        "same_system_prompt": spec.system_prompt == rejected.system_prompt,
        "same_user_prompt": spec.user_prompt == rejected.user_prompt,
        "same_model_and_credential_slot": (spec.model, spec.credential_slot) == (rejected.model, rejected.credential_slot),
        "same_other_generation_settings": ours == theirs,
        "native_schema_is_projection_of_rejected_native_schema": native == projection.project(full)[0],
        "native_schema_differs": native != full,
    }


def build_experiment() -> dict[str, Any]:
    _, stage2 = build_stage2_spec()
    stage1 = build_stage1_spec()
    return {
        "experiment_id": EXPERIMENT_ID,
        "task_id": protocol.TASK_ID,
        "protocol_id": protocol.PROTOCOL_ID,
        "protocol_sha256": protocol.PROTOCOL_SHA256,
        "synthetic_only": True,
        "operation_budget": {"total": TOTAL_OPERATION_BUDGET, "per_stage": STAGE_OPERATION_BUDGET},
        "execution_windows_per_stage": 1,
        "repair_calls": 0,
        "model": protocol.MODEL,
        "credential_slot": protocol.CREDENTIAL_SLOT,
        "transport": "GeminiDevWindowTransport",
        "provider_error_message_capture": "FORBIDDEN",
        "stage1": {
            "purpose": "DOES_THE_LOCKED_MODEL_AND_TRANSPORT_PATH_ACCEPT_A_NATIVE_RESPONSE_SCHEMA_AT_ALL",
            "job_id": stage1.job_id,
            "request_fingerprint": stage1.request_fingerprint,
            "native_schema": STAGE1_SCHEMA,
            "uses_draft_v1_1": False,
            "schema_response_mode": STAGE1_RESPONSE_MODE,
        },
        "stage2": {
            "purpose": "DOES_THE_PROVIDER_ACCEPT_THE_EXACT_P4_PROVIDER_PROJECTION",
            "job_id": stage2.job_id,
            "request_fingerprint": stage2.request_fingerprint,
            "prompt_schema_sha256": protocol.FULL_MODEL_SCHEMA_SHA256,
            "native_schema_sha256": protocol.PROVIDER_PROJECTION_SHA256,
            "isolation_from_rejected_protocol_v1_request": stage2_isolation(),
            "recorded_independently": [
                "A_PROVIDER_REQUEST_ACCEPTED", "B_RESPONSE_RECEIVED", "C_JSON_PARSE",
                "D_PROVIDER_PROJECTION_VALIDATION", "E_FULL_LOCAL_DRAFT_V1_1_VALIDATION", "F_COMPILER",
            ],
        },
        "interpretation_matrix": INTERPRETATION_MATRIX,
    }


def experiment_sha256() -> str:
    return hashlib.sha256(protocol.canonical_json_bytes(build_experiment())).hexdigest()


def locked_experiment() -> dict[str, Any]:
    """Return the experiment only while protocol V2 and every experiment binding are exact."""
    protocol.locked_protocol()
    try:
        used = projection.assert_provider_subset(json.loads(json.dumps(STAGE1_SCHEMA)))
    except projection.ProjectionError as error:
        raise P4RunnerError("Stage 1 schema leaves the documented provider subset") from error
    if "$ref" in used["keywords_used"] or not all(stage2_isolation().values()):
        raise P4RunnerError("Stage definitions differ from the locked experiment")
    assert_stage1_spec(build_stage1_spec())
    experiment = build_experiment()
    if hashlib.sha256(protocol.canonical_json_bytes(experiment)).hexdigest() != EXPERIMENT_SHA256:
        raise P4RunnerError("Experiment differs from the locked two-stage experiment")
    return experiment


def experiment_executor_id() -> str:
    return EXPERIMENT_ID + ":" + EXPERIMENT_SHA256


def interpret(stage1_outcome: str, stage2_outcome: str) -> dict[str, Any]:
    """Map the two stage outcomes to one locked case. Anything unlisted is UNDETERMINED."""
    for name in ("CASE_A", "CASE_B", "CASE_C"):
        case = INTERPRETATION_MATRIX["cases"][name]
        if case["when"] == {"stage1": stage1_outcome, "stage2": stage2_outcome}:
            return {"case": name, **{key: value for key, value in case.items() if key != "when"}}
    case = INTERPRETATION_MATRIX["cases"]["UNDETERMINED"]
    return {"case": "UNDETERMINED", **{key: value for key, value in case.items() if key != "when"}}


# ---------------------------------------------------------------------------
# Protocol V2 case execution (offline core for a later tuning run)
# ---------------------------------------------------------------------------

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
    """One primary and, after a structural failure, at most one structural repair.

    Validity is decided by the unchanged full validator and compiler. The provider
    projection is never used to accept or reject a draft.
    """
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

def select_locked_credential(config: Any) -> Any:
    """Return the single credential of the locked slot. No other slot can be selected."""
    selected = [item for item in config.credentials if item.slot_id == protocol.CREDENTIAL_SLOT]
    if len(selected) != 1:
        raise P4RunnerError("Locked credential slot is unavailable or ambiguous")
    return selected[0]


def build_durable_stack(
    checkpoint_root: Path, *, forbidden_secrets: tuple[str, ...] = ()
) -> tuple[PersistentRollingOperationPacer, DurableResearchExecutor, DurableResearchExecutor]:
    """One shared pacer and one executor per stage, each with its own checkpoint identity."""
    pacer = PersistentRollingOperationPacer(
        checkpoint_root / "global_pacing.json",
        max_operations=protocol.GLOBAL_MAX_PROVIDER_OPERATIONS,
        window_seconds=protocol.GLOBAL_ROLLING_WINDOW_SECONDS,
    )
    stage1 = DurableResearchExecutor(
        checkpoint_root / "stage1_jobs",
        protocol_id=experiment_executor_id(),
        window_cooldown_seconds=protocol.WINDOW_COOLDOWN_SECONDS,
        forbidden_secrets=forbidden_secrets,
    )
    stage2 = DurableResearchExecutor(
        checkpoint_root / "stage2_jobs",
        protocol_id=protocol.executor_protocol_id(),
        window_cooldown_seconds=protocol.WINDOW_COOLDOWN_SECONDS,
        forbidden_secrets=forbidden_secrets,
    )
    return pacer, stage1, stage2


def build_guard() -> Callable[[], None]:
    """Re-verify protocol V2 and the experiment lock before every provider operation."""

    def guard() -> None:
        try:
            locked_experiment()
        except (P4RunnerError, protocol.P4ProtocolV2Error, protocol_v1.P4ProtocolError, OSError, RuntimeError) as error:
            raise CheckpointIntegrityError("Locked protocol V2, experiment or a bound file changed") from error

    return guard


# ---------------------------------------------------------------------------
# Two-stage synthetic capability smoke
# ---------------------------------------------------------------------------

def _attempt_history(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [step for window in record.get("windows", []) for step in window.get("attempt_history", [])]


def _classify(record: Mapping[str, Any], budget_exhausted: bool) -> tuple[str, Optional[str]]:
    """Stage outcome and sanitized category, from transport metadata only. No message is read."""
    if record.get("state") == JobState.SUCCEEDED_LOCKED.value:
        return ACCEPTED, None
    if budget_exhausted:
        return UNDETERMINED, "OPERATION_BUDGET_EXHAUSTED_BY_TRANSIENT_FAILURE"
    history = _attempt_history(record)
    if not history:
        return UNDETERMINED, "NO_PROVIDER_ATTEMPT_RECORDED"
    last = history[-1]
    category = f"{last.get('classified_result')}:{last.get('http_status')}:{last.get('provider_reason')}"
    if last.get("http_status") == 400 and last.get("classified_result") == "PROVIDER_FAILURE":
        return REJECTED, category
    return UNDETERMINED, category


def _run_stage(
    executor: DurableResearchExecutor,
    spec: DurableJobSpec,
    pacer: PersistentRollingOperationPacer,
    make_transport: Callable[[BudgetedPacer], Any],
) -> dict[str, Any]:
    """One execution window with at most one real provider operation."""
    used = int(pacer.snapshot()["reservation_count"])
    if used + STAGE_OPERATION_BUDGET > TOTAL_OPERATION_BUDGET:
        raise OperationBudgetViolation("The task operation budget leaves no operation for this stage")
    budgeted = BudgetedPacer(pacer, used + STAGE_OPERATION_BUDGET)
    transport = make_transport(budgeted)
    exhausted = False
    try:
        record = executor.execute_window(spec, transport)
    except CheckpointIntegrityError:
        # A refused reservation reaches here as the transport's accounting error.
        if not budgeted.refusals:
            raise
        exhausted = True
        record = executor.load_job(spec)
    operations = int(pacer.snapshot()["reservation_count"]) - used
    if operations > STAGE_OPERATION_BUDGET:
        raise OperationBudgetViolation("A stage used more than one real provider operation")
    outcome, category = _classify(record, exhausted)
    telemetry = _job_telemetry(record)
    return {
        "executed": True,
        "job_id": spec.job_id,
        "request_fingerprint": spec.request_fingerprint,
        "job_state": record["state"],
        "execution_windows": int(record["window_count"]),
        "provider_operations": operations,
        "operation_budget_exhausted": exhausted,
        "outcome": outcome,
        "provider_request_accepted": {ACCEPTED: True, REJECTED: False}.get(outcome, UNDETERMINED),
        "provider_rejection_category": category,
        "response_received": outcome == ACCEPTED,
        "usage": telemetry.get("usage") or {},
        "provider_latency_seconds": telemetry.get("provider_latency_seconds"),
        "provider_reported_model_version": telemetry.get("provider_reported_model_version"),
        "_record": record,
    }


def _locked_response(stage: dict[str, Any]) -> str:
    success = stage.pop("_record")["first_success"]
    raw = success["raw_response"]
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if digest != success["response_sha256"]:
        raise P4RunnerError("Locked response identity mismatch")
    stage["response_sha256"] = digest
    return raw


def _validate_private_root(private_root: Path) -> Path:
    root = private_root.resolve()
    repository = REPO_ROOT.resolve()
    if root == repository or (repository in root.parents and root.relative_to(repository).parts[0] != ".local"):
        raise P4RunnerError("Private artifacts must live under ignored local storage")
    lowered = [part.lower() for part in root.parts]
    if any(marker in part for part in lowered[-2:] for marker in ("dev3", "holdout", "gold")):
        raise P4RunnerError("A dataset location is not accepted by this smoke")
    if HISTORICAL_V1_SMOKE_ROOT_NAME in lowered:
        raise P4RunnerError("The historical protocol V1 smoke root is not reused")
    return root


def run_two_stage_smoke(
    *,
    private_root: Path = DEFAULT_SMOKE_ROOT,
    transport_factory: Optional[Callable[[BudgetedPacer, Callable[[], None]], Any]] = None,
) -> dict[str, Any]:
    """Stage 1, then stage 2 only if stage 1 was accepted. Without an injected transport this is live.

    A test injects ``transport_factory(pacer, guard)``. The live path builds the accepted
    transport on the locked credential. The pacer refuses a second reservation inside a
    stage and a third in total, so the operation limits hold whatever the transport does.
    """
    real = transport_factory is None
    root = _validate_private_root(private_root)
    environment = verify_execution_environment() if real else None
    experiment = locked_experiment()
    guard = build_guard()
    stage1_spec = build_stage1_spec()
    assert_stage1_spec(stage1_spec)
    case, stage2_spec = build_stage2_spec()

    checkpoints = root / "checkpoints"
    if checkpoints.exists() and any(checkpoints.rglob("*.json")):
        raise P4RunnerError("Smoke state already exists; the smoke is not repeated")
    secrets: tuple[str, ...] = ()
    credential = None
    if real:
        try:
            config = load_runtime_config()
        except GeminiConfigError as error:
            raise P4RunnerError("Runtime credential configuration is invalid") from error
        credential = select_locked_credential(config)
        secrets = tuple(item._api_key for item in config.credentials)
    pacer, stage1_executor, stage2_executor = build_durable_stack(checkpoints, forbidden_secrets=secrets)

    def make_transport(budgeted: BudgetedPacer) -> Any:
        if real:
            return GeminiDevWindowTransport(credential, budgeted, guard)
        return transport_factory(budgeted, guard)

    guard()
    stage1 = _run_stage(stage1_executor, stage1_spec, pacer, make_transport)
    stage1.update({"response_sha256": None, "json_parse": None, "matches_minimal_schema": None})
    if stage1["outcome"] == ACCEPTED:
        raw = _locked_response(stage1)
        _write_bytes_atomic(root / "raw" / "stage1_response.txt", raw.encode("utf-8"))
        try:
            parsed = json.loads(raw)
            stage1["json_parse"] = True
            stage1["matches_minimal_schema"] = Draft202012Validator(STAGE1_SCHEMA).is_valid(parsed)
        except json.JSONDecodeError:
            stage1["json_parse"] = False
    stage1.pop("_record", None)
    stage1["minimal_native_schema_accepted"] = stage1["provider_request_accepted"]

    if stage1["outcome"] == ACCEPTED:
        guard()
        stage2 = _run_stage(stage2_executor, stage2_spec, pacer, make_transport)
        stage2.update({
            "response_sha256": None, "json_parse": None, "provider_projection_validation": None,
            "full_local_draft_v1_1_validation": None, "compiler": None,
            "structural_failure_category": None, "structural_finding_count": None,
        })
        if stage2["outcome"] == ACCEPTED:
            raw = _locked_response(stage2)
            _write_bytes_atomic(root / "raw" / "stage2_response.txt", raw.encode("utf-8"))
            draft, batch, validation = compile_raw_response(raw, case)
            category = validation["category"]
            parsed_ok = category != "JSON_PARSE_FAILURE"
            stage2.update({
                "json_parse": parsed_ok,
                "provider_projection_validation": (
                    Draft202012Validator(protocol.native_response_schema()).is_valid(draft) if parsed_ok else None
                ),
                "full_local_draft_v1_1_validation": category != "DRAFT_SCHEMA_FAILURE" if parsed_ok else None,
                "compiler": validation["pass"] if category in (None, "DRAFT_COMPILER_FAILURE") else None,
                "structural_failure_category": category,
                "structural_finding_count": (
                    0 if validation["diagnostic"] is None else validation["diagnostic"]["finding_count"]
                ),
            })
            if draft is not None:
                _write_bytes_atomic(root / "drafts" / "stage2_draft.json", protocol.canonical_json_bytes(draft))
            if batch is not None:
                _write_bytes_atomic(root / "compiled" / "stage2_compiled.json", protocol.canonical_json_bytes(batch))
            if validation["diagnostic"] is not None:
                _write_bytes_atomic(root / "failures" / "stage2_diagnostic.json",
                                    protocol.canonical_json_bytes(validation["diagnostic"]))
        stage2.pop("_record", None)
    else:
        stage2 = {"executed": False, "outcome": NOT_RUN, "provider_operations": 0,
                  "reason": "STAGE_1_WAS_NOT_ACCEPTED", "job_id": stage2_spec.job_id}
        if any((checkpoints / "stage2_jobs").glob("*.json")):
            raise P4RunnerError("Stage 2 state exists although stage 1 was not accepted")

    operations = int(pacer.snapshot()["reservation_count"])
    if operations > TOTAL_OPERATION_BUDGET or operations != stage1["provider_operations"] + stage2["provider_operations"]:
        raise OperationBudgetViolation("Real provider operation accounting does not match the budget")
    result = {
        "artifact": SMOKE_RESULT_ID,
        "runner_id": RUNNER_ID,
        "experiment_id": experiment["experiment_id"],
        "experiment_sha256": EXPERIMENT_SHA256,
        "protocol_id": protocol.PROTOCOL_ID,
        "protocol_sha256": protocol.PROTOCOL_SHA256,
        "full_model_schema_sha256": protocol.FULL_MODEL_SCHEMA_SHA256,
        "provider_projection_sha256": protocol.PROVIDER_PROJECTION_SHA256,
        "runner_sha256": protocol.normalized_file_sha256(REPO_ROOT / RUNNER_PATH),
        "protocol_module_sha256": protocol.normalized_file_sha256(REPO_ROOT / PROTOCOL_MODULE_PATH),
        "projection_tool_sha256": protocol.normalized_file_sha256(REPO_ROOT / PROJECTION_TOOL_PATH),
        "synthetic_only": True,
        "dataset_accessed": False,
        "transport": "ACCEPTED_GEMINI_DEV_WINDOW_TRANSPORT" if real else "INJECTED_MOCK",
        "execution_environment": None if environment is None else environment["method"],
        "source_commit": None if environment is None else environment["source_commit"],
        "model": protocol.MODEL,
        "credential_slot": protocol.CREDENTIAL_SLOT,
        "operation_budget": TOTAL_OPERATION_BUDGET,
        "provider_operations": operations,
        "repair_calls": 0,
        "pacing_invariant": pacer.snapshot()["invariant"],
        "stage1": stage1,
        "stage2": stage2,
        "stage2_isolation_from_rejected_protocol_v1_request": stage2_isolation(),
        "verdict": interpret(stage1["outcome"], stage2["outcome"]),
    }
    _write_bytes_atomic(root / f"{SMOKE_RESULT_ID}.json", protocol.canonical_json_bytes(result))
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("verify", "two-stage-smoke"), required=True)
    parser.add_argument("--private-root", type=Path, default=DEFAULT_SMOKE_ROOT)
    parser.add_argument("--authorize-live-provider-operations", default="")
    args = parser.parse_args(argv)
    try:
        if args.mode == "verify":
            locked_experiment()
            print(json.dumps({"experiment_sha256": EXPERIMENT_SHA256, "protocol_sha256": protocol.PROTOCOL_SHA256,
                              "provider_operations": 0, "status": "P4_PROTOCOL_V2_AND_EXPERIMENT_VERIFIED"},
                             sort_keys=True))
            return 0
        if args.authorize_live_provider_operations != SMOKE_AUTHORIZATION_TOKEN:
            raise P4RunnerError("The live smoke requires its explicit authorization token")
        result = run_two_stage_smoke(private_root=args.private_root)
    except (CheckpointIntegrityError, RuntimeError) as error:
        print(f"M4_04B4BR_SMOKE_STOPPED_FAIL_CLOSED: {type(error).__name__}", flush=True)
        return 2
    public = {
        "provider_operations": result["provider_operations"],
        "stage1": {key: result["stage1"].get(key) for key in (
            "outcome", "provider_operations", "provider_rejection_category", "json_parse", "matches_minimal_schema")},
        "stage2": {key: result["stage2"].get(key) for key in (
            "outcome", "provider_operations", "provider_rejection_category", "json_parse",
            "provider_projection_validation", "full_local_draft_v1_1_validation", "compiler",
            "structural_failure_category")},
        "case": result["verdict"]["case"],
        "status": result["verdict"]["status"],
    }
    print(json.dumps(public, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
