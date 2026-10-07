"""Offline tests for the P4 self-contained output contract (M4-04B4A).

Synthetic drafts and public tracked files only. No DEV3 artifact, gold, credential or
provider is touched; the provider SDK is inspected through its types and a fake client.
"""
import ast
import copy
import functools
import hashlib
import json
import os
from pathlib import Path
import tempfile
import types as python_types
import unittest
from unittest import mock

from jsonschema import Draft202012Validator
import yaml

from tests.story_extraction import fixture_builder as fx
from tools.story_extraction import draft_compiler_v1_1 as compiler
from tools.story_extraction import m4_04b3h0_dev3_decision_lock_v1 as decision_lock
from tools.story_extraction import m4_04b4a_p4_output_contract_v1 as p4
from tools.story_extraction import materialize_draft_v1_1_model_schema_v1 as materializer
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_coverage_v1_1 import canonical_gold_to_draft_v1_1
from tools.story_extraction.m4_04b3f_dev3_p3_protocol_v1 import (
    MAX_OUTPUT_TOKENS as P3_MAX_OUTPUT_TOKENS,
    MAX_STRUCTURAL_REPAIRS_PER_CASE as P3_MAX_REPAIRS,
    REPO_ROOT,
    TEMPERATURE as P3_TEMPERATURE,
    normalized_file_sha256,
    prompt_hashes as p3_prompt_hashes,
    prompt_material as p3_prompt_material,
)


MODEL_SCHEMA_SHA256 = "5aa2ed6dde3791546ddd5e059648d8dac38df1571a6073b7abc31c89eb257f14"
P3_SCHEMA_MARKER = "EXACT STORY_EXTRACTION_DRAFT_V1_1 JSON SCHEMA:"
RECORD = REPO_ROOT / "benchmarks/m4_extraction/M4_04B4A_P4_OUTPUT_CONTRACT_REDESIGN.yaml"
MATERIALIZER_FILE = REPO_ROOT / "tools/story_extraction/materialize_draft_v1_1_model_schema_v1.py"
CONTRACT_FILE = REPO_ROOT / "tools/story_extraction/m4_04b4a_p4_output_contract_v1.py"
SECRET = "SECRET_STORY_VALUE"


def maximal_draft():
    """A hand-built valid Draft V1.1 that exercises every definition and every variant."""
    return {
        "draft_version": "STORY_EXTRACTION_DRAFT_V1_1",
        "evidence": [
            {"handle": "EV1", "passage_handle": "P1", "quote": "alpha", "role": "DEPICTION"},
            {"handle": "EV2", "passage_handle": "P2", "quote": "beta", "occurrence": 2, "role": "IN_WORLD_REPORT"},
        ],
        "mentions": [
            {"handle": "M1", "passage_handle": "P1", "quote": "alpha", "role": "NARRATION_SUMMARY", "surface_form": "alpha"},
            {"handle": "M2", "passage_handle": "P1", "quote": "a", "occurrence": 1, "role": "PARATEXT"},
        ],
        "entities": [
            {"handle": "E_NEW_1", "kind": "CHARACTER"},
            {"handle": "E_NEW_2", "kind": "GROUP", "placeholder": True, "editorial_label": "label"},
        ],
        "events": [{"handle": "EVT1", "event_kind": "motion", "anchor_handle": "T1", "editorial_label": "e"}],
        "anchors": [
            {"handle": "T1", "anchor_kind": "EVENT_TIME", "event_handle": "EVT1"},
            {"handle": "T2", "anchor_kind": "NAMED_TIME", "editorial_label": "dawn"},
        ],
        "propositions": [
            {"handle": "PROP1", "predicate": "Occurred", "args": {
                "event": {"kind": "EVENT", "handle": "EVT1"},
                "who": {"kind": "ENTITY", "handle": "E_EXISTING_1"},
                "when": {"kind": "ANCHOR", "handle": "T2"},
                "m": {"kind": "MENTION", "handle": "M1"},
                "p": {"kind": "PROPOSITION", "handle": "PROP2"},
                "lit": {"kind": "LITERAL", "value_type": "STRING", "value": "x"},
                "num": {"kind": "LITERAL", "value_type": "NUMBER", "value": 3},
                "flag": {"kind": "LITERAL", "value_type": "BOOLEAN", "value": True},
                "tok": {"kind": "TOKEN", "vocabulary": "polarity", "value": "AFFIRMED"},
            }},
            {"handle": "PROP2", "placeholder": True, "editorial_label": "unknown"},
        ],
        "assertions": [
            {"handle": "A1", "proposition_handle": "PROP1", "polarity": "AFFIRMED", "epistemic_status": "EXPLICIT",
             "validity": {"start": {"kind": "OPEN"}, "end": {"kind": "ANCHOR", "anchor_handle": "T1", "support": {
                 "evidence_sets": [{"label": "CORROBORATING", "evidence_handles": ["EV2"]}], "derivations": []}}},
             "support": {
                 "evidence_sets": [{"label": "SUFFICIENT", "evidence_handles": ["EV1", "EV2"]},
                                   {"label": "PARTIAL", "evidence_handles": ["EV_EXISTING_1"]}],
                 "derivations": [{"rule_id": "RULE_ONE", "premise_handles": ["A_EXISTING_1", "A2"]}]},
             "textual_ambiguity": {"alternative_proposition_handles": ["PROP2"]}},
            {"handle": "A2", "proposition_handle": "PROP_EXISTING_3", "polarity": "OPEN", "epistemic_status": "ENTAILED",
             "support": {"evidence_sets": [], "derivations": []}},
        ],
    }


@functools.lru_cache(maxsize=1)
def fixture_drafts():
    drafts = {}
    for name in fx.CASES:
        ingestion, base, gold = fx.build(name)
        scope = gold["scope"]
        context = DraftCompilerContext(base, scope["passage_inputs"], scope["as_of_position"], scope["profile_id"],
                                       "M4_04B4A_TEST", "v1.1", name, ingestion)
        drafts[name] = canonical_gold_to_draft_v1_1(gold, context)[0]
    return drafts


REPLACEMENTS = (None, True, False, 0, 1, -1, 1.5, "", "x", "AFFIRMED", "EV1", "P1", [], ["x"], {}, {"kind": "OPEN"})


