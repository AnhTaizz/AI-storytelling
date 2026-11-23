"""Route Free plan Groq calls across eligible slots and persisted cooldowns."""
from collections import deque
import math
from threading import Lock
import time

from tools.llm_infra.groq_quota_policy import decide_groq_rate_limit
from tools.llm_infra.groq_transport import GroqClient, GroqHTTPError, redact_groq_data
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError
from tools.story_extraction.gemini_transport_v1 import _utc_iso


class GroqTransportError(RuntimeError):
    def __init__(self, code, attempts):
        self.code = code
        self.attempts = attempts
        super().__init__(f"Groq transport failed: {code} (attempts={attempts})")


class GroqQuotaPaused(GroqTransportError):
    def __init__(self, attempts, resume_after):
        super().__init__("QUOTA_EXHAUSTED", attempts)
        self.resume_after = resume_after
        self.args = (f"{self}. Quota resumes at {_utc_iso(resume_after)}",)


class GroqRouter:
    def __init__(self, config, store, client_factory=GroqClient, *,
                 max_transport_retries=2, base_backoff_seconds=1.0, max_inline_wait_seconds=60.0,
                 clock=time.time, sleep=time.sleep):
        if type(max_transport_retries) is not int or max_transport_retries < 0:
            raise GeminiConfigError("Groq transport retries must be a non-negative integer")
        if any(not math.isfinite(limit) or limit < 0 for limit in (base_backoff_seconds, max_inline_wait_seconds)):
            raise GeminiConfigError("Groq backoff and wait limits must be finite and non-negative")
        self._config = config
        self._store = store
        self._client_factory = client_factory
        self._retries = max_transport_retries
        self._backoff = base_backoff_seconds
        self._max_wait = max_inline_wait_seconds
        self._clock = clock
        self._sleep = sleep
        self._slots = deque(config.slots)
        self._disabled = set()
        self._lock = Lock()

    def _next_slot(self, model, now):
        blocked = {}
        with self._lock:
            for _ in range(len(self._slots)):
                slot = self._slots[0]
                self._slots.rotate(-1)
                if slot.slot_id in self._disabled or slot.scope in blocked:
                    continue
                until = self._store.blocked_until("groq", model, slot.scope, now)
                if until is None:
                    return slot, None
                blocked[slot.scope] = until
        return None, min(blocked.values(), default=None)

    def generate(self, system_instruction, user_content, model, generation_config, request_id):
        if any(secret in model for secret in self._config._secrets):
            raise GeminiConfigError("Model contains credential material")
        self._config.check_models((model,))
        start = self._clock()
        attempts = []
        refused = set()
        rate_limits = 0
        retries = 0
        waited = False
        while True:
            now = self._clock()
            slot, resume = self._next_slot(model, now)
            if slot is None:
                if resume is None:
                    raise GroqTransportError("NO_USABLE_CREDENTIAL", len(attempts))
                if waited or resume - now > self._max_wait:
                    raise GroqQuotaPaused(len(attempts), resume)
                self._sleep(resume - now)
                waited = True
                continue
            quota_key = ("groq", model, slot.scope)
            metadata = {"slot_id": slot.slot_id, "scope": slot.scope}
            attempt = {"attempt": len(attempts) + 1, **metadata}
            attempts.append(attempt)
            try:
                response = self._client_factory(slot._api_key).generate(
                    model=model, system_instruction=system_instruction, user_content=user_content,
                    generation_config=generation_config,
                )
            except GroqHTTPError as error:
                failure = error
            else:
                end = self._clock()
                attempt["outcome"] = "SUCCESS"
                self._store.record_success(*quota_key, end)
                if str(response.headers.get("x-ratelimit-remaining-requests")).strip() == "0":
                    decision = decide_groq_rate_limit(200, response.headers, {}, end, 0)
                    self._store.block(*quota_key, decision.blocked_until, decision.reason, end)
                record = {
                    "request_id": request_id, "provider": "Groq", "transport": "GROQ_ROUTER_V1",
                    "quota_scope": "organization_model", "model_requested": model,
                    "model_reported_if_available": response.model, **metadata,
                    "start_time": _utc_iso(start), "end_time": _utc_iso(end),
                    "latency_seconds": max(0, end - start), "usage_metadata": response.usage,
                    "provider_response_metadata": {"response_id": response_id}
                    if (response_id := getattr(response, "response_id", None)) else {},
                    "raw_content": response.text, "transport_attempts": attempts,
                }
                return redact_groq_data(record, self._config._secrets)

            kind = attempt["outcome"] = failure.kind
            if kind == "RATE_LIMIT":
                now = self._clock()
                decision = decide_groq_rate_limit(failure, None, None, now, self._store.unknown_streak(*quota_key))
                self._store.block(*quota_key, decision.blocked_until, decision.reason, now)
                refused.add(slot.scope)
                rate_limits += 1
                if rate_limits >= self._config.max_rate_limit_hops:
                    resume = min(self._store.blocked_until("groq", model, scope, now) or now for scope in refused)
                    raise GroqQuotaPaused(len(attempts), resume)
            elif kind == "AUTH_FAILURE":
                with self._lock:
                    self._disabled.add(slot.slot_id)
            elif kind in ("SERVER_FAILURE", "TRANSPORT_FAILURE") and retries < self._retries:
                self._sleep(self._backoff * 2 ** retries)
                retries += 1
            else:
                raise GroqTransportError(redact_groq_data(kind, self._config._secrets), len(attempts))
