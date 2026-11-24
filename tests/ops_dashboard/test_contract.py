import unittest

from tools.ops_dashboard import contract


class ContractTests(unittest.TestCase):
    def test_phase_five_columns_and_vocabulary(self):
        self.assertCountEqual(contract.TELEMETRY_COLUMNS, (
            "id", "timestamp_utc", "run_id", "stage", "request_id", "provider", "model_requested",
            "model_reported", "outcome", "error_code", "input_tokens", "output_tokens",
            "reasoning_tokens", "tokens_source", "latency_ms", "quota_scope", "quota_remaining",
            "cost_reported", "cost_estimated", "cost_source", "routing_policy_sha256", "skip_reasons",
        ))
        self.assertEqual(contract.VALUE_SOURCES, ("reported", "estimated", "unknown"))
        self.assertEqual(contract.OUTCOMES, ("SUCCESS", "FAILED", "SKIPPED"))
