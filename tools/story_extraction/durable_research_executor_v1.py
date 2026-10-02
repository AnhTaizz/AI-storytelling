"""Durable, checkpointed research execution above the accepted Gemini transport."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Mapping, Optional
import uuid


DURABLE_EXECUTOR_VERSION = "DURABLE_RESEARCH_EXECUTOR_V1"
CHECKPOINT_FORMAT_VERSION = "DURABLE_RESEARCH_CHECKPOINT_V1"
PACING_FORMAT_VERSION = "DURABLE_GLOBAL_PACING_CHECKPOINT_V1"
MAX_EXECUTION_WINDOWS_PER_JOB = 3
MAX_PROVIDER_ATTEMPTS_PER_WINDOW = 3
MAX_PROVIDER_ATTEMPTS_PER_JOB = 9
DEFAULT_WINDOW_COOLDOWN_SECONDS = 60.0
GLOBAL_MAX_PROVIDER_OPERATIONS = 6
GLOBAL_ROLLING_WINDOW_SECONDS = 60.0

DEFER_ELIGIBLE_CATEGORIES = frozenset(
    {
        "SERVER_FAILURE",
        "TIMEOUT",
        "NETWORK_FAILURE",
        "RATE_LIMIT",
        "CIRCUIT_OPEN",
        "PROVIDER_FAILURE",
        "LOCAL_RATE_LIMIT_WAIT",
    }
)
NON_DEFER_CATEGORIES = frozenset({"AUTH_FAILURE", "QUEUE_REJECTED"})
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class JobState(str, Enum):
    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    DEFERRED_TRANSPORT = "DEFERRED_TRANSPORT"
    SUCCEEDED_LOCKED = "SUCCEEDED_LOCKED"
    TERMINAL_FAILED = "TERMINAL_FAILED"


class DurableExecutorError(RuntimeError):
    """Base class for deliberate fail-closed executor errors."""


class CheckpointIntegrityError(DurableExecutorError):
    """Checkpoint is missing integrity or conflicts with the submitted request."""


class CooldownPending(DurableExecutorError):
    """The next deferred execution window is not yet eligible."""

    def __init__(self, remaining_seconds: float) -> None:
        self.remaining_seconds = max(0.0, float(remaining_seconds))
        super().__init__("Deferred execution window cooldown is still active")


class DurableTransportFailure(RuntimeError):
    """Sanitized transport-only terminal result for one accepted V1.1 window."""

    def __init__(
        self,
        category: str,
        *,
        provider_attempts: int,
        fingerprint: Optional[str] = None,
        attempts: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] = (),
        retry_after_seconds: Optional[float] = None,
    ) -> None:
        self.category = str(category)
        self.provider_attempts = int(provider_attempts)
        self.fingerprint = fingerprint or f"{self.category}:NO_PROVIDER_CODE"
        self.attempts = tuple(dict(item) for item in attempts)
        self.retry_after_seconds = (
            None
            if retry_after_seconds is None
            else max(0.0, float(retry_after_seconds))
        )
        super().__init__(
            f"Durable transport window failed safely: {self.category}; "
            f"provider_attempts={self.provider_attempts}"
        )


@dataclass(frozen=True)
class DurableJobSpec:
    job_id: str
    model: str
    system_prompt: str
    user_prompt: str
    generation_config: Mapping[str, Any]
    schema_response_mode: str
    credential_slot: str
    research_task_id: str

    def __post_init__(self) -> None:
        if not _JOB_ID.fullmatch(self.job_id):
            raise ValueError("Job id contains unsupported characters")
        required = (
            self.model,
            self.system_prompt,
            self.user_prompt,
            self.schema_response_mode,
            self.credential_slot,
            self.research_task_id,
        )
        if any(not str(value).strip() for value in required):
            raise ValueError("Durable job identity fields must be non-empty")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "credential_slot": self.credential_slot,
            "generation_config": dict(self.generation_config),
            "model": self.model,
            "research_task_id": self.research_task_id,
            "schema_response_mode": self.schema_response_mode,
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
        }

    @property
    def request_fingerprint(self) -> str:
        canonical = json.dumps(
            self.identity_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _timestamp_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _canonical_sha256(value: Any) -> str:
    serialized = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class AtomicIntegrityJsonStore:
    """Atomic JSON envelope with a canonical payload checksum."""

    def write(self, path: Path, payload: Mapping[str, Any]) -> None:
        clean_payload = dict(payload)
        envelope = {
            "payload": clean_payload,
            "payload_sha256": _canonical_sha256(clean_payload),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(envelope, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def read(self, path: Path) -> dict[str, Any]:
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise CheckpointIntegrityError("Checkpoint cannot be decoded") from error
        if not isinstance(envelope, dict):
            raise CheckpointIntegrityError("Checkpoint envelope is invalid")
        payload = envelope.get("payload")
        checksum = envelope.get("payload_sha256")
        if not isinstance(payload, dict) or not isinstance(checksum, str):
            raise CheckpointIntegrityError("Checkpoint envelope is incomplete")
        if _canonical_sha256(payload) != checksum:
            raise CheckpointIntegrityError("Checkpoint checksum mismatch")
        return payload


class PersistentRollingOperationPacer:
    """Restart-safe task-level provider-operation pacing."""

    def __init__(
        self,
        checkpoint_path: Path,
        *,
        max_operations: int = GLOBAL_MAX_PROVIDER_OPERATIONS,
        window_seconds: float = GLOBAL_ROLLING_WINDOW_SECONDS,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        store: Optional[AtomicIntegrityJsonStore] = None,
    ) -> None:
        if max_operations < 1 or window_seconds <= 0:
            raise ValueError("Persistent pacing limits must be positive")
        self.checkpoint_path = checkpoint_path
        self.max_operations = int(max_operations)
        self.window_seconds = float(window_seconds)
        self._clock = clock
        self._sleep = sleep
        self._store = store or AtomicIntegrityJsonStore()
        self._lock = threading.Lock()
        if not checkpoint_path.exists():
            self._store.write(checkpoint_path, self._new_state())
        else:
            self._validate(self._store.read(checkpoint_path))

    def _new_state(self) -> dict[str, Any]:
        return {
            "format": PACING_FORMAT_VERSION,
            "max_operations": self.max_operations,
            "window_seconds": self.window_seconds,
            "active_reservation_timestamps": [],
            "total_reservations": 0,
            "wait_count": 0,
            "wait_seconds_total": 0.0,
            "max_rolling_reservations_observed": 0,
        }

    def _validate(self, state: Mapping[str, Any]) -> None:
        if state.get("format") != PACING_FORMAT_VERSION:
            raise CheckpointIntegrityError("Pacing checkpoint version mismatch")
        if int(state.get("max_operations", -1)) != self.max_operations:
            raise CheckpointIntegrityError("Pacing maximum changed across restart")
        if float(state.get("window_seconds", -1)) != self.window_seconds:
            raise CheckpointIntegrityError("Pacing window changed across restart")
        timestamps = state.get("active_reservation_timestamps")
        if not isinstance(timestamps, list) or any(
            not isinstance(value, (int, float)) for value in timestamps
        ):
            raise CheckpointIntegrityError("Pacing timestamps are invalid")
        if len(timestamps) > self.max_operations:
            raise CheckpointIntegrityError("Pacing checkpoint exceeds rolling maximum")

    def acquire(self) -> float:
        waited = 0.0
        did_wait = False
        while True:
            with self._lock:
                state = self._store.read(self.checkpoint_path)
                self._validate(state)
                now = float(self._clock())
                cutoff = now - self.window_seconds
                active = deque(
                    float(value)
                    for value in state["active_reservation_timestamps"]
                    if float(value) > cutoff
                )
                if len(active) < self.max_operations:
                    active.append(now)
                    state["active_reservation_timestamps"] = list(active)
                    state["total_reservations"] = int(state["total_reservations"]) + 1
                    state["max_rolling_reservations_observed"] = max(
                        int(state["max_rolling_reservations_observed"]), len(active)
                    )
                    if did_wait:
                        state["wait_count"] = int(state["wait_count"]) + 1
                        state["wait_seconds_total"] = round(
                            float(state["wait_seconds_total"]) + waited, 6
                        )
                    self._store.write(self.checkpoint_path, state)
                    return waited
                delay = max(0.001, active[0] + self.window_seconds - now)
            did_wait = True
            self._sleep(delay)
            waited += delay

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = self._store.read(self.checkpoint_path)
            self._validate(state)
        return {
            "identity": "PERSISTENT_GLOBAL_UNKNOWN_TOPOLOGY_PACER_V1",
            "max_provider_operations": self.max_operations,
            "rolling_window_seconds": self.window_seconds,
            "reservation_count": int(state["total_reservations"]),
            "wait_count": int(state["wait_count"]),
            "wait_seconds_total": float(state["wait_seconds_total"]),
            "max_rolling_reservations_observed": int(
                state["max_rolling_reservations_observed"]
            ),
            "restart_persistent": True,
            "invariant": (
                "PASS"
                if int(state["max_rolling_reservations_observed"])
                <= self.max_operations
                else "FAIL"
            ),
        }


class DurableResearchExecutor:
    """One-success-only semantic job executor with persistent state transitions."""

    def __init__(
        self,
        checkpoint_directory: Path,
        *,
        protocol_id: str,
        window_cooldown_seconds: float = DEFAULT_WINDOW_COOLDOWN_SECONDS,
        max_execution_windows: int = MAX_EXECUTION_WINDOWS_PER_JOB,
        max_provider_attempts_per_window: int = MAX_PROVIDER_ATTEMPTS_PER_WINDOW,
        clock: Callable[[], float] = time.time,
        forbidden_secrets: tuple[str, ...] = (),
        store: Optional[AtomicIntegrityJsonStore] = None,
    ) -> None:
        if not protocol_id.strip():
            raise ValueError("Protocol identity is required")
        if window_cooldown_seconds < 60:
            raise ValueError("Deferred execution cooldown must be at least 60 seconds")
        if max_execution_windows != MAX_EXECUTION_WINDOWS_PER_JOB:
            raise ValueError("Durable V1 requires exactly three maximum windows")
        if max_provider_attempts_per_window != MAX_PROVIDER_ATTEMPTS_PER_WINDOW:
            raise ValueError("Durable V1 requires exactly three attempts per window")
        self.checkpoint_directory = checkpoint_directory
        self.protocol_id = protocol_id
        self.window_cooldown_seconds = float(window_cooldown_seconds)
        self.max_execution_windows = max_execution_windows
        self.max_provider_attempts_per_window = max_provider_attempts_per_window
        self._clock = clock
        self._forbidden_secrets = tuple(value for value in forbidden_secrets if value)
        self._store = store or AtomicIntegrityJsonStore()
        self._lock = threading.RLock()
        checkpoint_directory.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        if not _JOB_ID.fullmatch(job_id):
            raise ValueError("Job id contains unsupported characters")
        return self.checkpoint_directory / f"{job_id}.json"

    def _ensure_secret_safe(self, value: Any) -> None:
        serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if any(secret in serialized for secret in self._forbidden_secrets):
            raise CheckpointIntegrityError("Checkpoint secret leak guard rejected payload")

    def _write(self, path: Path, record: Mapping[str, Any]) -> None:
        self._ensure_secret_safe(record)
        self._store.write(path, record)

    def _validate_record(self, spec: DurableJobSpec, record: Mapping[str, Any]) -> None:
        expected = {
            "format": CHECKPOINT_FORMAT_VERSION,
            "durable_executor": DURABLE_EXECUTOR_VERSION,
            "protocol_id": self.protocol_id,
            "job_id": spec.job_id,
            "request_fingerprint": spec.request_fingerprint,
            "model_requested": spec.model,
            "credential_slot": spec.credential_slot,
            "research_task_id": spec.research_task_id,
        }
        for name, value in expected.items():
            if record.get(name) != value:
                raise CheckpointIntegrityError(f"Checkpoint identity mismatch: {name}")
        try:
            state = JobState(str(record.get("state")))
        except ValueError as error:
            raise CheckpointIntegrityError("Checkpoint state is invalid") from error
        windows = int(record.get("window_count", -1))
        attempts = int(record.get("total_provider_operations", -1))
        per_window = record.get("provider_attempts_per_window")
        if windows < 0 or windows > self.max_execution_windows:
            raise CheckpointIntegrityError("Checkpoint window limit violated")
        if attempts < 0 or attempts > MAX_PROVIDER_ATTEMPTS_PER_JOB:
            raise CheckpointIntegrityError("Checkpoint attempt limit violated")
        if not isinstance(per_window, list) or any(
            not isinstance(value, int)
            or value < 0
            or value > self.max_provider_attempts_per_window
            for value in per_window
        ):
            raise CheckpointIntegrityError("Checkpoint per-window attempts are invalid")
        if len(per_window) != windows or sum(per_window) != attempts:
            raise CheckpointIntegrityError("Checkpoint attempt accounting mismatch")
        if state == JobState.SUCCEEDED_LOCKED:
            success = record.get("first_success")
            if not isinstance(success, dict) or not success.get("response_sha256"):
                raise CheckpointIntegrityError("Locked success payload is incomplete")

    def ensure_job(self, spec: DurableJobSpec) -> dict[str, Any]:
        path = self._path(spec.job_id)
        with self._lock:
            if path.exists():
                record = self._store.read(path)
                self._validate_record(spec, record)
                if record["state"] == JobState.IN_FLIGHT.value:
                    raise CheckpointIntegrityError(
                        "Ambiguous in-flight checkpoint requires manual investigation"
                    )
                return record
            now = float(self._clock())
            record = {
                "format": CHECKPOINT_FORMAT_VERSION,
                "durable_executor": DURABLE_EXECUTOR_VERSION,
                "protocol_id": self.protocol_id,
                "job_id": spec.job_id,
                "request_fingerprint": spec.request_fingerprint,
                "model_requested": spec.model,
                "credential_slot": spec.credential_slot,
                "research_task_id": spec.research_task_id,
                "schema_response_mode": spec.schema_response_mode,
                "state": JobState.PENDING.value,
                "window_count": 0,
                "provider_attempts_per_window": [],
                "total_provider_operations": 0,
                "failure_fingerprints": {},
                "first_success": None,
                "next_eligible_at_utc": None,
                "created_at_utc": _timestamp_iso(now),
                "updated_at_utc": _timestamp_iso(now),
                "windows": [],
                "transitions": [
                    {
                        "from": None,
                        "to": JobState.PENDING.value,
                        "reason": "JOB_CREATED",
                        "at_utc": _timestamp_iso(now),
                    }
                ],
            }
            self._write(path, record)
            return record

    def load_job(self, spec: DurableJobSpec) -> dict[str, Any]:
        with self._lock:
            record = self._store.read(self._path(spec.job_id))
            self._validate_record(spec, record)
            return record

    def _transition(
        self,
        record: dict[str, Any],
        target: JobState,
        reason: str,
        now: float,
    ) -> None:
        current = JobState(record["state"])
        allowed = {
            JobState.PENDING: {JobState.IN_FLIGHT},
            JobState.DEFERRED_TRANSPORT: {JobState.IN_FLIGHT},
            JobState.IN_FLIGHT: {
                JobState.DEFERRED_TRANSPORT,
                JobState.SUCCEEDED_LOCKED,
                JobState.TERMINAL_FAILED,
            },
            JobState.SUCCEEDED_LOCKED: set(),
            JobState.TERMINAL_FAILED: set(),
        }
        if target not in allowed[current]:
            raise CheckpointIntegrityError(
                f"Illegal durable state transition: {current.value}->{target.value}"
            )
        record["transitions"].append(
            {
                "from": current.value,
                "to": target.value,
                "reason": reason,
                "at_utc": _timestamp_iso(now),
            }
        )
        record["state"] = target.value
        record["updated_at_utc"] = _timestamp_iso(now)

    def _audit_transport_identity(
        self,
        spec: DurableJobSpec,
        *,
        model: Optional[str],
        slot: Optional[str],
        attempts: list[dict[str, Any]],
    ) -> None:
        if model is not None and model != spec.model:
            raise CheckpointIntegrityError("Transport changed the requested model")
        if slot is not None and slot != spec.credential_slot:
            raise CheckpointIntegrityError("Transport changed the credential slot")
        for attempt in attempts:
            attempt_model = attempt.get("model")
            attempt_slot = attempt.get("slot_id")
            if attempt_model is not None and attempt_model != spec.model:
                raise CheckpointIntegrityError("Attempt history changed the model")
            if attempt_slot is not None and attempt_slot != spec.credential_slot:
                raise CheckpointIntegrityError("Attempt history changed the credential")

    def execute_window(
        self,
        spec: DurableJobSpec,
        transport: Callable[[DurableJobSpec, int, str], Mapping[str, Any]],
    ) -> dict[str, Any]:
        path = self._path(spec.job_id)
        with self._lock:
            record = self.ensure_job(spec)
            state = JobState(record["state"])
            if state in {JobState.SUCCEEDED_LOCKED, JobState.TERMINAL_FAILED}:
                return record
            now = float(self._clock())
            if state == JobState.DEFERRED_TRANSPORT:
                eligible = record.get("next_eligible_at_epoch")
                if not isinstance(eligible, (int, float)):
                    raise CheckpointIntegrityError("Deferred checkpoint lacks cooldown")
                if now < float(eligible):
                    raise CooldownPending(float(eligible) - now)
            if int(record["window_count"]) >= self.max_execution_windows:
                raise CheckpointIntegrityError("Execution window cap reached without terminal state")
            window_number = int(record["window_count"]) + 1
            self._transition(record, JobState.IN_FLIGHT, "WINDOW_STARTED", now)
            record["window_count"] = window_number
            record["provider_attempts_per_window"].append(0)
            record["next_eligible_at_epoch"] = None
            record["next_eligible_at_utc"] = None
            self._write(path, record)

        request_id = f"{spec.job_id}_W{window_number}"
        started = float(self._clock())
        try:
            response = dict(transport(spec, window_number, request_id))
        except DurableTransportFailure as failure:
            ended = float(self._clock())
            attempts = [dict(item) for item in failure.attempts]
            with self._lock:
                record = self._store.read(path)
                self._validate_record(spec, record)
                if record["state"] != JobState.IN_FLIGHT.value:
                    raise CheckpointIntegrityError("Window lost its in-flight state")
                if not 0 <= failure.provider_attempts <= self.max_provider_attempts_per_window:
                    raise CheckpointIntegrityError("Window provider-attempt cap violated")
                record["provider_attempts_per_window"][-1] = failure.provider_attempts
                record["total_provider_operations"] += failure.provider_attempts
                try:
                    self._audit_transport_identity(
                        spec, model=None, slot=None, attempts=attempts
                    )
                except CheckpointIntegrityError:
                    record["windows"].append(
                        {
                            "window": window_number,
                            "started_at_utc": _timestamp_iso(started),
                            "ended_at_utc": _timestamp_iso(ended),
                            "outcome": "IDENTITY_VIOLATION",
                            "provider_attempts": failure.provider_attempts,
                            "attempt_history": [],
                        }
                    )
                    self._transition(
                        record,
                        JobState.TERMINAL_FAILED,
                        "TRANSPORT_IDENTITY_VIOLATION",
                        ended,
                    )
                    self._write(path, record)
                    raise
                counts = Counter(record["failure_fingerprints"])
                counts[failure.fingerprint] += 1
                record["failure_fingerprints"] = dict(sorted(counts.items()))
                record["windows"].append(
                    {
                        "window": window_number,
                        "started_at_utc": _timestamp_iso(started),
                        "ended_at_utc": _timestamp_iso(ended),
                        "outcome": "TRANSPORT_FAILURE",
                        "category": failure.category,
                        "fingerprint": failure.fingerprint,
                        "provider_attempts": failure.provider_attempts,
                        "attempt_history": attempts,
                    }
                )
                if failure.category == "AUTH_FAILURE":
                    self._transition(
                        record,
                        JobState.TERMINAL_FAILED,
                        "AUTH_FAILURE_NON_DEFERABLE",
                        ended,
                    )
                elif (
                    failure.category in DEFER_ELIGIBLE_CATEGORIES
                    and window_number < self.max_execution_windows
                ):
                    cooldown = max(
                        self.window_cooldown_seconds,
                        failure.retry_after_seconds or 0.0,
                    )
                    record["next_eligible_at_epoch"] = ended + cooldown
                    record["next_eligible_at_utc"] = _timestamp_iso(ended + cooldown)
                    self._transition(
                        record,
                        JobState.DEFERRED_TRANSPORT,
                        f"DEFERRED_{failure.category}",
                        ended,
                    )
                else:
                    reason = (
                        "WINDOW_LIMIT_EXHAUSTED"
                        if failure.category in DEFER_ELIGIBLE_CATEGORIES
                        else f"NON_DEFERABLE_{failure.category}"
                    )
                    self._transition(
                        record, JobState.TERMINAL_FAILED, reason, ended
                    )
                self._write(path, record)
                self._validate_record(spec, record)
                return record
        except Exception:
            ended = float(self._clock())
            with self._lock:
                record = self._store.read(path)
                self._validate_record(spec, record)
                if record["state"] == JobState.IN_FLIGHT.value:
                    record["windows"].append(
                        {
                            "window": window_number,
                            "started_at_utc": _timestamp_iso(started),
                            "ended_at_utc": _timestamp_iso(ended),
                            "outcome": "UNCAUGHT_EXCEPTION",
                            "provider_attempts": 0,
                            "attempt_history": [],
                        }
                    )
                    self._transition(
                        record,
                        JobState.TERMINAL_FAILED,
                        "UNCAUGHT_EXCEPTION",
                        ended,
                    )
                    self._write(path, record)
            raise

        ended = float(self._clock())
        attempts = [dict(item) for item in response.get("transport_attempts", [])]
        accounting = response.get("attempt_accounting", {})
        provider_attempts = int(accounting.get("total_provider_attempts", len(attempts)))
        with self._lock:
            record = self._store.read(path)
            self._validate_record(spec, record)
            if record["state"] != JobState.IN_FLIGHT.value:
                raise CheckpointIntegrityError("Successful window lost its in-flight state")
            if not 1 <= provider_attempts <= self.max_provider_attempts_per_window:
                raise CheckpointIntegrityError("Successful window attempt cap violated")
            record["provider_attempts_per_window"][-1] = provider_attempts
            record["total_provider_operations"] += provider_attempts
            try:
                self._audit_transport_identity(
                    spec,
                    model=response.get("model_requested"),
                    slot=response.get("slot_id"),
                    attempts=attempts,
                )
            except CheckpointIntegrityError:
                record["windows"].append(
                    {
                        "window": window_number,
                        "started_at_utc": _timestamp_iso(started),
                        "ended_at_utc": _timestamp_iso(ended),
                        "outcome": "IDENTITY_VIOLATION",
                        "provider_attempts": provider_attempts,
                        "attempt_history": [],
                    }
                )
                self._transition(
                    record,
                    JobState.TERMINAL_FAILED,
                    "TRANSPORT_IDENTITY_VIOLATION",
                    ended,
                )
                self._write(path, record)
                raise
            raw_response = str(response.get("raw_content", ""))
            success = {
                "window": window_number,
                "locked_at_utc": _timestamp_iso(ended),
                "raw_response": raw_response,
                "response_sha256": hashlib.sha256(
                    raw_response.encode("utf-8")
                ).hexdigest(),
                "provider_metadata": response.get("provider_response_metadata"),
                "model_reported_version": response.get("model_reported_if_available"),
                "usage": response.get("usage_metadata"),
                "attempt_history": attempts,
            }
            try:
                self._ensure_secret_safe(success)
            except CheckpointIntegrityError:
                record["windows"].append(
                    {
                        "window": window_number,
                        "started_at_utc": _timestamp_iso(started),
                        "ended_at_utc": _timestamp_iso(ended),
                        "outcome": "SECRET_LEAK_GUARD",
                        "provider_attempts": provider_attempts,
                        "attempt_history": [],
                    }
                )
                self._transition(
                    record,
                    JobState.TERMINAL_FAILED,
                    "SECRET_LEAK_GUARD",
                    ended,
                )
                self._write(path, record)
                raise
            record["windows"].append(
                {
                    "window": window_number,
                    "started_at_utc": _timestamp_iso(started),
                    "ended_at_utc": _timestamp_iso(ended),
                    "outcome": "SUCCESS_LOCKED",
                    "provider_attempts": provider_attempts,
                    "attempt_history": attempts,
                }
            )
            record["first_success"] = success
            self._transition(
                record, JobState.SUCCEEDED_LOCKED, "FIRST_SUCCESS_LOCKED", ended
            )
            self._write(path, record)
            self._validate_record(spec, record)
            return record


def summarize_job(record: Mapping[str, Any]) -> dict[str, Any]:
    transitions = list(record.get("transitions", []))
    windows = list(record.get("windows", []))
    category_counts = Counter(
        str(window.get("category"))
        for window in windows
        if window.get("category")
    )
    attempt_category_counts = Counter(
        str(attempt.get("classified_result"))
        for window in windows
        for attempt in window.get("attempt_history", [])
        if attempt.get("classified_result")
    )
    http_status_counts = Counter(
        str(attempt.get("http_status"))
        for window in windows
        for attempt in window.get("attempt_history", [])
        if attempt.get("http_status") is not None
    )
    first_success = record.get("first_success") or {}
    return {
        "job_id": record["job_id"],
        "request_fingerprint": record["request_fingerprint"],
        "state": record["state"],
        "model": record["model_requested"],
        "credential_slot": record["credential_slot"],
        "windows_used": record["window_count"],
        "provider_attempts_per_window": record["provider_attempts_per_window"],
        "total_provider_operations": record["total_provider_operations"],
        "failure_fingerprints": record["failure_fingerprints"],
        "window_failure_categories": dict(sorted(category_counts.items())),
        "provider_attempt_categories": dict(sorted(attempt_category_counts.items())),
        "provider_http_status_counts": dict(sorted(http_status_counts.items())),
        "deferred_count": sum(
            item.get("to") == JobState.DEFERRED_TRANSPORT.value for item in transitions
        ),
        "resumed_count": sum(
            item.get("from") == JobState.DEFERRED_TRANSPORT.value
            and item.get("to") == JobState.IN_FLIGHT.value
            for item in transitions
        ),
        "success_lock_count": sum(
            item.get("to") == JobState.SUCCEEDED_LOCKED.value for item in transitions
        ),
        "first_success_response_sha256": first_success.get("response_sha256"),
        "model_reported_version": first_success.get("model_reported_version"),
    }
