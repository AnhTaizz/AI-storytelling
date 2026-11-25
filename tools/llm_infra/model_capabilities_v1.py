"""Offline capability snapshot for the maintained free model lists."""
from dataclasses import dataclass

from tools.llm_infra import cloudflare_free_models_v1 as cloudflare
from tools.llm_infra import gemini_free_models_v1 as gemini
from tools.llm_infra import groq_free_models_v1 as groq
from tools.llm_infra import openrouter_free_models_v1 as openrouter


# Unknown context is limited to 16K total, including the output reserve.
UNKNOWN_CONTEXT_TOKENS = 16_384


@dataclass(frozen=True)
class ModelCapability:
    context_tokens: int | None
    max_request_tokens: int | None
    json_mode: str
    reasoning: bool | None
    source: str
    verified_on: str

    @property
    def capacity(self):
        context = self.context_tokens or UNKNOWN_CONTEXT_TOKENS
        return min(context, self.max_request_tokens or context)


def _snapshot(source, json_mode, *, reasoning=None, max_request_tokens=None):
    return ModelCapability(None, max_request_tokens, json_mode, reasoning, source.SOURCE_URL, source.VERIFIED_ON)


OPENROUTER_FREE_VARIANT = _snapshot(openrouter, "native")
CAPABILITIES = {
    **{("gemini", model): _snapshot(gemini, "native") for model in gemini.FREE_TIER_TEXT_MODELS},
    **{("groq", model): _snapshot(groq, "native", reasoning=True, max_request_tokens=groq.FREE_PLAN_TPM)
       for model in groq.FREE_TIER_TEXT_MODELS},
    **{("cloudflare", model): _snapshot(cloudflare, "prompt", reasoning=True if "gpt-oss" in model else None)
       for model in cloudflare.ACTIVE_NEURON_PRICES},
    **{("openrouter", model): OPENROUTER_FREE_VARIANT for model in openrouter.DEFAULT_MODEL_CHAIN},
}


def model_capability(provider, model, capabilities=CAPABILITIES):
    if provider == "openrouter":
        return capabilities.get((provider, model), OPENROUTER_FREE_VARIANT) if openrouter.is_free_model(model) else None
    return capabilities.get((provider, model))
