"""Public-safe structural forensics for locked M4-04B3C prediction artifacts.

The analyzer reads only raw-response, parsed-draft, compiler-failure, and per-case
result files. It never accepts source, input, gold, holdout, compiler, evaluator, or
provider paths and never emits quotes or model response text.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


CASE_IDS = tuple(f"DEV2_{index:02d}" for index in range(1, 11))
COLLECTIONS = (
    "evidence",
    "mentions",
    "entities",
    "events",
    "anchors",
    "propositions",
    "assertions",
)


class StructuralForensicsError(RuntimeError):
    """Locked artifacts are missing, mutated, or unsafe to analyze."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StructuralForensicsError("Locked JSON artifact is invalid") from error


def failure_family(category: Any, code: Any) -> str:
    if category is None:
        return "PASS"
    if category == "JSON_PARSE_FAILURE":
        return "JSON"
    if category == "DRAFT_SCHEMA_FAILURE":
        return "DRAFT_SCHEMA"
    if code in {
        "AMBIGUOUS_QUOTE",
        "QUOTE_NOT_FOUND",
        "OCCURRENCE_OUT_OF_RANGE",
        "CONTEXT_ONLY_EVIDENCE",
    }:
        return "QUOTE"
    if code in {
        "UNKNOWN_HANDLE",
        "HANDLE_TYPE_MISMATCH",
        "UNKNOWN_EVIDENCE_HANDLE",
        "MENTION_EVIDENCE_MISMATCH",
        "UNKNOWN_PASSAGE_HANDLE",
        "PRIOR_CONTEXT_NOT_EVIDENCE",
    }:
        return "HANDLE"
    if isinstance(code, str) and (
        "PREDICATE" in code or "ARGUMENT" in code or "DERIVATION" in code
    ):
        return "PREDICATE"
    if code in {"CANONICAL_VALIDATOR_EXCEPTION", "CANONICAL_CONFORMANCE_FAILURE"}:
        return "CANONICAL_COMPILER"
    return "OTHER"


def _quote_relation(left: str, right: str) -> str:
    if left == right:
        return "EQUAL"
    if left in right:
        return "MENTION_QUOTE_STRICTLY_WITHIN_EVIDENCE_QUOTE"
    if right in left:
        return "EVIDENCE_QUOTE_STRICTLY_WITHIN_MENTION_QUOTE"
    return "DISTINCT_QUOTES"


def mention_linkage_shape(draft: Mapping[str, Any]) -> list[dict[str, Any]]:
    evidence = {
        item.get("handle"): item
        for item in draft.get("evidence", [])
        if isinstance(item, dict) and isinstance(item.get("handle"), str)
    }
    diagnostics: list[dict[str, Any]] = []
    for mention in draft.get("mentions", []):
        if not isinstance(mention, dict) or "evidence_handle" not in mention:
            continue
        target = evidence.get(mention.get("evidence_handle"))
        if target is None:
            diagnostics.append(
                {
                    "mention_handle": mention.get("handle"),
                    "evidence_handle": mention.get("evidence_handle"),
                    "mismatch_fields": ["unknown_evidence_handle"],
                    "quote_relation": "NOT_COMPARABLE",
                }
            )
            continue
        fields = []
        for field in ("passage_handle", "quote", "role", "occurrence"):
            if mention.get(field) != target.get(field):
                fields.append(field)
        diagnostics.append(
            {
                "mention_handle": mention.get("handle"),
                "evidence_handle": mention.get("evidence_handle"),
                "mismatch_fields": fields,
                "quote_relation": _quote_relation(
                    str(mention.get("quote", "")), str(target.get("quote", ""))
                ),
            }
        )
    return diagnostics


def _record_map(draft: Mapping[str, Any], collection: str) -> dict[str, Any]:
    return {
        item["handle"]: item
        for item in draft.get(collection, [])
        if isinstance(item, dict) and isinstance(item.get("handle"), str)
    }


def draft_change_shape(primary: Mapping[str, Any], repair: Mapping[str, Any]) -> dict[str, Any]:
    collections: dict[str, Any] = {}
    for name in COLLECTIONS:
        before = _record_map(primary, name)
        after = _record_map(repair, name)
        changed = {}
        for handle in sorted(set(before) & set(after)):
            if before[handle] != after[handle]:
                changed[handle] = sorted(set(before[handle]) ^ set(after[handle]) | {
                    key for key in set(before[handle]) & set(after[handle])
                    if before[handle][key] != after[handle][key]
                })
        if set(before) != set(after) or changed:
            collections[name] = {
                "added_handles": sorted(set(after) - set(before)),
                "removed_handles": sorted(set(before) - set(after)),
                "changed_fields_by_handle": changed,
            }
    return {
        "byte_identical_semantic_json": primary == repair,
        "changed_collections": collections,
    }


def _root_cause(category: Any, code: Any) -> str:
    if category is None:
        return "NONE_STRUCTURAL_PASS"
    if code == "MENTION_EVIDENCE_MISMATCH":
        return "MENTION_EVIDENCE_HANDLE_TARGETS_NONIDENTICAL_LOCATOR_OR_ROLE"
    if code == "AMBIGUOUS_QUOTE":
        return "REPEATED_QUOTE_LOCATOR_OMITS_REQUIRED_OCCURRENCE"
    if category == "JSON_PARSE_FAILURE":
        return "MODEL_RESPONSE_NOT_JSON"
    if category == "DRAFT_SCHEMA_FAILURE":
        return "MODEL_RESPONSE_VIOLATES_DRAFT_SCHEMA"
    return "OTHER_DETERMINISTIC_COMPILER_REJECTION"


