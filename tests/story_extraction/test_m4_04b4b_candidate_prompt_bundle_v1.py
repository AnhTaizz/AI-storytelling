"""Offline tests for the P3 Draft V1.1 prompt, schema bundle and candidate identity."""
from copy import deepcopy
import hashlib
from pathlib import Path
import re
import sys
import unittest

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture_builder as fx  # noqa: E402
from p3_v1_1_offline_support import oracle_case  # noqa: E402

from tools.story_extraction.draft_compiler_v1_1 import (  # noqa: E402
    DraftCompilationErrorV1_1,
    validate_draft_v1_1,
)
from tools.story_extraction.draft_v1_1_schema_bundle_v1 import (  # noqa: E402
    V1_ID,
    bundle_text,
    bundle_validator,
    build_bundle,
)
from tools.story_extraction.m4_draft_v1_1_candidate_p3_v1 import (  # noqa: E402
    BOUND_FILES,
    CandidateError,
    build_primary_spec,
    build_repair_spec,
    candidate_definition,
    candidate_definition_sha256,
    file_hash_record,
    prompt_hashes,
    prompt_material,
)

PROMPTS = REPO / "tools/story_extraction/prompts"
P3_FILES = (
    "story_extraction_draft_p3_system_v1_1.txt",
    "story_extraction_draft_p3_user_v1_1.txt",
    "story_extraction_draft_p3_repair_user_v1_1.txt",
)
MANIFEST = REPO / "benchmarks/m4_extraction/M4_04B4B_DRAFT_V1_1_CANDIDATE_MANIFEST.yaml"
AUTHORITATIVE_V1_1_SCHEMA_SHA256_LF = (
    "6b5267319e2b6be42734254ad8efdb8fe6ab6843c5ba945ae4e8b524f11f78c0"
)


def authoritative_accepts(draft) -> bool:
    try:
        validate_draft_v1_1(draft)
    except DraftCompilationErrorV1_1:
        return False
    return True


def draft_corpus():
    """Synthetic oracle drafts plus deliberate interface violations."""
    corpus = []
    for name in fx.CASES:
        _, draft = oracle_case(name)
        corpus.append(draft)
    _, base = oracle_case("c02_two_mentions_one_entity")
    mutations = []
    for mutate in (
        lambda d: d["mentions"][0].__setitem__("evidence_handle", "EV1"),
        lambda d: d.__setitem__("draft_version", "STORY_EXTRACTION_DRAFT_V1"),
        lambda d: d.pop("anchors"),
        lambda d: d.__setitem__("source_sha256", "0" * 64),
        lambda d: d["mentions"][0].__setitem__("handle", "MENTION_1"),
        lambda d: d["mentions"][0].__setitem__("occurrence", 0),
        lambda d: d["mentions"][0].__setitem__("role", "QUOTATION"),
        lambda d: d["mentions"][0].__setitem__("surface_form", ""),
        lambda d: d["evidence"][0].__setitem__("char_start", 3),
        lambda d: d["assertions"][0].__setitem__("polarity", "MAYBE"),
        lambda d: d["assertions"][0].__setitem__("epistemic_status", "LIKELY"),
        lambda d: d["entities"].append({"handle": "E_NEW_9", "kind": "PERSON"}),
    ):
        draft = deepcopy(base)
        mutate(draft)
        mutations.append(draft)
    return corpus, mutations


class PromptArtifactTests(unittest.TestCase):
    def test_p3_prompts_target_v1_1_only(self):
        for name in P3_FILES:
            with self.subTest(name=name):
                text = (PROMPTS / name).read_text(encoding="utf-8")
                self.assertIn("STORY_EXTRACTION_DRAFT_V1_1", text)
                self.assertIsNone(re.search(r"STORY_EXTRACTION_DRAFT_V1(?!_1)", text))
                self.assertNotIn("evidence_handle", text)
                self.assertNotIn("DEV2", text)
                self.assertNotIn("holdout", text.lower())

    def test_system_prompt_states_ownership_quotes_and_uncertainty(self):
        text = (PROMPTS / P3_FILES[0]).read_text(encoding="utf-8")
        for required in (
            "WHO OWNS WHAT", "overlapping matches count separately", "Never guess it",
            "A missing mention is safer than a mislocated one", "NO FABRICATION",
            "UNCERTAINTY", "SUGGESTED", "placeholder", "textual_ambiguity",
            "byte-for-byte substring",
        ):
            self.assertIn(required, text)

    def test_templates_have_exact_markers(self):
        material = prompt_material()
        self.assertEqual(
            set(re.findall(r"\{[A-Z_]+\}", material["primary_user_template"])),
            {"{CASE_ID}", "{PREPARED_INPUT_JSON}"},
        )
        self.assertEqual(
            set(re.findall(r"\{[A-Z_]+\}", material["repair_user_template"])),
            {"{CASE_ID}", "{PREPARED_INPUT_JSON}", "{PRIMARY_RESPONSE}", "{FAILURE_JSON}"},
        )

    def test_materialized_system_embeds_bundle_and_registry_without_external_refs(self):
        system = prompt_material()["primary_system"]
        self.assertIn(bundle_text(), system)
        self.assertIn("registry_version: predicate_registry/v0.1", system)
        self.assertNotIn(V1_ID + "#", system)
        # EvidenceSet.evidence_handles is a current field; only the singular is obsolete.
        self.assertIsNone(re.search(r"evidence_handle(?!s)",
                                    system.split("EXACT PREDICATE REGISTRY")[0]))
        self.assertIsNone(re.search(r"STORY_EXTRACTION_DRAFT_V1(?!_1)",
                                    system.split("EXACT PREDICATE REGISTRY")[0]))

    def test_prompt_hashes_are_stable(self):
        self.assertEqual(prompt_hashes(), prompt_hashes())


