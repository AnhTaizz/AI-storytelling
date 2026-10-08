"""Offline tests for the P4.1 diagnostic identity correction (M4-04B4D-F1).

Diagnostic V3.1 and candidate V1.1 against the verified-record-identity contract, and the
reproduction of the M4-04B4D mismatch in the unchanged, superseded diagnostic V3.

Every fixture is synthetic. No DEV3 data, private prediction, credential, provider or
gold is touched.
"""
import ast
import contextlib
import copy
import dataclasses
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import yaml

from tests.story_extraction import fixture_builder as fx
from tests.story_extraction import test_m4_04b4d_p4_1_compiler_aware_contract_v1 as b4d
from tools.story_extraction import draft_compiler_v1_1 as compiler_v1_1
from tools.story_extraction import m4_04b4a_p4_output_contract_v1 as p4_contract
from tools.story_extraction import m4_04b4br_p4_protocol_v2 as protocol_v2
from tools.story_extraction import m4_04b4d_f1_p4_1_compiler_aware_contract_v1_1 as contract
from tools.story_extraction import m4_04b4d_f1_structural_diagnostic_v3_1 as v31
from tools.story_extraction import m4_04b4d_p4_1_compiler_aware_contract_v1 as contract_v1
from tools.story_extraction import m4_04b4d_structural_diagnostic_v3 as v3
from tools.story_extraction import materialize_draft_v1_1_model_schema_v1 as materializer
from tools.story_extraction.draft_compiler_v1_1 import StructuralBlocker, prepare_story_extraction_draft_v1_1


REPO_ROOT = contract.REPO_ROOT
ADVERSARIAL = b4d.ADVERSARIAL
# The M4-04B4D files as committed at e0a048f. They are history and must not change.
SUPERSEDED_FILES = {
    "benchmarks/m4_extraction/M4_04B4D_P4_1_COMPILER_AWARE_REDESIGN.yaml":
        "a5322846f5e539f0d6a8b9facd8aaf72fd420089ff8fa118dc8f159e1013b79f",
    "docs/research/m4/M4_P4_1_COMPILER_AWARE_INTERFACE_DESIGN_V1.md":
        "7a7f23346e39c5c9da9bd95344d9b7aa856635d9a2a7f1a56c7b59b8010fbeaf",
    "tools/story_extraction/m4_04b4d_p4_1_compiler_aware_contract_v1.py":
        "daefe500545bdd03c7a07ffe364495304c4c85980ba583336b7d8dc9197e093b",
    "tools/story_extraction/m4_04b4d_structural_diagnostic_v3.py":
        "962ad21da3448d73efc6fabcbe443a41b838a0cf180ec6047a4b5f58320e4adc",
    "tools/story_extraction/prompts/story_extraction_draft_p4_1_v1_system.txt":
        "598aae325585dddae4588ca6f23551fe53ca91043bc9722e7fdafbc6afbbfea8",
    "tools/story_extraction/prompts/story_extraction_draft_p4_1_v1_user.txt":
        "4a642008e3b4be809ab71cf9a107a35260950066bb48ee90ca9e2d64ed76c01a",
    "tools/story_extraction/prompts/story_extraction_draft_p4_1_v1_repair_user.txt":
        "ba1d2035852a0fca8f4d889ca8f26cadb2410373fbe6e5208b40d800a9e30ab6",
}
SUPERSEDED_PRIMARY_PROMPTS = {
    "primary_system_sha256": "92869de37874635a7511af7220cb015a944753316d7047e4678e3f5f80a07ccf",
    "primary_user_template_sha256": "4a642008e3b4be809ab71cf9a107a35260950066bb48ee90ca9e2d64ed76c01a",
    "primary_prompt_pair_sha256": "b93e752db7f020398b946b3bb5c5abecee70269444fc3618baf55fef389672e4",
}
PREVIOUS_ACCEPTED_TOTAL = 1323


def diagnose(draft, context):
    return v31.structural_diagnostic_v3_1(json.dumps(draft, ensure_ascii=False), context)


def diagnose_v3(draft, context):
    return v3.structural_diagnostic_v3(json.dumps(draft, ensure_ascii=False), context)


def codes(diagnostic):
    return [finding["code"] for finding in diagnostic["findings"]]


def triple(finding):
    return (finding["record_collection"], finding["record_locator"], finding["record_index"], finding["record_handle"])


def blocked(*blockers):
    """The compiler reporting exactly these blockers. Test only: V3.1 itself never patches the compiler."""
    return mock.patch.object(compiler_v1_1, "compile_story_extraction_draft_v1_1",
                             side_effect=compiler_v1_1.DraftCompilationErrorV1_1(list(blockers)))


def shared_mention_handle():
    context, draft = b4d.fixture("c02_two_mentions_one_entity")
    draft["mentions"][1]["handle"] = draft["mentions"][0]["handle"]
    return context, draft


def three_problem_draft():
    """Two ambiguous quotes, a disallowed entity kind on two propositions and a duplicate proposition."""
    context, draft = b4d.fixture("c07_location")
    return context, b4d.duplicated(b4d.disallowed_kind(b4d.ambiguous(draft)))


def existing_reference_drafts():
    """Two drafts over existing context: a duplicate of an existing proposition, and a wrong-kind reference."""
    context, existing = b4d.existing_context()
    located = next(handle for handle, record in existing.items() if record.get("predicate") == "OccursAt")
    character = next(handle for handle, record in existing.items()
                     if handle.startswith("E_") and record.get("kind") == "CHARACTER")
    duplicate = b4d.empty_draft()
    duplicate["propositions"].append({"handle": "PROP1", **copy.deepcopy(existing[located])})
    wrong = b4d.empty_draft()
    proposition = {"handle": "PROP1", **copy.deepcopy(existing[located])}
    proposition["args"]["location"]["handle"] = character
    wrong["propositions"].append(proposition)
    return context, duplicate, wrong, located, character


def handle_like_values(node):
    """Every string in a structure that has the shape of a record handle."""
    return sorted(value for value in b4d.strings_in(node) if v31.is_safe_handle(value))


# ---------------------------------------------------------------------------
# The M4-04B4D mismatch, reproduced on the unchanged V3
# ---------------------------------------------------------------------------

class HistoricalDiscrepancyTests(unittest.TestCase):
    def test_superseded_b4d_files_are_unchanged(self):
        for relative, expected in SUPERSEDED_FILES.items():
            with self.subTest(path=relative):
                self.assertEqual(expected, protocol_v2.normalized_file_sha256(REPO_ROOT / relative))
        self.assertEqual(contract.SUPERSEDED_CANDIDATE_SHA256, contract_v1.candidate_sha256())
        self.assertEqual({"candidate_id": contract_v1.CANDIDATE_ID, "candidate_sha256": contract_v1.CANDIDATE_SHA256,
                          "diagnostic": v3.DIAGNOSTIC_ID, "unchanged": True}, contract.superseded_candidate_intact())
        record = yaml.safe_load((REPO_ROOT / "benchmarks/m4_extraction/M4_04B4D_P4_1_COMPILER_AWARE_REDESIGN.yaml")
                                .read_text(encoding="utf-8"))
        self.assertEqual(("M4_04B4D_P4_1_OFFLINE_CONTRACT_READY", contract.SUPERSEDED_CANDIDATE_SHA256),
                         (record["status"], record["candidate"]["sha256"]))

    def test_v3_locator_is_unique_but_its_duplicate_handle_branch_names_the_handle(self):
        """Review findings A, B and D: the locator refuses, the finding names the handle anyway."""
        context, draft = shared_mention_handle()
        shared = draft["mentions"][0]["handle"]
        self.assertEqual({"record_collection": "mentions", "record_index": None, "record_handle": None},
                         v3.locate_record(draft, "mentions", shared))
        finding = next(finding for finding in diagnose_v3(draft, context)["findings"]
                       if finding["code"] == "DUPLICATE_HANDLE")
        self.assertEqual(("mentions", None, shared), (finding["record_collection"], finding["record_index"],
                                                      finding["record_handle"]))
        self.assertTrue(diagnose_v3(draft, context)["complete"])

    def test_v3_assertion_accepts_grammar_valid_handles_it_never_verified(self):
        """Review finding C: any handle with the right characters passed the V3 safety assertion."""
        context, draft = three_problem_draft()
        diagnostic = diagnose_v3(draft, context)
        handles = {finding["record_handle"] for finding in diagnostic["findings"]}
        for invented in ("M99", "PROP5", "E_EXISTING_99"):
            mutated = copy.deepcopy(diagnostic)
            mutated["findings"][0]["record_handle"] = invented
            self.assertNotIn(invented, {record["handle"] for record in draft["mentions"]})
            v3.assert_diagnostic_safe(mutated, handles, context)

    def test_no_source_text_reached_a_v3_diagnostic_in_the_reproduction(self):
        context, draft = shared_mention_handle()
        diagnostic = diagnose_v3(draft, context)
        for mention in draft["mentions"]:
            self.assertNotIn(json.dumps(mention["quote"]), json.dumps(diagnostic))


# ---------------------------------------------------------------------------
# Verified record identity
# ---------------------------------------------------------------------------

