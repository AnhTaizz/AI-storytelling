import contextlib
import copy
from dataclasses import replace
import inspect
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from jsonschema import Draft202012Validator

from tests.story_extraction import test_m4_04b4a_p4_output_contract_v1 as b4a
from tools.story_extraction import m4_04b4a_p4_output_contract_v1 as contract
from tools.story_extraction import m4_04b4b_p4_protocol_v1 as protocol_v1
from tools.story_extraction import m4_04b4br_p4_protocol_v2 as protocol
from tools.story_extraction import materialize_draft_v1_1_model_schema_v1 as materializer
from tools.story_extraction import project_draft_v1_1_model_schema_to_gemini_v1 as projection
from tools.story_extraction import run_m4_04b4b_p4_structural_v1 as runner_v1
from tools.story_extraction import run_m4_04b4br_p4_projection_smoke_v1 as runner
from tools.story_extraction.draft_compiler_v1_1 import DraftCompilationErrorV1_1, validate_draft_v1_1
from tools.story_extraction.durable_research_executor_v1 import (
    CheckpointIntegrityError,
    DurableTransportFailure,
    JobState,
)
from tools.story_extraction.run_m4_04b3g_dev3_p3_predictions_v1 import FirstSuccessLedger


FULL_SHA256 = "5aa2ed6dde3791546ddd5e059648d8dac38df1571a6073b7abc31c89eb257f14"
PROJECTION_SHA256 = "89506defa4089b1449f7c80bbcf782d94065802ceae71aa86e1598a5a17ab9bd"
PROTOCOL_V1_SHA256 = "e0c74be45bcfd7cdca4111ff6029358e668b68f0a94fa94cf52718614f75279a"
PROTOCOL_V2_SHA256 = "24b2af927e07078da3a06fe329aa5378cdde92675e76e92e2c03d9ad82726025"
EXPERIMENT_SHA256 = "71cea1f4e603995ffd7466e16fd2fbb3034fed7935c581f890cc81f13f01cdc0"
HISTORICAL_FILES = {
    "tools/story_extraction/m4_04b4b_p4_protocol_v1.py":
        "513824f4c9c6f5208c73dd5d54c388f0d2577858570c8177551f6e0fda540a4b",
    "tools/story_extraction/run_m4_04b4b_p4_structural_v1.py":
        "4104b6be780eb4d8611951dfd412fed6b7f19c4b55f6170f7c790b1f19207106",
    "benchmarks/m4_extraction/M4_04B4B_P4_RUNTIME_PROTOCOL_AND_NATIVE_SCHEMA_SMOKE.yaml":
        "62f753a7eda9c61a7f4dccedaa8a8a56176e1af43e29ac3fdd396934dd3aaf51",
}
MARKER = "ZZ_PROVIDER_MESSAGE_MARKER_ZZ"
STAGE1 = runner.STAGE1_JOB_ID
STAGE2 = "M4B4BR_P4V2_SYNTHETIC_SMOKE_01_PRIMARY"
STAGE1_OK = '{"status": "OK"}'
SMOKE_DRAFT = {
    "draft_version": "STORY_EXTRACTION_DRAFT_V1_1",
    "evidence": [{"handle": "EV1", "passage_handle": "P1", "quote": "Tomas", "occurrence": 1, "role": "DEPICTION"}],
    "mentions": [{"handle": "M1", "passage_handle": "P1", "quote": "Tomas", "occurrence": 1, "role": "DEPICTION",
                  "surface_form": "Tomas"}],
    "entities": [{"handle": "E_NEW_1", "kind": "CHARACTER"}],
    "events": [],
    "anchors": [],
    "propositions": [{"handle": "PROP1", "predicate": "RefersTo",
                      "args": {"mention": {"kind": "MENTION", "handle": "M1"},
                               "entity": {"kind": "ENTITY", "handle": "E_NEW_1"}}}],
    "assertions": [{"handle": "A1", "proposition_handle": "PROP1", "polarity": "AFFIRMED",
                    "epistemic_status": "EXPLICIT",
                    "support": {"evidence_sets": [{"label": "SUFFICIENT", "evidence_handles": ["EV1"]}],
                                "derivations": []}}],
}


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


def full_schema():
    return materializer.load_tracked_model_schema()


def projected_schema():
    return projection.project_model_schema()


def resolve(schema, tokens):
    node = schema
    for token in tokens:
        node = node[int(token)] if isinstance(node, list) else node[token]
    return node


def tokens_of(pointer):
    return tuple(part.replace("~1", "/").replace("~0", "~") for part in pointer.split("/")[1:])


def edited(change, base=None):
    draft = copy.deepcopy(b4a.maximal_draft() if base is None else base)
    change(draft)
    return draft


def weaker_examples():
    """One draft per projected-away rule: the full schema rejects it, the projection accepts it."""
    return {
        "pattern": edited(lambda d: d["mentions"][0].__setitem__("handle", "X1")),
        "minLength": edited(lambda d: d["mentions"][0].__setitem__("quote", "")),
        "maxLength": edited(lambda d: d["mentions"][0].__setitem__("surface_form", "a" * 201)),
        "minProperties": edited(lambda d: d["propositions"][0].__setitem__("args", {})),
        "uniqueItems": edited(
            lambda d: d["assertions"][0]["support"]["evidence_sets"][0].__setitem__("evidence_handles", ["EV1", "EV1"])
        ),
        "if_then": edited(lambda d: d["anchors"][0].pop("event_handle")),
        "else_not": edited(lambda d: d["anchors"][1].__setitem__("event_handle", "EVT1")),
        "const_boolean": edited(lambda d: d["propositions"][1].__setitem__("placeholder", False)),
    }


def kept_rule_examples():
    """Drafts that break a rule the projection keeps: both schemas reject them."""
    return {
        "const_as_enum_root": edited(lambda d: d.__setitem__("draft_version", "STORY_EXTRACTION_DRAFT_V1")),
        "const_as_enum_argument_kind": edited(
            lambda d: d["propositions"][0]["args"]["lit"].__setitem__("kind", "LITERALLY")
        ),
        "const_as_enum_bound_kind": edited(lambda d: d["assertions"][0]["validity"]["start"].__setitem__("kind", "SHUT")),
        "enum": edited(lambda d: d["assertions"][0].__setitem__("polarity", "MAYBE")),
        "required": edited(lambda d: d["assertions"][0].pop("polarity")),
        "additionalProperties": edited(lambda d: d.__setitem__("zz_unexpected", 1)),
        "type": edited(lambda d: d.__setitem__("mentions", {})),
        "minItems": edited(lambda d: d["assertions"][0]["support"]["evidence_sets"][0].__setitem__("evidence_handles", [])),
        "oneOf_variant": edited(lambda d: d["propositions"][1].__setitem__("predicate", "Occurred")),
    }


class ProjectionDeterminismAndLineageTests(unittest.TestCase):
    def test_projection_is_deterministic_and_hash_locked(self):
        first, second = projection.project_model_schema(), projection.project_model_schema()
        self.assertEqual(first, second)
        self.assertEqual(projection.projection_text(first), projection.projection_text(second))
        self.assertEqual(PROJECTION_SHA256, projection.projection_sha256())
        self.assertEqual(PROJECTION_SHA256, projection.PROJECTION_SHA256)
        self.assertEqual("STORY_EXTRACTION_DRAFT_V1_1_GEMINI_RESPONSE_SCHEMA_V1", projection.PROJECTION_IDENTITY)
        self.assertEqual(projection.manifest_text(), projection.manifest_text())

    def test_tracked_files_equal_the_tool_output(self):
        self.assertEqual(projection.projection_text(),
                         projection.PROJECTION_PATH.read_text(encoding="utf-8").replace("\r\n", "\n"))
        self.assertEqual(projection.manifest_text(),
                         projection.MANIFEST_PATH.read_text(encoding="utf-8").replace("\r\n", "\n"))
        self.assertEqual(projected_schema(), projection.load_tracked_projection())
        self.assertEqual(projection.transformation_manifest(), projection.load_tracked_manifest())
        self.assertEqual(PROJECTION_SHA256, protocol.normalized_file_sha256(projection.PROJECTION_PATH))

    def test_hand_edited_tracked_projection_fails_closed(self):
        edits = {
            "weakened": lambda schema: schema["$defs"]["Assertion"]["required"].remove("support"),
            "strengthened": lambda schema: schema["$defs"]["Handle"].__setitem__("pattern", "^X$"),
            "renamed": lambda schema: schema["properties"].__setitem__("mention", schema["properties"].pop("mentions")),
        }
        for label, change in edits.items():
            with self.subTest(edit=label), tempfile.TemporaryDirectory() as directory:
                altered = projected_schema()
                change(altered)
                path = Path(directory) / "projection.schema.json"
                path.write_text(json.dumps(altered, indent=2) + "\n", encoding="utf-8")
                with mock.patch.object(projection, "PROJECTION_PATH", path):
                    with self.assertRaises(projection.ProjectionError):
                        projection.load_tracked_projection()
                    with self.assertRaises(projection.ProjectionError):
                        projection.lineage_gate()
                    with self.assertRaises(protocol.P4ProtocolV2Error):
                        protocol.native_response_schema()
                    with self.assertRaises(protocol.P4ProtocolV2Error):
                        protocol.locked_protocol()

    def test_input_is_exactly_the_accepted_full_model_schema(self):
        self.assertEqual(FULL_SHA256, materializer.model_schema_sha256())
        self.assertEqual(FULL_SHA256, projection.SOURCE_SHA256)
        self.assertEqual(full_schema(), projection.load_source_schema())
        self.assertEqual([], list(inspect.signature(projection.project_model_schema).parameters))
        self.assertEqual([], list(inspect.signature(projection.load_source_schema).parameters))
        with mock.patch.object(materializer, "model_schema_sha256", return_value="0" * 64):
            with self.assertRaises(projection.ProjectionError):
                projection.project_model_schema()
        edited_schema = full_schema()
        edited_schema["title"] = "INDEPENDENTLY_EDITED_SCHEMA"
        with mock.patch.object(materializer, "load_tracked_model_schema", return_value=edited_schema):
            with self.assertRaises(projection.ProjectionError):
                projection.project_model_schema()

    def test_lineage_gate_canonical_to_full_to_projection(self):
        self.assertEqual({"PASS"}, set(projection.lineage_gate().values()))
        self.assertEqual(full_schema(), materializer.materialize_model_schema())
        self.assertEqual(projection.load_tracked_projection(), projection.project(full_schema())[0])
        self.assertNotEqual(full_schema(), projected_schema())
        materializer.verify_equivalence_by_construction(full_schema())

    def test_full_model_schema_and_canonical_schemas_are_unchanged(self):
        bound = protocol_v1.BOUND_FILES
        for relative in (
            "schemas/story_extraction/story_extraction_draft_v1_1_model_schema_v1.schema.json",
            "schemas/story_extraction/story_extraction_draft_v1_1.schema.json",
            "schemas/story_extraction/story_extraction_draft_v1.schema.json",
            "schemas/canonical_story/predicate_registry_v0.yaml",
            "tools/story_extraction/draft_compiler_v1_1.py",
            "tools/story_extraction/prompts/story_extraction_draft_p4_v1_system.txt",
            "tools/story_extraction/prompts/story_extraction_draft_p4_v1_user.txt",
            "tools/story_extraction/prompts/story_extraction_draft_p4_v1_repair_user.txt",
        ):
            with self.subTest(path=relative):
                self.assertEqual(bound[relative], protocol.normalized_file_sha256(protocol.REPO_ROOT / relative))


