"""
Unit tests for INDEPENDENT_VALIDATION_FIXTURE_V1 validator (TASK M1-30CH-P)
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from tools.story_benchmark.validate_independent_validation_fixture_v1 import (
    CATEGORIES,
    EXPECTED_PER_CATEGORY,
    EXPECTED_PROBE_COUNT,
    find_privacy_leaks_in_manifest,
    validate_prefreeze_correction_deliverables,
    validate_review_artifact_bundle,
    validate_review_gate_deliverables,
    validate_source_gold_audit_and_partitions,
    validate_validation_probes,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestIndependentValidationFixtureValidator(unittest.TestCase):

    def setUp(self):
        self.probes_path = REPO_ROOT / ".local/story_integration/otonari_30ch/INDEPENDENT_VALIDATION_FIXTURE_V1/draft_probes.yaml"
        self.chunks_path = REPO_ROOT / ".local/story_integration/otonari_30ch/PARAGRAPH_PACK_V1/chunks.jsonl"
        self.orig_path = REPO_ROOT / ".local/story_integration/otonari_30ch/LONG_RANGE_PROBE_V1/probes.yaml"

    def test_real_draft_probes_validation_passes(self):
        res = validate_validation_probes(self.probes_path, self.chunks_path, self.orig_path)
        self.assertTrue(res["pass"], f"Validation failed with issues: {res.get('issues')}")
        m = res["metrics"]
        self.assertEqual(m["probe_count"], EXPECTED_PROBE_COUNT)
        for cat in CATEGORIES:
            self.assertEqual(m["per_category_counts"][cat], EXPECTED_PER_CATEGORY)
        self.assertEqual(m["annotation_status_counts"]["PENDING_REVIEW"], EXPECTED_PROBE_COUNT)
        self.assertEqual(m["multi_chunk_probe_count"], EXPECTED_PROBE_COUNT)

    def test_category_count_mismatch(self):
        with open(self.probes_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Remove 1 probe from CHRONOLOGY
        probes = [p for p in data["probes"] if p["probe_id"] != "V_CHRONO_01"]
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml", encoding="utf-8") as tf:
            yaml.dump({"probes": probes}, tf)
            tmp_path = Path(tf.name)

        try:
            res = validate_validation_probes(tmp_path, self.chunks_path, self.orig_path)
            self.assertFalse(res["pass"])
            self.assertTrue(any("Expected 25 probes" in issue for issue in res["issues"]))
            self.assertTrue(any("Category CHRONOLOGY has 4 probes" in issue for issue in res["issues"]))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_invalid_category(self):
        with open(self.probes_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        probes = copy.deepcopy(data["probes"])
        probes[0]["category"] = "INVALID_CATEGORY"
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml", encoding="utf-8") as tf:
            yaml.dump({"probes": probes}, tf)
            tmp_path = Path(tf.name)

        try:
            res = validate_validation_probes(tmp_path, self.chunks_path, self.orig_path)
            self.assertFalse(res["pass"])
            self.assertTrue(any("Invalid category" in issue for issue in res["issues"]))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_missing_annotation_status(self):
        with open(self.probes_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        probes = copy.deepcopy(data["probes"])
        del probes[0]["annotation_status"]
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml", encoding="utf-8") as tf:
            yaml.dump({"probes": probes}, tf)
            tmp_path = Path(tf.name)

        try:
            res = validate_validation_probes(tmp_path, self.chunks_path, self.orig_path)
            self.assertFalse(res["pass"])
            self.assertTrue(any("Missing annotation_status" in issue for issue in res["issues"]))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_spoiler_boundary_cutoff_violation(self):
        with open(self.probes_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        probes = copy.deepcopy(data["probes"])
        for p in probes:
            if p["category"] == "SPOILER_BOUNDARY":
                p["cutoff_chapter"] = 30
                break

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml", encoding="utf-8") as tf:
            yaml.dump({"probes": probes}, tf)
            tmp_path = Path(tf.name)

        try:
            res = validate_validation_probes(tmp_path, self.chunks_path, self.orig_path)
            self.assertFalse(res["pass"])
            self.assertTrue(any("SPOILER_BOUNDARY probe must have cutoff_chapter < 30" in issue for issue in res["issues"]))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_fewer_than_two_chunks(self):
        with open(self.probes_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        probes = copy.deepcopy(data["probes"])
        probes[0]["required_evidence_chunk_ids"] = [probes[0]["required_evidence_chunk_ids"][0]]
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml", encoding="utf-8") as tf:
            yaml.dump({"probes": probes}, tf)
            tmp_path = Path(tf.name)

        try:
            res = validate_validation_probes(tmp_path, self.chunks_path, self.orig_path)
            self.assertFalse(res["pass"])
            self.assertTrue(any("must require at least 2 chunks" in issue for issue in res["issues"]))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_overlap_with_original_probe_evidence(self):
        with open(self.probes_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Load first original probe required evidence
        with open(self.orig_path, "r", encoding="utf-8") as f:
            orig_req = yaml.safe_load(f)["probes"][0]["required_evidence_chunk_ids"]

        probes = copy.deepcopy(data["probes"])
        probes[0]["required_evidence_chunk_ids"] = list(orig_req)
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml", encoding="utf-8") as tf:
            yaml.dump({"probes": probes}, tf)
            tmp_path = Path(tf.name)

        try:
            res = validate_validation_probes(tmp_path, self.chunks_path, self.orig_path)
            self.assertFalse(res["pass"])
            self.assertTrue(any("identical to original probe" in issue for issue in res["issues"]))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_privacy_leak_scan(self):
        clean_manifest = "status: PREPARED_PENDING_HUMAN_REVIEW\nprobe_count: 25\n"
        self.assertEqual(find_privacy_leaks_in_manifest(clean_manifest), [])

        leak_chunk = "evidence: ch001_c0001"
        self.assertIn("<chunk-id pattern>", find_privacy_leaks_in_manifest(leak_chunk))

        leak_probe = "target probe: V_CHRONO_01"
        self.assertIn("<validation-probe-id pattern>", find_privacy_leaks_in_manifest(leak_probe))

    def test_flexible_probe_count_when_targets_none(self):
        with open(self.probes_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Slice to 10 probes across arbitrary categories
        probes = data["probes"][:10]
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml", encoding="utf-8") as tf:
            yaml.dump({"probes": probes}, tf)
            tmp_path = Path(tf.name)

        try:
            res = validate_validation_probes(
                tmp_path,
                self.chunks_path,
                self.orig_path,
                expected_probe_count=None,
                expected_per_category=None,
            )
            self.assertTrue(res["pass"], f"Flexible count failed: {res.get('issues')}")
            self.assertEqual(res["metrics"]["probe_count"], 10)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_intra_fixture_duplicate_detection(self):
        # Legacy draft has intra-fixture duplicate V_CALL_02 and V_SPOIL_02
        res = validate_validation_probes(
            self.probes_path,
            self.chunks_path,
            self.orig_path,
            check_intra_fixture_duplicates=True,
        )
        self.assertFalse(res["pass"])
        self.assertTrue(any("Intra-fixture duplicate required evidence set" in issue for issue in res["issues"]))

    def test_revised_draft_probes_validation_passes(self):
        revised_path = REPO_ROOT / ".local/story_integration/otonari_30ch/M1_30CH_P_REPAIR/revised_draft_probes.yaml"
        if revised_path.exists():
            res = validate_validation_probes(
                revised_path,
                self.chunks_path,
                self.orig_path,
                expected_probe_count=18,
                expected_per_category=None,
                check_intra_fixture_duplicates=True,
            )
            self.assertTrue(res["pass"], f"Revised validation failed: {res.get('issues')}")
            self.assertEqual(res["metrics"]["probe_count"], 18)
            self.assertEqual(res["metrics"]["multi_chunk_probe_count"], 18)

    def test_corrected_fixture_validates_cleanly(self):
        corr_dir = REPO_ROOT / ".local/story_integration/otonari_30ch/M1_30CH_P_CORRECTION"
        if not corr_dir.exists():
            self.skipTest("M1_30CH_P_CORRECTION directory not found")

        draft_p = corr_dir / "corrected_draft_probes.yaml"
        audit_p = corr_dir / "corrected_source_gold_audit.jsonl"
        aux_def_p = corr_dir / "auxiliary_and_deferred.yaml"

        # 1. Probe schema and cutoff validation
        res_probes = validate_validation_probes(
            draft_p,
            self.chunks_path,
            self.orig_path,
            expected_probe_count=16,
            expected_per_category=None,
            check_intra_fixture_duplicates=True,
        )
        self.assertTrue(res_probes["pass"], f"Corrected probes failed validation: {res_probes.get('issues')}")
        self.assertEqual(res_probes["metrics"]["probe_count"], 16)
        self.assertEqual(res_probes["metrics"]["multi_chunk_probe_count"], 16)

        # 2. Source gold audit and partition validation
        res_audit = validate_source_gold_audit_and_partitions(
            draft_p,
            audit_p,
            aux_def_p,
            self.chunks_path,
            expected_total_probes=25,
        )
        self.assertTrue(res_audit["pass"], f"Corrected audit failed validation: {res_audit.get('issues')}")
        self.assertEqual(res_audit["counts"]["primary"], 16)
        self.assertEqual(res_audit["counts"]["auxiliary"], 6)
        self.assertEqual(res_audit["counts"]["deferred"], 3)
        self.assertEqual(res_audit["counts"]["total_accounted"], 25)

    def test_semantic_fix_review_bundle_validates_cleanly(self):
        artifact_dir = REPO_ROOT / ".local/story_integration/otonari_30ch/M1_30CH_P_SEMANTIC_FIX"
        if not artifact_dir.exists():
            self.skipTest("M1_30CH_P_SEMANTIC_FIX directory not found")

        result = validate_review_artifact_bundle(
            artifact_dir,
            self.chunks_path,
            self.orig_path,
            expected_total_probes=25,
        )
        self.assertTrue(result["pass"], f"Semantic-fix bundle failed: {result.get('issues')}")
        self.assertEqual(result["metrics"]["total"], 25)

    def test_detect_invalid_span_bounds_or_mismatch(self):
        # Create synthetic chunks, draft, audit, aux_def
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            chunks_file = tdp / "chunks.jsonl"
            draft_file = tdp / "draft.yaml"
            audit_file = tdp / "audit.jsonl"
            aux_file = tdp / "aux.yaml"

            # Synthetic chunk: length 20
            c_text = "0123456789ABCDEFGHIJ"
            with open(chunks_file, "w", encoding="utf-8") as f:
                f.write(json.dumps({"chunk_id": "synth_c0001", "chapter_number": 1, "text": c_text}) + "\n")

            draft_content = {
                "probes": [{
                    "probe_id": "SYNTH_P01",
                    "question": "What is the text?",
                    "expected_answer": "01234",
                    "cutoff_chapter": 5,
                    "required_evidence_chunk_ids": ["synth_c0001"]
                }]
            }
            with open(draft_file, "w", encoding="utf-8") as f:
                yaml.dump(draft_content, f)

            with open(aux_file, "w", encoding="utf-8") as f:
                yaml.dump({"auxiliary_single_chunk_probes": [], "deferred_probes": []}, f)

            # Test A: Out of bounds span [15:25] when chunk length is 20
            bad_audit_a = {
                "probe_id": "SYNTH_P01",
                "question_original": "What is the text?",
                "expected_answer_original": "01234",
                "cutoff_chapter": 5,
                "minimality_and_multi_evidence": [{"chunk_id": "synth_c0001"}],
                "expected_propositions": [{
                    "proposition_id": "P1",
                    "supporting_chunk_id": "synth_c0001",
                    "chapter_number": 1,
                    "char_offset_start": 15,
                    "char_offset_end": 25,
                    "exact_excerpt": "FGHIJ"
                }]
            }
            with open(audit_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(bad_audit_a) + "\n")

            res_a = validate_source_gold_audit_and_partitions(draft_file, audit_file, aux_file, chunks_file, expected_total_probes=1)
            self.assertFalse(res_a["pass"])
            self.assertTrue(any("Invalid character span bounds [15:25]" in issue for issue in res_a["issues"]))

            # Test B: Excerpt mismatch ([0:5] slice is '01234', but excerpt says 'WRONG')
            bad_audit_b = {
                "probe_id": "SYNTH_P01",
                "question_original": "What is the text?",
                "expected_answer_original": "01234",
                "cutoff_chapter": 5,
                "minimality_and_multi_evidence": [{"chunk_id": "synth_c0001"}],
                "expected_propositions": [{
                    "proposition_id": "P1",
                    "supporting_chunk_id": "synth_c0001",
                    "chapter_number": 1,
                    "char_offset_start": 0,
                    "char_offset_end": 5,
                    "exact_excerpt": "WRONG"
                }]
            }
            with open(audit_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(bad_audit_b) + "\n")

            res_b = validate_source_gold_audit_and_partitions(draft_file, audit_file, aux_file, chunks_file, expected_total_probes=1)
            self.assertFalse(res_b["pass"])
            self.assertTrue(any("Source slice mismatch" in issue for issue in res_b["issues"]))

    def test_detect_unmapped_required_chunk_or_orphan_proposition(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            chunks_file = tdp / "chunks.jsonl"
            draft_file = tdp / "draft.yaml"
            audit_file = tdp / "audit.jsonl"
            aux_file = tdp / "aux.yaml"

            with open(chunks_file, "w", encoding="utf-8") as f:
                f.write(json.dumps({"chunk_id": "synth_c0001", "chapter_number": 1, "text": "chunk_one_text_here"}) + "\n")
                f.write(json.dumps({"chunk_id": "synth_c0002", "chapter_number": 1, "text": "chunk_two_text_here"}) + "\n")

            # Draft requires 2 chunks: synth_c0001 and synth_c0002
            draft_content = {
                "probes": [{
                    "probe_id": "SYNTH_P02",
                    "question": "Q?",
                    "expected_answer": "A",
                    "cutoff_chapter": 5,
                    "required_evidence_chunk_ids": ["synth_c0001", "synth_c0002"]
                }]
            }
            with open(draft_file, "w", encoding="utf-8") as f:
                yaml.dump(draft_content, f)

            with open(aux_file, "w", encoding="utf-8") as f:
                yaml.dump({"auxiliary_single_chunk_probes": [], "deferred_probes": []}, f)

            # Audit only maps proposition to synth_c0001 (synth_c0002 unmapped)
            bad_audit = {
                "probe_id": "SYNTH_P02",
                "question_original": "Q?",
                "expected_answer_original": "A",
                "cutoff_chapter": 5,
                "minimality_and_multi_evidence": [{"chunk_id": "synth_c0001"}, {"chunk_id": "synth_c0002"}],
                "expected_propositions": [{
                    "proposition_id": "P1",
                    "supporting_chunk_id": "synth_c0001",
                    "chapter_number": 1,
                    "char_offset_start": 0,
                    "char_offset_end": 5,
                    "exact_excerpt": "chunk"
                }]
            }
            with open(audit_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(bad_audit) + "\n")

            res = validate_source_gold_audit_and_partitions(draft_file, audit_file, aux_file, chunks_file, expected_total_probes=1)
            self.assertFalse(res["pass"])
            self.assertTrue(any("Proposition chunk mapping mismatch" in issue for issue in res["issues"]))

    def test_detect_draft_audit_inconsistency(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            chunks_file = tdp / "chunks.jsonl"
            draft_file = tdp / "draft.yaml"
            audit_file = tdp / "audit.jsonl"
            aux_file = tdp / "aux.yaml"

            with open(chunks_file, "w", encoding="utf-8") as f:
                f.write(json.dumps({"chunk_id": "synth_c0001", "chapter_number": 1, "text": "hello_world_sample"}) + "\n")

            draft_content = {
                "probes": [{
                    "probe_id": "SYNTH_P03",
                    "question": "Question A",
                    "expected_answer": "Answer A",
                    "cutoff_chapter": 5,
                    "required_evidence_chunk_ids": ["synth_c0001"]
                }]
            }
            with open(draft_file, "w", encoding="utf-8") as f:
                yaml.dump(draft_content, f)

            with open(aux_file, "w", encoding="utf-8") as f:
                yaml.dump({"auxiliary_single_chunk_probes": [], "deferred_probes": []}, f)

            # Audit has mismatched question: 'Question B'
            bad_audit = {
                "probe_id": "SYNTH_P03",
                "question_original": "Question B",
                "expected_answer_original": "Answer A",
                "cutoff_chapter": 5,
                "minimality_and_multi_evidence": [{"chunk_id": "synth_c0001"}],
                "expected_propositions": [{
                    "proposition_id": "P1",
                    "supporting_chunk_id": "synth_c0001",
                    "chapter_number": 1,
                    "char_offset_start": 0,
                    "char_offset_end": 5,
                    "exact_excerpt": "hello"
                }]
            }
            with open(audit_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(bad_audit) + "\n")

            res = validate_source_gold_audit_and_partitions(draft_file, audit_file, aux_file, chunks_file, expected_total_probes=1)
            self.assertFalse(res["pass"])
            self.assertTrue(any("Question mismatch in SYNTH_P03" in issue for issue in res["issues"]))

    def test_detect_partition_overlap_or_probe_loss(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            chunks_file = tdp / "chunks.jsonl"
            draft_file = tdp / "draft.yaml"
            audit_file = tdp / "audit.jsonl"
            aux_file = tdp / "aux.yaml"

            with open(chunks_file, "w", encoding="utf-8") as f:
                f.write(json.dumps({"chunk_id": "synth_c0001", "chapter_number": 1, "text": "hello_world_sample"}) + "\n")

            # Primary has SYNTH_P04
            draft_content = {
                "probes": [{
                    "probe_id": "SYNTH_P04",
                    "question": "Q?",
                    "expected_answer": "A",
                    "cutoff_chapter": 5,
                    "required_evidence_chunk_ids": ["synth_c0001"]
                }]
            }
            with open(draft_file, "w", encoding="utf-8") as f:
                yaml.dump(draft_content, f)

            audit_content = {
                "probe_id": "SYNTH_P04",
                "question_original": "Q?",
                "expected_answer_original": "A",
                "cutoff_chapter": 5,
                "minimality_and_multi_evidence": [{"chunk_id": "synth_c0001"}],
                "expected_propositions": [{
                    "proposition_id": "P1",
                    "supporting_chunk_id": "synth_c0001",
                    "chapter_number": 1,
                    "char_offset_start": 0,
                    "char_offset_end": 5,
                    "exact_excerpt": "hello"
                }]
            }
            with open(audit_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(audit_content) + "\n")

            # Auxiliary also contains SYNTH_P04 -> Overlap error!
            with open(aux_file, "w", encoding="utf-8") as f:
                yaml.dump({
                    "auxiliary_single_chunk_probes": [{"probe_id": "SYNTH_P04"}],
                    "deferred_probes": []
                }, f)

            res = validate_source_gold_audit_and_partitions(draft_file, audit_file, aux_file, chunks_file, expected_total_probes=1)
            self.assertFalse(res["pass"])
            self.assertTrue(any("Partition overlap between primary and auxiliary" in issue for issue in res["issues"]))

    def test_detect_chapter_metadata_and_cutoff_violations(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            chunks_file = tdp / "chunks.jsonl"
            draft_file = tdp / "draft.yaml"
            audit_file = tdp / "audit.jsonl"
            aux_file = tdp / "aux.yaml"

            with open(chunks_file, "w", encoding="utf-8") as f:
                f.write(json.dumps({"chunk_id": "synth_c0010", "chapter_number": 10, "text": "chapter_ten_content"}) + "\n")

            # Cutoff is Chapter 5, but chunk is Chapter 10 -> Cutoff violation!
            draft_content = {
                "probes": [{
                    "probe_id": "SYNTH_P05",
                    "question": "Q?",
                    "expected_answer": "A",
                    "cutoff_chapter": 5,
                    "required_evidence_chunk_ids": ["synth_c0010"]
                }]
            }
            with open(draft_file, "w", encoding="utf-8") as f:
                yaml.dump(draft_content, f)

            with open(aux_file, "w", encoding="utf-8") as f:
                yaml.dump({"auxiliary_single_chunk_probes": [], "deferred_probes": []}, f)

            bad_audit = {
                "probe_id": "SYNTH_P05",
                "question_original": "Q?",
                "expected_answer_original": "A",
                "cutoff_chapter": 5,
                "minimality_and_multi_evidence": [{"chunk_id": "synth_c0010"}],
                "expected_propositions": [{
                    "proposition_id": "P1",
                    "supporting_chunk_id": "synth_c0010",
                    "chapter_number": 10,
                    "char_offset_start": 0,
                    "char_offset_end": 7,
                    "exact_excerpt": "chapter"
                }]
            }
            with open(audit_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(bad_audit) + "\n")

            res = validate_source_gold_audit_and_partitions(draft_file, audit_file, aux_file, chunks_file, expected_total_probes=1)
            self.assertFalse(res["pass"])
            self.assertTrue(any("Cutoff violation in proposition P1" in issue for issue in res["issues"]))

    def test_review_gate_bundle_validates_cleanly(self):
        gate_dir = REPO_ROOT / ".local/story_integration/otonari_30ch/M1_30CH_P_REVIEW_GATE"
        if not gate_dir.exists():
            self.skipTest("M1_30CH_P_REVIEW_GATE directory not found")

        # Skip if manifest is not yet generated in this step
        if not (gate_dir / "manifest.json").exists():
            self.skipTest("manifest.json not yet generated in review gate")

        result = validate_review_gate_deliverables(gate_dir, expected_total_probes=25)
        self.assertTrue(result["pass"], f"Review gate bundle failed: {result.get('issues')}")
        self.assertEqual(result["metrics"]["total_probes"], 25)
        self.assertEqual(result["metrics"]["primary_probes"], 16)
        self.assertEqual(result["metrics"]["auxiliary_probes"], 6)
        self.assertEqual(result["metrics"]["deferred_probes"], 3)

    def test_detect_review_gate_synthetic_errors(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            # Create incomplete directory (missing files)
            res_missing = validate_review_gate_deliverables(tdp, expected_total_probes=1)
            self.assertFalse(res_missing["pass"])
            self.assertTrue(any("Missing required review gate deliverable" in i for i in res_missing["issues"]))

            # Create all required dummy files
            required_files = [
                "review_packet_vi.md",
                "review_decisions.csv",
                "source_review_findings.jsonl",
                "multi_gold_feasibility.md",
                "prefreeze_readiness_report.md",
                "validation_report.json",
                "raw_test_log.txt",
                "manifest.json",
            ]
            for rf in required_files:
                (tdp / rf).write_text("dummy", encoding="utf-8")

            (tdp / "source_review_findings.jsonl").write_text(
                json.dumps({"probe_id": "V_SYNTH_01", "status": "PENDING_REVIEW"}) + "\n",
                encoding="utf-8"
            )
            (tdp / "manifest.json").write_text(
                json.dumps({"files": {}}),
                encoding="utf-8"
            )

            # With invalid CSV content (non-PENDING_REVIEW status)
            csv_content = "probe_id,partition,category,cutoff_chapter,required_chunk_ids,decision_status,reviewer_notes\n"
            csv_content += "V_SYNTH_01,primary,CHRONOLOGY,30,ch001_c0001,APPROVED,notes\n"
            (tdp / "review_decisions.csv").write_text(csv_content, encoding="utf-8")

            res_bad_status = validate_review_gate_deliverables(tdp, expected_total_probes=1)
            self.assertFalse(res_bad_status["pass"])
            self.assertTrue(any("expected PENDING_REVIEW" in i for i in res_bad_status["issues"]))

    def test_prefreeze_correction_bundle_validates_cleanly(self):
        corr_dir = REPO_ROOT / ".local/story_integration/otonari_30ch/M1_30CH_P_PREFREEZE_CORRECTION"
        if not corr_dir.exists():
            self.skipTest("M1_30CH_P_PREFREEZE_CORRECTION directory not found")

        chunks_path = REPO_ROOT / ".local/story_integration/otonari_30ch/PARAGRAPH_PACK_V1/chunks.jsonl"
        result = validate_prefreeze_correction_deliverables(corr_dir, chunks_path=chunks_path, expected_total_probes=25)
        self.assertTrue(result["pass"], f"Prefreeze correction bundle failed: {result.get('issues')}")
        self.assertEqual(result["metrics"]["total_probes"], 25)
        self.assertEqual(result["metrics"]["primary_probes"], 16)
        self.assertEqual(result["metrics"]["auxiliary_probes"], 6)
        self.assertEqual(result["metrics"]["deferred_probes"], 3)
        self.assertTrue(result["metrics"]["all_pending_review"])

    def test_detect_prefreeze_correction_synthetic_errors(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            res_missing = validate_prefreeze_correction_deliverables(tdp, expected_total_probes=1)
            self.assertFalse(res_missing["pass"])
            self.assertTrue(any("Missing required prefreeze correction deliverable" in i for i in res_missing["issues"]))

            # Create dummy files
            required_files = [
                "canonical_probe_inventory.csv",
                "primary_gold_audit.jsonl",
                "corrected_human_review_packet_vi.md",
                "auxiliary_deferred_disposition.md",
                "evaluation_readiness.md",
                "correction_log.md",
                "validation_report.json",
                "raw_test_log.txt",
                "manifest.json",
            ]
            for rf in required_files:
                (tdp / rf).write_text("dummy", encoding="utf-8")

            # CSV with report-only typo
            csv_content = "probe_id,partition,category,cutoff,required_chunks,audit_status,human_decision,notes\n"
            csv_content += "V_CHRO_01,primary,CHRONOLOGY,30,ch001_c0001,SOURCE_GROUNDED_PASS,PENDING_REVIEW,notes\n"
            (tdp / "canonical_probe_inventory.csv").write_text(csv_content, encoding="utf-8")

            res_typo = validate_prefreeze_correction_deliverables(tdp, expected_total_probes=1)
            self.assertFalse(res_typo["pass"])
            self.assertTrue(any("report-only typo" in i for i in res_typo["issues"]))


if __name__ == "__main__":
    unittest.main()
