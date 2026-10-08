"""P4.1 compiler-aware model-facing contract (M4-04B4D). Offline design only.

P4 gave the model the complete output schema, and every P4 response on DEV3 satisfied
it. Half of the cases were still rejected, by rules the frozen compiler and canonical
validator enforce beyond the schema. P4.1 states those rules to the model in words and
gives a repair a diagnostic it can act on (structural diagnostic V3).

P4.1 changes instructions and diagnostics only. The canonical schemas, the full model
schema, the provider projection, the compiler, the validator and the registry are the
accepted ones, unchanged. What counts as a valid canonical result does not change.

Two parts of the system prompt are generated, not hand-written, so they cannot drift:

- the quote-locator examples, whose match counts are computed by the frozen compiler's
  own matcher;
- the lists of constrained entity arguments and of derivation-rule conclusions, which
  are read from the frozen registry.

This module builds prompt text and checks coverage. It binds no model, credential,
runtime or operation budget, builds no request, calls no provider and reads no dataset.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Optional
import unicodedata

import yaml

from tools.canonical_story.conformance_v0 import load_registry
from tools.story_extraction import draft_compiler_v1 as compiler_v1
from tools.story_extraction import m4_04b4a_p4_output_contract_v1 as p4_contract
from tools.story_extraction import m4_04b4br_p4_protocol_v2 as protocol_v2
from tools.story_extraction import m4_04b4d_structural_diagnostic_v3 as diagnostic_v3
from tools.story_extraction import materialize_draft_v1_1_model_schema_v1 as materializer
from tools.story_extraction import project_draft_v1_1_model_schema_to_gemini_v1 as projection


TASK_ID = "M4-04B4D"
EXPECTED_BASE_COMMIT = "0d5d9ddcfe885a5b4e8a877b5c820f43a2d8b611"
CANDIDATE_ID = "P4_1_STORY_EXTRACTION_DRAFT_V1_1_COMPILER_AWARE_V1"
CANDIDATE_FORMAT = "M4_P4_1_CANDIDATE_DEFINITION_V1"
SUPERSEDES_EXTRACTOR_ID = p4_contract.P4_EXTRACTOR_ID
# SHA-256 of canonical_json_bytes(candidate_definition()). A changed binding is a new candidate.
CANDIDATE_SHA256 = "f016306647b48bf9b9dd6c7531a49c5e5775d8d9c7c760a54406e1035db218a8"
CONTRACT_PATH = "tools/story_extraction/m4_04b4d_p4_1_compiler_aware_contract_v1.py"
REPO_ROOT = materializer.REPO_ROOT

PROMPT_ROOT = REPO_ROOT / "tools/story_extraction/prompts"
SYSTEM_PREAMBLE_PATH = PROMPT_ROOT / "story_extraction_draft_p4_1_v1_system.txt"
USER_TEMPLATE_PATH = PROMPT_ROOT / "story_extraction_draft_p4_1_v1_user.txt"
REPAIR_USER_TEMPLATE_PATH = PROMPT_ROOT / "story_extraction_draft_p4_1_v1_repair_user.txt"
PROMPT_FILES = (SYSTEM_PREAMBLE_PATH, USER_TEMPLATE_PATH, REPAIR_USER_TEMPLATE_PATH)
EXAMPLES_MARKER = "{QUOTE_LOCATOR_EXAMPLES}"
CONSTRAINTS_MARKER = "{REGISTRY_DERIVED_CONSTRAINTS}"
SCHEMA_SECTION_MARKER = p4_contract.SCHEMA_SECTION_MARKER
REGISTRY_SECTION_MARKER = p4_contract.REGISTRY_SECTION_MARKER

FULL_MODEL_SCHEMA_SHA256 = "5aa2ed6dde3791546ddd5e059648d8dac38df1571a6073b7abc31c89eb257f14"
PROVIDER_PROJECTION_SHA256 = "89506defa4089b1449f7c80bbcf782d94065802ceae71aa86e1598a5a17ab9bd"
# The registry these rule explanations were reviewed against. A changed registry fails closed.
REVIEWED_REGISTRY_SHA256 = "44f3eafc6982f84bcc74ccb91abe7cd467a453352ee96be147095f27559c5350"
REPAIR_ELIGIBLE_CATEGORIES = ("JSON_PARSE_FAILURE", "DRAFT_SCHEMA_FAILURE", "DRAFT_COMPILER_FAILURE")
MAX_STRUCTURAL_REPAIRS_PER_CASE = 1

REPAIR_SYSTEM_SUFFIX = """
STRUCTURAL REPAIR MODE
The host rejected the primary response. Correct every finding of the structural
diagnostic V3 supplied by the host and change nothing else. A finding names the rule
that was broken and, where the host could verify it, the record. It never states what
the story content should be. Do not fill coverage gaps, optimize quality, consult gold,
or introduce a new interpretation. This is the only repair for the case.
""".strip()

_E_ACUTE, _COMBINING_ACUTE = chr(0xE9), chr(0x301)
# Invented text only. label, passage, quote, note. Counts are computed, never typed.
QUOTE_EXAMPLES = (
    ("A", "The lamp is on the desk.", "lamp", "occurrence may be omitted."),
    ("B", "Rin met Rin at noon.", "Rin",
     "occurrence is required: 1 cites the first match and 2 cites the second."),
    ("C", "no, no, no", "no", "occurrence is required and is 1, 2 or 3."),
    ("D", "aaaa", "aa", "The matches overlap and all of them count. occurrence is required."),
    ("E", "caf" + _E_ACUTE + " menu", "cafe" + _COMBINING_ACUTE,
     "The passage has the single code point U+00E9. The quote has e followed by U+0301. They look the same "
     "and are not equal. Copy the code points of the passage."),
    ("F", "x + x = y", "x", "The quote is one code point. occurrence is required."),
    ("G", "on the desk, on the shelf", "on the", "The quote is several code points. occurrence is required."),
)
REQUIRED_EXAMPLE_PROPERTIES = (
    "QUOTE_OCCURS_ONCE", "QUOTE_OCCURS_TWICE", "QUOTE_OCCURS_THREE_TIMES", "OVERLAPPING_MATCHES",
    "UNICODE_EXACT_MATCHING", "QUOTE_OF_ONE_CODE_POINT", "QUOTE_OF_SEVERAL_CODE_POINTS",
)

# Statements the prompt must make, checked on its whitespace-normalized text.
QUOTE_RULE_STATEMENTS = {
    "exact_code_point_matching": "exact code-point substring matching",
    "no_normalization": "Nothing is normalized",
    "overlapping_matches_count": "Matches may overlap and every match counts",
    "zero_matches_rejected": "If the count is 0, the locator is rejected",
    "one_match_occurrence_optional": "If the count is 1, occurrence may be omitted",
    "repeated_quote_requires_occurrence": "If the count is 2 or more, occurrence is required",
    "occurrence_is_one_based_index_of_matches": "occurrence is the 1-based index, in reading order, of the match",
    "occurrence_within_count": "It must not exceed the count",
    "occurrence_is_the_intended_match": "Give the index of the match you actually mean",
    "no_default_occurrence": "Do not give 1 merely to satisfy the rule",
    "applies_to_mentions_and_evidence": "Do this for every mention and for every evidence record",
    "short_quotes_repeat": "Short quotes, such as one character, a pronoun, a name or a common word",
    "occurrence_is_not_an_offset": "It is not a source offset",
    "no_host_metadata": "Never output offsets, positions or any other host-owned metadata",
    "eligible_passages_only": "may cite only EVIDENCE_ELIGIBLE passages",
}
ENTITY_KIND_RULE_STATEMENTS = {
    "argument_kind_and_entity_kind_are_separate": "That is a second, separate constraint",
    "type_correct_handle_can_still_violate": "A type-correct entity handle can still break it",
    "check_before_emitting": "check every such argument against the kind of the entity it references",
    "registry_values_only": "Use the registry's values. Never guess them",
    "registry_field_named": "entity_kinds in the registry",
}
DERIVATION_RULE_STATEMENTS = {
    "rule_limits_the_conclusion_predicate": "a predicate listed in that rule's conclusion_predicates",
    "registered_rule_id_not_sufficient": "A registered rule_id is not sufficient",
    "valid_premises_not_sufficient": "valid premise handles are not sufficient",
    "no_rule_no_derivation": "If no registered rule can conclude the predicate, do not attach that derivation",
}
PROPOSITION_RULE_STATEMENTS = {
    "identical_content_rejected": "Two concrete propositions with identical content are rejected",
    "identity_definition": "the predicate is the same and, for every argument name, the kind is the same",
    "emit_once": "Emit such a proposition once",
    "assertions_may_share_a_proposition": "Several assertions may cite the same proposition handle",
    "reuse_existing_proposition": "reuse its PROP_EXISTING handle and do not emit it again",
    "distinct_propositions_kept": "Propositions that differ in the predicate or in any argument are distinct. Keep them",
    "similarity_is_not_identity": "Similar meaning is not identical content",
    "placeholders_never_duplicate": "Placeholder propositions are never duplicates of each other",
}
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
}
# Wordings that would tell the model to take a default occurrence. None may appear in any prompt.
FORBIDDEN_DEFAULT_OCCURRENCE = (
    r"(?:use|set|choose|pick|give|add|default to) occurrence(?: to| of| =|:)? 1\b",
    r"occurrence(?: to| of| =|:) 1 (?:by default|when unsure|if unsure|otherwise)",
    r"(?:pick|choose|take|use) the first (?:match|occurrence)",
    r"default(?:s)? to the first",
)


class P41ContractError(RuntimeError):
    """The P4.1 prompt, a coverage gate or a frozen binding does not hold. Fail closed."""


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeError) as error:
        raise P41ContractError("Prompt file is unavailable: " + path.name) from error


def _flat(text: str) -> str:
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Generated prompt sections
# ---------------------------------------------------------------------------

def exact_match_count(passage: str, quote: str) -> int:
    """Exact matches as the frozen compiler counts them: overlapping, never normalized."""
    return len(compiler_v1._occurrences(passage, quote))


def example_properties(passage: str, quote: str) -> set[str]:
    """What an example demonstrates, decided from the strings themselves."""
    count = exact_match_count(passage, quote)
    properties = {{1: "QUOTE_OCCURS_ONCE", 2: "QUOTE_OCCURS_TWICE", 3: "QUOTE_OCCURS_THREE_TIMES"}.get(count, "OTHER_COUNT")}
    if count > passage.count(quote):
        properties.add("OVERLAPPING_MATCHES")
    normalized = exact_match_count(unicodedata.normalize("NFC", passage), unicodedata.normalize("NFC", quote))
    if normalized != count:
        properties.add("UNICODE_EXACT_MATCHING")
    properties.add("QUOTE_OF_ONE_CODE_POINT" if len(quote) == 1 else "QUOTE_OF_SEVERAL_CODE_POINTS")
    return properties


def quote_examples_text() -> str:
    lines = []
    for label, passage, quote, note in QUOTE_EXAMPLES:
        count = exact_match_count(passage, quote)
        lines.append(
            f"  {label}. passage {json.dumps(passage, ensure_ascii=True)}, quote {json.dumps(quote, ensure_ascii=True)}: "
            f"exact match count {count}. {note}"
        )
    return "\n".join(lines)


def entity_kind_constraints() -> list[tuple[str, str, tuple[str, ...]]]:
    """Every registry argument that restricts the kind of the entity it references. Registry order."""
    registry = load_registry()
    return [(predicate, argument["name"], tuple(argument["entity_kinds"]))
            for predicate, spec in registry["predicates"].items()
            for argument in spec["args"] if argument.get("entity_kinds")]


def derivation_conclusion_constraints() -> list[tuple[str, tuple[str, ...]]]:
    """Every registry derivation rule with the predicates it may conclude. Registry order."""
    registry = load_registry()
    return [(rule_id, tuple(rule["conclusion_predicates"]))
            for rule_id, rule in registry["derivation_rules"].items() if rule.get("conclusion_predicates")]


def registry_constraints_text() -> str:
    lines = ["  Arguments whose referenced entity must have one of the listed kinds",
             "  (predicate.argument: entity_kinds):"]
    lines += [f"  - {predicate}.{argument}: {', '.join(kinds)}" for predicate, argument, kinds in entity_kind_constraints()]
    lines += ["  Derivation rules and the predicates they may conclude",
              "  (rule_id: conclusion_predicates):"]
    lines += [f"  - {rule_id}: {', '.join(predicates)}" for rule_id, predicates in derivation_conclusion_constraints()]
    return "\n".join(lines)


def _fill(template: str, replacements: Mapping[str, str]) -> str:
    rendered = template
    for marker, value in replacements.items():
        if rendered.count(marker) != 1:
            raise P41ContractError("Prompt marker missing or repeated: " + marker)
        rendered = rendered.replace(marker, value)
    return rendered


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

def system_preamble() -> str:
    """The instruction text with its two generated sections filled in. No schema or registry yet."""
    return _fill(_text(SYSTEM_PREAMBLE_PATH).rstrip(), {
        EXAMPLES_MARKER: quote_examples_text(), CONSTRAINTS_MARKER: registry_constraints_text(),
    })


def prompt_material() -> dict[str, str]:
    """The exact P4.1 prompt texts. Schema and registry sections are assembled exactly as in P4."""
    schema = materializer.load_tracked_model_schema()
    system = (
        system_preamble()
        + "\n\n" + SCHEMA_SECTION_MARKER + "\n" + materializer.model_schema_text(schema).rstrip()
        + "\n\n" + REGISTRY_SECTION_MARKER + "\n" + _text(p4_contract.PREDICATE_REGISTRY_PATH).rstrip()
    )
    return {
        "primary_system": system,
        "primary_user_template": _text(USER_TEMPLATE_PATH).rstrip() + "\n",
        "repair_system": system + "\n\n" + REPAIR_SYSTEM_SUFFIX,
        "repair_user_template": _text(REPAIR_USER_TEMPLATE_PATH).rstrip() + "\n",
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


def _case_id(case_id: Any) -> str:
    if not isinstance(case_id, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,39}", case_id):
        raise P41ContractError("Case id is not a valid case identifier")
    return case_id


def render_primary_user(case_id: str, prepared_input: Mapping[str, Any]) -> str:
    if not isinstance(prepared_input, Mapping) or prepared_input.get("draft_version") != materializer.CANONICAL_DRAFT_VERSION:
        raise P41ContractError("Prepared input is not Draft V1.1")
    return _fill(prompt_material()["primary_user_template"], {
        "{CASE_ID}": _case_id(case_id), "{PREPARED_INPUT_JSON}": p4_contract.canonical_json(prepared_input),
    })


def render_repair_user(
    case_id: str, prepared_input: Mapping[str, Any], primary_response: str, diagnostic: Mapping[str, Any]
) -> str:
    """The repair request: the same prepared input, the unchanged primary response and diagnostic V3."""
    if (
        not isinstance(diagnostic, Mapping)
        or tuple(diagnostic) != diagnostic_v3.ENVELOPE_FIELDS
        or diagnostic["diagnostic"] != diagnostic_v3.DIAGNOSTIC_ID
        or diagnostic["category"] not in REPAIR_ELIGIBLE_CATEGORIES
        or not diagnostic["findings"]
        or diagnostic["finding_count"] != len(diagnostic["findings"])
    ):
        raise P41ContractError("Repair requires a structural diagnostic V3 with an eligible category and findings")
    if not isinstance(primary_response, str) or not primary_response:
        raise P41ContractError("Repair requires one successful primary response")
    if not isinstance(prepared_input, Mapping) or prepared_input.get("draft_version") != materializer.CANONICAL_DRAFT_VERSION:
        raise P41ContractError("Prepared input is not Draft V1.1")
    return _fill(prompt_material()["repair_user_template"], {
        "{CASE_ID}": _case_id(case_id),
        "{PREPARED_INPUT_JSON}": p4_contract.canonical_json(prepared_input),
        "{STRUCTURAL_DIAGNOSTIC_JSON}": p4_contract.canonical_json(diagnostic),
        "{PRIMARY_RESPONSE}": primary_response,
    })


# ---------------------------------------------------------------------------
# Coverage gates
# ---------------------------------------------------------------------------

def _statements(text: str, statements: Mapping[str, str]) -> dict[str, bool]:
    flat = _flat(text)
    return {name: _flat(phrase) in flat for name, phrase in statements.items()}


def quote_rule_coverage() -> dict[str, Any]:
    """The prompt states the frozen matcher's rules and shows every required kind of example."""
    preamble = system_preamble()
    examples = []
    for label, passage, quote, _ in QUOTE_EXAMPLES:
        examples.append({"label": label, "exact_match_count": exact_match_count(passage, quote),
                         "demonstrates": sorted(example_properties(passage, quote))})
    shown = {name for example in examples for name in example["demonstrates"]}
    statements = _statements(preamble, QUOTE_RULE_STATEMENTS)
    rendered = quote_examples_text()
    report = {
        "statements": statements,
        "examples": examples,
        "required_example_properties": {name: name in shown for name in REQUIRED_EXAMPLE_PROPERTIES},
        "examples_rendered_in_prompt": rendered in preamble,
        "example_counts_computed_by_the_frozen_matcher": True,
        "automatic_occurrence_selection": "FORBIDDEN",
    }
    if not (all(statements.values()) and all(report["required_example_properties"].values())
            and report["examples_rendered_in_prompt"]):
        raise P41ContractError("Quote-locator rule coverage is incomplete")
    return report


