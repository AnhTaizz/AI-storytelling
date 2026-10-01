"""Consistency checks for the Script Quality Contract v0 candidate.

Deterministic. No model, API or network. These tests check that the Markdown
contract, the machine-readable candidate and the M1 evidence agree; they do not
evaluate any script.
"""
import re
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SPEC = REPO / "docs/contracts/SCRIPT_QUALITY_CONTRACT_V0.md"
CANDIDATE = REPO / "benchmarks/m1_script_quality/SCRIPT_QUALITY_CONTRACT_V0_CANDIDATE.yaml"
TEMPLATE = REPO / "benchmarks/m1_script_quality/evaluations/HUMAN_REVIEW_TEMPLATE.md"
FAILURE_TEMPLATE = REPO / "benchmarks/m1_script_quality/evaluations/FAILURE_REPORT_TEMPLATE.md"
RESIDUAL = REPO / "docs/research/H6B_RESIDUAL_FAILURE_ANALYSIS.md"
H7_CLOSURE = REPO / "benchmarks/m1_script_quality/experiments/h7/stage_a_v2/H7_V2_STAGE_A_CLOSURE.yaml"

REQUIRED_PARENTS = {
    "FACTUAL_ERROR", "TEMPORAL_ERROR", "CHARACTER_STATE_ERROR", "RELATIONSHIP_ERROR", "CAUSALITY_ERROR",
    "MISSING_IMPORTANT_EVENT", "UNSUPPORTED_INVENTION", "PREMATURE_SPOILER", "SOURCE_GROUNDING_FAILURE",
}
REQUIRED_CLAIM_TYPES = {"SUPPORTED_FACT", "SUPPORTED_INFERENCE", "ATTRIBUTED_REPORT", "COMMENTARY_RHETORIC",
                        "UNSUPPORTED_STORY_CLAIM"}
REQUIRED_KEYS = {"contract_version", "status", "hard_invariants", "hard_gates", "failure_taxonomy",
                 "severity_levels", "soft_dimensions", "verdicts", "known_limitations", "evidence_sources",
                 "validator_evidence_status"}


def load():
    return yaml.safe_load(CANDIDATE.read_text(encoding="utf-8"))


def taxonomy_ids(candidate):
    ids = []
    for layer in ("integrity", "narrative"):
        for entry in candidate["failure_taxonomy"][layer]:
            ids.append(entry["id"])
            ids.extend(entry["subtypes"])
    return ids