class ProjectionTransformationTests(unittest.TestCase):
    def setUp(self):
        self.full = full_schema()
        self.projected = projected_schema()
        self.manifest = projection.transformation_manifest()
        self.transformations = self.manifest["transformations"]

    def test_manifest_records_pointer_keyword_and_action_only(self):
        self.assertEqual(39, self.manifest["transformation_count"])
        self.assertEqual(
            {"CONST_TO_SINGLETON_ENUM": 5, "DROP_PROVIDER_UNSUPPORTED_CONSTRAINT": 30, "DROP_PROVIDER_METADATA": 4},
            self.manifest["action_counts"],
        )
        self.assertEqual(
            {"$id": 1, "$schema": 1, "const": 6, "description": 1, "else": 1, "if": 1, "maxLength": 3, "minLength": 6,
             "minProperties": 1, "pattern": 13, "then": 1, "title": 1, "uniqueItems": 3},
            self.manifest["keyword_counts"],
        )
        for item in self.transformations:
            self.assertEqual({"pointer", "keyword", "action"}, set(item))
            self.assertIn(item["action"], projection.ACTIONS)
            self.assertTrue(item["pointer"].endswith("/" + item["keyword"]))
            self.assertIn(item["keyword"], resolve(self.full, tokens_of(item["pointer"])[:-1]))
        self.assertEqual(len(self.transformations), len({item["pointer"] for item in self.transformations}))
        self.assertEqual(FULL_SHA256, self.manifest["source_sha256"])
        self.assertEqual(PROJECTION_SHA256, self.manifest["projection_sha256"])
        text = projection.manifest_text()
        for word in ("Tomas", "alpha", "quote\":", "passage"):
            self.assertNotIn(word, text.replace("passage_handle", ""))

    def test_manifest_applied_literally_reproduces_the_projection(self):
        self.assertEqual(self.projected, projection.apply_manifest(self.full, self.transformations))
        without_one = [item for item in self.transformations if item["keyword"] != "minProperties"]
        self.assertNotEqual(self.projected, projection.apply_manifest(self.full, without_one))

    def test_every_string_const_becomes_an_equivalent_singleton_enum(self):
        rewrites = [item for item in self.transformations if item["action"] == "CONST_TO_SINGLETON_ENUM"]
        self.assertEqual(
            ["/properties/draft_version/const", "/$defs/Argument/oneOf/1/properties/kind/const",
             "/$defs/Argument/oneOf/2/properties/kind/const", "/$defs/Bound/oneOf/0/properties/kind/const",
             "/$defs/Bound/oneOf/1/properties/kind/const"],
            [item["pointer"] for item in rewrites],
        )
        for item in rewrites:
            with self.subTest(pointer=item["pointer"]):
                parent = tokens_of(item["pointer"])[:-1]
                source, target = resolve(self.full, parent), resolve(self.projected, parent)
                value = source["const"]
                self.assertIsInstance(value, str)
                self.assertNotIn("enum", source)
                self.assertNotIn("const", target)
                self.assertEqual([value], target["enum"])
                self.assertEqual({key: item for key, item in source.items() if key != "const"},
                                 {key: item for key, item in target.items() if key != "enum"})
                before, after = Draft202012Validator(source), Draft202012Validator(target)
                probes = [value, value + "_x", value.lower(), " " + value, "", 0, 1, 1.5, True, False, None, [],
                          [value], {}, {"const": value}]
                for probe in probes:
                    self.assertEqual(before.is_valid(probe), after.is_valid(probe), repr(probe))
                self.assertTrue(after.is_valid(value))

    def test_boolean_const_is_dropped_because_enum_is_documented_for_strings_and_numbers(self):
        pointer = "/$defs/Proposition/oneOf/1/properties/placeholder/const"
        item = next(entry for entry in self.transformations if entry["pointer"] == pointer)
        self.assertEqual("DROP_PROVIDER_UNSUPPORTED_CONSTRAINT", item["action"])
        self.assertIs(True, resolve(self.full, tokens_of(pointer)))
        self.assertEqual({}, resolve(self.projected, tokens_of(pointer)[:-1]))
        from google.genai import types
        self.assertIn("`enum` (for strings and\n      numbers)".replace("\n      ", " "),
                      " ".join(types.GenerateContentConfig.model_fields["response_json_schema"].description.split()))
        boolean_enum = {"type": "object", "properties": {"x": {"enum": [True]}}}
        with self.assertRaises(projection.ProjectionError):
            projection.assert_provider_subset(projection.project(boolean_enum)[0])

    def test_unsupported_keywords_are_removed_everywhere(self):
        removed = set(projection.DROPPED_CONSTRAINTS) | {"const", "$schema"}
        for tokens, node in projection.iter_schema_nodes(self.projected):
            self.assertFalse(removed & set(node), tokens)
        for keyword in projection.ROOT_METADATA:
            self.assertNotIn(keyword, self.projected)
        self.assertFalse(set(projection.DROPPED_CONSTRAINTS) & set(projection.PROVIDER_KEYWORDS))
        self.assertEqual(
            ["$schema", "const", "else", "if", "maxLength", "minLength", "minProperties", "not", "pattern", "then",
             "uniqueItems"],
            contract.native_enforcement_gap()["keywords_not_documented_as_natively_enforced"],
        )

    def test_projection_uses_only_keywords_the_installed_sdk_documents(self):
        report = projection.assert_provider_subset(self.projected)
        self.assertEqual(
            ["$defs", "$ref", "additionalProperties", "enum", "items", "minItems", "minimum", "oneOf", "properties",
             "required", "type"],
            report["keywords_used"],
        )
        from google.genai import types
        documented = types.GenerateContentConfig.model_fields["response_json_schema"].description
        for keyword in report["keywords_used"]:
            self.assertIn(f"`{keyword}`", documented, keyword)
        self.assertIn("interpreted the same as `anyOf`", " ".join(documented.split()))

    def test_kept_keywords_hierarchy_and_names_are_unchanged(self):
        source_nodes = dict(projection.iter_schema_nodes(self.full))
        projected_nodes = dict(projection.iter_schema_nodes(self.projected))
        self.assertEqual(set(source_nodes), set(projected_nodes))
        allowed_removals = set(projection.DROPPED_CONSTRAINTS) | {"const"} | set(projection.ROOT_METADATA)
        for tokens, node in projected_nodes.items():
            source = source_nodes[tokens]
            with self.subTest(pointer=projection._pointer(tokens)):
                self.assertLessEqual(set(source) - set(node), allowed_removals)
                self.assertLessEqual(set(node) - set(source), {"enum"})
                for keyword in ("type", "required", "minItems", "minimum", "$ref"):
                    self.assertEqual(source.get(keyword), node.get(keyword), keyword)
                if isinstance(source.get("additionalProperties"), bool):
                    self.assertIs(source["additionalProperties"], node["additionalProperties"])
                for keyword in ("properties", "$defs"):
                    self.assertEqual(list(source.get(keyword, {})), list(node.get(keyword, {})), keyword)
                self.assertEqual(len(source.get("oneOf", [])), len(node.get("oneOf", [])))
                if "enum" in source:
                    self.assertEqual(source["enum"], node["enum"])

    def test_no_semantic_property_is_removed_added_or_renamed(self):
        def property_names(schema):
            return sorted(
                (projection._pointer(tokens), name)
                for tokens, node in projection.iter_schema_nodes(schema) for name in node.get("properties", {})
            )

        self.assertEqual(property_names(self.full), property_names(self.projected))
        self.assertEqual(list(self.full["$defs"]), list(self.projected["$defs"]))
        self.assertEqual(self.full["required"], self.projected["required"])

    def test_references_are_local_resolved_and_unchanged(self):
        def references(schema):
            return sorted((projection._pointer(tokens), node["$ref"])
                          for tokens, node in projection.iter_schema_nodes(schema) if "$ref" in node)

        self.assertEqual(references(self.full), references(self.projected))
        self.assertEqual(30, len(references(self.projected)))
        self.assertEqual([], materializer.external_refs(self.projected))
        report = materializer.assert_self_contained(self.projected)
        self.assertEqual((0, 30, 17), (report["external_ref_count"], report["ref_count"], report["definition_count"]))
        for _, ref in references(self.projected):
            self.assertTrue(ref.startswith("#/$defs/"))
            materializer.resolve_local_ref(self.projected, ref)
        self.assertFalse(projection._reference_cycle(self.projected))
        cyclic = {"type": "object", "properties": {"a": {"$ref": "#/$defs/A"}},
                  "$defs": {"A": {"type": "object", "properties": {"b": {"$ref": "#/$defs/A"}}}}}
        with self.assertRaises(projection.ProjectionError):
            projection.assert_provider_subset(cyclic)
        dangling = {"type": "object", "$defs": {"Unused": {"type": "string"}}}
        with self.assertRaises(projection.ProjectionError):
            projection.assert_provider_subset(dangling)

    def test_unknown_or_unsafe_input_fails_closed(self):
        for schema in (
            {"type": "object", "patternProperties": {"^x": {"type": "string"}}},
            {"type": "object", "properties": {"x": {"type": "string", "title": "nested annotation"}}},
            {"type": "object", "allOf": [{"type": "object"}]},
            {"type": "object", "properties": {"x": {"const": "A", "enum": ["A", "B"]}}},
            {"type": "object", "properties": {"x": []}},
        ):
            with self.subTest(schema=json.dumps(schema)), self.assertRaises(projection.ProjectionError):
                projection.project(schema)

    def test_one_of_variants_stay_mutually_exclusive(self):
        self.assertEqual({"one_of_nodes": 3}, projection.one_of_exclusivity(self.projected))
        overlapping = {"oneOf": [
            {"type": "object", "required": ["kind"], "properties": {"kind": {"type": "string"}}},
            {"type": "object", "required": ["kind"], "properties": {"kind": {"type": "string"}}},
        ]}
        with self.assertRaises(projection.ProjectionError):
            projection.one_of_exclusivity(overlapping)
        validator = Draft202012Validator(self.projected)
        any_of = Draft202012Validator(json.loads(projection.projection_text().replace('"oneOf"', '"anyOf"')))
        for draft in [b4a.maximal_draft(), *weaker_examples().values(), *kept_rule_examples().values()]:
            self.assertEqual(validator.is_valid(draft), any_of.is_valid(draft))

    def test_relaxation_is_proven_by_construction(self):
        report = projection.verify_relaxation_by_construction()
        self.assertTrue(all(report["checks"].values()))
        self.assertEqual(39, report["transformation_count"])
        strengthened = projected_schema()
        strengthened["$defs"]["Handle"]["minLength"] = 3
        with mock.patch.object(projection, "project", return_value=(strengthened, self.transformations)):
            with self.assertRaises(projection.ProjectionError):
                projection.verify_relaxation_by_construction()


