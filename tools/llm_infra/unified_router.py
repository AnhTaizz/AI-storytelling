"""Select eligible free providers without changing pipeline validation."""
from copy import copy
import re
import time

from tools.llm_infra.model_capabilities_v1 import CAPABILITIES, model_capability
from tools.llm_infra.pipeline_clients import JSON_PROMPT, ProviderFailure, normalized_record, transport_budget
from tools.llm_infra.telemetry import record_event
from tools.llm_infra.token_estimate import estimate_input_tokens


MAX_PROVIDER_CALLS = 12
_TRANSIENT = frozenset({"SERVER_FAILURE", "TRANSPORT_FAILURE", "TIMEOUT", "NETWORK_FAILURE"})
_FALLBACK = _TRANSIENT | {"QUOTA_EXHAUSTED"}
_LEGACY_CODE = re.compile(r"transport failed(?: safely)?: ([A-Z_]+)", re.IGNORECASE)


def request_stage(request_id):
    return request_id.split(":", 1)[0]


class _TelemetryClient:
    run_id = None

    def for_run(self, run_id):
        bound = copy(self)
        bound.run_id = run_id
        return bound

    def _record(self, request_id, stage, *, provider=None, model=None, outcome, code=None, record=None,
                estimated=None, skips=(), elapsed=None):
        record = record or {}
        tokens = record.get("usage") or {}
        cost = record.get("cost_reported")
        if any(value is not None for value in tokens.values()):
            source = "reported"
        elif estimated is not None:
            source = "estimated"
            tokens = dict(zip(("input_tokens", "output_tokens"), estimated))
        else:
            source = "unknown"
        record_event(self.telemetry, run_id=self.run_id, stage=stage, request_id=request_id,
                     provider=provider, model_requested=record.get("model_requested", model),
                     model_reported=record.get("model_reported"), outcome=outcome, error_code=code,
                     **tokens, tokens_source=source, latency_ms=record.get("latency_ms", elapsed),
                     quota_scope=record.get("quota_scope"), quota_remaining=record.get("quota_remaining"),
                     cost_reported=cost, cost_source="reported" if cost is not None else "unknown",
                     routing_policy_sha256=self.policy_hash, skip_reasons=skips)


class ObservedGeminiClient(_TelemetryClient):
    """Preserve the legacy Gemini model chain, request settings and exception behavior."""
    provider = "gemini"
    policy_hash = None

    def __init__(self, client, telemetry):
        self.client = client
        self.name = client.name
        self.telemetry = telemetry

    def complete(self, *, system, user, request_id):
        stage = request_stage(request_id)
        start = time.monotonic()
        try:
            record = normalized_record("gemini", self.client.complete(system=system, user=user, request_id=request_id))
        except Exception as error:
            match = _LEGACY_CODE.search(str(error))
            self._record(request_id, stage, provider="gemini", model=getattr(self.client, "model", None),
                         outcome="FAILED", code=match[1] if match else "PROVIDER_FAILURE",
                         elapsed=round(1000 * (time.monotonic() - start)))
            raise
        self._record(request_id, stage, provider="gemini", outcome="SUCCESS", record=record)
        return record


class UnifiedLLMClient(_TelemetryClient):
    def __init__(self, policy, adapters, capabilities=CAPABILITIES, telemetry=None,
                 stage_resolver=request_stage, *, provider="auto"):
        self.policy = policy
        self.adapters = adapters
        self.capabilities = capabilities
        self.telemetry = telemetry
        self.stage_resolver = stage_resolver
        self.provider = provider
        self.policy_hash = policy.sha256
        self.name = "auto" if provider == "auto" else adapters[provider].name

    def candidates(self, tier):
        seen = set()
        for provider, selector in tier.selectors():
            adapter = self.adapters.get(provider)
            models = (adapter.models or ("*",)) if selector == "*" and adapter else (selector,)
            for model in models:
                if (provider, model) not in seen:
                    seen.add((provider, model))
                    yield provider, model, adapter

    def eligibility(self, provider, model, adapter, tier, system="", user=""):
        if adapter is None:
            return "NOT_CONFIGURED", None, None
        capability = model_capability(provider, model, self.capabilities)
        if capability is None or not adapter.allows(model):
            return "MODEL_NOT_FREE_TIER", None, None
        extra = JSON_PROMPT if capability.json_mode == "prompt" else ""
        estimated = (estimate_input_tokens(system, user, extra), tier.max_output_tokens)
        if sum(estimated) > capability.capacity:
            return "REQUEST_TOO_LARGE", None, estimated
        if capability.json_mode not in {"native", "prompt"}:
            return "JSON_UNSUPPORTED", None, estimated
        reason, resume = adapter.availability(model, system, user)
        return reason, resume, estimated

    def complete(self, *, system, user, request_id):
        with transport_budget():
            return self._complete(system, user, request_id)

    def _complete(self, system, user, request_id):
        stage = self.stage_resolver(request_id)
        tier = self.policy.tier_for(stage)
        skips, resumes, fallback = [], [], []
        calls = quota_count = 0
        for provider, model, adapter in self.candidates(tier):
            reason, resume, estimated = self.eligibility(provider, model, adapter, tier, system, user)
            if reason is None and calls >= MAX_PROVIDER_CALLS:
                reason = "DISPATCH_LIMIT"
            if reason is None:
                calls += 1
                start = time.monotonic()
                try:
                    record = adapter.complete(system=system, user=user, request_id=request_id, model=model,
                                              max_output_tokens=tier.max_output_tokens)
                except ProviderFailure as error:
                    reason, resume = error.code, error.resume_after
                    # A failed transport has no trustworthy usage. The estimates on
                    # skipped requests describe the preflight decision instead.
                    self._record(request_id, stage, provider=provider, model=model, outcome="FAILED",
                                 code=reason, record=error.metadata, skips=skips,
                                 elapsed=round(1000 * (time.monotonic() - start)))
                    if reason not in _FALLBACK or not tier.cross_provider_fallback:
                        raise
                    fallback.append({"provider": provider, "model": model, "code": reason})
                else:
                    self._record(request_id, stage, provider=provider, model=model, outcome="SUCCESS",
                                 record=record, estimated=estimated, skips=skips)
                    return record | {"fallback_from": fallback}
            else:
                self._record(request_id, stage, provider=provider, model=model, outcome="SKIPPED",
                             code=reason, estimated=estimated, skips=[f"{provider}:{reason}"])
            skips.append(f"{provider}:{reason}")
            if reason == "QUOTA_EXHAUSTED":
                quota_count += 1
                if resume is not None:
                    resumes.append(resume)
        if skips and quota_count == len(skips):
            raise ProviderFailure("QUOTA_EXHAUSTED", min(resumes, default=None))
        # Keep quota messages mixed with other failures from matching QUOTA_PATTERN.
        public = ", ".join(reason.replace("QUOTA_EXHAUSTED", "TEMPORARILY_BLOCKED") for reason in skips)
        raise RuntimeError(f"NO_ELIGIBLE_PROVIDER ({public or 'no candidates'})")
