"""Combine the locked Gemini loader with Phase 1 cost and grouping rules."""
from dataclasses import dataclass, replace
import os
from pathlib import Path
import tempfile

from tools.llm_infra.cost_policy import CostPolicy
from tools.llm_infra.gemini_free_models_v1 import DEFAULT_MODEL_CHAIN
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
    model_source: str
    max_rate_limit_hops: int
    policy: CostPolicy
    duplicates_dropped: int


def inspect_settings(settings, model=None):
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
    # An unlabeled key is its own quota scope, so the owner need not map keys to projects.
    creds = config.credentials
    policy = CostPolicy.from_settings(settings, creds)
    configured = (model or "").strip() or config.model
    selected = configured or ",".join(DEFAULT_MODEL_CHAIN)
    chain = {m.strip() for m in selected.split(",") if m.strip()}
    public_models = chain | policy.effective_allowlist | policy.ignored_models
    if any(secret in value for secret in seen for value in (*public_models, str(state_path(settings)))):
        raise GeminiConfigError("Public configuration contains credential material")
    try:
        validate_scope(*public_models, *(c.group_id for c in creds))
    except ValueError:
        raise GeminiConfigError("Invalid model or project alias") from None
    try:
        hops = int(settings.get("GEMINI_MAX_RATE_LIMIT_HOPS", "3"))
    except ValueError:
        hops = 0
    if hops < 1:
        raise GeminiConfigError("GEMINI_MAX_RATE_LIMIT_HOPS must be an integer >= 1")
    return RoutingConfig(creds, selected, "configured" if configured else "default", hops, policy, duplicates)


def load_routing_config(dotenv_path, environ=None, *, model=None):
    config = inspect_settings(merged_settings(dotenv_path, environ), model)
    return replace(config, credentials=config.policy.eligible_credentials(config.credentials))