class RelaxationInvariantTests(unittest.TestCase):
    """FULL_VALID implies PROJECTION_VALID. The inverse is not required and does not hold."""

    @classmethod
    def setUpClass(cls):
        cls.full = Draft202012Validator(full_schema())
        cls.projected = Draft202012Validator(projected_schema())
        cls.bases = {"maximal": b4a.maximal_draft(), **b4a.fixture_drafts()}

    def test_every_valid_fixture_draft_passes_both_and_the_canonical_validator(self):
        self.assertEqual(27, len(self.bases))
        for name, draft in self.bases.items():
            with self.subTest(draft=name):
                validate_draft_v1_1(draft)
                self.assertTrue(self.full.is_valid(draft))
                self.assertTrue(self.projected.is_valid(draft))
        self.assertTrue(self.projected.is_valid(SMOKE_DRAFT))

    def test_no_full_valid_mutant_is_rejected_by_the_projection(self):
        everything = os.environ.get("M4_FULL_EQUIVALENCE_CORPUS") == "1"
        checked = full_valid = weaker = 0
        for name, base in self.bases.items():
            step = 1 if everything else (3 if name == "maximal" else 60)
            for index, draft in enumerate(b4a.mutants(base)):
                if index % step:
                    continue
                checked += 1
                accepted_full, accepted_projection = self.full.is_valid(draft), self.projected.is_valid(draft)
                full_valid += accepted_full
                weaker += accepted_projection and not accepted_full
                if accepted_full and not accepted_projection:
                    self.fail(f"projection rejects a full-valid draft: {name} mutant {index}")
        self.assertGreater(checked, 1500)
        self.assertGreater(full_valid, 50)
        self.assertGreater(weaker, 50)

    def test_projection_accepts_what_the_full_schema_rejects_for_each_removed_rule(self):
        examples = weaker_examples()
        self.assertEqual(
            {"pattern", "minLength", "maxLength", "minProperties", "uniqueItems", "if_then", "else_not", "const_boolean"},
            set(examples),
        )
        for rule, draft in examples.items():
            with self.subTest(rule=rule):
                self.assertFalse(self.full.is_valid(draft))
                self.assertTrue(self.projected.is_valid(draft))
                with self.assertRaises(DraftCompilationErrorV1_1):
                    validate_draft_v1_1(draft)
                diagnostic = contract.structural_diagnostic_v2(encoded(draft))
                self.assertEqual("DRAFT_SCHEMA_FAILURE", diagnostic["category"])
                self.assertTrue(diagnostic["findings"])

    def test_projection_still_rejects_what_it_keeps(self):
        for rule, draft in kept_rule_examples().items():
            with self.subTest(rule=rule):
                self.assertFalse(self.full.is_valid(draft))
                self.assertFalse(self.projected.is_valid(draft))


