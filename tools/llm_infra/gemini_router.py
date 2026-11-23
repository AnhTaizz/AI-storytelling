"""Rotate Gemini projects while keeping quota decisions scoped to the requested model."""
import json
import time

from tools.llm_infra.quota_policy import decide_rate_limit
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError, GeminiPoolExhausted
from tools.story_extraction.gemini_transport_v1 import (
    GeminiTransportError, _classify_error, _redact_tree, _safe_provider_metadata,
    _safe_usage, _utc_iso, official_client_factory,
)


class GeminiQuotaPaused(GeminiTransportError):
    def __init__(self, attempts, resume_after):
        super().__init__("QUOTA_EXHAUSTED", attempts)
        self.resume_after = resume_after
        self.args = (f"{self}; quota resumes at {_utc_iso(resume_after)}",)


class GeminiRouter:
    def __init__(self, pool, store, client_factory=official_client_factory, *,
                 max_transport_retries=2, base_backoff_seconds=1.0, max_inline_wait_seconds=60.0,
                 clock=time.time, sleep=time.sleep):
        if min(max_transport_retries, base_backoff_seconds, max_inline_wait_seconds) < 0:
            raise GeminiConfigError("Retry and wait limits must be non-negative")
        self.pool = pool
        self.store = store
        self.factory = client_factory
        self.retries = max_transport_retries
        self.backoff = base_backoff_seconds
        self.max_wait = max_inline_wait_seconds
        self.clock = clock
        self.sleep = sleep

    def generate(self, system_instruction, user_content, model, generation_config, request_id):
        start = self.clock()
        attempts = []
        groups = self.pool.group_ids()
        cap = self.retries + 1 + len(groups)
        waited = False
        last_code = "POOL_EXHAUSTED"
        if self.pool.redact(model) != model:
            raise GeminiConfigError("Model contains credential material")
        while True:
            now = self.clock()
            blocked = {}
            for group in groups:
                if self.pool.available_slot_count(group):
                    until = self.store.blocked_until("gemini", model, group, now)
                    if until is not None:
                        blocked[group] = until
            try:
                lease = self.pool.acquire(now, excluded_group_ids=blocked)
            except GeminiPoolExhausted:
                if not blocked:
                    raise GeminiTransportError("NO_USABLE_CREDENTIAL", len(attempts)) from None
                resume = min(blocked.values())
                if waited or resume - now > self.max_wait or len(attempts) >= cap:
                    raise GeminiQuotaPaused(len(attempts), resume) from None
                self.sleep(resume - now)
                waited = True
                continue
            if len(attempts) >= cap:
                raise GeminiTransportError(last_code, len(attempts)) from None
            scope = ("gemini", model, lease.group_id)
            attempt = {"attempt": len(attempts) + 1, **lease.public_metadata()}
            attempts.append(attempt)
            try:
                response = self.factory(lease.api_key).generate(model=model, system_instruction=system_instruction,
                    user_content=user_content, generation_config=dict(generation_config))
                content = getattr(response, "text", None)
                if content is None:
                    content = json.dumps(getattr(response, "parsed", None), ensure_ascii=False, separators=(",", ":"))
                end = self.clock()
                record = {"request_id": request_id, "provider": "Google Gemini API", "transport": "GEMINI_ROUTER_V1",
                          "quota_scope": "project_model", "model_requested": model,
                          "model_reported_if_available": getattr(response, "model_version", None),
                          **lease.public_metadata(), "start_time": _utc_iso(start), "end_time": _utc_iso(end),
                          "latency_seconds": max(0, end-start), "usage_metadata": _safe_usage(response),
                          "provider_response_metadata": _safe_provider_metadata(response), "raw_content": str(content),
                          "transport_attempts": attempts}
            except Exception as error:
                last_code = attempt["outcome"] = _classify_error(error)
                if last_code == "RATE_LIMIT":
                    now = self.clock()
                    decision = decide_rate_limit(error, now, self.store.unknown_streak(*scope))
                    self.store.block(*scope, decision.blocked_until, decision.reason, now)
                elif last_code == "AUTH_FAILURE":
                    self.pool.disable_slot(lease.slot_id)
                elif last_code in ("SERVER_FAILURE", "TRANSPORT_FAILURE") and len(attempts) <= self.retries:
                    self.sleep(self.backoff * 2 ** (len(attempts) - 1))
                else:
                    raise GeminiTransportError(last_code, len(attempts)) from None
                continue
            attempt["outcome"] = "SUCCESS"
            self.store.record_success(*scope, end)
            return _redact_tree(record, self.pool.redact)
