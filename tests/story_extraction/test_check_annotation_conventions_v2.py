"""Synthetic tests for the V3 dialogue evidence rule and development alignment."""

import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_check_annotation_conventions_v1 import Synthetic, literal, token
from tools.story_extraction import check_annotation_conventions_v2 as checker


class AnnotationConventionsV2Tests(unittest.TestCase):
    def test_dialogue_role_applies_to_sufficient_affirmed_and_negated_mentions(self):
        cases = (
            ("RefersTo", "AFFIRMED", "SUFFICIENT", "IN_WORLD_REPORT", True),
            ("NamedAs", "AFFIRMED", "SUFFICIENT", "IN_WORLD_REPORT", True),
            ("NamedAs", "NEGATED", "SUFFICIENT", "RETROSPECTIVE", True),
            ("RefersTo", "AFFIRMED", "SUFFICIENT", "DEPICTION", False),
            ("RefersTo", "OPEN", "SUFFICIENT", "IN_WORLD_REPORT", False),
            ("RefersTo", "AFFIRMED", "CORROBORATING", "IN_WORLD_REPORT", False),
            ("LocatedAt", "AFFIRMED", "SUFFICIENT", "IN_WORLD_REPORT", False),
        )
        for predicate, polarity, label, role, expected in cases:
            with self.subTest(predicate=predicate, polarity=polarity, label=label, role=role):
                fixture = Synthetic("語り手は「銀鈴は物置にある」と答えた。")
                ref_id = fixture.evidence("銀鈴")
                fixture.records["evidence_refs"][1]["role"] = role
                args = {"name": literal("銀鈴")} if predicate == "NamedAs" else {}
                fixture.claim(predicate, evidence=[ref_id], polarity=polarity, **args)
                evidence_set = fixture.records["assertions"][0]["support"]["evidence_sets"][0]
                evidence_set["label"] = label
                # Repeated support paths still identify one issue for the assertion and ref.
                fixture.records["assertions"][0]["support"]["evidence_sets"].append(
                    dict(evidence_set, id="es-repeat")
                )
                report = checker.check_batch(fixture.batch, iter([fixture.raw]))
                self.assertEqual(report["counts"]["R-EVR-01"], int(expected))
                self.assertEqual(report["findings"], [{
                    "rule": "R-EVR-01", "code": "MENTION_ROLE_IN_DIALOGUE",
                    "record_ids": ["a-0", ref_id, "p-0"],
                }] if expected else [])

    def test_quote_boundaries_are_inclusive_balanced_and_line_local(self):
        cases = (
            ("物置に銀鈴がある。", "銀鈴", False),
            ("「外側「銀鈴」物置」", "「銀鈴」", True),
            ("「外側「銀鈴」物置」", "銀鈴」物置", True),
            ("前置き「銀鈴は物置」続き", "「銀鈴", True),
            ("前置き「銀鈴は物置」続き", "物置」", True),
            ("前置き「銀鈴は物置」続き", "「銀鈴は物置」", True),
            ("前置き「銀鈴は物置」続き", "物置」続き", False),
            ("前置き「銀鈴は物置」続き", "き「銀鈴", False),
            ("「銀鈴」「物置」", "銀鈴」「物置", False),
            ("「物置\n銀鈴」", "銀鈴", False),
            ("「物置\r銀鈴」", "銀鈴", False),
            ("「物置\r\n銀鈴」", "物置\r\n銀鈴", False),
            ("「銀鈴」\r\n物置", "銀鈴", True),
            ("「未完\r\n」「銀鈴」", "銀鈴", True),
            ("「物置", "物置", False),
            ("「物置」", "", False),
        )
        for text, span, expected in cases:
            with self.subTest(text=text, span=span):
                fixture = Synthetic(text)
                ref_id = fixture.evidence(span)
                fixture.records["evidence_refs"][1]["role"] = "IN_WORLD_REPORT"
                fixture.records["evidence_refs"][1]["span"]["char_start"] = 0
                fixture.claim("RefersTo", evidence=[ref_id])
                source_hash = fixture.records["evidence_refs"][1]["span"]["source_sha256"]
                report = checker.check_batch(fixture.batch, {source_hash: fixture.raw})
                self.assertEqual(report["counts"]["R-EVR-01"], int(expected))

    def test_optional_base_segment_bounds_limit_the_quote_context(self):
        fixture = Synthetic("前置き「銀鈴」後書き")
        ref_id = fixture.evidence("銀鈴")
        evidence = fixture.records["evidence_refs"][1]
        evidence["role"] = "IN_WORLD_REPORT"
        fixture.claim("RefersTo", evidence=[ref_id])
        locator = evidence["span"].copy()
        base = {"source_segments": [{"id": evidence["segment_id"], "locator": locator}]}
        self.assertEqual(checker.check_batch(fixture.batch, [fixture.raw], base)["counts"]["R-EVR-01"], 0)
        locator["byte_start"] += 1
        with self.assertRaises(ValueError):
            checker.check_batch(fixture.batch, [fixture.raw], base)

    def test_v1_report_is_preserved_with_a_dialogue_violation_in_the_same_batch(self):
        fixture = Synthetic("「銀鈴」")
        fixture.records["evidence_refs"][0]["role"] = "IN_WORLD_REPORT"
        fixture.claim("RefersTo")
        fixture.claim("TemporalRelation", relation=token("AFTER"))
        expected = fixture.check()
        report = checker.check_batch(fixture.batch, [fixture.raw])
        self.assertEqual(report["rules_checked"].pop(), "R-EVR-01")
        self.assertEqual(report["counts"].pop("R-EVR-01"), 1)
        self.assertEqual(report["findings"].pop(0)["rule"], "R-EVR-01")
        self.assertEqual(report, expected)

    def test_alignment_counts_distinct_refs_and_does_not_mutate_the_batch(self):
        fixture = Synthetic("「銀鈴は物置にある」")
        ref_id = fixture.evidence("銀鈴")
        fixture.records["evidence_refs"][1]["role"] = "IN_WORLD_REPORT"
        fixture.claim("RefersTo", evidence=[ref_id])
        fixture.claim("NamedAs", evidence=[ref_id], name=literal("銀鈴"))
        fixture.claim("RefersTo", evidence=[ref_id], polarity="OPEN")
        before = copy.deepcopy(fixture.batch)
        self.assertEqual(checker.check_batch(fixture.batch, [fixture.raw])["counts"]["R-EVR-01"], 2)

        aligned, report = checker.align_mention_roles(fixture.batch, [fixture.raw])
        self.assertEqual(report, {"flagged": 1, "aligned": 1, "refused_shared": 0,
                                  "by_from_role": {"IN_WORLD_REPORT": 1}})
        self.assertEqual(fixture.batch, before)
        expected = copy.deepcopy(before)
        expected["candidate_records"]["evidence_refs"][1]["role"] = "DEPICTION"
        self.assertEqual(aligned, expected)
        self.assertEqual(checker.check_batch(aligned, [fixture.raw])["counts"]["R-EVR-01"], 0)
        aligned["candidate_records"]["assertions"].clear()
        self.assertEqual(fixture.batch, before)

    def test_alignment_refuses_refs_shared_with_non_mentions_in_any_evidence_set(self):
        for bound_support in (False, True):
            with self.subTest(bound_support=bound_support):
                fixture = Synthetic("「銀鈴は物置にある」")
                shared_id = fixture.evidence("銀鈴")
                unshared_id = fixture.evidence("物置")
                fixture.records["evidence_refs"][1]["role"] = "IN_WORLD_REPORT"
                fixture.records["evidence_refs"][2]["role"] = "RETROSPECTIVE"
                fixture.claim("RefersTo", evidence=[shared_id, unshared_id])
                fixture.claim("LocatedAt", evidence=[shared_id], polarity="OPEN")
                other = fixture.records["assertions"][1]
                other["support"]["evidence_sets"][0]["label"] = "PARTIAL"
                if bound_support:
                    other["validity"] = {"end": {"support": other.pop("support")}}
                aligned, report = checker.align_mention_roles(fixture.batch, [fixture.raw])
                self.assertEqual(report, {"flagged": 2, "aligned": 1, "refused_shared": 1,
                                          "by_from_role": {"IN_WORLD_REPORT": 1, "RETROSPECTIVE": 1}})
                refs = aligned["candidate_records"]["evidence_refs"]
                self.assertEqual(refs[1]["role"], "IN_WORLD_REPORT")
                self.assertEqual(refs[2]["role"], "DEPICTION")
                self.assertEqual(checker.check_batch(aligned, [fixture.raw])["counts"]["R-EVR-01"], 1)

    def test_alignment_of_a_base_ref_redirects_candidate_citations(self):
        fixture = Synthetic("「銀鈴」")
        fixture.mention("銀鈴")
        fixture.claim("RefersTo", evidence=["ev-1"])
        evidence = fixture.records["evidence_refs"].pop()
        evidence["role"] = "IN_WORLD_REPORT"
        base = {"evidence_refs": [evidence], "entities": [{"id": "ev-r-evr-01-1"}],
                "propositions": fixture.records["propositions"][:]}
        fixture.records["propositions"].clear()
        before = copy.deepcopy(base)

        aligned, report = checker.align_mention_roles(fixture.batch, [fixture.raw], base)
        self.assertEqual(report, {"flagged": 1, "aligned": 1, "refused_shared": 0,
                                  "by_from_role": {"IN_WORLD_REPORT": 1}})
        records = aligned["candidate_records"]
        copied_ref = records["evidence_refs"][1]
        self.assertEqual(copied_ref, dict(evidence, id="ev-r-evr-01-2", role="DEPICTION"))
        self.assertEqual(records["mentions"][0]["evidence_ref_id"], copied_ref["id"])
        evidence_set = records["assertions"][0]["support"]["evidence_sets"][0]
        self.assertEqual(evidence_set["evidence_ref_ids"], [copied_ref["id"]])
        self.assertEqual(checker.check_batch(aligned, [fixture.raw], base)["findings"], [])
        self.assertEqual(base, before)

    def test_cli_reports_findings_and_refuses_unavailable_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch, source, base, out = (root / name for name in ("batch.json", "source.txt", "base.json", "out.json"))
            fixture = Synthetic("「銀鈴」")
            fixture.records["evidence_refs"][0]["role"] = "IN_WORLD_REPORT"
            fixture.claim("RefersTo")
            batch.write_text(json.dumps(fixture.batch), encoding="utf-8")
            source.write_bytes(fixture.raw)
            base.write_text("{}", encoding="utf-8")
            argv = ["--batch", str(batch), "--source", str(source)]
            expected = checker.check_batch(fixture.batch, [fixture.raw])
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(checker.main(argv), 0)
            self.assertEqual(json.loads(stdout.getvalue()), expected)
            self.assertEqual(stderr.getvalue(), "")

            file_args = [*argv, "--source", str(source), "--base", str(base), "--out", str(out)]
            with contextlib.redirect_stdout(io.StringIO()) as file_stdout:
                self.assertEqual(checker.main(file_args), 0)
            self.assertEqual(file_stdout.getvalue(), "")
            self.assertEqual(out.read_bytes(), stdout.getvalue().encode("utf-8"))
            process = subprocess.run(
                [sys.executable, "-B", "-X", "utf8", "-m", checker.__name__, *file_args],
                cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stdout, "")
            self.assertEqual(json.loads(out.read_bytes()), expected)

            with contextlib.redirect_stderr(io.StringIO()) as refusal:
                self.assertEqual(checker.main([*argv, "--source", str(root / "missing")]), 2)
            self.assertEqual(refusal.getvalue(), "error: refused input or inaccessible report destination\n")


if __name__ == "__main__":
    unittest.main()
