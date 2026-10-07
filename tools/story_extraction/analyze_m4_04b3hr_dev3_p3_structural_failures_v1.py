"""Offline structural forensics for the locked M4-04B3H DEV3 P3 prediction set.

Reads only locked prediction artifacts (raw responses, parsed drafts, failure records,
case results and telemetry) and public tracked files. It accepts no input, gold, holdout,
evaluator or provider path, and it never calls a model. It replays the unchanged Draft
V1.1 validator and emits structure only: counts, blocker codes, paths, schema keywords,
field names and booleans. It never emits a response, a quote or a field value.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Optional

import yaml

from tools.story_extraction.draft_compiler_v1_1 import (
    DraftCompilationErrorV1_1,
    _validator,
    validate_draft_v1_1,
)
from tools.story_extraction.m4_04b3f_dev3_p3_protocol_v1 import (
    CASE_IDS,
    DRAFT_SCHEMA_PATH,
    REPAIR_ELIGIBLE_CATEGORIES,
    REPO_ROOT,
    canonical_json_bytes,
    prompt_material,
    sha256_bytes,
)


TASK_ID = "M4-04B3HR"
PUBLIC_LOCK_PATH = REPO_ROOT / "benchmarks/m4_extraction/M4_04B3H_DEV3_P3_PREDICTION_LOCK.yaml"
PUBLIC_LOCK_SHA256 = "850b6ea557027b7c8777c5960df0654d2d265e9e041487445dfeb9fdcf6d59f2"
PREDICTION_SET_SHA256 = "06d555f53f6c113e3db7ab7eea55501a4b442e7e8daec3047bcc7cb3b55f38fd"
V1_SCHEMA_PATH = REPO_ROOT / "schemas/story_extraction/story_extraction_draft_v1.schema.json"
PHASES = (("primary", "primary"), ("repair_1", "repair"))
IDENTITY_FIELDS = (
    "case_id", "primary_request_fingerprint", "primary_raw_response_sha256", "repair_used",
    "repair_request_fingerprint", "repair_raw_response_sha256", "terminal_status",
    "terminal_draft_sha256", "compiled_batch_sha256", "terminal_failure_sha256",
)
REPRODUCTION_DEFECT = "M4_04B3HR_LOCKED_RESULT_REPRODUCTION_DEFECT"
SCHEMA_SECTION_MARKER = "EXACT STORY_EXTRACTION_DRAFT_V1_1 JSON SCHEMA:"
REGISTRY_SECTION_MARKER = "EXACT PREDICATE REGISTRY:"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]{1,40}$")
_UPPER_TOKEN = re.compile(r"^[A-Z][A-Z_]{1,39}$")
_REQUIRED_MESSAGE = re.compile(r"^'([A-Za-z0-9_]+)' is a required property$")


class StructuralForensicsError(RuntimeError):
    """Locked artifacts are missing, mutated, unsafe to analyze, or not reproducible."""


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise StructuralForensicsError("Locked artifact is unavailable: " + path.name) from error


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StructuralForensicsError("Locked JSON artifact is invalid: " + path.name) from error


def path_pattern(path: str) -> str:
    """A blocker path with array indices replaced, so paths aggregate across records."""
    return "/".join("*" if part.isdigit() else part for part in path.split("/")) if path else ""


# ---------------------------------------------------------------------------
# Locked evidence
# ---------------------------------------------------------------------------

def load_public_lock(
    path: Path = PUBLIC_LOCK_PATH,
    *,
    expected_sha256: str = PUBLIC_LOCK_SHA256,
    expected_prediction_set_sha256: str = PREDICTION_SET_SHA256,
) -> dict[str, Any]:
    """Load the public prediction lock only if its file and prediction-set hashes hold."""
    try:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeError) as error:
        raise StructuralForensicsError("Public prediction lock is unavailable") from error
    if sha256_bytes(text.encode("utf-8")) != expected_sha256:
        raise StructuralForensicsError("Public prediction lock hash mismatch")
    lock = yaml.safe_load(text)
    cases = lock.get("cases") if isinstance(lock, dict) else None
    if not isinstance(cases, list) or [case.get("case_id") for case in cases] != list(CASE_IDS):
        raise StructuralForensicsError("Public prediction lock case order mismatch")
    identities = [{name: case[name] for name in IDENTITY_FIELDS} for case in cases]
    rebuilt = sha256_bytes(canonical_json_bytes(identities))
    if not (rebuilt == lock.get("prediction_set_sha256") == expected_prediction_set_sha256):
        raise StructuralForensicsError("Prediction-set hash mismatch")
    return lock


def _artifact_directories(artifact_root: Path) -> dict[str, Path]:
    if any(marker in part.lower() for part in artifact_root.parts for marker in ("gold", "holdout")):
        raise StructuralForensicsError("Gold or holdout paths are never accepted")
    directories = {name: artifact_root / name for name in ("raw", "drafts", "failures", "case_results", "telemetry")}
    if any(not path.is_dir() for path in directories.values()):
        raise StructuralForensicsError("Locked prediction artifact directory is missing")
    return directories


def verify_locked_artifacts(artifact_root: Path, lock: Mapping[str, Any]) -> dict[str, int]:
    """Verify every locked hash and request fingerprint before any content is analyzed."""
    directories = _artifact_directories(artifact_root)
    counts = Counter()
    for case in lock["cases"]:
        case_id = case["case_id"]
        result = _read_json(directories["case_results"] / f"{case_id}.json")
        counts["case_results"] += 1
        repair = result.get("repair")
        recorded = {
            "case_id": result.get("case_id"),
            "primary_request_fingerprint": result["primary"]["request_fingerprint"],
            "primary_raw_response_sha256": result["primary"]["raw_response_sha256"],
            "repair_used": result.get("repair_used"),
            "repair_request_fingerprint": None if repair is None else repair["request_fingerprint"],
            "repair_raw_response_sha256": None if repair is None else repair["raw_response_sha256"],
            "terminal_status": result.get("terminal_status"),
            "terminal_draft_sha256": result.get("terminal_draft_sha256"),
            "compiled_batch_sha256": result.get("compiled_batch_sha256"),
            "terminal_failure_sha256": result.get("terminal_failure_sha256"),
        }
        if recorded != {name: case[name] for name in IDENTITY_FIELDS}:
            raise StructuralForensicsError("Case result differs from the prediction lock: " + case_id)
        for phase, key in PHASES:
            fingerprint = case[f"{key}_request_fingerprint"]
            if fingerprint is None:
                continue
            telemetry = _read_json(directories["telemetry"] / f"M4B3F_P3_{case_id}_{phase.upper()}.json")
            if telemetry.get("request_fingerprint") != fingerprint:
                raise StructuralForensicsError("Request fingerprint mismatch: " + case_id)
            counts["request_fingerprints"] += 1
            raw_sha256 = case[f"{key}_raw_response_sha256"]
            raw_path = directories["raw"] / f"{case_id}_{phase}.txt"
            if raw_sha256 is None:
                if raw_path.exists():
                    raise StructuralForensicsError("Unlocked raw response present: " + case_id)
            elif _sha256_file(raw_path) != raw_sha256:
                raise StructuralForensicsError("Raw response hash mismatch: " + case_id)
            else:
                counts["raw_responses"] += 1
            draft_sha256 = case[f"{key}_draft_sha256"]
            draft_path = directories["drafts"] / f"{case_id}_{phase}.json"
            if draft_sha256 is None:
                if draft_path.exists():
                    raise StructuralForensicsError("Unlocked parsed draft present: " + case_id)
            elif _sha256_file(draft_path) != draft_sha256:
                raise StructuralForensicsError("Parsed draft hash mismatch: " + case_id)
            else:
                counts["parsed_drafts"] += 1
        if case["terminal_failure_sha256"] is not None:
            if _sha256_file(directories["failures"] / f"{case_id}.json") != case["terminal_failure_sha256"]:
                raise StructuralForensicsError("Failure record hash mismatch: " + case_id)
            counts["failure_records"] += 1
    return dict(counts)


# ---------------------------------------------------------------------------
# Replay of the unchanged validator
# ---------------------------------------------------------------------------

def classify_json_failure(text: str) -> str:
    """High-level class of a JSON parse failure, from punctuation and position only."""
    stripped = text.strip()
    try:
        json.loads(text)
        return "VALID_JSON"
    except json.JSONDecodeError as error:
        if not stripped:
            return "EMPTY"
        if stripped[0] not in "{[":
            return "NON_JSON_PREFIX"
        if error.msg.startswith("Extra data"):
            return "EXTRA_DATA_AFTER_JSON"
        balanced = (text.count("{") == text.count("}")) and (text.count("[") == text.count("]"))
        if not balanced or stripped[-1] not in "}]" or error.pos >= len(text.rstrip()):
            return "TRUNCATED_OR_UNBALANCED"
        if "escape" in error.msg.lower() or "control character" in error.msg.lower():
            return "INVALID_ESCAPING"
        # Decided from punctuation, because decoder wording differs between Python versions.
        before, after = text[: error.pos].rstrip()[-1:], text[error.pos:].lstrip()
        if (before == "," and after[:1] in ("}", "]")) or (after[:1] == "," and after[1:].lstrip()[:1] in ("}", "]")):
            return "TRAILING_COMMA"
        if error.msg.startswith("Expecting property name"):
            return "MALFORMED_OBJECT_MEMBER"
        return "OTHER_MALFORMED_STRUCTURE"


def definition_owner(path: tuple[Any, ...]) -> str:
    """Which schema text owns the requirement at an instance path of a Draft V1.1 object."""
    parts = [str(part) for part in path]
    if len(parts) <= 1:
        return "V1_1_ROOT_PRESENT_IN_PROMPT"
    if parts[0] == "mentions":
        if len(parts) >= 3 and parts[2] == "role":
            return "V1_REFERENCED_DEFINITION_ABSENT_FROM_PROMPT"
        return "V1_1_MENTION_PRESENT_IN_PROMPT"
    return "V1_REFERENCED_DEFINITION_ABSENT_FROM_PROMPT"


def _enum_value_class(value: Any, registry_text: str, prompt_text: str) -> str:
    if not isinstance(value, str) or not _UPPER_TOKEN.fullmatch(value):
        return "NOT_AN_UPPERCASE_TOKEN"
    if value in registry_text:
        return "TOKEN_OF_ANOTHER_VOCABULARY_IN_THE_REGISTRY"
    return "TOKEN_PRESENT_ELSEWHERE_IN_PROMPT" if value in prompt_text else "TOKEN_ABSENT_FROM_PROMPT"


def replay_attempt(raw_text: str, *, registry_text: str = "", prompt_text: str = "") -> dict[str, Any]:
    """Parse and validate one locked response exactly as the runner core did."""
    try:
        draft = json.loads(raw_text)
    except (TypeError, json.JSONDecodeError):
        return {
            "json_parse": False, "json_failure_class": classify_json_failure(raw_text), "schema_pass": False,
            "compiler_reached": False, "category": "JSON_PARSE_FAILURE",
            "blockers": [{"phase": "JSON", "code": "JSON_PARSE_FAILURE", "path": "$"}], "errors": [],
        }
    try:
        validate_draft_v1_1(draft)
    except DraftCompilationErrorV1_1 as error:
        blockers = [item.as_dict() for item in error.blockers]
    else:
        return {
            "json_parse": True, "json_failure_class": None, "schema_pass": True, "compiler_reached": True,
            "category": None, "blockers": [], "errors": [],
        }
    errors = []
    for item in _validator().iter_errors(draft):
        path = tuple(item.absolute_path)
        entry = {
            "keyword": str(item.validator),
            "path": "/".join(map(str, path)),
            "owner": definition_owner(path),
            "fields": [],
            "value_class": None,
        }
        if item.validator == "required":
            match = _REQUIRED_MESSAGE.match(item.message)
            entry["fields"] = [match.group(1)] if match else []
        elif item.validator == "additionalProperties" and isinstance(item.instance, dict):
            allowed = set(item.schema.get("properties", {}))
            entry["fields"] = [
                key if _IDENTIFIER.fullmatch(key) else "<NON_IDENTIFIER_KEY>"
                for key in sorted(item.instance) if key not in allowed
            ]
        elif item.validator == "enum":
            entry["value_class"] = _enum_value_class(item.instance, registry_text, prompt_text)
        errors.append(entry)
    return {
        "json_parse": True, "json_failure_class": None, "schema_pass": False, "compiler_reached": False,
        "category": "DRAFT_SCHEMA_FAILURE", "blockers": blockers, "errors": errors,
    }


def repair_effect(primary: Mapping[str, Any], repair: Optional[Mapping[str, Any]]) -> str:
    """Descriptive only: how the blocker set changed between the primary and the repair."""
    if repair is None:
        return "NO_REPAIR"
    key = lambda attempt: {(item["phase"], item["code"], item["path"]) for item in attempt["blockers"]}
    before, after = key(primary), key(repair)
    if not after:
        return "CLEARED_PRIMARY_BLOCKER"
    if primary["json_parse"] and not repair["json_parse"]:
        return "DEGRADED_TO_JSON_FAILURE"
    if before == after:
        return "SAME_BLOCKER"
    if after < before:
        return "PARTIALLY_CLEARED"
    if not before & after:
        return "DIFFERENT_BLOCKER"
    return "OTHER_STRUCTURAL"


# ---------------------------------------------------------------------------
# Prompt and schema consistency audit (public tracked files only)
# ---------------------------------------------------------------------------

def prompt_sections() -> dict[str, str]:
    system = prompt_material()["primary_system"]
    start, end = system.index(SCHEMA_SECTION_MARKER), system.index(REGISTRY_SECTION_MARKER)
    return {"preamble": system[:start], "schema_section": system[start:end], "registry_section": system[end:]}


def _key_status(key: str, sections: Mapping[str, str]) -> str:
    if f'"{key}"' in sections["schema_section"]:
        return "EXPLICIT_IN_PROMPT"
    word = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])")
    if word.search(sections["preamble"]) or word.search(sections["registry_section"]):
        return "IMPLICIT_ONLY"
    return "ABSENT_FROM_PROMPT"


def prompt_schema_audit() -> dict[str, Any]:
    """Compare the schema text the locked prompt contains with what the validator enforces."""
    sections = prompt_sections()
    system = "".join(sections.values())
    v1_1_text = DRAFT_SCHEMA_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    v1_text = V1_SCHEMA_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    v1 = json.loads(v1_text)
    references = sorted(set(re.findall(r'"\$ref": "' + re.escape(v1["$id"]) + r'#/\$defs/([A-Za-z]+)"', v1_1_text)))
    definitions = {}
    for name in references:
        definition = v1["$defs"][name]
        keys = list(definition.get("properties", {}))
        for branch in definition.get("oneOf", []):
            keys.extend(key for key in branch.get("properties", {}) if key not in keys)
        definitions[name] = {
            "definition_text_in_prompt": f'"{name}"' in sections["schema_section"],
            "required_keys": {key: _key_status(key, sections) for key in definition.get("required", [])},
            "all_keys": {key: _key_status(key, sections) for key in keys},
            "enum_values_total": len(definition.get("enum", [])),
            "enum_values_appearing_anywhere_in_prompt": sum(value in system for value in definition.get("enum", [])),
        }
    return {
        "prompt_schema_section_is_the_v1_1_schema_file": v1_1_text.strip() in sections["schema_section"],
        "v1_schema_text_in_prompt": v1_text.strip() in system,
        "v1_schema_id_appears_only_as_ref_target": v1["$id"] in sections["schema_section"],
        "external_ref_resource": v1["$id"],
        "definitions_referenced_but_absent_from_prompt": [
            name for name in references if not definitions[name]["definition_text_in_prompt"]
        ],
        "definitions_present_in_prompt": ["Mention"] if '"Mention"' in sections["schema_section"] else [],
        "v1_definitions_total": len(v1["$defs"]),
        "referenced_definitions": definitions,
        "provider_response_schema_used": False,
    }


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _attempt_summary(attempt: Mapping[str, Any]) -> dict[str, Any]:
    blockers = attempt["blockers"]
    return {
        "json_parse": attempt["json_parse"],
        "json_failure_class": attempt["json_failure_class"],
        "schema_pass": attempt["schema_pass"],
        "compiler_reached": attempt["compiler_reached"],
        "category": attempt["category"] or "SCHEMA_PASS",
        "blocker_count": len(blockers),
        "blocker_codes": dict(sorted(Counter(item["code"] for item in blockers).items())),
        "blocker_path_patterns": dict(sorted(Counter(path_pattern(item["path"]) for item in blockers).items())),
        "schema_error_count": len(attempt["errors"]),
        "schema_keywords": dict(sorted(Counter(item["keyword"] for item in attempt["errors"]).items())),
    }


def analyze(
    artifact_root: Path,
    lock_path: Path = PUBLIC_LOCK_PATH,
    *,
    expected_lock_sha256: str = PUBLIC_LOCK_SHA256,
    expected_prediction_set_sha256: str = PREDICTION_SET_SHA256,
) -> dict[str, Any]:
    """Return {"public": ..., "private": ...}. Fails closed if the lock is not reproduced."""
    lock = load_public_lock(
        lock_path, expected_sha256=expected_lock_sha256,
        expected_prediction_set_sha256=expected_prediction_set_sha256,
    )
    inventory = verify_locked_artifacts(artifact_root, lock)
    directories = _artifact_directories(artifact_root)
    sections = prompt_sections()
    prompt_text = "".join(sections.values())

    aggregate = {
        phase: {name: Counter() for name in (
            "category", "blocker_code", "blocker_phase", "blocker_path_pattern", "schema_keyword",
            "required_field_missing", "unexpected_field", "definition_owner", "enum_value_class",
        )} | {"valid_json": 0, "schema_pass": 0, "compiler_reached": 0, "attempts": 0,
              "cases_by_requirement": {}}
        for phase, _ in PHASES
    }
    effects, matrix, private_matrix = Counter(), [], []
    reproduced = recorded_equal = sanitized = eligible = token_consistent = 0
    absent_only_cases = 0

    for case in lock["cases"]:
        case_id = case["case_id"]
        result = _read_json(directories["case_results"] / f"{case_id}.json")
        attempts: dict[str, Optional[dict[str, Any]]] = {}
        usage = {}
        for phase, key in PHASES:
            if case[f"{key}_raw_response_sha256"] is None:
                attempts[key] = None
                continue
            raw = (directories["raw"] / f"{case_id}_{phase}.txt").read_text(encoding="utf-8")
            attempt = replay_attempt(raw, registry_text=sections["registry_section"], prompt_text=prompt_text)
            attempts[key] = attempt
            usage[key] = _read_json(directories["telemetry"] / f"M4B3F_P3_{case_id}_{phase.upper()}.json").get("usage") or {}
            bucket = aggregate[phase]
            bucket["attempts"] += 1
            bucket["valid_json"] += attempt["json_parse"]
            bucket["schema_pass"] += attempt["schema_pass"]
            bucket["compiler_reached"] += attempt["compiler_reached"]
            bucket["category"][attempt["category"] or "SCHEMA_PASS"] += 1
            for item in attempt["blockers"]:
                bucket["blocker_code"][item["code"]] += 1
                bucket["blocker_phase"][item["phase"]] += 1
                bucket["blocker_path_pattern"][path_pattern(item["path"])] += 1
            for item in attempt["errors"]:
                pattern = path_pattern(item["path"])
                bucket["schema_keyword"][item["keyword"]] += 1
                bucket["definition_owner"][item["owner"]] += 1
                names = item["fields"] or [None]
                for name in names:
                    requirement = f"{item['keyword']}:{pattern}" + (f":{name}" if name else "")
                    bucket["cases_by_requirement"].setdefault(requirement, set()).add(case_id)
                    if item["keyword"] == "required" and name:
                        bucket["required_field_missing"][f"{pattern}:{name}"] += 1
                    elif item["keyword"] == "additionalProperties" and name:
                        bucket["unexpected_field"][f"{pattern}:{name}"] += 1
                if item["value_class"]:
                    bucket["enum_value_class"][f"{pattern}:{item['value_class']}"] += 1

        primary, repair = attempts["primary"], attempts["repair"]
        terminal = repair or primary
        terminal_category = None if terminal is None else terminal["category"]
        if terminal_category != case["terminal_failure_category"]:
            raise StructuralForensicsError(REPRODUCTION_DEFECT + ": " + case_id)
        for key, attempt in attempts.items():
            if attempt is None:
                continue
            validation = (result[key] or {}).get("validation") or {}
            if validation.get("category") != attempt["category"]:
                raise StructuralForensicsError(REPRODUCTION_DEFECT + ": " + case_id)
            if attempt["category"] is not None and validation.get("blockers") == attempt["blockers"]:
                recorded_equal += 1
            if all(set(item) == {"phase", "code", "path"} for item in validation.get("blockers", [])):
                sanitized += 1
        reproduced += 1
        if primary is not None and primary["category"] in REPAIR_ELIGIBLE_CATEGORIES:
            eligible += 1
        if repair is not None and usage:
            grew = (usage["repair"].get("prompt_token_count") or 0) - (usage["primary"].get("prompt_token_count") or 0)
            token_consistent += grew >= (usage["primary"].get("candidates_token_count") or 0)
        effect = repair_effect(primary, repair) if primary is not None else "NO_PRIMARY_RESPONSE"
        effects[effect] += 1
        if terminal is not None and terminal["errors"] and all(
            item["owner"] == "V1_REFERENCED_DEFINITION_ABSENT_FROM_PROMPT" for item in terminal["errors"]
        ):
            absent_only_cases += 1
        paths = lambda attempt: set() if attempt is None else {item["path"] for item in attempt["blockers"]}
        entry = {
            "case_id": case_id,
            "primary": None if primary is None else _attempt_summary(primary),
            "repair": None if repair is None else _attempt_summary(repair),
            "repair_effect": effect,
            "blocker_paths_cleared": len(paths(primary) - paths(repair)) if repair else 0,
            "blocker_paths_new": len(paths(repair) - paths(primary)) if repair else 0,
            "blocker_paths_unchanged": len(paths(primary) & paths(repair)) if repair else 0,
            "primary_and_repair_raw_bytes_identical": (
                case["repair_raw_response_sha256"] is not None
                and case["primary_raw_response_sha256"] == case["repair_raw_response_sha256"]
            ),
            "request_fingerprints_differ": case["primary_request_fingerprint"] != case["repair_request_fingerprint"],
            "terminal_category": terminal_category or "SCHEMA_PASS",
            "terminal_category_reproduced": True,
        }
        matrix.append(entry)
        private_matrix.append({
            "case_id": case_id,
            **{key: None if attempt is None else {"blockers": attempt["blockers"], "errors": attempt["errors"]}
               for key, attempt in attempts.items()},
        })

    def counted(counter: Counter) -> dict[str, int]:
        return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))

    public_aggregate = {}
    for phase, key in PHASES:
        bucket = aggregate[phase]
        public_aggregate[key] = {
            "attempts": bucket["attempts"],
            "valid_json": bucket["valid_json"],
            "schema_pass": bucket["schema_pass"],
            "compiler_reached": bucket["compiler_reached"],
            "failure_categories": counted(bucket["category"]),
            "blocker_codes": counted(bucket["blocker_code"]),
            "blocker_phases": counted(bucket["blocker_phase"]),
            "blocker_path_patterns": counted(bucket["blocker_path_pattern"]),
            "schema_keywords": counted(bucket["schema_keyword"]),
            "schema_errors_by_definition_owner": counted(bucket["definition_owner"]),
            "required_fields_missing": counted(bucket["required_field_missing"]),
            "unexpected_fields": counted(bucket["unexpected_field"]),
            "enum_value_classes": counted(bucket["enum_value_class"]),
            "cases_affected_by_requirement": dict(sorted(
                ((name, len(cases)) for name, cases in bucket["cases_by_requirement"].items()),
                key=lambda item: (-item[1], item[0]),
            )),
        }
    repairs = sum(case["repair_used"] for case in lock["cases"])
    public = {
        "prediction_set_sha256": lock["prediction_set_sha256"],
        "reproduction": {
            "locked_artifact_hashes": "PASS",
            "inventory": inventory,
            "terminal_categories_reproduced": f"{reproduced}/{len(lock['cases'])}",
            "recorded_blocker_sets_equal_replay": recorded_equal,
            "attempts_replayed": sum(public_aggregate[key]["attempts"] for _, key in PHASES),
        },
        "aggregate": public_aggregate | {
            "repair_effects": counted(effects),
            "terminal_cases_whose_schema_errors_all_lie_in_definitions_absent_from_prompt": absent_only_cases,
        },
        "repair_forensics": {
            "repairs": repairs,
            "primary_category_repair_eligible": eligible,
            "recorded_blockers_have_phase_code_path_only": sanitized,
            "repair_prompt_grew_by_at_least_the_primary_output_tokens": token_consistent,
            "repair_request_fingerprint_differs_from_primary": sum(item["request_fingerprints_differ"] for item in matrix),
            "repairs_reaching_schema_validity": public_aggregate["repair"]["schema_pass"],
        },
        "case_matrix": matrix,
        "prompt_schema_audit": prompt_schema_audit(),
    }
    return {"public": public, "private": {"case_matrix": private_matrix}}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--private-output", required=True, type=Path)
    parser.add_argument("--public-summary-output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = analyze(args.artifact_root)
    except StructuralForensicsError as error:
        print(f"M4_04B3HR_FORENSICS_STOPPED: {error}")
        return 2
    for path, value in ((args.private_output, result["private"]), (args.public_summary_output, result["public"])):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json_bytes(value))
    print(json.dumps({"terminal_categories_reproduced": result["public"]["reproduction"]["terminal_categories_reproduced"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
