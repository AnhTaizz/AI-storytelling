"""Verdict sanity matrix for the Script Quality Contract v0 candidate (section 15-16).

The helper below is a test-only transcription of the contract's gate-status and
verdict rules. It is NOT a production evaluator. Deterministic; no model, API or network.
"""
import itertools
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CANDIDATE = yaml.safe_load(
    (REPO / "benchmarks/m1_script_quality/SCRIPT_QUALITY_CONTRACT_V0_CANDIDATE.yaml").read_text(encoding="utf-8"))

GATES = [g["id"] for g in CANDIDATE["hard_gates"]["gates"]]
SEMANTIC_GATES = set(CANDIDATE["hard_gates"]["human_audit_required_in_v0"])
MATERIAL = set(CANDIDATE["hard_gates"]["material_severities"])
SOFT = [d["id"] for d in CANDIDATE["soft_dimensions"]["dimensions"]]


def gate_status(gate, severities, human_audited):
    """Section 15: status of one gate from the severities of its confirmed findings."""
    if gate in SEMANTIC_GATES and not human_audited:
        return "GATE_NOT_DETERMINED"
    if MATERIAL & set(severities):
        return "GATE_FAIL"
    if "MEDIUM" in severities:
        return "GATE_CONDITIONAL"
    return "GATE_PASS"


def verdict(gate_statuses, soft_ratings, edit_cost):
    """Section 16: evaluated in order, first match wins. Ratings of None are NOT_APPLICABLE."""
    statuses = set(gate_statuses.values())
    applicable = [r for r in soft_ratings.values() if r is not None]
    if "GATE_FAIL" in statuses or edit_cost == "REWRITE":
        return "FAIL"
    if "GATE_NOT_DETERMINED" in statuses or min(applicable) <= 2 or edit_cost == "MAJOR":
        return "REVIEW_REQUIRED"
    if statuses == {"GATE_PASS"} and soft_ratings["OVERALL_USEFULNESS"] >= 4 and edit_cost == "MINIMAL":
        return "PASS"
    return "PASS_WITH_MINOR_EDITS"


def review(findings=None, soft=None, edit_cost="MINIMAL", human_audited=True):
    findings = findings or {}
    ratings = {d: 4 for d in SOFT}
    ratings.update(soft or {})
    statuses = {g: gate_status(g, findings.get(g, []), human_audited) for g in GATES}
    return verdict(statuses, ratings, edit_cost)


class TestVerdictSanityMatrix(unittest.TestCase):
    def test_v1_clean_script_passes(self):
        self.assertEqual(review(), "PASS")

    def test_v2_one_medium_local_finding_moderate_edit(self):
        self.assertEqual(review({"GATE_EPISTEMIC_INTEGRITY": ["MEDIUM"]}, edit_cost="MODERATE"),
                         "PASS_WITH_MINOR_EDITS")

    def test_v3_one_high_factual_finding_fails(self):
        self.assertEqual(review({"GATE_FACTUAL_GROUNDING": ["HIGH"]}), "FAIL")

    def test_v4_missing_human_audit_requires_review(self):
        self.assertEqual(review(human_audited=False), "REVIEW_REQUIRED")

    def test_v5_weak_pacing_requires_review(self):
        self.assertEqual(review(soft={"PACING": 2}), "REVIEW_REQUIRED")

    def test_v6_major_edit_cost_requires_review(self):
        self.assertEqual(review(edit_cost="MAJOR"), "REVIEW_REQUIRED")

    def test_v7_gate_failure_is_not_rescued_by_narrative_scores(self):
        self.assertEqual(review({"GATE_SPOILER_DISCIPLINE": ["CRITICAL"]}, soft={d: 5 for d in SOFT}), "FAIL")

    def test_v8_rewrite_edit_cost_fails(self):
        self.assertEqual(review(edit_cost="REWRITE"), "FAIL")


class TestVerdictLogicProperties(unittest.TestCase):
    def test_verdict_labels_match_candidate(self):
        self.assertEqual([v["id"] for v in CANDIDATE["verdicts"]],
                         ["FAIL", "REVIEW_REQUIRED", "PASS", "PASS_WITH_MINOR_EDITS"])

    def test_every_state_has_exactly_one_known_verdict(self):
        labels = {v["id"] for v in CANDIDATE["verdicts"]}
        statuses = CANDIDATE["hard_gates"]["statuses"]
        for worst, lowest, overall, cost in itertools.product(
                statuses, range(1, 6), range(1, 6), CANDIDATE["edit_cost_levels"]):
            gates = {g: "GATE_PASS" for g in GATES}
            gates[GATES[0]] = worst
            ratings = {d: 5 for d in SOFT}
            ratings["PACING"] = lowest
            ratings["OVERALL_USEFULNESS"] = overall
            self.assertIn(verdict(gates, ratings, cost), labels)

    def test_low_findings_do_not_block_pass(self):
        self.assertEqual(review({"GATE_FACTUAL_GROUNDING": ["LOW", "LOW"]}), "PASS")

    def test_not_applicable_dimensions_are_ignored(self):
        self.assertEqual(review(soft={"HUMOR_COMMENTARY_QUALITY": None, "CALLBACK_QUALITY": None}), "PASS")

    def test_pass_needs_overall_usefulness_of_four(self):
        self.assertEqual(review(soft={"OVERALL_USEFULNESS": 3}), "PASS_WITH_MINOR_EDITS")

    def test_dry_run_summary_verdicts_follow_from_recorded_states(self):
        summary = yaml.safe_load((REPO / "benchmarks/m1_script_quality/evaluations/CONTRACT_V0_DRY_RUN"
                                  / "DRY_RUN_SUMMARY.yaml").read_text(encoding="utf-8"))
        for run in summary["reviews"].values():
            self.assertEqual(set(run["gates"]), set(GATES))
            self.assertEqual(verdict(run["gates"], run["soft_dimensions"], run["edit_cost"]), run["dry_run_verdict"])
            unaudited = {g: ("GATE_NOT_DETERMINED" if g in SEMANTIC_GATES else s) for g, s in run["gates"].items()}
            self.assertEqual(verdict(unaudited, run["soft_dimensions"], run["edit_cost"]),
                             run["strict_contract_verdict"])


if __name__ == "__main__":
    unittest.main()