def mutants(draft):
    """Single-edit variants of a draft: every key removed, added and every value replaced."""
    def paths(node, prefix=()):
        yield prefix
        if isinstance(node, dict):
            for key, value in node.items():
                yield from paths(value, prefix + (key,))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                yield from paths(value, prefix + (index,))

    def get(node, path):
        for part in path:
            node = node[part]
        return node

    def edited(path, change):
        clone = copy.deepcopy(draft)
        if not path:
            return change(clone)
        parent = get(clone, path[:-1])
        result = change(parent[path[-1]])
        if result is DELETE:
            del parent[path[-1]]
        else:
            parent[path[-1]] = result
        return clone

    DELETE = object()
    for path in paths(draft):
        value = get(draft, path)
        if path and isinstance(get(draft, path[:-1]), dict):
            yield edited(path, lambda _: DELETE)
        for replacement in REPLACEMENTS:
            if replacement != value or type(replacement) is not type(value):
                yield edited(path, lambda _, r=replacement: copy.deepcopy(r))
        if isinstance(value, dict):
            yield edited(path, lambda node: {**node, "zz_unexpected": 1})
        elif isinstance(value, list) and value:
            yield edited(path, lambda node: node + [copy.deepcopy(node[0])])
            yield edited(path, lambda node: node[:-1])
        elif isinstance(value, str) and value:
            yield edited(path, lambda node: node + "_x")
            yield edited(path, lambda node: node.lower())
            yield edited(path, lambda node: "9" + node)
            yield edited(path, lambda node: node * 80)
        elif isinstance(value, int) and not isinstance(value, bool):
            yield edited(path, lambda node: node + 1)


def _error_signature(error):
    """Path, keyword and, for oneOf, the findings of every variant, recursively."""
    nested = tuple(sorted((tuple(map(str, child.relative_schema_path))[:1], _error_signature(child))
                          for child in (error.context or [])))
    return (tuple(map(str, error.absolute_path)), str(error.validator), nested)


def signature(validator, draft):
    return sorted(_error_signature(error) for error in validator.iter_errors(draft))


def signature_keywords(items):
    found = set()
    for _, keyword, nested in items:
        found.add(keyword)
        found |= signature_keywords(child for _, child in nested)
    return found


class MaterializerTests(unittest.TestCase):
    def setUp(self):
        self.schema = materializer.materialize_model_schema()

    def test_materialization_is_deterministic_and_matches_the_tracked_file(self):
        self.assertEqual(self.schema, materializer.materialize_model_schema())
        text = materializer.model_schema_text()
        self.assertEqual(text, materializer.model_schema_text(copy.deepcopy(self.schema)))
        self.assertEqual(MODEL_SCHEMA_SHA256, hashlib.sha256(text.encode("utf-8")).hexdigest())
        self.assertEqual(MODEL_SCHEMA_SHA256, materializer.model_schema_sha256())
        self.assertEqual(MODEL_SCHEMA_SHA256, normalized_file_sha256(materializer.MODEL_SCHEMA_PATH))
        self.assertEqual(self.schema, materializer.load_tracked_model_schema())
        self.assertEqual("STORY_EXTRACTION_DRAFT_V1_1_MODEL_SCHEMA_V1", self.schema["title"])
        Draft202012Validator.check_schema(self.schema)

    def test_tracked_file_cannot_drift_from_the_materializer(self):
        with tempfile.TemporaryDirectory() as directory:
            drifted = Path(directory) / "schema.json"
            edited = copy.deepcopy(self.schema)
            edited["$defs"]["Assertion"]["required"].remove("support")
            drifted.write_text(materializer.model_schema_text(edited), encoding="utf-8")
            with mock.patch.object(materializer, "MODEL_SCHEMA_PATH", drifted):
                with self.assertRaisesRegex(materializer.ModelSchemaError, "differs from the materializer"):
                    materializer.load_tracked_model_schema()

    def test_no_external_reference_and_every_reference_resolves(self):
        report = materializer.assert_self_contained(self.schema)
        self.assertEqual({"external_ref_count": 0, "ref_count": 30, "definition_count": 17}, report)
        self.assertEqual([], materializer.external_refs(self.schema))
        for ref in materializer.iter_refs(self.schema):
            self.assertTrue(ref.startswith("#/$defs/"), ref)
            self.assertIsInstance(materializer.resolve_local_ref(self.schema, ref), dict)
        self.assertNotIn("urn:ai-storytelling:story-extraction:draft:v1#", materializer.model_schema_text())

    def test_self_containment_gate_fails_closed(self):
        cases = (
            (lambda s: s["properties"]["evidence"]["items"].update({"$ref": "urn:ai-storytelling:story-extraction:draft:v1#/$defs/Evidence"}), "external or unresolved"),
            (lambda s: s["properties"]["evidence"]["items"].update({"$ref": "#/$defs/Missing"}), "external or unresolved"),
            (lambda s: s["properties"]["evidence"]["items"].update({"$ref": "other.json#/$defs/Evidence"}), "external or unresolved"),
            (lambda s: s["$defs"].update({"Orphan": {"type": "string"}}), "unreferenced definition"),
            (lambda s: s["$defs"]["Handle"].update({"$anchor": "handle"}), "Dynamic or anchored"),
            (lambda s: s["$defs"].pop("Support"), "external or unresolved"),
        )
        for change, message in cases:
            schema = copy.deepcopy(self.schema)
            change(schema)
            with self.subTest(message=message), self.assertRaisesRegex(materializer.ModelSchemaError, message):
                materializer.assert_self_contained(schema)

    def test_mention_keeps_the_v1_1_definition_without_evidence_handle(self):
        v1 = json.loads(materializer.V1_SCHEMA_PATH.read_text(encoding="utf-8"))
        v1_1 = json.loads(materializer.V1_1_SCHEMA_PATH.read_text(encoding="utf-8"))
        mention = self.schema["$defs"]["Mention"]
        self.assertNotIn("evidence_handle", mention["properties"])
        self.assertIn("evidence_handle", v1["$defs"]["Mention"]["properties"])
        self.assertEqual({"$ref": "#/$defs/EvidenceRole"}, mention["properties"]["role"])
        expected = copy.deepcopy(v1_1["$defs"]["Mention"])
        expected["properties"]["role"] = {"$ref": "#/$defs/EvidenceRole"}
        self.assertEqual(expected, mention)

    def test_equivalence_by_construction_and_no_silent_relaxation(self):
        report = materializer.verify_equivalence_by_construction(self.schema)
        self.assertTrue(all(report["checks"].values()))
        self.assertEqual(["Mention"], report["definitions_from_draft_v1_1"])
        self.assertEqual(["Mention"], report["draft_v1_definitions_not_needed"])
        self.assertEqual(16, len(report["definitions_copied_from_draft_v1"]))
        relaxations = (
            lambda s: s["$defs"]["Assertion"]["required"].remove("support"),
            lambda s: s["$defs"]["Assertion"].update(additionalProperties=True),
            lambda s: s["$defs"]["EvidenceRole"]["enum"].append("AGENT"),
            lambda s: s["$defs"]["Mention"]["properties"].update(evidence_handle={"type": "string"}),
            lambda s: s["$defs"]["Handle"].update(pattern=".*"),
            lambda s: s["$defs"]["Proposition"]["oneOf"].pop(),
            lambda s: s["required"].remove("anchors"),
            lambda s: s["properties"]["draft_version"].update(const="STORY_EXTRACTION_DRAFT_V1"),
        )
        for relax in relaxations:
            schema = copy.deepcopy(self.schema)
            relax(schema)
            with self.assertRaises(materializer.ModelSchemaError):
                materializer.verify_equivalence_by_construction(schema)


class SemanticEquivalenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canonical = compiler._validator()
        cls.model = Draft202012Validator(materializer.materialize_model_schema())

    def test_valid_drafts_are_accepted_by_both(self):
        drafts = dict(fixture_drafts(), maximal=maximal_draft())
        self.assertEqual(27, len(drafts))
        for name, draft in drafts.items():
            with self.subTest(name=name):
                self.assertEqual([], signature(self.canonical, draft))
                self.assertEqual([], signature(self.model, draft))
                compiler.validate_draft_v1_1(draft)

    def test_every_enum_token_is_accepted_in_place_by_both(self):
        schema = materializer.materialize_model_schema()["$defs"]
        places = (
            (("evidence", 0, "role"), schema["EvidenceRole"]["enum"]),
            (("mentions", 0, "role"), schema["EvidenceRole"]["enum"]),
            (("entities", 0, "kind"), schema["EntityKind"]["enum"]),
            (("assertions", 0, "polarity"), schema["Assertion"]["properties"]["polarity"]["enum"]),
            (("assertions", 0, "epistemic_status"), schema["Assertion"]["properties"]["epistemic_status"]["enum"]),
            (("assertions", 0, "support", "evidence_sets", 0, "label"), schema["EvidenceSet"]["properties"]["label"]["enum"]),
            (("propositions", 0, "args", "who", "kind"), schema["Argument"]["oneOf"][0]["properties"]["kind"]["enum"]),
            (("propositions", 0, "args", "lit", "value_type"), ["STRING", "DATE"]),
        )
        checked = 0
        for path, tokens in places:
            for token in tokens:
                draft = maximal_draft()
                node = draft
                for part in path[:-1]:
                    node = node[part]
                node[path[-1]] = token
                self.assertEqual([], signature(self.canonical, draft), (path, token))
                self.assertEqual([], signature(self.model, draft), (path, token))
                checked += 1
        self.assertEqual(31, checked)

    def test_mutation_corpus_gets_identical_findings_from_both(self):
        # A deterministic 1-in-N sample keeps the suite fast. Set M4_FULL_EQUIVALENCE_CORPUS=1
        # to validate every single-edit mutant of all four base drafts (13,518 drafts).
        full = os.environ.get("M4_FULL_EQUIVALENCE_CORPUS") == "1"
        bases = [(maximal_draft(), 1 if full else 3), (fixture_drafts()["c04_later_same_as"], 1 if full else 5)]
        if full:
            bases += [(fixture_drafts()[name], 1) for name in ("c17_conceal_convey", "c21_state_end_learned_later")]
        total = rejected = accepted = 0
        keywords, collections = set(), set()
        for base, stride in bases:
            for index, draft in enumerate(mutants(base)):
                if index % stride:
                    continue
                expected = signature(self.canonical, draft)
                self.assertEqual(expected, signature(self.model, draft))
                total += 1
                rejected += bool(expected)
                accepted += not expected
                keywords |= signature_keywords(expected)
                collections.update(item[0][0] for item in expected if item[0])
        self.assertGreater(total, 13000 if full else 1300)
        self.assertGreater(rejected, 1100)
        self.assertGreater(accepted, 10)
        self.assertEqual(
            {"required", "additionalProperties", "enum", "type", "const", "pattern", "oneOf", "minLength",
             "maxLength", "minimum", "minItems", "uniqueItems", "minProperties", "not"},
            keywords,
        )
        self.assertEqual({"draft_version", "evidence", "mentions", "entities", "events", "anchors",
                          "propositions", "assertions"}, collections)

    def test_targeted_rules_are_rejected_by_both(self):
        def edit(change):
            draft = maximal_draft()
            change(draft)
            return draft

        cases = {
            "mention evidence_handle": lambda d: d["mentions"][0].update(evidence_handle="EV1"),
            "occurrence zero": lambda d: d["evidence"][1].update(occurrence=0),
            "occurrence negative": lambda d: d["mentions"][1].update(occurrence=-1),
            "occurrence fraction": lambda d: d["evidence"][1].update(occurrence=1.5),
            "occurrence string": lambda d: d["evidence"][1].update(occurrence="1"),
            "occurrence boolean": lambda d: d["evidence"][1].update(occurrence=True),
            "missing top-level array": lambda d: d.pop("anchors"),
            "unexpected top-level key": lambda d: d.update(envelope={}),
            "wrong draft version": lambda d: d.update(draft_version="STORY_EXTRACTION_DRAFT_V1"),
            "assertion inline predicate": lambda d: d["assertions"][0].update(predicate="Occurred"),
            "assertion without proposition": lambda d: d["assertions"][0].pop("proposition_handle"),
            "support without derivations": lambda d: d["assertions"][0]["support"].pop("derivations"),
            "empty evidence set": lambda d: d["assertions"][0]["support"]["evidence_sets"][0].update(evidence_handles=[]),
            "duplicate evidence handle": lambda d: d["assertions"][0]["support"]["evidence_sets"][0].update(evidence_handles=["EV1", "EV1"]),
            "derivation rule pattern": lambda d: d["assertions"][0]["support"]["derivations"][0].update(rule_id="rule"),
            "bound anchor without handle": lambda d: d["assertions"][0]["validity"]["end"].pop("anchor_handle"),
            "validity without start": lambda d: d["assertions"][0]["validity"].pop("start"),
            "event without anchor": lambda d: d["events"][0].pop("anchor_handle"),
            "event time anchor without event": lambda d: d["anchors"][0].pop("event_handle"),
            "named time anchor with event": lambda d: d["anchors"][1].update(event_handle="EVT1"),
            "proposition both variants": lambda d: d["propositions"][0].update(placeholder=True),
            "proposition empty args": lambda d: d["propositions"][0].update(args={}),
            "argument unknown kind": lambda d: d["propositions"][0]["args"]["who"].update(kind="PERSON"),
            "literal without value_type": lambda d: d["propositions"][0]["args"]["lit"].pop("value_type"),
            "entity handle pattern": lambda d: d["entities"][0].update(handle="E1"),
            "handle pattern": lambda d: d["assertions"][0].update(proposition_handle="PROPOSITION_1"),
            "editorial label too long": lambda d: d["entities"][1].update(editorial_label="x" * 201),
        }
        for name, change in cases.items():
            draft = edit(change)
            expected = signature(self.canonical, draft)
            with self.subTest(name=name):
                self.assertTrue(expected)
                self.assertEqual(expected, signature(self.model, draft))
        without_occurrence = edit(lambda d: d["evidence"][1].pop("occurrence"))
        self.assertEqual([], signature(self.canonical, without_occurrence))
        self.assertEqual([], signature(self.model, without_occurrence))


