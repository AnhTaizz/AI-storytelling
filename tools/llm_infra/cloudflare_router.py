"""Route Workers Free calls across account-wide budgets and cooldowns."""
import math
from threading import Lock
import time

from tools.llm_infra.cloudflare_quota_policy import decide_cloudflare_limit
from tools.llm_infra.cloudflare_transport import CloudflareClient, CloudflareHTTPError, redact_cloudflare_data
from tools.llm_infra.neuron_ledger import NeuronLedger, estimate_prompt_neurons, estimate_response_neurons, utc_day
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError
from tools.story_extraction.gemini_transport_v1 import _utc_iso


PROVIDER = "cloudflare"
ACCOUNT_WIDE_MODEL = "*"


class CloudflareTransportError(RuntimeError):
    def __init__(self, code, attempts):
        self.code = code
        self.attempts = attempts
        super().__init__(f"Cloudflare transport failed: {code} (attempts={attempts})")


class CloudflareQuotaPaused(CloudflareTransportError):
    def __init__(self, attempts, resume_after):
        super().__init__("QUOTA_EXHAUSTED", attempts)
        self.resume_after = resume_after
        self.args = (f"{self}. Quota resumes at {_utc_iso(resume_after)}",)


def block_daily_budget(store, scope, now):
    decision = decide_cloudflare_limit("DAILY_ALLOCATION_EXHAUSTED", None, None, now, 0)
    store.block(PROVIDER, ACCOUNT_WIDE_MODEL, scope, decision.blocked_until, decision.reason, now)
    return decision.blocked_until


def cloudflare_quota_summary(config, ledger, blocks, now):
    return {
        "neurons_used_today": {scope: ledger.used(PROVIDER, scope, utc_day(now)) for scope in config.account_scopes},
        "blocked": [{"model": row["model"], "scope": row["project_alias"], "reason": row["reason"],
                     "until_utc": _utc_iso(row["blocked_until"])} for row in blocks if row["provider"] == PROVIDER],
    }


