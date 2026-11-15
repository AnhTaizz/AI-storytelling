"""Offline tests for the M4-04B3G FV1 blind-run runner (fake transports, synthetic cases)."""
import copy
import inspect
import json
from pathlib import Path
import tempfile
import unittest

from tests.story_extraction import fixture_builder as fx
from tools.story_extraction import m4_04b3f_fv1_protocol_v1 as lock
from tools.story_extraction import run_m4_04b3g_fv1_predictions_v1 as runner
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import (
    migrate_draft_v1_to_v1_1,
    prepare_story_extraction_draft_v1_1,
)
from tools.story_extraction.draft_coverage_v1 import canonical_gold_to_draft_v1
from tools.story_extraction.durable_research_executor_v1 import DurableResearchExecutor, DurableTransportFailure


def synthetic_case(case_id="FV1_01"):
    ingestion, base, gold = fx.build("c06_participant")
    scope = gold["scope"]
    context = DraftCompilerContext(base, scope["passage_inputs"], scope["as_of_position"], scope["profile_id"],
                                   "M4_04B3G_P3", "v1", f"P3_{case_id}", ingestion)
    draft_v1, _ = canonical_gold_to_draft_v1(gold, context)
    return runner.CaseInput(case_id, prepare_story_extraction_draft_v1_1(context), context), \
        migrate_draft_v1_to_v1_1(draft_v1)


class Clock:
    def __init__(self):
        self.now = 1_000.0

    def __call__(self):
        return self.now

    def wait(self, seconds):
        self.now += seconds


class FakeTransport:
    """Scripted raw responses per job id; `None` is a transport failure window."""

    def __init__(self, script):
        self.script = {key: list(value) for key, value in script.items()}
        self.calls = []

    def __call__(self, spec, window, request_id):
        self.calls.append((spec.job_id, spec.user_prompt))
        raw = self.script[spec.job_id].pop(0) if len(self.script[spec.job_id]) > 1 else self.script[spec.job_id][0]
        if raw is None:
            raise DurableTransportFailure("PROVIDER_UNAVAILABLE", provider_attempts=1)
        return {"raw_content": raw, "attempt_accounting": {"total_provider_attempts": 1},
                "transport_attempts": [{"model": spec.model, "slot_id": spec.credential_slot}],
                "usage_metadata": {"prompt_token_count": 10, "candidates_token_count": 5},
                "model_requested": spec.model, "slot_id": spec.credential_slot}


def executor(directory, clock):
    return DurableResearchExecutor(Path(directory) / "jobs", protocol_id="test", clock=clock)


class ValidationTests(unittest.TestCase):
    def test_structural_categories_carry_blockers_but_no_private_text(self):
        case, draft = synthetic_case()
        _, batch, ok = runner.validate_raw(json.dumps(draft, ensure_ascii=False), case.compiler_context)
        self.assertTrue(ok["pass"])
        self.assertIsNotNone(batch)
        schema = copy.deepcopy(draft)
        schema["unexpected"] = 1
        quote = copy.deepcopy(draft)
        quote["evidence"][0]["quote"] = "PRIVATE_TEST_QUOTE"
        cases = [("json", "{", "JSON_PARSE_FAILURE", "JSON"),
                 ("schema", json.dumps(schema), "DRAFT_SCHEMA_FAILURE", "SCHEMA"),
                 ("compiler", json.dumps(quote), "DRAFT_COMPILER_FAILURE", "QUOTE")]
        for label, raw, category, phase in cases:
            with self.subTest(label):
                _, batch, validation = runner.validate_raw(raw, case.compiler_context)
                self.assertIsNone(batch)
                self.assertEqual(validation["category"], category)
                self.assertEqual(validation["blockers"][0]["phase"], phase)
                self.assertNotIn("PRIVATE_TEST_QUOTE", json.dumps(validation))
                lock.sanitized_failure(validation["category"], validation["blockers"])  # repair-eligible

    def test_runner_cannot_reach_gold_or_an_evaluator(self):
        for function in (runner.verify_lock, runner.load_cases, runner.run_cases, runner.execute):
            names = set(inspect.signature(function).parameters)
            self.assertFalse(any("gold" in n.lower() or "evaluat" in n.lower() or "score" in n.lower()
                                 for n in names))
        self.assertEqual(runner.MAX_SEMANTIC_JOBS, 20)


