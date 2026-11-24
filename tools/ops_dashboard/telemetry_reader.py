"""Read bounded windows of Phase 5 request metadata."""

from contextlib import contextmanager
from datetime import datetime
import json
import re

from tools.llm_infra.routing_policy import PROVIDERS
from tools.llm_infra.telemetry import SCHEMA_VERSION, public_counters

from .contract import FIELDS, OUTCOMES, TELEMETRY_COLUMNS, VALUE_SOURCES
from .data_source import utc_stamp
from .privacy import label, number, private
from .sqlite_reader import SourceUnavailable, read_database


AGGREGATE_LIMIT = 10_000
_NUMBERS = ("id", "input", "output", "reasoning", "latency", "reportedCost", "estimatedCost")
_TEXT = ("stage", "request", "model", "responseModel", "error")


def json_value(value, kind):
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, RecursionError):
        return kind()
    return parsed if isinstance(parsed, kind) else kind()


def _row(raw, secrets):
    value = {name: raw[column] for name, column in FIELDS.items()}
    try:
        timestamp = datetime.fromisoformat(value["timestamp"])
        if timestamp.utcoffset() is None:
            return None
        stamp = utc_stamp(timestamp)
    except (TypeError, ValueError, OverflowError):
        return None
    if value["outcome"] not in OUTCOMES:
        return None
    clean = {key: number(value[key]) for key in _NUMBERS}
    clean.update({key: label(value[key]) for key in _TEXT})
    clean.update(timestamp=stamp, outcome=value["outcome"],
                 run=label(value["run"], basename=True),
                 stage=clean["stage"] or "unknown")
    clean["provider"] = value["provider"] if value["provider"] in PROVIDERS else None
    clean["quotaScope"] = value["quotaScope"] if value["quotaScope"] in ("project", "org", "account") else None
    digest = value["policyHash"]
    clean["policyHash"] = digest if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) else None
    counters = public_counters(json_value(value["quotaRemaining"], dict))
    clean["quotaRemaining"] = json.dumps(counters, sort_keys=True)
    reasons = json_value(value["skipReasons"], list)
    clean["skipReasons"] = json.dumps([reason for reason in reasons if label(reason) and not private(reason, secrets)])
    clean["tokenSource"] = value["tokenSource"] if value["tokenSource"] in VALUE_SOURCES else "unknown"
    clean["costSource"] = value["costSource"] if value["costSource"] in VALUE_SOURCES else "unknown"
    for key in ("reportedCost", "estimatedCost"):
        if not key.startswith(clean["costSource"]):
            clean[key] = None
    if clean["tokenSource"] == "unknown":
        clean.update(input=None, output=None, reasoning=None)
    clean["sources"] = {
        "id": "reported", "latency_ms": "reported" if clean["latency"] is not None else "unknown",
        "quota_remaining": "reported" if counters else "unknown",
    }
    return {FIELDS.get(key, key): item for key, item in clean.items()}


_WINDOW = f"{FIELDS['timestamp']} BETWEEN ? AND ?"
_ORDER = f"{FIELDS['timestamp']} DESC, {FIELDS['id']} DESC"


@contextmanager
def _telemetry_database(path):
    with read_database(path) as db:
        db.execute("BEGIN")
        if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise SourceUnavailable("schema_mismatch")
        yield db


def _select(db, start, end, limit, offset, filters, secrets):
    where = _WINDOW
    args = [utc_stamp(start), utc_stamp(end)]
    for key, value in (filters or {}).items():
        if key in ("provider", "stage", "outcome"):
            where += f" AND {FIELDS[key]} = ?"
            args.append(value)
    matching = db.execute(f"SELECT count(*) FROM llm_requests WHERE {where}", args).fetchone()[0]
    raw = db.execute(
        f"SELECT {', '.join(TELEMETRY_COLUMNS)} FROM llm_requests WHERE {where} "
        f"ORDER BY {_ORDER} LIMIT ? OFFSET ?", (*args, limit, offset),
    )
    return [row for item in raw if (row := _row(item, secrets)) is not None], matching


def read_requests(path, start, end, *, limit, offset=0, filters=None, secrets=()):
    with _telemetry_database(path) as db:
        return _select(db, start, end, limit, offset, filters, secrets)


def read_history(path, start, end, *, limit, offset, filters, secrets):
    with _telemetry_database(path) as db:
        stage = FIELDS["stage"]
        option_rows = db.execute(
            f"SELECT DISTINCT {stage} FROM (SELECT {stage} FROM llm_requests WHERE {_WINDOW} "
            f"ORDER BY {_ORDER} LIMIT ?)", (utc_stamp(start), utc_stamp(end), AGGREGATE_LIMIT),
        )
        options = sorted({label(raw) or "unknown" for (raw,) in option_rows})
        rows, matching = _select(db, start, end, limit, offset, filters, secrets)
        return rows, matching, options