class UniqueRecordIdentityTests(unittest.TestCase):
    def test_one_valid_unique_handle_is_a_verified_triple(self):
        context = b4d.text_context("Rin met Rin at noon.")
        draft = b4d.mention_draft("Rin")
        diagnostic = diagnose(draft, context)
        finding = diagnostic["findings"][0]
        self.assertEqual(("mentions", v31.LOCATOR_VERIFIED, 0, "M1"), triple(finding))
        self.assertEqual("mentions/0", finding["schema_path"])
        self.assertEqual(finding["record_handle"], draft[finding["record_collection"]][finding["record_index"]]["handle"])
        identity = v31.build_identity_index(draft, context)
        self.assertEqual((0, 1, 1), (identity.unique_index("mentions", "M1"), identity.count("mentions", "M1"),
                                     identity.size("mentions")))
        self.assertTrue(diagnostic["completeness"]["observed_blockers_located"])
        self.assertNotIn(v31.LIMIT_LOCATOR, diagnostic["limitations"])

    def test_a_duplicated_handle_is_never_shown_as_a_locator(self):
        context, draft = shared_mention_handle()
        shared = draft["mentions"][0]["handle"]
        diagnostic = diagnose(draft, context)
        finding = next(finding for finding in diagnostic["findings"] if finding["code"] == "DUPLICATE_HANDLE")
        self.assertEqual(("mentions", v31.LOCATOR_UNAVAILABLE, None, None), triple(finding))
        self.assertEqual({"records_sharing_this_handle": 2}, finding["structural_detail"])
        self.assertEqual("mentions/<UNVERIFIED>", finding["schema_path"])
        self.assertNotIn(shared, handle_like_values(diagnostic))
        self.assertIn(v31.LIMIT_LOCATOR, diagnostic["limitations"])
        self.assertEqual((False, False), (diagnostic["completeness"]["observed_blockers_located"], diagnostic["complete"]))
        with self.assertRaises(compiler_v1_1.DraftCompilationErrorV1_1) as raised:
            compiler_v1_1.compile_story_extraction_draft_v1_1(draft, context)
        self.assertEqual(len(raised.exception.blockers), diagnostic["compiler_verdict"]["compiler_blockers"])
        self.assertIn("DUPLICATE_HANDLE", diagnostic["compiler_verdict"]["blocker_codes"])
        self.assertTrue(diagnostic["completeness"]["observed_blockers_preserved"])
        identity = v31.build_identity_index(draft, context)
        self.assertEqual((None, 2), (identity.unique_index("mentions", shared), identity.count("mentions", shared)))
        self.assertEqual(("mentions", v31.LOCATOR_UNAVAILABLE, None, None),
                         triple(v31.locate_record(identity, "mentions", shared)))

    def test_several_duplicated_handles_stay_separate_findings_with_their_counts(self):
        context = b4d.text_context("The lamp is on the desk by the door near the wall.")
        draft = b4d.empty_draft()
        for handle, quote in (("M1", "lamp"), ("M1", "desk"), ("M1", "door"), ("M2", "wall"), ("M2", "near"),
                              ("M3", "The")):
            draft["mentions"].append({"handle": handle, "passage_handle": "P1", "quote": quote, "role": "DEPICTION"})
        diagnostic = diagnose(draft, context)
        duplicates = [finding for finding in diagnostic["findings"] if finding["code"] == "DUPLICATE_HANDLE"]
        with self.assertRaises(compiler_v1_1.DraftCompilationErrorV1_1) as raised:
            compiler_v1_1.compile_story_extraction_draft_v1_1(draft, context)
        from_compiler = [blocker for blocker in raised.exception.blockers if blocker.code == "DUPLICATE_HANDLE"]
        self.assertEqual(len(from_compiler), len(duplicates))
        self.assertEqual([2, 3], sorted(finding["structural_detail"]["records_sharing_this_handle"]
                                        for finding in duplicates))
        for finding in duplicates:
            self.assertEqual(("mentions", v31.LOCATOR_UNAVAILABLE, None, None), triple(finding))
        self.assertEqual([], [value for value in handle_like_values(diagnostic) if value in ("M1", "M2")])

    def test_a_quote_blocker_on_a_duplicated_handle_is_not_located(self):
        context = b4d.text_context("Rin met Rin at noon.")
        draft = b4d.mention_draft("Rin")
        draft["mentions"].append(copy.deepcopy(draft["mentions"][0]))
        diagnostic = diagnose(draft, context)
        self.assertEqual(["AMBIGUOUS_QUOTE", "DUPLICATE_HANDLE"], codes(diagnostic))
        for finding in diagnostic["findings"]:
            self.assertEqual(("mentions", v31.LOCATOR_UNAVAILABLE, None, None), triple(finding))
        self.assertEqual({}, diagnostic["findings"][0]["structural_detail"])
        self.assertEqual([], handle_like_values(diagnostic["findings"]))

    def test_the_same_looking_handle_in_another_collection_is_not_that_record(self):
        context, draft = b4d.fixture("c02_two_mentions_one_entity")
        mention = draft["mentions"][0]["handle"]
        draft["entities"][0]["handle"] = mention
        identity = v31.build_identity_index(draft, context)
        self.assertEqual(0, identity.unique_index("mentions", mention))
        self.assertEqual((None, 0), (identity.unique_index("entities", mention), identity.count("entities", mention)))
        self.assertEqual(("entities", v31.LOCATOR_UNAVAILABLE, None, None),
                         triple(v31.locate_record(identity, "entities", mention)))
        self.assertIsNone(identity.records["entities"][0])
        diagnostic = diagnose(draft, context)
        self.assertEqual("DRAFT_SCHEMA_FAILURE", diagnostic["category"])
        entity = [finding for finding in diagnostic["findings"] if finding["record_collection"] == "entities"]
        self.assertTrue(entity)
        for finding in entity:
            self.assertEqual(("entities", v31.LOCATOR_SCHEMA_PATH, None, None), triple(finding))
            self.assertTrue(finding["schema_path"].startswith("entities/0"))
        self.assertFalse(v31.is_safe_handle("EVT1", "evidence"))
        self.assertFalse(v31.is_safe_handle("EV1", "events"))

    def test_a_grammar_valid_handle_that_is_absent_is_not_located(self):
        context = b4d.text_context("Rin met Rin at noon.")
        draft = b4d.mention_draft("Rin")
        identity = v31.build_identity_index(draft, context)
        for collection, handle in (("mentions", "M9"), ("mentions", "PROP1"), ("propositions", "PROP1"),
                                   ("mentions", None), ("mentions", 1), ("no_such_collection", "M1"),
                                   (ADVERSARIAL[1], "M1"), (None, "M1")):
            located = v31.locate_record(identity, collection, handle)
            self.assertEqual((v31.LOCATOR_UNAVAILABLE, None, None),
                             (located["record_locator"], located["record_index"], located["record_handle"]))
        with blocked(StructuralBlocker("QUOTE", "AMBIGUOUS_QUOTE", "mentions/M9"),
                     StructuralBlocker("HANDLE", "UNKNOWN_HANDLE", "assertions/A7/proposition_handle"),
                     StructuralBlocker("HANDLE", "DUPLICATE_HANDLE", "M9")):
            diagnostic = v31.structural_diagnostic_v3_1(json.dumps(draft), context)
        self.assertEqual(3, diagnostic["finding_count"])
        for finding in diagnostic["findings"]:
            self.assertEqual((v31.LOCATOR_UNAVAILABLE, None, None), triple(finding)[1:])
        self.assertEqual([], handle_like_values(diagnostic))
        self.assertFalse(diagnostic["completeness"]["observed_blockers_located"])

    def test_the_locator_never_guesses_from_position_or_order(self):
        context, draft = shared_mention_handle()
        identity = v31.build_identity_index(draft, context)
        first, last = copy.deepcopy(draft), copy.deepcopy(draft)
        first["mentions"].reverse()
        self.assertEqual(triple(v31.locate_record(identity, "mentions", draft["mentions"][0]["handle"])),
                         triple(v31.locate_record(v31.build_identity_index(first, context), "mentions",
                                                  last["mentions"][0]["handle"])))
        source = Path(v31.__file__).read_text(encoding="utf-8")
        self.assertNotIn("indices[0]", source)
        self.assertEqual(1, source.count(".index(handle)"))

    def test_identity_index_is_built_only_from_the_draft_and_the_host_context(self):
        context, existing = b4d.existing_context()
        draft = b4d.empty_draft()
        identity = v31.build_identity_index(draft, context)
        self.assertEqual(set(v31.COLLECTION_DEFINITIONS), set(identity.records))
        self.assertEqual(set(existing), set(identity.existing))
        for handle, collection in identity.existing.items():
            self.assertIn(collection, v31.COLLECTION_DEFINITIONS)
            self.assertTrue(identity.is_existing(handle, collection))
            self.assertFalse(identity.is_existing(handle, "mentions" if collection != "mentions" else "entities"))
        self.assertEqual({f"P{index}" for index in range(1, len(context.passage_inputs) + 1)}, set(identity.passages))
        for weird in (None, [], "text", {"mentions": "M1"}, {"mentions": [None, 3, {"handle": ADVERSARIAL[0]}]}):
            other = v31.build_identity_index(weird, context)
            self.assertTrue(all(entry is None for entries in other.records.values() for entry in entries))
        empty = v31.build_identity_index(draft, None)
        self.assertEqual(({}, frozenset()), (dict(empty.existing), empty.passages))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            identity.passages = frozenset({"P9"})