class HistoricalStackUnchangedTests(unittest.TestCase):
    def test_p3_files_schemas_compiler_and_registry_are_unchanged(self):
        self.assertTrue(all(value == "PASS" for value in decision_lock.validate_protected_stacks().values()))
        self.assertEqual("3038772889aac164318bf379c6f8ccb001800787d6cf3bf6f9633dbc5e02ce63",
                         p3_prompt_hashes()["primary_system_sha256"])
        pinned = {
            "schemas/story_extraction/story_extraction_draft_v1.schema.json":
                "7993db7bdce15e461a0483ec3e4bf5cf7596b49393fab477d9d25d61bd1f0f15",
            "schemas/story_extraction/story_extraction_draft_v1_1.schema.json":
                "e0d38b65f0f265dfb1a0ef2be4e85c9b3950550a46f47e8980fbd6a7cab068a3",
            "tools/story_extraction/draft_compiler_v1_1.py":
                "f962e561a7801ddf48ef248416231673e1567b9eac9d04f2aaba1d1e16eed953",
            "schemas/canonical_story/predicate_registry_v0.yaml":
                "44f3eafc6982f84bcc74ccb91abe7cd467a453352ee96be147095f27559c5350",
            "tools/story_extraction/run_m4_04b3h_dev3_p3_live_v1_1.py":
                "2cd6f40178fa5390171b83c8e2401ff691bd8555fd6efa2bfbceb23bf4fe311b",
            "benchmarks/m4_extraction/M4_04B3H_DEV3_P3_PREDICTION_LOCK.yaml":
                "850b6ea557027b7c8777c5960df0654d2d265e9e041487445dfeb9fdcf6d59f2",
        }
        for path, expected in pinned.items():
            self.assertEqual(expected, normalized_file_sha256(REPO_ROOT / path), path)


class PromptTests(unittest.TestCase):
    def setUp(self):
        self.material = p4.prompt_material()
        self.system = self.material["primary_system"]

    def test_prompt_really_contains_the_complete_model_schema(self):
        schema = p4.extract_prompt_schema(self.system, p4.SCHEMA_SECTION_MARKER, p4.REGISTRY_SECTION_MARKER)
        self.assertEqual(materializer.load_tracked_model_schema(), schema)
        self.assertEqual(0, len(materializer.external_refs(schema)))
        self.assertIn(materializer.model_schema_text().rstrip(), self.system)
        for key in ('"proposition_handle"', '"anchor_handle"', '"evidence_sets"', '"epistemic_status"',
                    '"anchor_kind"', '"premise_handles"', '"Assertion"', '"EvidenceRole"'):
            self.assertIn(key, self.system, key)
            self.assertNotIn(key, p3_prompt_material()["primary_system"], key)
        self.assertNotIn("appended exact Draft V1.1 schema", self.system)
        self.assertTrue(self.material["repair_system"].startswith(self.system))
        self.assertIn(p4.REPAIR_SYSTEM_SUFFIX, self.material["repair_system"])

    def test_preamble_keeps_the_p3_semantic_instructions(self):
        p3 = (p4.PROMPT_ROOT / "story_extraction_draft_p3_v1_1_system.txt").read_text(encoding="utf-8").replace("\r\n", "\n")
        new = p4.SYSTEM_PREAMBLE_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
        removed = [line for line in p3.split("\n") if line not in new.split("\n")]
        self.assertEqual(
            ["STORY EXTRACTION DRAFT P3 V1.1",
             "Return exactly one JSON object conforming to STORY_EXTRACTION_DRAFT_V1_1. Return no",
             "Markdown, prose, code fence, commentary, alternate answer, or canonical batch. The",
             "host compiles the draft deterministically. Do not reproduce trusted host metadata.",
             "- Emit all eight required top-level arrays, including empty arrays, and only schema keys.",
             "The appended exact Draft V1.1 schema and predicate registry are authoritative. If an"],
            removed,
        )
        for section in ("INPUT AND LOCAL HANDLES", "EXACT EVIDENCE AND MENTIONS", "HOST-OWNED FIELDS - NEVER OUTPUT"):
            start = p3.index(section)
            self.assertIn(p3[start: p3.index("\n\n", start)], new, section)

    def test_prompts_carry_no_dataset_or_case_specific_text(self):
        for text in self.material.values():
            for word in ("DEV3", "DEV2", "DEV1", "holdout", "gold batch"):
                self.assertNotIn(word, text)
        self.assertNotIn("DEV", materializer.model_schema_text())

    def test_user_and_repair_prompts_render_deterministically(self):
        prepared = {"draft_version": "STORY_EXTRACTION_DRAFT_V1_1", "passages": [], "existing_context": {}}
        first = p4.render_primary_user("CASE_A", prepared)
        self.assertEqual(first, p4.render_primary_user("CASE_A", dict(reversed(list(prepared.items())))))
        self.assertIn("CASE CASE_A", first)
        diagnostic = p4.structural_diagnostic_v2("{")
        repair = p4.render_repair_user("CASE_A", prepared, "{", diagnostic)
        self.assertIn("STRUCTURAL_DIAGNOSTIC_V2_JSON", repair)
        self.assertIn("UNTERMINATED_JSON", repair)
        with self.assertRaises(p4.OutputContractError):
            p4.render_primary_user("CASE_A", {"draft_version": "STORY_EXTRACTION_DRAFT_V1"})
        with self.assertRaises(p4.OutputContractError):
            p4.render_repair_user("CASE_A", prepared, "{}", p4.structural_diagnostic_v2(json.dumps(maximal_draft())))
        with self.assertRaises(p4.OutputContractError):
            p4.render_repair_user("CASE_A", prepared, "", diagnostic)
        self.assertEqual((1, P3_MAX_REPAIRS), (p4.MAX_STRUCTURAL_REPAIRS_PER_CASE, 1))