class ProtocolV2Tests(unittest.TestCase):
    def test_protocol_v2_reconstructs_exactly(self):
        first, second = protocol.build_protocol(), protocol.build_protocol()
        self.assertEqual(protocol.canonical_json_bytes(first), protocol.canonical_json_bytes(second))
        self.assertEqual(PROTOCOL_V2_SHA256, protocol.protocol_sha256())
        self.assertEqual(PROTOCOL_V2_SHA256, protocol.PROTOCOL_SHA256)
        self.assertEqual(first, protocol.locked_protocol())
        self.assertEqual("M4_P4_STRUCTURAL_TUNING_PROTOCOL_V2", first["protocol_id"])
        self.assertEqual(protocol.PROTOCOL_ID + ":" + PROTOCOL_V2_SHA256, protocol.executor_protocol_id())
        self.assertNotEqual(protocol_v1.executor_protocol_id(), protocol.executor_protocol_id())

    def test_protocol_v2_binds_the_exact_runtime_and_both_schema_roles(self):
        locked = protocol.locked_protocol()
        self.assertEqual("P4_STORY_EXTRACTION_DRAFT_V1_1_SELF_CONTAINED_V1", locked["candidate"]["extractor_id"])
        self.assertIs(False, locked["candidate"]["extractor_identity_changed"])
        self.assertEqual({"protocol_id": "M4_P4_STRUCTURAL_TUNING_PROTOCOL_V1", "protocol_sha256": PROTOCOL_V1_SHA256,
                          "reason": "PROVIDER_REJECTED_FULL_MODEL_SCHEMA_AS_NATIVE_RESPONSE_SCHEMA",
                          "change": "PROVIDER_OUTPUT_SHAPING_CONSTRAINT_ONLY"}, locked["supersedes"])
        roles = locked["schema_roles"]
        self.assertEqual((FULL_SHA256, PROJECTION_SHA256), (roles["prompt_schema_sha256"], roles["native_schema_sha256"]))
        self.assertIs(True, roles["native_schema_is_weaker_than_prompt_schema"])
        self.assertEqual("OUTPUT_SHAPING_AID_ONLY", roles["native_schema_role"])
        generation = locked["generation"]
        self.assertEqual(("gemini-3.5-flash-lite", "gemini_slot_3"), (generation["model"], generation["credential_slot"]))
        self.assertIs(0, generation["temperature"])
        self.assertEqual((16384, "application/json"), (generation["max_output_tokens"], generation["response_mime_type"]))
        self.assertEqual(PROJECTION_SHA256, generation["native_schema_sha256"])
        durable = locked["durable_execution"]
        self.assertEqual("GEMINI_TRANSPORT_RESILIENCE_V1_1", durable["runtime"])
        self.assertEqual((6, 60), (durable["global_pacing_max_operations"],
                                   durable["global_pacing_rolling_window_seconds"]))
        self.assertEqual(("IMMUTABLE_LOCK", "FORBIDDEN", "FORBIDDEN"),
                         (durable["first_success"], durable["model_switch"], durable["credential_switch"]))
        repair = locked["repair_policy"]
        self.assertEqual((1, "M4_P4_STRUCTURAL_REPAIR_DIAGNOSTIC_V2"), (repair["maximum_per_case"], repair["diagnostic"]))
        self.assertEqual(protocol_v1.prompt_hashes(), locked["prompt_hashes"])
        self.assertIs(False, locked["data"]["bound_to_a_fresh_benchmark"])
        self.assertEqual("PASS", protocol.validate_bound_files()["bound_files"])
        self.assertLessEqual(set(protocol_v1.BOUND_FILES), set(protocol.BOUND_FILES))
        self.assertEqual(21, len(protocol.BOUND_FILES))

    def test_prompt_carries_the_full_schema_and_native_config_carries_the_projection(self):
        self.assertEqual({"PASS"}, set(protocol.schema_lineage_gate().values()))
        system = contract.prompt_material()["primary_system"]
        in_prompt = contract.extract_prompt_schema(
            system, contract.SCHEMA_SECTION_MARKER, contract.REGISTRY_SECTION_MARKER
        )
        config = protocol.generation_config()
        native = config["response_json_schema"]
        self.assertEqual(full_schema(), in_prompt)
        self.assertNotEqual(projected_schema(), in_prompt)
        self.assertEqual(projection.load_tracked_projection(), native)
        self.assertNotEqual(full_schema(), native)
        self.assertEqual({"temperature", "max_output_tokens", "response_json_schema"}, set(config))
        self.assertIs(int, type(config["temperature"]))
        self.assertEqual((0, 16384), (config["temperature"], config["max_output_tokens"]))
        self.assertEqual(PROJECTION_SHA256, protocol.sha256_text(projection.projection_text(native)))
        self.assertIn('"pattern"', system)
        self.assertNotIn("pattern", json.dumps(native))
        contract.assert_prompt_coverage(system)

    def test_full_schema_as_native_schema_fails_the_lineage_gate(self):
        with mock.patch.object(protocol, "native_response_schema", return_value=full_schema()):
            for call in (protocol.schema_lineage_gate, protocol.locked_protocol):
                with self.assertRaises(protocol.P4ProtocolV2Error):
                    call()

    def test_changed_bound_file_or_binding_fails_closed(self):
        for relative in protocol.BOUND_FILES:
            with self.subTest(path=relative), mock.patch.dict(protocol.BOUND_FILES, {relative: "0" * 64}):
                with self.assertRaises(protocol.P4ProtocolV2Error):
                    protocol.locked_protocol()
        for name, value in (("MODEL", "other-model"), ("CREDENTIAL_SLOT", "gemini_slot_2"),
                            ("MAX_STRUCTURAL_REPAIRS_PER_CASE", 2), ("RESPONSE_MIME_TYPE", "text/plain"),
                            ("PROVIDER_PROJECTION_SHA256", "0" * 64), ("TEMPERATURE", 1), ("MAX_OUTPUT_TOKENS", 8192)):
            with self.subTest(binding=name), mock.patch.object(protocol, name, value):
                with self.assertRaises(protocol.P4ProtocolV2Error):
                    protocol.locked_protocol()

    def test_historical_protocol_v1_runner_and_record_are_unchanged(self):
        for relative, expected in HISTORICAL_FILES.items():
            with self.subTest(path=relative):
                self.assertEqual(expected, protocol.normalized_file_sha256(protocol.REPO_ROOT / relative))
        self.assertEqual(PROTOCOL_V1_SHA256, protocol_v1.protocol_sha256())
        self.assertEqual(PROTOCOL_V1_SHA256, protocol_v1.locked_protocol() and protocol_v1.PROTOCOL_SHA256)
        self.assertEqual(full_schema(), protocol_v1.generation_config()["response_json_schema"])
        self.assertEqual({"PASS"}, set(protocol_v1.single_source_schema_gate().values()))
        with mock.patch.object(protocol_v1, "MODEL", "other-model"):
            with self.assertRaises(protocol.P4ProtocolV2Error):
                protocol.locked_protocol()


class ProtocolV2JobSpecTests(unittest.TestCase):
    def setUp(self):
        self.case = runner_v1.synthetic_smoke_case()
        self.spec = protocol.build_primary_spec(self.case.case_id, self.case.prepared_input)

    def test_primary_spec_is_exact(self):
        protocol.assert_locked_job_spec(self.spec)
        self.assertEqual(STAGE2, self.spec.job_id)
        self.assertEqual(contract.prompt_material()["primary_system"], self.spec.system_prompt)
        self.assertEqual(contract.render_primary_user(self.case.case_id, self.case.prepared_input), self.spec.user_prompt)
        self.assertEqual(projection.load_tracked_projection(), self.spec.generation_config["response_json_schema"])
        self.assertEqual(protocol.PROTOCOL_ID, self.spec.research_task_id)

    def test_checker_rejects_every_drift(self):
        config = dict(self.spec.generation_config)

        def with_schema(change):
            schema = copy.deepcopy(config["response_json_schema"])
            change(schema)
            return replace(self.spec, generation_config={**config, "response_json_schema": schema})

        without = {key: value for key, value in config.items() if key != "response_json_schema"}
        mutations = {
            "full_schema_used_natively": replace(
                self.spec, generation_config={**config, "response_json_schema": full_schema()}),
            "missing_native_schema": replace(self.spec, generation_config=without),
            "projection_weakened": with_schema(lambda s: s["$defs"]["Assertion"]["required"].remove("support")),
            "projection_strengthened": with_schema(lambda s: s["$defs"]["Handle"].__setitem__("pattern", "^A")),
            "projection_reordered_property_removed": with_schema(lambda s: s["properties"].pop("events")),
            "projection_empty": with_schema(lambda s: s.clear()),
            "stage1_schema": replace(self.spec, generation_config={**config, "response_json_schema": runner.STAGE1_SCHEMA}),
            "model_switch": replace(self.spec, model="gemini-3.5-flash"),
            "credential_switch": replace(self.spec, credential_slot="gemini_slot_1"),
            "temperature": replace(self.spec, generation_config={**config, "temperature": 1}),
            "temperature_type": replace(self.spec, generation_config={**config, "temperature": 0.0}),
            "max_tokens": replace(self.spec, generation_config={**config, "max_output_tokens": 8192}),
            "extra_setting": replace(self.spec, generation_config={**config, "top_p": 1}),
            "mode": replace(self.spec, schema_response_mode=protocol_v1.SCHEMA_RESPONSE_MODE),
            "task": replace(self.spec, research_task_id=protocol_v1.PROTOCOL_ID),
            "system_prompt": replace(self.spec, system_prompt=self.spec.system_prompt + " "),
            "v1_job_id": replace(self.spec, job_id="M4B4B_P4_SYNTHETIC_SMOKE_01_PRIMARY"),
            "second_repair": replace(self.spec, job_id="M4B4BR_P4V2_SYNTHETIC_SMOKE_01_REPAIR_2"),
        }
        for label, mutated in mutations.items():
            with self.subTest(mutation=label), self.assertRaises(protocol.P4ProtocolV2Error):
                protocol.assert_locked_job_spec(mutated)
        with self.assertRaisesRegex(protocol.P4ProtocolV2Error, "full model schema must not"):
            protocol.assert_locked_job_spec(mutations["full_schema_used_natively"])
        with self.assertRaisesRegex(protocol.P4ProtocolV2Error, "mandatory"):
            protocol.assert_locked_job_spec(mutations["missing_native_schema"])
        with self.assertRaisesRegex(protocol.P4ProtocolV2Error, "exact provider projection"):
            protocol.assert_locked_job_spec(mutations["projection_weakened"])

    def test_v1_and_v2_checkers_are_separate(self):
        v1_spec = protocol_v1.build_primary_spec(self.case.case_id, self.case.prepared_input)
        protocol_v1.assert_locked_job_spec(v1_spec)
        with self.assertRaises(protocol.P4ProtocolV2Error):
            protocol.assert_locked_job_spec(v1_spec)
        with self.assertRaises(protocol_v1.P4ProtocolError):
            protocol_v1.assert_locked_job_spec(self.spec)
        self.assertNotEqual(v1_spec.request_fingerprint, self.spec.request_fingerprint)

    def test_repair_spec_keeps_the_projection_and_needs_diagnostic_v2(self):
        raw = encoded(weaker_examples()["pattern"])
        diagnostic = contract.structural_diagnostic_v2(raw)
        spec = protocol.build_repair_spec(self.case.case_id, self.case.prepared_input, raw, diagnostic)
        protocol.assert_locked_job_spec(spec)
        self.assertEqual("M4B4BR_P4V2_SYNTHETIC_SMOKE_01_REPAIR_1", spec.job_id)
        self.assertEqual(contract.prompt_material()["repair_system"], spec.system_prompt)
        self.assertEqual(dict(self.spec.generation_config), dict(spec.generation_config))
        for bad in ({**diagnostic, "category": "LOW_COVERAGE"}, {**diagnostic, "findings": []},
                    {**diagnostic, "diagnostic": "OTHER"}, None):
            with self.assertRaises(protocol.P4ProtocolV2Error):
                protocol.build_repair_spec(self.case.case_id, self.case.prepared_input, raw, bad)


