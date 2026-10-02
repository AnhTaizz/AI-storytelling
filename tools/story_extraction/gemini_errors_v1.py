"""Centralized, secret-safe Gemini transport error classification."""

from __future__ import annotations

from email.utils import parsedate_to_datetime
from enum import Enum
from datetime import timezone
import re
from typing import Any, Mapping, Optional


class ErrorCategory(str, Enum):
    SUCCESS = "SUCCESS"
    RATE_LIMIT = "RATE_LIMIT"
    AUTH_FAILURE = "AUTH_FAILURE"
    SERVER_FAILURE = "SERVER_FAILURE"
    TIMEOUT = "TIMEOUT"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    LOCAL_RATE_LIMIT_WAIT = "LOCAL_RATE_LIMIT_WAIT"
    QUEUE_REJECTED = "QUEUE_REJECTED"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"


_SAFE_REASON = re.compile(r"^[A-Z][A-Z0-9_.-]{0,63}$")


def status_code(error: BaseException) -> Optional[int]:
    candidates = (
        getattr(error, "status_code", None),
        getattr(error, "code", None),
        getattr(getattr(error, "response", None), "status_code", None),
    )
    for candidate in candidates:
        if isinstance(candidate, int):
            return candidate
        if isinstance(candidate, str) and candidate.isdigit():
            return int(candidate)
    return None


def classify_error(error: BaseException) -> ErrorCategory:
    status = status_code(error)
    if status in (401, 403):
        return ErrorCategory.AUTH_FAILURE
    if status == 400:
        # This text is examined only in memory. It is never propagated.
        structured = getattr(error, "response_json", None)
        diagnostic = f"{getattr(error, 'status', '')} {structured!r} {error}"
        markers = ("API_KEY_INVALID", "API KEY NOT VALID", "UNAUTHENTICATED")
        if any(marker in diagnostic.upper() for marker in markers):
            return ErrorCategory.AUTH_FAILURE
    if status == 429:
        return ErrorCategory.RATE_LIMIT
    if status is not None and 500 <= status <= 599:
        return ErrorCategory.SERVER_FAILURE
    if isinstance(error, TimeoutError):
        return ErrorCategory.TIMEOUT
    if isinstance(error, (ConnectionError, OSError)):
        return ErrorCategory.NETWORK_FAILURE
    return ErrorCategory.PROVIDER_FAILURE


def retry_after_seconds(error: BaseException, now: float) -> Optional[float]:
    direct = getattr(error, "retry_after", None)
    if isinstance(direct, (int, float)):
        return max(0.0, float(direct))
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    value = headers.get("Retry-After") or headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(str(value))
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, retry_at.timestamp() - now)
        except (TypeError, ValueError, OverflowError):
            return None


def _safe_reason_token(value: Any) -> Optional[str]:
    """Return a bounded enum-like provider token, never free-form text."""
    if hasattr(value, "name"):
        value = getattr(value, "name")
    if not isinstance(value, str):
        return None
    candidate = value.strip().upper()
    return candidate if _SAFE_REASON.fullmatch(candidate) else None


def _structured_error(error: BaseException) -> Mapping[str, Any]:
    value = getattr(error, "response_json", None)
    if isinstance(value, Mapping):
        nested = value.get("error")
        return nested if isinstance(nested, Mapping) else value
    response = getattr(error, "response", None)
    json_method = getattr(response, "json", None)
    if callable(json_method):
        try:
            value = json_method()
        except Exception:
            value = None
        if isinstance(value, Mapping):
            nested = value.get("error")
            return nested if isinstance(nested, Mapping) else value
    return {}


def provider_reason(error: BaseException) -> Optional[str]:
    """Extract only a structured enum/code suitable for sanitized diagnostics."""
    structured = _structured_error(error)
    candidates = (
        getattr(error, "reason", None),
        getattr(error, "status", None),
        structured.get("status"),
        structured.get("reason"),
    )
    for candidate in candidates:
        safe = _safe_reason_token(candidate)
        if safe is not None and not safe.isdigit():
            return safe
    details = structured.get("details")
    if isinstance(details, list):
        for detail in details:
            if not isinstance(detail, Mapping):
                continue
            for name in ("reason", "status", "code"):
                safe = _safe_reason_token(detail.get(name))
                if safe is not None and not safe.isdigit():
                    return safe
    return None


def rate_limit_cause(error: BaseException) -> str:
    """Classify structured quota metadata conservatively into a fixed vocabulary."""
    if classify_error(error) != ErrorCategory.RATE_LIMIT:
        return "NOT_RATE_LIMIT"
    structured = _structured_error(error)
    # This representation is used only in memory for marker matching and is
    # never emitted. Public diagnostics contain only the canonical result.
    diagnostic = repr(structured).upper()
    if any(marker in diagnostic for marker in ("TOKENS_PER_MINUTE", "TOKEN_PER_MINUTE", "TPM")):
        return "TPM_EXHAUSTION"
    if any(marker in diagnostic for marker in ("REQUESTS_PER_MINUTE", "REQUEST_PER_MINUTE", "RPM")):
        return "RPM_EXHAUSTION"
    if any(marker in diagnostic for marker in ("REQUESTS_PER_DAY", "REQUEST_PER_DAY", "RPD", "DAILY")):
        return "RPD_DAILY_QUOTA"
    if "MODEL" in diagnostic and any(
        marker in diagnostic for marker in ("QUOTA", "LIMIT", "RATE")
    ):
        return "MODEL_SPECIFIC_QUOTA"
    return "429_CAUSE_NOT_EXPOSED"


def failure_fingerprint(
    error: BaseException,
    category: Optional[ErrorCategory] = None,
) -> str:
    """Create a stable, message-free diagnostic fingerprint."""
    resolved = category or classify_error(error)
    status = status_code(error)
    reason = provider_reason(error)
    if resolved == ErrorCategory.RATE_LIMIT and reason:
        suffix = reason
    elif status is not None:
        suffix = str(status)
    elif reason:
        suffix = reason
    else:
        suffix = "NO_PROVIDER_CODE"
    return f"{resolved.value}:{suffix}"


def sanitized_failure_metadata(error: BaseException, now: float) -> dict[str, Any]:
    """Return provider diagnostics with no exception message or credential data."""
    category = classify_error(error)
    status = status_code(error)
    reason = provider_reason(error)
    retry_after = retry_after_seconds(error, now)
    result: dict[str, Any] = {
        "category": category.value,
        "fingerprint": failure_fingerprint(error, category),
        "http_status": status,
        "http_status_family": f"{status // 100}xx" if status is not None else None,
        "provider_reason": reason,
        "retry_after_present": retry_after is not None,
        "retry_after_seconds": retry_after,
    }
    if category == ErrorCategory.RATE_LIMIT:
        result["rate_limit_cause"] = rate_limit_cause(error)
    return result
