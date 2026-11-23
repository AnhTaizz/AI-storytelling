"""Inspect OpenRouter settings offline or opt in to a key check and a small chat."""
import argparse
from functools import partial
import json
import time

from tools.llm_infra.gemini_config import merged_settings, state_path
from tools.llm_infra.openrouter_config import inspect_openrouter_settings
from tools.llm_infra.openrouter_transport import (
    OpenRouterClient, OpenRouterHTTPError, public_key_counts, redact_openrouter_data,
)
from tools.llm_infra.quota_state import QuotaStateStore
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError
from tools.story_extraction.gemini_transport_v1 import _utc_iso


def _live_request(model, slot, client_factory, clock):
    report = {
        "slot_id": slot.slot_id, "scope": slot.scope,
        "model": {"requested": model, "reported": None}, "key_info": {}, "cost": None,
        "key_outcome": None, "http_status": None, "latency_ms": 0,
    }
    try:
        client = client_factory(slot._api_key)
    except OpenRouterHTTPError as error:
        return report | {"outcome": error.kind, "http_status": error.status}

    try:
        report["key_info"] = public_key_counts(client.key_info())
    except OpenRouterHTTPError as error:
        report["key_outcome"] = error.kind
    else:
        report["key_outcome"] = "SUCCESS"

    start = clock()
    try:
        response = client.generate(
            model=model, system_instruction="Reply with JSON only.", user_content='Return {"status":"ok"}',
            generation_config={"temperature": 0, "max_output_tokens": 512, "response_mime_type": "application/json"},
        )
    except OpenRouterHTTPError as error:
        report.update(outcome=error.kind, http_status=error.status)
        if error.kind == "PAID_USAGE_DETECTED":
            reported = error.body.get("model")
            usage = error.body.get("usage")
            cost = usage.get("cost") if isinstance(usage, dict) else None
            report["model"]["reported"] = reported if isinstance(reported, str) else None
            report["cost"] = cost if type(cost) in (int, float) else None
    else:
        report.update(outcome="SUCCESS", http_status=response.status, cost=response.cost)
        report["model"]["reported"] = response.model
    report["latency_ms"] = max(0, round((clock() - start) * 1000))
    return report


def main(argv=None, *, environ=None, client_factory=None, clock=time.time):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--model")
    parser.add_argument("--live", action="store_true", help="inspect the key and send one synthetic chat request")
    args = parser.parse_args(argv)
    report = {"mode": "live"} if args.live else {"mode": "offline", "blocked": []}
    status_field = "outcome" if args.live else "status"
    status = "CONFIG_ERROR"
    secrets = ()
    try:
        settings = merged_settings(args.env_file, environ)
        config = inspect_openrouter_settings(settings, args.model, validate_models=False)
        secrets = config._secrets
        if args.live:
            model = args.model.strip() if args.model is not None else config.model_chain[0]
            config.check_models((model,) if args.model is not None else config.model_chain)
            config.check_eligible()
            if client_factory is None:
                client_factory = partial(OpenRouterClient, timeout=20, data_collection=config.data_collection)
            report.update(_live_request(model, config.slots[0], client_factory, clock))
            status = report["outcome"]
        else:
            report.update(config.public_summary())
            if config.slots:
                store = QuotaStateStore(state_path(settings), clock=clock)
                report["blocked"] = [
                    {"scope": row["project_alias"], "until_utc": _utc_iso(row["blocked_until"]),
                     "reason": row["reason"]}
                    for row in store.active_blocks(clock()) if row["provider"] == "openrouter"
                ]
            config.check_models(config.model_chain)
            status = "READY_FREE_ONLY" if config.slots else "WAITING_FOR_USER_CREDENTIALS"
    except GeminiConfigError as error:
        if str(error).startswith("MODEL_NOT_FREE_TIER:"):
            status = "BLOCKED_MODEL_NOT_FREE_TIER"
    except OSError:
        pass
    report[status_field] = status
    print(json.dumps(redact_openrouter_data(report, secrets)))
    if args.live:
        return int(status != "SUCCESS" or report["key_outcome"] != "SUCCESS")
    return int(status != "READY_FREE_ONLY")


if __name__ == "__main__":
    raise SystemExit(main())
