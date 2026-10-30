"""Offline identity of the P4 STORY_EXTRACTION_DRAFT_V1_2 extractor candidate.

Materializes prompts, request specifications, the candidate definition and an
environment record. It never opens a dataset, loads credentials, builds a transport or
performs provider work. Model and generation settings are unchanged from P2/P3.
"""
from __future__ import annotations

from importlib import metadata
import platform
import sys
from typing import Any, Mapping

from tools.story_extraction.draft_compiler_v1_2 import DRAFT_VERSION, SCHEMA_PATH
from tools.story_extraction.durable_research_executor_v1 import DurableJobSpec
from tools.story_extraction.m4_draft_v1_1_candidate_p3_v1 import (
    CASE_ID_PATTERN,
    CONCURRENCY,
    CREDENTIAL_SLOT,
    CREDENTIAL_TOPOLOGY,
    DURABLE_PROFILE_ID,
    DURABLE_PROFILE_SHA256,
    FORBIDDEN_ARCHIVE_SHA256,
    GENERATION_CONFIG,
    GLOBAL_MAX_PROVIDER_OPERATIONS,
    GLOBAL_ROLLING_WINDOW_SECONDS,
    MAX_OUTPUT_TOKENS,
    MAX_PROVIDER_ATTEMPTS_PER_JOB,
    MAX_PROVIDER_ATTEMPTS_PER_WINDOW,
    MAX_WINDOWS_PER_JOB,
    MODEL,
    REPO_ROOT,
    RUNTIME_VERSION,
    TEMPERATURE,
    WINDOW_COOLDOWN_SECONDS,
    CandidateError,
    _feedback_keys,
    _FORBIDDEN_FEEDBACK_KEYS,
    _normalized_text,
    _render,
    canonical_json_bytes,
    file_hash_record,
    sha256_bytes,
    sha256_text,
)


TASK_ID = "M4-04B4C-DRAFT-V1-2-GROUNDED-EXTRACTION"
CANDIDATE_ID = "P4_STORY_EXTRACTION_DRAFT_V1_2_GEMINI_3_5_FLASH_LITE_V1"
CANDIDATE_MANIFEST_ID = "M4_04B4C_DRAFT_V1_2_CANDIDATE_MANIFEST_V1"
HASH_POLICY = "M4_CROSS_PLATFORM_CONTENT_HASH_V1"
SCHEMA_RESPONSE_MODE = "PROVIDER_JSON_MIME_STORY_EXTRACTION_DRAFT_V1_2"
DURABLE_EXECUTOR_VERSION = "DURABLE_RESEARCH_EXECUTOR_V1"
REPAIR_ELIGIBLE_CATEGORIES = ("JSON_PARSE_FAILURE", "DRAFT_SCHEMA_FAILURE",
                              "DRAFT_COMPILER_FAILURE")
MAX_STRUCTURAL_REPAIRS_PER_CASE = 1

PROMPT_ROOT = REPO_ROOT / "tools/story_extraction/prompts"
SYSTEM_PREAMBLE_PATH = PROMPT_ROOT / "story_extraction_draft_p4_system_v1_2.txt"
USER_TEMPLATE_PATH = PROMPT_ROOT / "story_extraction_draft_p4_user_v1_2.txt"
REPAIR_USER_TEMPLATE_PATH = PROMPT_ROOT / "story_extraction_draft_p4_repair_user_v1_2.txt"
PREDICATE_REGISTRY_PATH = REPO_ROOT / "schemas/canonical_story/predicate_registry_v0.yaml"
REPAIR_SYSTEM_SUFFIX = """

STRUCTURAL REPAIR MODE
Repair only the sanitized deterministic blockers supplied by the host. Preserve semantic
choices from the primary response. Do not fill coverage gaps, optimize quality, consult
gold, or introduce a new interpretation. This is the only repair allowed for the case.
""".strip()

