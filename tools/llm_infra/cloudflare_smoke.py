"""Inspect Workers AI settings offline or send one synthetic chat with --live."""
import argparse
from functools import partial
import json
import time

from tools.llm_infra.cloudflare_config import inspect_cloudflare_settings
from tools.llm_infra.cloudflare_router import ACCOUNT_WIDE_MODEL, PROVIDER, block_daily_budget, cloudflare_quota_summary
from tools.llm_infra.cloudflare_transport import CloudflareClient, CloudflareHTTPError, redact_cloudflare_data
from tools.llm_infra.gemini_config import merged_settings, state_path
from tools.llm_infra.neuron_ledger import NeuronLedger, estimate_prompt_neurons, estimate_response_neurons, utc_day
from tools.llm_infra.quota_state import QuotaStateStore
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError


def _live_request(config, model, store, ledger, client_factory, clock):
    slot = config.slots[0]
    report = {
        "slot_id": slot.slot_id, "scope": slot.scope, "model": model, "http_status": None,
        "latency_ms": 0, "prompt_tokens": None, "completion_tokens": None,
        "neurons_estimated": None, "parsed_json": False,
    }
    system_instruction = "Reply with JSON only."
    user_content = 'Return {"status":"ok"}'
    prompt_chars = len(system_instruction) + len(user_content)
    start = clock()
    used = ledger.used(PROVIDER, slot.scope, utc_day(start))
    if used + estimate_prompt_neurons(model, prompt_chars) > config.daily_neuron_budget:
        block_daily_budget(store, slot.scope, start)
        return report | {"outcome": "QUOTA_EXHAUSTED"}
    if store.blocked_until(PROVIDER, ACCOUNT_WIDE_MODEL, slot.scope, start) is not None:
        return report | {"outcome": "QUOTA_EXHAUSTED"}
    try:
        response = client_factory(slot._account_id, slot._api_token).generate(
            model=model, system_instruction=system_instruction, user_content=user_content,
            generation_config={"temperature": 0, "max_output_tokens": 512},
        )
    except CloudflareHTTPError as error:
        report.update(outcome=error.kind, http_status=error.status)
        end = clock()
    else:
        end = clock()
        estimate = estimate_response_neurons(model, prompt_chars, response)
        total = ledger.add(PROVIDER, slot.scope, utc_day(end), estimate, end)
        if total >= config.daily_neuron_budget:
            block_daily_budget(store, slot.scope, end)
        try:
            json.loads(response.text)
        except (ValueError, RecursionError):
            pass
        else:
            report["parsed_json"] = True
        report.update(outcome="SUCCESS", http_status=response.status, prompt_tokens=response.prompt_tokens,
                      completion_tokens=response.completion_tokens, neurons_estimated=estimate)
    report["latency_ms"] = max(0, round((end - start) * 1000))
    return report


def main(argv=None, *, environ=None, client_factory=None, clock=time.time):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--model")
    parser.add_argument("--live", action="store_true", help="send one synthetic chat request")
    args = parser.parse_args(argv)
    report = {"mode": "live"} if args.live else {"mode": "offline", "blocked": []}
    status_field = "outcome" if args.live else "status"
    status = "CONFIG_ERROR"
    secrets = ()
    try:
        settings = merged_settings(args.env_file, environ)
        config = inspect_cloudflare_settings(settings, args.model, validate_models=False)
        secrets = config._secrets
        state = state_path(settings)
        if args.live:
            config.check_models(config.model_chain)
            if args.model is not None:
                config.check_models((args.model.strip(),))
            config.check_eligible()
            client_factory = partial(CloudflareClient, timeout=20) if client_factory is None else client_factory
            report.update(_live_request(config, config.model_chain[0], QuotaStateStore(state, clock=clock),
                                        NeuronLedger(state), client_factory, clock))
            status = report["outcome"]
        else:
            report.update(config.public_summary())
            if config.account_scopes:
                now = clock()
                store = QuotaStateStore(state, clock=clock)
                report.update(cloudflare_quota_summary(config, NeuronLedger(state), store.active_blocks(now), now))
            config.check_models(config.model_chain)
            if config.slots:
                status = "READY_FREE_ONLY"
            else:
                status = "BLOCKED_NO_ELIGIBLE_KEY" if config.account_scopes else "WAITING_FOR_USER_CREDENTIALS"
    except GeminiConfigError as error:
        if str(error).startswith("MODEL_NOT_FREE_TIER:"):
            status = "BLOCKED_MODEL_NOT_FREE_TIER"
    except OSError:
        pass
    report[status_field] = status
    print(json.dumps(redact_cloudflare_data(report, secrets)))
    return int(status != ("SUCCESS" if args.live else "READY_FREE_ONLY"))


if __name__ == "__main__":
    raise SystemExit(main())
