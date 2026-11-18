"""Synthetic saved-run tests for the counts-only M4 development diagnosis."""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests.story_extraction import fixture_builder as fx
from tests.story_extraction.test_diagnose_m4_04b3i_fv1_v1 import build
from tools.story_extraction import diagnose_m4_p4_dev_v1 as diag
from tools.story_extraction.draft_coverage_v1 import canonical_gold_to_draft_v1


class DevelopmentDiagnosisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ingestion, cls.base, cls.gold = build("g")
        _, _, cls.pred = build("p")
        scope = cls.gold["scope"]
        cls.context = diag.compiler.DraftCompilerContext(cls.base, scope["passage_inputs"],
            scope["as_of_position"], scope["profile_id"], "SYNTHETIC", "v1.1", "SYNTHETIC", cls.ingestion)
        v1, _ = canonical_gold_to_draft_v1(cls.gold, cls.context)
        cls.draft = diag.compiler11.migrate_draft_v1_to_v1_1(v1)

    @staticmethod
    def write(path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj), encoding="utf-8")

    def evaluation(self, predicted, item):
        return diag.runner.scoring.evaluator.evaluate_case(self.base, item["gold_batch"], predicted,
            ingestion=self.ingestion, case_spec={"mode": "REAL_SOURCE",
            "gold_completeness": item["gold_completeness"],
            "acceptable_assertion_ids": item.get("acceptable_optional_assertion_ids", []),
            "literal_variants": item.get("literal_variants", [])})

    @contextmanager
    def fixture(self, dataset="DEV2", optional=False, predictions=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = (diag.runner.dev1_protocol.CASE_IDS if dataset == "DEV1" else diag.runner.CASE_IDS)[:3]
            gold = {cid: {"gold_batch": self.gold, "gold_completeness": label,
                "acceptable_optional_assertion_ids": [self.gold["candidate_records"]["assertions"][-1]["id"]]
                if optional else []} for cid, label in zip(ids,
                ("COMPLETE_FOR_PROFILE", "UNCERTAIN", "UNCERTAIN"))}
            loaded = [diag.runner.CaseInput(cid, {}, self.context, (), dataset) for cid in ids]
            for variant in ("P3", "P4R3"):
                run = (root / "runs" / "DEV1" if dataset == "DEV1" else root / "runs") / variant
                rows = []
                for i, cid in enumerate(ids):
                    directory = run / "artifacts" / cid
                    if i == 2:
                        self.write(directory / "primary_draft.json", {})
                        self.write(directory / "repair_1_draft.json", {"draft_version": "WRONG"})
                        evaluation, status = {}, "DRAFT_SCHEMA_FAILURE"
                    else:
                        pred = deepcopy((predictions or {}).get(variant, self.pred))
                        for ref in pred["candidate_records"]["evidence_refs"]:
                            ref["role"] = "NARRATION_SUMMARY"
                        self.write(directory / "compiled_batch.json", pred)
                        evaluation, status = self.evaluation(pred, gold[cid]), "STRUCTURAL_VALID"
                    rows.append({"case_id": cid, "evaluation": evaluation,
                                 "terminal_status": status, "repair_used": i == 2})
                self.write(run / "score.json", {"rows": rows})
            loader = Mock(return_value=(loaded, gold))
            options = dict(dataset=dataset, variants=["P3", "P4R3"], output_root=root / "runs",
                           output_directory=root / "out", cases=ids, input_loader=loader)
            yield options, gold, loader

    def test_structural_issue_templates_remove_variable_values(self):
        examples = [
            ("canonical", "reference_integrity: event draftv1-P3-evt-1 anchor d2-time-8 is not an EVENT_TIME anchor of that event",
             "reference_integrity:EVENT_ANCHOR_NOT_OWN_EVENT_TIME"),
            ("reference_integrity", "event EVT12 references unknown anchor T9", "reference_integrity:EVENT_UNKNOWN_ANCHOR"),
            ("reference_integrity", "anchor T12 references unknown event EVT4", "reference_integrity:ANCHOR_UNKNOWN_EVENT"),
            ("reference_integrity", "assertion A12 references unknown proposition PROP12",
             "reference_integrity:ASSERTION_UNKNOWN_PROPOSITION"),
            ("predicate_integrity", "proposition embedding cycle through PROP12",
             "predicate_integrity:PROPOSITION_EMBEDDING_CYCLE"),
            ("temporal_bound_integrity", "assertion A12 validity starts and ends at the same anchor",
             "temporal_bound_integrity:VALIDITY_SAME_ANCHOR"),
            ("support_path_integrity", "assertion A12 has no complete support path (availability undefined)",
             "support_path_integrity:NO_COMPLETE_SUPPORT_PATH"),
            ("custom", "new issue draftv1-abc and d2-foo PROP12 g-a12 has 42 values 'Mara' and \"private text\"",
             "custom:new issue <id> and <id> <id> <id> has <n> values <text> and <text>"),
            ("SCHEMA", "DRAFT_SCHEMA_FAILURE", "SCHEMA:DRAFT_SCHEMA_FAILURE"),
            ("custom", "new issue PROP12 has 'O\\'Brien' and 2.5 values", "custom:new issue <id> has <text> and <n> values"),
        ]
        examples += [("predicate_integrity", message, "predicate_integrity:" + code) for message, code in (
            ("event EVT12 has unregistered event_kind PrivateWord", "EVENT_KIND_UNREGISTERED"),
            ("proposition PROP12 uses unregistered predicate PrivateWord", "PREDICATE_UNREGISTERED"),
            ("proposition PROP12 uses forbidden stored verdict predicate PrivateWord", "FORBIDDEN_VERDICT_PREDICATE"),
            ("proposition PROP12 arity mismatch for PrivateWord: got ['x'], expected ['y']", "PREDICATE_ARITY_MISMATCH"),
            ("proposition PROP12 Participates.role vocabulary PrivateWord != participant_role", "ARGUMENT_VOCABULARY_MISMATCH"),
            ("proposition PROP12 Participates.role stores forbidden verdict PrivateWord", "FORBIDDEN_VERDICT_VALUE"),
            ("proposition PROP12 Participates.role value PrivateWord not in participant_role", "ARGUMENT_TOKEN_NOT_IN_VOCABULARY"),
            ("proposition PROP12 argument PrivateWord references unknown ENTITY ENT12", "ARGUMENT_UNKNOWN_REFERENCE"),
        )]
        for section, message, expected in examples:
            with self.subTest(message=message):
                self.assertEqual(diag.issue_code(section, message), expected)

    def test_structural_capture_and_wrapper_restoration(self):
        for scenario in ("valid", "canonical", "schema", "validator exception", "unexpected exception", "missing"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                draft = deepcopy(self.draft)
                if scenario == "canonical":
                    draft["anchors"][0]["event_handle"] = draft["events"][1]["handle"]
                if scenario == "schema":
                    draft = {}
                if scenario != "missing":
                    self.write(directory / "primary_draft.json", draft)
                original = diag.compiler.validate_batch_guarded
                if scenario in ("validator exception", "unexpected exception"):
                    target = diag.compiler if scenario == "validator exception" else diag.compiler11
                    name = "validate_batch_guarded" if scenario == "validator exception" else "compile_story_extraction_draft_v1_1"
                    with patch.object(target, name, side_effect=RuntimeError("secret source")) as fail:
                        if scenario == "unexpected exception":
                            with self.assertRaises(RuntimeError):
                                diag.structural_diagnosis(directory, self.context)
                        else:
                            result = diag.structural_diagnosis(directory, self.context)
                            self.assertIn("CANONICAL_COMPILER:CANONICAL_VALIDATOR_EXCEPTION", result["codes"])
                            self.assertIs(diag.compiler.validate_batch_guarded, fail)
                else:
                    result = diag.structural_diagnosis(directory, self.context)
                    if scenario == "canonical":
                        self.assertIn("reference_integrity:EVENT_ANCHOR_NOT_OWN_EVENT_TIME", result["codes"])
                        self.assertTrue(result["validator_reports"])
                        self.assertNotIn("CANONICAL_COMPILER:CANONICAL_CONFORMANCE_FAILURE", result["codes"])
                    elif scenario == "valid":
                        self.assertEqual(result["codes"], [])
                    elif scenario == "schema":
                        self.assertIn("SCHEMA:DRAFT_SCHEMA_FAILURE", result["codes"])
                    else:
                        self.assertEqual(result["codes"], ["artifact:NO_SAVED_DRAFT"])
                self.assertIs(diag.compiler.validate_batch_guarded, original)

    def test_placeholder_propositions_are_labelled_not_rejected(self):
        # Real DEV1 gold asserts placeholder propositions, which carry no predicate.
        batch = {"candidate_records": {
            "propositions": [{"id": "p-1", "placeholder": True}, {"id": "p-2", "predicate": "Says"}],
            "assertions": [{"id": "a-1", "proposition_id": "p-1"}, {"id": "a-2", "proposition_id": "p-2"}]}}
        self.assertEqual(diag._predicates(batch, {"propositions": []}), {"a-1": "PLACEHOLDER", "a-2": "Says"})

    def test_classification_completeness_predicates_and_evidence_role_pairs(self):
        for dataset in ("DEV1", "DEV2"):
            with self.subTest(dataset=dataset), self.fixture(dataset) as (options, gold, loader):
                record = diag.diagnose(**options)
                public = diag.public_record(record)[dataset]
                self.assertEqual(loader.call_count, 2)
                all_counts = public["variants"]["P3"]["all"]
                self.assertEqual((all_counts["cases"], all_counts["structurally_valid"], all_counts["structural_failures"]), (3, 2, 1))
                self.assertEqual(all_counts["missed_by_class"],
                                 {"OTHER_PREDICATE": 2, "VALUE_MISMATCH": 2, "REFERENT_MISMATCH": 2, "NOT_EXTRACTED": 2})
                self.assertEqual(all_counts["missed_by_cause_predicate"]["ROLE_LABEL"], {"Participates": 2})
                self.assertEqual(all_counts["missed_resolutions_by_class_predicate"],
                                 {"MENTION_SPAN_DIFFERS": {"RefersTo": 2}})
                self.assertEqual(all_counts["unmatched_by_class_predicate"]["NO_GOLD_ON_EVIDENCE"], {"Occurred": 2})
                self.assertEqual(all_counts["no_gold_by_predicate_role"], {"Occurred": {"NARRATION_SUMMARY": 2}})
                self.assertEqual(all_counts["no_gold_by_predicate"], {"Occurred": 2})
                self.assertEqual(all_counts["no_gold_by_role"], {"NARRATION_SUMMARY": 2})
                self.assertEqual(all_counts["unmatched_by_predicate"], {"Occurred": 4, "Participates": 2, "Possesses": 2, "RefersTo": 2})
                complete = public["variants"]["P3"]["by_completeness"]["COMPLETE_FOR_PROFILE"]
                uncertain = public["variants"]["P3"]["by_completeness"]["UNCERTAIN"]
                self.assertEqual((complete["cases"], uncertain["cases"]), (1, 2))
                self.assertEqual(complete["unmatched_by_predicate"], uncertain["unmatched_by_predicate"])
                self.assertGreater(all_counts["role_pairs"]["DEPICTION"]["NARRATION_SUMMARY"], 0)
                last = record["variants"]["P3"][options["cases"][-1]]
                self.assertEqual(last["structural"]["draft_phase"], "repair_1")
                private = json.dumps(record)
                public_text = json.dumps(public)
                for forbidden in ("Mara", "Tomas", "the old key", "signature", "content_key", "positions"):
                    with self.subTest(forbidden=forbidden):
                        self.assertNotIn(forbidden, private)
                        self.assertNotIn(forbidden, public_text)
                for rid in [*options["cases"], *[a["id"] for a in self.gold["candidate_records"]["assertions"]]]:
                    self.assertNotIn(rid, public_text)
                def counts_only(node):
                    if isinstance(node, dict):
                        for child in node.values():
                            counts_only(child)
                    else:
                        self.assertIs(type(node), int)
                counts_only(public)
                self.assertEqual(json.loads((options["output_directory"] / diag.PRIVATE_NAME).read_text()), record)

    def test_optional_gold_and_literal_variant_adapters(self):
        for optional in (False, True):
            with self.subTest(optional=optional), self.fixture(optional=optional) as (options, _, _):
                record = diag.diagnose(**options)
                missed = record["variants"]["P3"][options["cases"][0]]["missed"]
                self.assertEqual(len(missed), 3 if optional else 4)
        ingestion, base = fx.ingest_text("Ari sat.\n")
        builder = fx.Builder(ingestion, base, prefix="literal")
        entity = builder.named(1, "Ari")
        builder.claim(builder.prop("NamedAs", entity=fx.E(entity), name=fx.S("Ari"),
            name_kind=fx.TOK("name_kind", "GIVEN")), [[builder.ev(1)]], validity=fx.OPEN)
        gold, pred = builder.batch(), deepcopy(builder.batch())
        pred["candidate_records"]["propositions"][-1]["args"]["name"]["value"] = "Arie"
        scope = gold["scope"]
        context = diag.compiler.DraftCompilerContext(base, scope["passage_inputs"], scope["as_of_position"],
            scope["profile_id"], "SYN", "v1.1", "SYN", ingestion)
        case = diag.runner.CaseInput("DEV2_01", {}, context, ())
        item = {"gold_batch": gold, "literal_variants": [{"predicate": "NamedAs", "argument": "name", "values": ["Ari", "Arie"]}]}
        evaluation = diag.runner.scoring.evaluator.evaluate_case(base, gold, pred, ingestion=ingestion,
            case_spec={"literal_variants": item["literal_variants"]})
        original = diag.frozen.ev._literal_groups
        result = diag.valid_diagnosis(case, item, pred, evaluation)
        self.assertEqual(result["missed"], [])
        self.assertIs(diag.frozen.ev._literal_groups, original)
        with patch.object(diag.frozen, "case_diagnosis", side_effect=RuntimeError("private")):
            with self.assertRaises(RuntimeError):
                diag.valid_diagnosis(case, item, pred, evaluation)
        self.assertIs(diag.frozen.ev._literal_groups, original)

    def test_paired_recovery_uses_only_jointly_valid_cases(self):
        # Both predictions share gold identities; each misses a different required assertion.
        a, b = deepcopy(self.gold), deepcopy(self.gold)
        named_id = next(x["id"] for x in a["candidate_records"]["assertions"]
                        if x["proposition_id"] == next(p["id"] for p in a["candidate_records"]["propositions"] if p["predicate"] == "NamedAs"))
        part_id = next(x["id"] for x in a["candidate_records"]["assertions"]
                       if x["proposition_id"] == next(p["id"] for p in a["candidate_records"]["propositions"] if p["predicate"] == "Participates"))
        for pred, missing in ((a, named_id), (b, part_id)):
            pred["candidate_records"]["assertions"] = [x for x in pred["candidate_records"]["assertions"] if x["id"] != missing]
        for order in (("P3", "P4R3"), ("P4R3", "P3")):
            with self.subTest(order=order), self.fixture(predictions={"P3": a, "P4R3": b}) as (options, _, _):
                record = diag.diagnose(**{**options, "variants": order})
                comparison = diag.public_record(record)["DEV2"]["paired"]["__".join(order)]
                n = len(self.gold["candidate_records"]["assertions"])
                self.assertEqual(comparison["all"]["cases_valid_in_both"], 2)
                for label in diag.COMPLETENESS:
                    part = comparison["by_completeness"][label]
                    self.assertEqual(part["cases_valid_in_both"], 1)
                    self.assertEqual((part["required_recovered_a"], part["required_recovered_b"]), (n - 1, n - 1))
                    self.assertEqual(part["a_only_by_predicate"], {"Participates" if order[0] == "P3" else "NamedAs": 1})
                    self.assertEqual(part["b_only_by_predicate"], {"NamedAs" if order[0] == "P3" else "Participates": 1})
                    self.assertEqual(sum(part["both_by_predicate"].values()), n - 2)

    def test_saved_role_failures_with_multiple_gold_roles(self):
        with self.fixture() as (options, _, _):
            path = options["output_root"] / "P3" / "score.json"
            score = json.loads(path.read_text())
            for row in score["rows"]:
                row["evaluation"].setdefault("failures", []).append({"code": "WRONG_EVIDENCE_ROLE",
                    "gold": ["DEPICTION", "NARRATION_SUMMARY"], "predicted": "DIALOGUE"})
            self.write(path, score)
            counts = diag.public_record(diag.diagnose(**options))["DEV2"]["variants"]["P3"]["all"]
            for role in ("DEPICTION", "NARRATION_SUMMARY"):
                with self.subTest(role=role):
                    self.assertEqual(counts["role_pairs"][role]["DIALOGUE"], 3)

    def test_loader_dispatch_verification_and_missing_arguments(self):
        args = dict(dataset="DEV2", variant="P3", selected=["DEV2_01"], input_root=Path("synthetic"),
                    dev2_input=None, dev2_gold=None, dev1_package=None, dev1_ingestion_manifest=None, dev1_source_root=None)
        for dataset in ("DEV1", "DEV2"):
            for supplied in (False, True):
                with self.subTest(dataset=dataset, supplied=supplied):
                    kwargs = {**args, "dataset": dataset}
                    if supplied:
                        kwargs.update({k: Path("synthetic") for k in args if k.startswith("dev")})
                    with patch.object(diag.runner, "verify_packages") as verify, \
                            patch.object(diag.runner.protocol, "file_sha256", return_value=diag.runner.DEV1_SHA256), \
                            patch.object(diag.runner, "load_dev1_cases", return_value=([1], {"gold": 2})) as dev1, \
                            patch.object(diag.runner, "load_cases", return_value=[1]) as dev2, \
                            patch.object(diag.runner, "read_gold", return_value={"gold": 2}):
                        if not supplied:
                            with self.assertRaises(diag.runner.DevelopmentError):
                                diag._load_inputs(**kwargs)
                        else:
                            self.assertEqual(diag._load_inputs(**kwargs), ([1], {"gold": 2}))
                            if dataset == "DEV1":
                                dev1.assert_called_once_with(Path("synthetic"), Path("synthetic"), args["selected"],
                                                             Path("synthetic"), Path("synthetic"), "P3")
                            else:
                                verify.assert_called_once()
                                dev2.assert_called_once_with(Path("synthetic"), Path("synthetic"), args["selected"], variant="P3")
        with patch.object(diag.runner.protocol, "file_sha256", return_value="wrong"):
            with self.assertRaisesRegex(diag.runner.DevelopmentError, "hash mismatch"):
                diag._load_inputs(**{**args, "dataset": "DEV1", "dev1_package": Path("synthetic"),
                    "dev1_ingestion_manifest": Path("synthetic"), "dev1_source_root": Path("synthetic")})

    def test_refuses_unreproduced_evaluations_and_bad_input_sets(self):
        for problem in ("one variant", "duplicate variant", "unsafe variant", "duplicate score", "missing score",
                        "missing loader case", "duplicate loader case", "missing gold", "completeness", "different labels",
                        "missed count", "resolution count", "recovery count"):
            with self.subTest(problem=problem), self.fixture() as (options, gold, loader):
                if problem in ("one variant", "duplicate variant", "unsafe variant"):
                    options["variants"] = {"one variant": ["P3"], "duplicate variant": ["P3", "P3"],
                                           "unsafe variant": ["P3", "../secret"]}[problem]
                elif problem.endswith("score") or problem.endswith("count"):
                    path = options["output_root"] / "P3" / "score.json"
                    score = json.loads(path.read_text())
                    if problem == "duplicate score":
                        score["rows"] *= 2
                    elif problem == "missing score":
                        score["rows"] = []
                    elif problem == "missed count":
                        score["rows"][0]["evaluation"]["failures"] = []
                    elif problem == "resolution count":
                        score["rows"][0]["evaluation"]["failures"].append({"code": "MISSING_ENTITY_RESOLUTION"})
                    else:
                        score["rows"][0]["evaluation"]["counts"]["required_recovered"] = 999
                    self.write(path, score)
                elif "loader case" in problem:
                    loaded, _ = loader.return_value
                    loader.return_value = (loaded[:-1] if problem.startswith("missing") else loaded * 2, gold)
                elif problem == "missing gold":
                    gold.clear()
                elif problem == "completeness":
                    gold[options["cases"][0]]["gold_completeness"] = "INCOMPLETE"
                else:
                    loaded, _ = loader.return_value
                    other = deepcopy(gold)
                    other[options["cases"][0]]["gold_completeness"] = "UNCERTAIN"
                    loader.side_effect = [(loaded, gold), (loaded, other)]
                with self.assertRaises((diag.runner.DevelopmentError, diag.frozen.DiagnosisError)):
                    diag.diagnose(**options)
                self.assertFalse(options["output_directory"].exists())

    def test_cli_writes_private_json_and_prints_counts(self):
        original = diag.diagnose
        for dataset in ("DEV1", "DEV2"):
            with self.subTest(dataset=dataset), self.fixture(dataset) as (options, _, _):
                argv = ["--dataset", dataset, "--variants", "P3,P4R3", "--cases", ",".join(options["cases"]),
                        "--output-root", str(options["output_root"]), "--output-directory", str(options["output_directory"])]
                output = io.StringIO()
                with patch.object(diag, "diagnose", side_effect=lambda **kw: original(**{**options, **kw})), redirect_stdout(output):
                    self.assertEqual(diag.main(argv), 0)
                self.assertTrue((options["output_directory"] / diag.PRIVATE_NAME).is_file())
                self.assertIn(dataset, json.loads(output.getvalue()))
                output = io.StringIO()
                with patch.object(diag, "diagnose", side_effect=ValueError("private source Mara")), redirect_stdout(output):
                    self.assertEqual(diag.main(argv), 2)
                self.assertEqual(output.getvalue().strip(), "M4_P4_DEV_DIAGNOSIS_STOPPED: ValueError")
        with patch("sys.argv", [diag.__name__]), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as stopped:
                runpy.run_module(diag.__name__, run_name="__main__")
        self.assertEqual(stopped.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
