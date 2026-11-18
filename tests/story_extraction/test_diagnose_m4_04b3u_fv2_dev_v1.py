"""Synthetic FV2 replays with package readers replaced by in-memory fixtures."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tests.story_extraction.test_diagnose_m4_04b3i_fv1_v1 import build
from tests.story_extraction.test_diagnose_m4_04b3q_fv2_v1 import fx
from tests.story_extraction.test_run_m4_04b3o_fv2_predictions_v1 import synthetic_case
from tools.story_extraction import diagnose_m4_04b3u_fv2_dev_v1 as diag


@contextmanager
def replay_inputs(fixtures):
    rows, gold = [], {}
    for case, gold_batch in fixtures:
        context = case.compiler_context
        rows.append({"case_id": case.case_id, "context": context, "prepared_input": case.prepared_input,
                     "base_document": context.base_document})
        gold[case.case_id] = {"gold_batch": gold_batch, "gold_completeness": "COMPLETE_FOR_PROFILE"}
    with (mock.patch.object(diag.lock, "CASE_IDS", tuple(gold)),
          mock.patch.object(diag.lock, "verify_fv2_packages") as verify,
          mock.patch.object(diag.runner, "load_input_cases", return_value=rows),
          mock.patch.object(diag.seal, "load_input_cases", return_value=rows) as load_contexts,
          mock.patch.object(diag.scorer, "read_gold", return_value=gold) as read_gold):
        yield verify, load_contexts, read_gold


def write_raw(root, case_id, phase, raw):
    directory = root / "predictions" / "artifacts" / "raw"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{case_id}_{phase}.txt").write_bytes(raw)


class DevelopmentDiagnosisTests(unittest.TestCase):
    def test_blocking_sets_and_counterfactuals_count_cases(self):
        codes = {
            "L1": "WRONG_EVIDENCE_SPAN", "L2": "WRONG_VALIDITY_BOUND", "L3": "WRONG_EVENT_GRANULARITY",
            "L4": "MISSED_REQUIRED_ASSERTION", "U": "UNSUPPORTED_ASSERTION",
        }
        combinations = ("L1", "L2", "L3", "L4", "U", "L1+L2", "L1+U", "L4+U", "L1+L2+U", "L1+L4+U")

        def evaluation(*failures, valid=True, pending=0):
            return {
                "l0_structural_validity": valid,
                "counts": {"pending_adjudication": pending},
                "failures": [{"code": code, "material": code != "DUPLICATE_ASSERTION"} for code in failures],
            }

        evaluations = [evaluation(*(codes[layer] for layer in group.split("+"))) for group in combinations]
        evaluations.extend([
            evaluation("DUPLICATE_ASSERTION"),
            evaluation("MISSING_ENTITY_RESOLUTION", "MISSING_ENTITY_RESOLUTION"),
            evaluation("WRONG_ARGUMENT"),
            evaluation("CANONICAL_CONFORMANCE_FAILURE", valid=False),
            evaluation(pending=1),
        ])
        blocking_sets, counterfactual = diag._blocker_counts(evaluations)
        self.assertEqual(blocking_sets, {
            **dict.fromkeys(combinations, 1), "U": 2, "L3+L4": 1, "NONE": 2, "L0": 1,
        })
        expected = {
            "L1": 2, "L2": 2, "L3": 3, "L4": 3, "U": 3, "L1+L2": 4, "L1+U": 5, "L4+U": 6,
            "L1+L2+U": 8, "L1+L4+U": 9, "ALL_BUT_L4": 9, "ALL_BUT_U": 7,
        }
        self.assertEqual(set(counterfactual), set(expected))
        for group, count in expected.items():
            with self.subTest(group=group):
                self.assertEqual(counterfactual[group], count)

    def test_histogram_boundaries(self):
        for count, bucket in enumerate(("0", "1", "2", "3-5", "3-5", "3-5", "6+", "6+")):
            with self.subTest(count=count):
                self.assertEqual(diag._histogram_bin(count), bucket)

    def test_replay_tries_repair_after_primary_failure_and_threads_options(self):
        first, draft = synthetic_case("SECRET_FIRST")
        second, _ = synthetic_case("SECRET_SECOND")
        _, _, gold = fx.build("c06_participant")
        fixtures = [(first, gold), (second, gold)]
        for repairs in (frozenset(), frozenset({"QR", "ME", "TB"}), frozenset(diag.REPAIR_OPTIONS)):
            with (self.subTest(repairs=repairs), tempfile.TemporaryDirectory() as tmp,
                  replay_inputs(fixtures),
                  mock.patch.object(diag.lock.dev, "validate_attempt", wraps=diag.lock.dev.validate_attempt) as validate):
                root = Path(tmp)
                write_raw(root, first.case_id, "primary", json.dumps(draft).encode("utf-8"))
                write_raw(root, first.case_id, "repair_1", b"\xff")
                write_raw(root, second.case_id, "primary", b"{\r\n")
                write_raw(root, second.case_id, "repair_1", json.dumps(draft).encode("utf-8"))
                public = diag.diagnose(root, root, root / "out", repairs=repairs, align_v3=False)
                expected = {
                    "quote_resolution": "QR" in repairs, "anchor_mentions": "AM" in repairs,
                    "mention_evidence": "ME" in repairs, "sentence_evidence": "SE" in repairs,
                    "transfer_bounds": "TB" in repairs,
                    "mention_evidence_predicates": diag.lock.dev.MENTION_EVIDENCE_PREDICATES,
                }
                self.assertEqual([call.args[1] for call in validate.call_args_list], [first, second, second])
                self.assertEqual([call.kwargs for call in validate.call_args_list], [expected] * 3)
                self.assertEqual(validate.call_args_list[1].args[0], "{\r\n")
                items = json.loads((root / "out" / diag.ITEMS_NAME).read_bytes())
                self.assertEqual([items[case.case_id]["phase"] for case in (first, second)], ["primary", "repair_1"])
                self.assertEqual(public["repairs"], sorted(repairs))
                self.assertEqual(public["valid_cases"], 2)

    def test_public_counts_and_private_items_for_failures_and_unscorable_case(self):
        ingestion, base, gold = build("g")
        _, _, predicted = build("p")
        case = diag.runner.CaseInput("SECRET_VALID_CASE", {}, SimpleNamespace(base_document=base, ingestion=ingestion))
        missing = diag.runner.CaseInput("SECRET_MISSING_CASE", {}, case.compiler_context)
        fixtures = [(case, gold), (missing, gold)]
        with (tempfile.TemporaryDirectory() as tmp, replay_inputs(fixtures),
              mock.patch.object(diag.lock.dev, "validate_attempt", return_value=(None, None, predicted, {}))):
            root = Path(tmp)
            write_raw(root, case.case_id, "primary", b"SECRET_RAW_RESPONSE")
            public = diag.diagnose(root, root, root / "out", repairs=frozenset(), align_v3=False)
            serialized = (root / "out" / diag.PUBLIC_NAME).read_bytes()
            private = json.loads((root / "out" / diag.ITEMS_NAME).read_bytes())
        self.assertEqual(public, json.loads(serialized))
        self.assertNotIn(b"\r", serialized)
        self.assertFalse(serialized.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(set(private), {case.case_id, missing.case_id})
        self.assertEqual(public["blocking_sets"], {"L0": 1, "L3+L4+U": 1})
        self.assertEqual((public["case_count"], public["valid_cases"], public["l1_pass"], public["full_success"]),
                         (2, 1, 1, 0))
        self.assertEqual(public["totals"], {
            "matched": 5, "grounded": 5, "required_recovered": 5, "predicted": 10, "unsupported": 5,
        })
        self.assertEqual(public["missed_required"], {
            "NamedAs": {"OTHER_PREDICATE": 1}, "Participates": {"VALUE_MISMATCH": 1},
            "Occurred": {"REFERENT_MISMATCH": 1, "NOT_EXTRACTED": 1},
        })
        self.assertEqual(public["missed_resolutions_by_class"], {"MENTION_SPAN_DIFFERS": 1})
        self.assertEqual(public["unsupported"]["by_predicate_and_mechanical_hint"], {
            predicate: {"UNSUPPORTED_ASSERTION": count}
            for predicate, count in (("Occurred", 2), ("Participates", 1), ("Possesses", 1), ("RefersTo", 1))
        })
        for field in ("missed_per_case_histogram", "unsupported_per_case_histogram"):
            self.assertEqual(public[field], {"0": 0, "1": 0, "2": 0, "3-5": 1, "6+": 0})
        self.assertNotIn("per_case", public)
        for forbidden in ("SECRET_", "Mara", "the old key", "content_key",
                          private[case.case_id]["missed"][0]["id"]):
            self.assertNotIn(forbidden, serialized.decode("utf-8"))

    def test_v3_alignment_uses_verified_ingestion_bytes_only_when_enabled(self):
        source = "「銀鈴」\r\n"
        ingestion, base = fx.ingest_text(source)
        gold_builder = fx.Builder(ingestion, base, prefix="g")
        gold_builder.named(1, "銀鈴", role="IN_WORLD_REPORT")
        gold = gold_builder.batch()
        builder = fx.Builder(ingestion, base, prefix="p")
        builder.named(1, "銀鈴")
        case = diag.runner.CaseInput("FV2_SYN", {}, SimpleNamespace(base_document=base, ingestion=ingestion))
        doc = ingestion.documents[0]
        with (tempfile.TemporaryDirectory() as tmp, replay_inputs([(case, gold)]),
              mock.patch.object(diag.lock.dev, "validate_attempt", return_value=(None, None, builder.batch(), {})),
              mock.patch.object(diag.conventions, "align_mention_roles",
                                wraps=diag.conventions.align_mention_roles) as align):
            root = Path(tmp)
            write_raw(root, case.case_id, "primary", b"{}")
            for enabled in (False, True):
                with self.subTest(enabled=enabled):
                    public = diag.diagnose(root, root, root / "out", repairs=frozenset(), align_v3=enabled)
                    self.assertIs(public["align_v3"], enabled)
                    self.assertEqual((public["aligned"], public["flagged"]), (int(enabled), int(enabled)))
                    self.assertEqual((public["l1_pass"], public["full_success"]), (int(enabled), int(enabled)))
                    self.assertEqual(public["l1_remaining"],
                                     {} if enabled else {"NO_PREDICATE": {"WRONG_EVIDENCE_ROLE": 1}})
                    if enabled:
                        align.assert_called_once_with(gold, {doc.version: source.encode("utf-8")}, base)
                    else:
                        align.assert_not_called()
            with mock.patch.object(doc, "source_bytes", source.replace("\r", "").encode("utf-8")):
                with self.assertRaisesRegex(ValueError, "Source map key does not match source hash"):
                    diag.diagnose(root, root, root / "invalid", repairs=frozenset(), align_v3=True)
                self.assertFalse((root / "invalid").exists())

    def test_package_verification_precedes_gold_and_refuses_bad_input(self):
        case, _ = synthetic_case()
        _, _, batch = fx.build("c06_participant")
        fv2 = Path("fixtures")
        out = mock.Mock()
        for variant in ("verified", "bad_lock", "changed_lock", "input_order", "gold_order", "completeness"):
            with self.subTest(variant=variant), replay_inputs([(case, batch)]) as (verify, load_contexts, read_gold):
                calls = mock.Mock()
                calls.attach_mock(verify, "verify")
                calls.attach_mock(load_contexts, "contexts")
                calls.attach_mock(read_gold, "gold")
                mismatch = diag.lock.Fv2ProtocolError("FV2 package hash mismatch")
                if variant == "bad_lock":
                    verify.side_effect = mismatch
                elif variant == "changed_lock":
                    verify.side_effect = [None, None, mismatch]
                elif variant == "input_order":
                    load_contexts.return_value = []
                elif variant == "gold_order":
                    read_gold.return_value = {}
                elif variant == "completeness":
                    read_gold.return_value[case.case_id]["gold_completeness"] = "INCOMPLETE"
                else:
                    read_gold.side_effect = LookupError("stop after gold is opened")
                error = {
                    "verified": LookupError, "bad_lock": diag.lock.Fv2ProtocolError,
                    "changed_lock": diag.lock.Fv2ProtocolError,
                }.get(variant, diag.fv1.DiagnosisError)
                with self.assertRaises(error):
                    diag.diagnose(fv2, mock.Mock(), out, repairs=frozenset(), align_v3=False)
                expected = [mock.call.verify(fv2, include_gold=True)]
                if variant != "bad_lock":
                    expected += [mock.call.verify(fv2), mock.call.contexts(fv2 / diag.lock.FV2_INPUT_NAME)]
                    if variant != "input_order":
                        expected += [mock.call.verify(fv2, include_gold=True)]
                        if variant != "changed_lock":
                            expected += [mock.call.gold(fv2 / diag.lock.FV2_GOLD_NAME)]
                self.assertEqual(calls.mock_calls, expected)

    def test_cli_parses_repair_set_and_refuses_invalid_options(self):
        args = ["--fv2", "input", "--run", "pred", "--out", "result"]
        for options, repairs, align in [
            ([], frozenset(), False),
            (["--repairs", "QR, ME,AM,TB,SE", "--align-v3"], frozenset({"QR", "AM", "ME", "SE", "TB"}), True),
            (["--repairs", ""], frozenset(), False),
        ]:
            with (self.subTest(options=options), redirect_stdout(io.StringIO()) as stdout,
                  mock.patch.object(diag, "diagnose", return_value={"valid_cases": 1}) as diagnose):
                self.assertEqual(diag.main(args + options), 0)
                self.assertEqual(json.loads(stdout.getvalue()), {"valid_cases": 1})
                diagnose.assert_called_once_with(Path("input"), Path("pred"), Path("result"),
                                                 repairs=repairs, align_v3=align)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as invalid:
            diag.main(args + ["--repairs", "QR,unknown"])
        self.assertEqual(invalid.exception.code, 2)
        with self.assertRaisesRegex(ValueError, "Unknown FV2 development repair"):
            diag.diagnose(None, None, None, repairs=frozenset({"unknown"}), align_v3=False)
        with (mock.patch.object(diag, "diagnose", side_effect=diag.fv1.DiagnosisError("PRIVATE_DETAIL")),
              redirect_stderr(io.StringIO()) as stderr, redirect_stdout(io.StringIO()) as stdout):
            self.assertEqual(diag.main(args), 2)
            self.assertEqual(stderr.getvalue().strip(), "FV2 development diagnosis refused")
            self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
