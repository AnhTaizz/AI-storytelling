"""Print the offline free LLM configuration and persisted cooldowns."""
import argparse
import json
import time

from tools.llm_infra.cloudflare_config import CREDENTIAL_PATTERN, cloudflare_secrets, inspect_cloudflare_settings
from tools.llm_infra.cloudflare_router import cloudflare_quota_summary
from tools.llm_infra.cloudflare_transport import redact_cloudflare_data
from tools.llm_infra.gemini_config import inspect_settings, merged_settings, state_path
from tools.llm_infra.groq_config import GROQ_KEY_PATTERN, inspect_groq_settings
from tools.llm_infra.groq_transport import redact_groq_data
from tools.llm_infra.model_capabilities_v1 import model_capability
from tools.llm_infra.neuron_ledger import NeuronLedger
from tools.llm_infra.openrouter_config import OPENROUTER_KEY_PATTERN, inspect_openrouter_settings
from tools.llm_infra.openrouter_transport import redact_openrouter_data
from tools.llm_infra.pipeline_clients import build_adapter
from tools.llm_infra.quota_state import QuotaStateError, QuotaStateStore
from tools.llm_infra.routing_policy import DEFAULT_POLICY, PROVIDERS, load_policy
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError, UNKNOWN_PROJECT_LABEL, _KEY_PATTERN
from tools.story_extraction.gemini_transport_v1 import _utc_iso


def _public_blocks(blocks, provider):
    return [{"model": row["model"], "scope": row["project_alias"], "reason": row["reason"],
             "until_utc": _utc_iso(row["blocked_until"])} for row in blocks if row["provider"] == provider]


def _groq_report(settings, state, blocks, clock):
    report = {"status": "CONFIG_ERROR"}
    try:
        if blocks is None:
            blocks = QuotaStateStore(state, clock=clock).active_blocks(clock())
        report["blocked"] = _public_blocks(blocks, "groq")
        config = inspect_groq_settings(settings, validate_models=False)
        report.update(config.public_summary())
        config.check_eligible()
        config.check_models(config.model_chain)
        report["status"] = "READY_FREE_ONLY"
    except GeminiConfigError as error:
        message = str(error)
        report["error"] = message
        if message.startswith("NO_ELIGIBLE_KEY"):
            report["status"] = "BLOCKED_NO_ELIGIBLE_KEY"
        elif message.startswith("MODEL_NOT_FREE_TIER"):
            report["status"] = "BLOCKED_MODEL_NOT_FREE_TIER"
    return report


def _openrouter_report(settings, state, blocks, clock):
    report = {"status": "CONFIG_ERROR", "blocked": []}
    try:
        if blocks is None:
            blocks = QuotaStateStore(state, clock=clock).active_blocks(clock())
        report["blocked"] = _public_blocks(blocks, "openrouter")
        config = inspect_openrouter_settings(settings, validate_models=False)
        report.update(config.public_summary())
        config.check_eligible()
        config.check_models(config.model_chain)
        report["status"] = "READY_FREE_ONLY"
    except (GeminiConfigError, OSError) as error:
        report["error"] = str(error) if not isinstance(error, OSError) else "Cannot read OpenRouter configuration"
        if report["error"].startswith("MODEL_NOT_FREE_TIER:"):
            report["status"] = "BLOCKED_MODEL_NOT_FREE_TIER"
    return report


def _cloudflare_report(settings, state, blocks, clock):
    report = {"status": "CONFIG_ERROR", "blocked": []}
    try:
        now = clock()
        if blocks is None:
            blocks = QuotaStateStore(state, clock=clock).active_blocks(now)
        report["blocked"] = _public_blocks(blocks, "cloudflare")
        config = inspect_cloudflare_settings(settings, validate_models=False)
        report.update(config.public_summary())
        report.update(cloudflare_quota_summary(config, NeuronLedger(state), blocks, now))
        config.check_eligible()
        config.check_models(config.model_chain)
        report["status"] = "READY_FREE_ONLY"
    except (GeminiConfigError, OSError) as error:
        report["error"] = str(error) if not isinstance(error, OSError) else "Cannot read Cloudflare configuration"
        if report["error"].startswith("MODEL_NOT_FREE_TIER:"):
            report["status"] = "BLOCKED_MODEL_NOT_FREE_TIER"
        elif report["error"].startswith("NO_ELIGIBLE_KEY:"):
            report["status"] = "BLOCKED_NO_ELIGIBLE_KEY"
    return report


