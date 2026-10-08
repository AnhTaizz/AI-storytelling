"""P4.1 compiler-aware contract V1.1 (M4-04B4D-F1). Offline design only.

V1.1 supersedes the P4.1 candidate of M4-04B4D. That candidate, its record and its files
stay in the repository unchanged as the historical record.

What V1.1 changes:

- the repair diagnostic is V3.1, which verifies record identity (see that module);
- the repair prompt is a new versioned template that explains the V3.1 fields, and
  rewrites two repair instructions the M4-04B4D-F1 risk audit found could reward the
  wrong behaviour.

What V1.1 does not change: the primary system prompt and the primary user template are
the M4-04B4D texts, byte for byte, assembled by the M4-04B4D module. The canonical
schemas, the full model schema, the provider projection, the compiler, the validator and
the registry are the accepted ones.

This module builds prompt text and checks coverage. It binds no model, credential,
runtime or operation budget, builds no request, calls no provider and reads no dataset.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Optional

from tools.story_extraction import m4_04b4a_p4_output_contract_v1 as p4_contract
from tools.story_extraction import m4_04b4br_p4_protocol_v2 as protocol_v2
from tools.story_extraction import m4_04b4d_f1_structural_diagnostic_v3_1 as diagnostic_v3_1
from tools.story_extraction import m4_04b4d_p4_1_compiler_aware_contract_v1 as contract_v1
from tools.story_extraction import materialize_draft_v1_1_model_schema_v1 as materializer


TASK_ID = "M4-04B4D-F1"
EXPECTED_BASE_COMMIT = "e0a048fc07bed2d348a8eb1ed75d1c842c1a146e"
CANDIDATE_ID = "P4_1_STORY_EXTRACTION_DRAFT_V1_1_COMPILER_AWARE_V1_1"
CANDIDATE_FORMAT = "M4_P4_1_CANDIDATE_DEFINITION_V1_1"
# SHA-256 of canonical_json_bytes(candidate_definition()). A changed binding is a new candidate.
CANDIDATE_SHA256 = "5a102aa782f876dcbfc94d71fef238de0e712288ed4428a27df6984edfe23019"
CONTRACT_PATH = "tools/story_extraction/m4_04b4d_f1_p4_1_compiler_aware_contract_v1_1.py"
REPO_ROOT = contract_v1.REPO_ROOT

# The M4-04B4D candidate this one supersedes. It must stay exactly as it was accepted for review.
SUPERSEDED_CANDIDATE_ID = "P4_1_STORY_EXTRACTION_DRAFT_V1_1_COMPILER_AWARE_V1"
SUPERSEDED_CANDIDATE_SHA256 = "f016306647b48bf9b9dd6c7531a49c5e5775d8d9c7c760a54406e1035db218a8"
SUPERSEDED_DIAGNOSTIC_ID = "M4_P4_1_STRUCTURAL_REPAIR_DIAGNOSTIC_V3"

REPAIR_USER_TEMPLATE_PATH = contract_v1.PROMPT_ROOT / "story_extraction_draft_p4_1_v1_1_repair_user.txt"
PROMPT_FILES = (contract_v1.SYSTEM_PREAMBLE_PATH, contract_v1.USER_TEMPLATE_PATH, REPAIR_USER_TEMPLATE_PATH)
REPAIR_ELIGIBLE_CATEGORIES = ("JSON_PARSE_FAILURE", "DRAFT_SCHEMA_FAILURE", "DRAFT_COMPILER_FAILURE")
MAX_STRUCTURAL_REPAIRS_PER_CASE = 1

REPAIR_SYSTEM_SUFFIX = """
STRUCTURAL REPAIR MODE
The host rejected the primary response. Correct every finding of the structural
diagnostic V3.1 supplied by the host and change nothing else. A finding names the rule
that was broken and, where the host could verify it, the record. It never states what
the story content should be. Do not fill coverage gaps, optimize quality, consult gold,
or introduce a new interpretation. This is the only repair for the case.
""".strip()

# Statements the repair template must make, checked on its whitespace-normalized text.
REPAIR_RULE_STATEMENTS = {
    "one_repair_only": "This is the only repair for this case",
    "findings_from_three_stages": "by deterministic JSON parsing, by the model output schema, or by the frozen compiler and canonical validator",
    "repair_only_what_is_required": "Correct every finding. Change only what a finding requires",
    "preserve_other_choices": "Preserve every other choice of the primary response",
    "no_new_facts_coverage_quality_or_gold": "Do not add facts, improve coverage, optimize quality, use scores or consult gold",
    "no_reinterpretation": "Do not reinterpret the story merely to satisfy a rule",
    "every_finding_is_separate": "Every finding is a separate problem. Correct all of them",
    "detail_never_states_story_content": "It never holds story text and never states what the story content should be",
    "occurrence_is_not_defaulted": "The host does not know which one you mean and no default is correct",
    "registry_constraint_is_fixed": "The registry constraint is fixed",
    "no_change_for_its_own_sake": "Do not change anything else to make the response look different",
    "correct_in_place_first": "Correct a finding inside its record whenever the passages support a correction",
    "removal_is_last_resort": "Removing a record is the last resort",
    "removal_is_minimal": "remove that record and only the records that cannot exist without it",
    "unaffected_records_are_kept": "Keep every record that no finding names and that does not depend on a removed record",
    "no_removal_to_pass": "Do not remove supported records to make the draft pass",
    "no_empty_or_reduced_draft": "do not return an empty or reduced draft in place of a correction",
    "host_never_guesses_a_record": "The host never guesses a record",
    "duplicate_handle_is_not_shown": "A shared handle names no single record, so the host shows no handle and no index",
    "findings_are_not_everything": "The findings are therefore what the host saw, not everything that may be wrong",
    "complete_is_false_for_rejected_drafts": "It is false for every rejected draft",
}
# Wording of the M4-04B4D repair template that the risk audit replaced. It must not come back.
SUPERSEDED_REPAIR_WORDING = (
    "Return a response that is different from the primary response",
    "remove the record that breaks the rule, together with the records that depend on it",
)
# What a live experiment with this candidate must report next to structural validity. No threshold is defined.
REQUIRED_LIVE_REPORTING = (
    "STRUCTURAL_VALIDITY",
    "RECORD_RETENTION_FROM_PRIMARY_TO_REPAIR_BY_COLLECTION",
    "EMPTY_OUTPUT_RATE",
    "REPAIR_RESPONSES_IDENTICAL_TO_PRIMARY",
)


class P41ContractV11Error(RuntimeError):
    """The P4.1 V1.1 prompt, a coverage gate or a frozen binding does not hold. Fail closed."""


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

def prompt_material() -> dict[str, str]:
    """The exact V1.1 prompt texts. The primary pair is the M4-04B4D pair; the repair pair is new."""
    try:
        primary = contract_v1.prompt_material()
        template = REPAIR_USER_TEMPLATE_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (contract_v1.P41ContractError, OSError, UnicodeError) as error:
        raise P41ContractV11Error("A prompt file is unavailable") from error
    return {
        "primary_system": primary["primary_system"],
        "primary_user_template": primary["primary_user_template"],
        "repair_system": primary["primary_system"] + "\n\n" + REPAIR_SYSTEM_SUFFIX,
        "repair_user_template": template.rstrip() + "\n",
    }


def prompt_hashes() -> dict[str, str]:
    material = prompt_material()
    return {
        "primary_system_sha256": sha256_text(material["primary_system"]),
        "primary_user_template_sha256": sha256_text(material["primary_user_template"]),
        "primary_prompt_pair_sha256": sha256_text(material["primary_system"] + "\0" + material["primary_user_template"]),
        "repair_system_sha256": sha256_text(material["repair_system"]),
        "repair_user_template_sha256": sha256_text(material["repair_user_template"]),
        "repair_prompt_pair_sha256": sha256_text(material["repair_system"] + "\0" + material["repair_user_template"]),
    }


def render_primary_user(case_id: str, prepared_input: Mapping[str, Any]) -> str:
    try:
        return contract_v1.render_primary_user(case_id, prepared_input)
    except contract_v1.P41ContractError as error:
        raise P41ContractV11Error(str(error)) from error


def render_repair_user(case_id: str, prepared_input: Mapping[str, Any], primary_response: str,
                       diagnostic: Mapping[str, Any], compiler_context: Any) -> str:
    """The repair request: the same prepared input, the unchanged primary response and diagnostic V3.1.

    The diagnostic must be exactly the one V3.1 produces for this response and this context.
    It is rebuilt here and compared, so an edited or mismatched diagnostic is never rendered.
    """
    if not isinstance(primary_response, str) or not primary_response:
        raise P41ContractV11Error("Repair requires one successful primary response")
    if not isinstance(prepared_input, Mapping) or prepared_input.get("draft_version") != materializer.CANONICAL_DRAFT_VERSION:
        raise P41ContractV11Error("Prepared input is not Draft V1.1")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,39}", case_id if isinstance(case_id, str) else ""):
        raise P41ContractV11Error("Case id is not a valid case identifier")
    try:
        rebuilt = diagnostic_v3_1.structural_diagnostic_v3_1(primary_response, compiler_context)
    except diagnostic_v3_1.DiagnosticV31Error as error:
        raise P41ContractV11Error("Structural diagnostic V3.1 failed its safety assertion") from error
    if not isinstance(diagnostic, Mapping) or canonical_json_bytes(diagnostic) != canonical_json_bytes(rebuilt):
        raise P41ContractV11Error("Repair requires the structural diagnostic V3.1 of this response and context")
    if rebuilt["category"] not in REPAIR_ELIGIBLE_CATEGORIES or not rebuilt["findings"]:
        raise P41ContractV11Error("Repair requires a rejected response with findings")
    rendered = prompt_material()["repair_user_template"]
    for marker, value in {
        "{CASE_ID}": case_id,
        "{PREPARED_INPUT_JSON}": p4_contract.canonical_json(prepared_input),
        "{STRUCTURAL_DIAGNOSTIC_JSON}": p4_contract.canonical_json(rebuilt),
        "{PRIMARY_RESPONSE}": primary_response,
    }.items():
        if rendered.count(marker) != 1:
            raise P41ContractV11Error("Prompt marker missing or repeated: " + marker)
        rendered = rendered.replace(marker, value)
    return rendered


# ---------------------------------------------------------------------------
# Coverage gates
# ---------------------------------------------------------------------------

def _named(template: str, names) -> dict[str, bool]:
    return {name: re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", template) is not None
            for name in names}


def repair_prompt_coverage() -> dict[str, Any]:
    """The repair prompt explains every code, field, locator state and completeness statement of V3.1."""
    material = prompt_material()
    template = material["repair_user_template"]
    flat = _flat(template)
    repairable = sorted(code for code, rule in diagnostic_v3_1.RULE_TAXONOMY.items() if rule[4])
    everything = _flat("\n".join(material.values()))
    report = {
        "diagnostic": diagnostic_v3_1.DIAGNOSTIC_ID,
        "diagnostic_named_in_repair_prompts": (
            "STRUCTURAL_DIAGNOSTIC_V3_1_JSON" in template and "diagnostic V3.1" in _flat(material["repair_system"])),
        "codes_repairable_by_the_model": len(repairable),
        "codes_explained": _named(template, repairable),
        "finding_fields_explained": _named(template, diagnostic_v3_1.FINDING_FIELDS),
        "envelope_fields_explained": _named(template, ("completeness", "complete", "limitations")),
        "locator_states_explained": _named(template, diagnostic_v3_1.LOCATOR_STATES),
        "completeness_statements_explained": _named(template, diagnostic_v3_1.COMPLETENESS_FIELDS),
        "finding_sources_explained": _named(template, ("FROZEN_COMPILER_BLOCKER", "INDEPENDENT_REGISTRY_CHECK")),
        "canonical_rule_classes_explained": _named(template, (
            diagnostic_v3_1.RULE_CLASS_CANONICAL_EXPLAINED, diagnostic_v3_1.RULE_CLASS_CANONICAL_UNRECOGNIZED)),
        "statements": {name: _flat(phrase) in flat for name, phrase in REPAIR_RULE_STATEMENTS.items()},
        "superseded_wording_absent": {phrase: _flat(phrase) not in everything for phrase in SUPERSEDED_REPAIR_WORDING},
        "no_default_occurrence_wording_in_any_prompt": all(
            re.search(pattern, everything, re.IGNORECASE) is None
            for pattern in contract_v1.FORBIDDEN_DEFAULT_OCCURRENCE),
        "maximum_repairs_per_case": MAX_STRUCTURAL_REPAIRS_PER_CASE,
    }
    gates = [report["diagnostic_named_in_repair_prompts"], report["no_default_occurrence_wording_in_any_prompt"]]
    gates += [all(report[name].values()) for name in (
        "codes_explained", "finding_fields_explained", "envelope_fields_explained", "locator_states_explained",
        "completeness_statements_explained", "finding_sources_explained", "canonical_rule_classes_explained",
        "statements", "superseded_wording_absent")]
    if not all(gates):
        raise P41ContractV11Error("Repair prompt coverage is incomplete")
    return report


def superseded_candidate_intact() -> dict[str, Any]:
    """The M4-04B4D candidate and diagnostic V3 are exactly as recorded. History is not rewritten."""
    from tools.story_extraction import m4_04b4d_structural_diagnostic_v3 as diagnostic_v3

    try:
        contract_v1.assert_candidate_ready()
    except contract_v1.P41ContractError as error:
        raise P41ContractV11Error("The superseded M4-04B4D candidate changed") from error
    if (contract_v1.CANDIDATE_ID, contract_v1.CANDIDATE_SHA256, diagnostic_v3.DIAGNOSTIC_ID) != (
            SUPERSEDED_CANDIDATE_ID, SUPERSEDED_CANDIDATE_SHA256, SUPERSEDED_DIAGNOSTIC_ID):
        raise P41ContractV11Error("The superseded M4-04B4D candidate identity changed")
    return {"candidate_id": SUPERSEDED_CANDIDATE_ID, "candidate_sha256": SUPERSEDED_CANDIDATE_SHA256,
            "diagnostic": SUPERSEDED_DIAGNOSTIC_ID, "unchanged": True}


# ---------------------------------------------------------------------------
# Candidate definition
# ---------------------------------------------------------------------------

def _file_sha256(relative: str) -> str:
    return protocol_v2.normalized_file_sha256(REPO_ROOT / relative)


def candidate_definition() -> dict[str, Any]:
    """What P4.1 V1.1 is. An offline candidate: no model, credential, runtime or budget is bound."""
    superseded = contract_v1.candidate_definition()
    hashes, superseded_hashes = prompt_hashes(), contract_v1.prompt_hashes()
    return {
        "candidate_id": CANDIDATE_ID,
        "format": CANDIDATE_FORMAT,
        "task_id": TASK_ID,
        "base_commit": EXPECTED_BASE_COMMIT,
        "supersedes": {"candidate_id": SUPERSEDED_CANDIDATE_ID, "candidate_sha256": SUPERSEDED_CANDIDATE_SHA256,
                       "diagnostic": SUPERSEDED_DIAGNOSTIC_ID, "status": "HISTORICAL_NOT_FOR_RUNTIME_USE"},
        "change": "REPAIR_DIAGNOSTIC_AND_REPAIR_PROMPT_ONLY",
        "canonical_draft_contract": superseded["canonical_draft_contract"],
        "model_schema": superseded["model_schema"],
        "provider_projection": superseded["provider_projection"],
        "frozen": superseded["frozen"],
        "prompt_hashes": hashes,
        "primary_prompts_identical_to_superseded_candidate": all(
            hashes[name] == superseded_hashes[name] for name in (
                "primary_system_sha256", "primary_user_template_sha256", "primary_prompt_pair_sha256")),
        "prompt_files": {path.relative_to(REPO_ROOT).as_posix(): protocol_v2.normalized_file_sha256(path)
                         for path in PROMPT_FILES},
        "generated_prompt_sections": {
            **{name: value for name, value in superseded["generated_prompt_sections"].items()
               if name != "repair_system_suffix_sha256"},
            "repair_system_suffix_sha256": sha256_text(REPAIR_SYSTEM_SUFFIX),
        },
        "primary_prompt_assembly_tool_sha256": _file_sha256(contract_v1.CONTRACT_PATH),
        "repair": {
            "diagnostic": diagnostic_v3_1.DIAGNOSTIC_ID,
            "diagnostic_format": diagnostic_v3_1.DIAGNOSTIC_FORMAT,
            "diagnostic_tool_sha256": _file_sha256(diagnostic_v3_1.DIAGNOSTIC_PATH),
            "taxonomy_codes": sorted(diagnostic_v3_1.RULE_TAXONOMY),
            "locator_states": list(diagnostic_v3_1.LOCATOR_STATES),
            "completeness_statements": list(diagnostic_v3_1.COMPLETENESS_FIELDS),
            "maximum_per_case": MAX_STRUCTURAL_REPAIRS_PER_CASE,
            "eligible_categories": list(REPAIR_ELIGIBLE_CATEGORIES),
            "repair_receives": ["SAME_PREPARED_INPUT", "UNCHANGED_PRIMARY_RESPONSE", "STRUCTURAL_DIAGNOSTIC_V3_1"],
            "diagnostic_rebuilt_and_compared_before_rendering": True,
        },
        "host_behaviour": superseded["host_behaviour"],
        "required_live_reporting": {"metrics": list(REQUIRED_LIVE_REPORTING), "acceptance_threshold": "NONE_DEFINED"},
        "runtime": superseded["runtime"],
    }


def candidate_sha256() -> str:
    return hashlib.sha256(canonical_json_bytes(candidate_definition())).hexdigest()


def assert_candidate_ready() -> dict[str, Any]:
    """Every offline gate of the candidate. Fails closed on any drift."""
    report = {"superseded_candidate_intact": superseded_candidate_intact()}
    try:
        report["schema_lineage"] = contract_v1.schema_lineage()
        report["quote_rule_coverage"] = contract_v1.quote_rule_coverage()
        report["registry_rule_coverage"] = contract_v1.registry_rule_coverage()
    except contract_v1.P41ContractError as error:
        raise P41ContractV11Error("A primary prompt gate failed") from error
    report["repair_prompt_coverage"] = repair_prompt_coverage()
    definition = candidate_definition()
    if not definition["primary_prompts_identical_to_superseded_candidate"]:
        raise P41ContractV11Error("The primary prompts differ from the M4-04B4D prompts")
    if hashlib.sha256(canonical_json_bytes(definition)).hexdigest() != CANDIDATE_SHA256:
        raise P41ContractV11Error("P4.1 V1.1 candidate differs from the locked candidate definition")
    return report


def main(argv: Optional[list[str]] = None) -> int:
    del argv
    try:
        assert_candidate_ready()
    except P41ContractV11Error as error:
        print(f"P4_1_V1_1_CANDIDATE_NOT_READY: {error}")
        return 2
    print(json.dumps({"candidate_id": CANDIDATE_ID, "candidate_sha256": CANDIDATE_SHA256,
                      "provider_operations": 0, "status": "P4_1_V1_1_CANDIDATE_OFFLINE_GATES_PASS"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