def registry_rule_coverage() -> dict[str, Any]:
    """Every entity-kind restriction and every rule conclusion restriction of the registry is covered."""
    if protocol_v2.normalized_file_sha256(p4_contract.PREDICATE_REGISTRY_PATH) != REVIEWED_REGISTRY_SHA256:
        raise P41ContractError("The predicate registry changed; the P4.1 rule explanations need review")
    material = prompt_material()
    system, preamble = material["primary_system"], system_preamble()
    registry = load_registry()
    in_prompt = yaml.safe_load(system.split(REGISTRY_SECTION_MARKER, 1)[1])
    entity = entity_kind_constraints()
    derivation = derivation_conclusion_constraints()
    entity_lines = {f"{predicate}.{argument}": f"- {predicate}.{argument}: {', '.join(kinds)}" in preamble
                    for predicate, argument, kinds in entity}
    derivation_lines = {rule_id: f"- {rule_id}: {', '.join(predicates)}" in preamble
                        for rule_id, predicates in derivation}
    report = {
        "registry_sha256": REVIEWED_REGISTRY_SHA256,
        "registry_in_prompt_equals_frozen_registry": in_prompt == registry,
        "entity_kind_constraints": {
            "registry_arguments_with_a_restriction": len(entity),
            "covered_by_the_generated_list": sum(entity_lines.values()),
            "arguments": entity_lines,
            "statements": _statements(preamble, ENTITY_KIND_RULE_STATEMENTS),
        },
        "derivation_conclusion_constraints": {
            "registry_rules_with_a_restriction": len(derivation),
            "registry_rules_total": len(registry["derivation_rules"]),
            "covered_by_the_generated_list": sum(derivation_lines.values()),
            "rules": derivation_lines,
            "statements": _statements(preamble, DERIVATION_RULE_STATEMENTS),
        },
        "duplicate_proposition_rule": {"statements": _statements(preamble, PROPOSITION_RULE_STATEMENTS)},
        "generated_from_the_registry_not_hand_maintained": True,
    }
    complete = (
        report["registry_in_prompt_equals_frozen_registry"]
        and entity and all(entity_lines.values())
        and derivation and all(derivation_lines.values())
        and all(report["entity_kind_constraints"]["statements"].values())
        and all(report["derivation_conclusion_constraints"]["statements"].values())
        and all(report["duplicate_proposition_rule"]["statements"].values())
    )
    if not complete:
        raise P41ContractError("Registry rule coverage is incomplete")
    return report