class ReferencedHandleTests(unittest.TestCase):
    def test_a_new_record_reference_is_shown_only_when_it_is_a_unique_record_of_the_right_type(self):
        context, draft = b4d.fixture("c07_location")
        diagnostic = diagnose(b4d.disallowed_kind(draft), context)
        finding = next(finding for finding in diagnostic["findings"]
                       if finding["code"] == "ARGUMENT_ENTITY_KIND_NOT_ALLOWED")
        detail = finding["structural_detail"]
        identity = v31.build_identity_index(draft, context)
        self.assertIs(False, detail["referenced_record_is_existing"])
        index = identity.unique_index("entities", detail["referenced_record_handle"])
        self.assertEqual(detail["referenced_entity_kind"], draft["entities"][index]["kind"])
        duplicate = diagnose(b4d.duplicated(b4d.fixture("c08_possession")[1]), b4d.fixture("c08_possession")[0])
        other = next(finding for finding in duplicate["findings"]
                     if finding["code"] == "DUPLICATE_CONCRETE_PROPOSITION_CONTENT")
        self.assertIs(False, other["structural_detail"]["identical_to_existing_record"])
        self.assertNotEqual(other["record_handle"], other["structural_detail"]["identical_to_record_handle"])

    def test_a_valid_existing_context_handle_is_verified_against_the_host_context(self):
        context, duplicate, wrong, located, character = existing_reference_drafts()
        identity = v31.build_identity_index(wrong, context)
        self.assertTrue(identity.is_existing(character, "entities"))
        self.assertTrue(identity.is_existing(located, "propositions"))
        self.assertEqual(0, identity.count("entities", character))
        finding = diagnose(wrong, context)["findings"][0]
        self.assertEqual("ARGUMENT_ENTITY_KIND_NOT_ALLOWED", finding["code"])
        self.assertEqual((True, character, "CHARACTER"), tuple(
            finding["structural_detail"][key]
            for key in ("referenced_record_is_existing", "referenced_record_handle", "referenced_entity_kind")))
        finding = diagnose(duplicate, context)["findings"][0]
        self.assertEqual({"identical_to_existing_record": True, "identical_to_record_handle": located},
                         finding["structural_detail"])
        self.assertEqual(("propositions", v31.LOCATOR_VERIFIED, 0, "PROP1"), triple(finding))

    def test_an_invented_existing_context_handle_is_never_shown(self):
        context, _, wrong, _, _ = existing_reference_drafts()
        for invented in ("E_EXISTING_99", "PROP_EXISTING_1", "E_NEW_7"):
            draft = copy.deepcopy(wrong)
            draft["propositions"][0]["args"]["location"]["handle"] = invented
            diagnostic = diagnose(draft, context)
            self.assertEqual("DRAFT_COMPILER_FAILURE", diagnostic["category"])
            self.assertNotIn(invented, handle_like_values(diagnostic))
            self.assertNotIn("ARGUMENT_ENTITY_KIND_NOT_ALLOWED", codes(diagnostic))
            for finding in diagnostic["findings"]:
                self.assertNotIn("referenced_record_handle", finding["structural_detail"])

    def test_references_through_a_duplicated_handle_are_not_resolved(self):
        context, draft = b4d.fixture("c07_location")
        b4d.disallowed_kind(draft)
        draft["entities"][1]["handle"] = draft["entities"][0]["handle"]
        diagnostic = diagnose(draft, context)
        self.assertIn("DUPLICATE_HANDLE", codes(diagnostic))
        self.assertNotIn("ARGUMENT_ENTITY_KIND_NOT_ALLOWED", codes(diagnostic))
        self.assertNotIn(draft["entities"][0]["handle"], handle_like_values(diagnostic))
        self.assertFalse(diagnostic["completeness"]["canonical_validation_reached"])
        self.assertIn(v31.LIMIT_CANONICAL_NOT_ENUMERATED, diagnostic["limitations"])


# ---------------------------------------------------------------------------
# The safety assertion
# ---------------------------------------------------------------------------

