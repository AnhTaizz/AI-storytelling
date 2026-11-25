from contextlib import redirect_stderr, redirect_stdout
from datetime import date
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from tools.llm_infra.pipeline_clients import ProviderFailure
from tools.model_bench.approval import approval_budget, content_sha256
from tools.model_bench.dataset import DATA, case_sha256, load_dataset
from tools.model_bench.planning import MAX_TRANSPORT_CALLS, SCREENING_CASES, make_plan
from tools.model_bench.registry import select_model
from tools.model_bench.run import FakeClient, _run_case, execute, main


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
            (["--plan-md"], "| 2 × 1 | 2 | 48 |"),
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
        for metadata, requests in ((None, None), ({"attempt_count": 3}, 3),
                                   ({"failures": [{"code": "TIMEOUT"}, {"code": "TIMEOUT"}]}, 2)):
            with self.subTest(metadata=metadata):
                client.complete.side_effect = ProviderFailure(secret, metadata=metadata)
                row = _run_case(client, model, 512, case, secrets=(secret,))
                self.assertEqual(row["error"], "provider_failure")
                self.assertEqual(row["requests"], requests)
                self.assertNotIn(secret, json.dumps(row))

    def test_screening_plan_matches_individual_run_configuration(self):
        cases = {case["id"]: case for case in self.cases}
        self.assertEqual(len({cases[case_id]["group"] for case_id in SCREENING_CASES}), 10)
        self.assertEqual({cases[case_id]["difficulty"] for case_id in SCREENING_CASES}, {"easy", "medium", "hard"})
        self.assertEqual(sum(cases[case_id]["scoring_method"] == "rubric_human" for case_id in SCREENING_CASES), 2)
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--screening", "--dry-run", "--plan-md"]), 0)
        table = output.getvalue()
        self.assertEqual(table.count("| 10 × 1 | 10 | 40 |"), 6)
        self.assertIn("Pending on `main` after merge", table)
        self.assertEqual(table.count("Shared-quota check."), 2)
        self.assertIn("Wave 2 — after M9 finishes and the owner confirms Gemini quota", table)
        wave1, wave2 = table.split("## Wave 2")
        for wave, expected_total, candidates in (
            (wave1, "| **Wave total** |  | 40 | 40 | 160 | 6510 + 20480 | 34520 + 81920 |", (
                ("groq", "openai/gpt-oss-20b"), ("groq", "openai/gpt-oss-120b"),
                ("cloudflare", "@cf/zai-org/glm-4.7-flash"), ("openrouter", "google/gemma-4-31b-it:free"),
            )),
            (wave2, "| **Wave total** |  | 20 | 20 | 80 | 3200 + 10240 | 17040 + 40960 |", (
                ("gemini", "gemini-3.5-flash-lite"), ("gemini", "gemini-3.6-flash"),
            )),
        ):
            self.assertIn(expected_total, wave)
            self.assertEqual(wave.count("unverified fields:"), len(candidates))
            self.assertEqual([line.split(" | ")[0][2:] for line in wave.splitlines() if "| 10 × 1 |" in line],
                             [f"{provider} / {model}" for provider, model in candidates])
            for provider, model in candidates:
                with self.subTest(model=model), redirect_stdout(io.StringIO()) as output:
                    selection = [arg for case_id in SCREENING_CASES for arg in ("--case", case_id)]
                    main(["--provider", provider, "--model", model, "--plan-md", *selection])
                    fingerprint = output.getvalue().split("plan SHA-256 ")[1].splitlines()[0]
                    self.assertIn(f"{provider} / {model} plan SHA-256 {fingerprint}", wave)

    def test_refuses_unpinned_openrouter_plan(self):
        with self.assertRaises(SystemExit) as error, redirect_stderr(io.StringIO()) as message:
            main(["--provider", "openrouter", "--model", "openrouter/free", "--dry-run", "--plan-md"])
        self.assertEqual(error.exception.code, 2)
        self.assertIn("named OpenRouter :free variant", message.getvalue())

    def test_live_refuses_before_any_dispatch_without_approval(self):
        with patch("tools.model_bench.run.build_adapter") as adapter:
            with self.assertRaises(SystemExit) as error, redirect_stderr(io.StringIO()) as message:
                main(self.CLI + ["--live"])
            self.assertEqual(error.exception.code, 2)
            self.assertIn("--approved-plan", message.getvalue())
            adapter.assert_not_called()

    def test_live_refuses_proposed_gold_before_dispatch(self):
        with patch("tools.model_bench.run.build_adapter") as adapter:
            with self.assertRaises(SystemExit) as error, redirect_stderr(io.StringIO()) as message:
                main(self.CLI + ["--case", SCREENING_CASES[0], "--live", "--approved-plan", "unused.json",
                                 "--gold-review", str(DATA / "GOLD_REVIEW.proposed.json")])
            self.assertEqual(error.exception.code, 2)
            self.assertIn("Không có ca nào đủ điều kiện", message.getvalue())
            adapter.assert_not_called()

    def test_live_budget_counts_retries_and_refuses_reuse_or_resume(self):
        model = self.CLI[-1]
        cases = self.cases[:3]
        meta = {"provider": "groq", "model": model, "mode": "live", "max_output_tokens": 512}
        for cap, counts, charged in ((MAX_TRANSPORT_CALLS + 1, [2], 2),
                                     (MAX_TRANSPORT_CALLS + 2, [2, MAX_TRANSPORT_CALLS], MAX_TRANSPORT_CALLS + 2),
                                     (MAX_TRANSPORT_CALLS, [None], MAX_TRANSPORT_CALLS)):
            with self.subTest(cap=cap, counts=counts), TemporaryDirectory() as temp:
                root = Path(temp)
                doc = {"plan_id": "screening", "content_sha256": "fixture",
                       "models": [{"provider": "groq", "model": model, "request_cap": cap}]}
                approval = doc, date.max, cap
                client = Mock(models=(model,))
                client.complete.side_effect = [
                    {"raw_content": json.dumps({"answer": case["gold"]}),
                     "transport_attempts": [{"outcome": "TIMEOUT"}] * (n - 1) + [{"outcome": "SUCCESS"}],
                     "usage": {"input_tokens": 8, "output_tokens": 4}}
                    if n is not None else ProviderFailure("QUOTA_EXHAUSTED")
                    for case, n in zip(cases, counts)
                ]
                with approval_budget(root, approval, meta, resume=False) as budget:
                    rows = execute(root / "run", meta, cases, lambda: client, budget=budget)
                self.assertEqual([row["requests"] for row in rows], counts)
                self.assertEqual(client.complete.call_count, len(counts))
                self.assertEqual(json.loads((root / "run" / "budget.json").read_text(encoding="utf-8")),
                                 {"budget_used": charged, "budget_cap": cap, "run_status": "BUDGET_EXHAUSTED"})
                if counts[0] is not None:
                    self.assertEqual((rows[0]["tokens_source"], rows[0]["requests_per_success"],
                                      rows[0]["tokens_per_success"], rows[0]["error_codes"]),
                                     ("reported", 2, 12, ["TIMEOUT"]))
                excluded = Mock()
                for resume, directory in ((False, "new-run"), (True, "run")):
                    with approval_budget(root, approval, meta, resume=resume) as budget:
                        execute(root / directory, meta, cases, excluded, budget=budget, resume=resume)
                excluded.assert_not_called()

    def test_live_gold_selection_and_draft_labels(self):
        dataset_hash, cases = load_dataset()
        case_ids = [case["id"] for case in cases[:2]]
        with TemporaryDirectory() as temp:
            root = Path(temp)
            plan = root / "approval.json"
            gold = root / "GOLD_REVIEW.json"
            for include_drafts in (False, True):
                with self.subTest(include_drafts=include_drafts):
                    provider, model = ("gemini", "gemini-3.5-flash-lite") if include_drafts else ("groq", self.CLI[-1])
                    cli = ["--provider", provider, "--model", model]
                    decisions = {case["id"]: {"status": status, "reviewer": "Owner", "date": "2026-11-24",
                                               "case_sha256": case_sha256(case)}
                                 for case, status in ((cases[0], "approved"), (cases[2], "rejected"),
                                                      (cases[3], "needs_change"))}
                    gold.write_text(json.dumps({"dataset_sha256": dataset_hash, "cases": decisions}),
                                    encoding="utf-8")
                    select = cli + ["--limit", "2" if include_drafts else "1"]
                    if include_drafts:
                        select += ["--include-drafts"]
                    with redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(main(select + ["--plan-md"]), 0)
                    fingerprint = output.getvalue().split("plan SHA-256 `")[1].split("`")[0]
                    doc = {"plan_id": f"gold-{int(include_drafts)}", "approved_by": "Owner",
                           "dataset_sha256": dataset_hash, "expires_on": date.max.isoformat(),
                           "case_ids": case_ids if include_drafts else case_ids[:1],
                           "models": [{"provider": provider, "model": model, "plan_sha256": fingerprint,
                                       "request_cap": MAX_TRANSPORT_CALLS * 2}]}
                    plan.write_text(json.dumps(doc | {"content_sha256": content_sha256(doc)}), encoding="utf-8")
                    directory = root / doc["plan_id"]
                    live = [*cli, "--limit", "4", "--live", "--approved-plan", str(plan),
                            "--output-dir", str(directory), "--gold-review", str(gold)]
                    if include_drafts:
                        (root / "gate_lock.json").touch()
                        live.extend(["--include-drafts", "--seasons-dir", str(root)])
                    with patch("tools.model_bench.run.RUNS", root), patch(
                            "tools.model_bench.run.build_adapter", return_value=FakeClient(model, cases)) as adapter, (
                            redirect_stdout(io.StringIO())):
                        if include_drafts:
                            with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()) as error:
                                main(live)
                            self.assertIn("M9 có thể đang chạy", error.getvalue())
                            adapter.assert_not_called()
                            live.append("--m9-clear-attested-by-owner")
                        self.assertEqual(main(live), 0)
                    manifest = json.loads((directory / "run.json").read_bytes())
                    self.assertEqual(manifest["m9_clear_attested_by_owner"], include_drafts)
                    rows = [json.loads(line) for line in (directory / "results.jsonl").read_bytes().splitlines()]
                    self.assertEqual([row["gold_tier"] for row in rows],
                                     ["approved", "draft"] if include_drafts else ["approved"])
