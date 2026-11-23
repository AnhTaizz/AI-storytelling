"""Owner attestations for free-only Gemini calls."""
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from tools.llm_infra.gemini_free_models_v1 import FREE_TIER_TEXT_MODELS, SOURCE_URL, VERIFIED_ON
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError, UNKNOWN_PROJECT_LABEL

STATUSES = ("FREE_TIER_CONFIRMED", "UNVERIFIED", "BILLING_ENABLED")
NOTICE = ("MAX_PAID_SPEND_USD=0 is an application limit only and does not stop Google "
          "from charging a project that has billing enabled. An API key cannot verify billing.")


def _flag(settings, name, default):
    value = settings.get(name, default).strip().lower()
    if value not in ("true", "false"):
        raise GeminiConfigError(f"Expected true or false for {name}")
    return value == "true"


def require_free_only(settings, phase):
    free = _flag(settings, "LLM_FREE_ONLY", "true")
    paid = _flag(settings, "LLM_ALLOW_PAID", "false")
    try:
        spend = Decimal(settings.get("MAX_PAID_SPEND_USD", "0"))
    except InvalidOperation:
        raise GeminiConfigError("Invalid MAX_PAID_SPEND_USD") from None
    if not spend.is_finite() or not spend.is_zero() or not free or paid:
        raise GeminiConfigError(f"Paid use is not supported in {phase}")


@dataclass(frozen=True)
class CostPolicy:
    billing: dict
    billing_sources: dict
    effective_allowlist: frozenset
    ignored_models: frozenset

    @classmethod
    def from_settings(cls, settings, credentials):
        require_free_only(settings, "Phase 1")
        confirmation = settings.get("GEMINI_KEYS_FREE_TIER_CONFIRMED", "").strip()
        confirmed = not confirmation or _flag(settings, "GEMINI_KEYS_FREE_TIER_CONFIRMED", "true")
        default = "FREE_TIER_CONFIRMED" if confirmed else "UNVERIFIED"
        default_source = "global_confirmation" if confirmation else "owner_standing_decision"
        sources = {}
        groups = {}
        billing = {}
        for slot in credentials:
            number = slot.slot_id.rsplit("_", 1)[1]
            declared = settings.get("GEMINI_PROJECT_BILLING_" + number, "").strip()
            status = declared or default
            sources[slot.slot_id] = "per_slot" if declared else default_source
            if status not in STATUSES:
                raise GeminiConfigError("Invalid GEMINI_PROJECT_BILLING_" + number)
            labeled = slot.project_label != UNKNOWN_PROJECT_LABEL
            if labeled and groups.setdefault(slot.project_label, status) != status:
                raise GeminiConfigError("Conflicting billing confirmations for a shared project label")
            billing[slot.slot_id] = status
        override = settings.get("GEMINI_FREE_MODELS", "").strip()
        models = frozenset(m.strip() for m in override.split(",") if m.strip())
        allowed = frozenset(FREE_TIER_TEXT_MODELS)
        effective = allowed & models if override else allowed
        return cls(billing, sources, effective, models - allowed)

    def eligible_credentials(self, credentials):
        eligible = tuple(c for c in credentials if self.billing[c.slot_id] == "FREE_TIER_CONFIRMED")
        if not eligible:
            raise GeminiConfigError("NO_ELIGIBLE_KEY: no eligible free-tier Gemini key")
        return eligible

    def check_models(self, models):
        missing = sorted(set(models) - self.effective_allowlist)
        if missing or not models or not self.effective_allowlist:
            allowed = ", ".join(sorted(self.effective_allowlist)) or "(none)"
            raise GeminiConfigError(f"MODEL_NOT_FREE_TIER: {', '.join(missing) or '(empty chain)'}; "
                                    f"allowed: {allowed}; {SOURCE_URL} ({VERIFIED_ON})")

    def public_summary(self):
        counts = Counter(self.billing.values())
        return {"billing_status_counts": {s: counts[s] for s in STATUSES},
                "billing_status_sources": self.billing_sources, "billing_verified_by_system": False,
                "free_models_source": SOURCE_URL, "free_models_verified_on": VERIFIED_ON,
                "effective_allowlist": sorted(self.effective_allowlist), "ignored_models": sorted(self.ignored_models),
                "LLM_FREE_ONLY": True, "LLM_ALLOW_PAID": False, "MAX_PAID_SPEND_USD": 0, "notice": NOTICE}