def repair_prompt_coverage() -> dict[str, Any]:
    """The repair prompt explains every code V3 can emit for the model to act on, and every field."""
    material = prompt_material()
    template = material["repair_user_template"]
    repairable = sorted(code for code, rule in diagnostic_v3.RULE_TAXONOMY.items() if rule[4])
    codes = {code: re.search(r"\b" + re.escape(code) + r"\b", template) is not None for code in repairable}
    fields = {name: name in template for name in (
        "phase", "code", "rule_class", "source", "compiler_reached", "repairable_by_model", "record_collection",
        "record_index", "record_handle", "schema_path", "validator_check", "validator_section", "structural_detail",
        "complete", "limitations")}
    fields["every_finding_field"] = all(name in template for name in diagnostic_v3.FINDING_FIELDS)
    fields["both_finding_sources"] = all(name in template for name in (
        "FROZEN_COMPILER_BLOCKER", "INDEPENDENT_REGISTRY_CHECK"))
    everything = "\n".join(material.values())
    forbidden = {pattern: re.search(pattern, _flat(everything), re.IGNORECASE) is None
                 for pattern in FORBIDDEN_DEFAULT_OCCURRENCE}
    statements = _statements(template, REPAIR_RULE_STATEMENTS)
    report = {
        "diagnostic": diagnostic_v3.DIAGNOSTIC_ID,
        "codes_repairable_by_the_model": len(repairable),
        "codes_explained": codes,
        "finding_fields_explained": fields,
        "statements": statements,
        "no_default_occurrence_wording_in_any_prompt": all(forbidden.values()),
        "maximum_repairs_per_case": MAX_STRUCTURAL_REPAIRS_PER_CASE,
    }
    if not (all(codes.values()) and all(fields.values()) and all(statements.values()) and all(forbidden.values())):
        raise P41ContractError("Repair prompt coverage is incomplete")
    return report


