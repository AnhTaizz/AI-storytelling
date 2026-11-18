"""Offline FV2 diagnosis tests using synthetic cases and in-memory package contents."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.story_extraction.test_diagnose_m4_04b3i_fv1_v1 import OPEN, SPEC, TEXT, build, fx
from tests.story_extraction.test_score_m4_04b3p_fv2_v1 import fake_transport, score_options, synthetic_bundle
from tools.story_extraction import diagnose_m4_04b3q_fv2_v1 as diag
from tools.story_extraction import fresh_validation_seal_v1 as seal
from tools.story_extraction import m4_04b3n_fv2_protocol_v1 as lock
from tools.story_extraction import run_m4_04b3o_fv2_predictions_v1 as runner
from tools.story_extraction import score_m4_04b3p_fv2_v1 as scorer


@contextmanager
def scored_bundle(structural_failure=False):
    """Reuse the scorer fixture with the archive boundaries replaced by memory."""
    inputs, gold, digests = [], {}, {}
    file_sha256 = lock.file_sha256

    def seal_in_memory(cases, directory, *_):
        for case in cases:
            context = seal.compiler_context(case.case_id, case.base_document, case.gold_batch["scope"], case.ingestion)
            inputs.append({"case_id": case.case_id, "context": context, "base_document": case.base_document,
                           "prepared_input": seal.prepare_story_extraction_draft_v1_1(context)})
            gold[case.case_id] = {"gold_batch": case.gold_batch, "gold_completeness": "COMPLETE_FOR_PROFILE"}
        packages = {key: {"sha256": lock.sha256_bytes(name.encode())}
                    for key, name, _ in lock.package_bindings()}
        digests.update({directory / name: packages[key]["sha256"] for key, name, _ in lock.package_bindings()})
        return {"packages": packages}

    def package_digest(path):
        return digests[path] if path in digests else file_sha256(path)

    with (tempfile.TemporaryDirectory() as tmp,
          mock.patch.object(seal, "seal", side_effect=seal_in_memory),
          mock.patch.object(lock, "file_sha256", side_effect=package_digest),
          mock.patch.object(runner, "load_input_cases", return_value=inputs),
          mock.patch.object(scorer, "load_input_cases", return_value=inputs),
          mock.patch.object(scorer.shared, "read_gold", return_value=gold) as opened,
          synthetic_bundle(Path(tmp)) as (options, _, drafts)):
        prefix = f"M4B3N_{lock.PROMPT_VARIANT}_FV2_01_"
        overrides = {prefix + phase: ["{"] for phase in ("PRIMARY", "REPAIR_1")} if structural_failure else {}
        result = runner.execute(**options, transport=fake_transport(drafts, overrides=overrides), wait=lambda _: None)
        arguments = score_options(options, result)
        scored = scorer.score(**arguments)
        opened.reset_mock()
        yield (arguments | {"scoring_directory": arguments["output_directory"],
                            "output_directory": Path(tmp) / "diagnosis"}, scored, opened, digests)


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


class DiagnosisTests(unittest.TestCase):
    def test_bad_or_missing_prerequisites_refuse_before_gold(self):
        with scored_bundle() as (options, _, opened, digests):
            paths = {
                "prediction lock": options["prediction_directory"] / runner.PREDICTION_LOCK_NAME,
                "protocol": options["protocol_path"],
                "gold access": options["scoring_directory"] / scorer.ACCESS_NAME,
            }
            for label, path in paths.items():
                original = path.read_bytes()
                for missing in (False, True):
                    with self.subTest(artifact=label, missing=missing), \
                            mock.patch.object(lock, "verify_fv2_packages", wraps=lock.verify_fv2_packages) as verified:
                        if missing:
                            path.unlink()
                        elif label == "gold access":
                            write_json(path, json.loads(original) | {"prediction_lock_sha256": "wrong"})
                        else:
                            path.write_bytes(original + b" ")
                        with self.assertRaises((OSError, diag.DiagnosisError, lock.Fv2ProtocolError,
                                                scorer.Fv2ScoringError)):
                            diag.diagnose(**options)
                        opened.assert_not_called()
                        verified.assert_not_called()
                        path.write_bytes(original)
            digests[options["fv2_directory"] / lock.FV2_GOLD_NAME] = "wrong"
            with self.assertRaisesRegex(lock.Fv2ProtocolError, "package hash mismatch"):
                diag.diagnose(**options)
            opened.assert_not_called()
            self.assertFalse(options["output_directory"].exists())

    def test_reproduction_refuses_changed_scoring(self):
        with scored_bundle() as (options, scored, opened, _):
            path = options["scoring_directory"] / f"{scorer.EVALUATION_ID}.json"
            for field, message in (("unsupported", "does not reproduce"), ("grounded", "Grounded"),
                                   ("matched_predictions", "Matched")):
                with self.subTest(field=field):
                    changed = deepcopy(scored)
                    changed["rows"][0]["evaluation"]["counts"][field] += 1
                    write_json(path, changed)
                    with self.assertRaisesRegex(diag.DiagnosisError, message):
                        diag.diagnose(**options)
                    self.assertFalse(options["output_directory"].exists())
            for change, message in (({"gold_sha256": "wrong"}, "binding"), ({"rows": []}, "case rows")):
                with self.subTest(message=message):
                    write_json(path, scored | change)
                    opened.reset_mock()
                    with self.assertRaisesRegex(diag.DiagnosisError, message):
                        diag.diagnose(**options)
                    opened.assert_not_called()

    def test_grounding_classes_and_evaluator_semantics(self):
        ingestion, base = fx.ingest_text(TEXT)

        def batch(prefix, spans, mixed):
            builder = fx.Builder(ingestion, base, prefix=prefix)
            entity = builder.named(1, "Mara")
            if mixed and prefix == "g":
                builder.ev(1, "Tomas", role="PARATEXT")
            proposition = builder.prop("NamedAs", entity=fx.E(entity), name=fx.S("Mara"),
                                       name_kind=fx.TOK("name_kind", "GIVEN"))
            builder.claim(proposition, [[builder.ev(segment, text)] for segment, text in spans], validity=OPEN)
            return builder.batch()

        name, wider, overlap, other, another = (
            (1, "old key"), (1, "the old key"), (1, "key to"), (1, "Tomas"), (2, None))
        variants = [
            ([name], [name], ["EXACT"], True, False),
            ([name], [wider], ["PRED_WIDER"], True, False),
            ([name], [wider], ["PRED_WIDER"], False, True),
            ([wider], [name], ["PRED_NARROWER"], False, False),
            ([name], [overlap], ["PARTIAL_OVERLAP"], False, False),
            ([name], [other], ["NO_OVERLAP_SAME_PASSAGE"], False, False),
            ([name], [another], ["OTHER_PASSAGE"], False, False),
            ([name, another], [name], ["PARTIAL_OVERLAP", "MISSING_GOLD_EVIDENCE_SET"], True, False),
            ([name], [name, another], ["PARTIAL_OVERLAP", "EXTRA_PREDICTED_EVIDENCE_SET"], True, False),
        ]
        for gold_spans, pred_spans, classes, grounded, mixed in variants:
            with self.subTest(classes=classes, mixed=mixed):
                gold, pred = batch("g", gold_spans, mixed), batch("p", pred_spans, mixed)
                scored = scorer.shared.evaluator.evaluate_case(base, gold, pred, ingestion=ingestion, case_spec=SPEC)
                pairs = diag.grounding_diagnosis(base, gold, pred, scored)
                named = next(pair for pair in pairs if pair["predicate"] == "NamedAs")
                self.assertEqual(named["classes"], classes)
                self.assertIs(named["grounded"], grounded)
                self.assertEqual(named["gold_evidence_roles"], ["DEPICTION"])
                self.assertEqual(scored["counts"]["grounded"], 1 + grounded)

    def test_derivation_only_support_reproduces_grounding(self):
        fixture = "c12_suggested_emotion"
        ingestion, base, gold = fx.build(fixture)
        for variant, classes, grounded in (("gold", ["EXACT"], True),
                                           ("overstated", ["EXTRA_PREDICTED_EVIDENCE_SET"], False)):
            with self.subTest(variant=variant):
                _, _, pred = fx.build(fixture, variant=variant, prefix="p")
                scored = scorer.shared.evaluator.evaluate_case(base, gold, pred, ingestion=ingestion, case_spec=SPEC)
                pairs = diag.grounding_diagnosis(base, gold, pred, scored)
                emotion = next(pair for pair in pairs if pair["predicate"] == "EmotionToward")
                self.assertIs(emotion["grounded"], grounded)
                self.assertEqual(emotion["classes"], classes)
                self.assertEqual(emotion["gold_evidence_roles"], [])

    def test_layers_and_unmatched_details_aggregate_by_fixed_labels(self):
        ingestion, base, gold = build("g")
        _, _, pred = build("p")
        scored = scorer.shared.evaluator.evaluate_case(base, gold, pred, ingestion=ingestion, case_spec=SPEC)
        predicates = set(diag.ev.load_registry()["predicates"]) | {diag.NO_PREDICATE}
        cases = {"SECRET_FV1_CASE": diag._evaluation_details(scored, predicates)}
        for index, (code, material) in enumerate((
                ("WRONG_EVIDENCE_ROLE", True), ("WRONG_POLARITY", True),
                ("MISSING_ENTITY_RESOLUTION", True), ("MISSED_REQUIRED_ASSERTION", True),
                ("UNSUPPORTED_ASSERTION", True), ("DUPLICATE_ASSERTION", False))):
            result = {**scored, "failures": [{"code": code, "material": material}], "failure_codes": [code],
                      "full_canonical_case_success": not material, "unmatched_predictions": []}
            cases[str(index)] = diag._evaluation_details(result, predicates)
        public = diag._public_record(cases)
        self.assertEqual(public["first_failing_layer"], {"L1": 1, "L2": 1, "L3": 2, "L4": 1, "L5": 1, "NONE": 1})
        for layer in ("L3", "L4", "L5"):
            self.assertEqual(public["layer_blocking"]["by_layer"][layer]["MISSING_ENTITY_RESOLUTION"], 2)
        self.assertEqual(public["layer_blocking"]["by_predicate"]["RefersTo"]["MISSING_ENTITY_RESOLUTION"], 1)
        self.assertEqual(public["unsupported"]["by_state"], {"UNSUPPORTED_ASSERTION": 5})
        self.assertEqual(public["unsupported"]["by_mechanical_hint"], {"UNSUPPORTED_ASSERTION": 5})
        self.assertEqual(public["unsupported"]["by_predicate"]["Occurred"], 2)
        encoded = json.dumps(public)
        for forbidden in ("SECRET_FV1_CASE", "content_key", "Mara",
                          *(entry["content_key"] for entry in scored["unmatched_predictions"])):
            self.assertNotIn(forbidden, encoded)
        for field in ("predicate", "state", "mechanical_hint"):
            with self.subTest(field=field):
                changed = deepcopy(scored)
                changed["unmatched_predictions"][0][field] = TEXT
                with self.assertRaisesRegex(diag.DiagnosisError, "Invalid unmatched prediction category"):
                    diag._evaluation_details(changed, predicates)

    def test_cli_reports_only_counts_and_writes_private_items(self):
        with scored_bundle(structural_failure=True) as (options, scored, opened, _):
            score_path = options["scoring_directory"] / f"{scorer.EVALUATION_ID}.json"
            scored["rows"][0]["evaluation"]["source_text"] = "SECRET_SOURCE_TEXT"
            scored["rows"][1]["annotation_conventions"]["findings"] = [{"record_ids": ["SECRET_HANDLE"]}]
            write_json(score_path, scored)
            args = []
            for key, value in options.items():
                args.extend([f"--{'protocol' if key == 'protocol_path' else key.replace('_', '-')}", str(value)])
            with redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(diag.main(args), 0)
            opened.assert_called_once_with(options["fv2_directory"] / lock.FV2_GOLD_NAME)
            public_text = (options["output_directory"] / diag.PUBLIC_NAME).read_text(encoding="utf-8")
            items = json.loads((options["output_directory"] / diag.ITEMS_NAME).read_bytes())
            public = json.loads(public_text)
            self.assertEqual(public, json.loads(stdout.getvalue()))
            self.assertEqual(public["first_failing_layer"], {"L0": 1, "NONE": 1})
            self.assertEqual(public["grounding"]["grounded_pairs"], 2)
            self.assertEqual(public["grounding"]["by_predicate"]["RefersTo"], {"EXACT": 2})
            self.assertEqual(public["grounding"]["by_gold_evidence_role"]["DEPICTION"], {"EXACT": 2})
            for serialized in (public_text, stdout.getvalue()):
                for forbidden in (*items, "per_case", "case_id", "content_key", "source_text", "SECRET", "Mira",
                                  items["FV2_02"]["grounding"][0]["prediction_id"]):
                    self.assertNotIn(forbidden, serialized)
            args[args.index("--prediction-lock-sha256") + 1] = "wrong"
            opened.reset_mock()
            with redirect_stderr(io.StringIO()) as refused, redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(diag.main(args), 2)
            self.assertEqual(refused.getvalue().strip(), "FV2 diagnosis refused")
            self.assertEqual(stdout.getvalue(), "")
            opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
