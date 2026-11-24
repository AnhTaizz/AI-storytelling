"""Public provider facts, offline configuration counts, and quota observations."""

import json
from pathlib import Path

from tools.llm_infra import cloudflare_free_models_v1 as cloudflare
from tools.llm_infra import gemini_free_models_v1 as gemini
from tools.llm_infra import groq_free_models_v1 as groq
from tools.llm_infra.cloudflare_config import inspect_cloudflare_settings
from tools.llm_infra.cost_policy import CostPolicy
from tools.llm_infra.groq_config import inspect_groq_settings
from tools.llm_infra.model_capabilities_v1 import CAPABILITIES
from tools.llm_infra.openrouter_config import inspect_openrouter_settings
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError, _KEY_PATTERN, load_runtime_config

from .contract import FIELDS
from .data_source import PROVIDER_NAMES, SCOPES


_CONFIG_FIELDS = ("keys_configured", "keys_eligible", "key_scopes")


def _gemini_summary(settings):
    # The shared loader accepts a directory as an absent dotenv file. Filter
    # duplicate values the same way as the Gemini routing config inspector.
    filtered = dict(settings)
    keys = sorted((int(match[1]), name, value.strip()) for name, value in settings.items()
                  if (match := _KEY_PATTERN.fullmatch(name)) and value.strip())
    if any(slot < 1 for slot, _, _ in keys) or len({slot for slot, _, _ in keys}) != len(keys):
        raise GeminiConfigError("Invalid credential slots")
    seen = set()
    for _, name, secret in keys:
        if secret in seen:
            del filtered[name]
        seen.add(secret)
    config = load_runtime_config(Path(__file__).parent, filtered)
    policy = CostPolicy.from_settings(settings, config.credentials)
    return {
        "keys_configured": len(keys),
        "keys_eligible": policy.public_summary()["billing_status_counts"]["FREE_TIER_CONFIRMED"],
        "key_scopes": len({credential.group_id for credential in config.credentials}),
    }


def configuration_counts(settings):
    def summary(inspect):
        return lambda values: inspect(values, validate_models=False).public_summary()

    inspectors = {"gemini": _gemini_summary, "groq": summary(inspect_groq_settings),
                  "openrouter": summary(inspect_openrouter_settings),
                  "cloudflare": summary(inspect_cloudflare_settings)}
    result = {}
    for provider, inspect in inspectors.items():
        try:
            raw = inspect(settings)
            counts = {key: raw[key] for key in _CONFIG_FIELDS}
        except (ValueError, GeminiConfigError, OSError):
            counts = dict.fromkeys(_CONFIG_FIELDS)
        result[provider] = {
            **counts, "source": "unknown" if counts["keys_configured"] is None else "reported",
            "status": "configured" if counts["keys_configured"] else "not_configured",
        }
    return result


def _limits(provider, neurons):
    label, unit, limit, snapshot = {
        "gemini": ("Per project and model", "requests", None, gemini),
        "groq": ("Tokens per minute", "tokens", groq.FREE_PLAN_TPM, groq),
        "openrouter": ("Free requests per UTC day", "requests", None, None),
        "cloudflare": ("Neurons per UTC day", "Neurons", cloudflare.DAILY_FREE_NEURONS, cloudflare),
    }[provider]
    used = neurons if provider == "cloudflare" else None
    return [{
        "label": label, "unit": unit, "limit": limit, "used": used, "remaining": None,
        "source": "static" if limit is not None else "unknown",
        "sources": {"limit": "static" if limit is not None else "unknown",
                    "used": "estimated" if used is not None else "unknown", "remaining": "unknown"},
        "source_url": snapshot.SOURCE_URL if snapshot else None,
        "verified_on": snapshot.VERIFIED_ON if snapshot else None,
    }]


def _observed_counters(rows):
    latest = {}
    for row in rows:
        model = row[FIELDS["model"]]
        scope = row[FIELDS["quotaScope"]]
        for name, value in json.loads(row[FIELDS["quotaRemaining"]]).items():
            latest.setdefault((model, scope, name), {
                "name": name, "value": value, "source": "reported",
                "model": model, "scope": scope, "timestamp": row[FIELDS["timestamp"]],
            })
    return list(latest.values())


def provider_summaries(config, rows, blocks, neurons):
    for provider, name in PROVIDER_NAMES.items():
        events = [row for row in rows if row[FIELDS["provider"]] == provider]
        latest = next((row for row in events if row[FIELDS["outcome"]] != "SKIPPED"), None)
        errors = (row[FIELDS["error"]] for row in events)
        active = [block for block in blocks if block["provider"] == provider]
        status = "NotConfigured"
        if active:
            status = "Cooldown"
        elif config[provider]["status"] == "configured":
            status = "Unobserved" if latest is None else (
                "Healthy" if latest[FIELDS["outcome"]] == "SUCCESS" else "Degraded")
        models = [{
            "model": model, "context_tokens": capability.context_tokens,
            "max_request_tokens": capability.max_request_tokens, "json_mode": capability.json_mode,
            "reasoning": capability.reasoning, "source": "static", "source_url": capability.source,
            "sources": {key: "static" if getattr(capability, key) is not None else "unknown"
                        for key in ("context_tokens", "max_request_tokens")},
            "verified_on": capability.verified_on,
        } for (slug, model), capability in CAPABILITIES.items() if slug == provider]
        yield {
            "slug": provider, "name": name, "status": status, "scope": SCOPES[provider],
            "models": [model["model"] for model in models], "model_details": models,
            "configuration": config[provider], "limits": _limits(provider, neurons),
            "blocks": active, "quota_counters": _observed_counters(events),
            "last_error": next((error for error in errors if error), None),
            "cooldown_until": min((block["until_utc"] for block in active), default=None),
        }