def schema_lineage() -> dict[str, str]:
    """The prompt carries the accepted full model schema; the native projection is the accepted one."""
    system = prompt_material()["primary_system"]
    in_prompt = p4_contract.extract_prompt_schema(system, SCHEMA_SECTION_MARKER, REGISTRY_SECTION_MARKER)
    full = materializer.load_tracked_model_schema()
    try:
        native = projection.load_tracked_projection()
        projection.lineage_gate()
    except (projection.ProjectionError, materializer.ModelSchemaError) as error:
        raise P41ContractError("Provider projection lineage failed") from error
    if not (in_prompt == full == materializer.materialize_model_schema()):
        raise P41ContractError("Prompt schema is not the full model schema")
    if materializer.model_schema_sha256() != FULL_MODEL_SCHEMA_SHA256:
        raise P41ContractError("Full model schema differs from the accepted schema")
    if projection.projection_sha256() != PROVIDER_PROJECTION_SHA256 or native == full:
        raise P41ContractError("Provider projection differs from the accepted projection")
    if EXAMPLES_MARKER in system or CONSTRAINTS_MARKER in system:
        raise P41ContractError("A generated prompt section was not filled in")
    p4_contract.assert_prompt_coverage(system)
    return {
        "prompt_schema_equals_full_model_schema": "PASS",
        "full_model_schema_sha256": "PASS",
        "provider_projection_sha256": "PASS",
        "provider_projection_lineage": "PASS",
        "prompt_structural_coverage_of_the_schema": "PASS",
        "generated_sections_filled": "PASS",
        "new_semantic_draft_version": "NONE",
    }


