"""Reviewed Workers Free text models and their Neuron prices per million tokens."""

SOURCE_URL = "https://developers.cloudflare.com/workers-ai/platform/pricing/"
VERIFIED_ON = "2026-11-24"
VERIFICATION_NOTE = "Phase 4 permits only reviewed text models available on Workers Free."
NEURON_PRICES = {
    "@cf/openai/gpt-oss-120b": (31818, 68182),
    "@cf/openai/gpt-oss-20b": (18182, 27273),
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast": (26668, 204805),
    "@cf/qwen/qwen3-30b-a3b-fp8": (4625, 30475),
    "@cf/google/gemma-4-26b-a4b-it": (9091, 27273),
    "@cf/zai-org/glm-4.7-flash": (5500, 36400),
    "@cf/mistralai/mistral-small-3.1-24b-instruct": (31876, 50488),
    "@cf/meta/llama-3.1-8b-instruct-fp8": (13778, 26128),
}
DEFAULT_MODEL_CHAIN = ("@cf/openai/gpt-oss-120b", "@cf/qwen/qwen3-30b-a3b-fp8")
DAILY_FREE_NEURONS = 10000
