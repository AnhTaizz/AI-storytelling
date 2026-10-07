"""Synthetic tests for the offline M4-04B3HR structural forensics analyzer.

Synthetic fixtures and synthetic prediction artifacts only. No DEV3 artifact, gold,
credential or provider is touched.
"""
import ast
import copy
import functools
import hashlib
import inspect
import json
from pathlib import Path
import re
import tempfile
import unittest

import yaml

from tests.story_extraction import fixture_builder as fx
from tools.story_extraction import analyze_m4_04b3hr_dev3_p3_structural_failures_v1 as forensics
from tools.story_extraction import run_m4_04b3g_dev3_p3_predictions_v1 as runner_core
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import prepare_story_extraction_draft_v1_1
from tools.story_extraction.draft_coverage_v1_1 import canonical_gold_to_draft_v1_1
from tools.story_extraction.m4_04b3f_dev3_p3_protocol_v1 import (
    CASE_IDS,
    REPO_ROOT,
    canonical_json_bytes,
    normalized_file_sha256,
    sha256_bytes,
)


TOOL_FILE = REPO_ROOT / "tools/story_extraction/analyze_m4_04b3hr_dev3_p3_structural_failures_v1.py"
RECORD = REPO_ROOT / "benchmarks/m4_extraction/M4_04B3HR_DEV3_P3_STRUCTURAL_FAILURE_FORENSICS.yaml"
SYNTHETIC_WORDS = ("Mira", "captain", "opened the", "smiled")
PUBLIC_TOKEN = re.compile(r"^[A-Za-z0-9_.:/*$<>-]{1,200}$")


@functools.lru_cache(maxsize=1)
def _fixture():
    ingestion, base, gold = fx.build("c02_two_mentions_one_entity")
    scope = gold["scope"]
    context = DraftCompilerContext(
        base, scope["passage_inputs"], scope["as_of_position"], scope["profile_id"],
        "M4_04B3HR_TEST", "v1.1", "P3_DEV3_01", ingestion,
    )
    case = runner_core.CaseInput("DEV3_01", prepare_story_extraction_draft_v1_1(context), context)
    return case, canonical_gold_to_draft_v1_1(gold, context)[0]


def valid_draft():
    return copy.deepcopy(_fixture()[1])


def text(draft):
    return json.dumps(draft, ensure_ascii=False)


def broken_assertions(count):
    """Assertions in an inline shape: required keys missing, unexpected keys present."""
    draft = valid_draft()
    for item in draft["assertions"][:count]:
        del item["proposition_handle"]
        del item["support"]
        item["predicate"] = "SYNTHETIC"
        item["bad key!"] = 1
    return draft


def bad_role():
    draft = valid_draft()
    draft["mentions"][0]["role"] = "SYNTHETIC_ROLE_TOKEN"
    return draft


MALFORMED = '{"draft_version": "STORY_EXTRACTION_DRAFT_V1_1", evidence: []}'


