"""Stdlib adapter for OpenRouter chat completions and public key limits."""
from dataclasses import dataclass
from http.client import HTTPException
import json
import math
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from tools.llm_infra.openrouter_free_models_v1 import is_free_model


BASE_URL = "https://openrouter.ai/api/v1"
_ERROR_KINDS = {
    400: "REQUEST_FAILURE",
    401: "AUTH_FAILURE",
    402: "PAYMENT_REQUIRED",
    403: "FORBIDDEN",
    404: "MODEL_UNAVAILABLE",
    408: "TRANSPORT_FAILURE",
    413: "REQUEST_TOO_LARGE",
    429: "RATE_LIMIT",
    500: "SERVER_FAILURE",
    502: "SERVER_FAILURE",
    503: "SERVER_FAILURE",
    504: "SERVER_FAILURE",
}


def redact_openrouter_data(value, secrets):
    """Redact secrets from JSON-like data, including field names."""
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {redact_openrouter_data(key, secrets): redact_openrouter_data(item, secrets)
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact_openrouter_data(item, secrets) for item in value]
    return value


class OpenRouterHTTPError(RuntimeError):
    def __init__(self, *, kind, status=None, headers=None, body=None):
        self.kind = kind
        self.status = status
        self.headers = headers or {}
        self.body = body or {}
        super().__init__(f"OpenRouter request failed: {kind}" +
                         (f" (HTTP {status})" if status is not None else ""))


@dataclass(frozen=True, slots=True)
class OpenRouterResponse:
    text: str
    usage: dict
    model: str
    headers: dict
    response_id: str | None = None
    status: int = 200
    cost: int | float | None = None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _urllib_http(url, headers, body, timeout):
    request = Request(url, data=body, headers=headers, method="GET" if body is None else "POST")
    try:
        response = build_opener(_NoRedirect()).open(request, timeout=timeout)
    except HTTPError as error:
        response = error
    with response:
        return response.code, dict(response.headers.items()), response.read()


def _json_object(body):
    try:
        value = json.loads(body)
    except (ValueError, RecursionError):
        return {}
    return value if isinstance(value, dict) else {}


def _response_error(status, data):
    if not 200 <= status < 300:
        return _ERROR_KINDS.get(status, "REQUEST_FAILURE")
    if "error" in data:
        error = data["error"]
        code = error.get("code") if isinstance(error, dict) else None
        if type(code) is int and 400 <= code < 600:
            return _ERROR_KINDS.get(code, "REQUEST_FAILURE")
        return "MALFORMED_RESPONSE"
    return None


def _is_number(value):
    return type(value) is int or (type(value) is float and math.isfinite(value))


def public_key_counts(data):
    """Keep only the documented numeric limits and boolean tier flag."""
    counts = {name: data[name] for name in ("limit", "limit_remaining", "usage_daily")
              if _is_number(data.get(name))}
    if type(data.get("is_free_tier")) is bool:
        counts["is_free_tier"] = data["is_free_tier"]
    daily = data.get("free_model_daily_requests")
    if isinstance(daily, dict):
        counts["free_model_daily_requests"] = {
            name: daily[name] for name in ("used", "limit", "remaining") if _is_number(daily.get(name))
        }
    return counts


class OpenRouterClient:
    def __init__(self, api_key, *, http=None, timeout=120, data_collection=None):
        if not api_key or not api_key.isascii() or not api_key.isprintable():
            raise OpenRouterHTTPError(kind="AUTH_FAILURE")
        if data_collection not in (None, "allow", "deny"):
            raise OpenRouterHTTPError(kind="REQUEST_FAILURE")
        self._api_key = api_key
        self._http = _urllib_http if http is None else http
        self._timeout = timeout
        self._data_collection = data_collection

    def _request(self, path, payload=None):
        headers = {"Authorization": f"Bearer {self._api_key}"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            status, headers, body = self._http(f"{BASE_URL}/{path}", headers, body, self._timeout)
        except (OSError, HTTPException):
            pass
        else:
            return status, {name.lower(): value for name, value in headers.items()}, _json_object(body)
        raise OpenRouterHTTPError(kind="TRANSPORT_FAILURE")

    def _raise_response_error(self, kind, status, headers, data):
        secrets = (self._api_key,)
        raise OpenRouterHTTPError(kind=kind, status=status, headers=redact_openrouter_data(headers, secrets),
                                  body=redact_openrouter_data(data, secrets))

    def generate(self, model, system_instruction, user_content, generation_config):
        if not is_free_model(model) or self._api_key in model:
            raise OpenRouterHTTPError(kind="MODEL_NOT_FREE")
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system_instruction},
                         {"role": "user", "content": user_content}],
            "usage": {"include": True},
        }
        if "temperature" in generation_config:
            payload["temperature"] = generation_config["temperature"]
        if "max_output_tokens" in generation_config:
            payload["max_tokens"] = generation_config["max_output_tokens"]
        if generation_config.get("response_mime_type") == "application/json":
            payload["response_format"] = {"type": "json_object"}
        if self._data_collection is not None:
            payload["provider"] = {"data_collection": self._data_collection}

        status, headers, data = self._request("chat/completions", payload)
        usage = data.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        cost = usage.get("cost")
        reported_model = data.get("model")
        if (
            (type(cost) in (int, float) and cost > 0)
            or (isinstance(reported_model, str) and not is_free_model(reported_model))
        ):
            self._raise_response_error("PAID_USAGE_DETECTED", status, headers, data)
        if kind := _response_error(status, data):
            self._raise_response_error(kind, status, headers, data)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None
        if not isinstance(content, str) or not isinstance(reported_model, str):
            self._raise_response_error("MALFORMED_RESPONSE", status, headers, data)
        response_id = data.get("id")
        content, usage, reported_model, headers, response_id = redact_openrouter_data(
            [content, usage, reported_model, headers, response_id if isinstance(response_id, str) else None],
            (self._api_key,),
        )
        return OpenRouterResponse(content, usage, reported_model, headers, response_id,
                                  status=status, cost=cost if _is_number(cost) else None)

    def key_info(self):
        status, headers, data = self._request("key")
        kind = _response_error(status, data)
        info = data.get("data")
        if kind or not isinstance(info, dict):
            self._raise_response_error(kind or "MALFORMED_RESPONSE", status, headers, data)
        return public_key_counts(info)
