"""Determine account-wide Cloudflare cooldowns from classified refusals."""
from tools.llm_infra.openrouter_quota_policy import _retry_after
from tools.llm_infra.quota_policy import QuotaDecision


def decide_cloudflare_limit(kind, headers, body, now, unknown_streak):
    headers = {name.lower(): value for name, value in (headers or {}).items()}
    retry_after = _retry_after(headers.get("retry-after"), now)
    if kind == "DAILY_ALLOCATION_EXHAUSTED":
        reason, source = "RPD", "daily_allocation"
        seconds = 86400 - now % 86400
    elif kind == "RATE_LIMIT":
        reason, source = "RPM", "rate_limit"
        seconds = retry_after or 60
    else:
        reason, source = "UNKNOWN_429", "unknown"
        seconds = retry_after or min(900, 60 * 2 ** min(max(0, unknown_streak), 4))
    return QuotaDecision(reason, now + min(seconds, 26 * 3600),
                         {"cause_source": source, "retry_after_present": retry_after is not None})