class SafetyAssertionTests(unittest.TestCase):
    def assert_rejected(self, diagnostic, identity, tampering):
        v31.assert_diagnostic_safe(copy.deepcopy(diagnostic), identity)
        for label, change in tampering.items():
            mutated = copy.deepcopy(diagnostic)
            change(mutated)
            with self.subTest(tampering=label), self.assertRaises(v31.DiagnosticV31Error):
                v31.assert_diagnostic_safe(mutated, identity)

    def test_record_identity_relations_are_verified(self):
        context, draft = three_problem_draft()
        diagnostic = diagnose(draft, context)
        identity = v31.build_identity_index(draft, context)
        self.assertEqual(("mentions", v31.LOCATOR_VERIFIED, 0, "M1"), triple(diagnostic["findings"][0]))

        def first(name, value):
            return lambda d: d["findings"][0].__setitem__(name, value)

        self.assert_rejected(diagnostic, identity, {
            "invented_grammar_valid_handle": first("record_handle", "M99"),
            "handle_of_another_collection": first("record_handle", "PROP5"),
            "collection_changed": first("record_collection", "propositions"),
            "unknown_collection": first("record_collection", "sentences"),
            "right_handle_wrong_index": first("record_index", 1),
            "right_index_wrong_handle": first("record_handle", "M2"),
            "index_out_of_range": first("record_index", 99),
            "negative_index": first("record_index", -1),
            "boolean_index": first("record_index", False),
            "text_index": first("record_index", "0"),
            "handle_without_index": first("record_index", None),
            "index_without_handle": first("record_handle", None),
            "unavailable_but_still_named": first("record_locator", v31.LOCATOR_UNAVAILABLE),
            "not_scoped_but_still_named": first("record_locator", v31.LOCATOR_NOT_SCOPED),
            "unknown_locator_state": first("record_locator", "PROBABLY_THIS_ONE"),
            "path_names_another_record": first("schema_path", "mentions/1"),
            "path_names_another_collection": first("schema_path", "entities/0"),
            "arbitrary_handle_text": first("record_handle", ADVERSARIAL[0]),
            "handle_with_trailing_newline": first("record_handle", "M1\n"),
            "unhashable_collection": first("record_collection", ["mentions"]),
            "unhashable_handle": first("record_handle", ["M1"]),
        })

    def test_a_duplicated_handle_cannot_be_presented_as_a_unique_locator(self):
        context, draft = shared_mention_handle()
        shared = draft["mentions"][0]["handle"]
        diagnostic = diagnose(draft, context)
        identity = v31.build_identity_index(draft, context)
        position = next(index for index, finding in enumerate(diagnostic["findings"])
                        if finding["code"] == "DUPLICATE_HANDLE")

        def named(index):
            def change(d):
                d["findings"][position].update(record_locator=v31.LOCATOR_VERIFIED, record_index=index,
                                               record_handle=shared, schema_path=f"mentions/{index}")
                d["limitations"].remove(v31.LIMIT_LOCATOR)
                d["completeness"]["observed_blockers_located"] = True
            return change

        self.assert_rejected(diagnostic, identity, {
            "named_at_first_index": named(0),
            "named_at_second_index": named(1),
            "handle_only_as_in_v3": lambda d: d["findings"][position].__setitem__("record_handle", shared),
            "handle_in_detail": lambda d: d["findings"][position]["structural_detail"].__setitem__(
                "identical_to_record_handle", shared),
        })

    def test_referenced_handles_and_passages_are_verified_in_their_namespace(self):
        context, draft = three_problem_draft()
        diagnostic = diagnose(draft, context)
        identity = v31.build_identity_index(draft, context)
        kind = next(index for index, finding in enumerate(diagnostic["findings"])
                    if finding["code"] == "ARGUMENT_ENTITY_KIND_NOT_ALLOWED")
        same = next(index for index, finding in enumerate(diagnostic["findings"])
                    if finding["code"] == "DUPLICATE_CONCRETE_PROPOSITION_CONTENT")

        def detail(position, name, value):
            return lambda d: d["findings"][position]["structural_detail"].__setitem__(name, value)

        self.assert_rejected(diagnostic, identity, {
            "invented_entity_reference": detail(kind, "referenced_record_handle", "E_NEW_99"),
            "reference_of_the_wrong_type": detail(kind, "referenced_record_handle", "PROP5"),
            "new_record_claimed_as_existing": detail(kind, "referenced_record_is_existing", True),
            "invented_existing_reference": lambda d: d["findings"][kind]["structural_detail"].update(
                referenced_record_handle="E_EXISTING_99", referenced_record_is_existing=True),
            "reference_without_a_namespace": lambda d: d["findings"][kind]["structural_detail"].pop(
                "referenced_record_is_existing"),
            "namespace_not_a_boolean": detail(kind, "referenced_record_is_existing", "false"),
            "invented_identical_proposition": detail(same, "identical_to_record_handle", "PROP99"),
            "identical_record_of_the_wrong_type": detail(same, "identical_to_record_handle", "E_NEW_2"),
            "passage_not_supplied": detail(0, "passage_handle", "P999"),
            "passage_text_as_handle": detail(0, "passage_handle", ADVERSARIAL[0]),
            "handle_under_another_key": detail(0, "passage_use", "M1"),
            "handle_nested_in_a_list": detail(kind, "allowed_entity_kinds", [{"record_handle": "M1"}]),
            "reference_key_on_a_finding_that_has_none": detail(0, "referenced_record_handle", "E_NEW_2"),
        })

    def test_existing_context_references_are_verified_against_the_host_context(self):
        context, duplicate, wrong, located, character = existing_reference_drafts()
        for draft, key, good, flag in ((wrong, "referenced_record_handle", character, "referenced_record_is_existing"),
                                       (duplicate, "identical_to_record_handle", located, "identical_to_existing_record")):
            diagnostic = diagnose(draft, context)
            identity = v31.build_identity_index(draft, context)
            self.assertEqual(good, diagnostic["findings"][0]["structural_detail"][key])

            def detail(name, value):
                return lambda d: d["findings"][0]["structural_detail"].__setitem__(name, value)

            self.assert_rejected(diagnostic, identity, {
                "invented_existing_handle": detail(key, good.rsplit("_", 1)[0] + "_999"),
                "existing_handle_of_the_wrong_type": detail(key, located if good == character else character),
                "existing_record_claimed_as_new": detail(flag, False),
                "new_record_handle_claimed_as_existing": detail(key, "PROP1"),
            })
            # The same diagnostic is not valid for a context that does not hold that record.
            bare = v31.build_identity_index(draft, b4d.fixture("c07_location")[0])
            with self.assertRaises(v31.DiagnosticV31Error):
                v31.assert_diagnostic_safe(copy.deepcopy(diagnostic), bare)

    def test_arbitrary_strings_and_malicious_path_components_are_rejected(self):
        context, draft = three_problem_draft()
        diagnostic = diagnose(draft, context)
        identity = v31.build_identity_index(draft, context)
        tampering = {
            "unknown_detail_key": lambda d: d["findings"][0]["structural_detail"].__setitem__(ADVERSARIAL[1], 1),
            "story_text_in_detail": lambda d: d["findings"][0]["structural_detail"].__setitem__("passage_use", ADVERSARIAL[0]),
            "unknown_code": lambda d: d["findings"][0].__setitem__("code", "Some invented sentence."),
            "unknown_rule_class": lambda d: d["findings"][0].__setitem__("rule_class", ADVERSARIAL[1]),
            "unknown_phase": lambda d: d["findings"][0].__setitem__("phase", "STORY"),
            "unknown_source": lambda d: d["findings"][0].__setitem__("source", "THE_MODEL"),
            "extra_finding_field": lambda d: d["findings"][0].__setitem__("expected_answer", "CHARACTER"),
            "missing_finding_field": lambda d: d["findings"][0].pop("record_locator"),
            "float_value": lambda d: d["findings"][0]["structural_detail"].__setitem__("exact_match_count", 2.5),
            "finding_not_an_object": lambda d: d["findings"].__setitem__(0, "AMBIGUOUS_QUOTE"),
            "detail_not_an_object": lambda d: d["findings"][0].__setitem__("structural_detail", ["M1"]),
            "flag_not_a_boolean": lambda d: d["findings"][0].__setitem__("compiler_reached", "true"),
        }
        for label, part in (("traversal", "../../etc/passwd"), ("backslash", "..\\windows"), ("story_text", ADVERSARIAL[0]),
                            ("prototype", "__proto__"), ("handle", "M1"), ("oversized_number", "1234567"),
                            ("unicode_digit", chr(0x0663)), ("empty", ""), ("json", '{"handle":"M1"}'),
                            ("newline", "role\nM1"), ("non_schema_name", "password")):
            tampering["path_" + label] = (lambda d, part=part: d["findings"][0].__setitem__(
                "schema_path", "mentions/0/" + part))
        tampering["path_not_a_string"] = lambda d: d["findings"][0].__setitem__("schema_path", ["mentions", 0])
        self.assert_rejected(diagnostic, identity, tampering)

    def test_the_envelope_must_agree_with_its_findings(self):
        context, draft = shared_mention_handle()
        diagnostic = diagnose(draft, context)
        identity = v31.build_identity_index(draft, context)

        def flag(name, value):
            return lambda d: d["completeness"].__setitem__(name, value)

        self.assert_rejected(diagnostic, identity, {
            "complete_claimed": lambda d: d.__setitem__("complete", True),
            "located_claimed": flag("observed_blockers_located", True),
            "located_claimed_and_complete_adjusted": lambda d: (
                d["completeness"].__setitem__("observed_blockers_located", True),
                d.__setitem__("complete", all(d["completeness"].values()))),
            "preservation_denied": flag("observed_blockers_preserved", False),
            "locator_limitation_removed": lambda d: d["limitations"].remove(v31.LIMIT_LOCATOR),
            "enumeration_claimed": flag("downstream_canonical_issues_enumerated", True),
            "canonical_reached_claimed_without_the_limitation_removed": lambda d: (
                d["completeness"].__setitem__("canonical_validation_reached", False),
                d["limitations"].remove(v31.LIMIT_CANONICAL_NOT_REACHED)),
            "enumeration_limitation_removed": lambda d: d["limitations"].remove(v31.LIMIT_CANONICAL_NOT_ENUMERATED),
            "unknown_limitation": lambda d: d["limitations"].append("ZZ_NOTE"),
            "limitations_unsorted": lambda d: d["limitations"].reverse(),
            "limitation_repeated": lambda d: d["limitations"].insert(0, d["limitations"][0]),
            "completeness_statement_missing": lambda d: d["completeness"].pop("observed_blockers_preserved"),
            "completeness_statement_added": flag("everything_is_fine", True),
            "completeness_not_boolean": flag("observed_blockers_preserved", 1),
            "finding_dropped": lambda d: d["findings"].pop(),
            "finding_count_changed": lambda d: d.__setitem__("finding_count", d["finding_count"] + 1),
            "blocker_count_changed": lambda d: d["compiler_verdict"].__setitem__("compiler_blockers", 1),
            "compiled_claimed": lambda d: d["compiler_verdict"].__setitem__("compiled", True),
            "category_removed": lambda d: d.__setitem__("category", None),
            "category_invented": lambda d: d.__setitem__("category", "LOW_COVERAGE"),
            "verdict_field_added": lambda d: d["compiler_verdict"].__setitem__("note", "x"),
            "v3_identity": lambda d: d.__setitem__("diagnostic", v3.DIAGNOSTIC_ID),
            "v3_format": lambda d: d.__setitem__("format", v3.DIAGNOSTIC_FORMAT),
            "envelope_field_added": lambda d: d.__setitem__("note", "x"),
            "blocker_code_invented": lambda d: d["compiler_verdict"]["blocker_codes"].append(ADVERSARIAL[0]),
        })
        for not_an_index in ({"M1", "M2"}, None, {"records": {}}, v3):
            with self.assertRaises(v31.DiagnosticV31Error):
                v31.assert_diagnostic_safe(copy.deepcopy(diagnostic), not_an_index)
        for not_a_diagnostic in (None, [], "text", {}, diagnose_v3(draft, context)):
            with self.assertRaises(v31.DiagnosticV31Error):
                v31.assert_diagnostic_safe(not_a_diagnostic, identity)

    def test_a_diagnostic_is_only_valid_for_the_draft_it_was_built_from(self):
        context, draft = three_problem_draft()
        diagnostic = diagnose(draft, context)
        other = copy.deepcopy(draft)
        other["mentions"].reverse()
        with self.assertRaises(v31.DiagnosticV31Error):
            v31.assert_diagnostic_safe(copy.deepcopy(diagnostic), v31.build_identity_index(other, context))
        fewer = copy.deepcopy(draft)
        fewer["propositions"].pop()
        with self.assertRaises(v31.DiagnosticV31Error):
            v31.assert_diagnostic_safe(copy.deepcopy(diagnostic), v31.build_identity_index(fewer, context))
        with self.assertRaises(v31.DiagnosticV31Error):
            v31.assert_diagnostic_safe(copy.deepcopy(diagnostic), v31.build_identity_index(None, None))

    def test_the_only_error_v3_1_raises_is_its_safety_assertion(self):
        source = Path(v31.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        raising = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                   and any(isinstance(inner, ast.Raise) for inner in ast.walk(node))}
        self.assertEqual({"_fail", "assert_diagnostic_safe"}, raising)
        self.assertIn("assert_diagnostic_safe(diagnostic, identity)", source)


# ---------------------------------------------------------------------------
# Completeness, blocker counts and determinism
# ---------------------------------------------------------------------------