def default_attempts():
    valid = text(valid_draft())
    return {
        "DEV3_01": (text(broken_assertions(2)), text(broken_assertions(1))),
        "DEV3_02": (text(broken_assertions(1)), json.dumps(broken_assertions(1), ensure_ascii=False, indent=1)),
        "DEV3_03": (MALFORMED, MALFORMED),
        "DEV3_04": (MALFORMED, text(bad_role())),
        "DEV3_05": (text(bad_role()), valid),
        "DEV3_06": (text(bad_role()), valid[: len(valid) // 2]),
        "DEV3_07": (valid, None),
        "DEV3_08": (text(bad_role()), text(bad_role()) + " "),
        "DEV3_09": (text(bad_role()), text(bad_role()) + "\n"),
        "DEV3_10": (text(bad_role()), text(bad_role()) + "\t"),
    }


class Workspace:
    """A synthetic locked prediction set: artifacts on disk plus a public lock file."""

    def __init__(self, test, attempts=None):
        directory = tempfile.TemporaryDirectory(prefix="m4b3hr_")
        test.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "predictions"
        for name in ("raw", "drafts", "failures", "case_results", "telemetry"):
            (self.root / name).mkdir(parents=True)
        self.lock_path = Path(directory.name) / "lock.yaml"
        cases = []
        for case_id in CASE_IDS:
            primary, repair = (attempts or default_attempts())[case_id]
            cases.append(self._case(case_id, primary, repair))
        identities = [{name: case[name] for name in forensics.IDENTITY_FIELDS} for case in cases]
        self.lock = {"cases": cases, "prediction_set_sha256": sha256_bytes(canonical_json_bytes(identities))}
        self.write_lock()

    def _case(self, case_id, primary, repair):
        recorded, terminal = {}, None
        for phase, key, raw in (("primary", "primary", primary), ("repair_1", "repair", repair)):
            if raw is None:
                recorded[key] = None
                continue
            (self.root / "raw" / f"{case_id}_{phase}.txt").write_bytes(raw.encode("utf-8"))
            attempt = forensics.replay_attempt(raw)
            draft_sha256 = None
            if attempt["json_parse"]:
                data = canonical_json_bytes(json.loads(raw))
                (self.root / "drafts" / f"{case_id}_{phase}.json").write_bytes(data)
                draft_sha256 = sha256_bytes(data)
            fingerprint = sha256_bytes(f"{case_id}:{phase}".encode("utf-8"))
            (self.root / "telemetry" / f"M4B3F_P3_{case_id}_{phase.upper()}.json").write_bytes(canonical_json_bytes({
                "request_fingerprint": fingerprint,
                "usage": {"prompt_token_count": 100 if key == "primary" else 400, "candidates_token_count": 50},
            }))
            recorded[key] = {
                "request_fingerprint": fingerprint,
                "raw_response_sha256": sha256_bytes(raw.encode("utf-8")),
                "draft_sha256": draft_sha256,
                "validation": {"pass": attempt["category"] is None, "category": attempt["category"],
                               "blockers": attempt["blockers"]},
            }
            terminal = (attempt, draft_sha256)
        attempt, terminal_draft = terminal
        valid = attempt["category"] is None
        failure_sha256 = None
        if not valid:
            data = canonical_json_bytes({"case_id": case_id, "category": attempt["category"]})
            (self.root / "failures" / f"{case_id}.json").write_bytes(data)
            failure_sha256 = sha256_bytes(data)
        result = {
            "case_id": case_id,
            "primary": recorded["primary"],
            "repair_used": recorded["repair"] is not None,
            "repair": recorded["repair"],
            "terminal_status": "STRUCTURAL_VALID" if valid else "STRUCTURAL_FAILURE",
            "terminal_draft_sha256": terminal_draft,
            "compiled_batch_sha256": sha256_bytes(b"compiled") if valid else None,
            "terminal_failure_sha256": failure_sha256,
        }
        (self.root / "case_results" / f"{case_id}.json").write_bytes(canonical_json_bytes(result))
        repair_record = recorded["repair"]
        return {
            "case_id": case_id,
            "primary_request_fingerprint": recorded["primary"]["request_fingerprint"],
            "primary_raw_response_sha256": recorded["primary"]["raw_response_sha256"],
            "repair_used": result["repair_used"],
            "repair_request_fingerprint": None if repair_record is None else repair_record["request_fingerprint"],
            "repair_raw_response_sha256": None if repair_record is None else repair_record["raw_response_sha256"],
            "terminal_status": result["terminal_status"],
            "terminal_draft_sha256": terminal_draft,
            "compiled_batch_sha256": result["compiled_batch_sha256"],
            "terminal_failure_sha256": failure_sha256,
            "primary_draft_sha256": recorded["primary"]["draft_sha256"],
            "repair_draft_sha256": None if repair_record is None else repair_record["draft_sha256"],
            "terminal_failure_category": attempt["category"],
        }

    def write_lock(self):
        data = yaml.safe_dump(self.lock, sort_keys=False).encode("utf-8")
        self.lock_path.write_bytes(data)
        self.lock_sha256 = sha256_bytes(data)

    def analyze(self):
        return forensics.analyze(
            self.root, self.lock_path,
            expected_lock_sha256=self.lock_sha256,
            expected_prediction_set_sha256=self.lock["prediction_set_sha256"],
        )


class LockedEvidenceTests(unittest.TestCase):
    def test_committed_prediction_lock_hashes_are_pinned_and_valid(self):
        self.assertEqual("850b6ea557027b7c8777c5960df0654d2d265e9e041487445dfeb9fdcf6d59f2", forensics.PUBLIC_LOCK_SHA256)
        self.assertEqual("06d555f53f6c113e3db7ab7eea55501a4b442e7e8daec3047bcc7cb3b55f38fd", forensics.PREDICTION_SET_SHA256)
        self.assertEqual(forensics.PUBLIC_LOCK_SHA256, normalized_file_sha256(forensics.PUBLIC_LOCK_PATH))
        lock = forensics.load_public_lock()
        self.assertEqual(forensics.PREDICTION_SET_SHA256, lock["prediction_set_sha256"])
        self.assertEqual(list(CASE_IDS), [case["case_id"] for case in lock["cases"]])
        self.assertEqual({"STRUCTURAL_FAILURE"}, {case["terminal_status"] for case in lock["cases"]})

    def test_lock_file_or_prediction_set_mismatch_fails_closed(self):
        workspace = Workspace(self)
        with self.assertRaisesRegex(forensics.StructuralForensicsError, "lock hash mismatch"):
            forensics.load_public_lock(workspace.lock_path, expected_sha256="0" * 64,
                                       expected_prediction_set_sha256=workspace.lock["prediction_set_sha256"])
        with self.assertRaisesRegex(forensics.StructuralForensicsError, "Prediction-set hash mismatch"):
            forensics.load_public_lock(workspace.lock_path, expected_sha256=workspace.lock_sha256,
                                       expected_prediction_set_sha256="0" * 64)
        workspace.lock["cases"][4]["primary_raw_response_sha256"] = "0" * 64
        workspace.write_lock()
        with self.assertRaisesRegex(forensics.StructuralForensicsError, "Prediction-set hash mismatch"):
            workspace.analyze()

    def test_every_locked_artifact_hash_and_fingerprint_is_validated(self):
        inventory = Workspace(self).analyze()["public"]["reproduction"]["inventory"]
        self.assertEqual({"raw_responses": 19, "parsed_drafts": 15, "failure_records": 8,
                          "case_results": 10, "request_fingerprints": 19}, inventory)
        tampering = (
            (lambda root: (root / "raw/DEV3_02_repair_1.txt").write_bytes(b"{}"), "Raw response hash"),
            (lambda root: (root / "drafts/DEV3_01_primary.json").write_bytes(b"{}\n"), "Parsed draft hash"),
            (lambda root: (root / "drafts/DEV3_03_primary.json").write_bytes(b"{}\n"), "Unlocked parsed draft"),
            (lambda root: (root / "failures/DEV3_09.json").write_bytes(b"{}\n"), "Failure record hash"),
            (lambda root: (root / "telemetry/M4B3F_P3_DEV3_05_REPAIR_1.json").write_bytes(
                canonical_json_bytes({"request_fingerprint": "0" * 64})), "Request fingerprint"),
            (lambda root: (root / "raw/DEV3_10_primary.txt").unlink(), "unavailable"),
        )
        for change, message in tampering:
            workspace = Workspace(self)
            change(workspace.root)
            with self.subTest(message=message), self.assertRaisesRegex(forensics.StructuralForensicsError, message):
                workspace.analyze()
        workspace = Workspace(self)
        path = workspace.root / "case_results/DEV3_06.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        result["primary"]["request_fingerprint"] = "0" * 64
        path.write_bytes(canonical_json_bytes(result))
        with self.assertRaisesRegex(forensics.StructuralForensicsError, "differs from the prediction lock"):
            workspace.analyze()

    def test_no_gold_holdout_input_or_provider_surface_exists(self):
        workspace = Workspace(self)
        for name in ("dev3_gold", "holdout_v1"):
            with self.assertRaisesRegex(forensics.StructuralForensicsError, "never accepted"):
                forensics.verify_locked_artifacts(workspace.root.parent / name / "predictions", workspace.lock)
        for function in (forensics.analyze, forensics.verify_locked_artifacts, forensics.replay_attempt,
                         forensics.load_public_lock, forensics.main):
            names = set(inspect.signature(function).parameters)
            self.assertFalse(any(word in name.lower() for name in names
                                 for word in ("gold", "holdout", "evaluat", "provider", "credential", "input")))
        tree = ast.parse(TOOL_FILE.read_text(encoding="utf-8"))
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
            alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertEqual(
            {"__future__", "argparse", "collections", "hashlib", "json", "pathlib", "re", "typing", "yaml",
             "tools.story_extraction.draft_compiler_v1_1", "tools.story_extraction.m4_04b3f_dev3_p3_protocol_v1"},
            modules,
        )
        source = TOOL_FILE.read_text(encoding="utf-8")
        for forbidden in ('"input"', "zipfile", "load_runtime_config", "official_client_factory", "evaluate_case"):
            self.assertNotIn(forbidden, source)
        (workspace.root / "input").mkdir()
        (workspace.root / "input" / "unit.txt").write_text("Mira opened the gate.", encoding="utf-8")
        self.assertNotIn("Mira", json.dumps(workspace.analyze()))


class ReplayTests(unittest.TestCase):
    def test_replay_matches_the_unchanged_runner_core(self):
        case = _fixture()[0]
        for raw in (text(broken_assertions(2)), text(bad_role()), MALFORMED, "", "not json"):
            _, _, validation = runner_core.compile_raw_response(raw, case)
            attempt = forensics.replay_attempt(raw)
            self.assertEqual(validation["category"], attempt["category"])
            self.assertEqual(validation["blockers"], attempt["blockers"])
            self.assertFalse(attempt["schema_pass"])
            self.assertFalse(attempt["compiler_reached"])
        passing = forensics.replay_attempt(text(valid_draft()))
        self.assertEqual((True, True, True, None, []), (passing["json_parse"], passing["schema_pass"],
                                                       passing["compiler_reached"], passing["category"],
                                                       passing["blockers"]))

    def test_schema_errors_report_keyword_field_and_owner_without_values(self):
        attempt = forensics.replay_attempt(text(broken_assertions(1)))
        keywords = {item["keyword"] for item in attempt["errors"]}
        self.assertEqual({"required", "additionalProperties"}, keywords)
        fields = {field for item in attempt["errors"] for field in item["fields"]}
        self.assertEqual({"proposition_handle", "support", "predicate", "<NON_IDENTIFIER_KEY>"}, fields)
        self.assertEqual({"V1_REFERENCED_DEFINITION_ABSENT_FROM_PROMPT"}, {item["owner"] for item in attempt["errors"]})
        self.assertNotIn("SYNTHETIC", json.dumps(attempt))
        role = forensics.replay_attempt(text(bad_role()))
        self.assertEqual(["enum"], [item["keyword"] for item in role["errors"]])
        self.assertEqual("TOKEN_ABSENT_FROM_PROMPT", role["errors"][0]["value_class"])
        self.assertNotIn("SYNTHETIC_ROLE_TOKEN", json.dumps(role))

    def test_definition_owner_distinguishes_prompt_text_from_referenced_definitions(self):
        self.assertEqual("V1_1_ROOT_PRESENT_IN_PROMPT", forensics.definition_owner(()))
        self.assertEqual("V1_1_ROOT_PRESENT_IN_PROMPT", forensics.definition_owner(("mentions",)))
        self.assertEqual("V1_1_MENTION_PRESENT_IN_PROMPT", forensics.definition_owner(("mentions", 0)))
        self.assertEqual("V1_1_MENTION_PRESENT_IN_PROMPT", forensics.definition_owner(("mentions", 0, "handle")))
        for path in (("mentions", 0, "role"), ("assertions", 3), ("events", 0), ("entities", 1, "kind"),
                     ("propositions", 2), ("evidence", 0, "role"), ("anchors", 0)):
            self.assertEqual("V1_REFERENCED_DEFINITION_ABSENT_FROM_PROMPT", forensics.definition_owner(path))
        draft = valid_draft()
        del draft["anchors"]
        draft["mentions"][0]["evidence_handle"] = "EV1"
        owners = {item["owner"] for item in forensics.replay_attempt(text(draft))["errors"]}
        self.assertEqual({"V1_1_ROOT_PRESENT_IN_PROMPT", "V1_1_MENTION_PRESENT_IN_PROMPT"}, owners)

    def test_json_failure_classes(self):
        valid = text(valid_draft())
        cases = (
            (valid, "VALID_JSON"),
            ("", "EMPTY"),
            ("   ", "EMPTY"),
            ("Here is the JSON: " + valid, "NON_JSON_PREFIX"),
            ("```json\n" + valid + "\n```", "NON_JSON_PREFIX"),
            (valid + " {}", "EXTRA_DATA_AFTER_JSON"),
            (valid[: len(valid) // 2], "TRUNCATED_OR_UNBALANCED"),
            (MALFORMED, "MALFORMED_OBJECT_MEMBER"),
            ('{"a": 1, b: 2}', "MALFORMED_OBJECT_MEMBER"),
            ('{"a": 1, }', "TRAILING_COMMA"),
            ('{"a": [1, 2, ]}', "TRAILING_COMMA"),
            ('{"a": "\\q"}', "INVALID_ESCAPING"),
            ('{"a" 1}', "OTHER_MALFORMED_STRUCTURE"),
        )
        for raw, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(expected, forensics.classify_json_failure(raw))

    def test_path_patterns_aggregate_array_indices(self):
        self.assertEqual("assertions/*", forensics.path_pattern("assertions/12"))
        self.assertEqual("mentions/*/role", forensics.path_pattern("mentions/0/role"))
        self.assertEqual("$", forensics.path_pattern("$"))
        self.assertEqual("", forensics.path_pattern(""))


class AnalysisTests(unittest.TestCase):
    def test_matrix_reproduces_terminal_categories_and_classifies_repair_effects(self):
        public = Workspace(self).analyze()["public"]
        self.assertEqual("10/10", public["reproduction"]["terminal_categories_reproduced"])
        self.assertEqual(19, public["reproduction"]["attempts_replayed"])
        self.assertEqual(17, public["reproduction"]["recorded_blocker_sets_equal_replay"])
        effects = {item["case_id"]: item["repair_effect"] for item in public["case_matrix"]}
        self.assertEqual(
            {"DEV3_01": "PARTIALLY_CLEARED", "DEV3_02": "SAME_BLOCKER", "DEV3_03": "SAME_BLOCKER",
             "DEV3_04": "DIFFERENT_BLOCKER", "DEV3_05": "CLEARED_PRIMARY_BLOCKER",
             "DEV3_06": "DEGRADED_TO_JSON_FAILURE", "DEV3_07": "NO_REPAIR", "DEV3_08": "SAME_BLOCKER",
             "DEV3_09": "SAME_BLOCKER", "DEV3_10": "SAME_BLOCKER"},
            effects,
        )
        by_case = {item["case_id"]: item for item in public["case_matrix"]}
        self.assertTrue(by_case["DEV3_03"]["primary_and_repair_raw_bytes_identical"])
        self.assertFalse(by_case["DEV3_02"]["primary_and_repair_raw_bytes_identical"])
        self.assertTrue(all(item["request_fingerprints_differ"] for item in public["case_matrix"]))
        self.assertEqual("MALFORMED_OBJECT_MEMBER", by_case["DEV3_03"]["primary"]["json_failure_class"])
        self.assertEqual("TRUNCATED_OR_UNBALANCED", by_case["DEV3_06"]["repair"]["json_failure_class"])
        self.assertEqual((2, 1, 1), (by_case["DEV3_01"]["primary"]["blocker_count"],
                                     by_case["DEV3_01"]["repair"]["blocker_count"],
                                     by_case["DEV3_01"]["blocker_paths_cleared"]))
        self.assertEqual("SCHEMA_PASS", by_case["DEV3_07"]["terminal_category"])
        aggregate = public["aggregate"]
        self.assertEqual((10, 8, 1, 1), (aggregate["primary"]["attempts"], aggregate["primary"]["valid_json"],
                                         aggregate["primary"]["schema_pass"], aggregate["primary"]["compiler_reached"]))
        self.assertEqual({"DRAFT_SCHEMA_FAILURE": 7, "JSON_PARSE_FAILURE": 2, "SCHEMA_PASS": 1},
                         aggregate["primary"]["failure_categories"])
        self.assertEqual({"assertions/*:proposition_handle": 3, "assertions/*:support": 3},
                         aggregate["primary"]["required_fields_missing"])
        self.assertEqual(9, public["repair_forensics"]["repairs"])
        self.assertEqual(9, public["repair_forensics"]["repair_prompt_grew_by_at_least_the_primary_output_tokens"])
        self.assertEqual(19, public["repair_forensics"]["recorded_blockers_have_phase_code_path_only"])

    def test_unreproduced_locked_result_is_a_reproduction_defect(self):
        workspace = Workspace(self)
        workspace.lock["cases"][7]["terminal_failure_category"] = "JSON_PARSE_FAILURE"
        workspace.write_lock()
        with self.assertRaisesRegex(forensics.StructuralForensicsError, "M4_04B3HR_LOCKED_RESULT_REPRODUCTION_DEFECT"):
            workspace.analyze()
        workspace = Workspace(self)
        path = workspace.root / "case_results/DEV3_02.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        result["primary"]["validation"]["category"] = "DRAFT_COMPILER_FAILURE"
        path.write_bytes(canonical_json_bytes(result))
        with self.assertRaisesRegex(forensics.StructuralForensicsError, "M4_04B3HR_LOCKED_RESULT_REPRODUCTION_DEFECT"):
            workspace.analyze()

    def test_public_output_contains_structure_only(self):
        result = Workspace(self).analyze()
        for name in ("public", "private"):
            serialized = json.dumps(result[name], ensure_ascii=False)
            quotes = tuple(item["quote"] for item in valid_draft()["evidence"] + valid_draft()["mentions"])
            for word in SYNTHETIC_WORDS + ("SYNTHETIC", "bad key!") + quotes:
                self.assertNotIn(word, serialized, name)

        def leaves(value):
            if isinstance(value, dict):
                return list(value) + [leaf for child in value.values() for leaf in leaves(child)]
            if isinstance(value, list):
                return [leaf for child in value for leaf in leaves(child)]
            return [value]

        for leaf in leaves(result["public"]):
            self.assertTrue(leaf is None or type(leaf) in (bool, int) or PUBLIC_TOKEN.fullmatch(leaf), leaf)


class PromptSchemaAuditTests(unittest.TestCase):
    def test_locked_prompt_omits_the_definitions_its_schema_references(self):
        audit = forensics.prompt_schema_audit()
        self.assertTrue(audit["prompt_schema_section_is_the_v1_1_schema_file"])
        self.assertFalse(audit["v1_schema_text_in_prompt"])
        self.assertTrue(audit["v1_schema_id_appears_only_as_ref_target"])
        self.assertEqual(["Mention"], audit["definitions_present_in_prompt"])
        self.assertEqual(
            ["Assertion", "Entity", "Event", "Evidence", "EvidenceRole", "Proposition", "TemporalAnchor"],
            audit["definitions_referenced_but_absent_from_prompt"],
        )
        definitions = audit["referenced_definitions"]
        self.assertEqual("ABSENT_FROM_PROMPT", definitions["Assertion"]["required_keys"]["proposition_handle"])
        self.assertEqual("ABSENT_FROM_PROMPT", definitions["Assertion"]["required_keys"]["epistemic_status"])
        self.assertEqual("IMPLICIT_ONLY", definitions["Assertion"]["required_keys"]["support"])
        self.assertEqual("ABSENT_FROM_PROMPT", definitions["Event"]["required_keys"]["anchor_handle"])
        self.assertEqual("ABSENT_FROM_PROMPT", definitions["TemporalAnchor"]["required_keys"]["anchor_kind"])
        self.assertEqual((5, 3), (definitions["EvidenceRole"]["enum_values_total"],
                                  definitions["EvidenceRole"]["enum_values_appearing_anywhere_in_prompt"]))
        self.assertFalse(audit["provider_response_schema_used"])
        sections = forensics.prompt_sections()
        prompt = "".join(sections.values())
        for key in ("proposition_handle", "anchor_handle", "evidence_sets", "evidence_handles", "premise_handles",
                    "epistemic_status", "anchor_kind", "event_handle", "derivations", "rule_id"):
            self.assertNotIn(key, prompt, key)
        for key in ('"handle"', '"passage_handle"', '"quote"', '"occurrence"', '"role"', '"surface_form"'):
            self.assertIn(key, sections["schema_section"], key)


class PublicRecordTests(unittest.TestCase):
    def setUp(self):
        self.text = RECORD.read_text(encoding="utf-8")
        self.record = yaml.safe_load(self.text)

    def test_record_binds_the_locked_evidence_and_reproduces_it(self):
        record = self.record
        self.assertEqual("M4_04B3HR_STRUCTURAL_FORENSICS_COMPLETE", record["status"])
        self.assertEqual(forensics.PREDICTION_SET_SHA256, record["prediction_set_sha256"])
        self.assertEqual(forensics.PUBLIC_LOCK_SHA256, record["locked_evidence"]["public_prediction_lock_sha256"])
        self.assertEqual("PASS", record["reproduction"]["locked_artifact_hashes"])
        self.assertEqual("10/10", record["reproduction"]["terminal_categories_reproduced"])
        self.assertEqual(normalized_file_sha256(TOOL_FILE), record["tooling"]["analyzer"]["sha256"])
        self.assertEqual(normalized_file_sha256(Path(__file__)), record["tooling"]["focused_tests"]["sha256"])
        self.assertEqual(0, record["boundaries"]["provider_calls"])
        for name in ("DEV3_gold_opened", "holdout_opened", "semantic_scoring", "predictions_rerun",
                     "DEV3_input_used_for_forensics"):
            self.assertIs(False, record["boundaries"][name])
        self.assertIs(True, record["boundaries"]["DEV3_input_source_lines_read_by_publication_leak_scan"])

    def test_record_counts_are_internally_consistent(self):
        aggregate = self.record["aggregate"]
        for key in ("primary", "repair"):
            bucket = aggregate[key]
            self.assertEqual(10, bucket["attempts"])
            self.assertEqual(10, sum(bucket["failure_categories"].values()))
            self.assertEqual(sum(bucket["blocker_codes"].values()), sum(bucket["blocker_path_patterns"].values()))
            self.assertEqual(sum(bucket["schema_keywords"].values()),
                             sum(bucket["schema_errors_by_definition_owner"].values()))
            self.assertEqual(0, bucket["schema_pass"])
            self.assertEqual(0, bucket["compiler_reached"])
        self.assertEqual(10, sum(aggregate["repair_effects"].values()))
        matrix = self.record["case_matrix"]
        self.assertEqual(list(CASE_IDS), [item["case_id"] for item in matrix])
        self.assertTrue(all(item["terminal_category_reproduced"] for item in matrix))
        lock = forensics.load_public_lock()
        for item, case in zip(matrix, lock["cases"]):
            self.assertEqual(case["terminal_failure_category"], item["terminal_category"])
        self.assertEqual({"DRAFT_SCHEMA_FAILURE": 9, "JSON_PARSE_FAILURE": 1}, aggregate["repair"]["failure_categories"])

    def test_record_states_the_known_h0_fact_without_a_formal_decision(self):
        fact = self.record["h0_known_fact"]
        self.assertEqual((0, 10), (fact["l0_valid_final_case_count"], fact["required"]))
        self.assertIs(False, fact["safety_gate_can_pass"])
        self.assertIs(False, fact["formal_decide_invoked"])
        self.assertEqual("REMAINING_GOLD_DEPENDENT_OBSERVATIONS_NOT_FABRICATED", fact["reason"])

    def test_record_is_public_safe(self):
        self.assertTrue(all(ord(char) < 128 for char in self.text))

        def leaves(value):
            if isinstance(value, dict):
                return list(value) + [leaf for child in value.values() for leaf in leaves(child)]
            if isinstance(value, list):
                return [leaf for child in value for leaf in leaves(child)]
            return [value]

        for section in ("aggregate", "case_matrix", "reproduction", "repair_forensics"):
            for leaf in leaves(self.record[section]):
                self.assertTrue(leaf is None or type(leaf) in (bool, int) or PUBLIC_TOKEN.fullmatch(leaf), leaf)


if __name__ == "__main__":
    unittest.main()