def _ownership(category: Any, code: Any) -> dict[str, Any]:
    if category is None:
        return {
            "machine_or_compiler_defect_evidence": False,
            "interface_instruction_problem": False,
            "semantic_model_output_problem": False,
        }
    if code == "MENTION_EVIDENCE_MISMATCH":
        return {
            "machine_or_compiler_defect_evidence": False,
            "interface_instruction_problem": True,
            "semantic_model_output_problem": True,
        }
    return {
        "machine_or_compiler_defect_evidence": False,
        "interface_instruction_problem": False,
        "semantic_model_output_problem": True,
    }


def _repair_effect(primary: Mapping[str, Any], repair: Mapping[str, Any], same: bool) -> str:
    if same:
        return "NO_CHANGE"
    if repair.get("pass") is True:
        return "FULL_STRUCTURAL_CORRECTION"
    if (
        primary.get("category") == repair.get("category")
        and primary.get("code") == repair.get("code")
        and primary.get("path") == repair.get("path")
    ):
        return "CHANGED_DRAFT_BUT_TRIGGER_PERSISTED"
    return "INITIAL_TRIGGER_CORRECTED_NEXT_TRIGGER_EXPOSED"


def analyze_locked_artifacts(artifact_root: Path) -> dict[str, Any]:
    if any("gold" in part.lower() or "input" == part.lower() for part in artifact_root.parts):
        raise StructuralForensicsError("Analyzer accepts prediction artifacts only")
    cases = []
    for case_id in CASE_IDS:
        result_path = artifact_root / "case_results" / f"{case_id}.json"
        result = _read_json(result_path)
        if result.get("case_id") != case_id or result.get("repair_used") is not True:
            raise StructuralForensicsError("Per-case result identity mismatch")

        primary_raw = artifact_root / "raw" / f"{case_id}_primary.txt"
        repair_raw = artifact_root / "raw" / f"{case_id}_repair_1.txt"
        primary_draft_path = artifact_root / "drafts" / f"{case_id}_primary.json"
        repair_draft_path = artifact_root / "drafts" / f"{case_id}_repair_1.json"
        expected = (
            (primary_raw, result["primary"]["raw_response_sha256"]),
            (repair_raw, result["repair"]["raw_response_sha256"]),
            (primary_draft_path, result["primary"]["draft_sha256"]),
            (repair_draft_path, result["repair"]["draft_sha256"]),
        )
        if any(_sha256(path) != digest for path, digest in expected):
            raise StructuralForensicsError("Locked raw/draft artifact hash mismatch")
        primary_draft = _read_json(primary_draft_path)
        repair_draft = _read_json(repair_draft_path)

        if result["terminal_status"] == "STRUCTURAL_FAILURE":
            failure_path = artifact_root / "failures" / f"{case_id}.json"
            if _sha256(failure_path) != result["terminal_failure_sha256"]:
                raise StructuralForensicsError("Locked compiler failure hash mismatch")
            failure = _read_json(failure_path)
            if failure.get("validation") != result["repair"]["validation"]:
                raise StructuralForensicsError("Compiler failure record mismatch")

        primary = result["primary"]["validation"]
        repair = result["repair"]["validation"]
        same = result["primary"]["draft_sha256"] == result["repair"]["draft_sha256"]
        primary_links = mention_linkage_shape(primary_draft)
        repair_links = mention_linkage_shape(repair_draft)
        effect = _repair_effect(primary, repair, same)
        cases.append(
            {
                "case_id": case_id,
                "terminal_status": result["terminal_status"],
                "primary": {
                    "category": primary.get("category"),
                    "code": primary.get("code"),
                    "path": primary.get("path"),
                    "failure_family": failure_family(
                        primary.get("category"), primary.get("code")
                    ),
                    "root_cause": _root_cause(
                        primary.get("category"), primary.get("code")
                    ),
                    "ownership": _ownership(
                        primary.get("category"), primary.get("code")
                    ),
                },
                "repair": {
                    "category": repair.get("category"),
                    "code": repair.get("code"),
                    "path": repair.get("path"),
                    "failure_family": failure_family(
                        repair.get("category"), repair.get("code")
                    ),
                    "root_cause": _root_cause(
                        repair.get("category"), repair.get("code")
                    ),
                    "ownership": _ownership(
                        repair.get("category"), repair.get("code")
                    ),
                },
                "repair_effect": effect,
                "repair_corrected_anything": effect
                in {"FULL_STRUCTURAL_CORRECTION", "INITIAL_TRIGGER_CORRECTED_NEXT_TRIGGER_EXPOSED"},
                "draft_change_shape": draft_change_shape(primary_draft, repair_draft),
                "primary_mention_linkages": primary_links,
                "repair_mention_linkages": repair_links,
            }
        )

    primary_codes = Counter(item["primary"]["code"] or "PASS" for item in cases)
    repair_codes = Counter(item["repair"]["code"] or "PASS" for item in cases)
    primary_families = Counter(item["primary"]["failure_family"] for item in cases)
    repair_families = Counter(item["repair"]["failure_family"] for item in cases)
    effects = Counter(item["repair_effect"] for item in cases)
    terminal = Counter(item["terminal_status"] for item in cases)
    return {
        "artifact": "M4_04B3CR_STRUCTURAL_FAILURE_FORENSICS_PRIVATE_V1",
        "case_count": len(cases),
        "cases": cases,
        "aggregate": {
            "primary_categories": dict(Counter(item["primary"]["category"] for item in cases)),
            "primary_codes": dict(primary_codes),
            "primary_failure_families": dict(primary_families),
            "repair_codes": dict(repair_codes),
            "repair_failure_families": dict(repair_families),
            "repair_effects": dict(effects),
            "terminal_states": dict(terminal),
        },
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    args = parser.parse_args()
    value = analyze_locked_artifacts(args.artifact_root)
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
