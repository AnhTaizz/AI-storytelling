from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from tools.llm_infra.pipeline_clients import ProviderFailure
from tools.model_bench.dataset import load_dataset
from tools.model_bench.planning import make_plan
from tools.model_bench.registry import select_model
from tools.model_bench.run import FakeClient, _run_case, _validate_approval, execute, main


class RunnerTests(unittest.TestCase):
    CLI = ["--provider", "groq", "--model", "openai/gpt-oss-20b"]

    @classmethod
    def setUpClass(cls):
        cls.cases = load_dataset()[1]

    def test_default_dry_run_math_and_markdown(self):
        model = select_model("groq", "openai/gpt-oss-20b")
        plan = make_plan(model, self.cases[:2], 512)
        tokens = sum(item["input"] for item in plan)
        for args, expected in (
            ([], f"Estimated requests: 2. Tokens: {tokens} input + 1024 reserved output = {tokens + 1024}."),
            (["--plan-md"], "| event_extraction | 2 | 6 |"),
            (["--max-output-tokens", "8000"], "(tpm)"),
        ):
            with self.subTest(args=args), patch("tools.model_bench.run.build_adapter") as adapter:
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(self.CLI + ["--limit", "2"] + args), 0)
                self.assertIn(expected, output.getvalue())
                adapter.assert_not_called()

    def test_offline_end_to_end_and_completed_resume(self):
        with TemporaryDirectory() as temp:
            out = Path(temp) / "run"
            args = self.CLI + ["--offline-fake", "--output-dir", str(out)]
            with redirect_stdout(io.StringIO()), patch("tools.model_bench.run.build_adapter") as adapter:
                self.assertEqual(main(args), 0)
                with patch("tools.model_bench.run.FakeClient") as fake:
                    self.assertEqual(main(args + ["--resume"]), 0)
                fake.assert_not_called()
                adapter.assert_not_called()
            rows = [json.loads(line) for line in (out / "results.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), len(self.cases))
            self.assertEqual(sum(row["score"] == 1 for row in rows), 72)
            self.assertEqual(sum(row["review"] is not None for row in rows), 6)
            report = (out / "report.md").read_text(encoding="utf-8")
            self.assertIn("offline-fake", report)
            self.assertIn("unknown", report)
            self.assertIn("plan_sha256", report)
            self.assertEqual(len((out / "human_review.jsonl").read_bytes().splitlines()), 6)

    def test_resume_after_interruption_restores_checkpoint_order(self):
        cases = self.cases[:2]
        model = self.CLI[-1]
        metadata = {"mode": "offline-fake", "model": model, "max_output_tokens": 512}
        fake = FakeClient(model, cases)
        with TemporaryDirectory() as temp:
            out = Path(temp) / "run"
            client = Mock(models=(model,))
            client.complete.side_effect = [fake.complete(system="", user="", request_id=cases[0]["id"],
                                                         model=model, max_output_tokens=512), KeyboardInterrupt()]
            with self.assertRaises(KeyboardInterrupt):
                execute(out, metadata, cases, lambda: client)
            path = out / "results.jsonl"
            original = path.read_bytes()
            path.write_bytes(original + b'{"partial":')
            with self.assertRaisesRegex(ValueError, "Resume settings"):
                execute(out, metadata | {"max_output_tokens": 513}, cases, lambda: fake, resume=True)
            resumed = Mock(models=(model,), wraps=fake)
            rows = execute(out, metadata, cases, lambda: resumed, resume=True)
            self.assertTrue(path.read_bytes().startswith(original))
            self.assertEqual([row["case_id"] for row in rows], [case["id"] for case in cases])
            resumed.complete.assert_called_once()
            self.assertEqual(resumed.complete.call_args.kwargs["request_id"], cases[1]["id"])
            self.assertEqual(resumed.complete.call_args.kwargs["model"], model)

    def test_pinned_client_and_safe_errors(self):
        case = self.cases[0]
        model = self.CLI[-1]
        secret = "private-test-credential"
        with TemporaryDirectory() as temp:
            out = Path(temp) / "run"
            client = Mock(models=(model, "fallback"))
            with self.assertRaisesRegex(ValueError, "pin exactly"):
                execute(out, {"mode": "offline-fake", "model": model, "max_output_tokens": 512},
                        [case], lambda: client)
            client.complete.assert_not_called()
        for response, expected in (
            ({"model_reported": "fallback", "raw_content": "{}"}, "model_mismatch"),
            ({"raw_content": '{"answer": "' + secret + '"}'}, "invalid_response"),
            ({"raw_content": '{"answer": 1, "answer": 2}'}, "invalid_response"),
            ({"raw_content": '{"answer": NaN}'}, "invalid_response"),
        ):
            with self.subTest(expected=expected, response=response):
                client = Mock()
                client.complete.return_value = response
                row = _run_case(client, model, 512, case, secrets=(secret,))
                self.assertEqual(row["error"], expected)
                self.assertNotIn(secret, json.dumps(row))
                client.complete.assert_called_once()
                self.assertEqual(client.complete.call_args.kwargs["model"], model)
        client.complete.side_effect = ProviderFailure("private-test-credential")
        row = _run_case(client, model, 512, case, secrets=(secret,))
        self.assertEqual(row["error"], "provider_failure")
        self.assertIsNone(row["requests"])
        self.assertNotIn(secret, json.dumps(row))

    def test_live_refuses_before_any_dispatch_and_approval_is_bound(self):
        with patch("tools.model_bench.run.build_adapter") as adapter:
            with self.assertRaises(SystemExit) as error, redirect_stderr(io.StringIO()) as message:
                main(self.CLI + ["--live"])
            self.assertEqual(error.exception.code, 2)
            self.assertIn("--approved-plan", message.getvalue())
            adapter.assert_not_called()
        with TemporaryDirectory() as temp:
            path = Path(temp) / "approval.json"
            approval = {"plan_sha256": "fingerprint", "approved_by": "Owner", "m9_quota_clear": True}
            path.write_text(json.dumps(approval), encoding="utf-8")
            _validate_approval(path, "fingerprint")
            for data in (approval | {"m9_quota_clear": False}, approval | {"plan_sha256": "other"}):
                with self.subTest(data=data), self.assertRaises(ValueError):
                    path.write_text(json.dumps(data), encoding="utf-8")
                    _validate_approval(path, "fingerprint")