class PromptCoverageGateTests(unittest.TestCase):
    def test_every_structural_rule_reaches_the_model_through_the_schema(self):
        report = p4.assert_prompt_coverage()
        self.assertEqual(318, report["structural_requirements"])
        self.assertEqual({"MODEL_SCHEMA": 318}, report["by_availability"])
        self.assertEqual(0, report["unavailable_count"])
        self.assertEqual([], report["definitions_missing_from_prompt_schema"])
        self.assertEqual(0, report["prompt_schema_external_ref_count"])
        self.assertEqual(
            {"ALLOWED_PROPERTY", "CONDITIONAL_RULE", "CONSTANT", "ENUM_TOKEN", "HANDLE_OR_TOKEN_PATTERN",
             "ONE_OF_VARIANT", "REFERENCE", "REQUIRED_FIELD", "TYPE_OR_COLLECTION_SHAPE", "VALUE_BOUND"},
            set(report["by_family"]),
        )
        self.assertEqual(18, len(report["definitions_required"]))

    def test_the_gate_would_have_stopped_p3_before_any_request(self):
        p3_system = p3_prompt_material()["primary_system"]
        report = p4.audit_prompt_coverage(p3_system, P3_SCHEMA_MARKER, p4.REGISTRY_SECTION_MARKER)
        self.assertEqual(318, report["structural_requirements"])
        self.assertEqual(214, report["unavailable_count"])
        self.assertEqual(7, report["prompt_schema_external_ref_count"])
        self.assertEqual(16, len(report["definitions_missing_from_prompt_schema"]))
        for name in ("Assertion", "Evidence", "EvidenceRole", "Entity", "Event", "TemporalAnchor", "Proposition"):
            self.assertIn(name, report["definitions_missing_from_prompt_schema"])
            self.assertGreater(report["unavailable_by_definition"][name], 0)
        self.assertNotIn("Mention", report["unavailable_by_definition"])
        delta = json.dumps(json.loads(materializer.V1_1_SCHEMA_PATH.read_text(encoding="utf-8")), indent=2)
        system = p4.prompt_material()["primary_system"]
        broken = system.replace(materializer.model_schema_text().rstrip(), delta)
        with self.assertRaisesRegex(p4.OutputContractError, "REQUIRED_BY_VALIDATOR_BUT_UNAVAILABLE_TO_MODEL"):
            p4.assert_prompt_coverage(broken)

    def test_any_rule_dropped_from_the_prompt_schema_fails_the_gate(self):
        system = p4.prompt_material()["primary_system"]
        schema = materializer.load_tracked_model_schema()
        drops = (
            lambda s: s["$defs"]["Assertion"]["required"].remove("proposition_handle"),
            lambda s: s["$defs"]["EvidenceRole"]["enum"].remove("PARATEXT"),
            lambda s: s["$defs"]["Handle"].pop("pattern"),
            lambda s: s["$defs"]["Proposition"]["oneOf"].pop(),
            lambda s: s["$defs"]["TemporalAnchor"].pop("then"),
            lambda s: s["$defs"]["EvidenceSet"]["properties"]["evidence_handles"].pop("uniqueItems"),
            lambda s: s["$defs"]["Event"]["properties"].pop("anchor_handle"),
        )
        for drop in drops:
            edited = copy.deepcopy(schema)
            drop(edited)
            broken = system.replace(materializer.model_schema_text().rstrip(), json.dumps(edited, indent=2))
            with self.assertRaises(p4.OutputContractError):
                p4.assert_prompt_coverage(broken)

    def test_p3_blocker_inventory_is_fully_exposed_in_p4(self):
        projection = p4.p3_blocker_projection(p3_prompt_material()["primary_system"], P3_SCHEMA_MARKER,
                                              p4.REGISTRY_SECTION_MARKER)
        self.assertEqual("M4_04B3HR_PUBLIC_RECORD_ONLY", projection["source"])
        self.assertEqual(16, projection["blocker_requirement_families"])
        self.assertEqual(16, projection["p3_structurally_unavailable_to_model"])
        self.assertEqual(0, projection["p4_structurally_unavailable_to_model"])
        self.assertEqual(["Assertion", "Entity", "EntityKind", "Event", "Evidence", "EvidenceRole", "Proposition",
                          "TemporalAnchor"], projection["definitions_involved"])
        schema = materializer.load_tracked_model_schema()
        for name in ("Assertion", "Evidence", "EvidenceRole", "Entity", "Event", "TemporalAnchor", "Proposition"):
            self.assertIn(name, schema["$defs"])


