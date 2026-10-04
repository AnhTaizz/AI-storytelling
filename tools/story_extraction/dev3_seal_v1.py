"""Deterministic, content-agnostic helpers for the private DEV3 seal.

No DEV3 source or gold is embedded here. The helpers operate on caller-supplied
bytes and public-safe package metadata; they have no provider integration.
"""
from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Mapping
import zipfile


INPUT_ARTIFACT = "M4_04B3_DEV3_INPUT_V1"
GOLD_ARTIFACT = "M4_04B3_DEV3_GOLD_V1"
BLINDNESS_ARTIFACT = "M4_04B3_DEV3_BLINDNESS_MANIFEST_V1"
CASE_IDS = tuple(f"DEV3_{index:02d}" for index in range(1, 11))
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
FORBIDDEN_INPUT_KEYS = frozenset({
    "gold_batch",
    "gold_status",
    "gold_completeness",
    "required_assertions",
    "acceptable_assertions",
    "line_coverage",
    "annotation_status",
    "human_reviewed",
    "evaluation_case_spec",
})
FORBIDDEN_INPUT_VALUES = frozenset({"AGENT_DRAFT_GOLD", "NOT_HUMAN_CONFIRMED"})


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def deterministic_zip_bytes(entries: Mapping[str, bytes]) -> bytes:
    """Build a byte-deterministic ZIP from normalized, unique relative names."""
    names = sorted(entries)
    if not names or len(names) != len(set(names)):
        raise ValueError("ZIP entries must be non-empty and unique")
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or path.as_posix() != name:
                raise ValueError("ZIP entry name is not normalized")
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, entries[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output.getvalue()


def _scan_value(value: Any, path: str = "$") -> list[str]:
    issues = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_INPUT_KEYS or "gold" in key.lower():
                issues.append(f"{path}.{key}: forbidden gold key")
            issues.extend(_scan_value(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            issues.extend(_scan_value(child, f"{path}[{index}]"))
    elif isinstance(value, str) and (
        value in FORBIDDEN_INPUT_VALUES or "gold" in value.lower()
    ):
        issues.append(f"{path}: forbidden gold value")
    return issues


def check_input_zero_gold(entries: Mapping[str, bytes]) -> list[str]:
    """Return public-safe issue locations; never echo source or other values."""
    issues = []
    for name, payload in sorted(entries.items()):
        if "gold" in name.lower():
            issues.append(f"{name}: member name contains gold")
        if name.endswith(".json"):
            try:
                value = json.loads(payload)
            except (UnicodeError, json.JSONDecodeError):
                issues.append(f"{name}: invalid JSON")
                continue
            issues.extend(f"{name}: {item}" for item in _scan_value(value))
    return issues


def check_package_separation(
    input_entries: Mapping[str, bytes],
    gold_entries: Mapping[str, bytes],
    input_sha256: str,
    gold_sha256: str,
) -> list[str]:
    issues = []
    if input_sha256 == gold_sha256:
        issues.append("input and gold package hashes are identical")
    shared = set(input_entries) & set(gold_entries)
    if shared:
        issues.append("input and gold packages share member names")
    issues.extend(check_input_zero_gold(input_entries))
    return issues


def build_blindness_manifest(input_sha256: str, gold_sha256: str) -> dict[str, Any]:
    return {
        "artifact": BLINDNESS_ARTIFACT,
        "case_order": list(CASE_IDS),
        "input_package_sha256": input_sha256,
        "gold_package_sha256": gold_sha256,
        "extractor_access": {"input": True, "gold": False},
        "gold_may_be_opened_after": {"predictions_locked_and_hashed": True},
        "dev2_usage": "TUNING_DATA_NOT_USED_FOR_DEV3_AUTHORING",
        "holdout_opened": False,
    }
