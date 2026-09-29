"""Synthetic cross-artifact consistency tests (no fixture text)."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.story_benchmark import probe_consistency as pc
from tools.story_benchmark.validate_independent_validation_fixture_v1 import (
    compare_review_artifacts,
    validate_signoff_consistency_bundle,
)

CHUNKS = {
    "A": "Alpha opens. The first event happens here.",
    "B": "Beta scene. The second event happens here.",
    "C": "Gamma closes. The third event happens here.",
    "D": "Delta recap. The second event also happens here.",
}


def evidence(chunk_id, phrase):
    start = CHUNKS[chunk_id].index(phrase)
    return {
        "chunk_id": chunk_id,
        "source_offsets": [start, start + len(phrase)],
        "source_excerpt": phrase,
    }


def make_probe(multi=True):
    second = [evidence("B", "The second event happens here.")]
    gold = [["A", "B", "C"]]
    if multi:
        second.append(evidence("D", "The second event also happens here."))
        gold.append(["A", "D", "C"])
    propositions = [
        {"proposition_id": "P1", "proposition_en": "First event.", "proposition_vi": "Một.",
         "classification": "DIRECTLY_EXPLICIT", "rationale_vi": "r",
         "supporting_evidence": [evidence("A", "The first event happens here.")]},
        {"proposition_id": "P2", "proposition_en": "Second event.", "proposition_vi": "Hai.",
         "classification": "STRONGLY_ENTAILED", "rationale_vi": "r",
         "supporting_evidence": second},
        {"proposition_id": "P3", "proposition_en": "Third event.", "proposition_vi": "Ba.",
         "classification": "DIRECTLY_EXPLICIT", "rationale_vi": "r",
         "supporting_evidence": [evidence("C", "The third event happens here.")]},
    ]
    union = sorted({c for s in gold for c in s})
    probe = {
        "probe_id": "V_SYNTH_01",
        "category": "CHRONOLOGY",
        "cutoff_chapter": 30,
        "question": "Order the synthetic events.",
        "question_vi": "Sắp xếp.",
        "expected_answer": "First, second, third.",
        "expected_answer_vi": "Một, hai, ba.",
        "propositions": propositions,
        "gold_evidence_sets": gold,
        "minimality": [
            {"chunk_id": c, "within_declared_set": "ESSENTIAL", "context_quality": "SELF_CONTAINED_ENOUGH"}
            for c in union
        ],
        "agent_recommendation": "KEEP_PENDING_HUMAN_REVIEW",
        "alternative_evidence_status": "ALL_COMPLETE_ALTERNATIVE_PATHS_REPRESENTED",
    }
    probe["expected_facts"] = pc.expected_facts(probe)
    return probe


def build_bundle(out_dir, probe):
    fixture = {
        "fixture_id": "SYN", "gold_schema_version": 2,
        "frozen": False, "evaluation_allowed": False, "task_q_executed": False,
        "probes": [probe],
    }
    aux = [{
        "probe_id": "V_SYNTH_02", "partition": "auxiliary", "category": "CALLBACK",
        "cutoff": "30", "gold_schema_version": "1", "gold_set_count": "1",
        "semantic_status": "AUXILIARY_DISPOSITION_ONLY", "alternative_evidence_status": "NOT_AUDITED",
        "agent_recommendation": "KEEP_AS_AUXILIARY", "human_decision": "PENDING_REVIEW", "notes": "",
    }]
    pc.write_projection_artifacts(out_dir, fixture, aux, ["Synthetic header"], "SYN.zip")
    for name, content in {
        "cross_artifact_consistency_report.json": "{}\n",
        "repair_log.jsonl": "",
        "raw_test_log.txt": "synthetic\n",
        "validation_report.json": json.dumps({
            "human_signoff_complete": False, "frozen": False, "evaluation_allowed": False,
            "task_q_executed": False, "privacy_pass": True,
        }),
    }.items():
        (out_dir / name).write_text(content, encoding="utf-8")
    refresh_manifest(out_dir)


def refresh_manifest(out_dir):
    files = {
        p.name: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
        for p in sorted(out_dir.iterdir()) if p.name not in {"manifest.json", "chunks.jsonl"}
    }
    (out_dir / "manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")


def write_chunks(path):
    with path.open("w", encoding="utf-8") as f:
        for chunk_id, text in CHUNKS.items():
            f.write(json.dumps({"chunk_id": chunk_id, "chapter_number": 1, "text": text}) + "\n")


class TestCrossArtifactComparison(unittest.TestCase):
    def setUp(self):
        self.probe = make_probe()
        self.audit = {"V_SYNTH_01": pc.audit_projection(self.probe)}
        self.guide = pc.render_review_guide([self.probe], ["h"])
        self.inventory = {"V_SYNTH_01": pc.inventory_row(self.probe)}

    def fields(self, audit=None, guide=None):
        return {
            (m["artifact"], m["field"])
            for m in compare_review_artifacts(
                [self.probe], audit or self.audit, guide or self.guide, self.inventory
            )
        }

    def test_consistent_artifacts_have_no_mismatch(self):
        self.assertEqual(self.fields(), set())

    def test_a_question_mismatch_fails(self):
        audit = copy.deepcopy(self.audit)
        audit["V_SYNTH_01"]["question"] = "A different reviewed question."
        self.assertIn(("semantic_audit", "question"), self.fields(audit=audit))

    def test_b_expected_answer_mismatch_fails(self):
        audit = copy.deepcopy(self.audit)
        audit["V_SYNTH_01"]["expected_answer"] = "A different reviewed answer."
        self.assertIn(("semantic_audit", "expected_answer"), self.fields(audit=audit))

    def test_c_gold_set_mismatch_fails(self):
        audit = copy.deepcopy(self.audit)
        audit["V_SYNTH_01"]["gold_evidence_sets"] = [["A", "C"]]
        self.assertIn(("semantic_audit", "gold_evidence_sets"), self.fields(audit=audit))

    def test_f_guide_from_stale_content_fails(self):
        stale = copy.deepcopy(self.probe)
        stale["question"] = "An older draft question."
        stale_guide = pc.render_review_guide([stale], ["h"])
        self.assertIn(("review_guide", "question"), self.fields(guide=stale_guide))


class TestPropositionGoldCoverage(unittest.TestCase):
    def test_h_valid_multi_gold_passes(self):
        self.assertEqual(pc.check_probe(make_probe(), CHUNKS), [])

    def test_valid_single_gold_passes(self):
        self.assertEqual(pc.check_probe(make_probe(multi=False), CHUNKS), [])

    def test_d_essential_chunk_absent_from_gold_path_fails(self):
        probe = make_probe(multi=False)
        probe["gold_evidence_sets"] = [["A", "C"]]
        probe["minimality"] = [m for m in probe["minimality"] if m["chunk_id"] != "B"]
        issues = pc.check_proposition_gold_coverage(probe)
        self.assertTrue(any("P2" in i and "none of" in i for i in issues), issues)

    def test_g_invalid_multi_gold_coverage_fails(self):
        probe = make_probe()
        probe["propositions"][1]["supporting_evidence"] = probe["propositions"][1]["supporting_evidence"][:1]
        issues = pc.check_proposition_gold_coverage(probe)
        self.assertTrue(any("gold set 2" in i and "P2" in i for i in issues), issues)

    def test_unrepresented_complete_alternative_fails(self):
        probe = make_probe()
        probe["gold_evidence_sets"] = [["A", "B", "C"]]
        issues = pc.check_proposition_gold_coverage(probe)
        self.assertTrue(any("not represented" in i for i in issues), issues)

    def test_superfluous_gold_chunk_fails(self):
        probe = make_probe(multi=False)
        probe["gold_evidence_sets"] = [["A", "B", "C", "D"]]
        issues = pc.check_proposition_gold_coverage(probe)
        self.assertTrue(any("non-minimal" in i for i in issues), issues)

    def test_e_stale_minimality_chunk_fails(self):
        probe = make_probe(multi=False)
        probe["minimality"].append({"chunk_id": "Z", "within_declared_set": "ESSENTIAL"})
        issues = pc.check_minimality_records(probe)
        self.assertTrue(any("stale minimality" in i and "Z" in i for i in issues), issues)

    def test_truncated_excerpt_fails(self):
        probe = make_probe(multi=False)
        entry = probe["propositions"][0]["supporting_evidence"][0]
        entry["source_excerpt"] = entry["source_excerpt"][:5]
        issues = pc.check_evidence_spans(probe, CHUNKS)
        self.assertTrue(any("not the exact source slice" in i for i in issues), issues)

    def test_i_legacy_single_support_row_fails_multi_gold(self):
        probe = make_probe()
        for prop in probe["propositions"]:
            first = prop.pop("supporting_evidence")[0]
            prop["supporting_chunk_id"] = first["chunk_id"]
        issues = pc.check_proposition_gold_coverage(probe)
        self.assertTrue(any("gold set 2" in i for i in issues), issues)


class TestSignoffConsistencyBundle(unittest.TestCase):
    def run_bundle(self, mutate=None):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            probe = make_probe()
            build_bundle(out, probe)
            if mutate:
                mutate(out)
                refresh_manifest(out)
            chunks = out / "chunks.jsonl"
            write_chunks(chunks)
            return validate_signoff_consistency_bundle(
                out, chunks, expected_total_probes=2, expected_primary_probes=1
            )

    def test_j_corrected_bundle_passes(self):
        result = self.run_bundle()
        self.assertTrue(result["pass"], result["issues"])
        self.assertEqual(result["metrics"]["multi_gold_probes"], 1)

    def test_i_bundle_with_divergent_audit_question_fails(self):
        def mutate(out):
            path = out / "primary_semantic_audit_v3.jsonl"
            row = json.loads(path.read_text(encoding="utf-8"))
            row["question"] = "Divergent question."
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        result = self.run_bundle(mutate)
        self.assertFalse(result["pass"])
        self.assertTrue(any("mismatch in question" in i for i in result["issues"]), result["issues"])

    def test_hand_edited_guide_fails(self):
        def mutate(out):
            path = out / "human_review_guide_vi_v3.md"
            path.write_text(path.read_text(encoding="utf-8") + "extra\n", encoding="utf-8")
        result = self.run_bundle(mutate)
        self.assertFalse(result["pass"])
        self.assertIn("Human review guide is not generated from the canonical fixture", result["issues"])

    def test_drifted_expected_facts_fail(self):
        def mutate(out):
            import yaml
            path = out / "canonical_primary_fixture.yaml"
            fixture = yaml.safe_load(path.read_text(encoding="utf-8"))
            fixture["probes"][0]["expected_facts"][0] = "Independently edited fact."
            path.write_text(yaml.safe_dump(fixture, allow_unicode=True, sort_keys=False), encoding="utf-8")
        result = self.run_bundle(mutate)
        self.assertFalse(result["pass"])
        self.assertTrue(any("expected_facts" in i for i in result["issues"]), result["issues"])

    def test_ai_created_decision_in_template_fails(self):
        def mutate(out):
            path = out / "human_signoff_template_v3.csv"
            path.write_text(
                path.read_text(encoding="utf-8").replace("PENDING_REVIEW", "APPROVED", 1),
                encoding="utf-8",
            )
        result = self.run_bundle(mutate)
        self.assertFalse(result["pass"])


if __name__ == "__main__":
    unittest.main()
