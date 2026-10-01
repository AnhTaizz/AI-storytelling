"""Freeze integrity checks for LIGHT_NOVEL_INGESTION/v0.

Deterministic. No private corpus, model, API or network.
"""
import hashlib
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import yaml  # noqa: E402

from tools.story_ingestion import light_novel_adapter_v0 as adapter  # noqa: E402

RECORD = REPO / "benchmarks/m3_ingestion/LIGHT_NOVEL_INGESTION_V0_FROZEN.yaml"
CONTRACT = REPO / "docs/research/m3/M3_LIGHT_NOVEL_INGESTION_CONTRACT_V0.md"
DECISIONS = REPO / "docs/DECISIONS.md"
GROUPS = ("normative_contract_artifacts", "validated_reference_implementation", "public_validation_evidence")


def blob_sha256(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


class TestIngestionFreeze(unittest.TestCase):
    def setUp(self):
        self.record = yaml.safe_load(RECORD.read_text(encoding="utf-8"))
        self.contract = CONTRACT.read_text(encoding="utf-8")

    def test_identity(self):
        r = self.record
        self.assertEqual(r["freeze_status"], "FROZEN")
        self.assertEqual((r["contract_version"], r["segmentation_version"], r["locator_kind"], r["passage_ref_kind"]),
                         (adapter.CONTRACT_VERSION, adapter.SEGMENTATION_VERSION, adapter.LOCATOR_KIND,
                          adapter.PASSAGE_REF_KIND))
        self.assertEqual(r["canonical_dependency"]["schema"], adapter.CANONICAL_SCHEMA_VERSION)
        self.assertEqual(r["canonical_dependency"]["registry"], "predicate_registry/v0.1")
        self.assertEqual(r["validated_reference_implementation"]["identity"], adapter.ADAPTER_VERSION)

    def test_bound_hashes_match(self):
        for group in GROUPS:
            for name, entry in self.record[group]["artifacts"].items():
                path = REPO / entry["path"]
                self.assertTrue(path.is_file(), entry["path"])
                self.assertEqual(blob_sha256(path), entry["sha256"], name)

    def test_normative_and_reference_are_distinct(self):
        normative = {e["path"] for e in self.record["normative_contract_artifacts"]["artifacts"].values()}
        reference = {e["path"] for e in self.record["validated_reference_implementation"]["artifacts"].values()}
        self.assertEqual(normative, {"docs/research/m3/M3_LIGHT_NOVEL_INGESTION_CONTRACT_V0.md",
                                     "schemas/light_novel_ingestion/light_novel_source_manifest_v0.schema.json"})
        self.assertEqual(reference, {"tools/story_ingestion/light_novel_adapter_v0.py"})
        self.assertFalse(normative & reference)
        self.assertIn("## 19. Normative Artifacts and Reference Implementation", self.contract)

    def test_reference_adapter_is_the_validated_one(self):
        validated = yaml.safe_load((REPO / "benchmarks/m3_ingestion/M3_02_PRIVATE_CORPUS_VALIDATION_RESULT.yaml")
                                   .read_text(encoding="utf-8"))["baseline_under_test"]["adapter_sha256"]
        self.assertEqual(blob_sha256(REPO / "tools/story_ingestion/light_novel_adapter_v0.py"), validated)
        self.assertEqual(self.record["changes_at_freeze"]["reference_adapter"], "none")

    def test_contract_states_frozen_clarifications(self):
        self.assertIn("**FROZEN / ACCEPTED**", self.contract)
        for text in ("### 7.1 SourceSegment semantic boundary", "### 7.2 Mixed-content segments",
                     "### 7.3 Granularity rule", "**Evidence-role rule (normative).**", "## 20. Evolution Rules",
                     "An `EvidenceRole` is assigned to the exact `EvidenceRef` span."):
            self.assertIn(text, self.contract)

    def test_accepted_issue_and_limitations(self):
        issue = self.record["accepted_issues"][0]
        self.assertEqual((issue["id"], issue["classification"], issue["orchestrator_decision"]),
                         ("I-01", "KNOWN_LIMITATION / NON_BLOCKING", "ACCEPTED FOR V0"))
        self.assertGreaterEqual(len(self.record["known_limitations"]), 13)
        self.assertFalse(self.record["m4_started"])

    def test_empirical_basis(self):
        real = self.record["empirical_basis"]["private_real_source"]
        self.assertEqual((real["source_documents"], real["source_segments"], real["historical_retrieval_chunks"],
                          real["untraceable"]), (30, 1519, 97, 0))

    def test_decision_record(self):
        text = DECISIONS.read_text(encoding="utf-8")
        section = text.split("## DEC-018 — Light Novel Ingestion Contract v0 Freeze")[1].split("\n## ")[0]
        self.assertIn("STATUS: ACCEPTED", section)
        self.assertIn("LIGHT_NOVEL_INGESTION_V0_FROZEN.yaml", section)
        self.assertEqual(text.count("## DEC-018"), 1)

    def test_mixed_content_segment_supports_role_specific_sub_spans(self):
        # Category-level illustration of the frozen rule, on synthetic text.
        import tempfile
        data = b"Heading line\nStory line.\nAuthor note line\n"
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "u.txt").write_bytes(data)
            manifest = {"contract_version": "LIGHT_NOVEL_INGESTION/v0", "story_id": "story-syn-fz",
                        "stream_id": "stream-syn-fz", "source_language": "en",
                        "documents": [{"document_id": "srcdoc-syn-fz", "order": 1, "path": "u.txt",
                                       "expected_sha256": hashlib.sha256(data).hexdigest()}]}
            result = adapter.ingest(manifest, Path(tmp))
            self.assertEqual(len(result.documents[0].segments), 1)          # one mixed-content segment
            segment = result.documents[0].segments[0]
            text = result.segment_text(segment["id"])
            story = result.passage_ref(segment["id"], text.index("Story"), text.index("Story") + len("Story line."))
            note = result.passage_ref(segment["id"], text.index("Author"), len(text))
            self.assertEqual(result.resolve_passage_text(story), "Story line.")
            refs = [adapter.materialize_evidence_ref(story, "DEPICTION", "ev-syn-fz-1"),
                    adapter.materialize_evidence_ref(note, "PARATEXT", "ev-syn-fz-2")]
            self.assertEqual({r["segment_id"] for r in refs}, {segment["id"]})
            self.assertEqual([r["role"] for r in refs], ["DEPICTION", "PARATEXT"])


if __name__ == "__main__":
    unittest.main()
