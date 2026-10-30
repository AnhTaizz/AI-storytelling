"""Offline identity of the P3 STORY_EXTRACTION_DRAFT_V1_1 extractor candidate.

This module materializes prompts, request specifications and the candidate manifest.
It never opens a dataset, loads credentials, constructs a transport or performs
provider work. Model and generation settings are carried over unchanged from the
P2 DEV2 protocol; only the draft interface, prompts and repair feedback differ.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Optional

from tools.story_extraction.draft_compiler_v1_1 import DRAFT_VERSION
from tools.story_extraction.draft_v1_1_schema_bundle_v1 import (
    BUNDLE_VERSION,
    bundle_sha256,
    bundle_text,
)
from tools.story_extraction.durable_research_executor_v1 import DurableJobSpec


REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "M4-04B4B-DRAFT-V1-1-CANDIDATE-READINESS"
CANDIDATE_ID = "P3_STORY_EXTRACTION_DRAFT_V1_1_GEMINI_3_5_FLASH_LITE_V1"
CANDIDATE_MANIFEST_ID = "M4_04B4B_DRAFT_V1_1_CANDIDATE_MANIFEST_V1"
HASH_POLICY = "M4_CROSS_PLATFORM_CONTENT_HASH_V1"

# Carried over unchanged from M4_04B3B2_DEV2_BENCHMARK_PROTOCOL_V1.
MODEL = "gemini-3.5-flash-lite"
CREDENTIAL_SLOT = "gemini_slot_3"
CREDENTIAL_TOPOLOGY = "UNKNOWN"
TEMPERATURE = 0
MAX_OUTPUT_TOKENS = 16384
CONCURRENCY = 1
GENERATION_CONFIG = {"temperature": TEMPERATURE, "max_output_tokens": MAX_OUTPUT_TOKENS}
SCHEMA_RESPONSE_MODE = "PROVIDER_JSON_MIME_STORY_EXTRACTION_DRAFT_V1_1"
DURABLE_PROFILE_ID = "M4_DURABLE_RESEARCH_EXECUTION_PROFILE_V1"
DURABLE_PROFILE_SHA256 = "c6c789f0f06d3fdabc2333c29b389252de853ffef0add536d4f06fb6b94e143e"
RUNTIME_VERSION = "GEMINI_TRANSPORT_RESILIENCE_V1_1"
DURABLE_EXECUTOR_VERSION = "DURABLE_RESEARCH_EXECUTOR_V1"
GLOBAL_MAX_PROVIDER_OPERATIONS = 6
GLOBAL_ROLLING_WINDOW_SECONDS = 60
WINDOW_COOLDOWN_SECONDS = 60
MAX_WINDOWS_PER_JOB = 3
MAX_PROVIDER_ATTEMPTS_PER_WINDOW = 3
MAX_PROVIDER_ATTEMPTS_PER_JOB = 9

REPAIR_ELIGIBLE_CATEGORIES = (
    "JSON_PARSE_FAILURE",
    "DRAFT_SCHEMA_FAILURE",
    "DRAFT_COMPILER_FAILURE",
)
MAX_STRUCTURAL_REPAIRS_PER_CASE = 1

PROMPT_ROOT = REPO_ROOT / "tools/story_extraction/prompts"
SYSTEM_PREAMBLE_PATH = PROMPT_ROOT / "story_extraction_draft_p3_system_v1_1.txt"
USER_TEMPLATE_PATH = PROMPT_ROOT / "story_extraction_draft_p3_user_v1_1.txt"
REPAIR_USER_TEMPLATE_PATH = PROMPT_ROOT / "story_extraction_draft_p3_repair_user_v1_1.txt"
PREDICATE_REGISTRY_PATH = REPO_ROOT / "schemas/canonical_story/predicate_registry_v0.yaml"
REPAIR_SYSTEM_SUFFIX = """

