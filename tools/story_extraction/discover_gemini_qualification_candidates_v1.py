"""Discover a deterministic Gemini transport-qualification candidate set."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Iterable, Optional

from tools.story_extraction.gemini_errors_v1 import (
    ErrorCategory,
    classify_error,
    sanitized_failure_metadata,
)
from tools.story_extraction.gemini_key_pool_v1 import CredentialConfig, load_runtime_config


DISCOVERY_VERSION = "M4_GEMINI_PROVIDER_CANDIDATE_DISCOVERY_V1"
_UNSTABLE_MARKERS = ("preview", "experimental", "-exp", "latest")
_NON_TEXT_MARKERS = (
    "embedding",
    "imagen",
    "image-generation",
    "veo",
    "tts",
    "audio",
    "live",
)


def _model_id(model: Any) -> str:
    name = getattr(model, "name", "")
    return name.removeprefix("models/") if isinstance(name, str) else ""


def _version_key(name: str) -> tuple[int, int, int]:
    match = re.search(r"gemini-(\d+)(?:\.(\d+))?", name)
    major, minor = (int(match.group(1)), int(match.group(2) or 0)) if match else (0, 0)
    revision = re.search(r"-(\d{3})$", name)
    # Prefer the stable family alias over a numbered revision at equal generation.
    return major, minor, 10_000 if revision is None else int(revision.group(1))


def _supports_text_generation(model: Any) -> bool:
    name = _model_id(model).lower()
    if not name or any(marker in name for marker in _NON_TEXT_MARKERS):
        return False
    actions = getattr(model, "supported_actions", None) or []
    normalized = {str(action).replace("_", "").lower() for action in actions}
    return "generatecontent" in normalized


def _is_stable(model: Any) -> bool:
    name = _model_id(model).lower()
    if any(marker in name for marker in _UNSTABLE_MARKERS):
        return False
    return not bool(getattr(model, "deprecated", False))


def _safe_metadata(model: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"model_id": _model_id(model)}
    for public_name, attribute in (
        ("display_name", "display_name"),
        ("version", "version"),
        ("input_token_limit", "input_token_limit"),
        ("output_token_limit", "output_token_limit"),
    ):
        value = getattr(model, attribute, None)
        if isinstance(value, (str, int, float, bool)):
            result[public_name] = value
    actions = getattr(model, "supported_actions", None) or []
    result["supported_actions"] = sorted(str(action) for action in actions)
    result["stable_filter"] = _is_stable(model)
    result["text_generation_capable"] = _supports_text_generation(model)
    return result


def select_candidates(models: Iterable[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    eligible = [model for model in models if _is_stable(model) and _supports_text_generation(model)]
    normal_flash = [
        model
        for model in eligible
        if "flash" in _model_id(model).lower() and "lite" not in _model_id(model).lower()
    ]
    normal_flash.sort(key=lambda model: _version_key(_model_id(model)), reverse=True)

    generations: list[Any] = []
    seen_versions: set[tuple[int, int]] = set()
    for model in normal_flash:
        key = _version_key(_model_id(model))[:2]
        if key in seen_versions:
            continue
        seen_versions.add(key)
        generations.append(model)

    lite = [
        model
        for model in eligible
        if "flash-lite" in _model_id(model).lower()
        or ("lite" in _model_id(model).lower() and "flash" in _model_id(model).lower())
    ]
    lite.sort(key=lambda model: _version_key(_model_id(model)), reverse=True)

    chosen: list[tuple[str, Any]] = []
    if generations:
        chosen.append(("A_LATEST_STABLE_FLASH", generations[0]))
    if len(generations) > 1:
        chosen.append(("B_PREVIOUS_STABLE_FLASH_GENERATION", generations[1]))
    if lite:
        chosen.append(("C_STABLE_FLASH_LITE", lite[0]))

    candidate_metadata = []
    seen_names: set[str] = set()
    for role, model in chosen:
        name = _model_id(model)
        if name in seen_names or len(candidate_metadata) >= 3:
            continue
        seen_names.add(name)
        candidate_metadata.append({"selection_role": role, **_safe_metadata(model)})
    eligible_metadata = sorted(
        (_safe_metadata(model) for model in eligible),
        key=lambda item: item["model_id"],
    )
    return candidate_metadata, eligible_metadata


def _list_models(credential: CredentialConfig) -> list[Any]:
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=credential._api_key,
        http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
    )
    try:
        return list(client.models.list())
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def discover(output: Path) -> dict[str, Any]:
    config = load_runtime_config()
    if not config.credentials:
        raise RuntimeError("No Gemini credential slots configured")
    ordered = sorted(config.credentials, key=lambda item: int(item.slot_id.rsplit("_", 1)[1]))
    attempts: list[dict[str, str]] = []
    selected: Optional[CredentialConfig] = None
    models: list[Any] = []
    for index, credential in enumerate(ordered[:2]):
        try:
            models = _list_models(credential)
            selected = credential
            attempts.append({"slot_id": credential.slot_id, "result": "SUCCESS"})
            break
        except Exception as error:
            now = datetime.now(timezone.utc).timestamp()
            safe = sanitized_failure_metadata(error, now)
            attempts.append(
                {
                    "slot_id": credential.slot_id,
                    "result": str(safe["category"]),
                    "fingerprint": str(safe["fingerprint"]),
                }
            )
            # Exactly one move is allowed, and only when the first slot is auth-failing.
            if index != 0 or classify_error(error) != ErrorCategory.AUTH_FAILURE:
                raise RuntimeError(
                    f"Gemini model discovery failed safely: {safe['fingerprint']}"
                ) from None
    if selected is None:
        raise RuntimeError("No usable Gemini qualification credential")

    candidates, eligible = select_candidates(models)
    if not candidates:
        raise RuntimeError("No stable text-generation qualification candidate discovered")
    report = {
        "task": "M4-04B1Q-GEMINI-PROVIDER-CAPACITY-QUALIFICATION",
        "discovery": DISCOVERY_VERSION,
        "discovered_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "credential_topology": "UNKNOWN",
        "credential_selection_rule": "lowest_numbered_configured_valid_slot_one_auth_move_maximum",
        "credential_attempts": attempts,
        "locked_credential_slot": selected.slot_id,
        "official_live_credentials_used": 1,
        "multi_project_failover": "DISABLED",
        "accessible_model_count": len(models),
        "eligible_stable_text_models": eligible,
        "candidate_models": candidates,
        "candidate_model_ids": [item["model_id"] for item in candidates],
        "candidate_set_locked_before_qualification_outcomes": True,
        "extraction_model_selected": False,
    }
    serialized = json.dumps(report, sort_keys=True)
    if selected._api_key in serialized:
        raise RuntimeError("Credential leak guard rejected discovery report")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    report = discover(args.output)
    print(f"Locked credential slot: {report['locked_credential_slot']}")
    print("Candidate models: " + ", ".join(report["candidate_model_ids"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

