"""Freeze integrity checks for SCRIPT_QUALITY_CONTRACT/v0.

Deterministic. No model, API or network. These tests check the frozen identity;
they do not evaluate any script, Writer or critic.
"""
import hashlib
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
M1 = REPO / "benchmarks/m1_script_quality"
FROZEN = M1 / "SCRIPT_QUALITY_CONTRACT_V0.yaml"
CANDIDATE = M1 / "SCRIPT_QUALITY_CONTRACT_V0_CANDIDATE.yaml"
RECORD = M1 / "SCRIPT_QUALITY_CONTRACT_V0_FREEZE_RECORD.yaml"
SPEC = REPO / "docs/contracts/SCRIPT_QUALITY_CONTRACT_V0.md"
TEMPLATE = M1 / "evaluations/HUMAN_REVIEW_TEMPLATE.md"
DECISIONS = REPO / "docs/DECISIONS.md"
RELEASE_METADATA = {"status", "revision", "freeze", "m1_closure_recommendation"}


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def blob_sha256(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


class TestFrozenContract(unittest.TestCase):
    def setUp(self):
        self.frozen, self.candidate, self.record = load(FROZEN), load(CANDIDATE), load(RECORD)

    def test_statuses(self):
        self.assertEqual(self.frozen["contract_version"], "SCRIPT_QUALITY_CONTRACT/v0")
        self.assertEqual(self.frozen["status"], "FROZEN")
        self.assertEqual(self.record["freeze_status"], "FROZEN")
        self.assertEqual(self.record["contract_version"], self.frozen["contract_version"])
        self.assertEqual(self.candidate["status"], "CANDIDATE_REPAIRED_PENDING_ORCHESTRATOR_FREEZE_REVIEW")

    def test_frozen_contract_has_the_candidate_semantics(self):
        strip = lambda d: {k: v for k, v in d.items() if k not in RELEASE_METADATA}
        self.assertEqual(strip(self.frozen), strip(self.candidate))
        self.assertEqual(self.frozen["freeze"]["semantic_changes_at_freeze"], "none")
        self.assertEqual(self.record["semantic_changes_at_freeze"], "none")

    def test_bound_hashes_match(self):
        for group in ("normative_frozen_artifacts", "validation_and_historical_evidence"):
            for name, entry in self.record[group].items():
                path = REPO / entry["path"]
                self.assertTrue(path.is_file(), entry["path"])
                self.assertEqual(blob_sha256(path), entry["sha256"], name)

    def test_normative_set_is_exactly_the_three_artifacts(self):
        paths = {e["path"] for e in self.record["normative_frozen_artifacts"].values()}
        self.assertEqual(paths, {str(p.relative_to(REPO)).replace("\\", "/") for p in (SPEC, FROZEN, TEMPLATE)})
        evidence = {e["path"] for e in self.record["validation_and_historical_evidence"].values()}
        self.assertIn("benchmarks/m1_script_quality/SCRIPT_QUALITY_CONTRACT_V0_CANDIDATE.yaml", evidence)
        self.assertFalse(paths & evidence)

    def test_documents_say_frozen(self):
        spec = SPEC.read_text(encoding="utf-8")
        self.assertIn("**FROZEN / ACCEPTED**", spec)
        self.assertIn("benchmarks/m1_script_quality/SCRIPT_QUALITY_CONTRACT_V0.yaml", spec)
        self.assertIn("`SCRIPT_QUALITY_CONTRACT/v0` — FROZEN", TEMPLATE.read_text(encoding="utf-8"))

    def test_decision_record(self):
        text = DECISIONS.read_text(encoding="utf-8")
        section = text.split("## DEC-017 — Script Quality Contract v0 Freeze")[1].split("\n## ")[0]
        self.assertIn("STATUS: ACCEPTED", section)
        self.assertIn("SCRIPT_QUALITY_CONTRACT_V0_FREEZE_RECORD.yaml", section)
        self.assertIn("`NOT_EVALUATED`", section)
        self.assertEqual(text.count("## DEC-017"), 1)

    def test_human_audit_rule_is_frozen(self):
        rule = self.record["human_audit_rule"]
        self.assertEqual(rule["official_contract_verdict_without_human_audit"], "REVIEW_REQUIRED")
        self.assertEqual(rule["semantic_gates"], self.frozen["hard_gates"]["human_audit_required_in_v0"])
        self.assertEqual(len(rule["semantic_gates"]), 5)
        self.assertFalse(self.frozen["verdict_rules"]["ai_only_review_can_yield_official_pass"])

    def test_h7_is_not_upgraded_and_no_performance_claim(self):
        status = self.record["validator_status"]
        self.assertEqual(status["h7_confirmatory_verdict"], "NOT_EVALUATED")
        self.assertEqual(status["h7_stage_b"], "NOT EXECUTED")
        self.assertFalse(status["any_writer_or_critic_shown_to_satisfy_contract"])
        h7 = self.frozen["validator_evidence_status"]["h7_targeted_epistemic_pass"]
        self.assertEqual((h7["stage_b_executed"], h7["confirmatory_verdict"]), (False, "NOT_EVALUATED"))
        for path in (SPEC, DECISIONS, RECORD):
            lowered = path.read_text(encoding="utf-8").lower()
            for phrase in ("h7 is validated", "h7 has been validated", "writer passes v0", "critic passes v0"):
                self.assertNotIn(phrase, lowered)

    def test_known_limitations_recorded(self):
        self.assertGreaterEqual(len(self.record["known_limitations"]), 9)
        self.assertFalse(self.record["m3_started"])


if __name__ == "__main__":
    unittest.main()
