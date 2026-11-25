"""Load paired Workers AI credentials and enforce the Workers Free policy."""
from collections import Counter
from dataclasses import dataclass, field
import re
from urllib.parse import quote

from tools.llm_infra.cloudflare_free_models_v1 import (
    ACTIVE_MODEL_CHAIN, ACTIVE_NEURON_PRICES, ACTIVE_REVIEWED_ON, DAILY_FREE_NEURONS, SOURCE_URL,
    VERIFICATION_NOTE,
)
from tools.llm_infra.cost_policy import _flag, require_free_only
from tools.llm_infra.gemini_config import merged_settings, state_path
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError


CREDENTIAL_PATTERN = re.compile(r"CLOUDFLARE_(ACCOUNT_ID|API_TOKEN)(?:_([0-9]+))?")
PLAN_STATUSES = ("WORKERS_FREE_CONFIRMED", "UNVERIFIED", "WORKERS_PAID")
NOTICE = ("A token cannot show the Workers plan. On Workers Paid, usage beyond 10,000 Neurons per day "
          "is billed. Neuron use is estimated locally from token counts.")


def cloudflare_secrets(settings):
    secrets = set()
    for name, value in settings.items():
        if (match := CREDENTIAL_PATTERN.fullmatch(name)) and (secret := value.strip()):
            secrets.add(secret)
            if match[1] == "ACCOUNT_ID":
                secrets.add(quote(secret, safe=""))
    return tuple(sorted(secrets, key=len, reverse=True))


@dataclass(frozen=True, slots=True)
class CloudflareSlot:
    slot_id: str
    scope: str
    _account_id: str = field(repr=False, compare=False)
    _api_token: str = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class CloudflareRoutingConfig:
    slots: tuple[CloudflareSlot, ...]
    model_chain: tuple[str, ...]
    model_source: str
    effective_allowlist: frozenset[str]
    ignored_models: frozenset[str]
    daily_neuron_budget: int
    max_rate_limit_hops: int
    duplicates_dropped: int
    account_scopes: tuple[str, ...]
    _plan_counts: tuple[int, ...]
    _secrets: tuple[str, ...] = field(repr=False, compare=False)

    def check_models(self, models):
        if not models or set(models) - self.effective_allowlist:
            raise GeminiConfigError(f"MODEL_NOT_FREE_TIER: {VERIFICATION_NOTE} "
                                    f"Any CLOUDFLARE_FREE_MODELS restriction also applies. "
                                    f"{SOURCE_URL} ({ACTIVE_REVIEWED_ON})")

    def check_eligible(self):
        if not self.slots:
            raise GeminiConfigError("NO_ELIGIBLE_KEY: no eligible Workers Free credential pair")

    def public_summary(self):
        return {
            "keys_configured": sum(self._plan_counts) + self.duplicates_dropped,
            "keys_eligible": len(self.slots),
            "duplicates_dropped": self.duplicates_dropped,
            "key_scopes": len(self.account_scopes),
            "plan_status_counts": dict(zip(PLAN_STATUSES, self._plan_counts)),
            "plan_verified_by_system": False,
            "model_chain": list(self.model_chain),
            "model_source": self.model_source,
            "effective_allowlist": sorted(self.effective_allowlist),
            "ignored_models": sorted(self.ignored_models),
            "free_model_rule": VERIFICATION_NOTE,
            "free_models_source": SOURCE_URL,
            "free_models_verified_on": ACTIVE_REVIEWED_ON,
            "daily_neuron_budget": self.daily_neuron_budget,
            "max_rate_limit_hops": self.max_rate_limit_hops,
            "notice": NOTICE,
        }


