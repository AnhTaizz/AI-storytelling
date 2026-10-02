"""Discover the latest accessible non-preview stable Gemini Flash model."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Optional

from tools.story_extraction.gemini_errors_v1 import sanitized_failure_metadata
from tools.story_extraction.gemini_key_pool_v1 import load_runtime_config
from tools.story_extraction.gemini_resilience_v1_1 import live_safe_credentials


_UNSTABLE_MARKERS = (
    "preview",
    "experimental",
    "-exp",
    "latest",
    "thinking",
    "image",
    "tts",
    "audio",
    "live",
)


def _model_id(value: Any) -> str:
    name = getattr(value, "name", "")
    if not isinstance(name, str):
        return ""
    return name.removeprefix("models/")


def _is_stable_flash(model: Any) -> bool:
    name = _model_id(model).lower()
    if "flash" not in name or "flash-lite" in name:
        return False
    if any(marker in name for marker in _UNSTABLE_MARKERS):
        return False
    actions = getattr(model, "supported_actions", None) or []
    normalized = {str(action).replace("_", "").lower() for action in actions}
    return not normalized or "generatecontent" in normalized


def _version_key(name: str) -> tuple[int, ...]:
    match = re.search(r"gemini-(\d+)(?:\.(\d+))?", name)
    version = (int(match.group(1)), int(match.group(2) or 0)) if match else (0, 0)
    # Prefer a stable numbered revision over an unnumbered alias only when model
    # generations are equal; both remain non-preview provider-listed models.
    revision = re.search(r"-(\d{3})$", name)
    return (*version, int(revision.group(1)) if revision else 10_000)


def discover(output: Path) -> dict[str, Any]:
    from google import genai
    from google.genai import types

    config = load_runtime_config()
    selected_credentials = live_safe_credentials(config.credentials)
    if not selected_credentials:
        raise RuntimeError("No Gemini credential slots configured")
    credential = selected_credentials[0]
    client = genai.Client(
        api_key=credential._api_key,
        http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
    )
    try:
        models = list(client.models.list())
    except Exception as error:
        safe = sanitized_failure_metadata(error, datetime.now(timezone.utc).timestamp())
        raise RuntimeError(
            f"Gemini model discovery failed safely: {safe['fingerprint']}"
        ) from None
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    candidates = sorted(
        {_model_id(model) for model in models if _is_stable_flash(model)},
        key=_version_key,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("No accessible non-preview stable Gemini Flash model discovered")
    report = {
        "task": "M4-04B1R-TRANSPORT-SMOKE-MODEL-DISCOVERY",
        "discovered_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "selection_rule": "latest_accessible_non_preview_stable_flash_excluding_flash_lite",
        "selected_transport_smoke_model": candidates[0],
        "stable_flash_candidates": candidates,
        "credential_slot_used": credential.slot_id,
        "project_label": credential.project_label,
        "extraction_model_selected": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    report = discover(args.output)
    print(f"Selected transport-smoke model: {report['selected_transport_smoke_model']}")
    print(f"Stable Flash candidates: {len(report['stable_flash_candidates'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