class ProtocolV2CaseExecutionTests(unittest.TestCase):
    """Offline core for a later tuning run. Mocked provider, zero operations."""

    PRIMARY = STAGE2
    REPAIR = "M4B4BR_P4V2_SYNTHETIC_SMOKE_01_REPAIR_1"

    def setUp(self):
        self.case = runner_v1.synthetic_smoke_case()

    def run_case(self, responses, **kwargs):
        provider = runner.OfflineMockProvider(responses)
        return runner.execute_case(self.case, provider, **kwargs), provider

    def test_valid_primary_needs_no_repair(self):
        result, provider = self.run_case({self.PRIMARY: encoded(SMOKE_DRAFT), self.REPAIR: encoded(SMOKE_DRAFT)})
        self.assertEqual(("STRUCTURAL_VALID", 0), (result["terminal_status"], result["repair_count"]))
        self.assertEqual([self.PRIMARY], provider.calls)
        self.assertEqual(0, provider.actual_provider_operations)

    def test_projection_valid_but_full_invalid_draft_is_a_structural_failure(self):
        broken = edited(lambda d: d["mentions"][0].__setitem__("handle", "X1"), SMOKE_DRAFT)
        self.assertTrue(Draft202012Validator(projected_schema()).is_valid(broken))
        result, provider = self.run_case({self.PRIMARY: encoded(broken), self.REPAIR: encoded(SMOKE_DRAFT)})
        primary = result["attempts"][0]["validation"]
        self.assertEqual("DRAFT_SCHEMA_FAILURE", primary["category"])
        self.assertEqual(contract.REPAIR_DIAGNOSTIC_ID, primary["diagnostic"]["diagnostic"])
        self.assertEqual([self.PRIMARY, self.REPAIR], provider.calls)
        self.assertEqual(("STRUCTURAL_VALID", 1), (result["terminal_status"], result["repair_count"]))
        self.assertEqual(projection.load_tracked_projection(), provider.specs[1].generation_config["response_json_schema"])

    def test_one_repair_at_most_and_no_quality_retry(self):
        responses = {self.PRIMARY: "{", self.REPAIR: "{", "M4B4BR_P4V2_SYNTHETIC_SMOKE_01_REPAIR_2": encoded(SMOKE_DRAFT)}
        result, provider = self.run_case(responses)
        self.assertEqual(("STRUCTURAL_FAILURE", 1), (result["terminal_status"], result["repair_count"]))
        self.assertEqual([self.PRIMARY, self.REPAIR], provider.calls)
        empty = {key: ([] if isinstance(value, list) else value) for key, value in SMOKE_DRAFT.items()}
        result, provider = self.run_case({self.PRIMARY: encoded(empty), self.REPAIR: encoded(SMOKE_DRAFT)})
        self.assertEqual([self.PRIMARY], provider.calls)
        self.assertEqual(0, result["quality_or_coverage_retries"])
        result, provider = self.run_case({self.PRIMARY: "{"}, allow_repair=False)
        self.assertEqual(("STRUCTURAL_FAILURE", 0), (result["terminal_status"], result["repair_count"]))

    def test_first_success_is_immutable_and_requests_must_be_locked(self):
        ledger = FirstSuccessLedger()
        runner.execute_case(self.case, runner.OfflineMockProvider({self.PRIMARY: encoded(SMOKE_DRAFT)}), ledger=ledger)
        with self.assertRaisesRegex(runner.P4RunnerError, "Immutable first-success"):
            runner.execute_case(self.case, runner.OfflineMockProvider({self.PRIMARY: "{}"}), ledger=ledger)
        provider = runner.OfflineMockProvider({self.PRIMARY: encoded(SMOKE_DRAFT)})
        v1_spec = protocol_v1.build_primary_spec(self.case.case_id, self.case.prepared_input)
        with self.assertRaises(protocol.P4ProtocolV2Error):
            provider.first_success(v1_spec)
        self.assertEqual([], provider.calls)


class ExperimentLockTests(unittest.TestCase):
    def test_experiment_is_hash_locked_before_any_request(self):
        self.assertEqual(EXPERIMENT_SHA256, runner.experiment_sha256())
        self.assertEqual(EXPERIMENT_SHA256, runner.EXPERIMENT_SHA256)
        experiment = runner.locked_experiment()
        self.assertEqual(runner.build_experiment(), experiment)
        self.assertEqual(PROTOCOL_V2_SHA256, experiment["protocol_sha256"])
        self.assertEqual({"total": 2, "per_stage": 1}, experiment["operation_budget"])
        self.assertEqual((2, 1), (runner.TOTAL_OPERATION_BUDGET, runner.STAGE_OPERATION_BUDGET))
        self.assertEqual(0, experiment["repair_calls"])
        self.assertIs(True, experiment["synthetic_only"])
        self.assertEqual("FORBIDDEN", experiment["provider_error_message_capture"])
        self.assertEqual(runner.INTERPRETATION_MATRIX, experiment["interpretation_matrix"])

    def test_changed_matrix_stage_or_budget_is_a_different_experiment(self):
        changed_matrix = copy.deepcopy(runner.INTERPRETATION_MATRIX)
        changed_matrix["cases"]["CASE_B"]["ready_for_DEV3_tuning"] = True
        for name, value in (("INTERPRETATION_MATRIX", changed_matrix), ("TOTAL_OPERATION_BUDGET", 3),
                            ("STAGE1_USER", "Another prompt."),
                            ("STAGE1_SCHEMA", {**runner.STAGE1_SCHEMA, "required": []})):
            with self.subTest(binding=name), mock.patch.object(runner, name, value):
                with self.assertRaises(runner.P4RunnerError):
                    runner.locked_experiment()
                with self.assertRaises(CheckpointIntegrityError):
                    runner.build_guard()()

    def test_interpretation_matrix(self):
        cases = {
            (runner.REJECTED, runner.NOT_RUN): ("CASE_A", "M4_04B4BR_MINIMAL_NATIVE_SCHEMA_REJECTED", False),
            (runner.ACCEPTED, runner.REJECTED): ("CASE_B", "M4_04B4BR_P4_PROJECTION_REJECTED", False),
            (runner.ACCEPTED, runner.ACCEPTED): ("CASE_C", "M4_04B4BR_PROVIDER_PROJECTION_READY", True),
            (runner.UNDETERMINED, runner.NOT_RUN): ("UNDETERMINED", None, False),
            (runner.ACCEPTED, runner.UNDETERMINED): ("UNDETERMINED", None, False),
            (runner.REJECTED, runner.ACCEPTED): ("UNDETERMINED", None, False),
            (runner.ACCEPTED, runner.NOT_RUN): ("UNDETERMINED", None, False),
        }
        for outcomes, (case, status, ready) in cases.items():
            with self.subTest(outcomes=outcomes):
                verdict = runner.interpret(*outcomes)
                self.assertEqual((case, status, ready),
                                 (verdict["case"], verdict["status"], verdict["ready_for_DEV3_tuning"]))
        a = runner.interpret(runner.REJECTED, runner.NOT_RUN)
        self.assertEqual("NATIVE_SCHEMA_PARAMETER_OR_MINIMAL_SCHEMA_NOT_ACCEPTED_ON_LOCKED_MODEL_PATH", a["conclusion"])
        self.assertTrue(a["next_action"].endswith("P4 JSON-MIME-ONLY RUNTIME"))
        self.assertTrue(runner.interpret(runner.ACCEPTED, runner.REJECTED)["next_action"].endswith(
            "PROVIDER PROJECTION INCOMPATIBILITY"))
        self.assertTrue(runner.interpret(runner.ACCEPTED, runner.ACCEPTED)["next_action"].endswith(
            "P4 STRUCTURAL TUNING RUN ON DEV3 INPUT USING PROTOCOL V2 AND EXACT PROVIDER PROJECTION"))
        self.assertIs(True, runner.INTERPRETATION_MATRIX["no_outcome_is_an_extraction_quality_result"])

    def test_stage1_is_a_minimal_documented_schema_and_not_draft_v1_1(self):
        spec = runner.build_stage1_spec()
        runner.assert_stage1_spec(spec)
        self.assertEqual(
            {"type": "object", "additionalProperties": False, "required": ["status"],
             "properties": {"status": {"type": "string", "enum": ["OK"]}}},
            spec.generation_config["response_json_schema"],
        )
        used = projection.assert_provider_subset(copy.deepcopy(runner.STAGE1_SCHEMA))["keywords_used"]
        self.assertEqual(["additionalProperties", "enum", "properties", "required", "type"], used)
        self.assertEqual((protocol.MODEL, protocol.CREDENTIAL_SLOT), (spec.model, spec.credential_slot))
        self.assertEqual((0, 16384), (spec.generation_config["temperature"], spec.generation_config["max_output_tokens"]))
        text = spec.system_prompt + spec.user_prompt + json.dumps(spec.generation_config)
        for word in ("draft_version", "DRAFT_V1_1", "passage", "Tomas", "$defs"):
            self.assertNotIn(word, text)
        config = dict(spec.generation_config)
        for label, mutated in {
            "schema": replace(spec, generation_config={**config, "response_json_schema": projected_schema()}),
            "no_schema": replace(spec, generation_config={"temperature": 0, "max_output_tokens": 16384}),
            "model": replace(spec, model="gemini-3.5-flash"),
            "slot": replace(spec, credential_slot="gemini_slot_1"),
            "prompt": replace(spec, user_prompt="Tell a story."),
            "job": replace(spec, job_id=STAGE2),
        }.items():
            with self.subTest(mutation=label), self.assertRaises(runner.P4RunnerError):
                runner.assert_stage1_spec(mutated)

    def test_stage2_differs_from_the_rejected_v1_request_only_in_its_native_schema(self):
        self.assertEqual({True}, set(runner.stage2_isolation().values()))
        case, spec = runner.build_stage2_spec()
        self.assertEqual(STAGE2, spec.job_id)
        self.assertEqual(runner_v1.synthetic_smoke_case().prepared_input, case.prepared_input)
        self.assertEqual(1, len(case.prepared_input["passages"]))


