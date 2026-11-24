"""Project telemetry and snapshot metadata into dashboard JSON payloads."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from math import ceil

from .contract import FIELDS, OUTCOMES, PIPELINE_STAGES, VALUE_SOURCES
from .data_source import DataSource, utc_stamp


USAGE_RANGES = {"24h": (24, timedelta(hours=1)), "7d": (7, timedelta(days=1))}


def _timestamp(row):
    return datetime.fromisoformat(row[FIELDS["timestamp"]])


def _total_tokens(row):
    # Reasoning may be included in the provider's output count. Keep it separate.
    return sum(row[FIELDS[field]] or 0 for field in ("input", "output"))


def _percentile(sorted_values, fraction):
    return sorted_values[ceil(len(sorted_values) * fraction) - 1] if sorted_values else None


def summarize(rows):
    outcomes = dict.fromkeys(OUTCOMES, 0)
    tokens = dict.fromkeys(VALUE_SOURCES, 0)
    errors = Counter()
    stage_mix = defaultdict(Counter)
    latencies = []
    for row in rows:
        outcomes[row[FIELDS["outcome"]]] += 1
        source = row[FIELDS["tokenSource"]]
        if source != "unknown":
            tokens[source] += _total_tokens(row)
        if row[FIELDS["error"]]:
            errors[row[FIELDS["error"]]] += 1
        if row[FIELDS["latency"]] is not None:
            latencies.append(row[FIELDS["latency"]])
        if row[FIELDS["provider"]]:
            stage_mix[row[FIELDS["stage"]]][row[FIELDS["provider"]]] += 1
    latencies.sort()
    dispatched = outcomes["SUCCESS"] + outcomes["FAILED"]
    return {
        "requests": sum(outcomes.values()),
        "outcomes": outcomes,
        "success_rate": outcomes["SUCCESS"] / dispatched if dispatched else None,
        "tokens_by_source": {**tokens, "unknown": None},
        "latency": {"p50": _percentile(latencies, 0.50), "p95": _percentile(latencies, 0.95)},
        "error_counts": dict(errors),
        "stage_provider_mix": {stage: dict(counts) for stage, counts in stage_mix.items()},
    }


def overview(source: DataSource):
    start = source.now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = [row for row in source.requests if start <= _timestamp(row) <= source.now]
    incidents = sorted(
        (row for row in source.requests if row[FIELDS["error"]]), key=_timestamp, reverse=True,
    )
    return {
        "today": summarize(today),
        "estimated_cost_usd": source.estimated_cost_usd,
        "active_cooldowns": sum(
            datetime.fromisoformat(provider["cooldown_until"]) > source.now
            for provider in source.providers if provider["cooldown_until"]
        ),
        "providers": [{key: provider[key] for key in ("slug", "name", "status")} for provider in source.providers],
        "incidents": incidents[:5],
        "fields": dict(FIELDS),
    }


def providers(source: DataSource):
    return {"providers": source.providers}


def usage(source: DataSource, range_name):
    count, width = USAGE_RANGES[range_name]
    start = source.now - count * width
    buckets = [{
        "start": utc_stamp(start + i * width),
        "providers": {provider["slug"]: {
            "requests": dict.fromkeys(VALUE_SOURCES, 0),
            "tokens": {"reported": 0, "estimated": 0, "unknown": None},
        } for provider in source.providers},
    } for i in range(count)]
    for row in source.requests:
        timestamp = _timestamp(row)
        provider = row[FIELDS["provider"]]
        if not start <= timestamp <= source.now or provider not in buckets[0]["providers"]:
            continue
        index = min((timestamp - start) // width, count - 1)
        series = buckets[index]["providers"][provider]
        provenance = row[FIELDS["tokenSource"]]
        series["requests"][provenance] += 1
        if provenance != "unknown":
            series["tokens"][provenance] += _total_tokens(row)
    return {"range": range_name, "buckets": buckets,
            "providers": [{key: provider[key] for key in ("slug", "name")} for provider in source.providers]}


def request_history(source: DataSource, limit, **filters):
    options = {
        "provider": [provider["slug"] for provider in source.providers],
        "stage": sorted({row[FIELDS["stage"]] for row in source.requests}),
        "outcome": OUTCOMES,
    }
    matching = [
        row for row in source.requests
        if all(row[FIELDS[key]] == value for key, value in filters.items())
    ]
    matching.sort(key=_timestamp, reverse=True)
    return {"requests": matching[:limit], "matching": len(matching), "limit": limit,
            "options": options, "fields": dict(FIELDS)}


def routing_policy(source: DataSource):
    return dict(source.routing_policy)


def pipeline(source: DataSource):
    return {"stages": PIPELINE_STAGES, "runs": source.runs}
