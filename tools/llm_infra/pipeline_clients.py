"""Pipeline adapters over the existing free-only provider routers."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import partial
import time

from tools.llm_infra.cloudflare_config import CREDENTIAL_PATTERN, inspect_cloudflare_settings
from tools.llm_infra.cloudflare_router import CloudflareRouter, CloudflareTransportError
from tools.llm_infra.cloudflare_transport import CloudflareClient, CloudflareHTTPError
from tools.llm_infra.gemini_config import inspect_settings
from tools.llm_infra.gemini_router import GeminiRouter
from tools.llm_infra.groq_config import GROQ_KEY_PATTERN, inspect_groq_settings
from tools.llm_infra.groq_router import GroqRouter, GroqTransportError
from tools.llm_infra.groq_transport import GroqClient
from tools.llm_infra.model_capabilities_v1 import model_capability
from tools.llm_infra.neuron_ledger import estimate_prompt_neurons
from tools.llm_infra.openrouter_config import OPENROUTER_KEY_PATTERN, inspect_openrouter_settings
from tools.llm_infra.openrouter_router import OpenRouterRouter, OpenRouterTransportError
from tools.llm_infra.openrouter_transport import OpenRouterClient, OpenRouterHTTPError
from tools.llm_infra.routing_policy import DEFAULT_OUTPUT_TOKENS
from tools.llm_infra.telemetry import public_counters, usage_counts
from tools.llm_infra.token_estimate import estimate_input_tokens
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError, GeminiKeyPool, _KEY_PATTERN
from tools.story_extraction.gemini_transport_v1 import GeminiTransportError, _utc_iso, official_client_factory


JSON_PROMPT = "\nReply with one JSON object only."
MAX_TRANSPORT_CALLS = 24
_TRANSPORT_ERRORS = (GroqTransportError, OpenRouterTransportError, CloudflareTransportError, GeminiTransportError)
_ERROR_CODES = frozenset({
    "ACCOUNT_BLOCKED", "AUTH_FAILURE", "EDGE_BLOCKED", "FORBIDDEN", "MALFORMED_RESPONSE",
    "MODEL_NOT_FREE", "MODEL_REQUIRES_PAID", "MODEL_UNAVAILABLE", "NETWORK_FAILURE",
    "NO_USABLE_CREDENTIAL", "PAID_USAGE_DETECTED", "PAYMENT_REQUIRED", "POOL_EXHAUSTED",
    "REQUEST_FAILURE", "REQUEST_TOO_LARGE", "SERVER_FAILURE", "TIMEOUT", "TRANSPORT_FAILURE",
})
_QUOTA_SCOPES = {"gemini": "project_model", "groq": "organization_model",
                 "openrouter": "account", "cloudflare": "account_neurons"}
_INSPECTORS = {"groq": inspect_groq_settings, "openrouter": inspect_openrouter_settings,
               "cloudflare": inspect_cloudflare_settings}
_BUDGET = ContextVar("pipeline_transport_budget", default=None)
_COUNTERS = ContextVar("pipeline_public_counters", default=None)


class _DispatchLimit(BaseException):
    """Leave provider retry loops immediately when the shared dispatch budget is spent."""


class ProviderFailure(RuntimeError):
    def __init__(self, code, resume_after=None, *, metadata=None):
        self.code = code
        self.resume_after = resume_after
        self.metadata = metadata
        suffix = f". Quota resumes at {_utc_iso(resume_after)}" if resume_after is not None else ""
        super().__init__(code + suffix)


@contextmanager
def transport_budget():
    token = _BUDGET.set([MAX_TRANSPORT_CALLS])
    try:
        yield
    finally:
        _BUDGET.reset(token)


def configured_secrets(settings):
    patterns = (_KEY_PATTERN, GROQ_KEY_PATTERN, OPENROUTER_KEY_PATTERN, CREDENTIAL_PATTERN)
    return tuple(value.strip() for name, value in settings.items()
                 if value.strip() and any(pattern.fullmatch(name) for pattern in patterns))


class _ObservedTransport:
    def __init__(self, factory, credentials):
        self.factory = factory
        self.credentials = credentials

    def generate(self, **kwargs):
        budget = _BUDGET.get()
        if budget is not None:
            if budget[0] == 0:
                raise _DispatchLimit()
            budget[0] -= 1
        response = self.factory(*self.credentials).generate(**kwargs)
        counters = public_counters(getattr(response, "headers", None) or {})
        _COUNTERS.set(counters)
        return response


def _observe(factory):
    return lambda *credentials: _ObservedTransport(factory, credentials)


def normalized_record(provider, record, counters=None):
    return record | {"provider": provider, "model_reported": record.get("model_reported_if_available"),
                     "quota_scope": _QUOTA_SCOPES[provider],
                     "usage": usage_counts(record), "latency_ms": round(1000 * record.get("latency_seconds", 0)),
                     "quota_remaining": counters or {}}


def _object(value):
    return value if isinstance(value, dict) else {}


def _failure_diagnostics(error):
    """Project a provider failure onto fields safe to keep in a benchmark checkpoint."""
    if not isinstance(error, (CloudflareHTTPError, OpenRouterHTTPError)) or error.status is None:
        return {}
    body = _object(error.body)
    data = _object(body.get("result")) if "result" in body else body
    details = {"http_status": error.status, "response_shape": "object" if body else "empty_or_nonobject"}
    native_errors = body.get("errors")
    provider_error = _object(body.get("error")) or _object(data.get("error"))
    if not provider_error and isinstance(native_errors, list):
        provider_error = next((item for item in native_errors if isinstance(item, dict)), {})
    if provider_error or "error" in body or native_errors or body.get("success") is False:
        details["response_shape"] = "error"
        if type(code := provider_error.get("code")) is int and 0 <= code <= 999999:
            details["provider_error_code"] = code
        if (param := provider_error.get("param")) in (
                "response_format", "max_tokens", "temperature", "model", "messages", "provider", "reasoning"):
            details["error_parameter"] = param

    choices = data.get("choices")
    if "choices" in data:
        details["response_shape"] = "result_choices" if data is not body else "choices"
        choice = _object(choices[0]) if isinstance(choices, list) and choices else {}
        if (reason := choice.get("finish_reason")) in ("stop", "length", "tool_calls", "content_filter", "error"):
            details["finish_reason"] = reason
        message = _object(choice.get("message"))
        content = message.get("content")
        state = "missing"
        if "content" in message:
            state = "null" if content is None else "other"
            if isinstance(content, str):
                state = "text" if content.strip() else "empty"
        details["content_state"] = state
    elif "response" in data:
        details["response_shape"] = "result_response" if data is not body else "response"
    usage = _object(data.get("usage")) or _object(body.get("usage"))
    details.update({key: value for key, value in usage_counts({"usage_metadata": usage}).items()
                    if value is not None})
    return details


class ProviderAdapter:
    def __init__(self, provider, router, models, check_models, *, temperature=0.4, clock=time.time, secrets=()):
        self.provider = provider
        self.router = router
        self.models = tuple(models)
        self.name = f"{provider}:{','.join(self.models)}"
        self._check_models = check_models
        self.temperature = temperature
        self.clock = clock
        self._secrets = secrets

    def allows(self, model):
        if any(secret in model for secret in self._secrets):
            return False
        try:
            self._check_models((model,))
        except GeminiConfigError:
            return False
        return True

    def availability(self, model, system="", user=""):
        """Return (skip code, earliest resume) using the provider's existing quota state."""
        now = self.clock()
        router = self.router
        if self.provider == "gemini":
            blocks = [router.store.blocked_until("gemini", model, group, now)
                      for group in router.pool.group_ids() if router.pool.available_slot_count(group)]
            if None in blocks:
                return None, None
            slot, resume = None, min(blocks, default=None)
        elif self.provider == "groq":
            slot, resume = router._next_slot(model, now)
        elif self.provider == "openrouter":
            slot, resume = router._next_slot(now)
        else:
            chars = len(system) + len(user) + len(JSON_PROMPT)
            # Reuse the Neuron calculation and quota-state check in the existing router.
            slot, resume, _ = router._next_slot(now, estimate_prompt_neurons(model, chars))
        if slot is not None:
            return None, None
        return ("QUOTA_EXHAUSTED", resume) if resume is not None else ("NO_USABLE_CREDENTIAL", None)

    def complete(self, *, system, user, request_id, model=None, max_output_tokens=DEFAULT_OUTPUT_TOKENS):
        model = self.models[0] if model is None else model
        capability = model_capability(self.provider, model)
        if capability is None or not self.allows(model):
            raise ProviderFailure("MODEL_NOT_FREE_TIER")
        extra = JSON_PROMPT if capability.json_mode == "prompt" else ""
        if estimate_input_tokens(system, user, extra) + max_output_tokens > capability.capacity:
            raise ProviderFailure("REQUEST_TOO_LARGE")
        config = {"temperature": self.temperature, "max_output_tokens": max_output_tokens}
        if self.provider == "cloudflare":
            system += JSON_PROMPT
        else:
            config["response_mime_type"] = "application/json"
        token = _COUNTERS.set({})
        try:
            record = self.router.generate(system, user, model, config, request_id)
            return normalized_record(self.provider, record, _COUNTERS.get())
        except _TRANSPORT_ERRORS as error:
            code = error.code
            # Only deliberate quota errors match the pipeline's message-based pause contract.
            if code in {"RATE_LIMIT", "QUOTA_EXHAUSTED"}:
                code = "QUOTA_EXHAUSTED"
            elif code not in _ERROR_CODES:
                code = "PROVIDER_FAILURE"
            metadata = {"quota_scope": _QUOTA_SCOPES[self.provider]}
            if diagnostics := _failure_diagnostics(error.__cause__):
                metadata["provider_diagnostics"] = diagnostics
            raise ProviderFailure(code, getattr(error, "resume_after", None),
                                  metadata=metadata) from None
        except _DispatchLimit:
            raise ProviderFailure("DISPATCH_LIMIT") from None
        finally:
            _COUNTERS.reset(token)