class StructuredOutputTests(unittest.TestCase):
    def test_installed_sdk_supports_a_native_schema_constraint(self):
        capability = p4.sdk_structured_output_capability()
        self.assertEqual("NATIVE_SCHEMA_CONSTRAINT_SUPPORTED_OFFLINE", capability["decision"])
        self.assertEqual("response_json_schema", capability["native_schema_parameter"])
        self.assertEqual("responseJsonSchema", capability["native_schema_wire_name"])
        self.assertEqual(p4.STRUCTURED_OUTPUT_DECISION, capability["decision"])

    def test_prompt_schema_and_native_schema_are_one_object(self):
        config = p4.generation_config()
        system = p4.prompt_material()["primary_system"]
        prompt_schema = p4.extract_prompt_schema(system, p4.SCHEMA_SECTION_MARKER, p4.REGISTRY_SECTION_MARKER)
        self.assertEqual(prompt_schema, config["response_json_schema"])
        self.assertEqual(materializer.materialize_model_schema(), config["response_json_schema"])
        self.assertEqual({"temperature", "max_output_tokens", "response_json_schema"}, set(config))
        self.assertEqual((0, 16384), (config["temperature"], config["max_output_tokens"]))
        self.assertEqual((P3_TEMPERATURE, P3_MAX_OUTPUT_TOKENS), (config["temperature"], config["max_output_tokens"]))
        self.assertEqual(json.dumps(config, sort_keys=True), json.dumps(p4.generation_config(), sort_keys=True))

    def test_accepted_client_serializes_the_exact_schema_into_the_provider_config(self):
        from google.genai import types
        from tools.story_extraction.gemini_transport_v1 import _OfficialGeminiClient

        captured = {}
        client = object.__new__(_OfficialGeminiClient)
        client._types = types
        client._client = python_types.SimpleNamespace(models=python_types.SimpleNamespace(
            generate_content=lambda **kwargs: captured.update(kwargs) or "synthetic-response"))
        result = client.generate(model="synthetic-model-not-bound", system_instruction="SYSTEM",
                                 user_content="USER", generation_config=p4.generation_config())
        self.assertEqual("synthetic-response", result)
        config = captured["config"]
        self.assertIsInstance(config, types.GenerateContentConfig)
        self.assertEqual(materializer.load_tracked_model_schema(), config.response_json_schema)
        self.assertEqual([], materializer.external_refs(config.response_json_schema))
        self.assertEqual("application/json", config.response_mime_type)
        self.assertEqual((0, 16384), (config.temperature, config.max_output_tokens))
        self.assertIsNone(config.response_schema)
        self.assertEqual(("SYSTEM", "USER"), (config.system_instruction, captured["contents"]))
        wire = config.model_dump(exclude_none=True, by_alias=True)
        self.assertEqual(materializer.load_tracked_model_schema(), wire["responseJsonSchema"])
        self.assertEqual({"maxOutputTokens", "responseJsonSchema", "responseMimeType", "systemInstruction", "temperature"},
                         set(wire))

    def test_accepted_durable_transport_passes_the_schema_through_unchanged(self):
        from tools.story_extraction.durable_research_executor_v1 import DurableJobSpec, PersistentRollingOperationPacer
        from tools.story_extraction.gemini_key_pool_v1 import load_runtime_config
        from tools.story_extraction.run_m4_04b2_dev_predictions_v1 import GeminiDevWindowTransport

        seen = []

        def fake_client_factory(api_key):
            def generate(**kwargs):
                seen.append(kwargs)
                return python_types.SimpleNamespace(text="{}", usage_metadata=None, model_version="synthetic")
            return python_types.SimpleNamespace(generate=generate)

        with tempfile.TemporaryDirectory() as directory:
            config = load_runtime_config(Path(directory) / "absent.env", {"GEMINI_API_KEY_3": "synthetic-credential-3"})
            pacer = PersistentRollingOperationPacer(Path(directory) / "pacing.json")
            spec = DurableJobSpec(job_id="P4_SYNTHETIC_SERIALIZATION", model="synthetic-model-not-bound",
                                  system_prompt="SYSTEM", user_prompt="USER", generation_config=p4.generation_config(),
                                  schema_response_mode="SYNTHETIC", credential_slot="gemini_slot_3",
                                  research_task_id="M4-04B4A-OFFLINE-TEST")
            with mock.patch("tools.story_extraction.run_m4_04b2_dev_predictions_v1.official_client_factory",
                            side_effect=fake_client_factory):
                response = GeminiDevWindowTransport(config.credentials[0], pacer, lambda: None)(spec, 1, "request")
        self.assertEqual("{}", response["raw_content"])
        self.assertEqual(1, len(seen))
        self.assertEqual(materializer.load_tracked_model_schema(), seen[0]["generation_config"]["response_json_schema"])
        self.assertEqual((0, 16384), (seen[0]["generation_config"]["temperature"],
                                      seen[0]["generation_config"]["max_output_tokens"]))
        changed = copy.deepcopy(p4.generation_config())
        changed["response_json_schema"]["$defs"]["Assertion"]["required"].remove("support")
        from dataclasses import replace
        self.assertNotEqual(spec.request_fingerprint, replace(spec, generation_config=changed).request_fingerprint)

    def test_native_enforcement_gap_is_recorded_not_hidden(self):
        gap = p4.native_enforcement_gap()
        self.assertEqual(
            ["$schema", "const", "else", "if", "maxLength", "minLength", "minProperties", "not", "pattern", "then",
             "uniqueItems"],
            gap["keywords_not_documented_as_natively_enforced"],
        )
        self.assertEqual(0, gap["ref_nodes_with_sibling_keywords"])
        self.assertFalse(gap["cyclic_references"])
        self.assertTrue(gap["local_validator_remains_authoritative"])
        from google.genai import types
        documented = types.GenerateContentConfig.model_fields["response_json_schema"].description
        for keyword in ("$ref", "$defs", "enum", "required", "additionalProperties", "oneOf", "properties", "items"):
            self.assertIn(f"`{keyword}`", documented, keyword)
            self.assertIn(keyword, p4.NATIVE_DOCUMENTED_KEYWORDS)
        for keyword in ("pattern", "const", "uniqueItems", "minLength"):
            self.assertNotIn(f"`{keyword}`", documented, keyword)