class CompletenessTests(unittest.TestCase):
    def flags(self, diagnostic):
        return tuple(diagnostic["completeness"][name] for name in v31.COMPLETENESS_FIELDS)

    def test_complete_is_the_conjunction_of_named_statements(self):
        for name in fx.CASES:
            context, draft = b4d.fixture(name)
            with self.subTest(fixture=name):
                diagnostic = diagnose(draft, context)
                self.assertEqual(((True,) * 7, True, [], None, 0),
                                 (self.flags(diagnostic), diagnostic["complete"], diagnostic["limitations"],
                                  diagnostic["category"], diagnostic["finding_count"]))
        self.assertEqual(v31.COMPLETENESS_FIELDS, tuple(diagnose(*reversed(b4d.fixture("c07_location")))["completeness"]))

    def test_a_rejected_draft_is_never_complete_and_says_why(self):
        context, draft = b4d.fixture("c07_location")
        cases = {
            # located, attributed, compiler rules checked, canonical reached
            "json": (v31.structural_diagnostic_v3_1('{"draft_version": ', context), (True, True, False, False)),
            "schema": (diagnose({key: value for key, value in draft.items() if key != "events"}, context),
                       (True, True, False, False)),
            "ambiguous_quote": (diagnose(b4d.ambiguous(copy.deepcopy(draft)), context), (True, True, True, False)),
            "canonical_known_rule": (diagnose(b4d.disallowed_kind(copy.deepcopy(draft)), context),
                                     (True, True, True, True)),
            "duplicate_handle": (diagnose(*reversed(shared_mention_handle())), (False, True, True, False)),
        }
        unknown = copy.deepcopy(b4d.fixture("c08_possession")[1])
        unknown["propositions"][-1]["args"].pop(sorted(unknown["propositions"][-1]["args"])[-1])
        cases["canonical_unknown_rule"] = (diagnose(unknown, b4d.fixture("c08_possession")[0]), (True, False, True, True))
        for label, (diagnostic, expected) in cases.items():
            with self.subTest(case=label):
                completeness = diagnostic["completeness"]
                self.assertEqual(expected, tuple(completeness[name] for name in (
                    "observed_blockers_located", "observed_blockers_attributed", "compiler_structural_rules_checked",
                    "canonical_validation_reached")))
                self.assertEqual((True, False, True, False),
                                 (completeness["observed_blockers_preserved"],
                                  completeness["downstream_canonical_issues_enumerated"],
                                  completeness["independent_checks_consistent_with_compiler"], diagnostic["complete"]))
                self.assertIn(v31.LIMIT_CANONICAL_NOT_ENUMERATED, diagnostic["limitations"])
                self.assertEqual(not expected[3], v31.LIMIT_CANONICAL_NOT_REACHED in diagnostic["limitations"])
                self.assertEqual(not expected[2], v31.LIMIT_COMPILER_NOT_REACHED in diagnostic["limitations"])
                self.assertEqual(not expected[0], v31.LIMIT_LOCATOR in diagnostic["limitations"])
                self.assertEqual(not expected[1], v31.LIMIT_CANONICAL_UNRECOGNIZED in diagnostic["limitations"])

    def test_the_compiler_canonical_blocker_is_kept_next_to_the_independent_findings(self):
        context, draft = b4d.fixture("c07_location")
        diagnostic = diagnose(b4d.duplicated(b4d.disallowed_kind(draft)), context)
        self.assertEqual(["ARGUMENT_ENTITY_KIND_NOT_ALLOWED", "ARGUMENT_ENTITY_KIND_NOT_ALLOWED",
                          "DUPLICATE_CONCRETE_PROPOSITION_CONTENT", "CANONICAL_CONFORMANCE_FAILURE"], codes(diagnostic))
        blocker = diagnostic["findings"][-1]
        self.assertEqual(("FROZEN_COMPILER_BLOCKER", v31.RULE_CLASS_CANONICAL_EXPLAINED, "canonical",
                          v31.LOCATOR_NOT_SCOPED,
                          {"failed_validator_checks": ["canonical"], "independent_findings_for_the_canonical_check": 3}),
                         (blocker["source"], blocker["rule_class"], blocker["validator_check"],
                          blocker["record_locator"], blocker["structural_detail"]))
        self.assertEqual(1, diagnostic["compiler_verdict"]["compiler_blockers"])
        self.assertEqual(1, sum(finding["source"] == "FROZEN_COMPILER_BLOCKER" for finding in diagnostic["findings"]))
        self.assertTrue(diagnostic["completeness"]["observed_blockers_attributed"])
        self.assertFalse(diagnostic["complete"])
        several = v31._canonical_blocker_finding(
            {"phase": "CANONICAL_COMPILER", "code": "CANONICAL_CONFORMANCE_FAILURE", "path": "evidence,canonical,zz"}, 2)
        self.assertEqual((v31.RULE_CLASS_CANONICAL_UNRECOGNIZED, None,
                          {"failed_validator_checks": ["<UNVERIFIED>", "canonical", "evidence"],
                           "independent_findings_for_the_canonical_check": 2}),
                         (several["rule_class"], several["validator_check"], several["structural_detail"]))

    def test_host_context_failure_unknown_code_and_disagreement_are_stated(self):
        context, draft = b4d.fixture("c07_location")
        broken_context = dataclasses.replace(context, passage_inputs=[])
        diagnostic = diagnose(draft, broken_context)
        self.assertEqual(("DRAFT_COMPILER_FAILURE", ["EMPTY_SCOPE"], False),
                         (diagnostic["category"], codes(diagnostic), diagnostic["findings"][0]["repairable_by_model"]))
        self.assertFalse(diagnostic["completeness"]["compiler_structural_rules_checked"])
        self.assertIn(v31.LIMIT_HOST_SIDE, diagnostic["limitations"])
        with blocked(StructuralBlocker("QUOTE", "SOME_FUTURE_CODE", "mentions/M1")):
            diagnostic = diagnose(draft, context)
        self.assertEqual(([v31.UNRECOGNIZED_CODE], False),
                         (codes(diagnostic), diagnostic["completeness"]["observed_blockers_attributed"]))
        self.assertNotIn("SOME_FUTURE_CODE", json.dumps(diagnostic))
        invented = v31._finding("DUPLICATE_CONCRETE_PROPOSITION_CONTENT", source="INDEPENDENT_REGISTRY_CHECK",
                                compiler_reached=True)
        with mock.patch.object(v31, "registry_rule_findings", return_value=[invented]):
            diagnostic = diagnose(draft, context)
        self.assertEqual((None, [], True, False, False, [v31.LIMIT_CHECK_DISAGREEMENT]),
                         (diagnostic["category"], diagnostic["findings"], diagnostic["compiler_verdict"]["compiled"],
                          diagnostic["completeness"]["independent_checks_consistent_with_compiler"],
                          diagnostic["complete"], diagnostic["limitations"]))
        broken = copy.deepcopy(draft)
        del broken["mentions"][0]["role"]
        with mock.patch.object(p4_contract, "schema_findings", return_value=[]):
            diagnostic = diagnose(broken, context)
        self.assertEqual((["DRAFT_SCHEMA_FAILURE"], False, v31.LOCATOR_NOT_SCOPED),
                         (codes(diagnostic), diagnostic["completeness"]["observed_blockers_attributed"],
                          diagnostic["findings"][0]["record_locator"]))
        self.assertIn(v31.LIMIT_SCHEMA_UNDESCRIBED, diagnostic["limitations"])

    def test_multiple_blockers_with_masked_identities_keep_their_exact_count(self):
        context = b4d.text_context("Rin met Rin at noon.")
        blockers = [StructuralBlocker("QUOTE", "AMBIGUOUS_QUOTE", "mentions/" + ADVERSARIAL[0]),
                    StructuralBlocker("QUOTE", "AMBIGUOUS_QUOTE", "mentions/" + ADVERSARIAL[1]),
                    StructuralBlocker("QUOTE", "AMBIGUOUS_QUOTE", "mentions/M1"),
                    StructuralBlocker("HANDLE", "UNKNOWN_HANDLE", "assertions/A1/proposition_handle"),
                    StructuralBlocker("HANDLE", "UNKNOWN_HANDLE", "assertions/A2/proposition_handle"),
                    StructuralBlocker("HANDLE", "DUPLICATE_HANDLE", ADVERSARIAL[2]),
                    StructuralBlocker("HANDLE", "DUPLICATE_HANDLE", "M1"),
                    StructuralBlocker(ADVERSARIAL[1], "AMBIGUOUS_QUOTE", ADVERSARIAL[0]),
                    StructuralBlocker("CANONICAL_COMPILER", "CANONICAL_CONFORMANCE_FAILURE", "")]
        with blocked(*blockers):
            diagnostic = v31.structural_diagnostic_v3_1(json.dumps(b4d.mention_draft("Rin")), context)
        self.assertEqual((9, 9, 9), (diagnostic["finding_count"], diagnostic["compiler_verdict"]["compiler_blockers"],
                                     sum(finding["source"] == "FROZEN_COMPILER_BLOCKER"
                                         for finding in diagnostic["findings"])))
        located = [finding for finding in diagnostic["findings"] if finding["record_locator"] == v31.LOCATOR_VERIFIED]
        self.assertEqual([("mentions", v31.LOCATOR_VERIFIED, 0, "M1")], [triple(finding) for finding in located])
        self.assertEqual(7, sum(finding["record_locator"] == v31.LOCATOR_UNAVAILABLE for finding in diagnostic["findings"]))
        self.assertEqual(["M1"], sorted(set(handle_like_values(diagnostic["findings"])) - {"P1"}))
        for needle in ADVERSARIAL[:3]:
            self.assertNotIn(needle, json.dumps(diagnostic, ensure_ascii=False))
        self.assertEqual((False, True), (diagnostic["completeness"]["observed_blockers_located"],
                                         diagnostic["completeness"]["observed_blockers_preserved"]))

    def test_blocker_counts_are_preserved_on_a_generic_mutation_corpus(self):
        checked = rejected = 0
        for name in fx.CASES:
            context, base = b4d.fixture(name)
            for index, draft in enumerate(b4d.b4a.mutants(base)):
                if index % 17:
                    continue
                try:
                    compiler_v1_1.validate_draft_v1_1(draft)
                except compiler_v1_1.DraftCompilationErrorV1_1:
                    continue
                checked += 1
                diagnostic = diagnose(draft, context)
                try:
                    compiler_v1_1.compile_story_extraction_draft_v1_1(draft, context)
                    blockers = ()
                except compiler_v1_1.DraftCompilationErrorV1_1 as error:
                    blockers = error.blockers
                rejected += bool(blockers)
                with self.subTest(fixture=name, mutant=index):
                    self.assertEqual(len(blockers), diagnostic["compiler_verdict"]["compiler_blockers"])
                    self.assertEqual(len(blockers), sum(finding["source"] == "FROZEN_COMPILER_BLOCKER"
                                                        for finding in diagnostic["findings"]))
                    self.assertEqual(not blockers, diagnostic["compiler_verdict"]["compiled"])
                    self.assertEqual(not blockers, diagnostic["complete"])
        self.assertEqual(b4d.CORPUS["generic_schema_valid_mutants"], checked)
        self.assertGreater(rejected, 100)

    def test_independent_checks_agree_with_the_frozen_validator(self):
        """Same corpus and the same expected counts as the M4-04B4D comparison, now for V3.1."""
        known = set(v31.INDEPENDENTLY_CHECKED_CANONICAL_RULES)
        registry = contract_v1.load_registry()
        kinds = materializer.load_tracked_model_schema()["$defs"]["EntityKind"]["enum"]
        seen = {code: 0 for code in v31.INDEPENDENTLY_CHECKED_CANONICAL_RULES}
        compared = 0
        for name in fx.CASES:
            context, base = b4d.fixture(name)
            variants = []
            for proposition in base["propositions"]:
                if "predicate" in proposition:
                    variants.append(copy.deepcopy(base))
                    variants[-1]["propositions"].append(
                        {**copy.deepcopy(proposition), "handle": f"PROP{len(base['propositions']) + 1}"})
            for index, entity in enumerate(base["entities"]):
                for kind in kinds:
                    if kind != entity["kind"]:
                        variants.append(copy.deepcopy(base))
                        variants[-1]["entities"][index]["kind"] = kind
            for index, assertion in enumerate(base["assertions"]):
                for position, derivation in enumerate(assertion["support"]["derivations"]):
                    for rule_id in registry["derivation_rules"]:
                        if rule_id != derivation["rule_id"]:
                            variants.append(copy.deepcopy(base))
                            variants[-1]["assertions"][index]["support"]["derivations"][position]["rule_id"] = rule_id
            for draft in variants:
                blockers, issues = b4d.validator_issues(draft, context)
                if not any(blocker["code"] == "CANONICAL_CONFORMANCE_FAILURE" for blocker in blockers):
                    continue
                compared += 1
                diagnostic = diagnose(draft, context)
                found = [finding for finding in diagnostic["findings"] if finding["code"] in known]
                from_validator = sorted(issue["rule_class"] for issue in issues if issue["rule_class"] in known)
                with self.subTest(fixture=name):
                    self.assertEqual(from_validator, sorted(finding["code"] for finding in found))
                    self.assertTrue(all(finding["record_locator"] == v31.LOCATOR_VERIFIED and finding["compiler_reached"]
                                        for finding in found))
                    self.assertTrue(diagnostic["completeness"]["canonical_validation_reached"])
                    self.assertEqual(bool(from_validator), diagnostic["completeness"]["observed_blockers_attributed"])
                    old = [(finding["code"], finding["record_index"], finding["record_handle"])
                           for finding in diagnose_v3(draft, context)["findings"] if finding["code"] in known]
                    self.assertEqual(old, [(finding["code"], finding["record_index"], finding["record_handle"])
                                           for finding in found])
                for code in from_validator:
                    seen[code] += 1
        self.assertEqual({name: b4d.CORPUS[name] for name in ("targeted_variants_reaching_canonical_validation", *seen)},
                         {"targeted_variants_reaching_canonical_validation": compared, **seen})

    def test_bytes_and_order_are_deterministic(self):
        context, draft = three_problem_draft()
        first = diagnose(draft, context)
        self.assertEqual(v31.canonical_json_bytes(first), v31.canonical_json_bytes(diagnose(copy.deepcopy(draft), context)))
        shuffled = {key: draft[key] for key in reversed(list(draft))}
        shuffled["mentions"] = [dict(reversed(list(mention.items()))) for mention in shuffled["mentions"]]
        self.assertEqual(v31.diagnostic_sha256(first), v31.diagnostic_sha256(diagnose(shuffled, context)))
        self.assertRegex(v31.diagnostic_sha256(first), r"^[0-9a-f]{64}$")
        self.assertEqual(v31.ENVELOPE_FIELDS, tuple(first))
        for finding in first["findings"]:
            self.assertEqual(v31.FINDING_FIELDS, tuple(finding))
        phases = [v31.PHASES.index(finding["phase"]) for finding in first["findings"]]
        self.assertEqual(sorted(phases), phases)
        self.assertNotEqual(v31.diagnostic_sha256(first),
                            v31.diagnostic_sha256(diagnose(*reversed(shared_mention_handle()))))
        text = v31.canonical_json_bytes(first).decode("ascii")
        for forbidden in ("2026", "C:\\\\", "/tmp", "E:/", "uuid"):
            self.assertNotIn(forbidden, text)

    def test_diagnostic_and_candidate_hashes_are_the_same_in_fresh_processes(self):
        context, draft = three_problem_draft()
        script = (
            "import json\n"
            "from tests.story_extraction import test_m4_04b4d_f1_p4_1_diagnostic_identity_correction_v1 as t\n"
            "context, draft = t.three_problem_draft()\n"
            "print(json.dumps([t.v31.diagnostic_sha256(t.diagnose(draft, context)), t.contract.candidate_sha256(),\n"
            "                  t.contract.main([])]))\n"
        )
        expected = [v31.diagnostic_sha256(diagnose(draft, context)), contract.CANDIDATE_SHA256, 0]
        for seed in ("0", "271828"):
            environment = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(REPO_ROOT),
                           "PYTHONDONTWRITEBYTECODE": "1"}
            done = subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT, env=environment, capture_output=True,
                                  text=True, timeout=300)
            self.assertEqual(0, done.returncode, done.stderr[-2000:])
            self.assertEqual(expected, json.loads(done.stdout.strip().splitlines()[-1]))


