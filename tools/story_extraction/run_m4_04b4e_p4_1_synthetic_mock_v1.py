"""Offline synthetic mock harness for the P4.1 runtime protocol candidate (M4-04B4E).

SYNTHETIC_MOCK_ONLY_NOT_PROVIDER_EVIDENCE.

Exercises the whole extraction, validation and repair path of the proposed protocol
without a provider: the P4.1 V1.1 request builders and checker, the unchanged Draft V1.1
validator and compiler, structural diagnostic V3.1, the repair-actionability rule, the
accepted durable executor and persistent pacer, a hard synthetic operation budget, and
the retention metrics.

The transport is a scripted fake that is injected. It holds no credential and no client,
and this module imports no provider SDK, no credential loader and no accepted Gemini
transport, so no network request can be made through it. Time is a virtual clock: the
harness never sleeps and reads no wall clock, which also makes every artifact
reproducible. The inputs are one invented sentence and hand-written drafts defined in
this file; no path to a dataset is accepted anywhere.

Nothing a run reports is provider evidence. No latency, token usage or cost is invented.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable, Mapping, Optional, Sequence

from jsonschema import Draft202012Validator

from tools.story_extraction import m4_04b4d_f1_structural_diagnostic_v3_1 as diagnostic_v3_1
from tools.story_extraction import m4_04b4e_p4_1_retention_metrics_v1 as retention
from tools.story_extraction import m4_04b4e_p4_1_runtime_protocol_candidate_v1 as protocol
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import (
    DraftCompilationErrorV1_1,
    compile_story_extraction_draft_v1_1,
    prepare_story_extraction_draft_v1_1,
    validate_draft_v1_1,
)
from tools.story_extraction.durable_research_executor_v1 import (
    DEFER_ELIGIBLE_CATEGORIES,
    AtomicIntegrityJsonStore,
    CheckpointIntegrityError,
    CooldownPending,
    DurableJobSpec,
    DurableResearchExecutor,
    DurableTransportFailure,
    JobState,
    PersistentRollingOperationPacer,
    summarize_job,
)
from tools.story_extraction.m4_04b4b_p4_protocol_v1 import canonical_json_bytes, normalized_file_sha256, sha256_bytes
from tools.story_ingestion import light_novel_adapter_v0 as ingestion_adapter


RUNNER_ID = "M4_04B4E_P4_1_SYNTHETIC_MOCK_HARNESS_V1"
RUNNER_PATH = "tools/story_extraction/run_m4_04b4e_p4_1_synthetic_mock_v1.py"
EVIDENCE_LABEL = "SYNTHETIC_MOCK_ONLY_NOT_PROVIDER_EVIDENCE"
REPO_ROOT = protocol.REPO_ROOT
PROCESS_ID = "M4_04B4E_P4_1_MOCK"
PROCESS_VERSION = "v1"
RUN_MANIFEST_ID = "M4_04B4E_SYNTHETIC_MOCK_RUN_MANIFEST_V1"
CASE_RESULT_ID = "M4_04B4E_SYNTHETIC_MOCK_CASE_RESULT_V1"
SCENARIO_SUMMARY_ID = "M4_04B4E_SYNTHETIC_MOCK_SCENARIO_SUMMARY_V1"
RUN_SUMMARY_ID = "M4_04B4E_SYNTHETIC_MOCK_RUN_SUMMARY_V1"
BUDGET_ID = "M4_04B4E_SYNTHETIC_OPERATION_BUDGET_V1"
# Virtual time. A fixed starting instant and a fixed step per mock operation; neither is a measurement.
VIRTUAL_EPOCH = 1_900_000_000.0
VIRTUAL_SECONDS_PER_OPERATION = 1.0
MAX_SYNTHETIC_BUDGET = 64
PRIVATE_DIRECTORIES = (
    "checkpoints", "raw_primary", "raw_repair", "drafts", "diagnostics", "compiled", "case_results", "summaries",
)
ALLOWED_LOCAL_ROOT_PREFIX = "m4_04b4e_synthetic_mock"
FORBIDDEN_ROOT_MARKERS = (
    "dev3", "dev4", "gold", "holdout", "authoring", "predictions", "m4_04b3", "m4_04b4b", "m4_04b4c",
    "smoke",
)
CREDENTIAL_NAME_PATTERN = re.compile(r"GEMINI|GOOGLE|GENAI|VERTEX", re.IGNORECASE)
MOCK_SUCCESS = "SUCCESS"
MOCK_PROCESS_DEATH = "PROCESS_DEATH"
MOCK_TRANSIENT_FAILURES = ("SERVER_FAILURE", "TIMEOUT", "NETWORK_FAILURE", "RATE_LIMIT")

STATUS_COMPLETE = "MOCK_RUN_COMPLETE"
STATUS_BUDGET_EXHAUSTED = "MOCK_RUN_STOPPED_SYNTHETIC_BUDGET_EXHAUSTED"
STATUS_INTERRUPTED = "MOCK_RUN_INTERRUPTED_REQUIRES_CHECKPOINT_REVIEW"
STATUS_FAIL_CLOSED = "MOCK_RUN_STOPPED_FAIL_CLOSED"
SKIP_POLICY_UNRESOLVED = "PARTIALLY_DESCRIBED_DIAGNOSTIC_AND_THE_INTERIM_POLICY_REFUSES_REPAIR"


class MockHarnessError(RuntimeError):
    """A fail-closed harness, fixture, budget or artifact error."""


class PriorExecutionState(MockHarnessError):
    """The private root already holds execution state. A run never overwrites or silently resumes it."""


class SyntheticBudgetExhausted(CheckpointIntegrityError):
    """The synthetic operation budget was reached before another mock operation."""


class SimulatedInterruption(BaseException):
    """A simulated process death. Not an Exception, so nothing between the transport and the top catches it."""


# A scripted transient failure must be one the accepted executor defers, so a mock window behaves like a real one.
if not set(MOCK_TRANSIENT_FAILURES) <= DEFER_ELIGIBLE_CATEGORIES:
    raise MockHarnessError("A scripted transient failure is not a category the durable executor defers")


# ---------------------------------------------------------------------------
# Isolation guards
# ---------------------------------------------------------------------------

def assert_no_provider_credentials(environment: Mapping[str, str]) -> None:
    """The mock harness does not run in a process that holds provider credential variables."""
    held = sorted(name for name, value in environment.items() if value and CREDENTIAL_NAME_PATTERN.search(name))
    if held:
        raise MockHarnessError(f"Provider credential variables are present in the process: {len(held)}")


def assert_isolated_private_root(private_root: Path) -> Path:
    """A private root must be isolated storage that no experiment, dataset or credential uses."""
    root = Path(private_root).resolve()
    repository = REPO_ROOT.resolve()
    if root == repository or root in repository.parents:
        raise MockHarnessError("The private root must not contain the repository")
    if repository in root.parents:
        relative = root.relative_to(repository).parts
        if relative[0] != ".local" or len(relative) < 2 or not relative[1].startswith(ALLOWED_LOCAL_ROOT_PREFIX):
            raise MockHarnessError("Inside the repository a mock root must be ignored storage of this harness")
        scanned = relative[1:]
    else:
        scanned = root.parts[-3:]
    lowered = [part.lower().replace(ALLOWED_LOCAL_ROOT_PREFIX, "") for part in scanned]
    if any(marker in part for part in lowered for marker in FORBIDDEN_ROOT_MARKERS):
        raise MockHarnessError("A dataset, gold, holdout or foreign experiment location is not accepted")
    return root


def private_layout(private_root: Path) -> dict[str, Path]:
    root = assert_isolated_private_root(private_root)
    layout = {name: root / name for name in PRIVATE_DIRECTORIES}
    for path in layout.values():
        path.mkdir(parents=True, exist_ok=True)
    layout["root"] = root
    return layout


def existing_execution_state(layout: Mapping[str, Path]) -> list[str]:
    found = [name for name in PRIVATE_DIRECTORIES if any(path.is_file() for path in layout[name].rglob("*"))]
    if (layout["root"] / f"{RUN_MANIFEST_ID}.json").exists():
        found.append(RUN_MANIFEST_ID)
    return found


def _write_once(path: Path, data: bytes) -> str:
    """Write an immutable private artifact. An existing different artifact is an error."""
    if path.exists():
        if path.read_bytes() != data:
            raise MockHarnessError("Immutable private artifact differs: " + path.name)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
    return sha256_bytes(data)


# ---------------------------------------------------------------------------
# Virtual time, synthetic budget and the mock transport
# ---------------------------------------------------------------------------

class VirtualClock:
    """Deterministic time for a mock run. Sleeping advances it; nothing waits and no wall clock is read."""

    def __init__(self, start: float = VIRTUAL_EPOCH) -> None:
        self._now = float(start)
        self.sleep_calls = 0

    def now(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise MockHarnessError("Virtual time cannot go backwards")
        self._now += float(seconds)
        self.sleep_calls += 1


class SyntheticOperationBudget:
    """A hard, restart-persistent cap on mock operations around the accepted persistent pacer.

    The consumed count is the pacer's persisted reservation total, so it survives a restart
    and cannot be reset by building a new object. The identity is written once beside the
    pacing state; a different identity fails closed. The limit is a simulation parameter.
    It is not, and does not imply, a budget for any live experiment.
    """

    def __init__(self, pacer: PersistentRollingOperationPacer, identity_path: Path, *, run_id: str, maximum: int) -> None:
        if type(maximum) is not int or not 1 <= maximum <= MAX_SYNTHETIC_BUDGET:
            raise MockHarnessError("The synthetic operation budget must be a small positive integer")
        self.identity = {
            "artifact": BUDGET_ID,
            "evidence": EVIDENCE_LABEL,
            "protocol_sha256": protocol.PROTOCOL_SHA256,
            "run_id": run_id,
            "synthetic_maximum_operations": maximum,
            "pacing_checkpoint": pacer.checkpoint_path.name,
            "live_operation_budget": protocol.LIVE_OPERATION_BUDGET,
        }
        data = canonical_json_bytes(self.identity)
        if identity_path.exists():
            if identity_path.read_bytes() != data:
                raise CheckpointIntegrityError("Synthetic operation budget identity changed across restart")
        else:
            _write_once(identity_path, data)
        self._pacer = pacer
        self.maximum = maximum
        self.refusals = 0

    def consumed(self) -> int:
        return int(self._pacer.snapshot()["reservation_count"])

    def remaining(self) -> int:
        return self.maximum - self.consumed()

    def acquire(self) -> float:
        if self.consumed() >= self.maximum:
            self.refusals += 1
            raise SyntheticBudgetExhausted("Synthetic operation budget is exhausted")
        return self._pacer.acquire()

    def snapshot(self) -> dict[str, Any]:
        consumed = self.consumed()
        return {"synthetic_maximum_operations": self.maximum, "consumed": consumed,
                "remaining": self.maximum - consumed, "refusals": self.refusals,
                "within_budget": consumed <= self.maximum}


@dataclass(frozen=True)
class MockJob:
    """Scripted behaviour of one job: per execution window the outcome of each mock operation, then the response."""
    windows: tuple
    response: Optional[str] = None

    def __post_init__(self) -> None:
        allowed = (MOCK_SUCCESS, MOCK_PROCESS_DEATH) + MOCK_TRANSIENT_FAILURES
        if not self.windows or any(not window or len(window) > 3 or any(step not in allowed for step in window)
                                   for window in self.windows):
            raise MockHarnessError("A mock job script is not valid")
        succeeds = any(MOCK_SUCCESS in window for window in self.windows)
        if succeeds != isinstance(self.response, str):
            raise MockHarnessError("A mock job has a response exactly when its script succeeds")


class OfflineMockTransport:
    """The injected fake transport. It has no credential, no client and no way to reach a network.

    It keeps the call contract of the accepted window transport: it re-checks the protocol
    guard and reserves one pacing slot immediately before each mock operation, so pacing,
    the budget and operation accounting are exercised exactly as they would be.
    """

    NETWORK_ACCESS = "NONE_NO_CLIENT_NO_CREDENTIAL_NO_SOCKET"
    OFFLINE_SYNTHETIC_MOCK = True

    def __init__(self, script: Mapping[str, MockJob], budget: SyntheticOperationBudget, guard: Callable[[], None],
                 clock: VirtualClock) -> None:
        self._script = dict(script)
        self._budget = budget
        self._guard = guard
        self._clock = clock
        self.window_calls: list[str] = []
        self.operations = 0

    def __call__(self, spec: DurableJobSpec, window: int, request_id: str) -> dict[str, Any]:
        self._guard()
        protocol.assert_job_spec(spec)
        job = self._script.get(spec.job_id)
        if job is None or not 1 <= window <= len(job.windows):
            raise MockHarnessError("No mock behaviour is scripted for this job and window")
        self.window_calls.append(request_id)
        attempts: list[dict[str, Any]] = []
        for outcome in job.windows[window - 1]:
            self._guard()
            wait = float(self._budget.acquire())
            self._guard()
            self._clock.sleep(VIRTUAL_SECONDS_PER_OPERATION)
            self.operations += 1
            if outcome == MOCK_PROCESS_DEATH:
                raise SimulatedInterruption()
            attempts.append({"model": spec.model, "slot_id": spec.credential_slot, "classified_result": outcome,
                             "paced_before_operation": wait > 0, "evidence": EVIDENCE_LABEL})
            if outcome == MOCK_SUCCESS:
                return {
                    "raw_content": job.response,
                    "transport_attempts": attempts,
                    "attempt_accounting": {"total_provider_attempts": len(attempts)},
                    "model_requested": spec.model,
                    "slot_id": spec.credential_slot,
                    "provider_response_metadata": {"evidence": EVIDENCE_LABEL},
                    "model_reported_if_available": None,
                    "usage_metadata": None,
                }
        category = job.windows[window - 1][-1]
        raise DurableTransportFailure(category, provider_attempts=len(attempts),
                                      fingerprint=f"{category}:SYNTHETIC_MOCK", attempts=attempts)


def build_guard() -> Callable[[], None]:
    """Re-verify every file the protocol candidate depends on before each mock operation."""

    def guard() -> None:
        try:
            protocol.validate_bound_files()
        except protocol.P41RuntimeProtocolError as error:
            raise CheckpointIntegrityError("A file bound by the protocol candidate changed") from error

    return guard


def _resume_instant(checkpoints: Path) -> float:
    """Virtual time continues after the latest reservation already persisted. No wall clock is involved."""
    pacing = checkpoints / "global_pacing.json"
    if not pacing.exists():
        return VIRTUAL_EPOCH
    stamps = AtomicIntegrityJsonStore().read(pacing).get("active_reservation_timestamps") or []
    return max([VIRTUAL_EPOCH] + [float(value) + VIRTUAL_SECONDS_PER_OPERATION for value in stamps])


def build_durable_stack(checkpoints: Path, clock: VirtualClock, *, run_id: str, synthetic_budget: int):
    """The accepted pacer and executor with the proposed limits, on virtual time, plus the synthetic budget."""
    checkpoints.mkdir(parents=True, exist_ok=True)
    pacer = PersistentRollingOperationPacer(
        checkpoints / "global_pacing.json",
        max_operations=protocol.GLOBAL_MAX_PROVIDER_OPERATIONS,
        window_seconds=protocol.GLOBAL_ROLLING_WINDOW_SECONDS,
        clock=clock.now,
        sleep=clock.sleep,
    )
    budget = SyntheticOperationBudget(pacer, checkpoints / "synthetic_operation_budget.json", run_id=run_id,
                                      maximum=synthetic_budget)
    executor = DurableResearchExecutor(
        checkpoints / "jobs",
        protocol_id=f"{protocol.executor_protocol_id()}:{RUNNER_ID}:{run_id}",
        window_cooldown_seconds=protocol.WINDOW_COOLDOWN_SECONDS,
        clock=clock.now,
    )
    return pacer, budget, executor


# ---------------------------------------------------------------------------
# Synthetic input and responses. Invented text; nothing here comes from a dataset.
# ---------------------------------------------------------------------------

SYNTHETIC_TEXT = "Oren barred the gate at the mill when Lysa arrived, and Oren did not greet her."


@dataclass(frozen=True)
class SyntheticCase:
    case_id: str
    prepared_input: Mapping[str, Any]
    compiler_context: DraftCompilerContext


def synthetic_case(case_id: str) -> SyntheticCase:
    """The invented sentence, ingested by the frozen ingestion adapter. Independent of every dataset."""
    data = SYNTHETIC_TEXT.encode("utf-8")
    with tempfile.TemporaryDirectory() as directory:
        (Path(directory) / "unit.txt").write_bytes(data)
        manifest = {
            "contract_version": "LIGHT_NOVEL_INGESTION/v0",
            "story_id": "story-synthetic-p41-mock",
            "stream_id": "stream-synthetic-p41-mock",
            "source_language": "en",
            "documents": [{"document_id": "srcdoc-synthetic-p41-mock", "order": 1, "path": "unit.txt",
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
        profile_id="synthetic-p41-mock-profile-v0",
        process_id=PROCESS_ID,
        process_version=PROCESS_VERSION,
        run_id=f"P41MOCK_{case_id}",
        ingestion=ingestion,
    )
    prepared = prepare_story_extraction_draft_v1_1(context)
    if [passage["text"] for passage in prepared["passages"]] != [SYNTHETIC_TEXT]:
        raise MockHarnessError("The synthetic input is not the single invented passage")
    return SyntheticCase(case_id, prepared, context)


def _evidence(handle: str, quote: str, occurrence: Optional[int] = None) -> dict[str, Any]:
    record = {"handle": handle, "passage_handle": "P1", "quote": quote, "role": "DEPICTION"}
    if occurrence is not None:
        record["occurrence"] = occurrence
    return record


def _assertion(handle: str, proposition: str, evidence: str) -> dict[str, Any]:
    return {"handle": handle, "proposition_handle": proposition, "polarity": "AFFIRMED", "epistemic_status": "EXPLICIT",
            "support": {"evidence_sets": [{"label": "SUFFICIENT", "evidence_handles": [evidence]}], "derivations": []}}


def _entity_argument(handle: str) -> dict[str, str]:
    return {"kind": "ENTITY", "handle": handle}


def valid_draft() -> dict[str, Any]:
    """A hand-written Draft V1.1 for the invented sentence that the unchanged compiler accepts."""
    event = {"kind": "EVENT", "handle": "EVT1"}
    return {
        "draft_version": "STORY_EXTRACTION_DRAFT_V1_1",
        "evidence": [_evidence("EV1", "Oren", 1), _evidence("EV2", "Lysa"), _evidence("EV3", "the mill"),
                     _evidence("EV4", SYNTHETIC_TEXT)],
        "mentions": [{**_evidence("M1", "Oren", 1), "surface_form": "Oren"},
                     {**_evidence("M2", "Lysa"), "surface_form": "Lysa"},
                     {**_evidence("M3", "the mill"), "surface_form": "the mill"}],
        "entities": [{"handle": "E_NEW_1", "kind": "CHARACTER"}, {"handle": "E_NEW_2", "kind": "CHARACTER"},
                     {"handle": "E_NEW_3", "kind": "LOCATION"}],
        "events": [{"handle": "EVT1", "event_kind": "GENERIC", "anchor_handle": "T1"}],
        "anchors": [{"handle": "T1", "anchor_kind": "EVENT_TIME", "event_handle": "EVT1"}],
        "propositions": [
            {"handle": "PROP1", "predicate": "RefersTo",
             "args": {"mention": {"kind": "MENTION", "handle": "M1"}, "entity": _entity_argument("E_NEW_1")}},
            {"handle": "PROP2", "predicate": "RefersTo",
             "args": {"mention": {"kind": "MENTION", "handle": "M2"}, "entity": _entity_argument("E_NEW_2")}},
            {"handle": "PROP3", "predicate": "RefersTo",
             "args": {"mention": {"kind": "MENTION", "handle": "M3"}, "entity": _entity_argument("E_NEW_3")}},
            {"handle": "PROP4", "predicate": "Occurred", "args": {"event": event}},
            {"handle": "PROP5", "predicate": "Participates",
             "args": {"event": event, "participant": _entity_argument("E_NEW_1"),
                      "role": {"kind": "TOKEN", "vocabulary": "participant_role", "value": "AGENT"}}},
            {"handle": "PROP6", "predicate": "OccursAt", "args": {"event": event, "location": _entity_argument("E_NEW_3")}},
            {"handle": "PROP7", "predicate": "EmotionToward",
             "args": {"holder": _entity_argument("E_NEW_1"), "target": _entity_argument("E_NEW_2"),
                      "emotion": {"kind": "LITERAL", "value_type": "STRING", "value": "resentment"}}},
        ],
        "assertions": [
            _assertion("A1", "PROP1", "EV1"), _assertion("A2", "PROP2", "EV2"), _assertion("A3", "PROP3", "EV3"),
            _assertion("A4", "PROP4", "EV4"), _assertion("A5", "PROP5", "EV4"), _assertion("A6", "PROP6", "EV4"),
            {"handle": "A7", "proposition_handle": "PROP7", "polarity": "AFFIRMED", "epistemic_status": "SUGGESTED",
             "support": {"evidence_sets": [],
                         "derivations": [{"rule_id": "BEHAVIOUR_SUGGESTS_STATE", "premise_handles": ["A4"]}]},
             "validity": {"start": {"kind": "OPEN"}, "end": {"kind": "OPEN"}}},
        ],
    }


def _record(draft: Mapping[str, Any], collection: str, handle: str) -> dict[str, Any]:
    return next(record for record in draft[collection] if record["handle"] == handle)


def _without(draft: dict[str, Any], removed: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    for collection, handles in removed.items():
        draft[collection] = [record for record in draft[collection] if record["handle"] not in handles]
    return draft


def _mutations() -> dict[str, Callable[[dict[str, Any]], Any]]:
    """Named ways a hand-written response differs from the valid draft. Each is one invented model output."""
    def ambiguous(draft):
        del _record(draft, "mentions", "M1")["occurrence"]

    def schema_invalid(draft):
        del _record(draft, "mentions", "M2")["role"]

    def projection_only_valid(draft):
        # The handle grammar is a pattern. The projection has no patterns; the full schema does.
        _record(draft, "mentions", "M3")["handle"] = "M03"

    def entity_kind(draft):
        _record(draft, "entities", "E_NEW_3")["kind"] = "OBJECT"

    def derivation(draft):
        _record(draft, "assertions", "A7")["support"]["derivations"][0]["rule_id"] = "TRANSFER_RESULT"

    def duplicate(draft):
        draft["propositions"].append({**copy.deepcopy(_record(draft, "propositions", "PROP6")), "handle": "PROP8"})

    def several(draft):
        ambiguous(draft)
        del _record(draft, "evidence", "EV1")["occurrence"]
        duplicate(draft)

    def occurrence_then_entity_kind(draft):
        _record(draft, "mentions", "M1")["occurrence"] = 2
        entity_kind(draft)

    def unknown_canonical(draft):
        del _record(draft, "propositions", "PROP6")["args"]["location"]

    def removes_supported_records(draft):
        # The ambiguous mention and what depends on it, and also the location, which no finding concerns.
        _without(draft, {"mentions": ["M1", "M3"], "evidence": ["EV3"], "entities": ["E_NEW_3"],
                         "propositions": ["PROP1", "PROP3", "PROP6"], "assertions": ["A1", "A3", "A6"]})

    def empty(draft):
        for collection in retention.COLLECTIONS:
            draft[collection] = []

    return {
        "VALID": lambda draft: None, "AMBIGUOUS_QUOTE": ambiguous, "SCHEMA_INVALID": schema_invalid,
        "PROJECTION_VALID_FULL_SCHEMA_INVALID": projection_only_valid, "ENTITY_KIND": entity_kind,
        "DERIVATION_CONCLUSION": derivation, "DUPLICATE_PROPOSITION": duplicate, "SEVERAL_BLOCKERS": several,
        "OCCURRENCE_ADDED_THEN_ENTITY_KIND": occurrence_then_entity_kind, "UNKNOWN_CANONICAL_RULE": unknown_canonical,
        "REMOVES_SUPPORTED_RECORDS": removes_supported_records, "EMPTY": empty,
    }


def mock_response(name: str) -> str:
    """One invented model output, as text. INVALID_JSON is the valid response cut short."""
    if name == "INVALID_JSON":
        text = mock_response("VALID")
        return text[: len(text) // 2]
    mutations = _mutations()
    if name not in mutations:
        raise MockHarnessError("Unknown synthetic response")
    draft = valid_draft()
    mutations[name](draft)
    return json.dumps(draft, ensure_ascii=False, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

_OK = ((MOCK_SUCCESS,),)
FOLLOW_UP_NONE = "NONE"
FOLLOW_UP_RESTART = "RESTART_ON_THE_SAME_ROOT"
FOLLOW_UP_REEXECUTE = "EXECUTE_THE_TERMINAL_CASE_AND_JOB_AGAIN"
FOLLOW_UPS = (FOLLOW_UP_NONE, FOLLOW_UP_RESTART, FOLLOW_UP_REEXECUTE)


@dataclass(frozen=True)
class CasePlan:
    case_id: str
    primary: str                       # name of the synthetic primary response, or "" for no response
    repair: Optional[str] = None       # name of the synthetic repair response, if the script provides one
    primary_windows: tuple = _OK
    repair_windows: tuple = _OK


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    simulates: str
    cases: tuple
    synthetic_budget: int = 12
    partially_described_policy: str = protocol.PARTIAL_POLICY_REFUSE
    follow_up: str = FOLLOW_UP_NONE


def _one(case_id: str, primary: str, repair: Optional[str] = None, **windows) -> tuple:
    return (CasePlan(case_id, primary, repair, **windows),)


_FAIL3 = (("SERVER_FAILURE", "TIMEOUT", "RATE_LIMIT"),)
SCENARIOS = (
    Scenario("S01", "VALID_PRIMARY_RESPONSE", _one("SYN_01", "VALID")),
    Scenario("S02", "INVALID_JSON_PRIMARY", _one("SYN_02", "INVALID_JSON", "VALID")),
    Scenario("S03", "FULL_SCHEMA_INVALID_PRIMARY", _one("SYN_03", "SCHEMA_INVALID", "VALID")),
    Scenario("S04", "PROJECTION_VALID_BUT_FULL_SCHEMA_INVALID_PRIMARY",
             _one("SYN_04", "PROJECTION_VALID_FULL_SCHEMA_INVALID", "VALID")),
    Scenario("S05", "COMPILER_INVALID_QUOTE_OCCURRENCE", _one("SYN_05", "AMBIGUOUS_QUOTE", "VALID")),
    Scenario("S06", "COMPILER_INVALID_ENTITY_KIND_REFERENCE", _one("SYN_06", "ENTITY_KIND", "VALID")),
    Scenario("S07", "COMPILER_INVALID_DERIVATION_CONCLUSION", _one("SYN_07", "DERIVATION_CONCLUSION", "VALID")),
    Scenario("S08", "DUPLICATE_CONCRETE_PROPOSITION", _one("SYN_08", "DUPLICATE_PROPOSITION", "VALID")),
    Scenario("S09", "SUCCESSFUL_REPAIR_OF_SEVERAL_BLOCKERS", _one("SYN_09", "SEVERAL_BLOCKERS", "VALID")),
    Scenario("S10", "BYTE_IDENTICAL_INEFFECTIVE_REPAIR", _one("SYN_10", "AMBIGUOUS_QUOTE", "AMBIGUOUS_QUOTE")),
    Scenario("S11", "REPAIR_THAT_CHANGES_THE_BLOCKER_BUT_STILL_FAILS",
             _one("SYN_11", "AMBIGUOUS_QUOTE", "OCCURRENCE_ADDED_THEN_ENTITY_KIND")),
    Scenario("S12", "TRANSPORT_RETRY_FOLLOWED_BY_SUCCESS",
             _one("SYN_12", "VALID", primary_windows=_FAIL3 + (("NETWORK_FAILURE", MOCK_SUCCESS),))),
    Scenario("S13", "TERMINAL_TRANSPORT_FAILURE", _one("SYN_13", "", primary_windows=_FAIL3 * 3)),
    Scenario("S14", "INTERRUPTED_CHECKPOINT", _one("SYN_14", "", primary_windows=((MOCK_PROCESS_DEATH,),)),
             follow_up=FOLLOW_UP_RESTART),
    Scenario("S15", "DUPLICATE_TERMINAL_JOB_ATTEMPT", _one("SYN_15", "VALID"), follow_up=FOLLOW_UP_REEXECUTE),
    Scenario("S16", "BUDGET_EXHAUSTION_UNDER_A_SYNTHETIC_LIMIT",
             _one("SYN_16", "VALID", primary_windows=(("SERVER_FAILURE", "TIMEOUT", MOCK_SUCCESS),)),
             synthetic_budget=2, follow_up=FOLLOW_UP_RESTART),
    Scenario("S17", "PACING_WINDOW_SATURATION",
             tuple(CasePlan(f"SYN_17{letter}", "VALID", primary_windows=(("SERVER_FAILURE", MOCK_SUCCESS),))
                   for letter in "ABCD"), synthetic_budget=16),
    Scenario("S18", "EMPTY_BUT_COMPILER_VALID_OUTPUT", _one("SYN_18", "EMPTY")),
    Scenario("S19", "REPAIR_THAT_REMOVES_OTHERWISE_SUPPORTED_RECORDS",
             _one("SYN_19", "AMBIGUOUS_QUOTE", "REMOVES_SUPPORTED_RECORDS")),
    Scenario("S20", "UNKNOWN_CANONICAL_ERROR_WITH_AN_INCOMPLETE_DIAGNOSTIC",
             _one("SYN_20", "UNKNOWN_CANONICAL_RULE", "VALID")),
    # The other branch of the one undecided policy, shown so both behaviours are visible. Not a twenty-first case of
    # the required list: the same response as S20 under ALLOW_REPAIR.
    Scenario("S21", "UNKNOWN_CANONICAL_ERROR_UNDER_THE_ALLOW_REPAIR_POLICY",
             _one("SYN_21", "UNKNOWN_CANONICAL_RULE", "VALID"), partially_described_policy=protocol.PARTIAL_POLICY_ALLOW),
)
REQUIRED_SIMULATIONS = tuple(scenario.simulates for scenario in SCENARIOS[:20])
# Identity of the invented text, every synthetic response and every script. A changed fixture is a different run.
FIXTURE_SET_SHA256 = "ed5e5ea00b2b2dbb1014c46050ba613aecd0ab12f519fac092d5fb287dadad0a"


def _job(windows: tuple, response_name: Optional[str]) -> MockJob:
    succeeds = any(MOCK_SUCCESS in window for window in windows)
    return MockJob(windows, mock_response(response_name) if succeeds and response_name else None)


def scenario_script(scenario: Scenario) -> dict[str, MockJob]:
    script = {}
    for plan in scenario.cases:
        script[protocol.PRIMARY_JOB_ID.format(CASE_ID=plan.case_id)] = _job(plan.primary_windows, plan.primary)
        if plan.repair is not None:
            script[protocol.REPAIR_JOB_ID.format(CASE_ID=plan.case_id)] = _job(plan.repair_windows, plan.repair)
    return script


def fixture_identity(scenario: Scenario) -> dict[str, Any]:
    jobs = {job_id: {"windows": [list(window) for window in job.windows],
                     "response_sha256": None if job.response is None else sha256_bytes(job.response.encode("utf-8"))}
            for job_id, job in sorted(scenario_script(scenario).items())}
    return {
        "scenario_id": scenario.scenario_id,
        "simulates": scenario.simulates,
        "synthetic_text_sha256": sha256_bytes(SYNTHETIC_TEXT.encode("utf-8")),
        "cases": [plan.case_id for plan in scenario.cases],
        "jobs": jobs,
        "synthetic_budget": scenario.synthetic_budget,
        "partially_described_policy": scenario.partially_described_policy,
        "follow_up": scenario.follow_up,
    }


def fixture_set_sha256() -> str:
    return sha256_bytes(canonical_json_bytes([fixture_identity(scenario) for scenario in SCENARIOS]))


def scenario_by_id(scenario_id: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.scenario_id == scenario_id:
            return scenario
    raise MockHarnessError("Unknown scenario")


# ---------------------------------------------------------------------------
# Response evaluation: the unchanged validator and compiler decide; diagnostic V3.1 describes
# ---------------------------------------------------------------------------

def projection_validator() -> Draft202012Validator:
    return Draft202012Validator(protocol.native_response_schema())


def evaluate_response(raw: str, case: SyntheticCase, validator: Draft202012Validator) -> dict[str, Any]:
    """Judge one locked response. The compiler's verdict is final; the diagnostic must agree with it or the run stops."""
    parsed, draft = retention.parse_response(raw)
    batch = None
    if not parsed:
        category = "JSON_PARSE_FAILURE"
    else:
        try:
            validate_draft_v1_1(draft)
        except DraftCompilationErrorV1_1:
            category = "DRAFT_SCHEMA_FAILURE"
        else:
            try:
                batch = compile_story_extraction_draft_v1_1(draft, case.compiler_context)
                category = None
            except DraftCompilationErrorV1_1:
                category = "DRAFT_COMPILER_FAILURE"
    try:
        diagnostic = diagnostic_v3_1.structural_diagnostic_v3_1(raw, case.compiler_context)
    except diagnostic_v3_1.DiagnosticV31Error:
        diagnostic = None
    if diagnostic is not None and (
            diagnostic["diagnostic"] != protocol.ACTIVE_DIAGNOSTIC_ID
            or diagnostic["category"] != category
            or diagnostic["compiler_verdict"]["compiled"] is not (category is None)):
        raise MockHarnessError("Structural diagnostic V3.1 disagrees with the compiler's verdict")
    return {
        "structurally_valid": category is None,
        "category": category,
        "json_parse": parsed,
        # Measured only. The projection never decides acceptance.
        "provider_projection_valid": validator.is_valid(draft) if parsed else None,
        "full_schema_valid": (category != "DRAFT_SCHEMA_FAILURE") if parsed else None,
        "compiler_reached": category in (None, "DRAFT_COMPILER_FAILURE"),
        "compiler_success": (category is None) if category in (None, "DRAFT_COMPILER_FAILURE") else None,
        "diagnostic": diagnostic,
        "diagnostic_safe": diagnostic is not None,
        "profile": retention.draft_profile(parsed, draft),
        "draft": draft if parsed else None,
        "batch": batch,
    }


