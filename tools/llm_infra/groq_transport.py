"""Stdlib adapter for Groq's OpenAI-compatible chat completions endpoint."""
from dataclasses import dataclass
from http.client import HTTPException
import json
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


BASE_URL = "https://api.groq.com/openai/v1"
# Groq's edge (Cloudflare) answers the default "Python-urllib" agent with 403 error 1010
# before the API sees the key, so every request names a generic client.
USER_AGENT = "llm-infra-client/1.0"


def redact_groq_data(value, secrets):
    """Redact strings in JSON-like data, including provider-controlled field names."""
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {redact_groq_data(key, secrets): redact_groq_data(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_groq_data(item, secrets) for item in value]
    return value


class GroqHTTPError(RuntimeError):
    def __init__(self, *, kind, status=None, headers=None, body=None):
        self.kind = kind
        self.status = status
        self.headers = headers or {}
        self.body = body or {}
        super().__init__(f"Groq request failed: {kind}" + (f" (HTTP {status})" if status is not None else ""))


@dataclass(frozen=True, slots=True)
class GroqResponse:
    text: str
    usage: dict
    model: str | None
    headers: dict
    response_id: str | None = None
    status: int = 200


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _urllib_http(url, headers, body, timeout):
    request = Request(url, data=body, headers=headers, method="POST")
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


def _error_kind(status, body):
    error = body.get("error")
    message = error.get("message") if isinstance(error, dict) else None
    if status == 413 or (status in (400, 429) and isinstance(message, str)
                         and "request too large" in message.casefold()):
        return "REQUEST_TOO_LARGE"
    if status == 429:
        return "RATE_LIMIT"
    if status == 403 and not error:
        # A 403 without the API's JSON error comes from the edge, not from the key.
        return "EDGE_BLOCKED"
    if status in (401, 403):
        return "AUTH_FAILURE"
    if status in (498, 500, 502, 503, 504):
        return "SERVER_FAILURE"
    code = error.get("code") if isinstance(error, dict) else None
    if status == 404 or code in ("model_not_found", "model_decommissioned"):
        return "MODEL_UNAVAILABLE"
    return "REQUEST_FAILURE"


class GroqClient:
    def __init__(self, api_key, *, http=None, timeout=120):
        if not api_key or not api_key.isascii() or not api_key.isprintable():
            raise GroqHTTPError(kind="AUTH_FAILURE")
        self._api_key = api_key
        self._http = _urllib_http if http is None else http
        self._timeout = timeout

    def generate(self, model, system_instruction, user_content, generation_config):
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system_instruction},
                         {"role": "user", "content": user_content}],
        }
        if "temperature" in generation_config:
            payload["temperature"] = generation_config["temperature"]
        if "max_output_tokens" in generation_config:
            payload["max_tokens"] = generation_config["max_output_tokens"]
        if generation_config.get("response_mime_type") == "application/json":
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload).encode("utf-8")
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json",
                   "User-Agent": USER_AGENT}
        try:
            status, headers, body = self._http(f"{BASE_URL}/chat/completions", headers, body, self._timeout)
        except (OSError, HTTPException):
            pass
        else:
            return self._decode_response(status, headers, body)
        raise GroqHTTPError(kind="TRANSPORT_FAILURE")

    def _decode_response(self, status, headers, body):
        raw = _json_object(body)
        headers = {name.lower(): value for name, value in headers.items()}
        raw_kind = _error_kind(status, raw) if not 200 <= status < 300 else None
        secrets = (self._api_key,)
        safe_headers = redact_groq_data(headers, secrets)
        data = redact_groq_data(raw, secrets)
        if raw_kind:
            raise GroqHTTPError(kind=raw_kind, status=status, headers=safe_headers, body=data)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None
        if not isinstance(content, str):
            raise GroqHTTPError(kind="MALFORMED_RESPONSE", status=status, headers=safe_headers, body=data)
        usage, model, response_id = data.get("usage"), data.get("model"), data.get("id")
        return GroqResponse(content, usage if isinstance(usage, dict) else {},
                            model if isinstance(model, str) else None, safe_headers,
                            response_id if isinstance(response_id, str) else None, status=status)
