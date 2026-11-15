"""LLM access for the story pipeline: provider clients plus a validate-and-repair JSON loop.

Each stage asks the model for one JSON object. The response is parsed, checked against
the stage's JSON Schema and then against stage-specific semantic rules. If anything
fails, the exact validation errors are sent back and the model is asked to return a
corrected object, up to `max_repairs` times. Structural errors are machine errors,
so feeding them back is the normal fix rather than a quality retry.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

from jsonschema import Draft202012Validator


class LLMClient(Protocol):
    """Anything that turns (system, user) into raw model text."""

    name: str

    def complete(self, *, system: str, user: str, request_id: str) -> Dict[str, Any]:
        """Return {"raw_content": str, ...optional metadata}."""


class StageFailed(RuntimeError):
    def __init__(self, stage: str, errors: List[str], attempts: int) -> None:
        self.stage = stage
        self.errors = errors
        self.attempts = attempts
        preview = "; ".join(errors[:5])
        super().__init__(f"stage {stage} failed after {attempts} attempt(s): {preview}")


# --------------------------------------------------------------------------- clients


# Transport failures after which the next model in the chain is tried. Overload (503) and
# per-model quota (429) are model-specific; a request the provider rejects is not.
FALLBACK_CODES = frozenset({"SERVER_FAILURE", "RATE_LIMIT", "TIMEOUT", "NETWORK_FAILURE", "POOL_EXHAUSTED"})


_NETWORK_MODULES = ("httpx", "httpcore", "h11", "h2", "ssl", "socket", "urllib3", "aiohttp")


class TransientProviderError(RuntimeError):
    """A dropped connection or client-side timeout, re-raised with a 503 so the existing M4
    transport classifies it as a retryable server failure instead of an unknown one."""

    code = 503

    def __init__(self, original: BaseException) -> None:
        super().__init__(f"transient network failure: {type(original).__module__}.{type(original).__name__}")


def _describe(error: BaseException) -> Dict[str, Any]:
    from tools.story_extraction.gemini_errors_v1 import status_code

    return {"type": f"{type(error).__module__}.{type(error).__name__}", "status": status_code(error)}


class _ObservedClient:
    """Wraps one SDK client: records every failure's type and status (never its message,
    which may echo request data) and turns network-level failures into retryable ones."""

    def __init__(self, inner: Any, failures: List[Dict[str, Any]]) -> None:
        self._inner = inner
        self._failures = failures

    def generate(self, **kwargs: Any) -> Any:
        try:
            return self._inner.generate(**kwargs)
        except Exception as error:  # noqa: BLE001 - re-raised below
            self._failures.append({"model": kwargs.get("model"), **_describe(error)})
            module = type(error).__module__.split(".")[0]
            if module in _NETWORK_MODULES or isinstance(error, (TimeoutError, ConnectionError)):
                raise TransientProviderError(error) from error
            raise


class GeminiLLMClient:
    """Wraps the existing M4 Gemini transport and key pool (reads `.env` and the environment).

    `model` may be a comma-separated chain, e.g. "gemini-3.6-flash,gemini-3.5-flash": each
    call uses the first model and moves to the next only after the transport has exhausted
    its retries with an overload, quota or network failure. Every record says which model
    served it and which ones failed first.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        *,
        dotenv_path: Path | str = Path(".env"),
        temperature: float = 0.4,
        max_transport_retries: int = 3,
        base_backoff_seconds: float = 5.0,
        client_factory: Optional[Callable[[str], Any]] = None,
        environ: Optional[Dict[str, str]] = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        from tools.story_extraction.gemini_key_pool_v1 import (
            GeminiConfigError,
            GeminiKeyPool,
            load_runtime_config,
        )
        from tools.story_extraction.gemini_transport_v1 import (
            GeminiTransport,
            official_client_factory,
        )

        from tools.story_extraction.gemini_transport_v1 import GeminiTransportError

        config = load_runtime_config(dotenv_path, environ)
        self.models = [m.strip() for m in (model or config.model or "").split(",") if m.strip()]
        if not self.models:
            raise GeminiConfigError(
                "No Gemini model: pass --model or set GEMINI_MODEL in .env")
        self.model = self.models[0]
        self.temperature = temperature
        self.name = "gemini:" + ",".join(self.models)
        self._transport_error = GeminiTransportError
        # A 429 cools the whole credential, not just the model, so a fallback model may first
        # wait out that cooldown; pool and transport share one clock for that reason.
        pool = GeminiKeyPool(config.credentials, clock=clock)
        factory = client_factory or official_client_factory
        self.attempt_failures: List[Dict[str, Any]] = []
        self._transport = GeminiTransport(
            pool,
            lambda api_key: _ObservedClient(factory(api_key), self.attempt_failures),
            max_transport_retries=max_transport_retries,
            base_backoff_seconds=base_backoff_seconds,
            sleep=sleep,
            clock=clock,
        )

    def complete(self, *, system: str, user: str, request_id: str) -> Dict[str, Any]:
        failed: List[Dict[str, Any]] = []
        self.attempt_failures.clear()
        for index, model in enumerate(self.models):
            try:
                record = self._transport.generate(
                    system_instruction=system,
                    user_content=user,
                    model=model,
                    generation_config={"temperature": self.temperature},
                    request_id=request_id,
                )
            except self._transport_error as error:
                # After a retry the model was already failing transiently, so whatever its last
                # error was (live run 4: three 503s, then an unclassified failure), move on.
                # A request refused on its first attempt is not sent to another model.
                retried = error.attempts > 1
                if (error.code not in FALLBACK_CODES and not retried) or index == len(self.models) - 1:
                    seen = "; ".join(f"{f['model']}: {f['type']} status={f['status']}" for f in self.attempt_failures)
                    raise RuntimeError(f"{error} [attempt errors: {seen or 'none recorded'}]") from error
                failed.append({"model": model, "code": error.code, "attempts": error.attempts})
                continue
            record["fallback_from"] = failed
            record["attempt_failures"] = list(self.attempt_failures)
            return record
        raise AssertionError("unreachable: the loop returns or raises")


