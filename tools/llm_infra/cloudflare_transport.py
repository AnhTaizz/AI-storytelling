"""Stdlib adapter for Workers AI chat completions."""
from dataclasses import dataclass
from http.client import HTTPException
import json
from urllib.parse import quote

from tools.llm_infra.cloudflare_free_models_v1 import ACTIVE_NEURON_PRICES
from tools.llm_infra.openrouter_transport import (
    USER_AGENT, _json_object, _urllib_http, redact_openrouter_data as redact_cloudflare_data,
)


BASE_URL = "https://api.cloudflare.com/client/v4/accounts"
_ERROR_CODES = {
    3036: "DAILY_ALLOCATION_EXHAUSTED",
    3040: "SERVER_FAILURE",
    5035: "MODEL_REQUIRES_PAID",
    5007: "MODEL_UNAVAILABLE",
    3042: "MODEL_UNAVAILABLE",
    5028: "MODEL_UNAVAILABLE",
    3023: "ACCOUNT_BLOCKED",
    3006: "REQUEST_TOO_LARGE",
    3007: "TRANSPORT_FAILURE",
    3008: "TRANSPORT_FAILURE",
    3003: "REQUEST_FAILURE",
    10000: "AUTH_FAILURE",
}
_HTTP_ERRORS = {
    401: "AUTH_FAILURE",
    403: "FORBIDDEN",
    408: "TRANSPORT_FAILURE",
    413: "REQUEST_TOO_LARGE",
    429: "RATE_LIMIT",
}


class CloudflareHTTPError(RuntimeError):
    def __init__(self, *, kind, status=None, headers=None, body=None):
        self.kind = kind
        self.status = status
        self.headers = headers or {}
        self.body = body or {}
        super().__init__(f"Cloudflare request failed: {kind}" +
                         (f" (HTTP {status})" if status is not None else ""))


def _token_count(value):
    return value if type(value) is int and value >= 0 else None


@dataclass(frozen=True, slots=True)
class CloudflareResponse:
    text: str
    usage: dict
    model: str
    headers: dict
    response_id: str | None = None
    status: int = 200

    @property
    def prompt_tokens(self):
        return _token_count(self.usage.get("prompt_tokens"))

    @property
    def completion_tokens(self):
        return _token_count(self.usage.get("completion_tokens"))


def _response_error(status, data):
    native = data.get("errors")
    errors = [item for item in native if isinstance(item, dict)] if isinstance(native, list) else []
    if isinstance(data.get("error"), dict):
        errors.append(data["error"])
    for error in errors:
        code = error.get("code")
        if type(code) is int and code in _ERROR_CODES:
            return _ERROR_CODES[code]
    has_api_error = bool(errors) or data.get("success") is False
    if status == 403 and not has_api_error:
        return "EDGE_BLOCKED"
    if 500 <= status < 600:
        return "SERVER_FAILURE"
    if not 200 <= status < 300:
        return _HTTP_ERRORS.get(status, "REQUEST_FAILURE")
    if has_api_error:
        return "REQUEST_FAILURE"
    return None


def _content(data):
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return data.get("response")


class CloudflareClient:
    def __init__(self, account_id, api_token, *, http=None, timeout=120):
        if any(not credential or not credential.isascii() or not credential.isprintable()
               for credential in (account_id, api_token)):
            raise CloudflareHTTPError(kind="AUTH_FAILURE")
        account_path = quote(account_id, safe="")
        self._url = f"{BASE_URL}/{account_path}/ai/v1/chat/completions"
        self._api_token = api_token
        self._secrets = tuple(sorted({account_id, account_path, api_token}, key=len, reverse=True))
        self._http = _urllib_http if http is None else http
        self._timeout = timeout

    def _request(self, payload):
        headers = {"Authorization": f"Bearer {self._api_token}", "User-Agent": USER_AGENT,
                   "Content-Type": "application/json"}
        try:
            status, headers, body = self._http(self._url, headers, json.dumps(payload).encode(), self._timeout)
        except (OSError, HTTPException):
            pass
        else:
            return status, {name.lower(): value for name, value in headers.items()}, _json_object(body)
        raise CloudflareHTTPError(kind="TRANSPORT_FAILURE")

    def generate(self, model, system_instruction, user_content, generation_config):
        if model not in ACTIVE_NEURON_PRICES or any(secret in model for secret in self._secrets):
            raise CloudflareHTTPError(kind="MODEL_NOT_FREE")
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system_instruction},
                         {"role": "user", "content": user_content}],
        }
        # The compatible endpoint has no documented response_format support.
        if "temperature" in generation_config:
            payload["temperature"] = generation_config["temperature"]
        if "max_output_tokens" in generation_config:
            payload["max_tokens"] = generation_config["max_output_tokens"]
        status, headers, envelope = self._request(payload)
        kind = _response_error(status, envelope)
        data = envelope.get("result", envelope)
        text = _content(data) if isinstance(data, dict) else None
        if kind or not isinstance(text, str):
            raise CloudflareHTTPError(
                kind=kind or "MALFORMED_RESPONSE", status=status,
                headers=redact_cloudflare_data(headers, self._secrets),
                body=redact_cloudflare_data(envelope, self._secrets),
            )
        usage, reported_model, response_id = data.get("usage"), data.get("model"), data.get("id")
        text, usage, reported_model, headers, response_id = redact_cloudflare_data(
            [text, usage if isinstance(usage, dict) else {},
             reported_model if isinstance(reported_model, str) else model,
             headers, response_id if isinstance(response_id, str) else None],
            self._secrets,
        )
        return CloudflareResponse(text, usage, reported_model, headers, response_id, status)
