"""Production text models reviewed for use with Groq Free plan keys."""

SOURCE_URL = "https://console.groq.com/docs/models"
VERIFIED_ON = "2026-11-23"
VERIFICATION_NOTE = ("Production models only. Free-plan limits apply per organization and "
                     "are shown at https://console.groq.com/settings/limits. "
                     "Removed llama-3.3-70b-versatile and llama-3.1-8b-instant after their "
                     "2026-08-16 shutdown listed at https://console.groq.com/docs/deprecations.")
FREE_TIER_TEXT_MODELS = ("openai/gpt-oss-120b", "openai/gpt-oss-20b")
DEFAULT_MODEL_CHAIN = FREE_TIER_TEXT_MODELS
SMOKE_MODEL = "openai/gpt-oss-20b"
FREE_PLAN_TPM = 8000
