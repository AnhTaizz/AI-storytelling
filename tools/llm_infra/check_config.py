"""Print the offline Phase 1 configuration and persisted cooldowns."""
import argparse
import json
import time

from tools.llm_infra.gemini_config import inspect_settings, merged_settings, state_path
from tools.llm_infra.quota_state import QuotaStateError, QuotaStateStore
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError, UNKNOWN_PROJECT_LABEL, _KEY_PATTERN
from tools.story_extraction.gemini_transport_v1 import _utc_iso


def main(argv=None, *, environ=None, clock=time.time):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--state")
    args = parser.parse_args(argv)
    status = "CONFIG_ERROR"
    report = {"billing_verified_by_system": False}
    secrets = []
    try:
        settings = merged_settings(args.env_file, environ)
        secrets = [v.strip() for k, v in settings.items() if _KEY_PATTERN.fullmatch(k) and v.strip()]
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
        report["blocked"] = [
            {"model": row["model"], "scope": row["project_alias"], "reason": row["reason"],
             "until_utc": _utc_iso(row["blocked_until"])} for row in blocks if row["provider"] == "gemini"]
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
