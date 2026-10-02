"""Versioned Gemini transport resilience remediation (V1.1).

V1.1 preserves the bounded V1 contract while adding model-aware rate buckets,
adaptive 429 protection, safe failure fingerprints, and diagnostic attempt
timelines. It never repairs semantic output or changes model/provider.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import random
import threading
import time
from typing import Any, Callable, Mapping, Optional

from tools.story_extraction.gemini_errors_v1 import (
    ErrorCategory,
    classify_error,
    sanitized_failure_metadata,
)
from tools.story_extraction.gemini_key_pool_v1 import (
    CredentialConfig,
    GeminiConfigError,
    GeminiKeyPool,
    GeminiPoolExhausted,
    UNKNOWN_PROJECT_LABEL,
)
from tools.story_extraction.gemini_resilience_v1 import (
    BoundedAdmissionController,
    ProjectLimit,
    ResilienceMetrics,
    _provider_metadata,
    _redact_tree,
    _usage_counts,
    _utc_iso,
    conservative_runtime_credentials,
    estimate_input_tokens,
)
from tools.story_extraction.gemini_transport_v1 import official_client_factory


RESILIENCE_VERSION = "GEMINI_TRANSPORT_RESILIENCE_V1_1"
CIRCUIT_VERSION = "GEMINI_PROJECT_MODEL_CIRCUIT_BREAKER_V1_1"
TRANSIENT_CATEGORIES = {
    ErrorCategory.SERVER_FAILURE,
    ErrorCategory.TIMEOUT,
    ErrorCategory.NETWORK_FAILURE,
}


class CircuitState(str):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class GeminiResilienceV11Error(RuntimeError):
    """Sanitized bounded-terminal-state error with a safe attempt timeline."""

    def __init__(
        self,
        category: ErrorCategory | str,
        attempts: list[dict[str, Any]],
        *,
        fingerprint: Optional[str] = None,
    ) -> None:
        self.category = ErrorCategory(category)
        self.provider_attempts = len(attempts)
        self.attempts = tuple(dict(attempt) for attempt in attempts)
        self.fingerprint = fingerprint
        super().__init__(
            f"Gemini resilience request failed safely: {self.category.value}; "
            f"provider_attempts={self.provider_attempts}"
        )


@dataclass(frozen=True)
class ResiliencePolicyV11:
    max_total_provider_attempts: int = 3
    max_transport_retries: int = 2
    max_credential_failovers: int = 2
    max_project_group_failovers: int = 2
    max_concurrency: int = 2
    queue_capacity: int = 16
    queue_wait_timeout_seconds: float = 180.0
    default_project_limit: ProjectLimit = field(default_factory=ProjectLimit)
    project_model_limits: Mapping[tuple[str, str], ProjectLimit] = field(default_factory=dict)
    max_local_rate_wait_seconds: float = 180.0
    max_scheduler_wait_seconds: float = 180.0
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 30.0
    backoff_jitter_ratio: float = 0.20
    circuit_failure_threshold: int = 3
    circuit_open_cooldown_seconds: float = 30.0
    half_open_probe_requests: int = 1
    adaptive_rate_limit_cooldown_seconds: float = 5.0
    adaptive_decrease_factor: float = 0.50
    adaptive_min_factor: float = 0.25
    adaptive_recovery_step: float = 0.10
    adaptive_successes_per_recovery: int = 2

    def __post_init__(self) -> None:
        if not 1 <= self.max_total_provider_attempts <= 3:
            raise GeminiConfigError("Total provider attempts must be between 1 and 3")
        budgets = (
            self.max_transport_retries,
            self.max_credential_failovers,
            self.max_project_group_failovers,
        )
        if any(value < 0 for value in budgets):
            raise GeminiConfigError("Retry and failover budgets must be non-negative")
        if self.max_concurrency < 1 or self.queue_capacity < 0:
            raise GeminiConfigError("Concurrency and queue configuration is invalid")
        if min(
            self.queue_wait_timeout_seconds,
            self.max_local_rate_wait_seconds,
            self.max_scheduler_wait_seconds,
            self.max_backoff_seconds,
        ) <= 0:
            raise GeminiConfigError("Wait limits must be positive")
        if not 0.0 <= self.backoff_jitter_ratio <= 1.0:
            raise GeminiConfigError("Backoff jitter ratio must be between zero and one")
        if self.circuit_failure_threshold < 1 or self.half_open_probe_requests < 1:
            raise GeminiConfigError("Circuit-breaker configuration is invalid")
        if not 0.0 < self.adaptive_min_factor <= self.adaptive_decrease_factor < 1.0:
            raise GeminiConfigError("Adaptive decrease factors are invalid")
        if not 0.0 < self.adaptive_recovery_step <= 1.0:
            raise GeminiConfigError("Adaptive recovery step is invalid")
        if self.adaptive_successes_per_recovery < 1:
            raise GeminiConfigError("Adaptive recovery threshold must be positive")


def _dotenv_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise GeminiConfigError(f"Invalid .env syntax at line {number}")
        name, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'\"', "'"}:
            value = value[1:-1]
        result[name.strip()] = value
    return result


def _positive_int(value: str, name: str, default: int) -> int:
    if not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as error:
        raise GeminiConfigError(f"{name} must be a positive integer") from error
    if parsed < 1:
        raise GeminiConfigError(f"{name} must be a positive integer")
    return parsed


def load_resilience_policy_v1_1(
    dotenv_path: Path | str = Path(".env"),
    environ: Optional[Mapping[str, str]] = None,
    **overrides: Any,
) -> ResiliencePolicyV11:
    """Load non-secret local limit policy; configured limits are user claims only."""
    path = Path(dotenv_path)
    source = _dotenv_values(path)
    process_env = os.environ if environ is None else environ
    for name in (
        "GEMINI_DEFAULT_RPM",
        "GEMINI_DEFAULT_TPM",
        "GEMINI_PROJECT_MODEL_LIMITS_FILE",
    ):
        if name in process_env:
            source[name] = process_env[name]
    default = ProjectLimit(
        rpm=_positive_int(source.get("GEMINI_DEFAULT_RPM", ""), "GEMINI_DEFAULT_RPM", 10),
        tpm=_positive_int(source.get("GEMINI_DEFAULT_TPM", ""), "GEMINI_DEFAULT_TPM", 3000),
    )
    limits: dict[tuple[str, str], ProjectLimit] = {}
    limits_name = source.get("GEMINI_PROJECT_MODEL_LIMITS_FILE", "").strip()
    if limits_name:
        limits_path = Path(limits_name)
        if not limits_path.is_absolute():
            limits_path = path.parent / limits_path
        try:
            payload = json.loads(limits_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise GeminiConfigError("Invalid private project/model limits file") from error
        groups = payload.get("project_model_limits", {}) if isinstance(payload, dict) else {}
        if not isinstance(groups, dict):
            raise GeminiConfigError("Invalid project/model limits structure")
        for group, models in groups.items():
            if not isinstance(group, str) or not isinstance(models, dict):
                raise GeminiConfigError("Invalid project/model limits structure")
            for model, values in models.items():
                if not isinstance(model, str) or not isinstance(values, dict):
                    raise GeminiConfigError("Invalid project/model limits structure")
                limits[(group, model)] = ProjectLimit(
                    rpm=_positive_int(str(values.get("rpm", "")), "rpm", default.rpm),
                    tpm=_positive_int(str(values.get("tpm", "")), "tpm", default.tpm),
                )
    values = {"default_project_limit": default, "project_model_limits": limits}
    values.update(overrides)
    return ResiliencePolicyV11(**values)


def live_safe_credentials(
    credentials: tuple[CredentialConfig, ...] | list[CredentialConfig],
) -> tuple[CredentialConfig, ...]:
    """Use explicit labeled groups, or exactly one unknown slot if none are labeled."""
    labeled = tuple(
        credential
        for credential in credentials
        if credential.project_label != UNKNOWN_PROJECT_LABEL
    )
    if labeled:
        return labeled
    return conservative_runtime_credentials(credentials)


class ResilienceMetricsV11(ResilienceMetrics):
    COUNTERS = ResilienceMetrics.COUNTERS + (
        "rpm_reservation_count",
        "tpm_reservation_count",
        "adaptive_rate_limit_event_count",
        "adaptive_rate_wait_count",
        "adaptive_recovery_count",
        "retry_after_429_count",
        "retry_after_5xx_count",
        "jittered_backoff_count",
        "circuit_inconclusive_reopen_count",
    )

    def __init__(self) -> None:
        super().__init__()
        self._fingerprints: Counter[str] = Counter()

    def observe_fingerprint(self, fingerprint: str) -> None:
        with self._lock:
            self._fingerprints[fingerprint] += 1

    def snapshot(self) -> dict[str, Any]:
        result = super().snapshot()
        with self._lock:
            result["failure_fingerprints"] = dict(sorted(self._fingerprints.items()))
        return result


@dataclass
class _RequestRecord:
    reservation_id: int
    timestamp: float


@dataclass
class _TokenRecord:
    reservation_id: int
    timestamp: float
    tokens: int


@dataclass
class _AdaptiveState:
    factor: float = 1.0
    cooldown_until: float = 0.0
    successes_since_change: int = 0


@dataclass
class _RateState:
    requests: deque[_RequestRecord] = field(default_factory=deque)
    tokens: deque[_TokenRecord] = field(default_factory=deque)
    adaptive: _AdaptiveState = field(default_factory=_AdaptiveState)


@dataclass(frozen=True)
class RateReservationV11:
    identity: tuple[str, str]
    reservation_id: int
    estimated_input_tokens: int
    reserved_tokens: int


@dataclass(frozen=True)
class RateDecisionV11:
    reservation: Optional[RateReservationV11]
    wait_seconds: float
    rpm_wait: bool
    tpm_wait: bool
    adaptive_wait: bool


class ProjectModelRateLimiter:
    WINDOW_SECONDS = 60.0

    def __init__(self, policy: ResiliencePolicyV11) -> None:
        self._policy = policy
        self._states: dict[tuple[str, str], _RateState] = {}
        self._next_reservation = 1
        self._lock = threading.RLock()

    def _configured_limit(
        self, group_id: str, project_label: str, model: str
    ) -> ProjectLimit:
        return (
            self._policy.project_model_limits.get((group_id, model))
            or self._policy.project_model_limits.get((project_label, model))
            or self._policy.default_project_limit
        )

    def reserve(
        self,
        group_id: str,
        project_label: str,
        model: str,
        estimated_input_tokens: int,
        maximum_output_tokens: int,
        now: float,
    ) -> RateDecisionV11:
        identity = (group_id, model)
        with self._lock:
            state = self._states.setdefault(identity, _RateState())
            self._prune(state, now)
            configured = self._configured_limit(group_id, project_label, model)
            factor = state.adaptive.factor
            limit = ProjectLimit(
                rpm=max(1, math.floor(configured.rpm * factor)),
                tpm=max(1, math.floor(configured.tpm * factor)),
            )
            reserved = estimated_input_tokens + maximum_output_tokens
            if reserved > limit.tpm:
                raise GeminiResilienceV11Error(ErrorCategory.LOCAL_RATE_LIMIT_WAIT, [])

            adaptive_wait = now < state.adaptive.cooldown_until
            adaptive_seconds = max(0.0, state.adaptive.cooldown_until - now)
            rpm_wait = len(state.requests) >= limit.rpm
            rpm_seconds = (
                max(0.0, state.requests[0].timestamp + self.WINDOW_SECONDS - now)
                if rpm_wait
                else 0.0
            )
            current_tokens = sum(record.tokens for record in state.tokens)
            tpm_wait = current_tokens + reserved > limit.tpm
            tpm_seconds = 0.0
            if tpm_wait:
                running = current_tokens
                for record in state.tokens:
                    running -= record.tokens
                    tpm_seconds = max(0.0, record.timestamp + self.WINDOW_SECONDS - now)
                    if running + reserved <= limit.tpm:
                        break
            wait = max(adaptive_seconds, rpm_seconds, tpm_seconds)
            if wait > 0:
                return RateDecisionV11(None, wait, rpm_wait, tpm_wait, adaptive_wait)

            reservation_id = self._next_reservation
            self._next_reservation += 1
            state.requests.append(_RequestRecord(reservation_id, now))
            state.tokens.append(_TokenRecord(reservation_id, now, reserved))
            return RateDecisionV11(
                RateReservationV11(identity, reservation_id, estimated_input_tokens, reserved),
                0.0,
                False,
                False,
                False,
            )

    def correct(self, reservation: RateReservationV11, actual_input: int, actual_output: int) -> None:
        with self._lock:
            state = self._states.get(reservation.identity)
            if state is None:
                return
            for record in state.tokens:
                if record.reservation_id == reservation.reservation_id:
                    record.tokens = max(0, actual_input) + max(0, actual_output)
                    return

    def cancel(self, reservation: RateReservationV11) -> None:
        """Remove a reservation when no provider attempt was made."""
        with self._lock:
            state = self._states.get(reservation.identity)
            if state is None:
                return
            state.requests = deque(
                item for item in state.requests if item.reservation_id != reservation.reservation_id
            )
            state.tokens = deque(
                item for item in state.tokens if item.reservation_id != reservation.reservation_id
            )

    def on_rate_limit(
        self,
        group_id: str,
        model: str,
        now: float,
        retry_after: Optional[float],
    ) -> dict[str, float]:
        identity = (group_id, model)
        with self._lock:
            state = self._states.setdefault(identity, _RateState())
            before = state.adaptive.factor
            state.adaptive.factor = max(
                self._policy.adaptive_min_factor,
                before * self._policy.adaptive_decrease_factor,
            )
            delay = (
                retry_after
                if retry_after is not None
                else self._policy.adaptive_rate_limit_cooldown_seconds
            )
            state.adaptive.cooldown_until = max(state.adaptive.cooldown_until, now + delay)
            state.adaptive.successes_since_change = 0
            return {
                "factor_before": before,
                "factor_after": state.adaptive.factor,
                "cooldown_seconds": max(0.0, state.adaptive.cooldown_until - now),
            }

    def on_success(self, group_id: str, model: str) -> bool:
        with self._lock:
            state = self._states.setdefault((group_id, model), _RateState())
            if state.adaptive.factor >= 1.0:
                return False
            state.adaptive.successes_since_change += 1
            if (
                state.adaptive.successes_since_change
                < self._policy.adaptive_successes_per_recovery
            ):
                return False
            state.adaptive.factor = min(
                1.0, state.adaptive.factor + self._policy.adaptive_recovery_step
            )
            state.adaptive.successes_since_change = 0
            return True

    def snapshot(self, group_id: str, project_label: str, model: str, now: float) -> dict[str, Any]:
        identity = (group_id, model)
        with self._lock:
            state = self._states.setdefault(identity, _RateState())
            self._prune(state, now)
            configured = self._configured_limit(group_id, project_label, model)
            return {
                "configured_rpm": configured.rpm,
                "configured_tpm": configured.tpm,
                "effective_factor": round(state.adaptive.factor, 6),
                "effective_rpm": max(1, math.floor(configured.rpm * state.adaptive.factor)),
                "effective_tpm": max(1, math.floor(configured.tpm * state.adaptive.factor)),
                "adaptive_cooldown_remaining_seconds": round(
                    max(0.0, state.adaptive.cooldown_until - now), 3
                ),
                "requests_last_window": len(state.requests),
            }

    def identities(self) -> tuple[tuple[str, str], ...]:
        with self._lock:
            return tuple(self._states)

    def _prune(self, state: _RateState, now: float) -> None:
        cutoff = now - self.WINDOW_SECONDS
        while state.requests and state.requests[0].timestamp <= cutoff:
            state.requests.popleft()
        while state.tokens and state.tokens[0].timestamp <= cutoff:
            state.tokens.popleft()


class ProjectModelCircuitBreaker:
    def __init__(self, policy: ResiliencePolicyV11) -> None:
        self._threshold = policy.circuit_failure_threshold
        self._cooldown = policy.circuit_open_cooldown_seconds
        self._probe_limit = policy.half_open_probe_requests
        self._state = CircuitState.CLOSED
        self._failure_streak = 0
        self._opened_until = 0.0
        self._half_open_inflight = 0
        self._lock = threading.RLock()

    def try_acquire(self, now: float) -> tuple[bool, bool]:
        with self._lock:
            transitioned = False
            if self._state == CircuitState.OPEN:
                if now < self._opened_until:
                    return False, False
                self._state = CircuitState.HALF_OPEN
                self._half_open_inflight = 0
                transitioned = True
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_inflight >= self._probe_limit:
                    return False, transitioned
                self._half_open_inflight += 1
            return True, transitioned

    def cancel_acquire(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN and self._half_open_inflight:
                self._half_open_inflight -= 1

    def on_success(self) -> bool:
        with self._lock:
            recovered = self._state == CircuitState.HALF_OPEN
            self._state = CircuitState.CLOSED
            self._failure_streak = 0
            self._opened_until = 0.0
            self._half_open_inflight = 0
            return recovered

    def on_transient_failure(self, now: float) -> bool:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._opened_until = now + self._cooldown
                self._half_open_inflight = 0
                return True
            self._failure_streak += 1
            if self._failure_streak >= self._threshold:
                self._state = CircuitState.OPEN
                self._opened_until = now + self._cooldown
                self._half_open_inflight = 0
                return True
            return False

    def on_non_health_response(self, now: float) -> bool:
        """Preserve CLOSED failure history; an inconclusive probe reopens."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._opened_until = now + self._cooldown
                self._half_open_inflight = 0
                return True
            return False

    def snapshot(self, now: float) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "failure_streak": self._failure_streak,
                "cooldown_remaining_seconds": round(max(0.0, self._opened_until - now), 3),
                "half_open_inflight": self._half_open_inflight,
            }


