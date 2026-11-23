"""Decide when one project may next use one Gemini model."""
from dataclasses import dataclass
import re

from tools.story_extraction.gemini_errors_v1 import rate_limit_cause, retry_after_seconds

REASONS = ("RPM", "TPM", "RPD", "UNKNOWN_429")


@dataclass(frozen=True)
class QuotaDecision:
    reason: str
    blocked_until: float
    evidence: dict


def _details(error):
    for body in (getattr(error, "response_json", None), getattr(error, "details", None)):
        if isinstance(body, (dict, list)) and body:
            break
    else:
        try:
            body = error.response.json()
        except Exception:
            return []
    if isinstance(body, dict):
        body = body.get("error", body)
    if isinstance(body, dict):
        body = body.get("details", [])
    return body if isinstance(body, list) else []


def decide_rate_limit(error, now, unknown_streak):
    causes = set()
    delay = retry_after_seconds(error, now)
    for detail in _details(error):
        if not isinstance(detail, dict):
            continue
        kind = str(detail.get("@type", ""))
        if kind.endswith("google.rpc.RetryInfo"):
            value = str(detail.get("retryDelay", ""))
            if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?s", value):
                delay = max(delay or 0, float(value[:-1]))
        violations = detail.get("violations")
        if kind.endswith("google.rpc.QuotaFailure") and isinstance(violations, list):
            for violation in violations:
                if not isinstance(violation, dict):
                    continue
                quota = (str(violation.get("quotaId", "")) + " " +
                         str(violation.get("quotaMetric", ""))).lower().replace("_", "")
                if "perday" in quota:
                    causes.add("RPD")
                elif "perminute" in quota:
                    if "token" in quota:
                        causes.add("TPM")
                    elif "request" in quota:
                        causes.add("RPM")
    if causes:
        reason = next(name for name in ("RPD", "TPM", "RPM") if name in causes)
        source = "quota_failure"
    else:
        reason = {"RPD_DAILY_QUOTA": "RPD", "TPM_EXHAUSTION": "TPM",
                  "RPM_EXHAUSTION": "RPM"}.get(rate_limit_cause(error), "UNKNOWN_429")
        source = "unknown" if reason == "UNKNOWN_429" else "legacy"
    if reason == "RPD":
        # The next 08:00 UTC, including a full day if now is exactly the reset.
        seconds = max(delay or 0, 86400 - (now - 8 * 3600) % 86400)
    elif reason == "UNKNOWN_429" and not delay:  # a zero delay would retry at once
        seconds = min(900, 60 * 2 ** min(max(0, unknown_streak), 4))
    else:
        seconds = delay if reason == "UNKNOWN_429" else (delay or 60)
    return QuotaDecision(reason, now + min(seconds, 26 * 3600),
                         {"cause_source": source, "retry_after_present": delay is not None})