# Runtime path of the V1.2 runner and compiler.
RUNTIME_FILES: tuple[tuple[str, str], ...] = (
    ("draft_schema_v1_2", "schemas/story_extraction/story_extraction_draft_v1_2.schema.json"),
    ("draft_schema_v1_1_backend", "schemas/story_extraction/story_extraction_draft_v1_1.schema.json"),
    ("draft_schema_v1_backend", "schemas/story_extraction/story_extraction_draft_v1.schema.json"),
    ("predicate_registry", "schemas/canonical_story/predicate_registry_v0.yaml"),
    ("canonical_schema", "schemas/canonical_story/canonical_story_v0.schema.json"),
    ("batch_schema", "schemas/story_extraction/story_extraction_batch_v0.schema.json"),
    ("anchor_resolver", "tools/story_extraction/contextual_anchor_resolver_v1.py"),
    ("compiler_v1_2", "tools/story_extraction/draft_compiler_v1_2.py"),
    ("compiler_v1_1_backend", "tools/story_extraction/draft_compiler_v1_1.py"),
    ("compiler_v1_backend", "tools/story_extraction/draft_compiler_v1.py"),
    ("conformance_diagnostics", "tools/story_extraction/draft_v1_1_conformance_diagnostics_v1.py"),
    ("batch_contract", "tools/story_extraction/extraction_contract_v0.py"),
    ("batch_guard", "tools/story_extraction/extraction_contract_guard_v1.py"),
    ("canonical_conformance", "tools/canonical_story/conformance_v0.py"),
    ("m3_adapter", "tools/story_ingestion/light_novel_adapter_v0.py"),
    ("prompt_system", "tools/story_extraction/prompts/story_extraction_draft_p4_system_v1_2.txt"),
    ("prompt_user", "tools/story_extraction/prompts/story_extraction_draft_p4_user_v1_2.txt"),
    ("prompt_repair_user",
     "tools/story_extraction/prompts/story_extraction_draft_p4_repair_user_v1_2.txt"),
    ("candidate_module", "tools/story_extraction/m4_draft_v1_2_candidate_p4_v1.py"),
    ("candidate_p3_shared_helpers", "tools/story_extraction/m4_draft_v1_1_candidate_p3_v1.py"),
    ("schema_bundle_v1_1_imported_by_p3", "tools/story_extraction/draft_v1_1_schema_bundle_v1.py"),
    ("runner_v1_2", "tools/story_extraction/run_m4_draft_v1_2_predictions_v1.py"),
    ("runner_v1_1_shared_helpers", "tools/story_extraction/run_m4_draft_v1_1_predictions_v1.py"),
    ("durable_executor", "tools/story_extraction/durable_research_executor_v1.py"),
    ("evaluation_snapshot_v2", "benchmarks/m4_extraction/M4_EVALUATION_PROTOCOL_SNAPSHOT_V2.yaml"),
)
# Not loaded while live execution is disabled; bound because any future live run uses
# them to classify provider failures and to construct the accepted window transport.
LIVE_PATH_FILES: tuple[tuple[str, str], ...] = (
    ("runtime", "tools/story_extraction/gemini_resilience_v1_1.py"),
    ("runtime_v1_base", "tools/story_extraction/gemini_resilience_v1.py"),
    ("provider_error_classification", "tools/story_extraction/gemini_errors_v1.py"),
    ("gemini_transport", "tools/story_extraction/gemini_transport_v1.py"),
    ("gemini_key_pool", "tools/story_extraction/gemini_key_pool_v1.py"),
    ("live_window_transport", "tools/story_extraction/run_m4_04b2_dev_predictions_v1.py"),
    ("live_window_transport_constants", "tools/story_extraction/m4_04b2_dev_protocol_v1.py"),
)
# Offline development tooling bound for reproducibility of reported results.
TOOLING_FILES: tuple[tuple[str, str], ...] = (
    ("oracle_projection", "tools/story_extraction/draft_v1_2_oracle_projection_v1.py"),
    ("oracle_projection_v1_base", "tools/story_extraction/draft_coverage_v1.py"),
)
ENVIRONMENT_DISTRIBUTIONS = ("jsonschema", "jsonschema-specifications", "referencing",
                             "rpds-py", "PyYAML", "attrs", "google-genai")
ENVIRONMENT_REQUIREMENTS = {"python": ">=3.13", "jsonschema": ">=4.18,<5",
                            "PyYAML": ">=6.0,<7", "google-genai": ">=2.27,<3.0 (live path only)"}


def prompt_material() -> dict[str, str]:
    """P4 prompts with the self-contained V1.2 schema and the exact registry."""
    system = (
        _normalized_text(SYSTEM_PREAMBLE_PATH)
        + "\n\nEXACT STORY_EXTRACTION_DRAFT_V1_2 JSON SCHEMA:\n"
        + _normalized_text(SCHEMA_PATH)
        + "\n\nEXACT PREDICATE REGISTRY:\n"
        + _normalized_text(PREDICATE_REGISTRY_PATH)
    )
    return {
        "primary_system": system,
        "primary_user_template": _normalized_text(USER_TEMPLATE_PATH) + "\n",
        "repair_system": system + "\n\n" + REPAIR_SYSTEM_SUFFIX,
        "repair_user_template": _normalized_text(REPAIR_USER_TEMPLATE_PATH) + "\n",
    }


