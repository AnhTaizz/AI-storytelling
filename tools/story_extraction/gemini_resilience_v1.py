"""Bounded load-safety and resilience layer for the Gemini transport.

The layer is transport-only: it never judges model output and never performs a
structural repair, model switch, provider switch, or local-model fallback.
"""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import math
import threading
import time
from typing import Any, Callable, Iterator, Mapping, Optional

from tools.story_extraction.gemini_errors_v1 import (
    ErrorCategory,
    classify_error,
    retry_after_seconds,
)
from tools.story_extraction.gemini_key_pool_v1 import (
    CredentialConfig,
    GeminiConfigError,
    GeminiKeyPool,
    GeminiPoolExhausted,
    UNKNOWN_PROJECT_LABEL,
)
from tools.story_extraction.gemini_transport_v1 import official_client_factory


RESILIENCE_VERSION = "GEMINI_TRANSPORT_RESILIENCE_V1"
CIRCUIT_VERSION = "GEMINI_PROJECT_CIRCUIT_BREAKER_V1"
TRANSIENT_CATEGORIES = {
    ErrorCategory.SERVER_FAILURE,
    ErrorCategory.TIMEOUT,
    ErrorCategory.NETWORK_FAILURE,
}


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class GeminiResilienceError(RuntimeError):
    """A sanitized bounded-terminal-state error."""

    def __init__(self, category: ErrorCategory | str, provider_attempts: int) -> None:
        self.category = ErrorCategory(category)
        self.provider_attempts = provider_attempts
        super().__init__(
            f"Gemini resilience request failed safely: {self.category.value}; "
            f"provider_attempts={provider_attempts}"
        )


@dataclass(frozen=True)
class ProjectLimit:
    rpm: int = 10
    tpm: int = 3000

    def __post_init__(self) -> None:
        if self.rpm < 1 or self.tpm < 1:
            raise GeminiConfigError("RPM and TPM limits must be positive")


@dataclass(frozen=True)
class ResiliencePolicy:
    max_total_provider_attempts: int = 3
    max_transport_retries: int = 2
    max_credential_failovers: int = 2
    max_project_group_failovers: int = 2
    max_concurrency: int = 2
    queue_capacity: int = 16
    queue_wait_timeout_seconds: float = 180.0
    default_project_limit: ProjectLimit = field(default_factory=ProjectLimit)
    project_limits: Mapping[str, ProjectLimit] = field(default_factory=dict)
    max_local_rate_wait_seconds: float = 180.0
    max_scheduler_wait_seconds: float = 180.0
    base_backoff_seconds: float = 1.0
    circuit_failure_threshold: int = 3
    circuit_open_cooldown_seconds: float = 30.0
    half_open_probe_requests: int = 1

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
        if self.queue_wait_timeout_seconds <= 0 or self.max_scheduler_wait_seconds <= 0:
            raise GeminiConfigError("Wait limits must be positive")
        if self.circuit_failure_threshold < 1 or self.half_open_probe_requests < 1:
            raise GeminiConfigError("Circuit-breaker configuration is invalid")


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


