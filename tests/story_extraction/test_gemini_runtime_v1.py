"""Offline tests for M4-04A Gemini transport and credential pool."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_extraction import gemini_key_pool_v1 as K  # noqa: E402
from tools.story_extraction import gemini_transport_v1 as T  # noqa: E402


FAKE_SECRET = "FAKE_SECRET_NEVER_LEAK_123"


class FakeClock:
    def __init__(self, value=1_700_000_000.0):
        self.value = value
        self.sleeps = []

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class ProviderError(Exception):
    def __init__(self, status_code, message="provider details", retry_after=None):
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(message)


def response(text='{"schema":"STORY_EXTRACTION_BATCH/v0"}', model="gemini-test"):
    usage = SimpleNamespace(
        prompt_token_count=10,
        candidates_token_count=5,
        total_token_count=15,
        cached_content_token_count=None,
        thoughts_token_count=None,
    )
    return SimpleNamespace(
        text=text,
        parsed=None,
        model_version=model,
        response_id="response-1",
        usage_metadata=usage,
        candidates=[],
    )


class FakeFactory:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.keys_seen = []
        self.calls = []

    def __call__(self, api_key):
        self.keys_seen.append(api_key)
        factory = self

        class Client:
            def generate(self, **kwargs):
                factory.calls.append(kwargs)
                outcome = factory.outcomes.pop(0)
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome

        return Client()


def config(*items, model=""):
    env = {"GEMINI_MODEL": model}
    for number, secret, label in items:
        env[f"GEMINI_API_KEY_{number}"] = secret
        env[f"GEMINI_PROJECT_LABEL_{number}"] = label
    return K.load_runtime_config(dotenv_path=REPO / "missing-test-env", environ=env)


def transport(runtime_config, outcomes, *, retries=2, clock=None):
    clock = clock or FakeClock()
    factory = FakeFactory(outcomes)
    pool = K.GeminiKeyPool(runtime_config.credentials, clock=clock)
    adapter = T.GeminiTransport(
        pool,
        factory,
        max_transport_retries=retries,
        clock=clock,
        sleep=clock.sleep,
    )
    return adapter, factory, pool, clock


def generate(adapter):
    return adapter.generate("system", "user", "gemini-test", {"temperature": 0}, "req-1")


class TestConfiguration(unittest.TestCase):
    def test_no_credentials_is_clean_waiting_state(self):
        loaded = config()
        self.assertEqual(loaded.public_summary(), {
            "credential_slots": 0,
            "project_groups": 0,
            "model_configured": False,
        })

    def test_one_credential(self):
        loaded = config((1, "secret-1", "project-a"))
        self.assertEqual(len(loaded.credentials), 1)
        self.assertEqual(loaded.project_group_count, 1)

    def test_several_credentials_sorted_by_numeric_slot(self):
        loaded = config((10, "secret-10", "p"), (2, "secret-2", "p"))
        self.assertEqual([s.slot_id for s in loaded.credentials], ["gemini_slot_2", "gemini_slot_10"])

    def test_duplicate_credentials_rejected_without_value(self):
        with self.assertRaises(K.GeminiConfigError) as caught:
            config((1, FAKE_SECRET, "a"), (2, FAKE_SECRET, "b"))
        self.assertNotIn(FAKE_SECRET, str(caught.exception))

    def test_project_label_cannot_publish_credential_material(self):
        with self.assertRaises(K.GeminiConfigError) as caught:
            config((1, FAKE_SECRET, f"project-{FAKE_SECRET}"))
        self.assertNotIn(FAKE_SECRET, str(caught.exception))

    def test_duplicate_numeric_slot_alias_is_rejected(self):
        env = {"GEMINI_API_KEY_1": "s1", "GEMINI_API_KEY_01": "s2"}
        with self.assertRaises(K.GeminiConfigError):
            K.load_runtime_config(REPO / "missing-test-env", env)

    def test_same_project_keys_are_grouped(self):
        loaded = config((1, "s1", "a"), (2, "s2", "a"))
        self.assertEqual(loaded.project_group_count, 1)

    def test_independent_projects_are_separate(self):
        loaded = config((1, "s1", "a"), (2, "s2", "b"))
        self.assertEqual(loaded.project_group_count, 2)

    def test_unlabeled_credentials_are_distinct_unknown_groups(self):
        loaded = config((1, "s1", ""), (2, "s2", ""))
        self.assertEqual(loaded.project_group_count, 2)
        self.assertTrue(all(s.project_label == K.UNKNOWN_PROJECT_LABEL for s in loaded.credentials))

    def test_dotenv_process_environment_has_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "GEMINI_API_KEY_1" + "=file-secret\nGEMINI_PROJECT_LABEL_1=file\n",
                encoding="utf-8",
            )
            loaded = K.load_runtime_config(path, {"GEMINI_API_KEY_1": "env-secret"})
        self.assertEqual(loaded.credentials[0].api_key if hasattr(loaded.credentials[0], "api_key") else loaded.credentials[0]._api_key, "env-secret")
        self.assertEqual(loaded.credentials[0].project_label, "file")

    def test_config_check_never_constructs_a_client(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = T.check_config(Path(directory) / ".env")
        self.assertEqual(summary["credential_slots"], 0)

    def test_cli_waiting_output_has_counts_and_no_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            output = StringIO()
            with redirect_stdout(output):
                code = T.main(["--check-config", "--env-file", str(Path(directory) / ".env")])
        self.assertEqual(code, 0)
        self.assertIn("WAITING_FOR_USER_CREDENTIALS", output.getvalue())
        self.assertNotIn("API_KEY_", output.getvalue())


class TestPoolScheduling(unittest.TestCase):
    def test_deterministic_round_robin_across_and_within_groups(self):
        loaded = config((1, "s1", "a"), (2, "s2", "a"), (3, "s3", "b"))
        pool = K.GeminiKeyPool(loaded.credentials, clock=lambda: 0)
        self.assertEqual(
            [pool.acquire().slot_id for _ in range(4)],
            ["gemini_slot_1", "gemini_slot_3", "gemini_slot_2", "gemini_slot_3"],
        )

    def test_429_cools_whole_project_group(self):
        loaded = config((1, "s1", "a"), (2, "s2", "a"), (3, "s3", "b"))
        pool = K.GeminiKeyPool(loaded.credentials, clock=lambda: 0)
        first = pool.acquire()
        pool.cool_project_group(first.slot_id, 10, now=0)
        self.assertEqual(pool.acquire(now=0).slot_id, "gemini_slot_3")

    def test_429_does_not_hammer_second_key_in_same_group(self):
        loaded = config((1, "s1", "a"), (2, "s2", "a"))
        pool = K.GeminiKeyPool(loaded.credentials, clock=lambda: 0)
        pool.cool_project_group("gemini_slot_1", 10, now=0)
        with self.assertRaises(K.GeminiPoolExhausted):
            pool.acquire(now=0)

    def test_auth_failure_disables_only_affected_slot(self):
        loaded = config((1, "s1", "a"), (2, "s2", "a"))
        pool = K.GeminiKeyPool(loaded.credentials, clock=lambda: 0)
        pool.disable_slot("gemini_slot_1")
        self.assertEqual(pool.acquire(now=0).slot_id, "gemini_slot_2")


class TestTransport(unittest.TestCase):
    def test_success_record_is_sanitized_and_complete(self):
        adapter, factory, _, _ = transport(config((1, "s1", "a")), [response()])
        result = generate(adapter)
        self.assertEqual(result["provider"], "Google Gemini API")
        self.assertEqual(result["slot_id"], "gemini_slot_1")
        self.assertEqual(result["transport_attempts"][0]["outcome"], "SUCCESS")
        self.assertEqual(result["usage_metadata"]["total_token_count"], 15)
        self.assertEqual(factory.calls[0]["generation_config"], {"temperature": 0})

    def test_independent_project_can_fail_over_after_429_without_sleep(self):
        loaded = config((1, "s1", "a"), (2, "s2", "b"))
        adapter, factory, _, clock = transport(loaded, [ProviderError(429, retry_after=30), response()])
        result = generate(adapter)
        self.assertEqual(factory.keys_seen, ["s1", "s2"])
        self.assertEqual(clock.sleeps, [])
        self.assertEqual(result["slot_id"], "gemini_slot_2")

    def test_auth_failure_retries_with_another_slot(self):
        loaded = config((1, "s1", "a"), (2, "s2", "a"))
        adapter, factory, _, _ = transport(loaded, [ProviderError(401), response()])
        result = generate(adapter)
        self.assertEqual(factory.keys_seen, ["s1", "s2"])
        self.assertEqual(result["slot_id"], "gemini_slot_2")

    def test_invalid_key_reported_as_400_disables_slot(self):
        loaded = config((1, "s1", "a"), (2, "s2", "a"))
        adapter, factory, _, _ = transport(
            loaded, [ProviderError(400, "API key not valid"), response()]
        )
        result = generate(adapter)
        self.assertEqual(factory.keys_seen, ["s1", "s2"])
        self.assertEqual(result["slot_id"], "gemini_slot_2")

    def test_5xx_retry_is_bounded(self):
        failures = [ProviderError(503), ProviderError(503), ProviderError(503)]
        adapter, factory, _, clock = transport(config((1, "s1", "a")), failures)
        with self.assertRaises(T.GeminiTransportError) as caught:
            generate(adapter)
        self.assertEqual(len(factory.calls), 3)
        self.assertEqual(clock.sleeps, [1.0, 2.0])
        self.assertEqual(caught.exception.attempts, 3)

    def test_retry_after_is_respected(self):
        adapter, _, _, clock = transport(
            config((1, "s1", "a")), [ProviderError(429, retry_after=7), response()]
        )
        generate(adapter)
        self.assertEqual(clock.sleeps, [7.0])

    def test_network_timeout_retries_same_semantic_request(self):
        adapter, factory, _, _ = transport(config((1, "s1", "a")), [TimeoutError(), response()])
        generate(adapter)
        self.assertEqual(factory.calls[0], factory.calls[1])

    def test_exhaustion_fails_closed(self):
        adapter, _, _, _ = transport(config((1, "s1", "a")), [ProviderError(401)], retries=0)
        with self.assertRaises(T.GeminiTransportError) as caught:
            generate(adapter)
        self.assertEqual(caught.exception.code, "AUTH_FAILURE")

    def test_unknown_provider_error_is_not_retried(self):
        adapter, factory, _, _ = transport(config((1, "s1", "a")), [ValueError("unsafe")])
        with self.assertRaises(T.GeminiTransportError):
            generate(adapter)
        self.assertEqual(len(factory.calls), 1)

    def test_transport_does_not_perform_structural_repair(self):
        adapter, factory, _, _ = transport(config((1, "s1", "a")), [response("not-json")])
        result = generate(adapter)
        self.assertEqual(result["raw_content"], "not-json")
        self.assertEqual(len(factory.calls), 1)

    def test_model_is_required_without_touching_client(self):
        adapter, factory, _, _ = transport(config((1, "s1", "a")), [response()])
        with self.assertRaises(K.GeminiConfigError):
            adapter.generate("s", "u", "", {}, "r")
        self.assertEqual(factory.calls, [])

    def test_secret_leak_guard_covers_result_metadata_and_repr(self):
        loaded = config((1, FAKE_SECRET, "project-safe"))
        adapter, _, pool, _ = transport(loaded, [response(FAKE_SECRET)])
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = generate(adapter)
        surfaces = [
            json.dumps(result, sort_keys=True),
            json.dumps(pool.public_metadata(), sort_keys=True),
            repr(loaded.credentials[0]),
            repr(pool),
            stdout.getvalue(),
            stderr.getvalue(),
        ]
        self.assertTrue(all(FAKE_SECRET not in surface for surface in surfaces))
        self.assertEqual(result["raw_content"], "[REDACTED]")

    def test_exception_message_is_sanitized(self):
        loaded = config((1, FAKE_SECRET, "a"))
        adapter, _, _, _ = transport(loaded, [ProviderError(400, FAKE_SECRET)])
        with self.assertRaises(T.GeminiTransportError) as caught:
            generate(adapter)
        self.assertNotIn(FAKE_SECRET, str(caught.exception))
        self.assertNotIn(FAKE_SECRET, repr(caught.exception))


class TestRepositorySecurity(unittest.TestCase):
    def test_no_local_model_fallback_in_runtime(self):
        source = (REPO / "tools/story_extraction/gemini_transport_v1.py").read_text(encoding="utf-8").lower()
        forbidden = "olla" + "ma"
        self.assertNotIn(forbidden, source)

    def test_env_is_ignored_and_example_is_allowed(self):
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", ".env"], cwd=REPO, check=False
        )
        example = subprocess.run(
            ["git", "check-ignore", "-q", ".env.example"], cwd=REPO, check=False
        )
        self.assertEqual(ignored.returncode, 0)
        self.assertNotEqual(example.returncode, 0)

    def test_env_example_has_blank_key_and_label_placeholders_without_fixed_model(self):
        content = (REPO / ".env.example").read_text(encoding="utf-8")
        assignments = [line for line in content.splitlines() if line and not line.startswith("#")]
        self.assertTrue(assignments)
        key_assignments = [line for line in assignments if line.startswith("GEMINI_API_KEY_")]
        label_assignments = [
            line for line in assignments if line.startswith("GEMINI_PROJECT_LABEL_")
        ]
        self.assertEqual(len(key_assignments), 3)
        self.assertEqual(len(label_assignments), 3)
        self.assertTrue(all(line.endswith("=") for line in key_assignments))
        self.assertTrue(all(line.endswith("=") for line in label_assignments))
        self.assertIn("GEMINI_MODEL=", assignments)
        self.assertNotIn("GEMINI_MODEL=gemini-", content)
        self.assertNotIn("AIza", content)
        self.assertNotIn(FAKE_SECRET, content)


if __name__ == "__main__":
    unittest.main()