def _credential_pairs(settings):
    unnumbered = {}
    numbered = {}
    for name, value in settings.items():
        if not (match := CREDENTIAL_PATTERN.fullmatch(name)) or not (value := value.strip()):
            continue
        kind, suffix = match.groups()
        if suffix is None:
            unnumbered[kind] = value
            continue
        try:
            number = int(suffix)
        except ValueError:
            raise GeminiConfigError("Invalid Cloudflare credential slot number") from None
        original_suffix, parts = numbered.setdefault(number, (suffix, {}))
        if not number or original_suffix != suffix:
            raise GeminiConfigError("Duplicate or invalid Cloudflare credential slot number")
        parts[kind] = value
    if unnumbered:
        if len(unnumbered) != 2:
            raise GeminiConfigError("Incomplete Cloudflare credential pair for slot 1 (unnumbered)")
        if 1 in numbered:
            suffix, parts = numbered[1]
            if suffix != "1":
                raise GeminiConfigError("Duplicate or invalid Cloudflare credential slot number")
            if len(parts) == 2 and parts != unnumbered:
                raise GeminiConfigError("CLOUDFLARE_*_1 conflicts with the unnumbered CLOUDFLARE_* pair")
        yield 1, "1", unnumbered["ACCOUNT_ID"], unnumbered["API_TOKEN"]
    for number, (suffix, parts) in sorted(numbered.items()):
        if len(parts) != 2:
            raise GeminiConfigError(f"Incomplete Cloudflare credential pair for slot {number}")
        yield number, suffix, parts["ACCOUNT_ID"], parts["API_TOKEN"]


def _integer_setting(settings, name, default, maximum=None):
    try:
        value = int(settings.get(name, str(default)))
    except ValueError:
        value = 0
    if value < 1 or (maximum is not None and value > maximum):
        bounds = ">= 1" if maximum is None else f"in 1..{maximum}"
        raise GeminiConfigError(f"{name} must be an integer {bounds}")
    return value


def inspect_cloudflare_settings(settings, model=None, *, validate_models=True):
    require_free_only(settings, "Phase 4")
    confirmation = settings.get("CLOUDFLARE_KEYS_FREE_PLAN_CONFIRMED", "").strip()
    confirmed = not confirmation or _flag(settings, "CLOUDFLARE_KEYS_FREE_PLAN_CONFIRMED", "true")
    default_plan = PLAN_STATUSES[0] if confirmed else "UNVERIFIED"
    secrets = cloudflare_secrets(settings)
    accounts = {}
    pairs = set()
    slots = []
    plans = Counter()
    duplicates = 0
    for number, suffix, account_id, token in _credential_pairs(settings):
        plan = settings.get(f"CLOUDFLARE_PLAN_{suffix}", "").strip() or default_plan
        if plan not in PLAN_STATUSES:
            raise GeminiConfigError(f"Invalid Cloudflare plan declaration for slot {number}")
        scope, account_plan = accounts.setdefault(account_id, (f"cloudflare_account_{number}", plan))
        if account_plan != plan:
            raise GeminiConfigError("Conflicting Cloudflare plan declarations for one account")
        if (account_id, token) in pairs:
            duplicates += 1
            continue
        pairs.add((account_id, token))
        plans[plan] += 1
        if plan == PLAN_STATUSES[0]:
            slots.append(CloudflareSlot(f"cloudflare_slot_{number}", scope, account_id, token))

    override = settings.get("CLOUDFLARE_FREE_MODELS", "").strip()
    reviewed = frozenset(ACTIVE_NEURON_PRICES)
    local_models = frozenset(part.strip() for part in override.split(",") if part.strip())
    configured = (model or "").strip() or settings.get("CLOUDFLARE_MODEL", "").strip()
    chain = tuple(part.strip() for part in configured.split(",")) if configured else ACTIVE_MODEL_CHAIN
    scopes = tuple(scope for scope, _ in accounts.values())
    public_values = (*chain, *local_models, *reviewed, *scopes, *(slot.slot_id for slot in slots),
                     str(state_path(settings)))
    if any(secret in value for secret in secrets for value in public_values):
        raise GeminiConfigError("Public Cloudflare configuration contains credential material")
    config = CloudflareRoutingConfig(
        tuple(slots), chain, "configured" if configured else "default",
        reviewed & local_models if override else reviewed, local_models - reviewed,
        _integer_setting(settings, "CLOUDFLARE_DAILY_NEURON_BUDGET", 9000, DAILY_FREE_NEURONS),
        _integer_setting(settings, "CLOUDFLARE_MAX_RATE_LIMIT_HOPS", 2), duplicates,
        scopes, tuple(plans[plan] for plan in PLAN_STATUSES), secrets,
    )
    if validate_models:
        config.check_models(config.model_chain)
    return config


def load_cloudflare_routing_config(dotenv_path, environ=None, *, model=None):
    config = inspect_cloudflare_settings(merged_settings(dotenv_path, environ), model)
    config.check_eligible()
    return config