class CircuitRegistryV11:
    def __init__(self, policy: ResiliencePolicyV11) -> None:
        self._policy = policy
        self._breakers: dict[tuple[str, str], ProjectModelCircuitBreaker] = {}
        self._lock = threading.RLock()

    def breaker(self, group_id: str, model: str) -> ProjectModelCircuitBreaker:
        with self._lock:
            return self._breakers.setdefault(
                (group_id, model), ProjectModelCircuitBreaker(self._policy)
            )


class GeminiResilientTransportV11:
    """Bounded V1.1 runtime with one limiter reservation per real attempt."""

    def __init__(
        self,
        pool: GeminiKeyPool,
        client_factory: Callable[[str], Any] = official_client_factory,
        *,
        policy: Optional[ResiliencePolicyV11] = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        random_unit: Callable[[], float] = random.random,
    ) -> None:
        self.pool = pool
        self.policy = policy or ResiliencePolicyV11()
        self.metrics = ResilienceMetricsV11()
        self._client_factory = client_factory
        self._clock = clock
        self._sleep = sleep
        self._random_unit = random_unit
        self._admission = BoundedAdmissionController(
            self.policy.max_concurrency,
            self.policy.queue_capacity,
            self.policy.queue_wait_timeout_seconds,
            monotonic,
        )
        self._rate_limiter = ProjectModelRateLimiter(self.policy)
        self._circuits = CircuitRegistryV11(self.policy)

    def generate(
        self,
        system_instruction: str,
        user_content: str,
        model: str,
        generation_config: Mapping[str, Any],
        request_id: str,
    ) -> dict[str, Any]:
        if not model.strip():
            raise GeminiConfigError("Gemini model is not configured")
        self.metrics.increment("semantic_request_count")
        estimated_input = estimate_input_tokens(system_instruction, user_content)
        self.metrics.increment("estimated_input_tokens", estimated_input)
        try:
            queue_wait_ms, queue_depth = self._admission.acquire()
        except Exception:
            self.metrics.increment("queue_rejected_count")
            self.metrics.increment("request_failure_count")
            raise GeminiResilienceV11Error(ErrorCategory.QUEUE_REJECTED, []) from None
        self.metrics.observe_queue_wait(queue_wait_ms)
        try:
            return self._generate_admitted(
                system_instruction,
                user_content,
                model,
                generation_config,
                request_id,
                estimated_input,
                queue_wait_ms,
                queue_depth,
            )
        finally:
            self._admission.release()

    def _generate_admitted(
        self,
        system_instruction: str,
        user_content: str,
        model: str,
        generation_config: Mapping[str, Any],
        request_id: str,
        estimated_input: int,
        queue_wait_ms: float,
        queue_depth: int,
    ) -> dict[str, Any]:
        request_started = self._clock()
        maximum_output = int(generation_config.get("max_output_tokens", 128))
        attempts: list[dict[str, Any]] = []
        transport_retries = 0
        credential_failovers = 0
        project_failovers = 0
        previous_slot: Optional[str] = None
        previous_group: Optional[str] = None
        last_category = ErrorCategory.PROVIDER_FAILURE
        last_fingerprint: Optional[str] = None

        while len(attempts) < self.policy.max_total_provider_attempts:
            try:
                lease = self._select_lease(model, previous_group)
            except GeminiResilienceV11Error as error:
                terminal = last_category if attempts else error.category
                return self._fail(terminal, attempts, last_fingerprint)

            breaker = self._circuits.breaker(lease.group_id, model)
            circuit_before = breaker.snapshot(self._clock())
            allowed, half_open = breaker.try_acquire(self._clock())
            if half_open:
                self.metrics.increment("circuit_half_open_count")
            if not allowed:
                # Selection checks OPEN circuits; this path is a concurrent
                # half-open probe collision and must not reserve local quota.
                return self._fail(ErrorCategory.CIRCUIT_OPEN, attempts, last_fingerprint)

            try:
                reservation, waits = self._reserve_rate_budget(
                    lease.group_id,
                    lease.project_label,
                    model,
                    estimated_input,
                    maximum_output,
                )
            except GeminiResilienceV11Error as error:
                breaker.cancel_acquire()
                return self._fail(error.category, attempts, last_fingerprint)

            if previous_slot is not None and lease.slot_id != previous_slot:
                if credential_failovers >= self.policy.max_credential_failovers:
                    self._rate_limiter.cancel(reservation)
                    breaker.cancel_acquire()
                    return self._fail(last_category, attempts, last_fingerprint)
                credential_failovers += 1
                self.metrics.increment("credential_failover_count")
            if previous_group is not None and lease.group_id != previous_group:
                if project_failovers >= self.policy.max_project_group_failovers:
                    self._rate_limiter.cancel(reservation)
                    breaker.cancel_acquire()
                    return self._fail(last_category, attempts, last_fingerprint)
                project_failovers += 1
                self.metrics.increment("project_group_failover_count")

            attempt_number = len(attempts) + 1
            now = self._clock()
            limiter_before = self._rate_limiter.snapshot(
                lease.group_id, lease.project_label, model, now
            )
            attempt_public: dict[str, Any] = {
                "attempt": attempt_number,
                "relative_timestamp_ms": round(max(0.0, now - request_started) * 1000.0, 3),
                "slot_id": lease.slot_id,
                "project_label": lease.project_label,
                "model": model,
                "local_rpm_wait_seconds": round(waits["rpm"], 6),
                "local_tpm_wait_seconds": round(waits["tpm"], 6),
                "adaptive_wait_seconds": round(waits["adaptive"], 6),
                "circuit_state_before": circuit_before["state"],
                "circuit_cooldown_before_seconds": circuit_before[
                    "cooldown_remaining_seconds"
                ],
                "adaptive_cooldown_before_seconds": limiter_before[
                    "adaptive_cooldown_remaining_seconds"
                ],
            }
            provider_started = self._clock()
            self.metrics.increment("provider_attempt_count")
            self.metrics.increment("rpm_reservation_count")
            self.metrics.increment("tpm_reservation_count")
            try:
                client = self._client_factory(lease.api_key)
                response = client.generate(
                    model=model,
                    system_instruction=system_instruction,
                    user_content=user_content,
                    generation_config=dict(generation_config),
                )
                provider_ended = self._clock()
                provider_latency = max(0.0, provider_ended - provider_started) * 1000.0
                self.metrics.observe_provider_latency(provider_latency)
                usage, actual_input, actual_output = _usage_counts(response)
                if actual_input or actual_output:
                    self._rate_limiter.correct(reservation, actual_input, actual_output)
                    self.metrics.increment("actual_input_tokens", actual_input)
                    self.metrics.increment("actual_output_tokens", actual_output)
                if self._rate_limiter.on_success(lease.group_id, model):
                    self.metrics.increment("adaptive_recovery_count")
                if breaker.on_success():
                    self.metrics.increment("circuit_recovery_count")
                limiter_after = self._rate_limiter.snapshot(
                    lease.group_id, lease.project_label, model, provider_ended
                )
                attempts.append(
                    {
                        **attempt_public,
                        "classified_result": ErrorCategory.SUCCESS.value,
                        "fingerprint": "SUCCESS",
                        "http_status": 200,
                        "http_status_family": "2xx",
                        "provider_reason": None,
                        "retry_after_present": False,
                        "retry_after_seconds": None,
                        "provider_latency_ms": round(provider_latency, 3),
                        "backoff_sleep_seconds": 0.0,
                        "circuit_state_after": breaker.snapshot(provider_ended)["state"],
                        "circuit_cooldown_after_seconds": breaker.snapshot(provider_ended)[
                            "cooldown_remaining_seconds"
                        ],
                        "adaptive_cooldown_after_seconds": limiter_after[
                            "adaptive_cooldown_remaining_seconds"
                        ],
                    }
                )
                self.metrics.increment("request_success_count")
                raw_content = getattr(response, "text", None)
                if raw_content is None:
                    raw_content = json.dumps(
                        getattr(response, "parsed", None), ensure_ascii=False, separators=(",", ":")
                    )
                record = {
                    "request_id": request_id,
                    "provider": "Google Gemini API",
                    "resilience": RESILIENCE_VERSION,
                    "model_requested": model,
                    "model_reported_if_available": getattr(response, "model_version", None),
                    "slot_id": lease.slot_id,
                    "project_label": lease.project_label,
                    "start_time": _utc_iso(request_started),
                    "end_time": _utc_iso(provider_ended),
                    "latency_seconds": max(0.0, provider_ended - request_started),
                    "queue_wait_ms": round(queue_wait_ms, 3),
                    "queue_depth": queue_depth,
                    "estimated_input_tokens": estimated_input,
                    "budget_reserved_tokens": reservation.reserved_tokens,
                    "actual_input_tokens": actual_input if actual_input else None,
                    "actual_output_tokens": actual_output if actual_output else None,
                    "usage_metadata": usage,
                    "provider_response_metadata": _provider_metadata(response),
                    "raw_content": str(raw_content),
                    "attempt_accounting": {
                        "total_provider_attempts": len(attempts),
                        "transport_retry_count": transport_retries,
                        "credential_failover_count": credential_failovers,
                        "project_group_failover_count": project_failovers,
                        "structural_repair_calls": 0,
                    },
                    "transport_attempts": attempts,
                }
                return _redact_tree(record, self.pool.redact)
            except Exception as error:
                provider_ended = self._clock()
                provider_latency = max(0.0, provider_ended - provider_started) * 1000.0
                self.metrics.observe_provider_latency(provider_latency)
                metadata = sanitized_failure_metadata(error, provider_ended)
                category = ErrorCategory(metadata["category"])
                last_category = category
                last_fingerprint = str(metadata["fingerprint"])
                self.metrics.observe_fingerprint(last_fingerprint)
                self._record_failure_category(category)
                retry_after = metadata["retry_after_seconds"]

                if category in TRANSIENT_CATEGORIES:
                    if breaker.on_transient_failure(provider_ended):
                        self.metrics.increment("circuit_open_count")
                else:
                    if breaker.on_non_health_response(provider_ended):
                        self.metrics.increment("circuit_inconclusive_reopen_count")

                if category == ErrorCategory.RATE_LIMIT:
                    self.metrics.increment("adaptive_rate_limit_event_count")
                    if retry_after is not None:
                        self.metrics.increment("retry_after_429_count")
                    self._rate_limiter.on_rate_limit(
                        lease.group_id, model, provider_ended, retry_after
                    )
                elif category == ErrorCategory.AUTH_FAILURE:
                    self.pool.disable_slot(lease.slot_id)

                backoff = 0.0
                consumes_transport_retry = (
                    category in TRANSIENT_CATEGORIES or category == ErrorCategory.RATE_LIMIT
                )
                retryable = consumes_transport_retry or category == ErrorCategory.AUTH_FAILURE
                if (
                    retryable
                    and len(attempts) + 1 < self.policy.max_total_provider_attempts
                    and transport_retries < self.policy.max_transport_retries
                    and category in TRANSIENT_CATEGORIES
                ):
                    backoff = self._backoff_seconds(transport_retries, retry_after)
                    if backoff > self.policy.max_scheduler_wait_seconds:
                        retryable = False
                        backoff = 0.0
                    elif retry_after is not None:
                        self.metrics.increment("retry_after_5xx_count")
                    else:
                        self.metrics.increment("jittered_backoff_count")

                limiter_after = self._rate_limiter.snapshot(
                    lease.group_id, lease.project_label, model, provider_ended
                )
                circuit_after = breaker.snapshot(provider_ended)
                attempts.append(
                    {
                        **attempt_public,
                        "classified_result": category.value,
                        "fingerprint": metadata["fingerprint"],
                        "http_status": metadata["http_status"],
                        "http_status_family": metadata["http_status_family"],
                        "provider_reason": metadata["provider_reason"],
                        "rate_limit_cause": metadata.get("rate_limit_cause"),
                        "retry_after_present": metadata["retry_after_present"],
                        "retry_after_seconds": retry_after,
                        "provider_latency_ms": round(provider_latency, 3),
                        "backoff_sleep_seconds": round(backoff, 6),
                        "circuit_state_after": circuit_after["state"],
                        "circuit_cooldown_after_seconds": circuit_after[
                            "cooldown_remaining_seconds"
                        ],
                        "adaptive_cooldown_after_seconds": limiter_after[
                            "adaptive_cooldown_remaining_seconds"
                        ],
                    }
                )

                if not retryable or len(attempts) >= self.policy.max_total_provider_attempts:
                    return self._fail(category, attempts, last_fingerprint)
                if consumes_transport_retry:
                    if transport_retries >= self.policy.max_transport_retries:
                        return self._fail(category, attempts, last_fingerprint)
                    transport_retries += 1
                    self.metrics.increment("transport_retry_count")
                if backoff > 0:
                    self._sleep(backoff)
                previous_slot = lease.slot_id
                previous_group = lease.group_id

        return self._fail(last_category, attempts, last_fingerprint)

    def _select_lease(self, model: str, avoid_group: Optional[str]):
        exclusion_passes = [{avoid_group}] if avoid_group else []
        exclusion_passes.append(set())
        for initial_excluded in exclusion_passes:
            excluded = {item for item in initial_excluded if item is not None}
            while True:
                try:
                    lease = self.pool.acquire(self._clock(), excluded_group_ids=excluded)
                except GeminiPoolExhausted:
                    break
                state = self._circuits.breaker(lease.group_id, model).snapshot(self._clock())
                if state["state"] != CircuitState.OPEN or state[
                    "cooldown_remaining_seconds"
                ] <= 0:
                    return lease
                excluded.add(lease.group_id)
        raise GeminiResilienceV11Error(ErrorCategory.CIRCUIT_OPEN, [])

    def _reserve_rate_budget(
        self,
        group_id: str,
        project_label: str,
        model: str,
        estimated_input: int,
        maximum_output: int,
    ) -> tuple[RateReservationV11, dict[str, float]]:
        total_wait = 0.0
        waits = {"rpm": 0.0, "tpm": 0.0, "adaptive": 0.0}
        while True:
            decision = self._rate_limiter.reserve(
                group_id,
                project_label,
                model,
                estimated_input,
                maximum_output,
                self._clock(),
            )
            if decision.reservation is not None:
                return decision.reservation, waits
            if total_wait + decision.wait_seconds > self.policy.max_local_rate_wait_seconds:
                raise GeminiResilienceV11Error(ErrorCategory.LOCAL_RATE_LIMIT_WAIT, [])
            if decision.rpm_wait:
                self.metrics.increment("local_rpm_wait_count")
                waits["rpm"] += decision.wait_seconds
            if decision.tpm_wait:
                self.metrics.increment("local_tpm_wait_count")
                waits["tpm"] += decision.wait_seconds
            if decision.adaptive_wait:
                self.metrics.increment("adaptive_rate_wait_count")
                waits["adaptive"] += decision.wait_seconds
            total_wait += decision.wait_seconds
            self._sleep(decision.wait_seconds)

    def _backoff_seconds(self, retry_index: int, retry_after: Optional[float]) -> float:
        if retry_after is not None:
            return max(0.0, retry_after)
        base = min(
            self.policy.max_backoff_seconds,
            self.policy.base_backoff_seconds * (2**retry_index),
        )
        unit = min(1.0, max(0.0, float(self._random_unit())))
        multiplier = 1.0 + self.policy.backoff_jitter_ratio * ((2.0 * unit) - 1.0)
        return min(self.policy.max_backoff_seconds, max(0.0, base * multiplier))

    def _record_failure_category(self, category: ErrorCategory) -> None:
        mapping = {
            ErrorCategory.RATE_LIMIT: "rate_limit_event_count",
            ErrorCategory.AUTH_FAILURE: "auth_disable_event_count",
            ErrorCategory.SERVER_FAILURE: "server_failure_count",
            ErrorCategory.TIMEOUT: "timeout_count",
            ErrorCategory.NETWORK_FAILURE: "network_failure_count",
        }
        metric = mapping.get(category)
        if metric:
            self.metrics.increment(metric)

    def _fail(
        self,
        category: ErrorCategory,
        attempts: list[dict[str, Any]],
        fingerprint: Optional[str],
    ):
        self.metrics.increment("request_failure_count")
        raise GeminiResilienceV11Error(
            category, attempts, fingerprint=fingerprint
        ) from None

    def health_snapshot(self) -> dict[str, Any]:
        now = self._clock()
        identities = self._rate_limiter.identities()
        groups = []
        for group_id, model in identities:
            label = self.pool.project_label_for_group(group_id)
            groups.append(
                {
                    "project_group": label,
                    "model": model,
                    "available_slots": self.pool.available_slot_count(group_id),
                    "circuit": self._circuits.breaker(group_id, model).snapshot(now),
                    "rate_limit": self._rate_limiter.snapshot(
                        group_id, label, model, now
                    ),
                }
            )
        return {
            "resilience": RESILIENCE_VERSION,
            "circuit_breaker": CIRCUIT_VERSION,
            **self._admission.snapshot(),
            "project_model_buckets": groups,
            "metrics": self.metrics.snapshot(),
        }