# ---------------------------------------------------------------------------
# Leak safety and the public summary
# ---------------------------------------------------------------------------

class LeakSafetyTests(unittest.TestCase):
    def assert_clean(self, diagnostic, needle):
        if needle != "quote":  # a schema field name, which a diagnostic may contain on its own account
            self.assertNotIn(needle, json.dumps(diagnostic, ensure_ascii=False))
            self.assertNotIn(json.dumps(needle)[1:-1], json.dumps(diagnostic))

    def test_arbitrary_text_in_any_draft_position_never_reaches_a_diagnostic(self):
        context, base = b4d.fixture("c08_possession")
        placements = {
            "record_handle": lambda d, s: d["mentions"][0].__setitem__("handle", s),
            "every_handle_of_a_collection": lambda d, s: [m.__setitem__("handle", s) for m in d["mentions"]],
            "entity_handle": lambda d, s: d["entities"][0].__setitem__("handle", s),
            "referenced_handle": lambda d, s: d["assertions"][0].__setitem__("proposition_handle", s),
            "argument_handle": lambda d, s: d["propositions"][-1]["args"].__setitem__(
                "holder", {"kind": "ENTITY", "handle": s}),
            "passage_handle": lambda d, s: d["mentions"][0].__setitem__("passage_handle", s),
            "quote_text": lambda d, s: d["mentions"][0].__setitem__("quote", s),
            "entity_label": lambda d, s: d["entities"][0].__setitem__("editorial_label", s[:200]),
            "unknown_property_name": lambda d, s: d["mentions"][0].__setitem__(s, 1),
            "unknown_root_property": lambda d, s: d.__setitem__(s, []),
            "predicate_like_string": lambda d, s: d["propositions"][-1].__setitem__("predicate", s),
            "argument_name": lambda d, s: d["propositions"][-1]["args"].__setitem__(
                s, {"kind": "ENTITY", "handle": "E_NEW_77"}),
            "literal_value": lambda d, s: d["propositions"][-1]["args"].__setitem__(
                "item", {"kind": "LITERAL", "value_type": "STRING", "value": s}),
            "rule_id": lambda d, s: d["assertions"][0]["support"]["derivations"].append(
                {"rule_id": s, "premise_handles": [d["assertions"][0]["handle"]]}),
        }
        produced = 0
        for label, place in placements.items():
            for needle in ADVERSARIAL:
                draft = copy.deepcopy(base)
                place(draft, needle)
                with self.subTest(placement=label, needle=needle[:24]):
                    diagnostic = diagnose(draft, context)
                    produced += diagnostic["finding_count"] > 0
                    self.assert_clean(diagnostic, needle)
                    identity = v31.build_identity_index(draft, context)
                    for finding in diagnostic["findings"]:
                        if finding["record_handle"] is not None:
                            self.assertEqual(finding["record_index"],
                                             identity.unique_index(finding["record_collection"], finding["record_handle"]))
        self.assertGreater(produced, len(placements) * len(ADVERSARIAL) // 2)

    def test_arbitrary_text_in_raw_responses_and_compiler_messages_never_reaches_a_diagnostic(self):
        context = b4d.text_context("Rin met Rin at noon.")
        raw = json.dumps(b4d.mention_draft("Rin"))
        for needle in ADVERSARIAL:
            with self.subTest(needle=needle[:24]):
                for response in (needle, "{\"" + needle, json.dumps([needle])):
                    self.assert_clean(v31.structural_diagnostic_v3_1(response, context), needle)
                for blocker in (
                    StructuralBlocker("QUOTE", "AMBIGUOUS_QUOTE", f"mentions/{needle}"),
                    StructuralBlocker("QUOTE", needle, "mentions/M1"),
                    StructuralBlocker(needle, "AMBIGUOUS_QUOTE", needle),
                    StructuralBlocker("HANDLE", "UNKNOWN_HANDLE", f"propositions/PROP1/args/{needle}/handle"),
                    StructuralBlocker("HANDLE", "UNKNOWN_HANDLE", f"{needle}/M1/handle"),
                    StructuralBlocker("HANDLE", "DUPLICATE_HANDLE", needle),
                    StructuralBlocker("CANONICAL_COMPILER", "CANONICAL_CONFORMANCE_FAILURE", f"canonical,{needle}"),
                    StructuralBlocker("CANONICAL_COMPILER", needle, needle),
                    StructuralBlocker("CONTEXT", "INVALID_PASSAGE_INPUT", needle),
                ):
                    with blocked(blocker):
                        diagnostic = v31.structural_diagnostic_v3_1(raw, context)
                    self.assert_clean(diagnostic, needle)
                    self.assertEqual(("DRAFT_COMPILER_FAILURE", 1, 1),
                                     (diagnostic["category"], diagnostic["finding_count"],
                                      diagnostic["compiler_verdict"]["compiler_blockers"]))

    def test_every_handle_in_a_diagnostic_is_verified_on_the_mutation_corpus(self):
        """No handle-shaped string appears unless the identity index vouches for it in that place."""
        handles = 0
        for name in ("c02_two_mentions_one_entity", "c08_possession", "c12_suggested_emotion"):
            context, base = b4d.fixture(name)
            for index, draft in enumerate(b4d.b4a.mutants(base)):
                if index % 11:
                    continue
                diagnostic = diagnose(draft, context)
                identity = v31.build_identity_index(draft, context)
                allowed = set(identity.passages)
                for finding in diagnostic["findings"]:
                    if finding["record_handle"] is not None:
                        self.assertEqual(finding["record_index"],
                                         identity.unique_index(finding["record_collection"], finding["record_handle"]))
                        allowed.add(finding["record_handle"])
                    for key, (flag, collection) in v31.REFERENCE_KEYS.items():
                        value = finding["structural_detail"].get(key)
                        if value is not None:
                            self.assertTrue(identity.is_existing(value, collection)
                                            or identity.unique_index(collection, value) is not None)
                            allowed.add(value)
                found = set(handle_like_values(diagnostic["findings"]))
                self.assertLessEqual(found, allowed)
                handles += len(found)
        self.assertGreater(handles, 300)

    def test_public_summary_holds_codes_and_counts_only(self):
        for context, draft in (three_problem_draft(), shared_mention_handle()):
            diagnostic = diagnose(draft, context)
            summary = v31.public_summary(diagnostic)
            self.assertEqual(diagnostic["finding_count"], sum(summary["findings_by_code"].values()))
            self.assertEqual(diagnostic["finding_count"], sum(summary["findings_by_record_locator"].values()))
            self.assertEqual(diagnostic["completeness"], summary["completeness"])
            self.assertEqual([], handle_like_values(summary))
            text = json.dumps(summary)
            for finding in diagnostic["findings"]:
                if finding["schema_path"]:
                    self.assertNotIn(finding["schema_path"], text)
            for forbidden in ("mentions/", "propositions/", "OccursAt", "LOCATION", "record_index", "record_handle",
                              "schema_path", "structural_detail"):
                self.assertNotIn(forbidden, text)
            for value in b4d.strings_in(summary):
                self.assertTrue(value in v31._trusted_tokens() or value in v31.COMPLETENESS_FIELDS
                                or value in ("diagnostic", "category", "complete", "completeness", "limitations",
                                             "finding_count", "compiler_blockers", "findings_by_code",
                                             "findings_by_rule_class", "findings_by_source",
                                             "findings_by_record_locator"), value)


# ---------------------------------------------------------------------------
# No implicit occurrence, repair prompt and candidate
# ---------------------------------------------------------------------------

class RepairPromptAndCandidateTests(unittest.TestCase):
    def test_no_occurrence_or_other_draft_field_is_chosen_by_the_host(self):
        context = b4d.text_context("Rin met Rin at noon.")
        draft = b4d.mention_draft("Rin")
        before = copy.deepcopy(draft)
        diagnostic = diagnose(draft, context)
        self.assertEqual(before, draft)
        detail = diagnostic["findings"][0]["structural_detail"]
        self.assertEqual((2, False, True, 1, 2), tuple(detail[key] for key in (
            "exact_match_count", "occurrence_present", "occurrence_required", "valid_occurrence_minimum",
            "valid_occurrence_maximum")))
        self.assertNotIn("occurrence", detail)
        self.assertFalse(any(key.startswith(("suggested", "recommended", "default", "chosen")) for key in detail))
        with self.assertRaises(compiler_v1_1.DraftCompilationErrorV1_1):
            compiler_v1_1.compile_story_extraction_draft_v1_1(draft, context)
        for module in (contract, v31):
            for node in ast.walk(ast.parse(Path(module.__file__).read_text(encoding="utf-8"))):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(
                    node, (ast.AugAssign, ast.AnnAssign)) else []
                for target in targets:
                    if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant):
                        self.assertNotIn(target.slice.value, ("occurrence", "quote", "kind", "rule_id", "predicate",
                                                              "handle"), f"{module.__name__} writes a draft field")
        self.assertTrue(contract.repair_prompt_coverage()["no_default_occurrence_wording_in_any_prompt"])
        self.assertEqual("FORBIDDEN", contract.candidate_definition()["host_behaviour"]["automatic_occurrence_selection"])

    def test_repair_prompt_explains_every_v3_1_code_field_state_and_statement(self):
        report = contract.repair_prompt_coverage()
        for name in ("codes_explained", "finding_fields_explained", "envelope_fields_explained",
                     "locator_states_explained", "completeness_statements_explained", "finding_sources_explained",
                     "canonical_rule_classes_explained", "statements", "superseded_wording_absent"):
            self.assertTrue(report[name] and all(report[name].values()), name)
        self.assertEqual(sorted(code for code, rule in v31.RULE_TAXONOMY.items() if rule[4]),
                         sorted(report["codes_explained"]))
        self.assertEqual(set(v31.FINDING_FIELDS), set(report["finding_fields_explained"]))
        self.assertEqual(set(v31.COMPLETENESS_FIELDS), set(report["completeness_statements_explained"]))
        self.assertEqual(set(v31.LOCATOR_STATES), set(report["locator_states_explained"]))
        self.assertEqual(set(v3.RULE_TAXONOMY), set(v31.RULE_TAXONOMY))
        with mock.patch.dict(v31.RULE_TAXONOMY, {"NEW_UNEXPLAINED_CODE": ("QUOTE", "X", None, None, True)}):
            with self.assertRaises(contract.P41ContractV11Error):
                contract.repair_prompt_coverage()
        with mock.patch.object(v31, "COMPLETENESS_FIELDS", v31.COMPLETENESS_FIELDS + ("an_unexplained_statement",)):
            with self.assertRaises(contract.P41ContractV11Error):
                contract.repair_prompt_coverage()
        with mock.patch.object(contract, "REPAIR_RULE_STATEMENTS",
                               {**contract.REPAIR_RULE_STATEMENTS, "missing": "a sentence that is not there"}):
            with self.assertRaises(contract.P41ContractV11Error):
                contract.repair_prompt_coverage()

    def test_the_two_audited_repair_instructions_are_replaced(self):
        old = contract_v1.prompt_material()["repair_user_template"]
        new = contract.prompt_material()["repair_user_template"]
        for phrase in contract.SUPERSEDED_REPAIR_WORDING:
            self.assertIn(" ".join(phrase.split()), " ".join(old.split()))
            self.assertNotIn(" ".join(phrase.split()), " ".join(new.split()))
        flat = " ".join(new.split())
        self.assertNotRegex(flat, r"(?i)\breturn a (?:different|changed) response\b")
        self.assertNotRegex(flat, r"(?i)\bmust (?:differ|be different)\b")
        for name in ("no_change_for_its_own_sake", "correct_in_place_first", "removal_is_last_resort",
                     "removal_is_minimal", "unaffected_records_are_kept", "no_removal_to_pass",
                     "no_empty_or_reduced_draft"):
            self.assertIn(" ".join(contract.REPAIR_RULE_STATEMENTS[name].split()), flat)
        with mock.patch.object(contract, "SUPERSEDED_REPAIR_WORDING", ("Removing a record is the last resort",)):
            with self.assertRaises(contract.P41ContractV11Error):
                contract.repair_prompt_coverage()
        definition = contract.candidate_definition()
        self.assertEqual({"metrics": list(contract.REQUIRED_LIVE_REPORTING), "acceptance_threshold": "NONE_DEFINED"},
                         definition["required_live_reporting"])
        self.assertLessEqual({"RECORD_RETENTION_FROM_PRIMARY_TO_REPAIR_BY_COLLECTION", "EMPTY_OUTPUT_RATE",
                              "STRUCTURAL_VALIDITY"}, set(contract.REQUIRED_LIVE_REPORTING))

    def test_an_empty_draft_is_compiler_valid_which_is_why_retention_must_be_reported(self):
        """The premise of the audit, established offline: structural validity alone cannot see deleted content."""
        for name in ("c02_two_mentions_one_entity", "c08_possession"):
            context, _ = b4d.fixture(name)
            diagnostic = diagnose(b4d.empty_draft(), context)
            self.assertEqual((None, True, True), (diagnostic["category"], diagnostic["compiler_verdict"]["compiled"],
                                                  diagnostic["complete"]))

    def test_repair_request_carries_exactly_the_diagnostic_v3_1_builds(self):
        context, draft = shared_mention_handle()
        prepared = prepare_story_extraction_draft_v1_1(context)
        raw = json.dumps(draft)
        diagnostic = v31.structural_diagnostic_v3_1(raw, context)
        repair = contract.render_repair_user("SYN_01", prepared, raw, diagnostic, context)
        for part in (raw, p4_contract.canonical_json(diagnostic), p4_contract.canonical_json(prepared), "SYN_01",
                     "STRUCTURAL_DIAGNOSTIC_V3_1_JSON:"):
            self.assertIn(part, repair)
        self.assertNotIn("{CASE_ID}", repair)
        tampered = copy.deepcopy(diagnostic)
        tampered["findings"][0]["record_handle"] = draft["mentions"][0]["handle"]
        valid_raw = json.dumps(b4d.fixture("c02_two_mentions_one_entity")[1])
        refused = (
            (raw, tampered, context),
            (raw, diagnose_v3(draft, context), context),
            (raw, {**diagnostic, "complete": True}, context),
            (raw, None, context),
            (raw, diagnostic, b4d.fixture("c07_location")[0]),
            (json.dumps(b4d.ambiguous(copy.deepcopy(draft))), diagnostic, context),
            (valid_raw, v31.structural_diagnostic_v3_1(valid_raw, context), context),
            ("", diagnostic, context),
        )
        for response, supplied, used_context in refused:
            with self.assertRaises(contract.P41ContractV11Error):
                contract.render_repair_user("SYN_01", prepared, response, supplied, used_context)
        for case_id in ("syn", "../X", "", None):
            with self.assertRaises(contract.P41ContractV11Error):
                contract.render_repair_user(case_id, prepared, raw, diagnostic, context)
            with self.assertRaises(contract.P41ContractV11Error):
                contract.render_primary_user(case_id, prepared)
        self.assertEqual(contract_v1.render_primary_user("SYN_01", prepared), contract.render_primary_user("SYN_01", prepared))

    def test_candidate_v1_1_is_locked_and_keeps_the_primary_prompts(self):
        definition = contract.candidate_definition()
        self.assertEqual(contract.CANDIDATE_SHA256, contract.candidate_sha256())
        self.assertNotEqual(contract.SUPERSEDED_CANDIDATE_SHA256, contract.CANDIDATE_SHA256)
        self.assertEqual(("P4_1_STORY_EXTRACTION_DRAFT_V1_1_COMPILER_AWARE_V1_1",
                          "M4_P4_1_STRUCTURAL_REPAIR_DIAGNOSTIC_V3_1"),
                         (definition["candidate_id"], definition["repair"]["diagnostic"]))
        self.assertEqual({"candidate_id": contract_v1.CANDIDATE_ID, "candidate_sha256": contract_v1.CANDIDATE_SHA256,
                          "diagnostic": v3.DIAGNOSTIC_ID, "status": "HISTORICAL_NOT_FOR_RUNTIME_USE"},
                         definition["supersedes"])
        hashes = contract.prompt_hashes()
        self.assertEqual(SUPERSEDED_PRIMARY_PROMPTS, {name: hashes[name] for name in SUPERSEDED_PRIMARY_PROMPTS})
        self.assertIs(True, definition["primary_prompts_identical_to_superseded_candidate"])
        old = contract_v1.prompt_hashes()
        for name in ("repair_system_sha256", "repair_user_template_sha256", "repair_prompt_pair_sha256"):
            self.assertNotEqual(old[name], hashes[name])
        self.assertEqual(protocol_v2.normalized_file_sha256(Path(v31.__file__)),
                         definition["repair"]["diagnostic_tool_sha256"])
        self.assertNotEqual(SUPERSEDED_FILES["tools/story_extraction/m4_04b4d_structural_diagnostic_v3.py"],
                            definition["repair"]["diagnostic_tool_sha256"])
        self.assertEqual((False, False), (definition["model_schema"]["changed"], definition["provider_projection"]["changed"]))
        self.assertEqual({"live_protocol_bound": False, "model_bound": False, "credential_bound": False,
                          "operation_budget_bound": False, "live_runner": "NOT_CREATED"}, definition["runtime"])
        report = contract.assert_candidate_ready()
        self.assertEqual({"superseded_candidate_intact", "schema_lineage", "quote_rule_coverage",
                          "registry_rule_coverage", "repair_prompt_coverage"}, set(report))
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(0, contract.main([]))
        self.assertIn(contract.CANDIDATE_SHA256, printed.getvalue())
        with mock.patch.object(contract, "REPAIR_SYSTEM_SUFFIX", contract.REPAIR_SYSTEM_SUFFIX + " "):
            with self.assertRaises(contract.P41ContractV11Error):
                contract.assert_candidate_ready()
        with mock.patch.object(contract_v1, "CANDIDATE_SHA256", "0" * 64):
            with self.assertRaises(contract.P41ContractV11Error):
                contract.assert_candidate_ready()

    def test_frozen_stack_is_unchanged_and_no_runner_or_provider_code_exists(self):
        from tools.story_extraction import m4_04b3h0_dev3_decision_lock_v1 as decision_lock

        for relative, expected in b4d.HISTORICAL.items():
            with self.subTest(path=relative):
                self.assertEqual(expected, protocol_v2.normalized_file_sha256(REPO_ROOT / relative))
        self.assertEqual({"PASS"}, set(decision_lock.validate_protected_stacks().values()))
        self.assertEqual(b4d.PROTOCOL_V2, protocol_v2.protocol_sha256())
        self.assertEqual("M4_P4_STRUCTURAL_REPAIR_DIAGNOSTIC_V2", p4_contract.REPAIR_DIAGNOSTIC_ID)
        tools = REPO_ROOT / "tools/story_extraction"
        self.assertEqual([], sorted(path.name for path in tools.glob("run_m4_04b4d*")))
        for module in (contract, v31):
            source = Path(module.__file__).read_text(encoding="utf-8")
            for forbidden in ("load_runtime_config", "GeminiDevWindowTransport", "official_client_factory", "genai",
                              "DurableResearchExecutor", "import google", "DEV3_INPUT", "gold_archive", "zipfile",
                              "evaluate_case", "unittest", "mock.patch", "subprocess", "urllib", "requests"):
                self.assertNotIn(forbidden, source, f"{module.__name__}: {forbidden}")
            self.assertTrue(source.isascii())
        self.assertTrue(contract.REPAIR_USER_TEMPLATE_PATH.read_bytes().isascii())