class TestCandidateStructure(unittest.TestCase):
    def setUp(self):
        self.c = load()
        self.spec = SPEC.read_text(encoding="utf-8")

    def test_required_sections_present(self):
        self.assertEqual(REQUIRED_KEYS - set(self.c), set())

    def test_identity_and_candidate_status(self):
        self.assertEqual(self.c["contract_version"], "SCRIPT_QUALITY_CONTRACT/v0")
        self.assertEqual(self.c["status"], "CANDIDATE_REPAIRED_PENDING_ORCHESTRATOR_FREEZE_REVIEW")
        self.assertFalse(self.c["revision"]["frozen"])
        self.assertIn("`SCRIPT_QUALITY_CONTRACT/v0`", self.spec)
        # The candidate file is history; the Markdown contract was frozen later (DEC-017).
        self.assertIn("**FROZEN / ACCEPTED**", self.spec)
        self.assertNotIn("FROZEN", self.c["status"])

    def test_referenced_files_exist(self):
        paths = [self.c["specification"], self.c["human_review_template"]] + self.c["evidence_sources"]
        missing = [p for p in paths if not (REPO / p).is_file()]
        self.assertEqual(missing, [])

    def test_invariant_count_and_unique_ids(self):
        ids = [i["id"] for i in self.c["hard_invariants"]]
        names = [i["name"] for i in self.c["hard_invariants"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(12 <= len(ids) <= 20, len(ids))

    def test_invariants_agree_with_markdown(self):
        yaml_ids = {i["id"] for i in self.c["hard_invariants"]}
        defined_in_spec = set(re.findall(r"^- `(SQ-INV-\d{2})` \*\*", self.spec, flags=re.M))
        self.assertEqual(defined_in_spec, yaml_ids)

    def test_every_invariant_belongs_to_a_declared_gate(self):
        gates = {g["id"] for g in self.c["hard_gates"]["gates"]}
        self.assertEqual({i["gate"] for i in self.c["hard_invariants"]}, gates)

    def test_gate_names_agree_with_markdown_and_template(self):
        gates = {g["id"] for g in self.c["hard_gates"]["gates"]}
        statuses = set(self.c["hard_gates"]["statuses"])
        for text in (self.spec, TEMPLATE.read_text(encoding="utf-8")):
            found = set(re.findall(r"`(GATE_[A-Z_]+)`", text))
            self.assertEqual(found - statuses, gates)
        self.assertTrue(set(self.c["hard_gates"]["human_audit_required_in_v0"]) <= gates)

    def test_markdown_gate_table_matches_invariant_assignment(self):
        def expand(cell):
            out = set()
            for a, b in re.findall(r"`SQ-INV-(\d{2})`(?:–`SQ-INV-(\d{2})`)?", cell):
                out.update(f"SQ-INV-{n:02d}" for n in range(int(a), int(b or a) + 1))
            return out
        section = self.spec.split("## 15. Hard Gates")[1].split("## 16.")[0]
        statuses = set(self.c["hard_gates"]["statuses"])
        table = {m.group(1): expand(m.group(2))
                 for m in re.finditer(r"^\| `(GATE_[A-Z_]+)` \| (.+?) \|", section, flags=re.M)
                 if m.group(1) not in statuses}
        expected = {}
        for inv in self.c["hard_invariants"]:
            expected.setdefault(inv["gate"], set()).add(inv["id"])
        self.assertEqual(table, expected)


class TestFailureTaxonomy(unittest.TestCase):
    def setUp(self):
        self.c = load()
        self.ids = taxonomy_ids(self.c)
        self.spec = SPEC.read_text(encoding="utf-8")

    def test_no_duplicate_ids(self):
        duplicates = sorted({i for i in self.ids if self.ids.count(i) > 1})
        self.assertEqual(duplicates, [])

    def test_required_parent_categories(self):
        parents = {e["id"] for e in self.c["failure_taxonomy"]["integrity"]}
        self.assertEqual(REQUIRED_PARENTS - parents, set())

    def test_all_provisional_categories_still_named(self):
        provisional = set(re.findall(r"^- ([A-Z_]+)$", FAILURE_TEMPLATE.read_text(encoding="utf-8"), flags=re.M))
        self.assertGreaterEqual(len(provisional), 19)
        self.assertEqual(provisional - set(self.ids), set())

    def test_all_h6b_residual_families_map_to_a_subtype(self):
        families = set(re.findall(r"^### ([A-Z_]+)$", RESIDUAL.read_text(encoding="utf-8"), flags=re.M))
        self.assertEqual(len(families), 8)
        subtypes = {s for e in self.c["failure_taxonomy"]["integrity"] for s in e["subtypes"]}
        self.assertEqual(families - subtypes, set())

    def test_integrity_categories_have_declared_gates(self):
        gates = {g["id"] for g in self.c["hard_gates"]["gates"]}
        for entry in self.c["failure_taxonomy"]["integrity"]:
            self.assertIn(entry["gate"], gates, entry["id"])
        for entry in self.c["failure_taxonomy"]["narrative"]:
            self.assertNotIn("gate", entry, entry["id"])

    def test_taxonomy_agrees_with_markdown(self):
        section = self.spec.split("## 13. Failure Taxonomy")[1].split("**Mapping from H6b claim classes.**")[0]
        in_tables = set()
        for line in section.splitlines():
            if line.startswith("| `"):
                cells = line.split("|")
                in_tables.update(re.findall(r"`([A-Z_]+)`", cells[1] + cells[2]))
        self.assertEqual(in_tables, set(self.ids))


class TestSemantics(unittest.TestCase):
    def setUp(self):
        self.c = load()
        self.spec = SPEC.read_text(encoding="utf-8")

    def test_claim_types(self):
        ct = self.c["claim_types"]
        all_types = ct["acceptable"] + ct["violating"] + ct["review_trigger"]
        self.assertEqual(len(all_types), len(set(all_types)))
        self.assertEqual(REQUIRED_CLAIM_TYPES - set(all_types), set())
        self.assertIn("UNSUPPORTED_STORY_CLAIM", ct["violating"])
        self.assertEqual(set(ct["h6b_class_mapping"].values()) - set(all_types), set())
        for name in all_types:
            self.assertIn(f"`{name}`", self.spec)

    def test_severity_and_materiality(self):
        levels = [s["id"] for s in self.c["severity_levels"]]
        self.assertEqual(levels, ["CRITICAL", "HIGH", "MEDIUM", "LOW"])
        material = [s["id"] for s in self.c["severity_levels"] if s["material"]]
        self.assertEqual(material, self.c["hard_gates"]["material_severities"][::-1])

    def test_verdicts_ordered_and_not_averaged(self):
        self.assertEqual([v["id"] for v in self.c["verdicts"]],
                         ["FAIL", "REVIEW_REQUIRED", "PASS", "PASS_WITH_MINOR_EDITS"])
        rules = self.c["verdict_rules"]
        self.assertFalse(rules["weighted_average_used"])
        self.assertFalse(rules["absence_of_automated_findings_is_pass"])
        self.assertFalse(self.c["soft_dimensions"]["averaging_across_dimensions"])
        section = self.spec.split("## 16. Verdict Semantics")[1].split("## 17.")[0]
        order = re.findall(r"^\| `([A-Z_]+)` \|", section, flags=re.M)
        self.assertEqual(order, [v["id"] for v in self.c["verdicts"]])

    def test_soft_dimensions_and_edit_cost_agree_with_documents(self):
        template = TEMPLATE.read_text(encoding="utf-8")
        for dim in self.c["soft_dimensions"]["dimensions"]:
            self.assertIn(f"`{dim['id']}`", self.spec)
            self.assertIn(f"`{dim['id']}`", template)
        for level in self.c["edit_cost_levels"]:
            self.assertIn(f"`{level}`", self.spec)
            self.assertIn(f"`{level}`", template)

    def test_length_is_not_a_universal_number(self):
        self.assertNotIn("length_target_words", self.c.get("request_constraints", {}))
        self.assertIn("Length is a request constraint, not a universal standard.", self.spec)

    def test_creative_freedom_principle_stated(self):
        self.assertIn("Engagement may increase through presentation transformation, not through factual mutation.",
                      self.spec)


class TestValidatorEvidenceIsNotOverclaimed(unittest.TestCase):
    def setUp(self):
        self.c = load()
        self.spec = SPEC.read_text(encoding="utf-8")
        self.h7 = self.c["validator_evidence_status"]["h7_targeted_epistemic_pass"]

    def test_h7_not_labelled_confirmed(self):
        self.assertEqual(self.h7["confirmatory_verdict"], "NOT_EVALUATED")
        self.assertFalse(self.h7["stage_b_executed"])
        self.assertFalse(self.h7["stage_b_authorized"])
        self.assertFalse(self.h7["generalization_claim_allowed"])
        self.assertFalse(self.h7["stage_a"]["later_exploratory_mapping"]["confirmatory"])
        self.assertEqual(self.h7["stage_a"]["strict_mechanical_contract"], "PASS")

    def test_h7_status_matches_recorded_closure(self):
        closure = yaml.safe_load(H7_CLOSURE.read_text(encoding="utf-8"))
        self.assertEqual(closure["interpretation"]["h7_confirmatory_verdict"], self.h7["confirmatory_verdict"])
        self.assertEqual(closure["future_stage_b"]["executed"], self.h7["stage_b_executed"])
        self.assertEqual(closure["mechanical_evidence"]["run"], self.h7["stage_a"]["run"])
        self.assertEqual(closure["exploratory_metrics"]["h7_v2"]["recall"],
                         self.h7["stage_a"]["later_exploratory_mapping"]["recall"])

    def test_no_overclaim_wording(self):
        lowered = self.spec.lower()
        for phrase in ("h7 is validated", "h7 solves", "h7 is production-ready", "h7 is confirmed",
                       "h7 has been validated"):
            self.assertNotIn(phrase, lowered)
        self.assertIn("**`NOT_EVALUATED`**", self.spec)

    def test_validator_evidence_is_outside_the_standard(self):
        self.assertFalse(self.c["validator_evidence_status"]["part_of_quality_standard"])
        self.assertFalse(self.c["versioning"]["validator_evidence_updates_change_contract"])
        self.assertFalse(self.c["validator_evidence_status"]["h6b_deterministic_claim_audit"]["sufficient_as_sole_gate"])
        self.assertIn("**It is not part of the quality standard.**", self.spec)


class TestPreFreezeRepair(unittest.TestCase):
    """Checks for the pre-freeze repair that followed the operational dry-run."""

    DRY_RUN = REPO / "benchmarks/m1_script_quality/evaluations/CONTRACT_V0_DRY_RUN"
    LOCKED = {
        "RUN_0003_REVIEW.md": "c707dbed0f67c46035e1d8df5a45968ca3195a38d2ded7bbd37a89e6b66cd139",
        "RUN_0004_REVIEW.md": "75d5eea18ce10e35d926a3c3d6a23151be06c643d0a3fc59520c0c47ef58f22e",
        "DRY_RUN_SUMMARY.yaml": "2404094e05ea99c1017dca3b6d28db6aa0e30bd5478f246e1c58852808a4f2bd",
    }

    def setUp(self):
        self.c = load()
        self.spec = SPEC.read_text(encoding="utf-8")
        self.template = TEMPLATE.read_text(encoding="utf-8")

    def test_locked_first_pass_files_are_unchanged(self):
        import hashlib
        for name, expected in self.LOCKED.items():
            data = (self.DRY_RUN / name).read_bytes().replace(b"\r\n", b"\n")
            self.assertEqual(hashlib.sha256(data).hexdigest(), expected, name)

    def test_severity_measures_story_and_deliverable_impact(self):
        basis = self.c["severity_basis"]
        self.assertEqual(basis["measures"], ["impact_on_audience_understanding",
                                             "impact_on_requested_deliverable_correctness_or_usability"])
        self.assertFalse(basis["computed_from_percentage_or_count"])
        self.assertFalse(basis["percentage_bands_defined"])
        self.assertEqual([s["id"] for s in self.c["severity_levels"]], ["CRITICAL", "HIGH", "MEDIUM", "LOW"])
        self.assertIn("There are no percentage bands.", self.spec)

    def test_request_and_output_findings_can_be_material(self):
        material = set(self.c["hard_gates"]["material_severities"])
        self.assertTrue(material & set(self.c["request_compliance_severity"]))
        self.assertTrue(material & set(self.c["output_integrity_severity"]))
        self.assertIn("### 14.1 Request-compliance findings", self.spec)
        self.assertIn("### 14.2 Output-integrity findings", self.spec)
        self.assertNotIn("Requested length or scope not met", self.spec)

    def test_calibration_examples(self):
        examples = {e["id"]: e for e in self.c["calibration_examples"]}
        major, small = examples["CAL-LENGTH-MAJOR"], examples["CAL-LENGTH-SMALL"]
        self.assertEqual((major["severity"], major["gate_status"]["GATE_REQUEST_COMPLIANCE"]), ("HIGH", "GATE_FAIL"))
        self.assertEqual((small["severity"], small["gate_status"]["GATE_REQUEST_COMPLIANCE"]),
                         ("MEDIUM", "GATE_CONDITIONAL"))
        self.assertFalse(major["generalizes_to_all_similar_magnitudes"])
        self.assertEqual(major["taxonomy"], small["taxonomy"])
        section = self.spec.split("### 14.3 Calibration examples")[1].split("### 14.4")[0]
        for text in ("900–1100 words", "1648 words", "`GATE_REQUEST_COMPLIANCE` = `GATE_FAIL`",
                     "`GATE_REQUEST_COMPLIANCE` = `GATE_CONDITIONAL`"):
            self.assertIn(text, section)

    def test_added_subtypes_sit_under_existing_parent(self):
        parents = {e["id"]: e["subtypes"] for e in self.c["failure_taxonomy"]["integrity"]}
        for subtype in ("INVENTED_SPEECH", "UNSUPPORTED_DESCRIPTIVE_ATTRIBUTE"):
            self.assertIn(subtype, parents["UNSUPPORTED_INVENTION"])
        self.assertEqual(len(parents), 12)

    def test_finding_rules(self):
        rules = self.c["finding_rules"]
        self.assertFalse(rules["sentence_or_token_level_findings_required"])
        self.assertTrue(rules["multi_category"]["counted_once_in_summaries"])
        self.assertTrue(rules["multi_category"]["all_affected_gates_receive_the_finding"])
        self.assertEqual(rules["ambiguous_speaker_hedged_guess"], "UNDETERMINED")
        self.assertFalse(rules["dialogue"]["literal_source_wording_required"])
        for heading in ("### 4.4 Reconstructed and translated dialogue", "### 13.1 Recording findings",
                        "### 14.4 Cumulative escalation"):
            self.assertIn(heading, self.spec)

    def test_escalation_record_fields_agree(self):
        fields = self.c["cumulative_escalation"]["record_fields"]
        self.assertTrue(self.c["cumulative_escalation"]["member_findings_keep_their_severity"])
        for field in fields:
            self.assertIn(f"`{field}`", self.spec)
            self.assertIn(f"`{field}`", self.template)

    def test_trace_and_official_verdicts_are_distinct(self):
        self.assertFalse(self.c["verdict_rules"]["ai_only_review_can_yield_official_pass"])
        for name in self.c["verdict_kinds"]:
            self.assertIn(f"`{name}`", self.spec)
            self.assertIn(f"`{name}`", self.template)

    def test_template_has_request_record(self):
        section = self.template.split("## 0. Request Record")[1].split("## 1.")[0]
        for item in ("Requested scope", "Truth boundary", "Target language", "Target length or duration",
                     "Length tolerance", "Counting method", "Spoiler mode", "Narrative Profile constraints"):
            self.assertIn(item, section)
        self.assertTrue(self.c["request_constraints"]["counting_method_must_be_stated"])

    def test_human_audit_and_h7_status_unchanged(self):
        self.assertEqual(len(self.c["hard_gates"]["human_audit_required_in_v0"]), 5)
        h7 = self.c["validator_evidence_status"]["h7_targeted_epistemic_pass"]
        self.assertEqual((h7["stage_b_executed"], h7["confirmatory_verdict"]), (False, "NOT_EVALUATED"))


class TestPrivacy(unittest.TestCase):
    def test_new_contract_documents_have_no_source_text(self):
        cjk = re.compile("[%s-%s%s-%s]" % (chr(0x3040), chr(0x30FF), chr(0x4E00), chr(0x9FFF)))  # kana and CJK ideographs
        for path in (SPEC, CANDIDATE, TEMPLATE):
            self.assertIsNone(cjk.search(path.read_text(encoding="utf-8")), path.name)


if __name__ == "__main__":
    unittest.main()