def prompt_hashes() -> dict[str, str]:
    material = prompt_material()
    return {
        "primary_system_sha256": sha256_text(material["primary_system"]),
        "primary_user_template_sha256": sha256_text(material["primary_user_template"]),
        "repair_system_sha256": sha256_text(material["repair_system"]),
        "repair_user_template_sha256": sha256_text(material["repair_user_template"]),
    }


def _check_case(case_id: str, prepared_input: Mapping[str, Any]) -> None:
    if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id):
        raise CandidateError("Case id does not match the candidate case-id pattern")
    if prepared_input.get("draft_version") != DRAFT_VERSION:
        raise CandidateError("Prepared input is not Draft V1.2")
    if set(prepared_input) != {"draft_version", "passages", "existing_context"}:
        raise CandidateError("Prepared input has unexpected fields")


def _spec(job_id: str, system: str, user: str, research_task_id: str) -> DurableJobSpec:
    return DurableJobSpec(job_id=job_id, model=MODEL, system_prompt=system, user_prompt=user,
                          generation_config=dict(GENERATION_CONFIG),
                          schema_response_mode=SCHEMA_RESPONSE_MODE,
                          credential_slot=CREDENTIAL_SLOT, research_task_id=research_task_id)


def build_primary_spec(case_id: str, prepared_input: Mapping[str, Any],
                       research_task_id: str) -> DurableJobSpec:
    _check_case(case_id, prepared_input)
    material = prompt_material()
    user = _render(material["primary_user_template"], {
        "CASE_ID": case_id,
        "PREPARED_INPUT_JSON": canonical_json_bytes(prepared_input).decode("utf-8").rstrip(),
    })
    return _spec(f"P4V12_{case_id}_PRIMARY", material["primary_system"], user, research_task_id)


def build_repair_spec(case_id: str, prepared_input: Mapping[str, Any], primary_response: str,
                      failure: Mapping[str, Any], research_task_id: str) -> DurableJobSpec:
    if failure.get("category") not in REPAIR_ELIGIBLE_CATEGORIES:
        raise CandidateError("Repair category is not eligible")
    if _feedback_keys(dict(failure)) & _FORBIDDEN_FEEDBACK_KEYS:
        raise CandidateError("Repair feedback contains a forbidden quality or gold signal")
    if not isinstance(primary_response, str) or not primary_response:
        raise CandidateError("Repair requires one received primary response")
    _check_case(case_id, prepared_input)
    material = prompt_material()
    user = _render(material["repair_user_template"], {
        "CASE_ID": case_id,
        "PREPARED_INPUT_JSON": canonical_json_bytes(prepared_input).decode("utf-8").rstrip(),
        "PRIMARY_RESPONSE": primary_response,
        "FAILURE_JSON": canonical_json_bytes(dict(failure)).decode("utf-8").rstrip(),
    })
    return _spec(f"P4V12_{case_id}_REPAIR_1", material["repair_system"], user,
                 research_task_id)


def estimated_job_tokens(spec: DurableJobSpec) -> int:
    """Conservative upper bound: one token per prompt code point plus the output cap."""
    return len(spec.system_prompt) + len(spec.user_prompt) + MAX_OUTPUT_TOKENS


def _files(entries: tuple[tuple[str, str], ...]) -> dict[str, dict[str, str]]:
    out = {}
    for name, relative in entries:
        record = file_hash_record(REPO_ROOT / relative)
        out[name] = {"path": relative, "content_sha256_lf": record["content_sha256_lf"],
                     "git_blob_sha1_lf": record["git_blob_sha1_lf"]}
    return out