# ---------------------------------------------------------------------------
# Public correction record and project state
# ---------------------------------------------------------------------------

class PublicRecordTests(unittest.TestCase):
    RECORD = REPO_ROOT / "benchmarks/m4_extraction/M4_04B4D_F1_P4_1_DIAGNOSTIC_IDENTITY_CORRECTION.yaml"

    def setUp(self):
        self.text = self.RECORD.read_text(encoding="utf-8")
        self.record = yaml.safe_load(self.text)

    def test_record_binds_the_corrected_identities_and_the_history(self):
        record = self.record
        self.assertEqual(("M4-04B4D-F1", "M4_04B4D_F1_SAFE_LOCATOR_CORRECTION_READY", contract.EXPECTED_BASE_COMMIT),
                         (record["task"], record["status"], record["base_commit"]))
        history = record["historical_B4D"]
        self.assertEqual((contract.SUPERSEDED_CANDIDATE_ID, contract.SUPERSEDED_CANDIDATE_SHA256, v3.DIAGNOSTIC_ID),
                         (history["candidate_identity"], history["candidate_sha256"], history["diagnostic_identity"]))
        self.assertEqual(SUPERSEDED_FILES, history["files_unchanged"])
        self.assertIs(False, history["record_rewritten"])
        corrected = record["corrected"]
        self.assertEqual((v31.DIAGNOSTIC_ID, v31.DIAGNOSTIC_FORMAT, contract.CANDIDATE_ID, contract.CANDIDATE_SHA256),
                         (corrected["diagnostic_identity"], corrected["diagnostic_format"],
                          corrected["candidate_identity"], corrected["candidate_sha256"]))
        self.assertEqual(protocol_v2.normalized_file_sha256(Path(v31.__file__)), corrected["diagnostic_tool"]["sha256"])
        self.assertEqual(protocol_v2.normalized_file_sha256(Path(contract.__file__)), corrected["contract_tool"]["sha256"])
        self.assertEqual(contract.prompt_hashes(), corrected["prompt_hashes"])
        self.assertIs(True, corrected["primary_prompts_identical_to_B4D"])
        self.assertEqual(list(v31.COMPLETENESS_FIELDS), record["completeness_semantics"]["statements"])
        self.assertEqual(list(v31.LOCATOR_STATES), record["unique_record_identity_rule"]["locator_states"])
        self.assertEqual(list(contract.REQUIRED_LIVE_REPORTING),
                         record["prompt_risk_audit"]["required_reporting_in_any_live_experiment"])
        self.assertEqual("NONE_DEFINED", record["prompt_risk_audit"]["acceptance_threshold"])
        # The record quotes the audited instructions as they stand in the two templates, bullets joined.
        old = " ".join(contract_v1.prompt_material()["repair_user_template"].split()).replace(" - ", " ")
        new = " ".join(contract.prompt_material()["repair_user_template"].split()).replace(" - ", " ")
        audited = record["prompt_risk_audit"]["instructions_audited"]
        self.assertEqual(2, len(audited))
        for item in audited:
            self.assertIn(item["B4D_wording"], old)
            self.assertNotIn(item["B4D_wording"], new)
            self.assertIn(item["V1_1_wording"], new)
            self.assertEqual("REVISION_REQUIRED", item["assessment"])

    def test_record_counts_boundaries_and_public_safety(self):
        record = self.record
        tests = record["offline_tests"]
        own = unittest.defaultTestLoader.loadTestsFromName(__name__).countTestCases()
        self.assertEqual(own, tests["focused"]["tests"])
        regression = tests["complete_regression"]
        self.assertEqual((PREVIOUS_ACCEPTED_TOTAL, PREVIOUS_ACCEPTED_TOTAL + own, sum(regression["suites"].values())),
                         (regression["previous_total"], regression["total"], regression["total"]))
        boundaries = record["boundaries"]
        self.assertEqual((0, 0), (boundaries["provider_calls"], boundaries["model_calls"]))
        for name, value in boundaries.items():
            if name not in ("provider_calls", "model_calls"):
                self.assertIs(False, value, name)
        self.assertIs(False, record["reproduced_original_mismatch"]["source_text_disclosure_demonstrated"])
        self.assertIs(True, record["decision"]["invariant_resolved"])
        self.assertTrue(self.text.isascii())
        self.assertNotRegex(self.text, r"AIza[0-9A-Za-z_\-]{10,}")
        for forbidden in ("GEMINI_API_KEY", "draftv1-", "C:\\", ".local/", "Rin met", "ZZ_PRIVATE"):
            self.assertNotIn(forbidden, self.text)
        self.assertEqual([], [value for value in handle_like_values(record) if not value.startswith("P4")])

    def test_project_state_records_the_correction_and_keeps_b4d(self):
        state = (REPO_ROOT / "docs/PROJECT_STATE.md").read_text(encoding="utf-8")
        for required in (f"Status: {self.record['status']}", "Status: M4_04B4D_P4_1_OFFLINE_CONTRACT_READY",
                         contract.CANDIDATE_SHA256, contract.SUPERSEDED_CANDIDATE_SHA256, v31.DIAGNOSTIC_ID,
                         self.record["decision"]["next_action"], "M4-04B4D-F1"):
            self.assertIn(required, state)
        self.assertLess(state.index("Status: M4_04B4D_P4_1_OFFLINE_CONTRACT_READY"),
                        state.index(f"Status: {self.record['status']}"))


if __name__ == "__main__":
    unittest.main()
