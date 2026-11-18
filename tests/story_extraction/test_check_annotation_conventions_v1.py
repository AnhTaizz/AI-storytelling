"""Behaviour tests for the conventions checker; all text and records are invented here."""

import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.story_extraction import check_annotation_conventions_v1 as checker


TEXT = "葵さんが赤い本を静かに渡した。蓮くんは喜んだ。の ABC 2026-11-17"
RAW = TEXT.encode("utf-8")
RULES = ("R-ROLE-01", "R-ROLE-02", "R-EVT-02", "R-MEN-01", "R-MEN-02",
         "R-LIT-01", "R-LIT-02", "R-LIT-04", "R-LIT-05", "R-TIME-02")


def ref(kind, identifier):
    return {"kind": kind, "ref": identifier}


def token(value):
    return {"kind": "TOKEN", "value": value}


def literal(value, value_type="STRING"):
    return {"kind": "LITERAL", "value_type": value_type, "value": value}


class Synthetic:
    """Minimal in-memory Japanese fixtures, independent of ingestion and private data."""

    def __init__(self, text=TEXT):
        self.raw = text.encode("utf-8")
        self.text = text
        self.records = {key: [] for key in (
            "assertions", "entities", "events", "evidence_refs", "mentions",
            "propositions", "temporal_anchors", "extraction_provenance")}
        self.batch = {"contract_version": "STORY_EXTRACTION_BATCH/v0", "candidate_records": self.records}
        self.evidence("葵さん" if text == TEXT else text)

    def evidence(self, text):
        start = self.text.index(text)
        byte_start = len(self.text[:start].encode("utf-8"))
        raw = text.encode("utf-8")
        identifier = f"ev-{len(self.records['evidence_refs'])}"
        self.records["evidence_refs"].append({
            "id": identifier, "segment_id": "seg-synthetic", "role": "DEPICTION",
            "span": {"kind": "TEXT_RANGE_V0", "source_sha256": hashlib.sha256(self.raw).hexdigest(),
                     "byte_start": byte_start, "byte_end_exclusive": byte_start + len(raw),
                     "char_start": start, "char_end_exclusive": start + len(text),
                     "span_text_sha256": hashlib.sha256(raw).hexdigest()}})
        return identifier

    def event(self, kind="GENERIC", identifier="evt-1"):
        self.records["events"].append({"id": identifier, "event_kind": kind, "anchor_id": "t-1"})
        return ref("EVENT", identifier)

    def claim(self, predicate, *, evidence=None, polarity="AFFIRMED", **args):
        number = len(self.records["assertions"])
        pid, aid = f"p-{number}", f"a-{number}"
        self.records["propositions"].append({"id": pid, "predicate": predicate, "args": args})
        self.records["assertions"].append({
            "id": aid, "proposition_id": pid, "polarity": polarity, "epistemic_status": "EXPLICIT",
            "support": {"derivations": [], "evidence_sets": [
                {"id": f"es-{number}", "label": "SUFFICIENT", "evidence_ref_ids": evidence or ["ev-0"]}]}})
        return ref("PROPOSITION", pid)

    def mention(self, text, surface=None):
        self.records["mentions"].append({"id": "m-1", "evidence_ref_id": self.evidence(text),
                                         "surface_form": text if surface is None else surface})

    def check(self, base=None):
        return checker.check_batch(self.batch, [self.raw], base)


def scenario(code, bad):
    fixture = Synthetic()
    if code == "MULTIPLE_ROLES":
        event = fixture.event()
        for role in ("AGENT", "THEME" if bad else "AGENT"):
            fixture.claim("Participates", event=event, participant=ref("ENTITY", "ent-1"), role=token(role))
    elif code in {"ROLE_NOT_IN_FRAME", "UNKNOWN_EVENT"}:
        event = ref("EVENT", "evt-1") if code == "UNKNOWN_EVENT" and bad else fixture.event("UTTERANCE")
        fixture.claim("Participates", event=event, participant=ref("ENTITY", "ent-1"),
                      role=token("PATIENT" if code == "ROLE_NOT_IN_FRAME" and bad else "AGENT"))
    elif code == "CONVEYS_ON_NON_REVEAL":
        fixture.claim("Conveys", event=fixture.event("GENERIC" if bad else "REVEAL_TELL"))
    elif code == "REVEAL_WITHOUT_CONVEYS":
        event = fixture.event("REVEAL_DISCOVER")
        fixture.claim("Occurred", event=event)
        if not bad:
            fixture.claim("Conveys", event=event)
    elif code == "SURFACE_FORM_MISMATCH":
        fixture.mention("葵さん", "別人" if bad else "葵さん")
    elif code == "HONORIFIC_OUTSIDE_SPAN":
        fixture.mention("葵" if bad else "葵さん")
    elif code == "TRAILING_PARTICLE":
        fixture.mention("葵さんが" if bad else "葵さん")
    elif code == "TRANSLATED_LITERAL":
        fixture.claim("NamedAs", name=literal("Aoi" if bad else "葵"))
    elif code == "NOT_VERBATIM":
        fixture.claim("PhysicalCondition", condition=literal("負傷" if bad else "葵"))
    elif code == "HONORIFIC_IN_NAME":
        fixture.claim("NamedAs", name=literal("葵さん" if bad else "葵"))
    elif code == "BAD_DATE_FORMAT":
        fixture.claim("AnchorDate", date=literal("明日" if bad else "2026-11", "DATE"))
    elif code == "AFTER_RELATION":
        fixture.claim("TemporalRelation", relation=token("AFTER" if bad else "BEFORE"))
    return fixture


