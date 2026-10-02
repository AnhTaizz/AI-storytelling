"""Fail-closed protocol-integrity tests for the M4-04B1D2 live runner."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_extraction.gemini_key_pool_v1 import (  # noqa: E402
    CredentialConfig,
    GeminiRuntimeConfig,
)
from tools.story_extraction.m4_04b1d2_confirmation_protocol_v1 import (  # noqa: E402
    EXPECTED_BASE_COMMIT,
    LOCKED_CREDENTIAL_SLOT,
    LOCKED_MODEL,
    ConfirmationProtocolError,
    build_confirmation_protocol,
    validate_confirmation_protocol_file,
    write_canonical_confirmation_protocol,
    write_protocol_validation_result,
)
from tools.story_extraction.run_gemini_durable_confirmation_v1 import (  # noqa: E402
    execute,
    prepare_confirmation_run,
)


class ConfirmationProtocolTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.protocol_path = self.root / "protocol.json"
        self.validation_path = self.root / "validation.json"
        self.checkpoints = self.root / "checkpoints"
        self.result_path = self.root / "result.json"
        self.profile_path = self.root / "profile.json"
        self.validated = write_canonical_confirmation_protocol(self.protocol_path)
        write_protocol_validation_result(self.validation_path, self.validated)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def config() -> GeminiRuntimeConfig:
        credential = CredentialConfig(
            slot_id=LOCKED_CREDENTIAL_SLOT,
            env_name="GEMINI_API_KEY_3",
            project_label="PROJECT_GROUP_UNKNOWN",
            group_id="PROJECT_GROUP_UNKNOWN:gemini_slot_3",
            _api_key="test-only-not-a-real-key",
        )
        return GeminiRuntimeConfig((credential,), "")

    def write_protocol_value(self, value) -> None:
        self.protocol_path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def assert_execute_rejected_before_provider(self) -> None:
        config_calls = 0

        def loader():
            nonlocal config_calls
            config_calls += 1
            return self.config()

        with patch(
            "tools.story_extraction.run_gemini_durable_confirmation_v1.official_client_factory"
        ) as client_factory:
            with self.assertRaises(ConfirmationProtocolError):
                execute(
                    protocol_path=self.protocol_path,
                    validation_result_path=self.validation_path,
                    expected_protocol_sha256=self.validated.protocol_sha256,
                    lock_commit="lock-commit",
                    checkpoint_directory=self.checkpoints,
                    result_path=self.result_path,
                    profile_path=self.profile_path,
                    config_loader=loader,
                )
        self.assertEqual(config_calls, 0)
        client_factory.assert_not_called()
        self.assertFalse(self.checkpoints.exists())


class TestProtocolFailClosed(ConfirmationProtocolTestCase):
    def test_invalid_json_means_zero_provider_calls(self):
        self.protocol_path.write_text('{"protocol_id":\n', encoding="utf-8")
        self.assert_execute_rejected_before_provider()

    def test_schema_invalid_protocol_means_zero_provider_calls(self):
        value = build_confirmation_protocol()
        del value["job_count"]
        self.write_protocol_value(value)
        self.assert_execute_rejected_before_provider()

    def test_runtime_protocol_mismatch_means_zero_provider_calls(self):
        value = build_confirmation_protocol()
        value["runtime_version"] = "UNACCEPTED_RUNTIME"
        self.write_protocol_value(value)
        self.assert_execute_rejected_before_provider()

    def test_fingerprint_mismatch_means_zero_provider_calls(self):
        value = build_confirmation_protocol()
        first = next(iter(value["request_fingerprints"]))
        value["request_fingerprints"][first] = "0" * 64
        self.write_protocol_value(value)
        self.assert_execute_rejected_before_provider()

    def test_wrong_attempt_limit_means_zero_provider_calls(self):
        value = build_confirmation_protocol()
        value["max_provider_attempts_per_job"] = 10
        self.write_protocol_value(value)
        self.assert_execute_rejected_before_provider()

    def test_output_aware_retry_means_zero_provider_calls(self):
        value = build_confirmation_protocol()
        value["output_aware_retry"] = "ENABLED"
        self.write_protocol_value(value)
        self.assert_execute_rejected_before_provider()

    def test_wrong_holdout_policy_means_zero_provider_calls(self):
        value = build_confirmation_protocol()
        value["holdout_access_policy"]["holdout_input"] = "ALLOWED"
        self.write_protocol_value(value)
        self.assert_execute_rejected_before_provider()

    def test_unknown_semantic_field_means_zero_provider_calls(self):
        value = build_confirmation_protocol()
        value["retry_on_bad_json"] = True
        self.write_protocol_value(value)
        self.assert_execute_rejected_before_provider()

    def test_old_malformed_protocol_regression_caught_pre_live(self):
        self.protocol_path.write_text(
            "protocol_id: M4_04B1D_DURABLE_EXECUTION_PROTOCOL_V1\n"
            "job_states:\n"
            "  PENDING: initial\n"
            "    IN_FLIGHT: running\n",
            encoding="utf-8",
        )
        self.assert_execute_rejected_before_provider()

    def test_protocol_mutation_after_lock_fails_closed(self):
        self.protocol_path.write_bytes(self.validated.locked_bytes + b" ")
        with self.assertRaises(ConfirmationProtocolError):
            self.validated.assert_byte_identical()
        self.assert_execute_rejected_before_provider()


class TestProtocolEligibility(ConfirmationProtocolTestCase):
    def test_canonical_protocol_is_live_runner_eligible(self):
        calls = 0

        def loader():
            nonlocal calls
            calls += 1
            return self.config()

        prepared = prepare_confirmation_run(
            protocol_path=self.protocol_path,
            validation_result_path=self.validation_path,
            expected_protocol_sha256=self.validated.protocol_sha256,
            config_loader=loader,
        )
        self.assertEqual(calls, 1)
        self.assertEqual(prepared.credential.slot_id, LOCKED_CREDENTIAL_SLOT)
        self.assertEqual(prepared.validated.protocol["model"], LOCKED_MODEL)
        self.assertEqual(
            prepared.validated.protocol["base_commit"], EXPECTED_BASE_COMMIT
        )

    def test_hash_is_calculated_after_all_validation_passes(self):
        checked = validate_confirmation_protocol_file(
            self.protocol_path,
            expected_sha256=self.validated.protocol_sha256,
        )
        self.assertEqual(checked.checks["parse"], "PASS")
        self.assertEqual(checked.checks["schema"], "PASS")
        self.assertEqual(checked.checks["semantic_consistency"], "PASS")
        self.assertEqual(checked.checks["fingerprints"], "PASS")


if __name__ == "__main__":
    unittest.main()
