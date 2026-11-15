"""Synthetic, offline tests for tools/story_extraction/fresh_validation_seal_v1.py.

Cases come from the hand-authored synthetic graphs in fixture_builder.py; no private text,
gold or provider is involved.
"""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture_builder as fx  # noqa: E402

from tools.story_extraction import fresh_validation_seal_v1 as seal  # noqa: E402

SET_ID = "SYNTHETIC_FRESH_VALIDATION"
FAMILY = "SYNTHETIC_EN_FIXTURES"


def authored(case_id, fixture_name):
    """An AuthoredCase over one synthetic fixture graph."""
    text, annotate = fx.CASES[fixture_name]
    data = text.encode("utf-8")
    manifest = {"contract_version": "LIGHT_NOVEL_INGESTION/v0", "story_id": f"story-{case_id.lower()}",
                "stream_id": f"stream-{case_id.lower()}", "source_language": "en",
                "documents": [{"document_id": f"srcdoc-{case_id.lower()}", "order": 1,
                               "path": seal.SOURCE_MEMBER,
                               "expected_sha256": hashlib.sha256(data).hexdigest()}]}
    ingestion = seal.ingest_source(manifest, data)
    base = ingestion.canonical_skeleton()
    builder = fx.Builder(ingestion, base, prefix=case_id.lower())
    annotate(builder, "gold")
    batch = builder.batch()
    batch["scope"]["profile_id"] = seal.PROFILE_ID
    coverage = tuple({"segment": n, "note": "all in-profile facts annotated"}
                     for n in range(1, len(batch["scope"]["passage_inputs"]) + 1))
    return seal.AuthoredCase(case_id, fixture_name, manifest, data, base, batch, coverage, ingestion)


def cases():
    return [authored("SYN_01", "c02_two_mentions_one_entity"), authored("SYN_02", "c13_self_report"),
            authored("SYN_03", "c21_state_end_learned_later"), authored("SYN_04", "c24_partial_not_sufficient")]


class SealTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)

    def test_seal_is_deterministic_separates_gold_and_verifies(self):
        summary = seal.seal(cases(), self.out / "a", SET_ID, FAMILY, {"author.py": b"# authoring script\n"})
        again = seal.seal(cases(), self.out / "b", SET_ID, FAMILY, {"author.py": b"# authoring script\n"})
        self.assertEqual(summary, again)
        names = [f"{SET_ID}_INPUT.zip", f"{SET_ID}_GOLD.zip", f"{SET_ID}_BLINDNESS_MANIFEST.json"]
        for name in names:
            self.assertEqual((self.out / "a" / name).read_bytes(), (self.out / "b" / name).read_bytes(), name)

        self.assertEqual(summary["representational_gate"]["representable"], "4/4")
        self.assertEqual(summary["gold"]["cases"], 4)
        self.assertEqual(summary["gold"]["evidence_set_labels"]["PARTIAL"], 1)
        self.assertEqual(summary["gold"]["predicate_counts"]["Says"], 1)
        self.assertNotIn("Mira", json.dumps(summary))  # the public summary carries no source text

        with zipfile.ZipFile(self.out / "a" / names[0]) as bundle:
            input_names = set(bundle.namelist())
        with zipfile.ZipFile(self.out / "a" / names[1]) as bundle:
            gold_names = set(bundle.namelist())
        self.assertFalse(input_names & gold_names)
        self.assertIn("gold/authoring/author.py", gold_names)
        self.assertFalse([name for name in input_names if "gold" in name.lower()])

        report = seal.verify_sealed(self.out / "a", SET_ID)
        self.assertEqual(report, {"pass": True, "issues": [], "cases_representable": "4/4"})

    def test_input_package_gives_the_extractor_only_the_prepared_surface(self):
        seal.seal(cases(), self.out, SET_ID, FAMILY)
        loaded = seal.load_input_cases(self.out / f"{SET_ID}_INPUT.zip")
        self.assertEqual([item["case_id"] for item in loaded], ["SYN_01", "SYN_02", "SYN_03", "SYN_04"])
        prepared = loaded[0]["prepared_input"]
        self.assertEqual(prepared["draft_version"], "STORY_EXTRACTION_DRAFT_V1_1")
        self.assertEqual(set(prepared), {"draft_version", "passages", "existing_context"})
        self.assertEqual([p["use"] for p in prepared["passages"]], ["EVIDENCE_ELIGIBLE"] * 2)
        self.assertEqual(seal.gold_leaks({"x.json": prepared}), [])

    def test_problems_block_the_seal(self):
        def reviewed(items):
            items[0].gold_batch["candidate_records"]["assertions"][0]["review"] = {"state": "ACCEPTED"}

        def off_source(items):
            items[1].gold_batch["candidate_records"]["evidence_refs"][0]["span"]["char_end_exclusive"] += 400

        def wrong_profile(items):
            items[2].gold_batch["scope"]["profile_id"] = "other-profile"

        mutations = {
            "no cases": (lambda items: items.clear(), "at least one case"),
            "duplicate case id": (lambda items: items.append(items[0]), "unique"),
            "missing coverage note": (lambda items: items.__setitem__(
                0, copy.replace(items[0], line_coverage=items[0].line_coverage[:1])), "coverage notes"),
            "empty coverage note": (lambda items: items.__setitem__(
                0, copy.replace(items[0], line_coverage=tuple({**n, "note": " "} for n in items[0].line_coverage))),
                "empty coverage note"),
            "reviewed gold": (reviewed, "UNREVIEWED"),
            "gold off the source": (off_source, "GOLD_FAILS_FROZEN_VALIDATION"),
            "wrong profile": (wrong_profile, "profile is not"),
        }
        for label, (mutate, message) in mutations.items():
            with self.subTest(label):
                items = cases()
                mutate(items)
                with self.assertRaisesRegex(seal.FreshValidationError, message):
                    seal.seal(items, self.out / label.replace(" ", "_"), SET_ID, FAMILY)
                self.assertFalse((self.out / label.replace(" ", "_")).exists())  # nothing is written

    def test_unrepresentable_gold_is_reported_by_code(self):
        case = authored("SYN_05", "c05_event_occurred")
        case.gold_batch["candidate_records"]["propositions"][0]["predicate"] = "NotARegisteredPredicate"
        gate = seal.representational_gate(case)
        self.assertFalse(gate["representable"])
        self.assertEqual(gate["failure"], "GOLD_FAILS_FROZEN_VALIDATION")
        self.assertNotIn("oracle_draft", gate)

    def test_records_of_a_prior_base_document_are_reused_not_copied(self):
        """A case may build on records an earlier step put in the base document."""
        first = authored("SYN_06", "c21_state_end_learned_later")
        prior = fx.Builder(first.ingestion, first.base_document, prefix="prior")
        mira = prior.named(1, "Mira")
        prior_batch = prior.batch(as_of_segment=1)
        prior_batch["scope"]["profile_id"] = seal.PROFILE_ID
        base = seal.contract_merge(prior_batch, first.base_document)

        builder = fx.Builder(first.ingestion, base, prefix="syn06", context_only={1})
        give, _ = builder.event("TRANSFER")
        builder.occurred(give, 2, role="RETROSPECTIVE")
        builder.claim(builder.prop("Participates", event=fx.V(give), participant=fx.E(mira), role=fx.ROLE("SOURCE")),
                      [[builder.ev(2, role="RETROSPECTIVE")]])
        batch = builder.batch()
        batch["scope"]["profile_id"] = seal.PROFILE_ID
        case = copy.replace(first, base_document=base, gold_batch=batch,
                            line_coverage=({"segment": 2, "note": "the handover"},))
        self.assertEqual(seal.case_issues(case), [])
        gate = seal.representational_gate(case)
        self.assertTrue(gate["representable"], gate["failure"])
        self.assertIn("E_EXISTING_1", json.dumps(gate["oracle_draft"]))

        summary = seal.seal([case], self.out, SET_ID, FAMILY)
        self.assertEqual(summary["gold"]["predicate_counts"], {"Occurred": 1, "Participates": 1})
        prepared = seal.load_input_cases(self.out / f"{SET_ID}_INPUT.zip")[0]["prepared_input"]
        self.assertEqual([p["use"] for p in prepared["passages"]], ["CONTEXT_ONLY", "EVIDENCE_ELIGIBLE"])
        self.assertIn("E_EXISTING_1", prepared["existing_context"])
        self.assertTrue(seal.verify_sealed(self.out, SET_ID)["pass"])

    def test_changes_after_sealing_are_detected(self):
        seal.seal(cases(), self.out, SET_ID, FAMILY)
        gold = self.out / f"{SET_ID}_GOLD.zip"
        gold.write_bytes(gold.read_bytes() + b"\0")
        report = seal.verify_sealed(self.out, SET_ID)
        self.assertFalse(report["pass"])
        self.assertIn("gold package hash mismatch", report["issues"])

    def test_gold_in_an_input_package_is_refused(self):
        cases_with_leaks = {
            "gold key in a member": {"input_manifest.json": {"cases": [], "gold_batch": {}}},
            "gold-named member": {"input_manifest.json": {"cases": []}, "cases/X/gold_notes.json": {}},
            "nested gold key": {"input_manifest.json": {"cases": [{"line_coverage": []}]}},
        }
        for label, members in cases_with_leaks.items():
            with self.subTest(label):
                path = self.out / f"{label.replace(' ', '_')}.zip"
                with zipfile.ZipFile(path, "w") as bundle:
                    for name, value in members.items():
                        bundle.writestr(name, json.dumps(value))
                with self.assertRaisesRegex(seal.FreshValidationError, "gold found in the input package"):
                    seal.load_input_cases(path)

    def test_source_manifest_must_be_one_document(self):
        with self.assertRaisesRegex(seal.FreshValidationError, "exactly one document"):
            seal.ingest_source({"documents": [{"path": "a.txt"}, {"path": "b.txt"}]}, b"x")


if __name__ == "__main__":
    unittest.main()