class RunTests(unittest.TestCase):
    def test_primary_repair_and_terminal_outcomes(self):
        case, draft = synthetic_case()
        good = json.dumps(draft, ensure_ascii=False)
        scenarios = [
            ("valid primary", [good], None, "STRUCTURAL_VALID", 1),
            ("repaired", ["{"], [good], "STRUCTURAL_VALID", 2),
            ("repair also fails", ["{"], ["{"], "STRUCTURAL_FAILURE", 2),
            ("primary transport failure", [None], None, "TRANSPORT_FAILURE", 1),
        ]
        for label, primary, repair, status, jobs in scenarios:
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                clock = Clock()
                script = {"M4B3F_P3_FV1_01_PRIMARY": primary}
                if repair:
                    script["M4B3F_P3_FV1_01_REPAIR_1"] = repair
                transport = FakeTransport(script)
                results = runner.run_cases([case], executor(tmp, clock), transport, Path(tmp) / "art",
                                           wait=clock.wait)
                self.assertEqual(results[0]["terminal_status"], status)
                self.assertEqual(len(results[0]["attempts"]), jobs)
                if repair:  # the repair request names the blockers as phase/code/path only
                    repair_prompt = [u for j, u in transport.calls if j.endswith("REPAIR_1")][0]
                    self.assertIn('"code": "INVALID_JSON"', repair_prompt)
                stored = Path(tmp) / "art" / ("compiled" if status == "STRUCTURAL_VALID" else "failures")
                self.assertTrue((stored / "FV1_01.json").is_file())

    def test_smoke_qualification_and_summary(self):
        case, draft = synthetic_case()
        for raw, qualified in (('{"status":"ok"}', True), ('{"status":"no"}', False), ("no json", False)):
            with self.subTest(raw), tempfile.TemporaryDirectory() as tmp:
                smoke = runner.qualify_credential(executor(tmp, Clock()), FakeTransport({runner.SMOKE_JOB_ID: [raw]}))
                self.assertEqual(smoke["qualified"], qualified)
        with tempfile.TemporaryDirectory() as tmp:
            clock = Clock()
            transport = FakeTransport({runner.SMOKE_JOB_ID: ['{"status":"ok"}'],
                                       "M4B3F_P3_FV1_01_PRIMARY": [json.dumps(draft, ensure_ascii=False)]})
            ex = executor(tmp, clock)
            smoke = runner.qualify_credential(ex, transport, clock.wait)
            results = runner.run_cases([case], ex, transport, Path(tmp) / "art", wait=clock.wait)
            result, manifest = runner.summarize(results, smoke)
            again, _ = runner.summarize(results, smoke)
        self.assertEqual(result["prediction_set_sha256"], again["prediction_set_sha256"])
        self.assertEqual(manifest["terminal_counts"], {"STRUCTURAL_VALID": 1, "STRUCTURAL_FAILURE": 0,
                                                       "TRANSPORT_FAILURE": 0})
        self.assertEqual(manifest["usage_totals"], {"prompt_token_count": 20, "candidates_token_count": 10})
        self.assertEqual((manifest["semantic_jobs"], manifest["fv1_gold_opened"]), (1, False))
        self.assertNotIn(lock.DRAFT_VERSION, json.dumps(manifest))  # hashes only, no draft content

    def test_lock_mismatches_stop_before_any_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            protocol = Path(tmp) / "protocol.json"
            protocol.write_text("{}", encoding="utf-8")
            with self.assertRaises(lock.Fv1ProtocolError):
                runner.verify_lock(protocol, protocol, Path(tmp))
            code = runner.main(["--mode", "preflight", "--protocol", str(protocol),
                                "--protocol-validation", str(protocol), "--fv1-directory", tmp])
            self.assertEqual(code, 2)
            with self.assertRaises(FileNotFoundError):
                runner.load_cases(Path(tmp))


if __name__ == "__main__":
    unittest.main()