def build_adapter(provider, settings, store, *, model=None, temperature=0.4, clock=time.time,
                  client_factory=None, strict=False, secrets=None):
    """Use the provider's existing settings loader logic and router over the shared store."""
    secrets = configured_secrets(settings) if secrets is None else secrets
    if provider == "gemini":
        config = inspect_settings(settings, model)
        credentials = config.policy.eligible_credentials(config.credentials)
        check_models = config.policy.check_models
        models = tuple(item.strip() for item in config.model.split(",") if item.strip())
        router = GeminiRouter(GeminiKeyPool(credentials, clock=clock), store,
                              _observe(client_factory or official_client_factory),
                              max_rate_limit_hops=config.max_rate_limit_hops, clock=clock)
    else:
        config = _INSPECTORS[provider](settings, model, validate_models=False)
        config.check_eligible()
        check_models, models = config.check_models, config.model_chain
        if provider == "groq":
            router = GroqRouter(config, store, _observe(client_factory or GroqClient), clock=clock)
        elif provider == "openrouter":
            factory = client_factory or partial(OpenRouterClient, data_collection=config.data_collection)
            router = OpenRouterRouter(config, store, _observe(factory), clock=clock)
        else:
            router = CloudflareRouter(config, store, _observe(client_factory or CloudflareClient), clock=clock)
    adapter = ProviderAdapter(provider, router, models, check_models, temperature=temperature, clock=clock,
                              secrets=secrets)
    if strict and (not models or not all(adapter.allows(item) for item in models)):
        raise GeminiConfigError("MODEL_NOT_FREE_TIER: use a model on the provider's free list")
    return adapter
