"""Print the offline Phase 1 configuration and persisted cooldowns."""
import argparse
import json
import time

from tools.llm_infra.gemini_config import inspect_settings, merged_settings, state_path
from tools.llm_infra.quota_state import QuotaStateError, QuotaStateStore
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError, _KEY_PATTERN
from tools.story_extraction.gemini_transport_v1 import _utc_iso


def main(argv=None, *, environ=None, clock=time.time):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--state")
    args = parser.parse_args(argv)
    status = "CONFIG_ERROR"
    report = {"billing_verified_by_system": False, "projects": []}
    secrets = []
    try:
        settings = merged_settings(args.env_file, environ)
        secrets = [v.strip() for k, v in settings.items() if _KEY_PATTERN.fullmatch(k) and v.strip()]
        config = inspect_settings(settings)
        report.update(config.policy.public_summary())
        report.update(slots_configured=len(config.credentials) + config.duplicates_dropped,
                      duplicates_dropped=config.duplicates_dropped,
                      project_groups=len({c.group_id for c in config.credentials}))
        store = QuotaStateStore(args.state or state_path(settings), clock=clock)
        report["active_blocks"] = [
            {**{k: row[k] for k in ("provider", "model", "project_alias", "reason")},
             "until_utc": _utc_iso(row["blocked_until"])} for row in store.active_blocks(clock())]
        if not config.credentials:
            status = "WAITING_FOR_USER_CREDENTIALS"
        else:
            models = [m.strip() for m in config.model.split(",") if m.strip()]
            config.policy.check_models(models)
            config.policy.eligible_credentials(config.credentials)
            if not models:
                raise GeminiConfigError("MODEL_NOT_CONFIRMED_FREE: set GEMINI_MODEL")
            status = "READY_FREE_ONLY"
    except (GeminiConfigError, QuotaStateError, OSError) as error:
        message = str(error) if not isinstance(error, OSError) else "Cannot read configuration"
        report["error"] = message
        if message.startswith("NO_FREE_TIER_CONFIRMED_PROJECT"):
            status = "BLOCKED_NO_CONFIRMED_FREE_PROJECT"
        elif message.startswith(("MODEL_NOT_CONFIRMED_FREE:", "MODEL_ALLOWLIST_EMPTY:")):
            status = "BLOCKED_MODEL_NOT_CONFIRMED_FREE"
        elif message.startswith("PROJECT_LABEL_REQUIRED:"):
            status = "BLOCKED_PROJECT_LABEL_REQUIRED"
        elif message.startswith("PER_PROJECT_CONFIRMATION_REQUIRED:"):
            status = "BLOCKED_PER_PROJECT_CONFIRMATION_REQUIRED"
    report["application_policy"] = "PASS" if status == "READY_FREE_ONLY" else "BLOCKED"
    output = json.dumps(report, ensure_ascii=False, indent=2)
    for secret in secrets:
        output = output.replace(secret, "[REDACTED]")
    print(output)
    if status == "READY_FREE_ONLY":
        print("Billing: owner-attested, not verified by this tool. READY_FREE_ONLY means the "
              "application policy passes; it is not a guarantee that Google cannot charge.")
    print("Status:", status)
    return int(status != "READY_FREE_ONLY")


if __name__ == "__main__":
    raise SystemExit(main())
