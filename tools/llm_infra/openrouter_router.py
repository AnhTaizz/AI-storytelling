"""Route free OpenRouter calls across enabled slots and account cooldowns."""
from functools import partial
import math
from threading import Lock
import time

from tools.llm_infra.openrouter_quota_policy import decide_openrouter_rate_limit
from tools.llm_infra.openrouter_transport import OpenRouterClient, OpenRouterHTTPError, redact_openrouter_data
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError
from tools.story_extraction.gemini_transport_v1 import _utc_iso


PROVIDER = "openrouter"
# The ledger requires a model column. Free limits span every model on the account.
ACCOUNT_WIDE_MODEL = "*"


class OpenRouterTransportError(RuntimeError):
    def __init__(self, code, attempts):
        self.code = code
        self.attempts = attempts
        super().__init__(f"OpenRouter transport failed: {code} (attempts={attempts})")


class OpenRouterQuotaPaused(OpenRouterTransportError):
    def __init__(self, attempts, resume_after):
        super().__init__("QUOTA_EXHAUSTED", attempts)
        self.resume_after = resume_after
        self.args = (f"{self}. Quota resumes at {_utc_iso(resume_after)}",)


class OpenRouterRouter:
    def __init__(self, config, store, client_factory=None, *,
                 max_transport_retries=2, base_backoff_seconds=1.0, max_inline_wait_seconds=60.0,
                 clock=time.time, sleep=time.sleep):
        if type(max_transport_retries) is not int or max_transport_retries < 0:
            raise GeminiConfigError("OpenRouter transport retries must be a non-negative integer")
        if any(not math.isfinite(limit) or limit < 0 for limit in (base_backoff_seconds, max_inline_wait_seconds)):
            raise GeminiConfigError("OpenRouter backoff and wait limits must be finite and non-negative")
        self._config = config
        self._store = store
        self._client_factory = (partial(OpenRouterClient, data_collection=config.data_collection)
                                if client_factory is None else client_factory)
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

    def _next_slot(self, now):
        blocked = []
        with self._lock:
            for scope, slots in self._scopes.items():
                slot = next((slot for slot in slots if slot.slot_id not in self._disabled), None)
                if slot is None:
                    continue
                until = self._store.blocked_until(PROVIDER, ACCOUNT_WIDE_MODEL, scope, now)
                if until is None:
                    return slot, None
                blocked.append(until)
        return None, min(blocked, default=None)

    def generate(self, system_instruction, user_content, model, generation_config, request_id):
        self._config.check_models((model,))
        if any(secret in model for secret in self._config._secrets):
            raise GeminiConfigError("Model contains credential material")
        start = self._clock()
        attempts = []
        refused = set()
        rate_limits = 0
        retries = 0
        waited = False
        while True:
            now = self._clock()
            slot, resume = self._next_slot(now)
            if slot is None:
                if resume is None:
                    raise OpenRouterTransportError("NO_USABLE_CREDENTIAL", len(attempts))
                if waited or resume - now > self._max_wait:
                    raise OpenRouterQuotaPaused(len(attempts), resume)
                self._sleep(resume - now)
                waited = True
                continue
            quota_key = (PROVIDER, ACCOUNT_WIDE_MODEL, slot.scope)
            metadata = {"slot_id": slot.slot_id, "scope": slot.scope}
            attempt = {"attempt": len(attempts) + 1, **metadata}
            attempts.append(attempt)
            try:
                response = self._client_factory(slot._api_key).generate(
                    model=model, system_instruction=system_instruction, user_content=user_content,
                    generation_config=generation_config,
                )
            except OpenRouterHTTPError as error:
                failure = error
            else:
                end = self._clock()
                attempt["outcome"] = "SUCCESS"
                self._store.record_success(*quota_key, end)
                record = {
                    "request_id": request_id, "provider": "OpenRouter", "transport": "OPENROUTER_ROUTER_V1",
                    "quota_scope": "account_model", "model_requested": model,
                    "model_reported_if_available": response.model, **metadata,
                    "start_time": _utc_iso(start), "end_time": _utc_iso(end),
                    "latency_seconds": max(0, end - start), "usage_metadata": response.usage,
                    "cost_reported": response.cost,
                    "provider_response_metadata": {"response_id": response_id}
                    if (response_id := response.response_id) else {},
                    "raw_content": response.text, "transport_attempts": attempts,
                }
                return redact_openrouter_data(record, self._config._secrets)

            kind = attempt["outcome"] = failure.kind
            if kind == "RATE_LIMIT":
                now = self._clock()
                decision = decide_openrouter_rate_limit(failure, None, None, now,
                                                       self._store.unknown_streak(*quota_key))
                self._store.block(*quota_key, decision.blocked_until, decision.reason, now)
                refused.add(slot.scope)
                rate_limits += 1
                if rate_limits >= self._config.max_rate_limit_hops:
                    resume = min(self._store.blocked_until(PROVIDER, ACCOUNT_WIDE_MODEL, scope, now) or now
                                 for scope in refused)
                    raise OpenRouterQuotaPaused(len(attempts), resume)
            elif kind == "AUTH_FAILURE":
                with self._lock:
                    self._disabled.add(slot.slot_id)
            elif kind in ("SERVER_FAILURE", "TRANSPORT_FAILURE") and retries < self._retries:
                self._sleep(self._backoff * 2 ** retries)
                retries += 1
            else:
                raise OpenRouterTransportError(
                    redact_openrouter_data(kind, self._config._secrets), len(attempts)
                ) from failure
