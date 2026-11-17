"""Synthetic, offline behaviour tests for the DEV2 prompt development runner."""
from contextlib import contextmanager, ExitStack, redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from tests.story_extraction import fixture_builder as fx
from tests.story_extraction.test_run_m4_04b3g_fv1_predictions_v1 import Clock, FakeTransport
from tools.story_extraction import run_m4_p4_dev_v1 as runner
from tools.story_extraction import m4_04b3f_fv1_protocol_v1 as protocol
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import migrate_draft_v1_to_v1_1
from tools.story_extraction.draft_coverage_v1 import canonical_gold_to_draft_v1


class DevelopmentRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ingestion, base, cls.gold = fx.build("c06_participant")
        scope = cls.gold["scope"]
        cls.context = DraftCompilerContext(base, scope["passage_inputs"], scope["as_of_position"],
                                           scope["profile_id"], "DEV_V1", "v1", "DEV_V1", ingestion)
        draft, _ = canonical_gold_to_draft_v1(cls.gold, cls.context)
        cls.draft = migrate_draft_v1_to_v1_1(draft)
        cls.good = json.dumps(cls.draft)

    @contextmanager
    def fixture(self, ids=("DEV2_01",), optional=(), members=()):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            input_zip, gold_zip = root / "input.zip", root / "gold.zip"
            with ZipFile(input_zip, "w") as bundle:
                bundle.writestr("cases/", "")
                for cid in ids:
                    bundle.writestr(f"m3_sources/{cid}/unit.txt",
                                    self.context.ingestion.documents[0].source_bytes)
                for member in members:
                    bundle.writestr(member, "untrusted")
            manifest = {"cases": [{"case_id": cid,
                "canonical_annotation_member": f"cases/{cid}/canonical_annotation_batch.json",
                "gold_completeness": "COMPLETE_FOR_PROFILE",
                "required_assertion_ids": [a["id"] for a in self.gold["candidate_records"]["assertions"]
                                           if a["id"] not in optional],
                "acceptable_optional_assertion_ids": list(optional)} for cid in ids]}
            with ZipFile(gold_zip, "w") as bundle:
                bundle.writestr(runner.GOLD_MANIFEST, json.dumps(manifest))
                for row in manifest["cases"]:
                    bundle.writestr(row["canonical_annotation_member"], json.dumps(self.gold))
            for key, path in (("INPUT_SHA256", input_zip), ("GOLD_SHA256", gold_zip)):
                stack.enter_context(patch.object(runner, key, protocol.file_sha256(path)))
            # Deliberately obsolete V1 preparation: the runner must regenerate V1.1.
            loaded = [runner.CaseInput(cid, {"draft_version": "STORY_EXTRACTION_DRAFT_V1"},
                                       self.context, ()) for cid in ids]
            loader = Mock(return_value=loaded)
            clock = Clock()
            options = dict(variant="P3", dev2_input=input_zip, dev2_gold=gold_zip,
                           output_root=root / "output", cases=ids, case_loader=loader,
                           clock=clock, wait=clock.wait)
            yield options, loaded, manifest

    def transport(self, variant="P3", script=None, smoke='{"status":"ok"}', slot=protocol.CREDENTIAL_SLOT):
        values = {f"{runner.TASK_ID}_{variant}_SMOKE_{slot.upper()}": [smoke]}
        for (cid, phase), raw in (script or {("DEV2_01", "PRIMARY"): self.good}).items():
            values[f"{runner.TASK_ID}_{variant}_{cid}_{phase}"] = [raw]
        return FakeTransport(values)

    def test_prompt_composition_sources_and_request_identity(self):
        locked = protocol.prompt_material()
        self.assertEqual(runner.prompt_material("P3"), locked)
        p4 = runner.prompt_material("P4")
        old = protocol._normalized_text(protocol.SYSTEM_PREAMBLE_PATH)
        new = protocol._normalized_text(protocol.PROMPT_ROOT / "story_extraction_draft_p4_system_v1_1.txt")
        self.assertNotEqual(old, new)
        self.assertEqual(p4["primary_system"], new + locked["primary_system"][len(old):])
        self.assertEqual(p4["repair_system"], p4["primary_system"] + "\n\n" + protocol.REPAIR_SYSTEM_SUFFIX)
        for key in ("primary_user_template", "repair_user_template"):
            self.assertEqual(p4[key], locked[key])
        with self.fixture() as (opts, _, _), tempfile.TemporaryDirectory() as tmp:
            case = runner.load_cases(opts["dev2_input"], Path(tmp), opts["cases"], opts["case_loader"])[0]
            specs = []
            for variant in ("P3", "P4"):
                with self.subTest(variant=variant):
                    spec = runner.build_primary_spec(variant, case, "custom-model", "custom_slot")
                    specs.append(spec)
                    self.assertEqual((spec.model, spec.credential_slot), ("custom-model", "custom_slot"))
                    self.assertEqual(spec.generation_config, {"temperature": 0, "max_output_tokens": 16384})
                    self.assertEqual(spec.schema_response_mode, protocol.SCHEMA_RESPONSE_MODE)
                    self.assertIn('"draft_version": "STORY_EXTRACTION_DRAFT_V1_1"', spec.user_prompt)
                    self.assertEqual(case.compiler_context.process_version, "v1.1")
                    self.assertNotIn("evidence_handle", spec.user_prompt)
                    hashes = runner.prompt_hashes(variant)
                    self.assertEqual(len(hashes["source_sha256"]), 6)
                    self.assertEqual(hashes["composed_sha256"]["primary_system"],
                                     protocol.sha256_text(spec.system_prompt))
            self.assertNotEqual(specs[0].job_id, specs[1].job_id)
            self.assertNotEqual(specs[0].request_fingerprint, specs[1].request_fingerprint)
        with self.assertRaises(runner.DevelopmentError):
            runner.prompt_material("P5")

    def test_hash_refusal_and_selection_validation(self):
        with self.fixture() as (opts, _, _):
            for name in ("dev2_input", "dev2_gold"):
                with self.subTest(archive=name), patch.object(runner, "INPUT_SHA256" if name == "dev2_input"
                                                             else "GOLD_SHA256", "0" * 64):
                    fake = Mock(side_effect=AssertionError("provider called"))
                    with self.assertRaisesRegex(runner.DevelopmentError, "hash mismatch"):
                        runner.execute(**opts, mode="run", transport=fake)
                    fake.assert_not_called()
                    opts["case_loader"].assert_not_called()
            for cases in ([], ["DEV2_00"], ["DEV2_01", "DEV2_01"]):
                with self.subTest(cases=cases), self.assertRaises(runner.DevelopmentError):
                    runner.selected_cases(cases)
            self.assertEqual(runner.selected_cases(None), runner.CASE_IDS)
            with self.assertRaises(runner.DevelopmentError):
                runner.execute(**opts, mode="invalid")

    def test_preflight_selects_and_builds_one_spec_without_provider_work(self):
        with self.fixture(("DEV2_01", "DEV2_03")) as (opts, _, _):
            fake = Mock(side_effect=AssertionError("provider called"))
            for ids in (("DEV2_03",), ("DEV2_03", "DEV2_01")):
                with self.subTest(ids=ids), patch.object(runner, "build_primary_spec",
                                                       wraps=runner.build_primary_spec) as build:
                    result = runner.execute(**{**opts, "cases": ids}, transport=fake)
                    self.assertEqual((result["case_count"], result["primary_specs"]), (len(ids), len(ids)))
                    self.assertEqual([call.args[1].case_id for call in build.call_args_list], list(ids))
                    self.assertEqual(result["prompt_hashes"], runner.prompt_hashes("P3"))
                    self.assertEqual(result["status"], "PREFLIGHT_PASS")
            fake.assert_not_called()
            self.assertFalse(opts["output_root"].exists())

    def test_run_outcomes_artifacts_and_locked_resume(self):
        schema = {**self.draft, "unexpected": True}
        compiler = deepcopy(self.draft)
        compiler["evidence"][0]["quote"] = "SYNTHETIC_MISMATCH"
        scenarios = [("success", self.good, None, True), ("json repair", "{", self.good, True),
                     ("schema repair", json.dumps(schema), self.good, True),
                     ("compiler repair", json.dumps(compiler), self.good, True),
                     ("double failure", "{", "{", False), ("empty primary", "", self.good, True),
                     ("transport", None, None, False), ("repair transport", "{", None, False)]
        for variant in ("P3", "P4"):
            for label, primary, repair, valid in scenarios:
                with self.subTest(variant=variant, scenario=label), self.fixture() as (opts, _, _):
                    opts["variant"] = variant
                    script = {("DEV2_01", "PRIMARY"): primary}
                    if primary is not None and primary != self.good:
                        script["DEV2_01", "REPAIR_1"] = repair
                    fake = self.transport(variant, script)
                    score = runner.execute(**opts, mode="run", transport=fake)
                    before = list(fake.calls)
                    again = runner.execute(**opts, mode="run", transport=fake)
                    self.assertEqual(fake.calls, before)
                    self.assertEqual(again["summary"], score["summary"])
                    self.assertEqual(score["summary"]["layers"]["L0_structural_valid"], int(valid))
                    directory = opts["output_root"] / variant / "artifacts" / "DEV2_01"
                    saved = json.loads((directory / "validation.json").read_text())
                    self.assertEqual(saved["repair_used"], primary is not None and primary != self.good)
                    if primary is not None:
                        self.assertEqual((directory / "primary_raw.txt").read_text(), primary)
                    if valid:
                        self.assertTrue((directory / "compiled_batch.json").is_file())
                        batch = json.loads((directory / "compiled_batch.json").read_text())
                        self.assertEqual(batch["candidate_records"]["extraction_provenance"][0]["process_id"],
                                         f"{runner.TASK_ID}_{variant}")
                        phase = "primary" if primary == self.good else "repair_1"
                        self.assertEqual(json.loads((directory / f"{phase}_draft.json").read_text()), self.draft)
                    else:
                        self.assertEqual(score["rows"][0]["evaluation"]["case_outcome"], "FAIL")
                        self.assertFalse((directory / "compiled_batch.json").exists())
                    self.assertTrue((opts["output_root"] / variant / "score.json").is_file())

    def test_interrupted_artifact_write_resumes_locked_response_and_variants_are_isolated(self):
        with self.fixture() as (opts, _, _):
            fake = self.transport()
            with patch.object(runner, "validate_raw", side_effect=RuntimeError("interrupted")):
                with self.assertRaises(RuntimeError):
                    runner.execute(**opts, mode="run", transport=fake)
            before = list(fake.calls)
            runner.execute(**opts, mode="run", transport=fake)
            self.assertEqual(fake.calls, before)
            other = self.transport("P4")
            runner.execute(**{**opts, "variant": "P4"}, mode="run", transport=other)
            self.assertTrue(set(j for j, _ in before).isdisjoint(j for j, _ in other.calls))
            for variant in ("P3", "P4"):
                self.assertEqual(len(list((opts["output_root"] / variant / "checkpoints" / "jobs").glob("*.json"))), 2)

    def test_smoke_refusal_overrides_and_prompt_change_guard(self):
        for raw in ('{"status":"no"}', "invalid json", None):
            with self.subTest(raw=raw), self.fixture() as (opts, _, _):
                fake = self.transport(smoke=raw)
                with self.assertRaisesRegex(runner.DevelopmentError, "smoke"):
                    runner.execute(**opts, mode="run", transport=fake)
                self.assertTrue(all("SMOKE" in job for job, _ in fake.calls))
        with self.fixture() as (opts, _, _):
            fake = self.transport(slot="custom_slot")
            runner.execute(**opts, mode="run", transport=fake, model="custom-model", credential_slot="custom_slot")
            self.assertIn("CUSTOM_SLOT", fake.calls[0][0])
            with self.assertRaises(runner.CheckpointIntegrityError):
                runner.execute(**opts, mode="run", transport=fake, model="changed-model", credential_slot="custom_slot")
        with self.fixture() as (opts, _, _):
            fake = Mock()
            hashes = runner.prompt_hashes("P3")
            with patch.object(runner, "prompt_hashes", side_effect=[hashes, {}]):
                with self.assertRaisesRegex(runner.CheckpointIntegrityError, "sources changed"):
                    runner.execute(**opts, mode="run", transport=fake)
            fake.assert_not_called()

    def test_real_scoring_optional_ids_aggregation_conventions_and_public_summary(self):
        optional = self.gold["candidate_records"]["assertions"][-1]["id"]
        draft = deepcopy(self.draft)
        draft["assertions"].pop()
        ids = ("DEV2_01", "DEV2_02", "DEV2_03")
        with self.fixture(ids, (optional,)) as (opts, _, _):
            fake = self.transport(script={(ids[0], "PRIMARY"): json.dumps(draft),
                                          (ids[1], "PRIMARY"): self.good,
                                          (ids[2], "PRIMARY"): "{", (ids[2], "REPAIR_1"): "{"})
            with patch.object(runner.scoring.evaluator, "evaluate_case",
                              wraps=runner.scoring.evaluator.evaluate_case) as evaluate:
                result = runner.execute(**opts, mode="run", transport=fake)
            for call in evaluate.call_args_list:
                self.assertEqual(call.kwargs["case_spec"], {
                    "mode": "REAL_SOURCE", "gold_completeness": "COMPLETE_FOR_PROFILE",
                    "acceptable_assertion_ids": [optional], "adjudications": []})
            metrics = result["summary"]
            self.assertEqual(metrics["cases"], 3)
            self.assertEqual(metrics["cases_structurally_invalid"], 1)
            self.assertEqual(metrics["full_canonical_case_success_count"], 2)
            self.assertEqual(metrics["assertion_recall"], 1.0)
            self.assertEqual(metrics["assertion_precision"], 1.0)
            self.assertEqual(metrics["failure_code_counts"], {"CANONICAL_CONFORMANCE_FAILURE": 1})
            self.assertEqual(result["conventions_cases_checked"], 2)
            for rule in runner.RULE_IDS:
                self.assertEqual(result["conventions_counts"][rule], sum(
                    r["conventions"]["counts"][rule] for r in result["rows"] if r["conventions"]))
            no_provider = Mock(side_effect=AssertionError("score contacted provider"))
            again = runner.execute(**opts, mode="score", transport=no_provider)
            no_provider.assert_not_called()
            self.assertEqual(again["summary"], metrics)
            result["summary"]["gold_ids"] = [optional]
            result["summary"]["assertion_precision"] = "PRIVATE_TEXT"
            public = json.dumps(runner.public_summary(result))
            for secret in (optional, "DEV2_01", "PRIVATE_TEXT", "gold_ids", "candidate_records"):
                self.assertNotIn(secret, public)
            self.assertIn("CANONICAL_CONFORMANCE_FAILURE", public)
            directory = opts["output_root"] / "P3" / "artifacts" / ids[0]
            (directory / "compiled_batch.json").write_text("{}")
            with self.assertRaisesRegex(runner.CheckpointIntegrityError, "hash mismatch"):
                runner.execute(**opts, mode="score", transport=no_provider)
            with self.assertRaisesRegex(runner.CheckpointIntegrityError, "request differs"):
                runner.execute(**opts, mode="score", model="different-model", transport=no_provider)

    def test_input_loader_and_gold_refusals(self):
        for member in ("../escape.txt", "gold/leak.txt"):
            with self.subTest(member=member), self.fixture(members=(member,)) as (opts, _, _):
                with self.assertRaises(runner.Dev2PredictionError):
                    runner.execute(**opts)
                opts["case_loader"].assert_not_called()
        with self.fixture() as (opts, loaded, manifest):
            for bad in ([], loaded + loaded):
                with self.subTest(loaded=len(bad)):
                    opts["case_loader"].return_value = bad
                    with self.assertRaisesRegex(runner.DevelopmentError, "loader case identity"):
                        runner.execute(**opts)
            for problem in ("duplicate case", "missing case", "partition", "completeness"):
                bad = deepcopy(manifest)
                if problem == "duplicate case":
                    bad["cases"] *= 2
                elif problem == "missing case":
                    bad["cases"] = []
                elif problem == "partition":
                    bad["cases"][0]["required_assertion_ids"] = []
                else:
                    bad["cases"][0]["gold_completeness"] = "INVALID"
                with self.subTest(problem=problem), ZipFile(opts["dev2_gold"], "w") as bundle:
                    bundle.writestr(runner.GOLD_MANIFEST, json.dumps(bad))
                    bundle.writestr(manifest["cases"][0]["canonical_annotation_member"], json.dumps(self.gold))
                with self.assertRaises(runner.DevelopmentError):
                    runner.read_gold(opts["dev2_gold"], opts["cases"])

    def test_cli_modes_refusal_and_module_entrypoint(self):
        original = runner.execute
        for mode in ("preflight", "run", "score"):
            with self.subTest(mode=mode), self.fixture() as (opts, _, _):
                fake = self.transport()
                if mode == "score":
                    original(**opts, mode="run", transport=fake)
                argv = ["--variant", "P3", "--dev2-input", str(opts["dev2_input"]),
                        "--dev2-gold", str(opts["dev2_gold"]), "--output-root", str(opts["output_root"]),
                        "--cases", "DEV2_01", "--mode", mode]
                def execute_cli(**kwargs):
                    return original(**{**opts, **kwargs}, transport=fake)
                output = io.StringIO()
                with patch.object(runner, "execute", side_effect=execute_cli), redirect_stdout(output):
                    self.assertEqual(runner.main(argv), 0)
                self.assertIsInstance(json.loads(output.getvalue()), dict)
                with patch.object(runner, "execute", side_effect=runner.DevelopmentError("private")), redirect_stdout(output):
                    self.assertEqual(runner.main(argv), 2)
                self.assertIn("M4_P4_DEV_STOPPED: DevelopmentError", output.getvalue())
        with patch("sys.argv", [runner.__name__]), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as stopped:
                runpy.run_module(runner.__name__, run_name="__main__")
            self.assertEqual(stopped.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
