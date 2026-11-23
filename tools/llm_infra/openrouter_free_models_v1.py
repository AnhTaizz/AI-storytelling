"""Reviewed rule for selecting free OpenRouter models."""

SOURCE_URL = "https://openrouter.ai/docs/guides/routing/model-variants/free"
VERIFIED_ON = "2026-11-23"
VERIFICATION_NOTE = "The :free variant is free, and openrouter/free routes only to free models."
DEFAULT_MODEL_CHAIN = ("openrouter/free",)


def is_free_model(model_id: str) -> bool:
    """Accept the free router or a single lowercase model ID with a terminal :free."""
    if not isinstance(model_id, str) or model_id != model_id.lower():
        return False
    if "," in model_id or not model_id.isprintable() or any(char.isspace() for char in model_id):
        return False
    base, _, suffix = model_id.partition(":free")
    return model_id == "openrouter/free" or bool(base and not suffix and model_id.endswith(":free"))