class SchemaBundleTests(unittest.TestCase):
    def test_authoritative_schema_is_unchanged(self):
        record = file_hash_record(
            REPO / "schemas/story_extraction/story_extraction_draft_v1_1.schema.json")
        self.assertEqual(record["content_sha256_lf"], AUTHORITATIVE_V1_1_SCHEMA_SHA256_LF)

    def test_bundle_is_self_contained(self):
        bundle = build_bundle()
        refs = set(re.findall(r'"\$ref": "([^"]+)"', bundle_text()))
        self.assertTrue(refs)
        self.assertTrue(all(ref.startswith("#/$defs/") for ref in refs))
        self.assertEqual({ref[len("#/$defs/"):] for ref in refs}, set(bundle["$defs"]))
        self.assertNotIn("evidence_handle", bundle["$defs"]["Mention"]["properties"])
        self.assertFalse(bundle["$defs"]["Mention"]["additionalProperties"])

    def test_bundle_verdicts_equal_authoritative_verdicts(self):
        corpus, mutations = draft_corpus()
        validator = bundle_validator()
        for index, draft in enumerate(corpus + mutations):
            with self.subTest(index=index):
                self.assertEqual(validator.is_valid(draft), authoritative_accepts(draft))
        self.assertTrue(all(authoritative_accepts(item) for item in corpus))
        self.assertFalse(any(authoritative_accepts(item) for item in mutations))


class RequestConstructionTests(unittest.TestCase):
    def setUp(self):
        self.case, self.draft = oracle_case("c02_two_mentions_one_entity")

    def test_primary_spec_binds_candidate_settings(self):
        spec = build_primary_spec(self.case.case_id, self.case.prepared_input, "TEST-TASK")
        self.assertEqual(spec.model, "gemini-3.5-flash-lite")
        self.assertEqual(spec.credential_slot, "gemini_slot_3")
        self.assertEqual(dict(spec.generation_config),
                         {"temperature": 0, "max_output_tokens": 16384})
        self.assertEqual(spec.job_id, "P3V11_SYN_01_PRIMARY")
        self.assertIn('"draft_version": "STORY_EXTRACTION_DRAFT_V1_1"', spec.user_prompt)

    def test_case_id_and_prepared_input_are_checked(self):
        with self.assertRaises(CandidateError):
            build_primary_spec("syn-01", self.case.prepared_input, "TEST-TASK")
        wrong = dict(self.case.prepared_input, draft_version="STORY_EXTRACTION_DRAFT_V1")
        with self.assertRaises(CandidateError):
            build_primary_spec("SYN_01", wrong, "TEST-TASK")

    def test_repair_substitution_is_single_pass(self):
        hostile = '{"note": "{FAILURE_JSON} {PREPARED_INPUT_JSON}"}'
        spec = build_repair_spec("SYN_01", self.case.prepared_input, hostile,
                                 {"category": "JSON_PARSE_FAILURE", "blockers": []}, "TEST-TASK")
        self.assertIn(hostile, spec.user_prompt)
        self.assertEqual(spec.user_prompt.count('"category": "JSON_PARSE_FAILURE"'), 1)

    def test_repair_rejects_quality_or_gold_signals_and_ineligible_categories(self):
        for failure in (
            {"category": "DRAFT_COMPILER_FAILURE", "blockers": [{"gold": "x"}]},
            {"category": "DRAFT_COMPILER_FAILURE", "score": 1},
            {"category": "TRANSPORT_FAILURE"},
            {"category": "COMPILER_INTERNAL_EXCEPTION"},
        ):
            with self.subTest(failure=failure), self.assertRaises(CandidateError):
                build_repair_spec("SYN_01", self.case.prepared_input, "{}", failure, "TEST-TASK")


class CandidateManifestTests(unittest.TestCase):
    def test_definition_is_deterministic_and_checkout_independent(self):
        first = candidate_definition()
        self.assertEqual(first, candidate_definition())
        for record in first["files"].values():
            self.assertEqual(set(record), {"path", "content_sha256_lf", "git_blob_sha1_lf"})

    def test_every_bound_file_exists(self):
        for _, relative in BOUND_FILES:
            self.assertTrue((REPO / relative).is_file(), relative)

    def test_git_blob_ids_match_git_for_lf_content(self):
        record = file_hash_record(REPO / "tools/story_extraction/draft_compiler_v1_1.py")
        data = (REPO / "tools/story_extraction/draft_compiler_v1_1.py").read_bytes()
        data = data.replace(b"\r\n", b"\n")
        self.assertEqual(record["git_blob_sha1_lf"],
                         hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest())

    def test_committed_manifest_matches_current_candidate(self):
        manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["candidate_definition_sha256"], candidate_definition_sha256())
        self.assertEqual(manifest["prompt_hashes"], prompt_hashes())
        current = candidate_definition()["files"]
        for name, record in manifest["files"].items():
            with self.subTest(name=name):
                self.assertEqual(record["content_sha256_lf"], current[name]["content_sha256_lf"])
                self.assertEqual(record["git_blob_sha1_lf"], current[name]["git_blob_sha1_lf"])


if __name__ == "__main__":
    unittest.main()