# ---------------------------------------------------------------------------
# Candidate definition
# ---------------------------------------------------------------------------

def candidate_definition() -> dict[str, Any]:
    """What P4.1 is. An offline candidate: no model, credential, runtime or budget is bound."""
    bound = protocol_v2.BOUND_FILES
    return {
        "candidate_id": CANDIDATE_ID,
        "format": CANDIDATE_FORMAT,
        "task_id": TASK_ID,
        "base_commit": EXPECTED_BASE_COMMIT,
        "supersedes_extractor": SUPERSEDES_EXTRACTOR_ID,
        "change": "MODEL_FACING_INSTRUCTIONS_AND_REPAIR_DIAGNOSTIC_ONLY",
        "canonical_draft_contract": materializer.CANONICAL_DRAFT_VERSION,
        "model_schema": {"identity": materializer.MODEL_SCHEMA_IDENTITY, "sha256": FULL_MODEL_SCHEMA_SHA256,
                         "changed": False},
        "provider_projection": {"identity": projection.PROJECTION_IDENTITY, "sha256": PROVIDER_PROJECTION_SHA256,
                                "changed": False},
        "frozen": {
            "predicate_registry_sha256": REVIEWED_REGISTRY_SHA256,
            "compiler_v1_1_sha256": bound["tools/story_extraction/draft_compiler_v1_1.py"],
            "compiler_v1_sha256": bound["tools/story_extraction/draft_compiler_v1.py"],
            "canonical_draft_v1_1_schema_sha256": bound["schemas/story_extraction/story_extraction_draft_v1_1.schema.json"],
            "canonical_draft_v1_schema_sha256": bound["schemas/story_extraction/story_extraction_draft_v1.schema.json"],
            "acceptance_authority": "UNCHANGED_COMPILER_AND_CANONICAL_VALIDATOR",
        },
        "prompt_hashes": prompt_hashes(),
        "prompt_files": {path.relative_to(REPO_ROOT).as_posix(): protocol_v2.normalized_file_sha256(path)
                         for path in PROMPT_FILES},
        "generated_prompt_sections": {
            "quote_locator_examples_sha256": sha256_text(quote_examples_text()),
            "registry_derived_constraints_sha256": sha256_text(registry_constraints_text()),
            "repair_system_suffix_sha256": sha256_text(REPAIR_SYSTEM_SUFFIX),
        },
        "repair": {
            "diagnostic": diagnostic_v3.DIAGNOSTIC_ID,
            "diagnostic_format": diagnostic_v3.DIAGNOSTIC_FORMAT,
            "diagnostic_tool_sha256": protocol_v2.normalized_file_sha256(REPO_ROOT / diagnostic_v3.DIAGNOSTIC_PATH),
            "taxonomy_codes": sorted(diagnostic_v3.RULE_TAXONOMY),
            "maximum_per_case": MAX_STRUCTURAL_REPAIRS_PER_CASE,
            "eligible_categories": list(REPAIR_ELIGIBLE_CATEGORIES),
            "repair_receives": ["SAME_PREPARED_INPUT", "UNCHANGED_PRIMARY_RESPONSE", "STRUCTURAL_DIAGNOSTIC_V3"],
        },
        "host_behaviour": {
            "automatic_occurrence_selection": "FORBIDDEN",
            "host_rewrites_model_output": False,
            "fuzzy_or_semantic_deduplication": "FORBIDDEN",
            "canonical_acceptance_standard_lowered": False,
        },
        "runtime": {
            "live_protocol_bound": False, "model_bound": False, "credential_bound": False,
            "operation_budget_bound": False, "live_runner": "NOT_CREATED",
        },
    }


