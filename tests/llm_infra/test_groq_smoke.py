from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fixtures import Clock, FakeGroq, GROQ_TEST_KEY, groq_settings
from tools.llm_infra.groq_free_models_v1 import DEFAULT_MODEL_CHAIN
from tools.llm_infra.groq_smoke import main
from tools.llm_infra.groq_transport import GroqHTTPError, GroqResponse


class GroqSmokeTests(unittest.TestCase):
    def test_one_json_mode_request_and_small_secret_safe_output(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings"
            path.write_text(f"GROQ_API_KEY_1={GROQ_TEST_KEY}\nGROQ_ORG_LABEL_1=smoke-org\n", encoding="utf-8")
            for model in (None, "llama-3.1-8b-instant"):
                with self.subTest(model=model):
                    clock = Clock()
                    client = FakeGroq(GroqResponse(GROQ_TEST_KEY, {}, GROQ_TEST_KEY, {}))
                    capture = StringIO()
                    args = ["--env-file", str(path)] + (["--model", model] if model else [])
                    with redirect_stdout(capture):
                        result = main(args, environ={"LLM_QUOTA_STATE_PATH": ":memory:"}, client_factory=client.factory,
                                      clock=clock, sleep=clock.sleep)
                    self.assertEqual(result, 0)
                    self.assertNotIn(GROQ_TEST_KEY, capture.getvalue())
                    expected = model or DEFAULT_MODEL_CHAIN[0]
                    self.assertEqual(json.loads(capture.getvalue()), {
                        "slot_id": "groq_slot_1", "scope": "smoke-org", "model": expected,
                        "outcome": "SUCCESS", "latency_seconds": 0,
                    })
                    (key, request), = client.calls
                    self.assertEqual(key, GROQ_TEST_KEY)
                    self.assertEqual(request["model"], expected)
                    self.assertEqual(request["user_content"], 'Return {"status":"ok"}')
                    self.assertEqual(request["generation_config"]["response_mime_type"], "application/json")

    def test_failures_return_only_public_metadata(self):
        with TemporaryDirectory() as tmp:
            for model, outcome, calls in [(GROQ_TEST_KEY, "CONFIG_ERROR", 0), (None, "REQUEST_FAILURE", 1)]:
                with self.subTest(outcome=outcome):
                    clock = Clock()
                    client = FakeGroq(GroqHTTPError(kind="REQUEST_FAILURE",
                                                    body={"error": {"message": GROQ_TEST_KEY}}))
                    capture = StringIO()
                    args = ["--env-file", str(Path(tmp) / "absent")] + (["--model", model] if model else [])
                    with redirect_stdout(capture):
                        result = main(args, environ=groq_settings("") | {"LLM_QUOTA_STATE_PATH": ":memory:"},
                                      client_factory=client.factory, clock=clock, sleep=clock.sleep)
                    self.assertEqual(result, 1)
                    self.assertEqual(len(client.calls), calls)
                    self.assertNotIn(GROQ_TEST_KEY, capture.getvalue())
                    self.assertEqual(json.loads(capture.getvalue()), {
                        "slot_id": None, "scope": None, "model": DEFAULT_MODEL_CHAIN[0] if calls else None,
                        "outcome": outcome, "latency_seconds": 0,
                    })
