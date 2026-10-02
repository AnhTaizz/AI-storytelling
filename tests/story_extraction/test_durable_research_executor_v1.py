"""Deterministic fault matrix for DURABLE_RESEARCH_EXECUTOR_V1."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_extraction.durable_research_executor_v1 import (  # noqa: E402
    CheckpointIntegrityError,
    CooldownPending,
    DurableJobSpec,
    DurableResearchExecutor,
    DurableTransportFailure,
    JobState,
    PersistentRollingOperationPacer,
)
from tools.story_extraction.run_gemini_durable_qualification_v1 import (  # noqa: E402
    CANDIDATES,
    JOB_COUNT,
    LOCKED_CREDENTIAL_SLOT,
    OUTPUT_TOKEN_CAP,
    PROMPT_FAMILY_SHA256,
    _build_specs,
)


class FakeTime:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


def job(
    job_id: str = "job_01",
    *,
    model: str = "gemini-3.8-flash",
    slot: str = "gemini_slot_3",
    user_prompt: str = "Return one tiny JSON object.",
) -> DurableJobSpec:
    return DurableJobSpec(
        job_id=job_id,
        model=model,
        system_prompt="Return only JSON.",
        user_prompt=user_prompt,
        generation_config={"temperature": 0, "max_output_tokens": 128},
        schema_response_mode="JSON_TEXT_NO_SEMANTIC_VALIDATION",
        credential_slot=slot,
        research_task_id="M4-04B1D",
    )


def success(spec: DurableJobSpec, raw: str = '{"status":"ok"}') -> dict:
    return {
        "model_requested": spec.model,
        "model_reported_if_available": spec.model + "-001",
        "slot_id": spec.credential_slot,
        "raw_content": raw,
        "provider_response_metadata": {"finish_reason": "STOP"},
        "usage_metadata": {"input_tokens": 4, "output_tokens": 4},
        "attempt_accounting": {"total_provider_attempts": 1},
        "transport_attempts": [
            {
                "attempt": 1,
                "model": spec.model,
                "slot_id": spec.credential_slot,
                "classified_result": "SUCCESS",
            }
        ],
    }


def transport_failure(
    spec: DurableJobSpec,
    category: str,
    *,
    attempts: int = 1,
    retry_after: float | None = None,
) -> DurableTransportFailure:
    return DurableTransportFailure(
        category,
        provider_attempts=attempts,
        fingerprint=f"{category}:TEST",
        retry_after_seconds=retry_after,
        attempts=[
            {
                "attempt": index,
                "model": spec.model,
                "slot_id": spec.credential_slot,
                "classified_result": category,
            }
            for index in range(1, attempts + 1)
        ],
    )


class SequenceTransport:
    def __init__(self, events) -> None:
        self.events = list(events)
        self.calls = 0

    def __call__(self, spec, window, request_id):
        del window, request_id
        self.calls += 1
        event = self.events.pop(0)
        if isinstance(event, Exception):
            raise event
        if callable(event):
            return event(spec)
        return event


class DurableExecutorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.time = FakeTime()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def executor(self, *, secrets=()) -> DurableResearchExecutor:
        return DurableResearchExecutor(
            self.root / "jobs",
            protocol_id="TEST_PROTOCOL_V1",
            clock=self.time.clock,
            forbidden_secrets=tuple(secrets),
        )

    def advance_cooldown(self, seconds: float = 60.0) -> None:
        self.time.advance(seconds)


class TestDeferredTransportMatrix(DurableExecutorTestCase):
    def test_503_then_next_window_success(self):
        spec = job()
        transport = SequenceTransport(
            [transport_failure(spec, "SERVER_FAILURE"), success]
        )
        executor = self.executor()
        first = executor.execute_window(spec, transport)
        self.assertEqual(first["state"], JobState.DEFERRED_TRANSPORT.value)
        self.advance_cooldown()
        final = executor.execute_window(spec, transport)
        self.assertEqual(final["state"], JobState.SUCCEEDED_LOCKED.value)
        self.assertEqual(final["provider_attempts_per_window"], [1, 1])

    def test_three_503_attempts_then_window_two_success(self):
        spec = job()
        transport = SequenceTransport(
            [transport_failure(spec, "SERVER_FAILURE", attempts=3), success]
        )
        executor = self.executor()
        executor.execute_window(spec, transport)
        self.advance_cooldown()
        final = executor.execute_window(spec, transport)
        self.assertEqual(final["total_provider_operations"], 4)

    def test_429_retry_after_controls_deferred_cooldown(self):
        spec = job()
        transport = SequenceTransport(
            [
                transport_failure(
                    spec, "RATE_LIMIT", retry_after=120.0
                ),
                success,
            ]
        )
        executor = self.executor()
        executor.execute_window(spec, transport)
        self.advance_cooldown(60)
        with self.assertRaises(CooldownPending) as caught:
            executor.execute_window(spec, transport)
        self.assertEqual(caught.exception.remaining_seconds, 60.0)
        self.advance_cooldown(60)
        self.assertEqual(
            executor.execute_window(spec, transport)["state"],
            JobState.SUCCEEDED_LOCKED.value,
        )

    def test_timeout_then_success(self):
        spec = job()
        transport = SequenceTransport(
            [transport_failure(spec, "TIMEOUT"), success]
        )
        executor = self.executor()
        executor.execute_window(spec, transport)
        self.advance_cooldown()
        self.assertEqual(
            executor.execute_window(spec, transport)["state"],
            JobState.SUCCEEDED_LOCKED.value,
        )

    def test_network_failure_across_multiple_windows(self):
        spec = job()
        transport = SequenceTransport(
            [
                transport_failure(spec, "NETWORK_FAILURE"),
                transport_failure(spec, "NETWORK_FAILURE"),
                success,
            ]
        )
        executor = self.executor()
        executor.execute_window(spec, transport)
        self.advance_cooldown()
        executor.execute_window(spec, transport)
        self.advance_cooldown()
        final = executor.execute_window(spec, transport)
        self.assertEqual(final["window_count"], 3)
        self.assertEqual(final["state"], JobState.SUCCEEDED_LOCKED.value)

    def test_three_failed_windows_become_terminal(self):
        spec = job()
        transport = SequenceTransport(
            [transport_failure(spec, "SERVER_FAILURE", attempts=3) for _ in range(3)]
        )
        executor = self.executor()
        for index in range(3):
            final = executor.execute_window(spec, transport)
            if index < 2:
                self.advance_cooldown()
        self.assertEqual(final["state"], JobState.TERMINAL_FAILED.value)
        self.assertEqual(final["total_provider_operations"], 9)

    def test_auth_failure_is_terminal_without_defer(self):
        spec = job()
        transport = SequenceTransport([transport_failure(spec, "AUTH_FAILURE")])
        executor = self.executor()
        final = executor.execute_window(spec, transport)
        self.assertEqual(final["state"], JobState.TERMINAL_FAILED.value)
        self.assertEqual(final["window_count"], 1)
        executor.execute_window(spec, transport)
        self.assertEqual(transport.calls, 1)

    def test_generic_provider_failure_is_transport_defer_eligible(self):
        spec = job()
        transport = SequenceTransport(
            [transport_failure(spec, "PROVIDER_FAILURE"), success]
        )
        executor = self.executor()
        self.assertEqual(
            executor.execute_window(spec, transport)["state"],
            JobState.DEFERRED_TRANSPORT.value,
        )
        self.advance_cooldown()
        self.assertEqual(
            executor.execute_window(spec, transport)["state"],
            JobState.SUCCEEDED_LOCKED.value,
        )


class TestFirstSuccessAndSemanticBoundary(DurableExecutorTestCase):
    def test_successful_response_never_reruns(self):
        spec = job()
        transport = SequenceTransport([success])
        executor = self.executor()
        first = executor.execute_window(spec, transport)
        second = executor.execute_window(spec, transport)
        self.assertEqual(first["first_success"], second["first_success"])
        self.assertEqual(transport.calls, 1)

    def test_success_lock_survives_simulated_process_crash(self):
        spec = job()
        transport = SequenceTransport([success])
        self.executor().execute_window(spec, transport)
        restarted = self.executor()
        record = restarted.execute_window(spec, transport)
        self.assertEqual(record["state"], JobState.SUCCEEDED_LOCKED.value)
        self.assertEqual(transport.calls, 1)

    def test_invalid_json_provider_success_is_locked_without_retry(self):
        spec = job()
        transport = SequenceTransport([lambda item: success(item, "not-json")])
        final = self.executor().execute_window(spec, transport)
        self.assertEqual(final["state"], JobState.SUCCEEDED_LOCKED.value)
        self.assertEqual(transport.calls, 1)

    def test_schema_invalid_provider_success_is_locked_without_retry(self):
        spec = job()
        transport = SequenceTransport(
            [lambda item: success(item, '{"unexpected":true}')]
        )
        final = self.executor().execute_window(spec, transport)
        self.assertEqual(final["state"], JobState.SUCCEEDED_LOCKED.value)
        self.assertEqual(transport.calls, 1)


class TestCheckpointAndRestartSafety(DurableExecutorTestCase):
    def test_request_fingerprint_mismatch_fails_closed(self):
        original = job()
        executor = self.executor()
        executor.ensure_job(original)
        changed = job(user_prompt="Different semantic request")
        with self.assertRaises(CheckpointIntegrityError):
            executor.ensure_job(changed)

    def test_checkpoint_corruption_fails_closed(self):
        spec = job()
        executor = self.executor()
        executor.ensure_job(spec)
        (self.root / "jobs" / "job_01.json").write_text("{broken", encoding="utf-8")
        with self.assertRaises(CheckpointIntegrityError):
            executor.ensure_job(spec)

    def test_deferred_checkpoint_resumes_in_new_executor_object(self):
        spec = job()
        transport = SequenceTransport(
            [transport_failure(spec, "SERVER_FAILURE"), success]
        )
        first_executor = self.executor()
        first_executor.execute_window(spec, transport)
        self.advance_cooldown()
        restarted = self.executor()
        final = restarted.execute_window(spec, transport)
        self.assertEqual(final["state"], JobState.SUCCEEDED_LOCKED.value)
        self.assertEqual(transport.calls, 2)

    def test_attempt_and_window_limits_never_exceed_three_and_nine(self):
        spec = job()
        transport = SequenceTransport(
            [transport_failure(spec, "SERVER_FAILURE", attempts=3) for _ in range(3)]
        )
        executor = self.executor()
        for index in range(3):
            final = executor.execute_window(spec, transport)
            if index < 2:
                self.advance_cooldown()
        executor.execute_window(spec, transport)
        self.assertEqual(transport.calls, 3)
        self.assertEqual(final["window_count"], 3)
        self.assertEqual(final["total_provider_operations"], 9)
        self.assertEqual(max(final["provider_attempts_per_window"]), 3)


class TestIdentityPacingAndSecrets(DurableExecutorTestCase):
    def test_global_six_per_sixty_pacing_survives_restart(self):
        checkpoint = self.root / "pacing.json"
        first = PersistentRollingOperationPacer(
            checkpoint, clock=self.time.clock, sleep=self.time.sleep
        )
        self.assertEqual([first.acquire() for _ in range(6)], [0.0] * 6)
        restarted = PersistentRollingOperationPacer(
            checkpoint, clock=self.time.clock, sleep=self.time.sleep
        )
        self.assertEqual(restarted.acquire(), 60.0)
        snapshot = restarted.snapshot()
        self.assertEqual(snapshot["max_rolling_reservations_observed"], 6)
        self.assertEqual(snapshot["invariant"], "PASS")

    def test_credential_change_fails_closed(self):
        spec = job()

        def changed_slot(item):
            result = success(item)
            result["slot_id"] = "gemini_slot_4"
            return result

        executor = self.executor()
        with self.assertRaises(CheckpointIntegrityError):
            executor.execute_window(spec, SequenceTransport([changed_slot]))
        self.assertEqual(executor.load_job(spec)["state"], JobState.TERMINAL_FAILED.value)


class TestLiveQualificationContract(DurableExecutorTestCase):
    def test_fixed_candidate_order_and_locked_credential(self):
        self.assertEqual(
            CANDIDATES,
            (
                "gemini-3.8-flash",
                "gemini-3.7-flash",
                "gemini-3.5-flash-lite",
            ),
        )
        for model in CANDIDATES:
            specs = _build_specs(model)
            self.assertEqual(len(specs), JOB_COUNT)
            self.assertEqual({item.model for item in specs}, {model})
            self.assertEqual(
                {item.credential_slot for item in specs},
                {LOCKED_CREDENTIAL_SLOT},
            )
            self.assertEqual(len({item.request_fingerprint for item in specs}), JOB_COUNT)

    def test_prompt_family_and_output_cap_are_locked(self):
        self.assertEqual(
            PROMPT_FAMILY_SHA256,
            "2f4d1c8ab918088370327d62c9db490dec0c0eb00821b1232761ca2445152641",
        )
        self.assertEqual(OUTPUT_TOKEN_CAP, 128)

    def test_model_change_fails_closed(self):
        spec = job()

        def changed_model(item):
            result = success(item)
            result["model_requested"] = "gemini-3.7-flash"
            return result

        executor = self.executor()
        with self.assertRaises(CheckpointIntegrityError):
            executor.execute_window(spec, SequenceTransport([changed_model]))
        self.assertEqual(executor.load_job(spec)["state"], JobState.TERMINAL_FAILED.value)

    def test_secret_leak_guard_fails_without_persisting_secret(self):
        secret = "configured-secret-never-persist"
        spec = job()
        executor = self.executor(secrets=(secret,))
        transport = SequenceTransport(
            [lambda item: success(item, '{"value":"' + secret + '"}')]
        )
        with self.assertRaises(CheckpointIntegrityError):
            executor.execute_window(spec, transport)
        checkpoint = (self.root / "jobs" / "job_01.json").read_text(encoding="utf-8")
        self.assertNotIn(secret, checkpoint)
        self.assertEqual(executor.load_job(spec)["state"], JobState.TERMINAL_FAILED.value)


if __name__ == "__main__":
    unittest.main()
