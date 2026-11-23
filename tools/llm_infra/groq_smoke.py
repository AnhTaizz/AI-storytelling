"""Inspect Groq Free plan settings offline or opt in to one small request."""
import argparse
from functools import partial
import json
import re
import time

from tools.llm_infra.gemini_config import merged_settings, state_path
from tools.llm_infra.groq_config import inspect_groq_settings
from tools.llm_infra.groq_free_models_v1 import SMOKE_MODEL
from tools.llm_infra.groq_transport import GroqClient, GroqHTTPError, redact_groq_data
from tools.llm_infra.quota_state import QuotaStateStore
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError
from tools.story_extraction.gemini_transport_v1 import _utc_iso


PLAN_NOTICE = ("The app cannot see the Groq plan. Keep the account on Free; "
               "do not add a card or upgrade to Developer.")
RATE_LIMIT_HEADERS = (
    "x-ratelimit-limit-requests", "x-ratelimit-limit-tokens", "x-ratelimit-remaining-requests",
    "x-ratelimit-remaining-tokens", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens", "retry-after",
)
USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")
# Groq error codes are short identifiers (e.g. json_validate_failed); anything else is dropped.
ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")


def _live_request(model, slot, client_factory, clock):
    start = clock()
    try:
        # Plain text: gpt-oss spends part of the 32 tokens on reasoning, and JSON mode then
        # rejects the cut-off output (json_validate_failed). The smoke test only checks access.
        response = client_factory(slot._api_key).generate(
            model=model, system_instruction="Reply briefly.", user_content="Reply with the word OK.",
            generation_config={"temperature": 0, "max_output_tokens": 32},
        )
    except GroqHTTPError as error:
        outcome, status, headers, reported, usage = error.kind, error.status, error.headers, None, {}
        detail = error.body.get("error") if isinstance(error.body, dict) else None
        code = detail.get("code") if isinstance(detail, dict) else None
        error_code = code if isinstance(code, str) and ERROR_CODE.fullmatch(code) else None
    else:
        outcome, status, headers, reported, usage = (
            "SUCCESS", response.status, response.headers, response.model, response.usage,
        )
        error_code = None
    headers = {name.lower(): value for name, value in headers.items()}
    return {
        "outcome": outcome, "http_status": status, "model": {"requested": model, "reported": reported},
        "usage": {name: usage[name] for name in USAGE_FIELDS if type(usage.get(name)) is int},
        "latency_ms": max(0, round((clock() - start) * 1000)),
        "rate_limit": {name: headers[name] for name in RATE_LIMIT_HEADERS if name in headers},
        "error_code": error_code,
    }


def main(argv=None, *, environ=None, client_factory=partial(GroqClient, timeout=20), clock=time.time):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--model")
    parser.add_argument("--live", action="store_true", help="send one synthetic request to Groq")
    args = parser.parse_args(argv)
    model = args.model.strip() if args.model is not None else SMOKE_MODEL
    if args.live:
        report = {"mode": "live", "http_status": None, "model": {"requested": None, "reported": None},
                  "usage": {}, "latency_ms": 0, "rate_limit": {}, "error_code": None}
        status_field = "outcome"
    else:
        report = {"mode": "offline", "plan_notice": PLAN_NOTICE, "blocked": []}
        status_field = "status"
    status = "CONFIG_ERROR"
    secrets = ()
    try:
        settings = merged_settings(args.env_file, environ)
        config = inspect_groq_settings(settings, model if args.live else args.model, validate_models=False)
        secrets = config._secrets
        if args.live:
            config.check_models((model,))
            config.check_eligible()
            report.update(_live_request(model, config.slots[0], client_factory, clock))
            status = report["outcome"]
        else:
            report.update(config.public_summary())
            if config.model_chain:
                store = QuotaStateStore(state_path(settings), clock=clock)
                report["blocked"] = [
                    {"scope": row["project_alias"], "until_utc": _utc_iso(row["blocked_until"]),
                     "reason": row["reason"]}
                    for row in store.active_blocks(clock())
                    if row["provider"] == "groq" and row["model"] == config.model_chain[0]
                ]
            config.check_models(config.model_chain)
            if report["keys_configured"]:
                config.check_eligible()
                status = "READY_FREE_PLAN"
            else:
                status = "WAITING_FOR_USER_CREDENTIALS"
    except GeminiConfigError as error:
        if str(error).startswith("MODEL_NOT_FREE_TIER:"):
            status = "BLOCKED_MODEL_NOT_FREE_PLAN"
    except OSError:
        pass
    report[status_field] = status
    print(json.dumps(redact_groq_data(report, secrets)))
    return int(status not in ("READY_FREE_PLAN", "SUCCESS"))


if __name__ == "__main__":
    raise SystemExit(main())