def candidate_definition() -> dict[str, Any]:
    """Checkout-independent identity; environment observations are kept separately."""
    return {
        "candidate_id": CANDIDATE_ID,
        "draft_version": DRAFT_VERSION,
        "hash_policy": HASH_POLICY,
        "generation": {
            "concurrency": CONCURRENCY, "credential_slot": CREDENTIAL_SLOT,
            "credential_topology": CREDENTIAL_TOPOLOGY, "json_mode": True,
            "max_output_tokens": MAX_OUTPUT_TOKENS, "model": MODEL,
            "response_mime_type": "application/json",
            "schema_response_mode": SCHEMA_RESPONSE_MODE, "seed": "NOT_SUPPORTED_NOT_USED",
            "temperature": TEMPERATURE,
            "provider_reported_model_version": "RECORDED_PER_JOB_DRIFT_STOPS_RUN",
        },
        "execution": {
            "live_execution": "DISABLED_IN_THIS_VERSION",
            "durable_executor": DURABLE_EXECUTOR_VERSION,
            "durable_profile_id": DURABLE_PROFILE_ID,
            "durable_profile_sha256_recorded": DURABLE_PROFILE_SHA256,
            "durable_profile_review_status": "QUALIFIED_PENDING_ORCHESTRATOR_REVIEW",
            "runtime": RUNTIME_VERSION,
            "global_pacing_max_operations": GLOBAL_MAX_PROVIDER_OPERATIONS,
            "global_pacing_rolling_window_seconds": GLOBAL_ROLLING_WINDOW_SECONDS,
            "maximum_windows_per_job": MAX_WINDOWS_PER_JOB,
            "maximum_provider_attempts_per_window": MAX_PROVIDER_ATTEMPTS_PER_WINDOW,
            "maximum_provider_attempts_per_job": MAX_PROVIDER_ATTEMPTS_PER_JOB,
            "window_cooldown_seconds": WINDOW_COOLDOWN_SECONDS,
            "budget_rule": "START_JOB_ONLY_IF_OPERATIONS_PLUS_9_AND_TOKENS_PLUS_ESTIMATE_FIT",
            "token_estimate": "PROMPT_CODE_POINTS_PLUS_MAX_OUTPUT_TOKENS",
            "interruption": "CASE_STATUS_ARTIFACT_WRITTEN_FOR_EVERY_STARTED_CASE",
            "diagnostics_concurrency": "SERIAL_ONLY_LOCKED_OBSERVER",
        },
        "compiler_binding": {
            "compiler_entrypoint":
                "tools.story_extraction.draft_compiler_v1_2.compile_story_extraction_draft_v1_2",
            "resolver": "CONTEXTUAL_ANCHOR_RESOLVER_V1",
            "max_context_code_points": 32,
            "partial_extraction": "FORBIDDEN_CASE_COMPILES_COMPLETELY_OR_NOT_AT_ALL",
            "surface_form": "SOURCE_DERIVED",
            "semantic_inference": False,
        },
        "evaluation_snapshot": {
            "identity": "M4_EVALUATION_PROTOCOL_SNAPSHOT_V2",
            "sha256": "8dddbd0b9f3ea51af593c1fab0631b088b6f4e6b8c16833a1f11b8448088eee9",
            "used_by_runner": False,
        },
        "prompt_hashes": prompt_hashes(),
        "repair_policy": {
            "eligible_primary_failure_categories": list(REPAIR_ELIGIBLE_CATEGORIES),
            "maximum_per_case": MAX_STRUCTURAL_REPAIRS_PER_CASE,
            "feedback": "SANITIZED_BLOCKERS_LOCATOR_STATUSES_AND_CANONICAL_ISSUE_CLASSES",
            "gold_signal": "FORBIDDEN",
            "quality_signal": "FORBIDDEN",
            "repair_failure_is_terminal": True,
        },
        "request_construction": {
            "case_id_pattern": CASE_ID_PATTERN.pattern,
            "primary_job_id_pattern": "P4V12_{CASE_ID}_PRIMARY",
            "repair_job_id_pattern": "P4V12_{CASE_ID}_REPAIR_1",
        },
        "forbidden_input_archives": dict(sorted(FORBIDDEN_ARCHIVE_SHA256.items())),
        "files": {"runtime": _files(RUNTIME_FILES), "live_path": _files(LIVE_PATH_FILES),
                  "tooling": _files(TOOLING_FILES)},
    }


def candidate_definition_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(candidate_definition()))


def environment_observed() -> dict[str, Any]:
    versions = {}
    for name in ENVIRONMENT_DISTRIBUTIONS:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "NOT_INSTALLED"
    return {"python": platform.python_version(), "implementation": sys.implementation.name,
            "platform": platform.system(), "distributions": versions,
            "requirements": dict(ENVIRONMENT_REQUIREMENTS)}
