"""Combine the locked Gemini loader with Phase 1 cost and grouping rules."""
from dataclasses import dataclass, replace
import os
from pathlib import Path
import tempfile

from tools.llm_infra.cost_policy import CostPolicy
from tools.llm_infra.quota_state import validate_scope
from tools.story_extraction.gemini_key_pool_v1 import (
    CredentialConfig, GeminiConfigError, _KEY_PATTERN, _parse_dotenv,
    load_runtime_config,
)

DEFAULT_STATE = Path(__file__).resolve().parents[2] / ".local" / "llm_quota_state.sqlite3"


def merged_settings(dotenv_path, environ=None):
    return {**_parse_dotenv(Path(dotenv_path)), **(os.environ if environ is None else environ)}


def state_path(settings):
    return settings.get("LLM_QUOTA_STATE_PATH") or DEFAULT_STATE


@dataclass(frozen=True)
class RoutingConfig:
    credentials: tuple[CredentialConfig, ...]
    model: str
    policy: CostPolicy
    duplicates_dropped: int


def inspect_settings(settings):
    filtered = dict(settings)
    numbered = sorted((int(m[1]), name, value.strip()) for name, value in settings.items()
                      if (m := _KEY_PATTERN.fullmatch(name)) and value.strip())
    seen = set()
    slot_numbers = set()
    duplicates = 0
    for number, name, secret in numbered:
        if number < 1 or number in slot_numbers:
            raise GeminiConfigError("Duplicate or invalid Gemini credential slot number")
        slot_numbers.add(number)
        if secret in seen:
            del filtered[name]
            duplicates += 1
        seen.add(secret)
    with tempfile.TemporaryDirectory() as directory:
        config = load_runtime_config(Path(directory) / "absent", filtered)
    creds = config.credentials
    missing = [c.slot_id.rsplit("_", 1)[1] for c in creds if c.group_id != c.project_label]
    if len(creds) > 1 and missing:
        raise GeminiConfigError("PROJECT_LABEL_REQUIRED: set GEMINI_PROJECT_LABEL_<n> for slots "
                                + ", ".join(missing) + ". Keys of the same Google Cloud project need the "
                                "same label, keys of different projects need different labels. "
                                "The AI Studio API keys page shows the project of each key.")
    policy = CostPolicy.from_settings(settings, creds)
    public_models = set(policy.confirmed_models) | {m.strip() for m in config.model.split(",") if m.strip()}
    if any(secret in value for secret in seen for value in (*public_models, str(state_path(settings)))):
        raise GeminiConfigError("Public configuration contains credential material")
    try:
        validate_scope(*public_models, *(c.group_id for c in creds))
    except ValueError:
        raise GeminiConfigError("Invalid model or project alias") from None
    return RoutingConfig(creds, config.model, policy, duplicates)


def load_routing_config(dotenv_path, environ=None, *, model=None):
    settings = merged_settings(dotenv_path, environ)
    if model:
        settings["GEMINI_MODEL"] = model
    config = inspect_settings(settings)
    if config.credentials:
        config.policy.check_models([m.strip() for m in config.model.split(",") if m.strip()])
    return replace(config, credentials=config.policy.eligible_credentials(config.credentials))
