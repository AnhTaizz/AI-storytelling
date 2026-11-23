"""Load numbered OpenRouter keys and a chain restricted to free models."""
from dataclasses import dataclass, field
import re

from tools.llm_infra.cost_policy import require_free_only
from tools.llm_infra.gemini_config import merged_settings, state_path
from tools.llm_infra.openrouter_free_models_v1 import (
    DEFAULT_MODEL_CHAIN, SOURCE_URL, VERIFICATION_NOTE, VERIFIED_ON, is_free_model,
)
from tools.llm_infra.quota_state import validate_scope
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError


OPENROUTER_KEY_PATTERN = re.compile(r"OPENROUTER_API_KEY_([0-9]+)")
DEFAULT_ACCOUNT_SCOPE = "openrouter_account"
DATA_COLLECTION_VALUES = ("allow", "deny")
NOTICE = ("Free-model limits are account-wide; extra keys or accounts do not raise them. "
          "A negative balance can block free models.")


@dataclass(frozen=True, slots=True)
class OpenRouterSlot:
    slot_id: str
    scope: str
    _api_key: str = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class OpenRouterRoutingConfig:
    slots: tuple[OpenRouterSlot, ...]
    model_chain: tuple[str, ...]
    model_source: str
    max_rate_limit_hops: int
    duplicates_dropped: int
    effective_allowlist: frozenset[str] | None
    ignored_models: frozenset[str]
    data_collection: str | None
    _labels: int
    _secrets: tuple[str, ...] = field(repr=False, compare=False)

    def check_models(self, models):
        missing = [model for model in models if not is_free_model(model)
                   or (self.effective_allowlist is not None and model not in self.effective_allowlist)]
        if missing or not models:
            raise GeminiConfigError(f"MODEL_NOT_FREE_TIER: {VERIFICATION_NOTE} "
                                    f"Any OPENROUTER_FREE_MODELS restriction also applies. "
                                    f"{SOURCE_URL} ({VERIFIED_ON})")

    def check_eligible(self):
        if not self.slots:
            raise GeminiConfigError("NO_ELIGIBLE_KEY: no OpenRouter API key configured")

    def public_summary(self):
        return {
            "keys_configured": len(self.slots) + self.duplicates_dropped,
            "keys_eligible": len(self.slots),
            "duplicates_dropped": self.duplicates_dropped,
            "key_scopes": len({slot.scope for slot in self.slots}),
            "labels_used": self._labels,
            "model_chain": list(self.model_chain),
            "model_source": self.model_source,
            "max_rate_limit_hops": self.max_rate_limit_hops,
            "effective_allowlist": (sorted(self.effective_allowlist)
                                    if self.effective_allowlist is not None else None),
            "ignored_models": sorted(self.ignored_models),
            "free_model_rule": VERIFICATION_NOTE,
            "free_models_source": SOURCE_URL,
            "free_models_verified_on": VERIFIED_ON,
            "data_collection": self.data_collection,
            "notice": NOTICE,
        }


def _read_openrouter_settings(settings, model):
    require_free_only(settings, "Phase 3")
    try:
        numbered = sorted((int(match[1]), match[1], value.strip())
                          for name, value in settings.items()
                          if (match := OPENROUTER_KEY_PATTERN.fullmatch(name)) and value.strip())
    except ValueError:
        raise GeminiConfigError("Invalid OpenRouter credential slot number") from None
    numbers = [number for number, _, _ in numbered]
    if 0 in numbers or len(set(numbers)) != len(numbers):
        raise GeminiConfigError("Duplicate or invalid OpenRouter credential slot number")

    secrets = set()
    slots = []
    labels = set()
    duplicates = 0
    for number, suffix, secret in numbered:
        if secret in secrets:
            duplicates += 1
            continue
        secrets.add(secret)
        label = settings.get(f"OPENROUTER_ACCOUNT_LABEL_{suffix}", "").strip()
        if label:
            labels.add(label)
        slots.append(OpenRouterSlot(f"openrouter_slot_{number}", label or DEFAULT_ACCOUNT_SCOPE, secret))

    override = settings.get("OPENROUTER_FREE_MODELS", "").strip()
    local_models = frozenset(part.strip() for part in override.split(",") if part.strip())
    allowed = frozenset(model_id for model_id in local_models if is_free_model(model_id))
    configured = (model or "").strip() or settings.get("OPENROUTER_MODEL", "").strip()
    chain = tuple(part.strip() for part in configured.split(",")) if configured else DEFAULT_MODEL_CHAIN
    scopes = {slot.scope for slot in slots}
    public_values = set(chain) | local_models | scopes | {slot.slot_id for slot in slots}
    if any(secret in value for secret in secrets for value in (*public_values, str(state_path(settings)))):
        raise GeminiConfigError("Public OpenRouter configuration contains credential material")
    try:
        validate_scope(*scopes)
    except ValueError:
        raise GeminiConfigError("Invalid OpenRouter account scope") from None

    data_collection = settings.get("OPENROUTER_DATA_COLLECTION", "").strip() or None
    if data_collection is not None and data_collection not in DATA_COLLECTION_VALUES:
        raise GeminiConfigError("OPENROUTER_DATA_COLLECTION must be allow or deny")
    try:
        hops = int(settings.get("OPENROUTER_MAX_RATE_LIMIT_HOPS", "2"))
    except ValueError:
        hops = 0
    if hops < 1:
        raise GeminiConfigError("OPENROUTER_MAX_RATE_LIMIT_HOPS must be an integer >= 1")
    return OpenRouterRoutingConfig(
        tuple(slots), chain, "configured" if configured else "default", hops, duplicates,
        allowed if override else None, local_models - allowed, data_collection, len(labels),
        tuple(sorted(secrets, key=len, reverse=True)),
    )


def inspect_openrouter_settings(settings, model=None, *, validate_models=True):
    config = _read_openrouter_settings(settings, model)
    if validate_models:
        config.check_models(config.model_chain)
    return config


def load_openrouter_routing_config(dotenv_path, environ=None, *, model=None):
    config = inspect_openrouter_settings(merged_settings(dotenv_path, environ), model)
    config.check_eligible()
    return config