class TwoStageSmokeMockedTests(unittest.TestCase):
    """The smoke with an injected transport. No provider is constructed."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="m4b4br_smoke_")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "private"
        self.calls = []

    def factory(self, behaviours):
        def build(pacer, guard):
            def transport(spec, window, request_id):
                self.calls.append(spec.job_id)
                guard()
                return behaviours[spec.job_id](pacer, spec)
            return transport
        return build

    @staticmethod
    def success(raw):
        def behaviour(pacer, spec):
            pacer.acquire()
            return {"raw_content": raw, "model_requested": spec.model, "slot_id": spec.credential_slot,
                    "transport_attempts": [{"model": spec.model, "slot_id": spec.credential_slot,
                                            "classified_result": "SUCCESS", "http_status": 200}],
                    "attempt_accounting": {"total_provider_attempts": 1}}
        return behaviour

    @staticmethod
    def failure(category, status, reason, attempts=1):
        def behaviour(pacer, spec):
            history = []
            for _ in range(attempts):
                try:
                    pacer.acquire()
                except runner_v1.OperationBudgetExhausted:
                    raise CheckpointIntegrityError("Global pacing attempt accounting mismatch") from None
                history.append({"model": spec.model, "slot_id": spec.credential_slot, "classified_result": category,
                                "http_status": status, "provider_reason": reason})
            raise DurableTransportFailure(category, provider_attempts=len(history),
                                          fingerprint=f"{category}:{status}", attempts=history)
        return behaviour

    def smoke(self, stage1, stage2=None):
        behaviours = {STAGE1: stage1}
        if stage2 is not None:
            behaviours[STAGE2] = stage2
        return runner.run_two_stage_smoke(private_root=self.root, transport_factory=self.factory(behaviours))

    def stage2_checkpoints(self):
        directory = self.root / "checkpoints" / "stage2_jobs"
        return sorted(path.name for path in directory.glob("*.json")) if directory.exists() else []

    def test_both_stages_accepted_is_case_c_with_two_operations_and_no_repair(self):
        result = self.smoke(self.success(STAGE1_OK), self.success(encoded(SMOKE_DRAFT)))
        self.assertEqual([STAGE1, STAGE2], self.calls)
        self.assertEqual(2, result["provider_operations"])
        self.assertEqual(0, result["repair_calls"])
        stage1, stage2 = result["stage1"], result["stage2"]
        self.assertEqual((runner.ACCEPTED, True, 1), (stage1["outcome"], stage1["minimal_native_schema_accepted"],
                                                      stage1["provider_operations"]))
        self.assertEqual((True, True), (stage1["json_parse"], stage1["matches_minimal_schema"]))
        self.assertEqual(
            (True, True, True, True, True, True),
            (stage2["provider_request_accepted"], stage2["response_received"], stage2["json_parse"],
             stage2["provider_projection_validation"], stage2["full_local_draft_v1_1_validation"], stage2["compiler"]),
        )
        self.assertEqual(("CASE_C", "M4_04B4BR_PROVIDER_PROJECTION_READY"),
                         (result["verdict"]["case"], result["verdict"]["status"]))
        self.assertIs(True, result["synthetic_only"])
        self.assertIs(False, result["dataset_accessed"])
        self.assertEqual((PROTOCOL_V2_SHA256, EXPERIMENT_SHA256, PROJECTION_SHA256),
                         (result["protocol_sha256"], result["experiment_sha256"], result["provider_projection_sha256"]))
        self.assertEqual(["M4B4BR_P4V2_SYNTHETIC_SMOKE_01_PRIMARY.json"], self.stage2_checkpoints())
        self.assertNotIn("_record", stage1)
        self.assertNotIn("_record", stage2)
        stored = json.loads((self.root / f"{runner.SMOKE_RESULT_ID}.json").read_text(encoding="utf-8"))
        self.assertEqual(result, stored)
        self.assertNotIn("Tomas", json.dumps(stored))

    def test_stage1_rejection_stops_everything_case_a(self):
        result = self.smoke(self.failure("PROVIDER_FAILURE", 400, "INVALID_ARGUMENT"), self.success(encoded(SMOKE_DRAFT)))
        self.assertEqual([STAGE1], self.calls)
        self.assertEqual(1, result["provider_operations"])
        self.assertIs(False, result["stage1"]["minimal_native_schema_accepted"])
        self.assertEqual("PROVIDER_FAILURE:400:INVALID_ARGUMENT", result["stage1"]["provider_rejection_category"])
        self.assertEqual({"executed": False, "outcome": runner.NOT_RUN, "provider_operations": 0,
                          "reason": "STAGE_1_WAS_NOT_ACCEPTED", "job_id": STAGE2}, result["stage2"])
        self.assertEqual([], self.stage2_checkpoints())
        self.assertEqual(("CASE_A", "M4_04B4BR_MINIMAL_NATIVE_SCHEMA_REJECTED"),
                         (result["verdict"]["case"], result["verdict"]["status"]))
        self.assertEqual("NATIVE_SCHEMA_PARAMETER_OR_MINIMAL_SCHEMA_NOT_ACCEPTED_ON_LOCKED_MODEL_PATH",
                         result["verdict"]["conclusion"])
        self.assertIs(False, result["verdict"]["ready_for_DEV3_tuning"])

    def test_stage2_rejection_is_case_b(self):
        result = self.smoke(self.success(STAGE1_OK), self.failure("PROVIDER_FAILURE", 400, "INVALID_ARGUMENT"))
        self.assertEqual([STAGE1, STAGE2], self.calls)
        self.assertEqual(2, result["provider_operations"])
        stage2 = result["stage2"]
        self.assertEqual((False, False), (stage2["provider_request_accepted"], stage2["response_received"]))
        self.assertEqual((None, None, None, None),
                         (stage2["json_parse"], stage2["provider_projection_validation"],
                          stage2["full_local_draft_v1_1_validation"], stage2["compiler"]))
        self.assertEqual(("CASE_B", "M4_04B4BR_P4_PROJECTION_REJECTED"),
                         (result["verdict"]["case"], result["verdict"]["status"]))
        self.assertEqual(JobState.DEFERRED_TRANSPORT.value, stage2["job_state"])

    def test_projection_valid_but_full_invalid_response_is_still_case_c_and_spends_no_repair(self):
        broken = edited(lambda d: d["mentions"][0].__setitem__("handle", "X1"), SMOKE_DRAFT)
        result = self.smoke(self.success(STAGE1_OK), self.success(encoded(broken)))
        stage2 = result["stage2"]
        self.assertEqual((True, True, False, None),
                         (stage2["json_parse"], stage2["provider_projection_validation"],
                          stage2["full_local_draft_v1_1_validation"], stage2["compiler"]))
        self.assertEqual("DRAFT_SCHEMA_FAILURE", stage2["structural_failure_category"])
        self.assertEqual("CASE_C", result["verdict"]["case"])
        self.assertEqual([STAGE1, STAGE2], self.calls)
        self.assertEqual(2, result["provider_operations"])
        self.assertFalse(any("REPAIR" in name for name in self.stage2_checkpoints()))

    def test_other_local_outcomes_are_recorded_independently(self):
        cases = (
            ('{"draft_version": ', (False, None, None, None)),
            (encoded(edited(lambda d: d.__setitem__("zz", 1), SMOKE_DRAFT)), (True, False, False, None)),
            (encoded(edited(lambda d: d["assertions"][0].__setitem__("proposition_handle", "PROP998"), SMOKE_DRAFT)),
             (True, True, True, False)),
        )
        for index, (raw, stages) in enumerate(cases):
            with self.subTest(index=index):
                self.root = self.root.parent / f"private_{index}"
                self.calls = []
                stage2 = self.smoke(self.success(STAGE1_OK), self.success(raw))["stage2"]
                self.assertEqual(stages, (stage2["json_parse"], stage2["provider_projection_validation"],
                                          stage2["full_local_draft_v1_1_validation"], stage2["compiler"]))
                self.assertEqual(2, len(self.calls))

    def test_stage1_response_content_does_not_decide_acceptance(self):
        result = self.smoke(self.success('{"status": "NO"}'), self.success(encoded(SMOKE_DRAFT)))
        self.assertEqual((runner.ACCEPTED, True, False),
                         (result["stage1"]["outcome"], result["stage1"]["json_parse"],
                          result["stage1"]["matches_minimal_schema"]))
        self.assertEqual([STAGE1, STAGE2], self.calls)

    def test_transient_stage1_failure_is_undetermined_and_stage2_does_not_run(self):
        result = self.smoke(self.failure("SERVER_FAILURE", 503, "UNAVAILABLE", attempts=2),
                            self.success(encoded(SMOKE_DRAFT)))
        self.assertEqual([STAGE1], self.calls)
        self.assertEqual(1, result["provider_operations"])
        self.assertTrue(result["stage1"]["operation_budget_exhausted"])
        self.assertEqual(runner.UNDETERMINED, result["stage1"]["outcome"])
        self.assertEqual(runner.UNDETERMINED, result["stage1"]["minimal_native_schema_accepted"])
        self.assertEqual(runner.NOT_RUN, result["stage2"]["outcome"])
        self.assertEqual(("UNDETERMINED", None), (result["verdict"]["case"], result["verdict"]["status"]))
        self.assertEqual([], self.stage2_checkpoints())

    def test_authentication_failure_is_not_a_schema_rejection(self):
        result = self.smoke(self.failure("AUTH_FAILURE", 403, "PERMISSION_DENIED"))
        self.assertEqual(runner.UNDETERMINED, result["stage1"]["outcome"])
        self.assertEqual("AUTH_FAILURE:403:PERMISSION_DENIED", result["stage1"]["provider_rejection_category"])
        self.assertEqual("UNDETERMINED", result["verdict"]["case"])

    def test_each_stage_is_limited_to_one_operation_and_the_total_to_two(self):
        result = self.smoke(self.success(STAGE1_OK), self.failure("SERVER_FAILURE", 503, "UNAVAILABLE", attempts=3))
        self.assertEqual(2, result["provider_operations"])
        self.assertEqual((1, 1), (result["stage1"]["provider_operations"], result["stage2"]["provider_operations"]))
        self.assertTrue(result["stage2"]["operation_budget_exhausted"])
        self.assertEqual("UNDETERMINED", result["verdict"]["case"])
        pacing = json.loads((self.root / "checkpoints" / "global_pacing.json").read_text(encoding="utf-8"))["payload"]
        self.assertEqual(2, pacing["total_reservations"])

    def test_smoke_is_not_repeated_and_never_reaches_a_third_operation(self):
        self.smoke(self.success(STAGE1_OK), self.success(encoded(SMOKE_DRAFT)))
        self.assertEqual(2, len(self.calls))
        for _ in range(2):
            with self.assertRaisesRegex(runner.P4RunnerError, "not repeated"):
                self.smoke(self.success(STAGE1_OK), self.success(encoded(SMOKE_DRAFT)))
        self.assertEqual(2, len(self.calls))
        pacer, stage1_executor, _ = runner.build_durable_stack(self.root / "checkpoints")
        with self.assertRaises(runner.OperationBudgetViolation):
            runner._run_stage(stage1_executor, runner.build_stage1_spec(), pacer, lambda budgeted: None)

    def test_private_root_must_be_new_ignored_and_not_a_dataset_location(self):
        repository = runner.REPO_ROOT
        outside = self.root.parent
        for root in (repository, repository / "benchmarks" / "smoke", repository / ".local" / "m4_04b3_dev3" / "x",
                     repository / ".local" / "m4_04b4b_p4_synthetic_smoke", outside / "DEV3_input",
                     outside / "holdout_set", outside / "gold" / "smoke"):
            with self.subTest(root=str(root.name)), self.assertRaises(runner.P4RunnerError):
                runner.run_two_stage_smoke(private_root=root, transport_factory=self.factory({}))
        self.assertEqual([], self.calls)
        self.assertEqual(".local", runner.DEFAULT_SMOKE_ROOT.relative_to(repository).parts[0])
        self.assertNotEqual(runner_v1.DEFAULT_SMOKE_ROOT, runner.DEFAULT_SMOKE_ROOT)

    def test_changed_protocol_stops_the_smoke_before_any_request(self):
        relative = "schemas/story_extraction/story_extraction_draft_v1_1_gemini_response_schema_v1.schema.json"
        with mock.patch.dict(protocol.BOUND_FILES, {relative: "0" * 64}):
            with self.assertRaises(protocol.P4ProtocolV2Error):
                self.smoke(self.success(STAGE1_OK), self.success(encoded(SMOKE_DRAFT)))
        self.assertEqual([], self.calls)

    def test_command_line_takes_no_dataset_and_needs_the_authorization_token(self):
        for arguments in (["--mode", "two-stage-smoke"],
                          ["--mode", "two-stage-smoke", "--authorize-live-provider-operations", "M4-04B4B-SYNTHETIC-SMOKE"]):
            output = io.StringIO()
            with mock.patch.object(runner, "run_two_stage_smoke") as smoke, contextlib.redirect_stdout(output):
                self.assertEqual(2, runner.main(arguments))
            smoke.assert_not_called()
            self.assertIn("FAIL_CLOSED", output.getvalue())
        for option in ("--input-archive", "--gold", "--dev3-input", "--protocol"):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    runner.main(["--mode", "verify", option, "x.zip"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(0, runner.main(["--mode", "verify"]))
        self.assertEqual(0, json.loads(output.getvalue())["provider_operations"])

    def test_runner_has_no_dataset_gold_evaluator_or_direct_sdk_path(self):
        for function in (runner.run_two_stage_smoke, runner.execute_case, runner.build_stage2_spec,
                         runner.build_stage1_spec):
            names = set(inspect.signature(function).parameters)
            self.assertFalse(any(token in name.lower() for name in names
                                 for token in ("gold", "evaluat", "input", "archive", "dataset")))
        source = Path(runner.__file__).read_text(encoding="utf-8")
        for forbidden in ("zipfile", "import google", "from google", "genai", "official_client_factory",
                          "generate_content", "str(error)", "error.args", "traceback"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("build_repair_spec", inspect.getsource(runner.run_two_stage_smoke))


class FakeProviderError(Exception):
    """Shaped like an SDK API error: a status code, a structured status and a message."""

    def __init__(self, code, status):
        super().__init__(f"{code} {status}. {MARKER} provider message text")
        self.code = code
        self.status = status


class TwoStageSmokeAcceptedTransportTests(unittest.TestCase):
    """The live path end to end with the SDK client replaced. No network, no real key."""

    FAKE_KEY = "synthetic-credential-3-not-a-real-key"

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="m4b4br_live_path_")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "private"
        self.env = Path(directory.name) / "absent.env"
        self.requests = []
        self.keys = []

    def smoke(self, respond, environ=None):
        from tools.story_extraction.gemini_key_pool_v1 import load_runtime_config

        environ = {"GEMINI_API_KEY_3": self.FAKE_KEY} if environ is None else environ

        def fake_client_factory(api_key):
            self.keys.append(api_key)

            def generate(**kwargs):
                self.requests.append(kwargs)
                return respond(len(self.requests), kwargs)
            return SimpleNamespace(generate=generate)

        patches = (
            mock.patch.object(runner, "load_runtime_config", side_effect=lambda: load_runtime_config(self.env, environ)),
            mock.patch.object(runner, "verify_execution_environment",
                              return_value={"method": "SYNTHETIC_TEST_ENVIRONMENT", "source_commit": "0" * 40}),
            mock.patch("tools.story_extraction.run_m4_04b2_dev_predictions_v1.official_client_factory",
                       side_effect=fake_client_factory),
            mock.patch("time.sleep"),
        )
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            return runner.run_two_stage_smoke(private_root=self.root)

    def private_text(self):
        return "\n".join(path.read_text(encoding="utf-8") for path in self.root.rglob("*") if path.is_file())

    @staticmethod
    def answer(text):
        return SimpleNamespace(text=text, usage_metadata=None, model_version="synthetic-model-version")

    def both_ok(self, count, kwargs):
        return self.answer(STAGE1_OK if count == 1 else encoded(SMOKE_DRAFT))

    def test_two_requests_minimal_schema_then_projection_with_full_schema_in_prompt(self):
        result = self.smoke(self.both_ok)
        self.assertEqual(2, len(self.requests))
        first, second = self.requests
        self.assertEqual(runner.STAGE1_SCHEMA, first["generation_config"]["response_json_schema"])
        self.assertEqual((runner.STAGE1_SYSTEM, runner.STAGE1_USER), (first["system_instruction"], first["user_content"]))
        self.assertEqual(projection.load_tracked_projection(), second["generation_config"]["response_json_schema"])
        self.assertNotEqual(full_schema(), second["generation_config"]["response_json_schema"])
        in_prompt = contract.extract_prompt_schema(
            second["system_instruction"], contract.SCHEMA_SECTION_MARKER, contract.REGISTRY_SECTION_MARKER
        )
        self.assertEqual(full_schema(), in_prompt)
        self.assertIn(runner_v1.SMOKE_TEXT, second["user_content"])
        for request in self.requests:
            self.assertEqual("gemini-3.5-flash-lite", request["model"])
            self.assertEqual({"temperature", "max_output_tokens", "response_json_schema"},
                             set(request["generation_config"]))
            self.assertEqual((0, 16384), (request["generation_config"]["temperature"],
                                          request["generation_config"]["max_output_tokens"]))
        self.assertEqual([self.FAKE_KEY, self.FAKE_KEY], self.keys)
        self.assertEqual("ACCEPTED_GEMINI_DEV_WINDOW_TRANSPORT", result["transport"])
        self.assertEqual(("CASE_C", 2), (result["verdict"]["case"], result["provider_operations"]))
        self.assertEqual(protocol.normalized_file_sha256(Path(runner.__file__)), result["runner_sha256"])
        self.assertEqual(protocol.normalized_file_sha256(Path(protocol.__file__)), result["protocol_module_sha256"])
        self.assertEqual(protocol.normalized_file_sha256(Path(projection.__file__)), result["projection_tool_sha256"])
        self.assertNotIn(self.FAKE_KEY, self.private_text())

    def test_stage1_400_sends_exactly_one_request(self):
        def respond(count, kwargs):
            raise FakeProviderError(400, "INVALID_ARGUMENT")

        result = self.smoke(respond)
        self.assertEqual(1, len(self.requests))
        self.assertEqual(runner.STAGE1_SCHEMA, self.requests[0]["generation_config"]["response_json_schema"])
        self.assertEqual(("CASE_A", 1), (result["verdict"]["case"], result["provider_operations"]))
        self.assertEqual("PROVIDER_FAILURE:400:INVALID_ARGUMENT", result["stage1"]["provider_rejection_category"])
        text = self.private_text()
        self.assertNotIn(MARKER, text)
        self.assertNotIn(self.FAKE_KEY, text)
        with self.assertRaisesRegex(runner.P4RunnerError, "not repeated"):
            self.smoke(self.both_ok)
        self.assertEqual(1, len(self.requests))

    def test_stage2_400_sends_exactly_two_requests(self):
        def respond(count, kwargs):
            if count == 1:
                return self.answer(STAGE1_OK)
            raise FakeProviderError(400, "INVALID_ARGUMENT")

        result = self.smoke(respond)
        self.assertEqual(2, len(self.requests))
        self.assertEqual(("CASE_B", 2), (result["verdict"]["case"], result["provider_operations"]))
        self.assertNotIn(MARKER, self.private_text())

    def test_server_failure_is_never_retried_inside_a_stage(self):
        def respond(count, kwargs):
            raise FakeProviderError(503, "UNAVAILABLE")

        result = self.smoke(respond)
        self.assertEqual(1, len(self.requests))
        self.assertEqual(("UNDETERMINED", 1), (result["verdict"]["case"], result["provider_operations"]))
        self.assertEqual(runner.NOT_RUN, result["stage2"]["outcome"])

    def test_stage2_server_failure_stops_at_two_requests(self):
        def respond(count, kwargs):
            if count == 1:
                return self.answer(STAGE1_OK)
            raise FakeProviderError(503, "UNAVAILABLE")

        result = self.smoke(respond)
        self.assertEqual(2, len(self.requests))
        self.assertEqual(("UNDETERMINED", 2), (result["verdict"]["case"], result["provider_operations"]))

    def test_only_the_locked_credential_slot_is_used(self):
        for environ in ({}, {"GEMINI_API_KEY_1": "synthetic-credential-1"}):
            with self.subTest(slots=sorted(environ)), self.assertRaises(runner.P4RunnerError):
                self.smoke(self.both_ok, environ=environ)
        self.assertEqual(([], []), (self.keys, self.requests))
        environ = {"GEMINI_API_KEY_1": "synthetic-credential-1", "GEMINI_API_KEY_3": self.FAKE_KEY}
        self.smoke(self.both_ok, environ=environ)
        self.assertEqual([self.FAKE_KEY, self.FAKE_KEY], self.keys)


class PublicRecordTests(unittest.TestCase):
    """The public record of the projection, protocol V2 and the two-stage live smoke."""

    RECORD = protocol.REPO_ROOT / "benchmarks/m4_extraction/M4_04B4BR_PROVIDER_SCHEMA_PROJECTION_AND_SMOKE.yaml"

    def setUp(self):
        import yaml

        self.text = self.RECORD.read_text(encoding="utf-8")
        self.record = yaml.safe_load(self.text)

    def test_record_identifies_prior_result_projection_and_protocol_v2(self):
        record = self.record
        self.assertEqual("M4-04B4BR", record["task"])
        self.assertEqual(protocol.EXPECTED_BASE_COMMIT, record["base_commit"])
        prior = record["prior_B4B"]
        self.assertEqual("M4_04B4B_NATIVE_SCHEMA_PROVIDER_REJECTED", prior["status"])
        self.assertEqual(PROTOCOL_V1_SHA256, prior["protocol_v1_sha256"])
        self.assertEqual("PROVIDER_FAILURE:400:INVALID_ARGUMENT", prior["provider_rejection"])
        projected = record["projection"]
        self.assertEqual(projection.PROJECTION_IDENTITY, projected["identity"])
        self.assertEqual((FULL_SHA256, PROJECTION_SHA256),
                         (projected["source_full_schema_sha256"], projected["projection_sha256"]))
        manifest = projection.transformation_manifest()
        self.assertEqual(manifest["action_counts"], projected["transformation_counts"])
        self.assertEqual(manifest["transformation_count"], projected["transformation_total"])
        self.assertEqual(0, projected["external_refs"])
        self.assertEqual(0, projected["relaxation_gate"]["full_corpus"]["full_valid_but_projection_invalid"])
        self.assertEqual("PASS", projected["relaxation_gate"]["result"])
        locked = record["protocol_v2"]
        self.assertEqual((protocol.PROTOCOL_ID, PROTOCOL_V2_SHA256), (locked["identity"], locked["sha256"]))
        self.assertEqual(protocol.protocol_sha256(), locked["sha256"])
        self.assertEqual(("gemini-3.5-flash-lite", "gemini_slot_3", protocol.RUNTIME_VERSION),
                         (locked["model"], locked["credential_slot"], locked["runtime"]))
        self.assertEqual((FULL_SHA256, PROJECTION_SHA256),
                         (locked["full_prompt_schema_sha256"], locked["native_projection_sha256"]))
        self.assertEqual(protocol.generation_config_sha256(), locked["generation_config_sha256"])
        self.assertEqual(dict(protocol.BOUND_FILES), locked["bound_files"])

    def test_the_code_that_ran_live_is_the_code_that_is_tracked(self):
        live = self.record["live"]
        self.assertEqual(protocol.normalized_file_sha256(Path(runner.__file__)), live["executed_runner_sha256"])
        self.assertEqual(protocol.normalized_file_sha256(Path(protocol.__file__)), live["executed_protocol_module_sha256"])
        self.assertEqual(protocol.normalized_file_sha256(Path(projection.__file__)), live["executed_projection_tool_sha256"])
        self.assertEqual((PROTOCOL_V2_SHA256, EXPERIMENT_SHA256),
                         (live["executed_protocol_sha256"], live["experiment_sha256"]))
        self.assertEqual(runner.experiment_sha256(), live["experiment_sha256"])
        self.assertEqual(runner.INTERPRETATION_MATRIX["cases"], self.record["interpretation_matrix"]["cases"])
        self.assertIs(True, self.record["interpretation_matrix"]["locked_before_live_calls"])

    def test_live_smoke_stayed_inside_its_authorization(self):
        live = self.record["live"]
        self.assertEqual(2, live["operation_budget"])
        self.assertLessEqual(live["actual_operations"], 2)
        self.assertEqual(live["actual_operations"],
                         live["stage1"]["provider_operations"] + live["stage2"]["provider_operations"])
        self.assertLessEqual(live["stage1"]["provider_operations"], 1)
        self.assertLessEqual(live["stage2"]["provider_operations"], 1)
        self.assertIs(True, live["synthetic_only"])
        self.assertEqual(0, live["repair_calls"])
        self.assertIs(False, live["provider_error_message_captured"])
        self.assertIs(False, live["one_off_direct_sdk_call"])
        self.assertEqual("gemini_slot_3", live["credential"]["slot"])
        self.assertIs(False, live["credential"]["secret_value_in_any_artifact"])
        self.assertEqual(0, self.record["offline"]["provider_operations_before_smoke"])

    def test_status_follows_from_the_locked_interpretation_matrix(self):
        record, live = self.record, self.record["live"]
        verdict = runner.interpret(live["stage1"]["outcome"], live["stage2"]["outcome"])
        self.assertEqual(verdict["status"], record["status"])
        self.assertEqual(verdict["case"], live["case"])
        decision = record["decision"]
        self.assertEqual(verdict["native_schema_runtime_capability"], decision["native_schema_runtime_capability"])
        self.assertEqual(verdict["provider_projection_compatible"], decision["provider_projection_compatible"])
        self.assertEqual(verdict["ready_for_DEV3_tuning"], decision["ready_for_DEV3_tuning"])
        self.assertEqual(verdict["next_action"], decision["next_action"])
        self.assertIs(False, decision["extraction_quality_result"])
        if record["status"] == "M4_04B4BR_PROVIDER_PROJECTION_READY":
            self.assertIs(True, live["stage1"]["minimal_native_schema_accepted"])
            self.assertIs(True, live["stage2"]["A_provider_request_accepted"])
            self.assertIs(True, live["stage2"]["B_response_received"])

    def test_boundaries_and_public_safety(self):
        boundaries = self.record["boundaries"]
        self.assertEqual(("NOT_ACCESSED", "SEALED", "SEALED", "UNCHANGED"),
                         (boundaries["DEV3_input"], boundaries["DEV3_gold"], boundaries["holdout"], boundaries["P3"]))
        self.assertNotRegex(self.text, r"AIza[0-9A-Za-z_\-]{10,}")
        self.assertNotIn("GEMINI_API_KEY", self.text)
        for content in (runner_v1.SMOKE_TEXT, "Tomas", "RefersTo", '"status"'):
            self.assertNotIn(content, self.text)

    def test_project_state_records_the_status_and_next_action(self):
        state = (protocol.REPO_ROOT / "docs/PROJECT_STATE.md").read_text(encoding="utf-8")
        self.assertIn(f"Status: {self.record['status']}", state)
        self.assertIn(self.record["decision"]["next_action"], state)


if __name__ == "__main__":
    unittest.main()
