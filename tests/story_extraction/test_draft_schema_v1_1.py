"""Offline contract tests for STORY_EXTRACTION_DRAFT_V1_1."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


REPO = Path(__file__).resolve().parents[2]
V1 = REPO / "schemas/story_extraction/story_extraction_draft_v1.schema.json"
V1_1 = REPO / "schemas/story_extraction/story_extraction_draft_v1_1.schema.json"


def validator():
    v1 = json.loads(V1.read_text(encoding="utf-8"))
    schema = json.loads(V1_1.read_text(encoding="utf-8"))
    registry = Registry().with_resource(v1["$id"], Resource.from_contents(v1))
    return Draft202012Validator(schema, registry=registry)


def draft():
    return {
        "draft_version": "STORY_EXTRACTION_DRAFT_V1_1",
        "evidence": [],
        "mentions": [
            {
                "handle": "M1",
                "passage_handle": "P1",
                "quote": "synthetic mention",
                "occurrence": 1,
                "role": "DEPICTION",
                "surface_form": "synthetic",
            }
        ],
        "entities": [],
        "events": [],
        "anchors": [],
        "propositions": [],
        "assertions": [],
    }


class DraftSchemaV11Tests(unittest.TestCase):
    def assert_valid(self, value):
        self.assertEqual(list(validator().iter_errors(value)), [])

    def test_exact_contract_is_valid(self):
        self.assert_valid(draft())

    def test_occurrence_and_surface_form_are_optional(self):
        value = draft()
        value["mentions"][0].pop("occurrence")
        value["mentions"][0].pop("surface_form")
        self.assert_valid(value)

    def test_model_facing_evidence_handle_is_forbidden(self):
        value = draft()
        value["mentions"][0]["evidence_handle"] = "EV1"
        self.assertTrue(list(validator().iter_errors(value)))

    def test_machine_owned_fields_are_forbidden(self):
        for field, field_value in (
            ("char_start", 0),
            ("source_sha256", "0" * 64),
            ("canonical_id", "M_CANONICAL"),
            ("review", {"state": "UNREVIEWED"}),
        ):
            with self.subTest(field=field):
                value = draft()
                value["mentions"][0][field] = field_value
                self.assertTrue(list(validator().iter_errors(value)))

    def test_required_locator_and_role_fail_closed(self):
        for field in ("handle", "passage_handle", "quote", "role"):
            with self.subTest(field=field):
                value = draft()
                value["mentions"][0].pop(field)
                self.assertTrue(list(validator().iter_errors(value)))

    def test_only_declared_mention_fields_exist(self):
        schema = json.loads(V1_1.read_text(encoding="utf-8"))
        self.assertEqual(
            set(schema["$defs"]["Mention"]["properties"]),
            {"handle", "passage_handle", "quote", "occurrence", "role", "surface_form"},
        )

    def test_old_v1_schema_is_frozen(self):
        self.assertEqual(
            hashlib.sha256(V1.read_bytes()).hexdigest(),
            "498edf8dba8d45b80380a180d1383787f5c0e4ecea5060254883cc27c7d83e80",
        )

    def test_v1_tag_is_rejected(self):
        value = deepcopy(draft())
        value["draft_version"] = "STORY_EXTRACTION_DRAFT_V1"
        self.assertTrue(list(validator().iter_errors(value)))


if __name__ == "__main__":
    unittest.main()