STRUCTURAL REPAIR MODE
Repair only the sanitized deterministic blockers supplied by the host. Preserve semantic
choices from the primary response. Do not fill coverage gaps, optimize quality, consult
gold, or introduce a new interpretation. This is the only repair allowed for the case.
""".strip()

CASE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_[0-9]{2,3}$")
TEMPLATE_MARKERS = ("{CASE_ID}", "{PREPARED_INPUT_JSON}", "{PRIMARY_RESPONSE}", "{FAILURE_JSON}")

# Files whose content defines the candidate. Paths are repository-relative POSIX paths.
BOUND_FILES: tuple[tuple[str, str], ...] = (
    ("draft_schema_v1_1", "schemas/story_extraction/story_extraction_draft_v1_1.schema.json"),
    ("draft_schema_v1_dependency", "schemas/story_extraction/story_extraction_draft_v1.schema.json"),
    ("predicate_registry", "schemas/canonical_story/predicate_registry_v0.yaml"),
    ("canonical_schema", "schemas/canonical_story/canonical_story_v0.schema.json"),
    ("batch_schema", "schemas/story_extraction/story_extraction_batch_v0.schema.json"),
    ("compiler_v1_1", "tools/story_extraction/draft_compiler_v1_1.py"),
    ("compiler_v1_backend", "tools/story_extraction/draft_compiler_v1.py"),
    ("batch_contract", "tools/story_extraction/extraction_contract_v0.py"),
    ("batch_guard", "tools/story_extraction/extraction_contract_guard_v1.py"),
    ("canonical_conformance", "tools/canonical_story/conformance_v0.py"),
    ("m3_adapter", "tools/story_ingestion/light_novel_adapter_v0.py"),
    ("schema_bundle", "tools/story_extraction/draft_v1_1_schema_bundle_v1.py"),
    ("conformance_diagnostics", "tools/story_extraction/draft_v1_1_conformance_diagnostics_v1.py"),
    ("prompt_system", "tools/story_extraction/prompts/story_extraction_draft_p3_system_v1_1.txt"),
    ("prompt_user", "tools/story_extraction/prompts/story_extraction_draft_p3_user_v1_1.txt"),
    ("prompt_repair_user", "tools/story_extraction/prompts/story_extraction_draft_p3_repair_user_v1_1.txt"),
    ("candidate_module", "tools/story_extraction/m4_draft_v1_1_candidate_p3_v1.py"),
    ("runner", "tools/story_extraction/run_m4_draft_v1_1_predictions_v1.py"),
    ("durable_executor", "tools/story_extraction/durable_research_executor_v1.py"),
    ("runtime", "tools/story_extraction/gemini_resilience_v1_1.py"),
    ("runtime_v1_base", "tools/story_extraction/gemini_resilience_v1.py"),
    ("live_window_transport", "tools/story_extraction/run_m4_04b2_dev_predictions_v1.py"),
    ("gemini_transport", "tools/story_extraction/gemini_transport_v1.py"),
    ("gemini_key_pool", "tools/story_extraction/gemini_key_pool_v1.py"),
    ("evaluation_snapshot_v2", "benchmarks/m4_extraction/M4_EVALUATION_PROTOCOL_SNAPSHOT_V2.yaml"),
)

# Known sealed or gold archives that no candidate run may ever accept as input.
FORBIDDEN_ARCHIVE_SHA256 = {
    "11388350b830d08c48010a7010c7c376ea7b613abf30b71592b0a190ff80eceb": "M4_03_HOLDOUT_INPUT_V1",
    "7de8f597797dd24f493ce76f08284145c3245b0da8423fe8840411252aaa22cb": "M4_03_HOLDOUT_GOLD_V1",
    "77b9655b92b09c5b2c0d0ce749432ae12da342bbf07d62a01b16b37b1fce9939": "M4_04B3_DEV2_GOLD_V1",
}


class CandidateError(RuntimeError):
    """The candidate identity or a request differs from the exact definition."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def normalize_line_endings(data: bytes) -> bytes:
    """CRLF to LF only; lone CR is preserved so that it stays visible as a difference."""
    return data.replace(b"\r\n", b"\n")


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def file_hash_record(path: Path) -> dict[str, str]:
    """Raw bytes as observed, plus checkout-independent content identities."""
    raw = path.read_bytes()
    normalized = normalize_line_endings(raw)
    return {
        "raw_sha256_observed": sha256_bytes(raw),
        "content_sha256_lf": sha256_bytes(normalized),
        "git_blob_sha1_lf": git_blob_sha1(normalized),
        "observed_line_endings": (
            "CRLF" if b"\r\n" in raw else ("LF" if b"\n" in raw else "NONE")
        ),
    }


def _normalized_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip()


