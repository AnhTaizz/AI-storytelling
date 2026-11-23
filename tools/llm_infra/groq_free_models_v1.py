"""Production text models reviewed for use with Groq Free plan keys."""

SOURCE_URL = "https://console.groq.com/docs/models"
VERIFIED_ON = "2026-11-23"
VERIFICATION_NOTE = ("Production models only. Free-plan limits apply per organization and "
                     "are shown at https://console.groq.com/settings/limits.")
FREE_TIER_TEXT_MODELS = ("openai/gpt-oss-120b", "openai/gpt-oss-20b",
                         "llama-3.3-70b-versatile", "llama-3.1-8b-instant")
DEFAULT_MODEL_CHAIN = ("openai/gpt-oss-120b", "llama-3.3-70b-versatile")
