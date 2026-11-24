from contextlib import closing
import sqlite3
from pathlib import Path
import tempfile
import unittest

from fixtures import CF_ACCOUNT, CF_TOKEN, GROQ_TEST_KEY, OPENROUTER_TEST_KEY
from tools.llm_infra.pipeline_clients import configured_secrets
from tools.llm_infra.telemetry import Telemetry, record_event


class TelemetryTests(unittest.TestCase):
    def test_schema_and_all_columns_exclude_injected_secrets(self):
        settings = {"GEMINI_API_KEY_1": "fake-google-key", "GROQ_API_KEY_1": GROQ_TEST_KEY,
                    "OPENROUTER_API_KEY_1": OPENROUTER_TEST_KEY, "CLOUDFLARE_ACCOUNT_ID_1": CF_ACCOUNT,
                    "CLOUDFLARE_API_TOKEN_1": CF_TOKEN}
        secrets = configured_secrets(settings)
        self.assertEqual(set(secrets), set(settings.values()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "telemetry.db"
            telemetry = Telemetry(path, secrets=secrets)
            for secret in secrets:
                telemetry.write(run_id=secret, stage=secret, request_id=secret, provider=secret,
                                model_requested=secret, model_reported=secret, error_code=secret,
                                outcome=secret, tokens_source=secret, quota_scope=secret, cost_source=secret,
                                routing_policy_sha256=secret, skip_reasons=[secret, "safe:SKIPPED"],
                                quota_remaining={"x-ratelimit-remaining-tokens": secret, secret: 42,
                                                 "x-ratelimit-remaining-requests": 7, "Authorization": secret},
                                raw_content="private-response", prompt="private-prompt")
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (1,))
                indexes = {r[1] for r in db.execute("PRAGMA index_list('llm_requests')")}
                self.assertEqual(indexes, {"llm_requests_timestamp", "llm_requests_model"})
                rows = db.execute("SELECT * FROM llm_requests").fetchall()
            self.assertEqual(len(rows), len(settings))
            for private in (*secrets, "Authorization", "private-prompt", "private-response"):
                self.assertNotIn(private, repr(rows))
            self.assertIn("safe:SKIPPED", repr(rows))
            self.assertIn("x-ratelimit-remaining-requests", repr(rows))

    def test_unsupported_schema_warns_without_overwriting_version(self):
        telemetry = Telemetry(":memory:")
        telemetry.write(provider="gemini")
        telemetry._memory.execute("PRAGMA user_version = 99")
        with self.assertLogs("tools.llm_infra.telemetry", "WARNING"):
            record_event(telemetry, provider="groq")
        self.assertEqual(telemetry._memory.execute("SELECT provider FROM llm_requests").fetchall(), [("gemini",)])