def prompt_material() -> dict[str, str]:
    """Build P3 prompts from tracked files with the reference-free schema bundle."""
    preamble = _normalized_text(SYSTEM_PREAMBLE_PATH)
    registry = _normalized_text(PREDICATE_REGISTRY_PATH)
    system = (
        preamble
        + "\n\nEXACT STORY_EXTRACTION_DRAFT_V1_1 JSON SCHEMA (model-facing bundle, "
        + BUNDLE_VERSION
        + "):\n"
        + bundle_text()
        + "\n\nEXACT PREDICATE REGISTRY:\n"
        + registry
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
        "schema_bundle_sha256": bundle_sha256(),
        "primary_system_sha256": sha256_text(material["primary_system"]),
        "primary_user_template_sha256": sha256_text(material["primary_user_template"]),
        "primary_prompt_pair_sha256": sha256_text(
            material["primary_system"] + "\0" + material["primary_user_template"]
        ),
        "repair_system_sha256": sha256_text(material["repair_system"]),
        "repair_user_template_sha256": sha256_text(material["repair_user_template"]),
        "repair_prompt_pair_sha256": sha256_text(
            material["repair_system"] + "\0" + material["repair_user_template"]
        ),
    }


def prompt_size() -> dict[str, int]:
    material = prompt_material()
    return {
        "primary_system_characters": len(material["primary_system"]),
        "primary_system_utf8_bytes": len(material["primary_system"].encode("utf-8")),
        "repair_system_characters": len(material["repair_system"]),
    }


def _render(template: str, replacements: Mapping[str, str]) -> str:
    """Single-pass substitution, so inserted text is never itself re-substituted."""
    for key in replacements:
        if "{" + key + "}" not in template:
            raise CandidateError("Prompt template marker missing: {" + key + "}")
    leftover = template
    for key in replacements:
        leftover = leftover.replace("{" + key + "}", "")
    if any(marker in leftover for marker in TEMPLATE_MARKERS):
        raise CandidateError("Prompt template has unresolved markers")
    pattern = re.compile("|".join(re.escape("{" + key + "}") for key in replacements))
    return pattern.sub(lambda match: replacements[match.group(0)[1:-1]], template)


def _check_case(case_id: str, prepared_input: Mapping[str, Any]) -> None:
    if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id):
        raise CandidateError("Case id does not match the candidate case-id pattern")
    if prepared_input.get("draft_version") != DRAFT_VERSION:
        raise CandidateError("Prepared input is not Draft V1.1")
    if set(prepared_input) != {"draft_version", "passages", "existing_context"}:
        raise CandidateError("Prepared input has unexpected fields")


def primary_user_prompt(case_id: str, prepared_input: Mapping[str, Any]) -> str:
    _check_case(case_id, prepared_input)
    return _render(prompt_material()["primary_user_template"], {
        "CASE_ID": case_id,
        "PREPARED_INPUT_JSON": canonical_json_bytes(prepared_input).decode("utf-8").rstrip(),
    })


def build_primary_spec(case_id: str, prepared_input: Mapping[str, Any],
                       research_task_id: str) -> DurableJobSpec:
    material = prompt_material()
    return DurableJobSpec(
        job_id=f"P3V11_{case_id}_PRIMARY",
        model=MODEL,
        system_prompt=material["primary_system"],
        user_prompt=primary_user_prompt(case_id, prepared_input),
        generation_config=dict(GENERATION_CONFIG),
        schema_response_mode=SCHEMA_RESPONSE_MODE,
        credential_slot=CREDENTIAL_SLOT,
        research_task_id=research_task_id,
    )


_FORBIDDEN_FEEDBACK_KEYS = frozenset({
    "gold", "score", "quality", "missing_assertions", "expected", "recall", "precision",
})


def _feedback_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = {str(key).lower() for key in value}
        for item in value.values():
            keys |= _feedback_keys(item)
        return keys
    if isinstance(value, list):
        out: set[str] = set()
        for item in value:
            out |= _feedback_keys(item)
        return out
    return set()


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
    return DurableJobSpec(
        job_id=f"P3V11_{case_id}_REPAIR_1",
        model=MODEL,
        system_prompt=material["repair_system"],
        user_prompt=user,
        generation_config=dict(GENERATION_CONFIG),
        schema_response_mode=SCHEMA_RESPONSE_MODE,
        credential_slot=CREDENTIAL_SLOT,
        research_task_id=research_task_id,
    )


def bound_file_hashes(repo_root: Path = REPO_ROOT) -> dict[str, dict[str, str]]:
    out = {}
    for name, relative in BOUND_FILES:
        record = file_hash_record(repo_root / relative)
        record["path"] = relative
        out[name] = record
    return out