class ResilienceMetrics:
    COUNTERS = (
        "semantic_request_count",
        "provider_attempt_count",
        "request_success_count",
        "request_failure_count",
        "rate_limit_event_count",
        "auth_disable_event_count",
        "server_failure_count",
        "timeout_count",
        "network_failure_count",
        "transport_retry_count",
        "credential_failover_count",
        "project_group_failover_count",
        "circuit_open_count",
        "circuit_half_open_count",
        "circuit_recovery_count",
        "estimated_input_tokens",
        "actual_input_tokens",
        "actual_output_tokens",
        "local_rpm_wait_count",
        "local_tpm_wait_count",
        "queue_rejected_count",
    )

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._counts = {name: 0 for name in self.COUNTERS}
        self._queue_wait_ms: list[float] = []
        self._provider_latency_ms: list[float] = []

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            if name not in self._counts:
                raise GeminiConfigError("Unknown resilience metric")
            self._counts[name] += amount

    def observe_queue_wait(self, milliseconds: float) -> None:
        with self._lock:
            self._queue_wait_ms.append(max(0.0, milliseconds))

    def observe_provider_latency(self, milliseconds: float) -> None:
        with self._lock:
            self._provider_latency_ms.append(max(0.0, milliseconds))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            result: dict[str, Any] = dict(self._counts)
            result.update(
                {
                    "queue_wait_ms_total": round(sum(self._queue_wait_ms), 3),
                    "queue_wait_ms_p50": round(_percentile(self._queue_wait_ms, 0.50), 3),
                    "queue_wait_ms_p95": round(_percentile(self._queue_wait_ms, 0.95), 3),
                    "provider_latency_ms_p50": round(
                        _percentile(self._provider_latency_ms, 0.50), 3
                    ),
                    "provider_latency_ms_p95": round(
                        _percentile(self._provider_latency_ms, 0.95), 3
                    ),
                    "structural_repair_calls": 0,
                }
            )
            return result


