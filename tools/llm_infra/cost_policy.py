"""Owner attestations for free-only Gemini calls."""
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError, UNKNOWN_PROJECT_LABEL

STATUSES = ("FREE_TIER_CONFIRMED", "UNVERIFIED", "BILLING_ENABLED")
NOTICE = ("MAX_PAID_SPEND_USD=0 is an application limit only and does not stop Google "
          "from charging a project that has billing enabled.")


def _flag(settings, name, default):
    value = settings.get(name, default).strip().lower()
    if value not in ("true", "false"):
        raise GeminiConfigError(f"Expected true or false for {name}")
    return value == "true"


@dataclass(frozen=True)
class CostPolicy:
    billing: dict
    confirmed_models: frozenset

    @classmethod
    def from_settings(cls, settings, credentials):
        free = _flag(settings, "LLM_FREE_ONLY", "true")
        paid = _flag(settings, "LLM_ALLOW_PAID", "false")
        try:
            spend = Decimal(settings.get("MAX_PAID_SPEND_USD", "0"))
        except InvalidOperation:
            raise GeminiConfigError("Invalid MAX_PAID_SPEND_USD") from None
        if not spend.is_finite() or not spend.is_zero() or not free or paid:
            raise GeminiConfigError("Paid use is not supported in Phase 1")
        groups = {}
        billing = {}
        for slot in credentials:
            number = slot.slot_id.rsplit("_", 1)[1]
            status = settings.get("GEMINI_PROJECT_BILLING_" + number, "").strip() or "UNVERIFIED"
            if status not in STATUSES:
                raise GeminiConfigError("Invalid GEMINI_PROJECT_BILLING_" + number)
            # Unlabeled slots share a quota group but may be different projects.
            labeled = slot.project_label != UNKNOWN_PROJECT_LABEL
            if labeled and groups.setdefault(slot.project_label, status) != status:
                raise GeminiConfigError("Conflicting billing confirmations for a shared project label")
            billing[slot.slot_id] = status
        models = frozenset(m.strip() for m in settings.get("GEMINI_FREE_MODELS", "").split(",") if m.strip())
        return cls(billing, models)

    def eligible_credentials(self, credentials):
        eligible = tuple(c for c in credentials if self.billing[c.slot_id] == "FREE_TIER_CONFIRMED")
        if not eligible:
            raise GeminiConfigError("NO_FREE_TIER_CONFIRMED_PROJECT: set GEMINI_API_KEY_<n> and "
                                    "GEMINI_PROJECT_BILLING_<n>=FREE_TIER_CONFIRMED in .env")
        return eligible

    def check_models(self, models):
        missing = sorted(set(models) - self.confirmed_models)
        if missing:
            raise GeminiConfigError("MODEL_NOT_CONFIRMED_FREE: set GEMINI_FREE_MODELS for " + ", ".join(missing))

    def public_summary(self):
        counts = Counter(self.billing.values())
        return {"billing_status_counts": {s: counts[s] for s in STATUSES},
                "confirmed_models": sorted(self.confirmed_models), "LLM_FREE_ONLY": True,
                "LLM_ALLOW_PAID": False, "MAX_PAID_SPEND_USD": 0, "notice": NOTICE}