def _attempt_record(phase: str, spec: DurableJobSpec, record: Mapping[str, Any]) -> dict[str, Any]:
    summary = summarize_job(record)
    return {
        "phase": phase,
        "job_id": spec.job_id,
        "request_fingerprint": spec.request_fingerprint,
        "job_state": record["state"],
        "provider_success": record["state"] == JobState.SUCCEEDED_LOCKED.value,
        "transport_terminal_reason": None,
        "windows_used": summary["windows_used"],
        "checkpointed_operations": summary["total_provider_operations"],
        "deferred_count": summary["deferred_count"],
        "success_lock_count": summary["success_lock_count"],
        "raw_response_sha256": summary["first_success_response_sha256"],
    }


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

class MockRun:
    """One isolated mock run of one scenario: its private root, durable stack, transport and results."""

    def __init__(self, scenario: Scenario, private_root: Path, *, resume: bool = False,
                 environment: Optional[Mapping[str, str]] = None, synthetic_budget: Optional[int] = None) -> None:
        assert_no_provider_credentials(os.environ if environment is None else environment)
        if fixture_set_sha256() != FIXTURE_SET_SHA256:
            raise MockHarnessError("The synthetic fixtures differ from the pinned fixture set")
        try:
            protocol.locked_protocol()
        except protocol.P41RuntimeProtocolError as error:
            raise MockHarnessError("The runtime protocol candidate does not pass its gates") from error
        self.scenario = scenario
        self.layout = private_layout(private_root)
        self.run_id = f"MOCK_{scenario.scenario_id}"
        manifest = {
            "artifact": RUN_MANIFEST_ID,
            "evidence": EVIDENCE_LABEL,
            "runner_id": RUNNER_ID,
            "run_id": self.run_id,
            "protocol_id": protocol.PROTOCOL_ID,
            "protocol_sha256": protocol.PROTOCOL_SHA256,
            "fixture_set_sha256": FIXTURE_SET_SHA256,
            "fixture": fixture_identity(scenario),
        }
        manifest_path = self.layout["root"] / f"{RUN_MANIFEST_ID}.json"
        state = existing_execution_state(self.layout)
        if resume:
            if not manifest_path.exists() or manifest_path.read_bytes() != canonical_json_bytes(manifest):
                raise PriorExecutionState("The state on disk does not belong to this run")
        elif state:
            raise PriorExecutionState("The private root already holds execution state: " + ", ".join(sorted(state)))
        _write_once(manifest_path, canonical_json_bytes(manifest))
        self.manifest = manifest
        self.clock = VirtualClock(_resume_instant(self.layout["checkpoints"]))
        self.pacer, self.budget, self.executor = build_durable_stack(
            self.layout["checkpoints"], self.clock, run_id=self.run_id,
            synthetic_budget=scenario.synthetic_budget if synthetic_budget is None else synthetic_budget)
        self.guard = build_guard()
        self.transport = OfflineMockTransport(scenario_script(scenario), self.budget, self.guard, self.clock)
        self.validator = projection_validator()
        self.results: list[dict[str, Any]] = []

    # -- jobs ---------------------------------------------------------------

    def run_job(self, spec: DurableJobSpec) -> dict[str, Any]:
        """Run one durable job to a terminal state on the mock transport. Only the mock transport is accepted."""
        if type(self.transport) is not OfflineMockTransport:
            raise MockHarnessError("This harness runs only on its offline mock transport")
        if not isinstance(spec, DurableJobSpec) or spec.research_task_id != protocol.PROTOCOL_ID:
            raise MockHarnessError("The job does not belong to the protocol candidate")
        self.guard()
        if self.budget.remaining() <= 0:
            self.budget.refusals += 1
            raise SyntheticBudgetExhausted("Synthetic operation budget is exhausted")
        self.executor.ensure_job(spec)
        while True:
            record = self.executor.load_job(spec)
            if JobState(record["state"]) in (JobState.SUCCEEDED_LOCKED, JobState.TERMINAL_FAILED):
                return record
            try:
                self.executor.execute_window(spec, self.transport)
            except CooldownPending as pending:
                self.clock.sleep(max(0.001, pending.remaining_seconds))

    def _locked_response(self, record: Mapping[str, Any], directory: Path, case_id: str) -> str:
        success = record["first_success"]
        raw = success.get("raw_response")
        if not isinstance(raw, str) or sha256_bytes(raw.encode("utf-8")) != success.get("response_sha256"):
            raise CheckpointIntegrityError("Locked first-success response identity mismatch")
        if _write_once(directory / f"{case_id}.txt", raw.encode("utf-8")) != success["response_sha256"]:
            raise MockHarnessError("Raw response identity mismatch")
        return raw

    def _persist_evaluation(self, case_id: str, phase: str, attempt: dict[str, Any], evaluation: Mapping[str, Any]) -> None:
        diagnostic = evaluation["diagnostic"]
        attempt.update({
            "json_parse": evaluation["json_parse"],
            "provider_projection_valid": evaluation["provider_projection_valid"],
            "full_schema_valid": evaluation["full_schema_valid"],
            "compiler_reached": evaluation["compiler_reached"],
            "compiler_success": evaluation["compiler_success"],
            "structurally_valid": evaluation["structurally_valid"],
            "structural_failure_category": evaluation["category"],
            "diagnostic_safe": evaluation["diagnostic_safe"],
            "diagnostic_sha256": None,
            "diagnostic_summary": None,
            "draft_sha256": None,
            "profile": evaluation["profile"],
        })
        if evaluation["draft"] is not None:
            attempt["draft_sha256"] = _write_once(
                self.layout["drafts"] / f"{case_id}_{phase}.json", canonical_json_bytes(evaluation["draft"]))
        if diagnostic is not None:
            attempt["diagnostic_sha256"] = _write_once(
                self.layout["diagnostics"] / f"{case_id}_{phase}.json", diagnostic_v3_1.canonical_json_bytes(diagnostic))
            attempt["diagnostic_summary"] = diagnostic_v3_1.public_summary(diagnostic)

    # -- cases --------------------------------------------------------------

    def execute_case(self, plan: CasePlan) -> dict[str, Any]:
        """One primary and, if the actionability rule decides so, exactly one structural repair."""
        result_path = self.layout["case_results"] / f"{plan.case_id}.json"
        if result_path.exists():
            raise MockHarnessError("A terminal case is never executed again")
        case = synthetic_case(plan.case_id)
        policy = self.scenario.partially_described_policy
        attempts: list[dict[str, Any]] = []
        actionability = decision = repair_skipped = effect = None
        transport_phase = transport_reason = None
        primary_eval = repair_eval = None

        primary_spec = protocol.build_primary_spec(case.case_id, case.prepared_input)
        protocol.assert_request_identity(primary_spec, case.case_id, case.prepared_input)
        record = self.run_job(primary_spec)
        attempts.append(_attempt_record("primary", primary_spec, record))
        if record["state"] != JobState.SUCCEEDED_LOCKED.value:
            transport_phase, transport_reason = "PRIMARY", str(record["transitions"][-1]["reason"])
            attempts[-1]["transport_terminal_reason"] = transport_reason
        else:
            primary_raw = self._locked_response(record, self.layout["raw_primary"], case.case_id)
            primary_eval = evaluate_response(primary_raw, case, self.validator)
            self._persist_evaluation(case.case_id, "primary", attempts[-1], primary_eval)
            if not primary_eval["structurally_valid"]:
                actionability = (protocol.classify_repair_actionability(primary_eval["diagnostic"], primary_raw)
                                 if primary_eval["diagnostic_safe"] else
                                 {"class": protocol.ACTION_INVALID, "reasons": [], "incomplete_downstream_statements": []})
                decision = protocol.repair_decision(actionability, partially_described_policy=policy)
                if decision != protocol.DECISION_REPAIR:
                    repair_skipped = (SKIP_POLICY_UNRESOLVED if actionability["class"] == protocol.ACTION_PARTIAL
                                      else actionability["class"])
                else:
                    repair_spec = protocol.build_repair_spec(
                        case.case_id, case.prepared_input, primary_raw, primary_eval["diagnostic"],
                        case.compiler_context, partially_described_policy=policy)
                    protocol.assert_request_identity(
                        repair_spec, case.case_id, case.prepared_input, primary_response=primary_raw,
                        diagnostic=primary_eval["diagnostic"], compiler_context=case.compiler_context,
                        partially_described_policy=policy)
                    record = self.run_job(repair_spec)
                    attempts.append(_attempt_record("repair_1", repair_spec, record))
                    if record["state"] != JobState.SUCCEEDED_LOCKED.value:
                        transport_phase, transport_reason = "REPAIR", str(record["transitions"][-1]["reason"])
                        attempts[-1]["transport_terminal_reason"] = transport_reason
                    else:
                        repair_raw = self._locked_response(record, self.layout["raw_repair"], case.case_id)
                        repair_eval = evaluate_response(repair_raw, case, self.validator)
                        self._persist_evaluation(case.case_id, "repair_1", attempts[-1], repair_eval)
                        effect = retention.repair_effect(
                            primary_raw, repair_raw, primary_eval["diagnostic"], repair_eval["diagnostic"],
                            primary_valid=False, repair_valid=repair_eval["structurally_valid"])

        if not 1 <= len(attempts) <= 1 + protocol.MAX_STRUCTURAL_REPAIRS_PER_CASE:
            raise MockHarnessError("Case job sequence differs from the protocol candidate")
        final = repair_eval or primary_eval
        if transport_phase is not None:
            terminal_status, category = "TRANSPORT_FAILURE", "TRANSPORT_FAILURE"
        elif final["structurally_valid"]:
            terminal_status, category = "STRUCTURAL_VALID", None
        else:
            terminal_status, category = "STRUCTURAL_FAILURE", final["category"]
        compiled_sha256 = None
        if terminal_status == "STRUCTURAL_VALID":
            compiled_sha256 = _write_once(
                self.layout["compiled"] / f"{case.case_id}.json", canonical_json_bytes(final["batch"]))
        warnings = sorted(set(
            (retention.output_warnings(final["profile"]) if final is not None and transport_phase is None else [])
            + (effect["effect"]["warnings"] if effect else [])))
        result = {
            "artifact": CASE_RESULT_ID,
            "evidence": EVIDENCE_LABEL,
            "case_id": case.case_id,
            "run_id": self.run_id,
            "protocol_sha256": protocol.PROTOCOL_SHA256,
            "primary": attempts[0],
            "repair_used": len(attempts) > 1,
            "repair": attempts[1] if len(attempts) > 1 else None,
            "repair_actionability": actionability,
            "repair_decision": decision,
            "repair_skipped_reason": repair_skipped,
            "partially_described_policy_applied": policy,
            "terminal_status": terminal_status,
            "terminal_phase": transport_phase or attempts[-1]["phase"].upper(),
            "terminal_failure_category": category,
            "compiled_batch_sha256": compiled_sha256,
            "retention": effect,
            "warnings": warnings,
            "durable_jobs": len(attempts),
            "checkpointed_operations": sum(item["checkpointed_operations"] for item in attempts),
        }
        _write_once(result_path, canonical_json_bytes(result))
        self.results.append(result)
        return result

    # -- the run ------------------------------------------------------------

    def operations(self) -> dict[str, Any]:
        pacing = self.pacer.snapshot()
        return {
            "evidence": EVIDENCE_LABEL,
            "mock_operations_started": int(pacing["reservation_count"]),
            "mock_operations_by_this_process": self.transport.operations,
            "pacing_max_operations": int(pacing["max_provider_operations"]),
            "pacing_rolling_window_seconds": pacing["rolling_window_seconds"],
            "pacing_waits": int(pacing["wait_count"]),
            "max_rolling_operations_observed": int(pacing["max_rolling_reservations_observed"]),
            "pacing_invariant": pacing["invariant"],
            "restart_persistent": pacing["restart_persistent"],
            "synthetic_budget": self.budget.snapshot(),
            "real_provider_operations": 0,
        }

    def _in_flight_jobs(self) -> list[str]:
        """Jobs whose checkpoint says a window started and never ended: the mark of an interrupted process."""
        store = AtomicIntegrityJsonStore()
        return sorted(path.stem for path in (self.layout["checkpoints"] / "jobs").glob("*.json")
                      if store.read(path).get("state") == JobState.IN_FLIGHT.value)

    def execute(self) -> dict[str, Any]:
        """Execute every case not yet terminal. A budget stop, an interruption or an integrity error ends the run."""
        status = STATUS_COMPLETE
        stopped_at = None
        for plan in self.scenario.cases:
            if (self.layout["case_results"] / f"{plan.case_id}.json").exists():
                continue
            try:
                self.execute_case(plan)
            except CheckpointIntegrityError as error:
                stopped_at = plan.case_id
                if isinstance(error, SyntheticBudgetExhausted) or self.budget.refusals:
                    status = STATUS_BUDGET_EXHAUSTED
                elif self._in_flight_jobs():
                    status = STATUS_INTERRUPTED
                else:
                    status = STATUS_FAIL_CLOSED
                break
        return {"run_status": status, "stopped_at_case": stopped_at, "operations": self.operations()}