class BoundedAdmissionController:
    """Thread-safe FIFO admission with bounded waiting and explicit rejection."""

    def __init__(
        self,
        max_concurrency: int,
        queue_capacity: int,
        wait_timeout_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_concurrency = max_concurrency
        self.queue_capacity = queue_capacity
        self.wait_timeout_seconds = wait_timeout_seconds
        self._monotonic = monotonic
        self._condition = threading.Condition(threading.RLock())
        self._active = 0
        self._max_active_seen = 0
        self._tickets: deque[int] = deque()
        self._next_ticket = 0
        self._max_queue_depth_seen = 0

    def acquire(self) -> tuple[float, int]:
        started = self._monotonic()
        with self._condition:
            if self._active < self.max_concurrency and not self._tickets:
                self._active += 1
                self._max_active_seen = max(self._max_active_seen, self._active)
                return 0.0, 0
            if len(self._tickets) >= self.queue_capacity:
                raise GeminiResilienceError(ErrorCategory.QUEUE_REJECTED, 0)
            ticket = self._next_ticket
            self._next_ticket += 1
            self._tickets.append(ticket)
            depth_at_arrival = len(self._tickets)
            self._max_queue_depth_seen = max(self._max_queue_depth_seen, depth_at_arrival)
            deadline = started + self.wait_timeout_seconds
            while True:
                if self._tickets and self._tickets[0] == ticket and self._active < self.max_concurrency:
                    self._tickets.popleft()
                    self._active += 1
                    self._max_active_seen = max(self._max_active_seen, self._active)
                    waited_ms = (self._monotonic() - started) * 1000.0
                    return max(0.0, waited_ms), depth_at_arrival
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    try:
                        self._tickets.remove(ticket)
                    except ValueError:
                        pass
                    self._condition.notify_all()
                    raise GeminiResilienceError(ErrorCategory.QUEUE_REJECTED, 0)
                self._condition.wait(remaining)

    def release(self) -> None:
        with self._condition:
            self._active -= 1
            if self._active < 0:
                raise RuntimeError("Admission controller release imbalance")
            self._condition.notify_all()

    def snapshot(self) -> dict[str, int]:
        with self._condition:
            return {
                "active_requests": self._active,
                "queued_requests": len(self._tickets),
                "max_active_seen": self._max_active_seen,
                "max_queue_depth_seen": self._max_queue_depth_seen,
            }


@dataclass
class _TokenRecord:
    reservation_id: int
    timestamp: float
    tokens: int


@dataclass
class _RateState:
    requests: deque[float] = field(default_factory=deque)
    tokens: deque[_TokenRecord] = field(default_factory=deque)


@dataclass(frozen=True)
class RateReservation:
    group_id: str
    reservation_id: int
    estimated_input_tokens: int
    reserved_tokens: int


@dataclass(frozen=True)
class RateDecision:
    reservation: Optional[RateReservation]
    wait_seconds: float
    rpm_wait: bool
    tpm_wait: bool


class ProjectRateLimiter:
    WINDOW_SECONDS = 60.0

    def __init__(self, policy: ResiliencePolicy) -> None:
        self._policy = policy
        self._lock = threading.RLock()
        self._states: dict[str, _RateState] = {}
        self._next_reservation = 1

    def _limit(self, group_id: str, project_label: str) -> ProjectLimit:
        return (
            self._policy.project_limits.get(group_id)
            or self._policy.project_limits.get(project_label)
            or self._policy.default_project_limit
        )

    def reserve(
        self,
        group_id: str,
        project_label: str,
        estimated_input_tokens: int,
        maximum_output_tokens: int,
        now: float,
    ) -> RateDecision:
        with self._lock:
            state = self._states.setdefault(group_id, _RateState())
            self._prune(state, now)
            limit = self._limit(group_id, project_label)
            reserved = estimated_input_tokens + maximum_output_tokens
            if reserved > limit.tpm:
                raise GeminiResilienceError(ErrorCategory.LOCAL_RATE_LIMIT_WAIT, 0)

            rpm_wait = len(state.requests) >= limit.rpm
            rpm_seconds = (
                max(0.0, state.requests[0] + self.WINDOW_SECONDS - now) if rpm_wait else 0.0
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
            wait = max(rpm_seconds, tpm_seconds)
            if wait > 0:
                return RateDecision(None, wait, rpm_wait, tpm_wait)

            reservation_id = self._next_reservation
            self._next_reservation += 1
            state.requests.append(now)
            state.tokens.append(_TokenRecord(reservation_id, now, reserved))
            return RateDecision(
                RateReservation(group_id, reservation_id, estimated_input_tokens, reserved),
                0.0,
                False,
                False,
            )

    def correct(self, reservation: RateReservation, actual_input: int, actual_output: int) -> None:
        with self._lock:
            state = self._states.get(reservation.group_id)
            if state is None:
                return
            for record in state.tokens:
                if record.reservation_id == reservation.reservation_id:
                    record.tokens = max(0, actual_input) + max(0, actual_output)
                    return

    def cancel(self, reservation: RateReservation) -> None:
        with self._lock:
            state = self._states.get(reservation.group_id)
            if state is None:
                return
            state.tokens = deque(
                record for record in state.tokens if record.reservation_id != reservation.reservation_id
            )
            # Keep the RPM admission as a conservative accounting event. Another
            # thread may have reserved after this one, so removing by position
            # would corrupt shared project accounting.

    def requests_last_window(self, group_id: str, now: float) -> int:
        with self._lock:
            state = self._states.setdefault(group_id, _RateState())
            self._prune(state, now)
            return len(state.requests)

    def _prune(self, state: _RateState, now: float) -> None:
        cutoff = now - self.WINDOW_SECONDS
        while state.requests and state.requests[0] <= cutoff:
            state.requests.popleft()
        while state.tokens and state.tokens[0].timestamp <= cutoff:
            state.tokens.popleft()


class ProjectCircuitBreaker:
    def __init__(self, policy: ResiliencePolicy) -> None:
        self._threshold = policy.circuit_failure_threshold
        self._cooldown = policy.circuit_open_cooldown_seconds
        self._probe_limit = policy.half_open_probe_requests
        self._lock = threading.RLock()
        self._state = CircuitState.CLOSED
        self._failure_streak = 0
        self._opened_until = 0.0
        self._half_open_inflight = 0

    def try_acquire(self, now: float) -> tuple[bool, bool]:
        """Return (allowed, transitioned_to_half_open)."""
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

    def on_success(self) -> bool:
        """Close/reset and return whether this was a recovery."""
        with self._lock:
            recovered = self._state == CircuitState.HALF_OPEN
            self._state = CircuitState.CLOSED
            self._failure_streak = 0
            self._half_open_inflight = 0
            self._opened_until = 0.0
            return recovered

    def on_transient_failure(self, now: float) -> bool:
        """Record a transport-health failure and return whether circuit opened."""
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

    def on_non_health_response(self) -> bool:
        # 429/auth/provider errors prove that the transport endpoint responded;
        # they are not transport-health failures.
        return self.on_success()

    def snapshot(self, now: float) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state.value,
                "failure_streak": self._failure_streak,
                "cooldown_remaining_seconds": round(max(0.0, self._opened_until - now), 3),
                "half_open_inflight": self._half_open_inflight,
            }

    def seconds_until_probe(self, now: float) -> float:
        with self._lock:
            if self._state == CircuitState.OPEN:
                return max(0.0, self._opened_until - now)
            return 0.0


class CircuitRegistry:
    def __init__(self, group_ids: tuple[str, ...], policy: ResiliencePolicy) -> None:
        self._breakers = {group_id: ProjectCircuitBreaker(policy) for group_id in group_ids}

    def breaker(self, group_id: str) -> ProjectCircuitBreaker:
        return self._breakers[group_id]

    def minimum_wait(self, now: float) -> Optional[float]:
        waits = [breaker.seconds_until_probe(now) for breaker in self._breakers.values()]
        positive = [wait for wait in waits if wait > 0]
        return min(positive) if positive else None


def estimate_input_tokens(system_instruction: str, user_content: str) -> int:
    """Conservative deterministic approximation; makes no network countTokens call."""
    byte_count = len(system_instruction.encode("utf-8")) + len(user_content.encode("utf-8"))
    return max(1, math.ceil(byte_count / 3))


def conservative_runtime_credentials(
    credentials: tuple[CredentialConfig, ...] | list[CredentialConfig],
) -> tuple[CredentialConfig, ...]:
    """Keep at most one unlabeled slot; labeled project groups remain eligible."""
    selected: list[CredentialConfig] = []
    unknown_kept = False
    for credential in credentials:
        if credential.project_label == UNKNOWN_PROJECT_LABEL:
            if unknown_kept:
                continue
            unknown_kept = True
        selected.append(credential)
    return tuple(selected)


def _utc_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _usage_counts(response: Any) -> tuple[dict[str, int], int, int]:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return {}, 0, 0
    names = (
        "prompt_token_count",
        "candidates_token_count",
        "total_token_count",
        "cached_content_token_count",
        "thoughts_token_count",
    )
    safe = {
        name: int(getattr(usage, name))
        for name in names
        if isinstance(getattr(usage, name, None), (int, float))
    }
    return safe, safe.get("prompt_token_count", 0), safe.get("candidates_token_count", 0)


def _provider_metadata(response: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in ("response_id", "model_version"):
        value = getattr(response, name, None)
        if isinstance(value, (str, int, float, bool)):
            result[name] = value
    return result


def _redact_tree(value: Any, redact: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {str(key): _redact_tree(item, redact) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_tree(item, redact) for item in value]
    return value


class GeminiResilientTransport:
    """Transport gate with bounded queue, rate budgets, retries and circuits."""

    def __init__(
        self,
        pool: GeminiKeyPool,
        client_factory: Callable[[str], Any] = official_client_factory,
        *,
        policy: Optional[ResiliencePolicy] = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.pool = pool
        self.policy = policy or ResiliencePolicy()
        self.metrics = ResilienceMetrics()
        self._client_factory = client_factory
        self._clock = clock
        self._sleep = sleep
        self._admission = BoundedAdmissionController(
            self.policy.max_concurrency,
            self.policy.queue_capacity,
            self.policy.queue_wait_timeout_seconds,
            monotonic,
        )
        self._rate_limiter = ProjectRateLimiter(self.policy)
        self._circuits = CircuitRegistry(self.pool.group_ids(), self.policy)

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
        except GeminiResilienceError:
            self.metrics.increment("queue_rejected_count")
            self.metrics.increment("request_failure_count")
            raise
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
        scheduler_wait = 0.0
        local_rate_wait = 0.0
        last_category = ErrorCategory.PROVIDER_FAILURE

        while len(attempts) < self.policy.max_total_provider_attempts:
            try:
                lease = self._select_lease(scheduler_wait)
            except GeminiResilienceError as error:
                terminal = last_category if attempts else error.category
                return self._fail(terminal, len(attempts))
            if previous_slot is not None and lease.slot_id != previous_slot:
                if credential_failovers >= self.policy.max_credential_failovers:
                    return self._fail(last_category, len(attempts))
                credential_failovers += 1
                self.metrics.increment("credential_failover_count")
            if previous_group is not None and lease.group_id != previous_group:
                if project_failovers >= self.policy.max_project_group_failovers:
                    return self._fail(last_category, len(attempts))
                project_failovers += 1
                self.metrics.increment("project_group_failover_count")

            try:
                reservation, waited = self._reserve_rate_budget(
                    lease.group_id,
                    lease.project_label,
                    estimated_input,
                    maximum_output,
                    local_rate_wait,
                )
            except GeminiResilienceError as error:
                return self._fail(error.category, len(attempts))
            local_rate_wait += waited

            breaker = self._circuits.breaker(lease.group_id)
            allowed, half_open = breaker.try_acquire(self._clock())
            if half_open:
                self.metrics.increment("circuit_half_open_count")
            if not allowed:
                self._rate_limiter.cancel(reservation)
                # A concurrent half-open probe owns the only permit. Re-enter the
                # bounded scheduler instead of issuing a stampede.
                wait = breaker.seconds_until_probe(self._clock()) or 0.01
                if scheduler_wait + wait > self.policy.max_scheduler_wait_seconds:
                    return self._fail(ErrorCategory.CIRCUIT_OPEN, len(attempts))
                scheduler_wait += wait
                self._sleep(wait)
                continue

            attempt_number = len(attempts) + 1
            attempt_public = {
                "attempt": attempt_number,
                "slot_id": lease.slot_id,
                "project_label": lease.project_label,
            }
            provider_started = self._clock()
            self.metrics.increment("provider_attempt_count")
            try:
                client = self._client_factory(lease.api_key)
                response = client.generate(
                    model=model,
                    system_instruction=system_instruction,
                    user_content=user_content,
                    generation_config=dict(generation_config),
                )
                provider_ended = self._clock()
                self.metrics.observe_provider_latency((provider_ended - provider_started) * 1000.0)
                attempts.append({**attempt_public, "outcome": ErrorCategory.SUCCESS.value})
                usage, actual_input, actual_output = _usage_counts(response)
                if actual_input or actual_output:
                    self._rate_limiter.correct(reservation, actual_input, actual_output)
                    self.metrics.increment("actual_input_tokens", actual_input)
                    self.metrics.increment("actual_output_tokens", actual_output)
                if breaker.on_success():
                    self.metrics.increment("circuit_recovery_count")
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
                self.metrics.observe_provider_latency((provider_ended - provider_started) * 1000.0)
                category = classify_error(error)
                last_category = category
                attempts.append({**attempt_public, "outcome": category.value})
                self._record_failure_category(category)

                if category in TRANSIENT_CATEGORIES:
                    if breaker.on_transient_failure(self._clock()):
                        self.metrics.increment("circuit_open_count")
                else:
                    if breaker.on_non_health_response():
                        self.metrics.increment("circuit_recovery_count")

                if category == ErrorCategory.RATE_LIMIT:
                    delay = retry_after_seconds(error, self._clock())
                    if delay is None:
                        delay = self.policy.base_backoff_seconds * (2 ** transport_retries)
                    self.pool.cool_project_group(lease.slot_id, delay, self._clock())
                elif category == ErrorCategory.AUTH_FAILURE:
                    self.pool.disable_slot(lease.slot_id)
                elif category == ErrorCategory.PROVIDER_FAILURE:
                    return self._fail(category, len(attempts))

                if len(attempts) >= self.policy.max_total_provider_attempts:
                    return self._fail(category, len(attempts))
                if category in TRANSIENT_CATEGORIES or category == ErrorCategory.RATE_LIMIT:
                    if transport_retries >= self.policy.max_transport_retries:
                        return self._fail(category, len(attempts))
                    transport_retries += 1
                    self.metrics.increment("transport_retry_count")
                    if category in TRANSIENT_CATEGORIES:
                        self._sleep(
                            self.policy.base_backoff_seconds * (2 ** (transport_retries - 1))
                        )

                previous_slot = lease.slot_id
                previous_group = lease.group_id

        return self._fail(last_category, len(attempts))

    def _select_lease(self, already_waited: float):
        waited = already_waited
        while True:
            excluded: set[str] = set()
            while True:
                try:
                    lease = self.pool.acquire(
                        self._clock(), excluded_group_ids=excluded
                    )
                except GeminiPoolExhausted:
                    break
                circuit = self._circuits.breaker(lease.group_id).snapshot(self._clock())
                if (
                    circuit["state"] != CircuitState.OPEN.value
                    or circuit["cooldown_remaining_seconds"] <= 0
                ):
                    return lease
                excluded.add(lease.group_id)

            pool_wait = self.pool.seconds_until_available(self._clock())
            circuit_wait = self._circuits.minimum_wait(self._clock())
            # An otherwise available group is blocked only by an OPEN circuit.
            # Fail immediately; a later semantic request may become the single
            # half-open probe after cooldown. Do not hold a queue slot sleeping.
            if pool_wait == 0 and circuit_wait is not None:
                raise GeminiResilienceError(ErrorCategory.CIRCUIT_OPEN, 0)
            waits = [value for value in (pool_wait, circuit_wait) if value is not None and value > 0]
            if not waits:
                raise GeminiResilienceError(ErrorCategory.CIRCUIT_OPEN, 0)
            delay = min(waits)
            if waited + delay > self.policy.max_scheduler_wait_seconds:
                raise GeminiResilienceError(ErrorCategory.CIRCUIT_OPEN, 0)
            waited += delay
            self._sleep(delay)

    def _reserve_rate_budget(
        self,
        group_id: str,
        project_label: str,
        estimated_input: int,
        maximum_output: int,
        already_waited: float,
    ) -> tuple[RateReservation, float]:
        waited = 0.0
        while True:
            decision = self._rate_limiter.reserve(
                group_id,
                project_label,
                estimated_input,
                maximum_output,
                self._clock(),
            )
            if decision.reservation is not None:
                return decision.reservation, waited
            if decision.rpm_wait:
                self.metrics.increment("local_rpm_wait_count")
            if decision.tpm_wait:
                self.metrics.increment("local_tpm_wait_count")
            if already_waited + waited + decision.wait_seconds > self.policy.max_local_rate_wait_seconds:
                raise GeminiResilienceError(ErrorCategory.LOCAL_RATE_LIMIT_WAIT, 0)
            waited += decision.wait_seconds
            self._sleep(decision.wait_seconds)

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

    def _fail(self, category: ErrorCategory, attempts: int):
        self.metrics.increment("request_failure_count")
        raise GeminiResilienceError(category, attempts)

    def health_snapshot(self) -> dict[str, Any]:
        now = self._clock()
        groups = []
        for group_id in self.pool.group_ids():
            circuit = self._circuits.breaker(group_id).snapshot(now)
            groups.append(
                {
                    "project_group": self.pool.project_label_for_group(group_id),
                    "circuit_state": circuit["state"],
                    "active_half_open_probes": circuit["half_open_inflight"],
                    "available_slots": self.pool.available_slot_count(group_id),
                    "cooldown_remaining_seconds": self.pool.cooldown_remaining(group_id, now),
                    "circuit_cooldown_remaining_seconds": circuit[
                        "cooldown_remaining_seconds"
                    ],
                    "requests_last_window": self._rate_limiter.requests_last_window(
                        group_id, now
                    ),
                }
            )
        return {
            "resilience": RESILIENCE_VERSION,
            **self._admission.snapshot(),
            "groups": groups,
            "metrics": self.metrics.snapshot(),
        }