class RepairDiagnosticTests(unittest.TestCase):
    def leaves(self, value):
        if isinstance(value, dict):
            return [leaf for child in value.values() for leaf in self.leaves(child)]
        if isinstance(value, list):
            return [leaf for child in value for leaf in self.leaves(child)]
        return [value]

    def assert_structural_only(self, diagnostic):
        serialized = json.dumps(diagnostic, ensure_ascii=False)
        self.assertNotIn(SECRET, serialized)
        self.assertNotIn("\u65e5\u672c\u8a9e", serialized)
        vocabulary = p4.diagnostic_vocabulary()
        paths = p4.path_vocabulary()

        def walk(node, key=None):
            if isinstance(node, dict):
                for name, child in node.items():
                    walk(child, name)
            elif isinstance(node, list):
                for child in node:
                    walk(child, key)
            elif isinstance(node, str):
                if key == "path":
                    for part in node.split("/"):
                        self.assertTrue(part == "$" or part.isdigit() or part in paths or part == "<UNRECOGNIZED_KEY>", node)
                else:
                    self.assertIn(node, vocabulary, (key, node))

        walk(diagnostic)

    def test_diagnostic_names_the_broken_rule_not_only_its_path(self):
        draft = maximal_draft()
        del draft["assertions"][0]["proposition_handle"]
        del draft["assertions"][0]["support"]
        draft["assertions"][0]["predicate"] = "Occurred"
        draft["mentions"][0]["role"] = "AGENT"
        diagnostic = p4.structural_diagnostic_v2(json.dumps(draft))
        self.assertEqual(("M4_P4_STRUCTURAL_REPAIR_DIAGNOSTIC_V2", "DRAFT_SCHEMA_FAILURE", 3),
                         (diagnostic["diagnostic"], diagnostic["category"], diagnostic["finding_count"]))
        by_key = {(item["path"], item["schema_keyword"]): item for item in diagnostic["findings"]}
        self.assertEqual(["proposition_handle", "support"], by_key[("assertions/0", "required")]["missing_required_fields"])
        self.assertEqual(1, by_key[("assertions/0", "additionalProperties")]["unexpected_field_count"])
        self.assertIn("proposition_handle", by_key[("assertions/0", "additionalProperties")]["allowed_fields"])
        self.assertEqual(["DEPICTION", "RETROSPECTIVE", "IN_WORLD_REPORT", "NARRATION_SUMMARY", "PARATEXT"],
                         by_key[("mentions/0/role", "enum")]["allowed_enum_tokens"])
        self.assertNotIn("predicate", json.dumps(by_key[("assertions/0", "additionalProperties")]["unexpected_field_count"]))
        self.assert_structural_only(diagnostic)
        self.assertEqual(0, p4.structural_diagnostic_v2(json.dumps(maximal_draft()))["finding_count"])

    def test_every_rule_kind_has_a_schema_owned_explanation(self):
        def finding(change, path, keyword):
            draft = maximal_draft()
            change(draft)
            diagnostic = p4.structural_diagnostic_v2(json.dumps(draft))
            self.assert_structural_only(diagnostic)
            return {(item["path"], item["schema_keyword"]): item for item in diagnostic["findings"]}[(path, keyword)]

        self.assertEqual("integer", finding(lambda d: d["evidence"][1].update(occurrence="1"), "evidence/1/occurrence", "type")["expected_type"])
        self.assertEqual(1, finding(lambda d: d["evidence"][1].update(occurrence=0), "evidence/1/occurrence", "minimum")["limit"])
        self.assertEqual("STORY_EXTRACTION_DRAFT_V1_1",
                         finding(lambda d: d.update(draft_version="X"), "draft_version", "const")["required_constant"])
        self.assertEqual("^E_NEW_[1-9][0-9]*$", finding(lambda d: d["entities"][0].update(handle="E1"), "entities/0/handle", "pattern")["required_pattern"])
        self.assertEqual(["event_handle"], finding(lambda d: d["anchors"][1].update(event_handle="EVT1"), "anchors/1", "not")["forbidden_fields"])
        self.assertEqual(["event_handle"], finding(lambda d: d["anchors"][0].pop("event_handle"), "anchors/0", "required")["missing_required_fields"])
        self.assertEqual(200, finding(lambda d: d["entities"][1].update(editorial_label="x" * 201), "entities/1/editorial_label", "maxLength")["limit"])
        variants = finding(lambda d: d["propositions"][0].update(args={}), "propositions/0", "oneOf")["variants"]
        self.assertEqual([["handle", "predicate", "args"], ["handle", "placeholder"]], [v["required_fields"] for v in variants])
        self.assertEqual("minProperties", variants[0]["findings"][0]["schema_keyword"])
        self.assertEqual({"placeholder": [True]}, variants[1]["fixed_values"])
        nested = finding(lambda d: d["propositions"][0]["args"]["lit"].pop("value_type"), "propositions/0", "oneOf")
        inner = nested["variants"][0]["findings"][0]
        self.assertEqual(("propositions/0/args/<UNRECOGNIZED_KEY>", "oneOf"), (inner["path"], inner["schema_keyword"]))
        self.assertEqual(["value_type"], inner["variants"][1]["findings"][0]["missing_required_fields"])

    def test_arbitrary_model_output_cannot_leak_values_into_the_diagnostic(self):
        def poison(node):
            if isinstance(node, dict):
                return {key: poison(value) for key, value in node.items()}
            if isinstance(node, list):
                return [poison(value) for value in node]
            return f"{SECRET} \u65e5\u672c\u8a9e {node}"

        outputs = [poison(maximal_draft())]
        for draft in list(mutants(maximal_draft()))[::7]:
            outputs.append(draft)
        keyed = maximal_draft()
        keyed[f"{SECRET}_key"] = SECRET
        keyed["assertions"][0][f"{SECRET} key with spaces"] = {SECRET: [SECRET]}
        keyed["propositions"][0]["args"][f"{SECRET}_argument"] = {"kind": SECRET, SECRET: SECRET}
        keyed["entities"].append({SECRET: SECRET})
        keyed["evidence"][0]["quote"] = SECRET
        outputs += [keyed, [SECRET], SECRET, {SECRET: SECRET}, {"draft_version": SECRET}, 7, None]
        checked = 0
        for output in outputs:
            diagnostic = p4.structural_diagnostic_v2(json.dumps(output, ensure_ascii=False))
            self.assert_structural_only(diagnostic)
            checked += 1
        self.assertGreater(checked, 300)

    def test_json_diagnostic_gives_class_and_position_but_no_text(self):
        valid = json.dumps(maximal_draft())
        cases = (
            ("", "EMPTY_RESPONSE"), ("   \n", "EMPTY_RESPONSE"), (None, "EMPTY_RESPONSE"),
            (f"Here is {SECRET}: " + valid, "NON_JSON_PREFIX_SUFFIX"),
            ("```json\n" + valid + "\n```", "NON_JSON_PREFIX_SUFFIX"),
            (valid + f" {SECRET}", "EXTRA_DATA"),
            (valid[: len(valid) // 2], "UNTERMINATED_JSON"),
            ('{"quote": "' + SECRET, "UNTERMINATED_JSON"),
            ('{"a": 1, ' + SECRET + ': 2}', "INVALID_PROPERTY_NAME"),
            ('{"a": "' + SECRET + '\\q"}', "INVALID_ESCAPE"),
            ('{"a": 1, }', "TRAILING_COMMA"), ('{"a": [1, ]}', "TRAILING_COMMA"),
            ('{"a" "' + SECRET + '"}', "OTHER_JSON_SYNTAX"),
        )
        for text, expected in cases:
            finding = p4.json_error_diagnostic(text)
            with self.subTest(expected=expected):
                self.assertEqual(expected, finding["json_error_class"])
                self.assertEqual({"phase", "code", "path", "json_error_class", "line", "column"}, set(finding))
                self.assertTrue(type(finding["line"]) is int and type(finding["column"]) is int)
                self.assertNotIn(SECRET, json.dumps(finding))
                self.assert_structural_only({"findings": [finding]})
        self.assertEqual("JSON_PARSE_FAILURE", p4.structural_diagnostic_v2("{")["category"])
        multi = p4.json_error_diagnostic('{\n  "a": 1,\n  b: 2\n}')
        self.assertEqual((3, 3), (multi["line"], multi["column"]))
        with self.assertRaises(p4.OutputContractError):
            p4.json_error_diagnostic(valid)

    def test_compiler_blockers_are_reduced_to_structural_fields(self):
        findings = p4.compiler_findings([
            {"phase": "HANDLE", "code": "UNKNOWN_HANDLE", "path": "assertions/0/proposition_handle", "quote": SECRET},
            {"phase": "HANDLE", "code": "UNKNOWN_HANDLE", "path": f"propositions/0/args/{SECRET}/handle"},
            {"phase": "HANDLE", "code": "UNKNOWN_HANDLE", "path": "assertions/0/proposition_handle"},
        ])
        self.assertEqual(2, len(findings))
        self.assertTrue(all(set(item) == {"phase", "code", "path"} for item in findings))
        self.assertNotIn(SECRET, json.dumps(findings))
        self.assertEqual("propositions/0/args/<UNRECOGNIZED_KEY>/handle", findings[1]["path"])
        for bad in ({"phase": "HANDLE", "code": f"{SECRET} code", "path": ""}, {"phase": "handle", "code": "X", "path": ""},
                    {"phase": "HANDLE", "code": "X", "path": 3}):
            with self.assertRaises(p4.OutputContractError):
                p4.compiler_findings([bad])

    def test_diagnostic_is_deterministic(self):
        raw = json.dumps(next(iter(mutants(maximal_draft()))))
        self.assertEqual(p4.structural_diagnostic_v2(raw), p4.structural_diagnostic_v2(raw))


class OfflineBoundaryTests(unittest.TestCase):
    def imports(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        return {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
            alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}

    def test_tools_have_no_provider_dataset_or_evaluator_integration(self):
        self.assertEqual({"__future__", "argparse", "copy", "hashlib", "json", "pathlib", "typing"},
                         self.imports(MATERIALIZER_FILE))
        self.assertEqual(
            {"__future__", "collections", "functools", "json", "pathlib", "re", "typing", "jsonschema", "yaml",
             "importlib.metadata", "google.genai",
             "tools.story_extraction.materialize_draft_v1_1_model_schema_v1"},
            self.imports(CONTRACT_FILE),
        )
        for path in (MATERIALIZER_FILE, CONTRACT_FILE):
            source = path.read_text(encoding="utf-8")
            for forbidden in ("genai.Client", "api_key", "generate_content", "load_runtime_config", "zipfile",
                              "evaluate_case", ".local", "official_client_factory"):
                self.assertNotIn(forbidden, source, (path.name, forbidden))
        self.assertFalse(p4.contract_identity()["model_or_credential_bound"])


class PublicRecordTests(unittest.TestCase):
    def setUp(self):
        self.text = RECORD.read_text(encoding="utf-8")
        self.record = yaml.safe_load(self.text)

    def test_record_binds_the_contract_and_its_tooling(self):
        record = self.record
        self.assertEqual("M4_04B4A_P4_OUTPUT_CONTRACT_READY", record["status"])
        self.assertEqual("TUNING_DATA_AFTER_P3_FAILURE", record["DEV3_STATUS_FOR_P4"])
        self.assertEqual("STORY_EXTRACTION_DRAFT_V1_1", record["canonical_draft_contract"]["identity"])
        self.assertFalse(record["canonical_draft_contract"]["semantics_changed"])
        schema = record["model_facing_schema"]
        self.assertEqual(("STORY_EXTRACTION_DRAFT_V1_1_MODEL_SCHEMA_V1", MODEL_SCHEMA_SHA256, 0),
                         (schema["identity"], schema["sha256"], schema["external_ref_count"]))
        hashes = record["tooling"]
        for key, path in (("materializer", MATERIALIZER_FILE), ("output_contract", CONTRACT_FILE),
                          ("focused_tests", Path(__file__)), ("system_preamble", p4.SYSTEM_PREAMBLE_PATH),
                          ("user_template", p4.USER_TEMPLATE_PATH), ("repair_user_template", p4.REPAIR_USER_TEMPLATE_PATH)):
            self.assertEqual(normalized_file_sha256(path), hashes[key]["sha256"], key)

    def test_record_numbers_equal_the_recomputed_gates(self):
        record = self.record
        coverage = p4.assert_prompt_coverage()
        self.assertEqual(coverage["structural_requirements"], record["prompt_structural_coverage"]["P4"]["structural_requirements"])
        self.assertEqual(0, record["prompt_structural_coverage"]["P4"]["unavailable"])
        self.assertEqual(214, record["prompt_structural_coverage"]["P3_same_gate"]["unavailable"])
        projection = record["p3_failure_projection"]
        self.assertEqual((16, 16, 0), (projection["blocker_requirement_families"],
                                       projection["p3_structurally_unavailable_to_model"],
                                       projection["p4_structurally_unavailable_to_model"]))
        self.assertEqual(p4.STRUCTURED_OUTPUT_DECISION, record["structured_output"]["decision"])
        self.assertEqual(p4.native_enforcement_gap()["keywords_not_documented_as_natively_enforced"],
                         record["structured_output"]["keywords_not_documented_as_natively_enforced"])
        self.assertEqual(p4.REPAIR_DIAGNOSTIC_ID, record["repair_diagnostic"]["identity"])
        self.assertEqual(1, record["repair_diagnostic"]["maximum_repairs_per_case"])

    def test_record_boundaries(self):
        boundaries = self.record["boundaries"]
        self.assertEqual(0, boundaries["provider_operations"])
        for name in ("DEV3_gold_opened", "holdout_opened", "DEV3_input_accessed", "P3_rerun", "DEV4_created",
                     "extraction_quality_improvement_claimed"):
            self.assertIs(False, boundaries[name], name)
        self.assertTrue(all(ord(char) < 128 for char in self.text))


if __name__ == "__main__":
    unittest.main()