class ScriptedLLMClient:
    """Offline client for tests and dry runs: `responder(stage, system, user)` returns text."""

    def __init__(self, responder: Callable[[str, str, str], str], name: str = "scripted") -> None:
        self._responder = responder
        self.name = name
        self.calls: List[Dict[str, str]] = []

    def complete(self, *, system: str, user: str, request_id: str) -> Dict[str, Any]:
        stage = request_id.split(":", 1)[0]
        self.calls.append({"request_id": request_id, "stage": stage})
        return {"raw_content": self._responder(stage, system, user), "request_id": request_id}


# --------------------------------------------------------------------------- JSON loop

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def parse_json_object(raw: str) -> Any:
    """Parse a JSON object, tolerating a single surrounding Markdown code fence."""
    text = raw.strip()
    match = _FENCE.match(text)
    if match:
        text = match.group(1)
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
    return json.loads(text)


def schema_errors(schema: Dict[str, Any], obj: Any, limit: int = 25) -> List[str]:
    validator = Draft202012Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(obj), key=lambda e: list(e.absolute_path)):
        path = "/".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append(f"schema: at {path}: {error.message}")
        if len(errors) >= limit:
            break
    return errors


REPAIR_TEMPLATE = """{original}

=== YOUR PREVIOUS RESPONSE ===
{previous}

=== VALIDATION ERRORS IN YOUR PREVIOUS RESPONSE ===
{errors}

Return the complete corrected JSON object only. Fix every listed error. Keep everything
that was already correct. Do not add commentary, Markdown or code fences."""


@dataclass
class CallLog:
    """Collects every model call of a run so it can be written to disk."""

    entries: List[Dict[str, Any]] = field(default_factory=list)

    def add(self, entry: Dict[str, Any]) -> None:
        self.entries.append(entry)


def run_json_stage(
    client: LLMClient,
    *,
    stage: str,
    system: str,
    user: str,
    schema: Dict[str, Any],
    semantic_check: Optional[Callable[[Any], List[str]]] = None,
    soft_check: Optional[Callable[[Any], List[str]]] = None,
    max_repairs: int = 2,
    log: Optional[CallLog] = None,
    request_suffix: str = "",
) -> Any:
    """Call the model until it returns a schema-valid, semantically valid object.

    `semantic_check` errors are hard: the stage fails if they survive every repair.
    `soft_check` errors (for example a missed word count) also trigger repairs, but
    if only soft errors remain after the last attempt the object is returned anyway;
    the caller re-checks and reports them. A repair can also make things worse (live run 8:
    splitting facts for the soft check introduced a hard error), so when the last attempt
    has hard errors, the latest attempt that had only soft errors is returned instead.
    """
    prompt = user
    errors: List[str] = []
    best_soft: Any = None
    last_attempt = max_repairs + 1
    for attempt in range(1, last_attempt + 1):
        request_id = f"{stage}:{request_suffix}:attempt{attempt}"
        started = time.time()
        record = client.complete(system=system, user=prompt, request_id=request_id)
        raw = str(record.get("raw_content", ""))
        errors = []
        obj: Any = None
        try:
            obj = parse_json_object(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            errors = [f"json: response is not a valid JSON object ({exc})"]
        if not errors:
            errors = schema_errors(schema, obj)
        if not errors and semantic_check is not None:
            errors = semantic_check(obj)
        soft_only = False
        if not errors and soft_check is not None:
            errors = soft_check(obj)
            soft_only = bool(errors)
        if log is not None:
            log.add({
                "stage": stage,
                "request_id": request_id,
                "attempt": attempt,
                "client": getattr(client, "name", "unknown"),
                "model": record.get("model_requested"),
                "fallback_from": record.get("fallback_from") or [],
                "attempt_failures": record.get("attempt_failures") or [],
                "seconds": round(time.time() - started, 3),
                "usage": record.get("usage_metadata"),
                "valid": not errors,
                "soft_errors_only": soft_only,
                "errors": errors,
                "raw_content": raw,
            })
        if soft_only:
            best_soft = obj
        if not errors:
            return obj
        if attempt == last_attempt and best_soft is not None:
            return best_soft
        prompt = REPAIR_TEMPLATE.format(
            original=user,
            previous=raw[:60000],
            errors="\n".join(f"- {e}" for e in errors),
        )
    raise StageFailed(stage, errors, last_attempt)
