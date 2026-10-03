from dataclasses import replace
import inspect
import json
from pathlib import Path
import tempfile
import unittest

from tests.story_extraction import fixture_builder as fx
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_coverage_v1 import canonical_gold_to_draft_v1
from tools.story_extraction.run_m4_04b3c_dev2_predictions_v1 import (
    CaseInput,
    Dev2PredictionError,
    LOCKED_PROTOCOL_SHA256,
    _compile_raw_response,
    _member_path,
    execute,
    preflight,
)


def synthetic_case():
    ingestion, base, gold = fx.build("c06_participant")
    scope = gold["scope"]
    context = DraftCompilerContext(
        base,
        scope["passage_inputs"],
        scope["as_of_position"],
        scope["profile_id"],
        "M4_04B3C_P2",
        "v1",
        "P2_DEV2_01",
        ingestion,
    )
    draft, _ = canonical_gold_to_draft_v1(gold, context)
    return CaseInput("DEV2_01", {}, context), draft


class M404B3CDev2PredictionRunnerTests(unittest.TestCase):
    def test_protocol_hash_is_the_locked_b3b2_value(self):
        self.assertEqual(
            "9dea83083e082e80eb350b71cad9a552f620b67f2235056d89788c9b0a23a3a4",
            LOCKED_PROTOCOL_SHA256,
        )

    def test_runner_has_no_gold_or_evaluator_parameter(self):
        for function in (preflight, execute):
            parameters = set(inspect.signature(function).parameters)
            self.assertFalse(any("gold" in name.lower() for name in parameters))
            self.assertFalse(any("evaluat" in name.lower() for name in parameters))

    def test_member_guard_rejects_gold_and_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(Dev2PredictionError):
                _member_path(root, "../escape.json")
            with self.assertRaises(Dev2PredictionError):
                _member_path(root, "cases/dev2_gold.json")

    def test_valid_draft_compiles_source_exact(self):
        case, draft = synthetic_case()
        parsed, batch, validation = _compile_raw_response(
            json.dumps(draft, ensure_ascii=False), case
        )
        self.assertEqual(draft, parsed)
        self.assertIsNotNone(batch)
        self.assertTrue(validation["pass"])

    def test_json_failure_is_repair_eligible_category(self):
        case, _ = synthetic_case()
        draft, batch, validation = _compile_raw_response("{", case)
        self.assertIsNone(draft)
        self.assertIsNone(batch)
        self.assertEqual("JSON_PARSE_FAILURE", validation["category"])

    def test_schema_failure_is_repair_eligible_category(self):
        case, draft = synthetic_case()
        draft["unexpected_hash"] = "0" * 64
        parsed, batch, validation = _compile_raw_response(json.dumps(draft), case)
        self.assertIsNotNone(parsed)
        self.assertIsNone(batch)
        self.assertEqual("DRAFT_SCHEMA_FAILURE", validation["category"])

    def test_compiler_failure_is_repair_eligible_and_private_safe(self):
        case, draft = synthetic_case()
        private_quote = "PRIVATE_TEST_QUOTE"
        draft["evidence"][0]["quote"] = private_quote
        parsed, batch, validation = _compile_raw_response(json.dumps(draft), case)
        self.assertIsNotNone(parsed)
        self.assertIsNone(batch)
        self.assertEqual("DRAFT_COMPILER_FAILURE", validation["category"])
        self.assertEqual("QUOTE_NOT_FOUND", validation["code"])
        self.assertNotIn(private_quote, json.dumps(validation))

    def test_context_only_compiler_failure_remains_structural(self):
        case, draft = synthetic_case()
        inputs = [dict(item) for item in case.compiler_context.passage_inputs]
        inputs[0]["use"] = "CONTEXT_ONLY"
        guarded = replace(
            case,
            compiler_context=replace(case.compiler_context, passage_inputs=inputs),
        )
        _, batch, validation = _compile_raw_response(json.dumps(draft), guarded)
        self.assertIsNone(batch)
        self.assertEqual("DRAFT_COMPILER_FAILURE", validation["category"])
        self.assertEqual("CONTEXT_ONLY_EVIDENCE", validation["code"])


if __name__ == "__main__":
    unittest.main()
