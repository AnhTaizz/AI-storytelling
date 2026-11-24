"""Validate metadata labels and scrub every outgoing JSON payload."""

import math
import re
from urllib.parse import unquote

from tools.llm_infra.cloudflare_config import CREDENTIAL_PATTERN, cloudflare_secrets
from tools.llm_infra.groq_config import GROQ_KEY_PATTERN
from tools.llm_infra.openrouter_config import OPENROUTER_KEY_PATTERN
from tools.story_extraction.gemini_key_pool_v1 import _KEY_PATTERN


_PRIVATE = re.compile(
    r"AIza|gsk_|sk-or-|Bearer|Authorization|(?<![a-f\d])[a-f\d]{32}(?![a-f\d])"
    r"|[a-z]:[\\/]|\\|/Users/|(?:^|[\s:=])/(?!/)|^//", re.I,
)
_LABEL = re.compile(r"[A-Za-z0-9@_.:+/-]{1,256}")
_BASENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def configured_secrets(settings):
    patterns = (_KEY_PATTERN, GROQ_KEY_PATTERN, OPENROUTER_KEY_PATTERN, CREDENTIAL_PATTERN)
    return frozenset(cloudflare_secrets(settings)) | frozenset(
        value.strip() for key, value in settings.items()
        if any(pattern.fullmatch(key) for pattern in patterns) and value.strip()
    )


def private(value, secrets=()):
    # Static documentation URLs are supplied by code. Data labels reject URLs.
    decoded = unquote(value)
    return (_PRIVATE.search(decoded.removeprefix("https://")) is not None
            or any(secret in value or secret in decoded for secret in secrets))


def label(value, *, basename=False):
    pattern = _BASENAME if basename else _LABEL
    if (isinstance(value, str) and pattern.fullmatch(value) and "://" not in value
            and ".." not in value and not private(value)):
        return value
    return None


def number(value):
    if type(value) is int and 0 <= value < 2**63:
        return value
    if type(value) is float and math.isfinite(value) and 0 <= value < 2**63:
        return value
    return None


def scrub(payload, secrets=()):
    if isinstance(payload, dict):
        return {key: scrub(value, secrets) for key, value in payload.items() if not private(key, secrets)}
    if isinstance(payload, (list, tuple)):
        return [scrub(item, secrets) for item in payload]
    if isinstance(payload, str) and private(payload, secrets):
        return None
    return payload