class CloudflareRouter:
    def __init__(self, config, store, client_factory=None, *, ledger=None,
                 max_transport_retries=2, base_backoff_seconds=1.0, max_inline_wait_seconds=60.0,
                 clock=time.time, sleep=time.sleep):
        if type(max_transport_retries) is not int or max_transport_retries < 0:
            raise GeminiConfigError("Cloudflare transport retries must be a non-negative integer")
        if any(not math.isfinite(limit) or limit < 0 for limit in (base_backoff_seconds, max_inline_wait_seconds)):
            raise GeminiConfigError("Cloudflare backoff and wait limits must be finite and non-negative")
        if any(secret in str(store.path) for secret in config._secrets):
            raise GeminiConfigError("Cloudflare quota state path contains credential material")
        self._config = config
        self._store = store
        self._ledger = NeuronLedger(store.path) if ledger is None else ledger
        self._client_factory = CloudflareClient if client_factory is None else client_factory
        self._retries = max_transport_retries
        self._backoff = base_backoff_seconds
        self._max_wait = max_inline_wait_seconds
        self._clock = clock
        self._sleep = sleep
        self._scopes = {}
        for slot in config.slots:
            self._scopes.setdefault(slot.scope, []).append(slot)
        self._disabled = set()
        self._lock = Lock()

    def _next_slot(self, now, prompt_cost):
        blocked = []
        all_over_budget = True
        day = utc_day(now)
        with self._lock:
            for scope, slots in self._scopes.items():
                slot = next((slot for slot in slots if slot.slot_id not in self._disabled), None)
                if slot is None:
                    continue
                until = self._store.blocked_until(PROVIDER, ACCOUNT_WIDE_MODEL, scope, now)
                over_budget = self._ledger.used(PROVIDER, scope, day) + prompt_cost > self._config.daily_neuron_budget
                if over_budget:
                    until = max(until or now, block_daily_budget(self._store, scope, now))
                else:
                    all_over_budget = False
                if until is None:
                    return slot, None, False
                blocked.append(until)
        return None, min(blocked, default=None), all_over_budget

    def _success(self, response, model, prompt_chars, request_id, start, metadata, attempts):
        end = self._clock()
        scope = metadata["scope"]
        estimate = estimate_response_neurons(model, prompt_chars, response)
        with self._lock:
            total = self._ledger.add(PROVIDER, scope, utc_day(end), estimate, end)
            self._store.record_success(PROVIDER, ACCOUNT_WIDE_MODEL, scope, end)
            if total >= self._config.daily_neuron_budget:
                block_daily_budget(self._store, scope, end)
        record = {
            "request_id": request_id, "provider": "Cloudflare Workers AI", "transport": "CLOUDFLARE_ROUTER_V1",
            "quota_scope": "account_neurons", "model_requested": model,
            "model_reported_if_available": response.model, **metadata,
            "start_time": _utc_iso(start), "end_time": _utc_iso(end),
            "latency_seconds": max(0, end - start), "usage_metadata": response.usage,
            "neurons_estimated": estimate, "neurons_used_today": total,
            "provider_response_metadata": {"response_id": response.response_id} if response.response_id else {},
            "raw_content": response.text, "transport_attempts": attempts,
        }
        return redact_cloudflare_data(record, self._config._secrets)

    def generate(self, system_instruction, user_content, model, generation_config, request_id):
        self._config.check_models((model,))
        start = self._clock()
        prompt_chars = len(system_instruction) + len(user_content)
        prompt_cost = estimate_prompt_neurons(model, prompt_chars)
        attempts = []
        quota_refusals = retries = 0
        waited = False
        while True:
            now = self._clock()
            slot, resume, all_over_budget = self._next_slot(now, prompt_cost)
            if slot is None:
                if resume is None:
                    raise CloudflareTransportError("NO_USABLE_CREDENTIAL", len(attempts))
                if all_over_budget or waited or resume - now > self._max_wait:
                    raise CloudflareQuotaPaused(len(attempts), resume)
                self._sleep(resume - now)
                waited = True
                continue
            quota_key = (PROVIDER, ACCOUNT_WIDE_MODEL, slot.scope)
            metadata = {"slot_id": slot.slot_id, "scope": slot.scope}
            attempt = {"attempt": len(attempts) + 1, **metadata}
            attempts.append(attempt)
            try:
                response = self._client_factory(slot._account_id, slot._api_token).generate(
                    model=model, system_instruction=system_instruction, user_content=user_content,
                    generation_config=generation_config,
                )
            except CloudflareHTTPError as error:
                failure = error
            else:
                attempt["outcome"] = "SUCCESS"
                return self._success(response, model, prompt_chars, request_id, start, metadata, attempts)

            kind = attempt["outcome"] = failure.kind
            if kind in ("DAILY_ALLOCATION_EXHAUSTED", "RATE_LIMIT"):
                now = self._clock()
                decision = decide_cloudflare_limit(kind, failure.headers, failure.body, now,
                                                  self._store.unknown_streak(*quota_key))
                self._store.block(*quota_key, decision.blocked_until, decision.reason, now)
                quota_refusals += 1
                if quota_refusals >= self._config.max_rate_limit_hops:
                    with self._lock:
                        resumes = [until for scope, slots in self._scopes.items()
                                   if any(slot.slot_id not in self._disabled for slot in slots)
                                   and (until := self._store.blocked_until(PROVIDER, ACCOUNT_WIDE_MODEL, scope, now))
                                   is not None]
                    raise CloudflareQuotaPaused(len(attempts), min(resumes, default=decision.blocked_until))
            elif kind == "AUTH_FAILURE":
                with self._lock:
                    self._disabled.add(slot.slot_id)
            elif kind in ("SERVER_FAILURE", "TRANSPORT_FAILURE") and retries < self._retries:
                self._sleep(self._backoff * 2 ** retries)
                retries += 1
            else:
                raise CloudflareTransportError(
                    redact_cloudflare_data(kind, self._config._secrets), len(attempts)
                ) from failure