def candidate_sha256() -> str:
    return hashlib.sha256(canonical_json_bytes(candidate_definition())).hexdigest()


def assert_candidate_ready() -> dict[str, Any]:
    """Every offline gate of the candidate. Fails closed on any drift."""
    try:
        protocol_v2.locked_protocol()
    except (protocol_v2.P4ProtocolV2Error, protocol_v2.protocol_v1.P4ProtocolError) as error:
        raise P41ContractError("A frozen P4 binding changed") from error
    report = {
        "schema_lineage": schema_lineage(),
        "quote_rule_coverage": quote_rule_coverage(),
        "registry_rule_coverage": registry_rule_coverage(),
        "repair_prompt_coverage": repair_prompt_coverage(),
    }
    if candidate_sha256() != CANDIDATE_SHA256:
        raise P41ContractError("P4.1 candidate differs from the locked candidate definition")
    return report


def main(argv: Optional[list[str]] = None) -> int:
    del argv
    try:
        assert_candidate_ready()
    except P41ContractError as error:
        print(f"P4_1_CANDIDATE_NOT_READY: {error}")
        return 2
    print(json.dumps({"candidate_id": CANDIDATE_ID, "candidate_sha256": CANDIDATE_SHA256,
                      "provider_operations": 0, "status": "P4_1_CANDIDATE_OFFLINE_GATES_PASS"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
