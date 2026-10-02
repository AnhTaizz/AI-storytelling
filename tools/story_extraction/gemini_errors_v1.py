"""Centralized, secret-safe Gemini transport error classification."""

from __future__ import annotations

from email.utils import parsedate_to_datetime
from enum import Enum
from datetime import timezone
from typing import Optional


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