def candidate_definition() -> dict[str, Any]:
    """Checkout-independent identity of the candidate (no raw-byte or git-commit fields)."""
    files = {
        name: {"path": record["path"], "content_sha256_lf": record["content_sha256_lf"],
               "git_blob_sha1_lf": record["git_blob_sha1_lf"]}
        for name, record in bound_file_hashes().items()
    }
    return {
        "candidate_id": CANDIDATE_ID,
        "draft_version": DRAFT_VERSION,
        "hash_policy": HASH_POLICY,
        "generation": {
            "concurrency": CONCURRENCY,
            "credential_slot": CREDENTIAL_SLOT,
            "credential_topology": CREDENTIAL_TOPOLOGY,
            "json_mode": True,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "model": MODEL,
            "response_mime_type": "application/json",
            "schema_response_mode": SCHEMA_RESPONSE_MODE,
            "seed": "NOT_SUPPORTED_NOT_USED",
            "temperature": TEMPERATURE,
            "provider_reported_model_version": "RECORDED_PER_JOB_DRIFT_FAILS_RUN",
        },
        "durable_execution": {
            "durable_executor": DURABLE_EXECUTOR_VERSION,
            "first_success": "IMMUTABLE_LOCK",
            "global_pacing_max_operations": GLOBAL_MAX_PROVIDER_OPERATIONS,
            "global_pacing_rolling_window_seconds": GLOBAL_ROLLING_WINDOW_SECONDS,
            "maximum_provider_attempts_per_job": MAX_PROVIDER_ATTEMPTS_PER_JOB,
            "maximum_provider_attempts_per_window": MAX_PROVIDER_ATTEMPTS_PER_WINDOW,
            "maximum_windows_per_job": MAX_WINDOWS_PER_JOB,
            "output_aware_transport_retry": "FORBIDDEN",
            "profile_id": DURABLE_PROFILE_ID,
            "profile_sha256_recorded": DURABLE_PROFILE_SHA256,
            "profile_review_status": "QUALIFIED_PENDING_ORCHESTRATOR_REVIEW",
            "runtime": RUNTIME_VERSION,
            "window_cooldown_seconds": WINDOW_COOLDOWN_SECONDS,
        },
        "compiler_binding": {
            "compiler_entrypoint": (
                "tools.story_extraction.draft_compiler_v1_1.compile_story_extraction_draft_v1_1"
            ),
            "diagnostic_observer": "DRAFT_V1_1_CANONICAL_REPORT_OBSERVER_V1",
            "semantic_inference": False,
        },
        "evaluation_snapshot": {
            "identity": "M4_EVALUATION_PROTOCOL_SNAPSHOT_V2",
            "sha256": "8dddbd0b9f3ea51af593c1fab0631b088b6f4e6b8c16833a1f11b8448088eee9",
            "used_by_runner": False,
        },
        "prompt_hashes": prompt_hashes(),
        "repair_policy": {
            "eligible_only_after_received_primary_response": True,
            "eligible_primary_failure_categories": list(REPAIR_ELIGIBLE_CATEGORIES),
            "feedback": "SANITIZED_AGGREGATE_V1_1_BLOCKERS_AND_CANONICAL_ISSUE_CLASSES",
            "gold_signal": "FORBIDDEN",
            "maximum_per_case": MAX_STRUCTURAL_REPAIRS_PER_CASE,
            "missing_fact_or_coverage_retry": "FORBIDDEN",
            "quality_signal": "FORBIDDEN",
            "repair_failure_is_terminal": True,
        },
        "request_construction": {
            "case_id_pattern": CASE_ID_PATTERN.pattern,
            "input": "HOST_PREPARED_DRAFT_V1_1_INPUT_ONLY",
            "primary_job_id_pattern": "P3V11_{CASE_ID}_PRIMARY",
            "repair_job_id_pattern": "P3V11_{CASE_ID}_REPAIR_1",
        },
        "files": files,
    }


def candidate_definition_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(candidate_definition()))


def git_head(repo_root: Path = REPO_ROOT) -> Optional[str]:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def validate_candidate_definition(value: Any) -> None:
    expected = candidate_definition()
    if value != expected:
        differing = sorted(
            key for key in set(expected) | set(value or {})
            if (value or {}).get(key) != expected.get(key)
        )
        raise CandidateError("Candidate definition mismatch: " + ",".join(differing))
