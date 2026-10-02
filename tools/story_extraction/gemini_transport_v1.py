"""Isolated Gemini structured-response transport with no local fallback."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Optional

try:
    from tools.story_extraction.gemini_key_pool_v1 import (
        GeminiConfigError,
        GeminiKeyPool,
        GeminiPoolExhausted,
        load_runtime_config,
    )
except ModuleNotFoundError:  # Supports direct execution from this directory.
    from gemini_key_pool_v1 import (  # type: ignore
        GeminiConfigError,
        GeminiKeyPool,
        GeminiPoolExhausted,
        load_runtime_config,
    )


TRANSPORT_VERSION = "GEMINI_TRANSPORT_V1"


class GeminiTransportError(RuntimeError):
    def __init__(self, code: str, attempts: int) -> None:
        self.code = code
        self.attempts = attempts
        super().__init__(f"Gemini transport failed safely: {code}; attempts={attempts}")


class _OfficialGeminiClient:
    def __init__(self, api_key: str) -> None:
        from google import genai
        from google.genai import types

        http_options = types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1)
        )
        self._client = genai.Client(api_key=api_key, http_options=http_options)
        self._types = types

    def generate(
        self,
        *,
        model: str,
        system_instruction: str,
        user_content: str,
        generation_config: Mapping[str, Any],
    ) -> Any:
        config = dict(generation_config)
        config["system_instruction"] = system_instruction
        config["response_mime_type"] = "application/json"
        return self._client.models.generate_content(
            model=model,
            contents=user_content,
            config=self._types.GenerateContentConfig(**config),
        )


def official_client_factory(api_key: str) -> _OfficialGeminiClient:
    """Lazy SDK construction: importing this module performs no API activity."""
    return _OfficialGeminiClient(api_key)


def _status_code(error: BaseException) -> Optional[int]:
    candidates = [
        getattr(error, "status_code", None),
        getattr(error, "code", None),
        getattr(getattr(error, "response", None), "status_code", None),
    ]
    for candidate in candidates:
        if isinstance(candidate, int):
            return candidate
        if isinstance(candidate, str) and candidate.isdigit():
            return int(candidate)
    return None


def _classify_error(error: BaseException) -> str:
    status = _status_code(error)
    if status in (401, 403):
        return "AUTH_FAILURE"
    if status == 400:
        # The SDK/provider commonly reports an invalid key as HTTP 400. Inspect
        # only to classify in memory; the provider text is never propagated.
        structured = getattr(error, "response_json", None)
        diagnostic = f"{getattr(error, 'status', '')} {structured!r} {error}"
        auth_markers = ("API_KEY_INVALID", "API KEY NOT VALID", "UNAUTHENTICATED")
        if any(marker in diagnostic.upper() for marker in auth_markers):
            return "AUTH_FAILURE"
    if status == 429:
        return "RATE_LIMIT"
    if status is not None and 500 <= status <= 599:
        return "SERVER_FAILURE"
    if isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return "TRANSPORT_FAILURE"
    return "PROVIDER_FAILURE"


def _retry_after_seconds(error: BaseException, now: float) -> Optional[float]:
    direct = getattr(error, "retry_after", None)
    if isinstance(direct, (int, float)):
        return max(0.0, float(direct))
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        value = headers.get("Retry-After") or headers.get("retry-after")
        if value is not None:
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
    return None


def _utc_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_usage(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return {}
    allowed = (
        "prompt_token_count",
        "candidates_token_count",
        "total_token_count",
        "cached_content_token_count",
        "thoughts_token_count",
    )
    return {name: getattr(usage, name) for name in allowed if getattr(usage, name, None) is not None}


def _safe_provider_metadata(response: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for public_name, attribute in (("response_id", "response_id"), ("model_version", "model_version")):
        value = getattr(response, attribute, None)
        if isinstance(value, (str, int, float, bool)):
            metadata[public_name] = value
    finish_reasons: list[str] = []
    for candidate in getattr(response, "candidates", None) or []:
        reason = getattr(candidate, "finish_reason", None)
        if reason is not None:
            finish_reasons.append(getattr(reason, "name", str(reason)))
    if finish_reasons:
        metadata["finish_reasons"] = finish_reasons
    return metadata


def _redact_tree(value: Any, redact: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {str(key): _redact_tree(item, redact) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_tree(item, redact) for item in value]
    return value


class GeminiTransport:
    """One semantic request with bounded retries for transport failures only."""

    def __init__(
        self,
        pool: GeminiKeyPool,
        client_factory: Callable[[str], Any] = official_client_factory,
        *,
        max_transport_retries: int = 2,
        base_backoff_seconds: float = 1.0,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_transport_retries < 0:
            raise GeminiConfigError("max_transport_retries must be non-negative")
        self._pool = pool
        self._client_factory = client_factory
        self._max_transport_retries = max_transport_retries
        self._base_backoff_seconds = base_backoff_seconds
        self._clock = clock
        self._sleep = sleep

    def generate(
        self,
        system_instruction: str,
        user_content: str,
        model: str,
        generation_config: Mapping[str, Any],
        request_id: str,
    ) -> dict[str, Any]:
        if not model.strip():
            raise GeminiConfigError("Gemini model is not configured")
        start = self._clock()
        attempts: list[dict[str, Any]] = []
        last_code = "POOL_EXHAUSTED"

        for attempt_number in range(1, self._max_transport_retries + 2):
            try:
                lease = self._pool.acquire(self._clock())
            except GeminiPoolExhausted:
                wait = self._pool.seconds_until_available(self._clock())
                if wait is not None and wait > 0 and attempt_number <= self._max_transport_retries:
                    self._sleep(wait)
                    lease = self._pool.acquire(self._clock())
                else:
                    raise GeminiTransportError(last_code, len(attempts)) from None

            attempt_public = {
                "attempt": attempt_number,
                "slot_id": lease.slot_id,
                "project_label": lease.project_label,
            }
            try:
                client = self._client_factory(lease.api_key)
                response = client.generate(
                    model=model,
                    system_instruction=system_instruction,
                    user_content=user_content,
                    generation_config=dict(generation_config),
                )
                end = self._clock()
                attempts.append({**attempt_public, "outcome": "SUCCESS"})
                raw_content = getattr(response, "text", None)
                if raw_content is None:
                    parsed = getattr(response, "parsed", None)
                    raw_content = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
                record = {
                    "request_id": request_id,
                    "provider": "Google Gemini API",
                    "transport": TRANSPORT_VERSION,
                    "model_requested": model,
                    "model_reported_if_available": getattr(response, "model_version", None),
                    "slot_id": lease.slot_id,
                    "project_label": lease.project_label,
                    "start_time": _utc_iso(start),
                    "end_time": _utc_iso(end),
                    "latency_seconds": max(0.0, end - start),
                    "usage_metadata": _safe_usage(response),
                    "provider_response_metadata": _safe_provider_metadata(response),
                    "raw_content": str(raw_content),
                    "transport_attempts": attempts,
                }
                return _redact_tree(record, self._pool.redact)
            except Exception as error:
                code = _classify_error(error)
                last_code = code
                attempts.append({**attempt_public, "outcome": code})
                if code == "AUTH_FAILURE":
                    self._pool.disable_slot(lease.slot_id)
                elif code == "RATE_LIMIT":
                    delay = _retry_after_seconds(error, self._clock())
                    if delay is None:
                        delay = self._base_backoff_seconds * (2 ** (attempt_number - 1))
                    self._pool.cool_project_group(lease.slot_id, delay, self._clock())
                    if not self._pool.has_available(self._clock()) and attempt_number <= self._max_transport_retries:
                        self._sleep(delay)
                elif code in ("SERVER_FAILURE", "TRANSPORT_FAILURE"):
                    if attempt_number <= self._max_transport_retries:
                        self._sleep(self._base_backoff_seconds * (2 ** (attempt_number - 1)))
                else:
                    raise GeminiTransportError(code, attempt_number) from None

                if attempt_number > self._max_transport_retries:
                    raise GeminiTransportError(code, attempt_number) from None

        raise GeminiTransportError(last_code, len(attempts))


def check_config(dotenv_path: Path | str = Path(".env")) -> dict[str, object]:
    """Inspect local configuration without constructing a client or making a call."""
    return load_runtime_config(dotenv_path=dotenv_path).public_summary()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Gemini story-extraction transport")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    if not args.check_config:
        parser.error("Only --check-config is available in M4-04A")
    summary = check_config(args.env_file)
    print(f"Gemini credential slots configured: {summary['credential_slots']}")
    print(f"Project groups configured: {summary['project_groups']}")
    print(f"Model configured: {'yes' if summary['model_configured'] else 'no'}")
    if summary["credential_slots"] == 0:
        print("Status: WAITING_FOR_USER_CREDENTIALS")
    else:
        print("Status: CONFIG_PRESENT_NOT_USED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