class AnnotationConventionsTests(unittest.TestCase):
    def test_every_finding_code_has_a_violating_and_conforming_case(self):
        cases = {
            "MULTIPLE_ROLES": "R-ROLE-01", "ROLE_NOT_IN_FRAME": "R-ROLE-02",
            "UNKNOWN_EVENT": "R-ROLE-02", "CONVEYS_ON_NON_REVEAL": "R-EVT-02",
            "REVEAL_WITHOUT_CONVEYS": "R-EVT-02", "SURFACE_FORM_MISMATCH": "R-MEN-01",
            "HONORIFIC_OUTSIDE_SPAN": "R-MEN-02", "TRAILING_PARTICLE": "R-MEN-02",
            "TRANSLATED_LITERAL": "R-LIT-01", "NOT_VERBATIM": "R-LIT-02",
            "HONORIFIC_IN_NAME": "R-LIT-04", "BAD_DATE_FORMAT": "R-LIT-05",
            "AFTER_RELATION": "R-TIME-02"}
        for code, rule in cases.items():
            for bad in (False, True):
                with self.subTest(code=code, bad=bad):
                    report = scenario(code, bad).check()
                    matches = [f for f in report["findings"] if f["code"] == code]
                    self.assertEqual(len(matches), int(bad))
                    if bad:
                        expected_ids = (["a-0", "a-1"] if code == "MULTIPLE_ROLES" else
                                        ["evt-1"] if code == "REVEAL_WITHOUT_CONVEYS" else
                                        ["m-1"] if rule.startswith("R-MEN") else ["a-0", "p-0"])
                        self.assertEqual(matches, [{"rule": rule, "code": code, "record_ids": expected_ids}])
                    else:
                        self.assertEqual(report["findings"], [])
                    self.assertEqual(report["rules_checked"], list(RULES))
                    self.assertEqual(report["counts"], {
                        r: sum(f["rule"] == r for f in report["findings"]) for r in RULES})
                    for finding in report["findings"]:
                        self.assertEqual(set(finding), {"rule", "code", "record_ids"})

    def test_role_frames_cover_every_allowed_and_disallowed_role(self):
        frames = {
            "GENERIC": "AGENT PATIENT THEME EXPERIENCER RECIPIENT WITNESS",
            "TRANSFER": "SOURCE RECIPIENT THEME AGENT WITNESS",
            "UTTERANCE": "AGENT RECIPIENT WITNESS", "MOVEMENT": "AGENT THEME WITNESS",
            "ENCOUNTER": "AGENT THEME WITNESS", "ADDRESS_CHANGE": "AGENT RECIPIENT WITNESS",
            "REVEAL_TELL": "SOURCE RECIPIENT WITNESS", "REVEAL_DISCOVER": "RECIPIENT THEME WITNESS",
            "REVEAL_INFER": "RECIPIENT", "UNREGISTERED": ""}
        for kind, allowed in frames.items():
            for role in "AGENT PATIENT SOURCE RECIPIENT THEME EXPERIENCER WITNESS".split():
                with self.subTest(kind=kind, role=role):
                    fixture = Synthetic()
                    fixture.claim("Participates", event=fixture.event(kind),
                                  participant=ref("ENTITY", "ent-1"), role=token(role))
                    self.assertEqual(fixture.check()["counts"]["R-ROLE-02"], int(role not in allowed.split()))

    def test_base_supplies_lookups_but_is_never_audited(self):
        for override in (False, True):
            with self.subTest(override=override):
                fixture = scenario("ROLE_NOT_IN_FRAME", True)
                events = fixture.records["events"]
                fixture.records["events"] = events if override else []
                base = {"events": [{"id": "evt-1", "event_kind": "GENERIC"}],
                        "mentions": [{"id": "base-mention", "evidence_ref_id": "missing"}],
                        "assertions": [{"id": "base-assertion", "polarity": "AFFIRMED"}],
                        "propositions": [{"id": "base-p", "predicate": "NamedAs",
                                          "args": {"name": literal("Translatedさん")}}],
                        "evidence_refs": [{"id": "unused-base-evidence"}]}
                self.assertEqual(fixture.check(base)["counts"]["R-ROLE-02"], int(override))
        fixture = Synthetic()
        fixture.mention("葵さん")
        base = {"evidence_refs": fixture.records.pop("evidence_refs")}
        self.assertEqual(fixture.check(base)["findings"], [])
        fixture = scenario("NOT_VERBATIM", False)
        base = {"propositions": fixture.records.pop("propositions")}
        self.assertEqual(fixture.check(base)["checked"]["string_literals"], 0)

    def test_only_affirmed_batch_assertions_affect_rules_and_counts(self):
        for polarity in ("NEGATED", "OPEN", None):
            with self.subTest(polarity=polarity):
                fixture = scenario("MULTIPLE_ROLES", True)
                fixture.records["assertions"][1]["polarity"] = polarity
                fixture.claim("NamedAs", name=literal("Translatedさん"), polarity=polarity)
                fixture.claim("AnchorDate", date=literal("明日", "DATE"), polarity=polarity)
                fixture.claim("TemporalRelation", relation=token("AFTER"), polarity=polarity)
                self.assertEqual(fixture.check()["findings"], [])
                self.assertEqual(fixture.check()["checked"], {"assertions": 1, "mentions": 0,
                                 "string_literals": 0, "date_literals": 0, "participates": 1})
        fixture = scenario("REVEAL_WITHOUT_CONVEYS", True)
        fixture.claim("Conveys", event=ref("EVENT", "evt-1"), polarity="NEGATED")
        base = {"assertions": [dict(fixture.records["assertions"][-1], polarity="AFFIRMED")]}
        self.assertEqual(fixture.check(base)["counts"]["R-EVT-02"], 1)
        fixture.records["assertions"][0]["polarity"] = "OPEN"
        self.assertEqual(fixture.check(base)["findings"], [])
        fixture.records["events"] = []
        fixture.records["assertions"][0]["polarity"] = "AFFIRMED"
        self.assertEqual(fixture.check({"events": [{"id": "evt-1", "event_kind": "REVEAL_INFER"}]})[
            "findings"], [])

    def test_literal_evidence_is_pooled_over_the_assertions_of_a_proposition(self):
        cases = [
            ("葵", ["葵さん"], "SUFFICIENT", set()),
            ("葵さんが", ["葵さん", "が"], "SUFFICIENT", {"NOT_VERBATIM"}),
            ("ABC", ["葵さん", "ABC"], "SUFFICIENT", set()),
            ("Aoi", ["葵さん", "ABC"], "SUFFICIENT", {"NOT_VERBATIM"}),
            ("ABC", ["ABC"], "PARTIAL", {"TRANSLATED_LITERAL", "NOT_VERBATIM"}),
            ("葵", ["葵さん"], "PARTIAL", {"NOT_VERBATIM"})]
        for value, spans, label, codes in cases:
            with self.subTest(value=value, spans=spans, label=label):
                fixture = Synthetic()
                fixture.claim("UnregisteredPredicate", evidence=[fixture.evidence(s) for s in spans],
                              any_argument=literal(value), ignored=literal("unused", "INTEGER"), tok=token("ABC"))
                fixture.records["assertions"][0]["support"]["evidence_sets"][0]["label"] = label
                report = fixture.check()
                self.assertEqual({f["code"] for f in report["findings"]}, codes)
                self.assertEqual(report["checked"]["string_literals"], 1)
        # R-LIT-02 asks for the literal in at least one SUFFICIENT span of the proposition's
        # assertions: a second assertion with other evidence, or with none at all (a SUGGESTED
        # assertion), does not make it a finding; when no assertion carries it, every
        # assertion that reaches the proposition is named.
        for other_evidence, expected in (
                (["ev-0"], []), ([], []),
                (None, [{"rule": "R-LIT-02", "code": "NOT_VERBATIM", "record_ids": ["a-0", "a-other", "p-0"]}])):
            with self.subTest(other_evidence=other_evidence):
                fixture = Synthetic()
                fixture.claim("Manner", manner=literal("静かに"), evidence=[fixture.evidence("静かに")])
                other = copy.deepcopy(fixture.records["assertions"][0])
                other["id"] = "a-other"
                if other_evidence is None:
                    fixture.records["assertions"][0]["support"]["evidence_sets"][0]["evidence_ref_ids"] = ["ev-0"]
                    other["support"]["evidence_sets"][0]["evidence_ref_ids"] = ["ev-0"]
                elif other_evidence:
                    other["support"]["evidence_sets"][0]["evidence_ref_ids"] = other_evidence
                else:
                    other["support"]["evidence_sets"] = []
                fixture.records["assertions"].append(other)
                report = fixture.check()
                self.assertEqual(report["findings"], expected)
                self.assertEqual(report["checked"]["string_literals"], 1)

    def test_nested_literals_use_outer_evidence_and_guard_cycles(self):
        for value in ("葵", "別人", "Aoi"):
            with self.subTest(value=value):
                fixture = Synthetic()
                fixture.claim("Says", content=ref("PROPOSITION", "inner"),
                              duplicate_path=ref("PROPOSITION", "inner"))
                fixture.records["propositions"].extend([
                    {"id": "inner", "predicate": "Intends", "args": {"content": ref("PROPOSITION", "leaf")}},
                    {"id": "leaf", "predicate": "NamedAs", "args": {
                        "name": literal(value), "cycle": ref("PROPOSITION", "p-0")}}])
                report = fixture.check()
                expected = [] if value == "葵" else ["NOT_VERBATIM"]
                if value == "Aoi":
                    expected += ["TRANSLATED_LITERAL"]
                self.assertEqual(sorted(f["code"] for f in report["findings"]), sorted(expected))
                self.assertTrue(all(f["record_ids"] == ["a-0", "leaf"] for f in report["findings"]))
                self.assertEqual(report["checked"]["string_literals"], 1)

    def test_suffix_and_date_boundaries_are_literal_mechanical_checks(self):
        honorifics = ("さん", "くん", "君", "ちゃん", "様", "さま", "先輩", "先生", "殿", "氏")
        for suffix in honorifics:
            for included in (False, True):
                with self.subTest(suffix=suffix, included=included):
                    fixture = Synthetic("葵" + suffix + "が歩いた。")
                    fixture.mention("葵" + suffix if included else "葵")
                    fixture.claim("NamedAs", name=literal("葵" + suffix))
                    report = fixture.check()
                    self.assertEqual(report["counts"]["R-MEN-02"], int(not included))
                    self.assertEqual(report["counts"]["R-LIT-04"], 1)
        for particle in ("は", "が", "を", "に", "へ", "と", "で", "も", "の", "から", "まで", "より"):
            for prefix in ("", "葵"):
                with self.subTest(particle=particle, prefix=prefix):
                    fixture = Synthetic(prefix + particle)
                    fixture.mention(prefix + particle)
                    self.assertEqual(fixture.check()["counts"]["R-MEN-02"], int(bool(prefix)))
        for value, valid in (("2026-11-17", True), ("2026-11", True), ("--11-17", True),
                             ("9999-99-99", True), ("2026-1-1", False), ("2026", False),
                             ("2026-11-17\n", False), (" 2026-11", False), ("明日", False)):
            with self.subTest(date=value):
                fixture = Synthetic()
                fixture.claim("AnchorDate", date=literal(value, "DATE"))
                self.assertEqual(fixture.check()["counts"]["R-LIT-05"], int(not valid))

    def test_unverifiable_spans_and_broken_references_are_refused(self):
        for failure in ("missing-source", "hash", "source-key", "raw-type", "range", "offset-type",
                        "kind", "utf8", "missing-evidence", "missing-proposition", "nested-reference"):
            with self.subTest(failure=failure):
                fixture = Synthetic()
                sources = [fixture.raw]
                span = fixture.records["evidence_refs"][0]["span"]
                if failure == "missing-source":
                    sources = []
                elif failure == "hash":
                    span["span_text_sha256"] = "0" * 64
                elif failure == "source-key":
                    sources = {"incorrect-key": fixture.raw}
                elif failure == "raw-type":
                    sources = [TEXT]
                elif failure == "range":
                    span["byte_start"] = -1
                elif failure == "offset-type":
                    span["byte_start"] = True
                elif failure == "kind":
                    span["kind"] = "OTHER"
                elif failure == "utf8":
                    fixture.raw = b"\xff"
                    span.update(source_sha256=hashlib.sha256(fixture.raw).hexdigest(), byte_start=0,
                                byte_end_exclusive=1, span_text_sha256=hashlib.sha256(fixture.raw).hexdigest())
                    sources = [fixture.raw]
                elif failure == "missing-evidence":
                    fixture.mention("葵さん")
                    fixture.records["mentions"][0]["evidence_ref_id"] = "missing"
                elif failure == "missing-proposition":
                    fixture.claim("Occurred", event=fixture.event())
                    fixture.records["propositions"] = []
                else:
                    fixture.claim("Says", content=ref("PROPOSITION", "missing"))
                with self.assertRaises(ValueError):
                    checker.check_batch(fixture.batch, sources)
        for batch, base in (([], None), ({"candidate_records": []}, None), ({}, []),
                            ({"candidate_records": {"events": {}}}, None),
                            ({"candidate_records": {"events": [{}]}}, None),
                            ({"candidate_records": {"events": [{"id": "x"}, {"id": "x"}]}}, None)):
            with self.subTest(batch=batch, base=base), self.assertRaises(ValueError):
                checker.check_batch(batch, [], base)
        fixture = Synthetic()
        fixture.claim("NamedAs", name=literal(123))
        with self.assertRaises(ValueError):
            fixture.check()

    def test_report_is_deterministic_sorted_and_does_not_mutate_inputs(self):
        fixture = scenario("MULTIPLE_ROLES", True)
        fixture.claim("NamedAs", name=literal("Translatedさん"), extra=literal("Another"))
        fixture.mention("葵")
        fixture.claim("AnchorDate", date=literal("明日", "DATE"))
        before = copy.deepcopy(fixture.batch)
        reports = [fixture.check(), fixture.check()]
        self.assertEqual(fixture.batch, before)
        for rows in fixture.records.values():
            rows.reverse()
        reports.append(checker.check_batch(fixture.batch, {hashlib.sha256(RAW).hexdigest(): RAW}))
        reports.append(checker.check_batch(fixture.batch, iter([RAW, b"unused source"])))
        encoded = [json.dumps(report, sort_keys=True, ensure_ascii=False) for report in reports]
        self.assertTrue(all(output == encoded[0] for output in encoded))
        findings = reports[0]["findings"]
        self.assertEqual(findings, sorted(findings, key=lambda f: (f["rule"], f["code"], f["record_ids"])))
        self.assertNotIn("Translated", encoded[0])
        self.assertNotIn("葵", encoded[0])
        self.assertEqual(reports[0]["checked"], {"assertions": 4, "mentions": 1,
                         "string_literals": 2, "date_literals": 1, "participates": 2})
        empty = checker.check_batch({}, [])
        self.assertEqual(empty["findings"], [])
        self.assertEqual(empty["counts"], dict.fromkeys(RULES, 0))
        self.assertEqual(empty["checked"], dict.fromkeys(reports[0]["checked"], 0))

    def test_cli_output_and_refusal_are_safe_and_have_documented_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = scenario("HONORIFIC_IN_NAME", True)
            batch, source, base, out = (root / name for name in ("batch.json", "source.txt", "base.json", "out.json"))
            batch.write_text(json.dumps(fixture.batch, ensure_ascii=False), encoding="utf-8")
            source.write_bytes(fixture.raw)
            base.write_text("{}", encoding="utf-8")
            argv = ["--batch", str(batch), "--source", str(source)]
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(checker.main(argv), 0)
            self.assertEqual(json.loads(stdout.getvalue()), fixture.check())
            self.assertEqual(stderr.getvalue(), "")
            process = subprocess.run(
                [sys.executable, "-m", "tools.story_extraction.check_annotation_conventions_v1",
                 *argv, "--source", str(source), "--base", str(base), "--out", str(out)],
                cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True,
                env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"))
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stdout, "")
            self.assertEqual(out.read_text(encoding="utf-8"), stdout.getvalue())
            for failure in ("missing-file", "bad-json", "unverified", "out-directory"):
                with self.subTest(failure=failure):
                    batch.write_text(json.dumps(fixture.batch), encoding="utf-8")
                    args = argv[:]
                    if failure == "missing-file":
                        args[1] = str(root / "missing")
                    elif failure == "bad-json":
                        batch.write_text("private literal is not JSON", encoding="utf-8")
                    elif failure == "unverified":
                        source.write_bytes(b"different source")
                    else:
                        source.write_bytes(fixture.raw)
                        args += ["--out", str(root)]
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        self.assertEqual(checker.main(args), 2)
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertEqual(stderr.getvalue(), "error: refused input or inaccessible report destination\n")


if __name__ == "__main__":
    unittest.main()
