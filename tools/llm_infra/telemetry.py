"""Best-effort SQLite telemetry with a metadata allowlist."""
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import re
import sqlite3
from threading import Lock


DEFAULT_TELEMETRY = Path(__file__).resolve().parents[2] / ".local" / "llm_telemetry.sqlite3"
SCHEMA_VERSION = 1
_LOG = logging.getLogger(__name__)
_LABEL = re.compile(r"[A-Za-z0-9@_.:/+-]{1,256}")
_TEXT = ("run_id", "stage", "request_id", "provider", "model_requested", "model_reported",
         "outcome", "error_code", "tokens_source", "quota_scope", "cost_source", "routing_policy_sha256")
_NUMBERS = ("input_tokens", "output_tokens", "reasoning_tokens", "latency_ms", "cost_reported", "cost_estimated")
_COUNTERS = frozenset({"x-ratelimit-remaining-requests", "x-ratelimit-remaining-tokens",
                       "x-ratelimit-limit-requests", "x-ratelimit-limit-tokens"})
_COLUMNS = ("timestamp_utc", *_TEXT, *_NUMBERS, "quota_remaining", "skip_reasons")


def _number(value):
    if type(value) is int:
        return value if 0 <= value < 2**63 else None
    return value if type(value) is float and math.isfinite(value) and value >= 0 else None


def _first_count(*values):
    return next((value for value in values if type(value) is int and _number(value) is not None), None)


def usage_counts(record):
    usage = record.get("usage_metadata") or {}
    details = usage.get("completion_tokens_details") or {}
    return {
        "input_tokens": _first_count(usage.get("prompt_tokens"), usage.get("prompt_token_count")),
        "output_tokens": _first_count(usage.get("completion_tokens"), usage.get("candidates_token_count")),
        "reasoning_tokens": _first_count(usage.get("reasoning_tokens"), usage.get("thoughts_token_count"),
                                         details.get("reasoning_tokens") if isinstance(details, dict) else None),
    }


def public_counters(headers):
    counters = {}
    for name in _COUNTERS:
        value = headers.get(name)
        if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 19:
            value = int(value)
        if _number(value) is not None:
            counters[name] = value
    return counters


class Telemetry:
    def __init__(self, path=DEFAULT_TELEMETRY, *, secrets=()):
        self.path = str(path)
        self._secrets = tuple(sorted(filter(None, set(secrets)), key=len, reverse=True))
        self._lock = Lock()
        self._memory = None

    def _redact(self, value):
        return None if any(secret in value for secret in self._secrets) else value

    def _label(self, value):
        return self._redact(value) if isinstance(value, str) and _LABEL.fullmatch(value) else None

    def _row(self, fields):
        values = {"timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds")}
        values.update({name: self._label(fields.get(name)) for name in _TEXT})
        values.update({name: _number(fields.get(name)) for name in _NUMBERS})
        counters = public_counters(fields.get("quota_remaining") or {})
        reasons = [self._label(reason) for reason in fields.get("skip_reasons") or ()]
        values["quota_remaining"] = json.dumps(counters, sort_keys=True)
        values["skip_reasons"] = json.dumps([reason for reason in reasons if reason])
        return tuple(value if value is None or self._redact(str(value)) is not None else None
                     for value in (values[column] for column in _COLUMNS))

    def _insert(self, connection, row):
        with connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                columns = ", ".join(f"{name} TEXT" for name in (*_TEXT, "quota_remaining", "skip_reasons"))
                numbers = ", ".join(f"{name} INTEGER" for name in _NUMBERS[:4])
                connection.execute(f"CREATE TABLE IF NOT EXISTS llm_requests (id INTEGER PRIMARY KEY, "
                                   f"timestamp_utc TEXT, {columns}, {numbers}, "
                                   "cost_reported REAL, cost_estimated REAL)")
                connection.execute("CREATE INDEX IF NOT EXISTS llm_requests_timestamp ON llm_requests(timestamp_utc)")
                connection.execute("CREATE INDEX IF NOT EXISTS llm_requests_model "
                                   "ON llm_requests(provider, model_requested)")
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            elif version != SCHEMA_VERSION:
                raise ValueError("Unsupported telemetry schema version")
            placeholders = ", ".join("?" for _ in _COLUMNS)
            connection.execute(f"INSERT INTO llm_requests ({', '.join(_COLUMNS)}) VALUES ({placeholders})", row)

    def write(self, **fields):
        row = self._row(fields)
        with self._lock:
            if self.path == ":memory:":
                if self._memory is None:
                    self._memory = sqlite3.connect(self.path, check_same_thread=False)
                self._insert(self._memory, row)
            else:
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(self.path, timeout=0.25)
                try:
                    self._insert(connection, row)
                finally:
                    connection.close()


def record_event(telemetry, **fields):
    if telemetry is not None:
        try:
            telemetry.write(**fields)
        except Exception:
            _LOG.warning("Could not write LLM telemetry")
