"""Load owner-declared Free plan Groq keys and the reviewed model chain."""
from collections import Counter
from dataclasses import dataclass, field
import re

from tools.llm_infra.cost_policy import _flag, require_free_only
from tools.llm_infra.gemini_config import merged_settings, state_path
from tools.llm_infra.groq_free_models_v1 import (
    DEFAULT_MODEL_CHAIN, FREE_TIER_TEXT_MODELS, SOURCE_URL, VERIFIED_ON,
)
from tools.llm_infra.quota_state import validate_scope
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError


GROQ_KEY_PATTERN = re.compile(r"GROQ_API_KEY_([0-9]+)")
PLAN_STATUSES = ("FREE_PLAN_CONFIRMED", "UNVERIFIED", "PAID_PLAN")


@dataclass(frozen=True, slots=True)
class GroqSlot:
    slot_id: str
    scope: str
    _api_key: str = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class GroqRoutingConfig:
    slots: tuple[GroqSlot, ...]
    model_chain: tuple[str, ...]
    model_source: str
    max_rate_limit_hops: int
    duplicates_dropped: int
    effective_allowlist: frozenset[str]
    ignored_models: frozenset[str]
    _scopes: int
    _labels: int
    _plan_counts: tuple[int, ...]
    _secrets: tuple[str, ...] = field(repr=False, compare=False)

    def check_models(self, models):
        missing = sorted(set(models) - self.effective_allowlist)
        if missing or not models:
            allowed = ", ".join(sorted(self.effective_allowlist)) or "(none)"
            rejected = ", ".join(missing) or "(empty chain)"
            raise GeminiConfigError(f"MODEL_NOT_FREE_TIER: {rejected}. "
                                    f"Allowed models: {allowed}. {SOURCE_URL} ({VERIFIED_ON})")

    def check_eligible(self):
        if not self.slots:
            raise GeminiConfigError("NO_ELIGIBLE_KEY: no eligible Free plan Groq key")

    def public_summary(self):
        return {
            "keys_configured": sum(self._plan_counts) + self.duplicates_dropped,
            "keys_eligible": len(self.slots),
            "duplicates_dropped": self.duplicates_dropped,
            "key_scopes": self._scopes,
            "labels_used": self._labels,
            "model_chain": list(self.model_chain),
            "model_source": self.model_source,
            "max_rate_limit_hops": self.max_rate_limit_hops,
            "effective_allowlist": sorted(self.effective_allowlist),
            "ignored_models": sorted(self.ignored_models),
            "free_models_source": SOURCE_URL,
            "free_models_verified_on": VERIFIED_ON,
            "plan_status_counts": dict(zip(PLAN_STATUSES, self._plan_counts)),
            "plan_verified_by_system": False,
            "notice": "An API key cannot show the Groq plan. The Developer plan charges per token.",
        }


def _models(value):
    return tuple(model.strip() for model in value.split(",") if model.strip())


def _read_groq_settings(settings, model=None):
    """Collect diagnostics first so the CLI can show the chain even when it is blocked."""
    require_free_only(settings, "Phase 2")
    global_flag = settings.get("GROQ_KEYS_FREE_PLAN_CONFIRMED", "").strip()
    confirmed = not global_flag or _flag(settings, "GROQ_KEYS_FREE_PLAN_CONFIRMED", "true")
    default_plan = "FREE_PLAN_CONFIRMED" if confirmed else "UNVERIFIED"

    numbered = sorted((int(match[1]), match[1], value.strip())
                      for name, value in settings.items()
                      if (match := GROQ_KEY_PATTERN.fullmatch(name)) and value.strip())
    numbers = [number for number, _, _ in numbered]
    if 0 in numbers or len(set(numbers)) != len(numbers):
        raise GeminiConfigError("Duplicate or invalid Groq credential slot number")

    secrets = set()
    slots = []
    unlabeled = set()
    labeled_plans = {}
    plans = Counter()
    duplicates = 0
    for number, suffix, secret in numbered:
        if secret in secrets:
            duplicates += 1
            continue
        secrets.add(secret)
        slot_id = f"groq_slot_{number}"
        label = settings.get(f"GROQ_ORG_LABEL_{suffix}", "").strip()
        plan = settings.get(f"GROQ_ORG_PLAN_{suffix}", "").strip() or default_plan
        if plan not in PLAN_STATUSES:
            raise GeminiConfigError("Invalid Groq organization plan declaration")
        if label:
            if labeled_plans.setdefault(label, plan) != plan:
                raise GeminiConfigError("Conflicting plan declarations for a shared Groq organization label")
        else:
            unlabeled.add(slot_id)
        plans[plan] += 1
        if plan == "FREE_PLAN_CONFIRMED":
            slots.append(GroqSlot(slot_id, label or slot_id, secret))

    scopes = unlabeled | labeled_plans.keys()
    if unlabeled & labeled_plans.keys():
        raise GeminiConfigError("Groq organization label conflicts with an unlabeled scope")
    override = settings.get("GROQ_FREE_MODELS", "").strip()
    reviewed = frozenset(FREE_TIER_TEXT_MODELS)
    local_models = frozenset(_models(override))
    effective = reviewed & local_models if override else reviewed
    ignored = local_models - reviewed
    configured = (model or "").strip() or settings.get("GROQ_MODEL", "").strip()
    chain = _models(configured) if configured else DEFAULT_MODEL_CHAIN
    public_values = set(chain) | local_models | reviewed | scopes | {f"groq_slot_{n}" for n in numbers}
    if any(secret in value for secret in secrets for value in (*public_values, str(state_path(settings)))):
        raise GeminiConfigError("Public Groq configuration contains credential material")
    try:
        validate_scope(*scopes)
    except ValueError:
        raise GeminiConfigError("Invalid Groq organization scope") from None
    try:
        hops = int(settings.get("GROQ_MAX_RATE_LIMIT_HOPS", "3"))
    except ValueError:
        hops = 0
    if hops < 1:
        raise GeminiConfigError("GROQ_MAX_RATE_LIMIT_HOPS must be an integer >= 1")
    return GroqRoutingConfig(
        tuple(slots), chain, "configured" if configured else "default", hops, duplicates,
        effective, ignored, len(scopes), len(labeled_plans), tuple(plans[s] for s in PLAN_STATUSES),
        tuple(sorted(secrets, key=len, reverse=True)),
    )


def inspect_groq_settings(settings, model=None):
    config = _read_groq_settings(settings, model)
    config.check_models(config.model_chain)
    return config


def load_groq_routing_config(dotenv_path, environ=None, *, model=None):
    config = inspect_groq_settings(merged_settings(dotenv_path, environ), model)
    config.check_eligible()
    return config