# ---------------------------------------------------------------------------
# Public-safe summaries: codes, counts, flags and hashes only
# ---------------------------------------------------------------------------

_PUBLIC_ATTEMPT_FIELDS = (
    "phase", "job_state", "provider_success", "transport_terminal_reason", "windows_used", "checkpointed_operations",
    "deferred_count", "success_lock_count", "json_parse", "provider_projection_valid", "full_schema_valid",
    "compiler_reached", "compiler_success", "structurally_valid", "structural_failure_category", "diagnostic_safe",
)


def _public_attempt(attempt: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    if attempt is None:
        return None
    public = {name: attempt.get(name) for name in _PUBLIC_ATTEMPT_FIELDS}
    profile = attempt.get("profile")
    public["record_counts"] = None if profile is None else dict(profile["record_counts"])
    public["total_records"] = None if profile is None else profile["total_records"]
    public["empty_output"] = None if profile is None else profile["empty_output"]
    summary = attempt.get("diagnostic_summary")
    public["diagnostic"] = None if summary is None else {
        name: summary[name] for name in ("category", "complete", "completeness", "limitations", "finding_count",
                                         "compiler_blockers", "findings_by_code", "findings_by_source",
                                         "findings_by_record_locator")}
    return public


def public_case_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    effect = result["retention"]
    return {
        "case_id": result["case_id"],
        "terminal_status": result["terminal_status"],
        "terminal_phase": result["terminal_phase"],
        "terminal_failure_category": result["terminal_failure_category"],
        "primary": _public_attempt(result["primary"]),
        "repair_used": result["repair_used"],
        "repair": _public_attempt(result["repair"]),
        "repair_actionability": result["repair_actionability"],
        "repair_decision": result["repair_decision"],
        "repair_skipped_reason": result["repair_skipped_reason"],
        "partially_described_policy_applied": result["partially_described_policy_applied"],
        "retention": None if effect is None else {
            "comparison": retention.public_comparison(effect["comparison"]),
            "effect": dict(effect["effect"]),
        },
        "warnings": list(result["warnings"]),
        "durable_jobs": result["durable_jobs"],
        "checkpointed_operations": result["checkpointed_operations"],
    }


def _scenario_summary(scenario: Scenario, run: MockRun, outcome: Mapping[str, Any], follow_up: Mapping[str, Any]) -> dict[str, Any]:
    summary = {
        "artifact": SCENARIO_SUMMARY_ID,
        "evidence": EVIDENCE_LABEL,
        "scenario_id": scenario.scenario_id,
        "simulates": scenario.simulates,
        "protocol_sha256": protocol.PROTOCOL_SHA256,
        "fixture_set_sha256": FIXTURE_SET_SHA256,
        "run_status": outcome["run_status"],
        "stopped_at_case": outcome["stopped_at_case"],
        "cases": [public_case_summary(result) for result in run.results],
        "operations": outcome["operations"],
        "follow_up": dict(follow_up),
    }
    summary["summary_sha256"] = sha256_bytes(canonical_json_bytes(summary))
    return summary


def run_scenario(scenario_id: str, private_root: Path, *, environment: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """Run one scenario in its own private root and return its public-safe summary."""
    scenario = scenario_by_id(scenario_id)
    run = MockRun(scenario, private_root, environment=environment)
    follow_up: dict[str, Any] = {"kind": scenario.follow_up}
    try:
        outcome = run.execute()
    except SimulatedInterruption:
        # The simulated process died inside a window. Nothing was cleaned up; the checkpoint stays in flight.
        outcome = {"run_status": STATUS_INTERRUPTED, "stopped_at_case": scenario.cases[0].case_id,
                   "operations": run.operations()}
        follow_up["process_died_inside_a_window"] = True
    if scenario.follow_up == FOLLOW_UP_RESTART:
        follow_up.update(_restart(scenario, private_root, environment))
    elif scenario.follow_up == FOLLOW_UP_REEXECUTE:
        follow_up.update(_reexecute_terminal(scenario, run, private_root, environment))
    summary = _scenario_summary(scenario, run, outcome, follow_up)
    _write_once(run.layout["summaries"] / f"{scenario.scenario_id}.json", canonical_json_bytes(summary))
    return summary


def _restart(scenario: Scenario, private_root: Path, environment: Optional[Mapping[str, str]]) -> dict[str, Any]:
    """Start again on the same root, as a new process would. Nothing may be retried or reset."""
    observed: dict[str, Any] = {}
    try:
        MockRun(scenario, private_root, environment=environment)
        observed["a_new_run_on_existing_state"] = "ACCEPTED"
    except PriorExecutionState:
        observed["a_new_run_on_existing_state"] = "REFUSED"
    try:
        MockRun(scenario, private_root, resume=True, environment=environment,
                synthetic_budget=scenario.synthetic_budget + 1)
        observed["resume_with_a_larger_budget"] = "ACCEPTED"
    except CheckpointIntegrityError:
        observed["resume_with_a_larger_budget"] = "REFUSED"
    resumed = MockRun(scenario, private_root, resume=True, environment=environment)
    before = resumed.operations()["mock_operations_started"]
    outcome = resumed.execute()
    observed.update({
        "resume_run_status": outcome["run_status"],
        "operations_started_by_the_resume": outcome["operations"]["mock_operations_started"] - before,
        "operations_persisted_across_restart": before,
        "cases_made_terminal_by_the_resume": len(resumed.results),
    })
    return observed


def _reexecute_terminal(scenario: Scenario, run: MockRun, private_root: Path,
                        environment: Optional[Mapping[str, str]]) -> dict[str, Any]:
    """Try to execute a terminal case and its locked job again. Neither may reach the transport."""
    plan = scenario.cases[0]
    case = synthetic_case(plan.case_id)
    spec = protocol.build_primary_spec(case.case_id, case.prepared_input)
    windows, operations = len(run.transport.window_calls), run.transport.operations
    first = run.executor.load_job(spec)["first_success"]["response_sha256"]
    observed: dict[str, Any] = {}
    try:
        run.execute_case(plan)
        observed["terminal_case_executed_again"] = "ACCEPTED"
    except MockHarnessError:
        observed["terminal_case_executed_again"] = "REFUSED"
    again = run.run_job(spec)
    observed.update({
        "locked_job_returned_without_a_transport_call": (
            len(run.transport.window_calls), run.transport.operations) == (windows, operations),
        "locked_response_unchanged": again["first_success"]["response_sha256"] == first,
        "success_lock_count": summarize_job(again)["success_lock_count"],
    })
    try:
        MockRun(scenario, private_root, environment=environment)
        observed["a_new_run_on_existing_state"] = "ACCEPTED"
    except PriorExecutionState:
        observed["a_new_run_on_existing_state"] = "REFUSED"
    return observed


def run_all(private_parent: Path, *, environment: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """Run every scenario, each in its own private root under the parent, and return the public-safe summary."""
    parent = assert_isolated_private_root(private_parent)
    scenarios = [run_scenario(scenario.scenario_id, parent / scenario.scenario_id.lower(), environment=environment)
                 for scenario in SCENARIOS]
    summary = {
        "artifact": RUN_SUMMARY_ID,
        "evidence": EVIDENCE_LABEL,
        "runner_id": RUNNER_ID,
        "runner_sha256": normalized_file_sha256(REPO_ROOT / RUNNER_PATH),
        "protocol_id": protocol.PROTOCOL_ID,
        "protocol_sha256": protocol.PROTOCOL_SHA256,
        "fixture_set_sha256": FIXTURE_SET_SHA256,
        "scenario_count": len(scenarios),
        "required_simulations_covered": [item["simulates"] for item in scenarios][:20] == list(REQUIRED_SIMULATIONS),
        "real_provider_operations": 0,
        "model_calls": 0,
        "credentials_loaded": 0,
        "scenarios": scenarios,
    }
    summary["summary_sha256"] = sha256_bytes(canonical_json_bytes(summary))
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("verify", "mock"), required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "verify":
            protocol.locked_protocol()
            if fixture_set_sha256() != FIXTURE_SET_SHA256:
                raise MockHarnessError("The synthetic fixtures differ from the pinned fixture set")
            print(json.dumps({"evidence": EVIDENCE_LABEL, "protocol_sha256": protocol.PROTOCOL_SHA256,
                              "fixture_set_sha256": FIXTURE_SET_SHA256, "real_provider_operations": 0,
                              "status": "P4_1_MOCK_HARNESS_VERIFIED"}, sort_keys=True))
            return 0
        with tempfile.TemporaryDirectory(prefix="m4_04b4e_synthetic_mock_") as directory:
            summary = run_all(Path(directory))
    except (MockHarnessError, protocol.P41RuntimeProtocolError, CheckpointIntegrityError) as error:
        print(f"M4_04B4E_MOCK_STOPPED_FAIL_CLOSED: {type(error).__name__}", flush=True)
        return 2
    print(json.dumps({
        "evidence": EVIDENCE_LABEL,
        "summary_sha256": summary["summary_sha256"],
        "scenarios": {item["scenario_id"]: [item["run_status"]] + [case["terminal_status"] for case in item["cases"]]
                      for item in summary["scenarios"]},
        "real_provider_operations": 0,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