def _routing_report(settings, path, clock, blocks):
    providers = {}
    adapters = {}
    store = QuotaStateStore(None, clock=clock)
    now = clock()
    for row in blocks or ():
        store.block(row["provider"], row["model"], row["project_alias"],
                    row["blocked_until"], row["reason"], now)
    patterns = dict(zip(PROVIDERS, (_KEY_PATTERN, GROQ_KEY_PATTERN, OPENROUTER_KEY_PATTERN, CREDENTIAL_PATTERN)))
    for provider in PROVIDERS:
        try:
            adapters[provider] = build_adapter(provider, settings, store, clock=clock)
        except GeminiConfigError:
            pass
        adapter = adapters.get(provider)
        configured = any(patterns[provider].fullmatch(name) and value.strip() for name, value in settings.items())
        providers[provider] = {"configured": configured, "eligible": False}
        if adapter is not None:
            providers[provider].update(configured=True, eligible=any(adapter.allows(model) for model in adapter.models))
    result = {"policy_path": str(path), "policy_sha256": None, "providers": providers, "tiers": {}}
    try:
        policy = load_policy(path)
    except ValueError as error:
        return result | {"error": str(error)}
    result["policy_sha256"] = policy.sha256
    for name, tier in policy.tiers.items():
        candidates = []
        for provider, selector in tier.selectors():
            adapter = adapters.get(provider)
            if adapter is None:
                continue
            for model in adapter.models if selector == "*" else (selector,):
                capability = model_capability(provider, model)
                if (capability is not None and capability.capacity >= tier.max_output_tokens
                        and adapter.allows(model) and adapter.availability(model)[0] is None):
                    candidates.append(f"{provider}:{model}")
                    providers[provider]["eligible"] = True
        result["tiers"][name] = list(dict.fromkeys(candidates))
    return result


def main(argv=None, *, environ=None, clock=time.time):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--state")
    parser.add_argument("--routing-policy", default=DEFAULT_POLICY)
    args = parser.parse_args(argv)
    status = "CONFIG_ERROR"
    report = {"billing_verified_by_system": False}
    secrets = []
    groq_secrets = []
    openrouter_secrets = []
    cf_secrets = ()
    blocks = None
    settings = {}
    try:
        settings = merged_settings(args.env_file, environ)
        cf_secrets = cloudflare_secrets(settings)
        secrets = [v.strip() for k, v in settings.items() if _KEY_PATTERN.fullmatch(k) and v.strip()]
        groq_secrets = sorted({v.strip() for k, v in settings.items() if GROQ_KEY_PATTERN.fullmatch(k) and v.strip()},
                              key=len, reverse=True)
        openrouter_secrets = sorted({value.strip() for name, value in settings.items()
                                     if OPENROUTER_KEY_PATTERN.fullmatch(name) and value.strip()},
                                    key=len, reverse=True)
        config = inspect_settings(settings)
        report.update(config.policy.public_summary())
        models = [m.strip() for m in config.model.split(",") if m.strip()]
        scopes = {c.group_id for c in config.credentials}
        eligible = {c.group_id for c in config.credentials
                    if config.policy.billing[c.slot_id] == "FREE_TIER_CONFIRMED"}
        report.update(keys_configured=len(config.credentials) + config.duplicates_dropped,
                      duplicates_dropped=config.duplicates_dropped, key_scopes=len(scopes),
                      labels_used=len({c.project_label for c in config.credentials
                                       if c.project_label != UNKNOWN_PROJECT_LABEL}),
                      model_chain=models, model_source=config.model_source,
                      max_rate_limit_hops=config.max_rate_limit_hops)
        store = QuotaStateStore(args.state or state_path(settings), clock=clock)
        blocks = store.active_blocks(clock())
        report["blocked"] = _public_blocks(blocks, "gemini")
        report["available_now"] = len(eligible - {row["scope"] for row in report["blocked"]
                                                  if models and row["model"] == models[0]})
        if not config.credentials:
            status = "WAITING_FOR_USER_CREDENTIALS"
        else:
            config.policy.eligible_credentials(config.credentials)
            config.policy.check_models(models)
            status = "READY_FREE_ONLY"
    except (GeminiConfigError, QuotaStateError, OSError) as error:
        message = str(error) if not isinstance(error, OSError) else "Cannot read configuration"
        report["error"] = message
        if message.startswith("NO_ELIGIBLE_KEY"):
            status = "BLOCKED_NO_ELIGIBLE_KEY"
        elif message.startswith("MODEL_NOT_FREE_TIER"):
            status = "BLOCKED_MODEL_NOT_FREE_TIER"
    if groq_secrets:
        report["groq"] = _groq_report(settings, args.state or state_path(settings), blocks, clock)
    report["routing"] = _routing_report(settings, args.routing_policy, clock, blocks)
    if openrouter_secrets:
        report["openrouter"] = _openrouter_report(settings, args.state or state_path(settings), blocks, clock)
        report = redact_openrouter_data(report, openrouter_secrets)
    if groq_secrets:
        report = redact_groq_data(report, groq_secrets)
    if cf_secrets:
        report["cloudflare"] = _cloudflare_report(settings, args.state or state_path(settings), blocks, clock)
        report = redact_cloudflare_data(report, cf_secrets)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    for secret in secrets:
        output = output.replace(secret, "[REDACTED]")
    print(output)
    print("Billing: not verified by this tool. An API key cannot show whether its Google Cloud "
          "project has billing; check once in AI Studio / Cloud Billing that no billing account is linked.")
    print("Status:", status)
    return int(status != "READY_FREE_ONLY")


if __name__ == "__main__":
    raise SystemExit(main())
