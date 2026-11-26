"""Project telemetry and snapshot metadata into dashboard JSON payloads."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
import json
from math import ceil

from .contract import FIELDS, HISTORY_MAX_OFFSET, OUTCOMES, PIPELINE_STAGES, VALUE_SOURCES
from .data_source import PROVIDER_NAMES, DataSource, utc_stamp


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
    skips = Counter()
    stage_mix = defaultdict(Counter)
    latencies = []
    costs = defaultdict(float)
    reasoning = Counter()
    unknown_count = 0
    for row in rows:
        outcomes[row[FIELDS["outcome"]]] += 1
        source = row[FIELDS["tokenSource"]]
        if source != "unknown":
            tokens[source] += _total_tokens(row)
            if (count := row.get(FIELDS["reasoning"])) is not None:
                reasoning[source] += count
        else:
            unknown_count += 1
        for source, field in (("reported", "reportedCost"), ("estimated", "estimatedCost")):
            if (cost := row.get(FIELDS[field])) is not None:
                costs[source] += cost
        skips.update(json.loads(row.get(FIELDS["skipReasons"]) or "[]"))
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
        "reasoning_by_source": {source: reasoning.get(source) for source in VALUE_SOURCES},
        "unknown_token_requests": unknown_count,
        "cost_by_source": {source: costs.get(source) for source in VALUE_SOURCES},
        "latency": {"p50": _percentile(latencies, 0.50), "p95": _percentile(latencies, 0.95)},
        "error_counts": dict(errors),
        "skip_reason_counts": dict(skips),
        "stage_provider_mix": {stage: dict(counts) for stage, counts in stage_mix.items()},
        "sources": {"requests": "reported", "outcomes": "reported",
                    "success_rate": "reported" if dispatched else "unknown",
                    "unknown_token_requests": "reported",
                    "latency": "reported" if latencies else "unknown",
                    "error_counts": "reported", "skip_reason_counts": "reported", "stage_provider_mix": "reported"},
    }


def overview(source: DataSource):
    start = source.now.replace(hour=0, minute=0, second=0, microsecond=0)
    if hasattr(source, "window"):
        today, count = source.window(start)
        source.telemetry_state(count, capped=True)
    else:
        today = [row for row in source.requests if start <= _timestamp(row) <= source.now]
    incidents = sorted(
        (row for row in source.requests if row[FIELDS["error"]]), key=_timestamp, reverse=True,
    )
    providers = source.providers
    payload = {
        "today": summarize(today),
        "estimated_cost_usd": source.estimated_cost_usd,
        "active_cooldowns": sum(
            datetime.fromisoformat(provider["cooldown_until"]) > source.now
            for provider in providers if provider["cooldown_until"]
        ),
        "providers": [{key: provider[key] for key in ("slug", "name", "status")} for provider in providers],
        "incidents": incidents[:5],
        "fields": dict(FIELDS),
        "sources": {"active_cooldowns": "reported",
                    "estimated_cost_usd": "estimated" if source.estimated_cost_usd is not None else "unknown"},
    }
    if hasattr(source, "window"):
        payload["active_cooldowns"] = sum(len(provider["blocks"]) for provider in providers)
        if "quota_state" in source.states:
            payload["active_cooldowns"] = None
            payload["sources"]["active_cooldowns"] = "unknown"
        if source.states.get("telemetry") not in (None, "telemetry_empty", "telemetry_capped"):
            payload["today"]["sources"] = dict.fromkeys(payload["today"]["sources"], "unknown")
    return payload


def providers(source: DataSource):
    providers = source.providers
    if hasattr(source, "telemetry_state"):
        source.telemetry_state(len(source.requests))
    return {"providers": providers}


def usage(source: DataSource, range_name):
    count, width = USAGE_RANGES[range_name]
    start = source.now - count * width
    providers = ([{"slug": slug, "name": name} for slug, name in PROVIDER_NAMES.items()]
                 if hasattr(source, "window") else source.providers)
    buckets = [{
        "start": utc_stamp(start + i * width),
        "providers": {provider["slug"]: {
            "requests": dict.fromkeys(VALUE_SOURCES, 0),
            "tokens": {"reported": 0, "estimated": 0, "unknown": None},
        } for provider in providers},
        "sources": {"requests": "reported"},
    } for i in range(count)]
    if hasattr(source, "window"):
        requests, matching = source.window(start)
        source.telemetry_state(matching, capped=True)
        if source.states.get("telemetry") not in (None, "telemetry_empty", "telemetry_capped"):
            for bucket in buckets:
                bucket["sources"]["requests"] = "unknown"
    else:
        requests = source.requests
    for row in requests:
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
            "providers": [{key: provider[key] for key in ("slug", "name")} for provider in providers]}


def request_history(source: DataSource, limit, offset=0, **filters):
    matching_source = "reported"
    if hasattr(source, "window"):
        rows, count, stages = source.history(limit, offset, filters)
        options = {"provider": list(PROVIDER_NAMES), "stage": stages, "outcome": OUTCOMES}
        if source.states.get("telemetry") not in (None, "telemetry_empty"):
            matching_source = "unknown"
    else:
        options, rows, count = _mock_history(source, limit, offset, filters)
    next_offset = offset + limit
    return {"requests": rows, "matching": count, "limit": limit, "offset": offset,
            "next_offset": next_offset if next_offset < count and next_offset <= HISTORY_MAX_OFFSET else None,
            "options": options, "fields": dict(FIELDS),
            "sources": {"matching": matching_source, "limit": "static", "offset": "static",
                        "next_offset": "static" if next_offset < count else "unknown"}}


def _mock_history(source, limit, offset, filters):
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
    return options, matching[offset:offset + limit], len(matching)


def routing_policy(source: DataSource):
    return dict(source.routing_policy)


def pipeline(source: DataSource):
    return {"stages": PIPELINE_STAGES, "runs": source.runs}


def run_detail(source: DataSource, ref):
    if hasattr(source, "run_detail") and (run := source.run_detail(ref)) is not None:
        return {"stages": PIPELINE_STAGES, "run": run}
    return None
