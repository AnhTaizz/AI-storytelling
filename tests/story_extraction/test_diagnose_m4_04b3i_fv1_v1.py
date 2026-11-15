"""Offline tests for tools/story_extraction/diagnose_m4_04b3i_fv1_v1.py (synthetic batches only).

One synthetic case holds every kind of difference the FV1 diagnosis found: a name never
asserted, a role label, an event whose kind differs, a narrower mention, a missed event and
predictions with and without gold on their evidence. The rebuilt matching is checked
against the frozen evaluator on the same input.
"""
import json
import sys
import tempfile
import contextlib
import io
import unittest
from pathlib import Path
from unittest import mock
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture_builder as fx  # noqa: E402

from tools.story_extraction import diagnose_m4_04b3i_fv1_v1 as diag  # noqa: E402
from tools.story_extraction import evaluate_extraction_v0 as frozen  # noqa: E402

TEXT = "Mara gave the old key to Tomas.\n\nThe lantern shook in the night.\n\nTomas walked home.\n\nRain fell.\n"
OPEN = {"start": {"kind": "OPEN"}, "end": {"kind": "OPEN"}}
SPEC = {"mode": "REAL_SOURCE", "gold_completeness": "COMPLETE_FOR_PROFILE"}


def build(prefix):
    ingestion, base = fx.ingest_text(TEXT)
    b = fx.Builder(ingestion, base, prefix=prefix)
    gold = prefix == "g"
    mara = b.named(1, "Mara")
    key = b.named(1, "the old key" if gold else "old key", kind="OBJECT")
    tomas = b.named(1, "Tomas")
    if gold:  # the extractor never asserts the name
        b.claim(b.prop("NamedAs", entity=fx.E(mara), name=fx.S("Mara"), name_kind=fx.TOK("name_kind", "GIVEN")),
                [[b.ev(1, "Mara")]], validity=OPEN)
    give, _ = b.event("TRANSFER")
    b.occurred(give, 1)
    for who, role in ((mara, "SOURCE" if gold else "AGENT"), (key, "THEME"), (tomas, "RECIPIENT")):
        b.claim(b.prop("Participates", event=fx.V(give), participant=fx.E(who), role=fx.ROLE(role)), [[b.ev(1)]])
    shake, _ = b.event("GENERIC" if gold else "ENCOUNTER")  # a kind the other side does not use
    b.occurred(shake, 2)
    if gold:
        walk, _ = b.event("MOVEMENT")
        b.occurred(walk, 3)  # the extractor says nothing about this passage
    else:
        rain, _ = b.event("GENERIC")
        b.occurred(rain, 4)  # no gold on this evidence
        b.claim(b.prop("Possesses", holder=fx.E(tomas), item=fx.E(key)), [[b.ev(1)]], validity=OPEN)
    return ingestion, base, b.batch()


class DiagnosisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ingestion, cls.base, cls.gold = build("g")
        _, _, cls.pred = build("p")
        cls.diagnosis = diag.case_diagnosis(cls.base, cls.gold, cls.pred)

    def test_every_item_gets_its_class_and_cause(self):
        missed = {(m["predicate"], m["class"], m["cause"]) for m in self.diagnosis["missed"]}
        self.assertEqual(missed, {
            ("NamedAs", "OTHER_PREDICATE", "NAMING_NOT_EMITTED"),
            ("Participates", "VALUE_MISMATCH", "ROLE_LABEL"),
            ("Occurred", "REFERENT_MISMATCH", "EVENT_NOT_ALIGNED"),
            ("Occurred", "NOT_EXTRACTED", "OTHER_OMISSION"),
        })
        unsupported = sorted((u["predicate"], u["class"]) for u in self.diagnosis["unsupported"])
        self.assertEqual(unsupported, [("Occurred", "NO_GOLD_ON_EVIDENCE"), ("Occurred", "PAIRED_WITH_MISS"),
                                       ("Participates", "PAIRED_WITH_MISS"), ("Possesses", "ON_GOLD_EVIDENCE"),
                                       ("RefersTo", "PAIRED_WITH_MISSED_RESOLUTION")])
        self.assertEqual([r["class"] for r in self.diagnosis["missed_resolutions"]], ["MENTION_SPAN_DIFFERS"])

    def test_the_rebuilt_matching_reproduces_the_frozen_evaluator(self):
        evaluation = frozen.evaluate_case(self.base, self.gold, self.pred, ingestion=self.ingestion, case_spec=SPEC)
        diag.check_reproduction("SYN", self.diagnosis, evaluation)  # does not raise
        broken = dict(self.diagnosis, missed=self.diagnosis["missed"][1:])
        with self.assertRaises(diag.DiagnosisError):
            diag.check_reproduction("SYN", broken, evaluation)

    def test_cause_rules(self):
        literal = {"emotion": ("LITERAL", '["STRING", "恐れ"]')}
        cases = [
            ("unaligned event", ("Participates", "REFERENT_MISMATCH", ["event"], {"event": ("EVENT", '"e1"')},
                                 {"event": ("EVENT", '"?p-EVT2"')}, False), "EVENT_NOT_ALIGNED"),
            ("literal wording", ("EmotionToward", "VALUE_MISMATCH", ["emotion"], literal,
                                 {"emotion": ("LITERAL", '["STRING", "fear"]')}, False), "LITERAL_WORDING"),
            ("another participant", ("Participates", "REFERENT_MISMATCH", ["participant", "role"],
                                     {"participant": ("ENTITY", '"g2"'), "role": ("TOKEN", '"x"')},
                                     {"participant": ("ENTITY", '"g1"'), "role": ("TOKEN", '"y"')}, True),
             "MISSING_PARTICIPANT"),
            ("temporal", ("AnchorDate", "OTHER_PREDICATE", [], {}, {}, False), "TEMPORAL_STRUCTURE"),
            ("other", ("Owns", "NOT_EXTRACTED", [], {}, {}, False), "OTHER_OMISSION"),
        ]
        for label, args, expected in cases:
            with self.subTest(label):
                self.assertEqual(diag.miss_cause(*args), expected)

    def test_public_record_holds_counts_only(self):
        adjudications = {u["content_key"]: {"state": "UNSUPPORTED_ASSERTION", "severity": "LOW"}
                         for u in self.diagnosis["unsupported"][:2]}
        adjudications["k"] = {"state": "EQUIVALENT_REPRESENTATION"}
        record = diag.public_record({"SYN": self.diagnosis}, adjudications)
        self.assertEqual(sum(record["missed_by_class"].values()), 4)
        self.assertEqual(record["missed_by_cause"]["NAMING_NOT_EMITTED"], 1)
        self.assertEqual(record["adjudication"], {"states": {"UNSUPPORTED_ASSERTION": 2, "EQUIVALENT_REPRESENTATION": 1},
                                                  "unsupported_severity": {"LOW": 2}})
        text = json.dumps(record, ensure_ascii=False)
        self.assertNotIn("Mara", text)  # no source text or signatures in the public record
        self.assertNotIn("content_key", text)

    def test_diagnose_reads_the_private_files_and_checks_each_case(self):
        from tools.story_extraction import score_m4_04b3h_fv1_v1 as scoring
        evaluation = frozen.evaluate_case(self.base, self.gold, self.pred, ingestion=self.ingestion, case_spec=SPEC)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "fv1").mkdir()
            with ZipFile(root / "fv1" / scoring.GOLD_NAME, "w") as archive:
                archive.writestr("gold_manifest.json", json.dumps({"cases": [
                    {"case_id": "FV1_01", "gold_batch_member": "g/FV1_01.json", "gold_completeness": "COMPLETE_FOR_PROFILE"}]}))
                archive.writestr("g/FV1_01.json", json.dumps(self.gold))
            compiled = root / "pred" / "artifacts" / "compiled"
            compiled.mkdir(parents=True)
            (compiled / "FV1_01.json").write_text(json.dumps(self.pred), encoding="utf-8")
            (root / "score").mkdir()
            rows = [{"case_id": "FV1_01", "terminal_status": "STRUCTURAL_VALID", "evaluation": evaluation},
                    {"case_id": "FV1_03", "terminal_status": "STRUCTURAL_FAILURE", "evaluation": {}}]
            (root / "score" / f"{scoring.EVALUATION_ID}.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
            cases = diag.diagnose(root / "fv1", root / "pred", root / "score", root / "out",
                                  load_cases=lambda path: [{"case_id": "FV1_01", "base_document": self.base}])
            self.assertEqual(list(cases), ["FV1_01"])  # the structural failure has nothing to diagnose
            self.assertTrue((root / "out" / "M4_04B3I_FV1_DIAGNOSIS_ITEMS_V1.json").is_file())
            args = ["--fv1-directory", "a", "--prediction-directory", "b", "--scoring-directory", "c",
                    "--output-directory", "d"]
            with mock.patch.object(diag, "diagnose", side_effect=diag.DiagnosisError("boom")), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(diag.main(args), 1)
            adjudications = root / "adjudications.json"
            adjudications.write_text(json.dumps({"k": {"state": "OUT_OF_SCOPE_ASSERTION"}}), encoding="utf-8")
            printed = io.StringIO()
            with mock.patch.object(diag, "diagnose", return_value={"SYN": self.diagnosis}), \
                    contextlib.redirect_stdout(printed):
                self.assertEqual(diag.main(args + ["--adjudications", str(adjudications)]), 0)
            self.assertEqual(json.loads(printed.getvalue())["adjudication"]["states"], {"OUT_OF_SCOPE_ASSERTION": 1})


if __name__ == "__main__":
    unittest.main()
