"""Determine an OpenRouter account cooldown from a 429 response."""
from datetime import timezone
from email.utils import parsedate_to_datetime
import math
import re

from tools.llm_infra.quota_policy import QuotaDecision


_DAILY = re.compile(r"\b(?:per[ -]day|daily)\b", re.IGNORECASE)
_MINUTE = re.compile(r"\bper[ -]minute\b", re.IGNORECASE)


def _number(value):
    try:
        seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _retry_after(value, now):
    if value is None:
        return None
    seconds = _number(value)
    if seconds is not None:
        return seconds
    try:
        retry_at = parsedate_to_datetime(str(value))
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0, retry_at.timestamp() - now)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def decide_openrouter_rate_limit(error_or_info, headers, body, now, unknown_streak):
    """Use explicit evidence or the attributes of an OpenRouter transport error."""
    headers = headers if headers is not None else getattr(error_or_info, "headers", {})
    headers = {name.lower(): value for name, value in headers.items()}
    body = body if body is not None else getattr(error_or_info, "body", {})
    error = body.get("error")
    error = error if isinstance(error, dict) else {}
    metadata = error.get("metadata")
    message = str(error.get("message", ""))
    limit = _number(headers.get("x-ratelimit-limit"))
    retry_after = _retry_after(headers.get("retry-after"), now)
    reset_ms = _number(headers.get("x-ratelimit-reset"))
    reset_delay = max(0, (reset_ms or 0) / 1000 - now)

    if isinstance(metadata, dict) and "provider_code" in metadata:
        reason, source = "UNKNOWN_429", "upstream_provider"
    elif limit in (50, 1000) or _DAILY.search(message):
        reason, source = "RPD", "headers" if limit in (50, 1000) else "message"
    elif limit == 20 or _MINUTE.search(message):
        reason, source = "RPM", "headers" if limit == 20 else "message"
    else:
        reason, source = "UNKNOWN_429", "unknown"

    if reason == "RPD":
        seconds = reset_delay or (86400 - now % 86400)
    elif reason == "RPM":
        seconds = reset_delay or retry_after or 60
    else:
        seconds = retry_after or min(900, 60 * 2 ** min(max(0, unknown_streak), 4))
    return QuotaDecision(reason, now + min(max(seconds, retry_after or 0), 26 * 3600),
                         {"cause_source": source, "retry_after_present": retry_after is not None})
