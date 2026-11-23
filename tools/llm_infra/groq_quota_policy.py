"""Determine an organization-model cooldown from Groq rate-limit evidence."""
import math
import re

from tools.llm_infra.quota_policy import QuotaDecision


_NUMBER = r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
_DURATION = re.compile(rf"(?:(?P<h>{_NUMBER})h)?(?:(?P<m>{_NUMBER})m)?"
                       rf"(?:(?P<s>{_NUMBER})s)?(?:(?P<ms>{_NUMBER})ms)?")
_CAUSES = {
    "TPD": r"\btpd\b|\btokens per day\b",
    "RPD": r"\brpd\b|\brequests per day\b",
    "TPM": r"\btpm\b|\btokens per minute\b",
    "RPM": r"\brpm\b|\brequests per minute\b",
}
_RESET_HEADERS = {"RPD": "x-ratelimit-reset-requests", "TPM": "x-ratelimit-reset-tokens"}
_RETRY_MESSAGE = re.compile(r"\btry again in\s+(\S+)", re.IGNORECASE)


def parse_duration(value):
    """Return seconds for a plain number or a Groq duration, or None for bad input."""
    text = str(value).strip().lower()
    if not text:
        return None
    if re.fullmatch(_NUMBER, text):
        seconds = float(text)
    elif match := _DURATION.fullmatch(text):
        seconds = sum(float(match[unit] or 0) * factor
                      for unit, factor in (("h", 3600), ("m", 60), ("s", 1), ("ms", 0.001)))
    else:
        return None
    return seconds if math.isfinite(seconds) else None


def decide_groq_rate_limit(status_or_error_info, headers, body, now, unknown_streak):
    """Use explicit metadata, falling back to attributes of a transport error."""
    headers = headers if headers is not None else getattr(status_or_error_info, "headers", {})
    headers = {name.lower(): value for name, value in headers.items()}
    body = body if body is not None else getattr(status_or_error_info, "body", {})
    error = body.get("error")
    message = str(error.get("message", "")) if isinstance(error, dict) else ""

    reason = next((name for name, pattern in _CAUSES.items() if re.search(pattern, message, re.IGNORECASE)), None)
    if reason:
        source = "message"
    elif str(headers.get("x-ratelimit-remaining-requests")).strip() == "0":
        reason, source = "RPD", "headers"
    elif str(headers.get("x-ratelimit-remaining-tokens")).strip() == "0":
        reason, source = "TPM", "headers"
    else:
        reason, source = "UNKNOWN_429", "unknown"

    retry_after = parse_duration(headers.get("retry-after"))
    match = _RETRY_MESSAGE.search(message)
    retry_message = parse_duration(match[1].rstrip(".,;!?)]")) if match else None
    reset_header = _RESET_HEADERS.get(reason)
    reset = parse_duration(headers.get(reset_header)) if reset_header else None
    seconds = max(retry_after or 0, retry_message or 0, reset or 0)
    if not seconds:
        if reason in ("RPD", "TPD"):
            seconds = 3600
        elif reason == "UNKNOWN_429":
            seconds = min(900, 60 * 2 ** min(max(0, unknown_streak), 4))
        else:
            seconds = 60
    return QuotaDecision(reason, now + min(seconds, 26 * 3600),
                         {"cause_source": source, "retry_after_present": retry_after is not None})
