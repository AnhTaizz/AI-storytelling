"""Owner attestations for free-only Gemini calls."""
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError

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
    projects: list

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
        bulk = _flag(settings, "GEMINI_KEYS_FREE_TIER_CONFIRMED", "false")
        groups = {}
        for slot in credentials:
            groups.setdefault(slot.group_id, []).append(slot)
        if bulk and len(groups) != 1:
            raise GeminiConfigError("PER_PROJECT_CONFIRMATION_REQUIRED: set "
                                    "GEMINI_PROJECT_BILLING_<n>=FREE_TIER_CONFIRMED per verified project")
        billing = {}
        projects = []
        for slots in groups.values():
            explicit = set()
            numbers = []
            for slot in slots:
                number = slot.slot_id.rsplit("_", 1)[1]
                numbers.append(int(number))
                name = "GEMINI_PROJECT_BILLING_" + number
                value = settings.get(name, "").strip()
                if value:
                    if value not in STATUSES:
                        raise GeminiConfigError("Invalid " + name)
                    explicit.add(value)
            if len(explicit) > 1:
                raise GeminiConfigError("Conflicting billing confirmations for a shared project label")
            status = next(iter(explicit), "FREE_TIER_CONFIRMED" if bulk else "UNVERIFIED")
            projects.append({"project_label": slots[0].project_label, "slots": numbers,
                             "billing_status": status,
                             "source": "per_project" if explicit else "bulk_line" if bulk else "default"})
            billing.update((slot.slot_id, status) for slot in slots)
        models = frozenset(m.strip() for m in settings.get("GEMINI_FREE_MODELS", "").split(",") if m.strip())
        return cls(billing, models, projects)

    def eligible_credentials(self, credentials):
        eligible = tuple(c for c in credentials if self.billing[c.slot_id] == "FREE_TIER_CONFIRMED")
        if not eligible:
            raise GeminiConfigError("NO_FREE_TIER_CONFIRMED_PROJECT: after checking that the keys' projects "
                                    "have no billing, set GEMINI_PROJECT_BILLING_<n>=FREE_TIER_CONFIRMED")
        return eligible

    def check_models(self, models):
        if not self.confirmed_models:
            raise GeminiConfigError("MODEL_ALLOWLIST_EMPTY: set GEMINI_FREE_MODELS to the confirmed free models")
        missing = sorted(set(models) - self.confirmed_models)
        if missing:
            raise GeminiConfigError("MODEL_NOT_CONFIRMED_FREE: set GEMINI_FREE_MODELS for " + ", ".join(missing))

    def public_summary(self):
        counts = Counter(self.billing.values())
        return {"projects": self.projects, "billing_status_counts": {s: counts[s] for s in STATUSES},
                "confirmed_models": sorted(self.confirmed_models), "LLM_FREE_ONLY": True,
                "LLM_ALLOW_PAID": False, "MAX_PAID_SPEND_USD": 0, "notice": NOTICE}
