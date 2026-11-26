"""Read run metadata and allowlisted saved results for unlocked runs."""

from collections import deque
from datetime import datetime, timezone
from hashlib import sha256
from heapq import nlargest
import json
import os
import re

from tools.llm_infra.routing_policy import PROVIDERS
from tools.llm_infra.telemetry import usage_counts
from tools.story_pipeline.llm import QUOTA_PATTERN

from .contract import PIPELINE_STAGES
from .data_source import utc_stamp
from .privacy import label, number


RUN_LIMIT = 50
_JSON_LIMIT = 4 * 1024 * 1024
_CALL_LOG_LIMIT = 8 * 1024 * 1024
_CALL_LINE_LIMIT = 10_000
_DETAIL_CALL_LIMIT = 250
_RESULT_LIMIT = 16 * 1024 * 1024
_LOCK_LABEL = "đợt chạy đã khóa (M9)"
_STATUSES = (
    "RUNNING", "COMPLETED", "FAILED", "PAUSED_QUOTA", "NEEDS_REVIEW", "NOT_RUN",
    "COMPLETED_WITH_FAILURES", "STOPPED_AFTER_BRIEF", "STOPPED_AFTER_PLAN", "STOPPED_AFTER_SCRIPT",
)
_STAGE_OUTPUTS = {"brief": "story_brief.json", "plan": "plan.json", "script": "script_v1.json",
                  "critic": "critic_v1.json"}
_RESULT_FILES = {"brief": "story_brief.html", "plan": "plan_review.html", "script": "script_v1.md",
                 "critic": "review.html", "revise": "script_final.md"}
_DETAIL_OUTPUTS = ("story_brief.html", "brief_check.md", "plan_review.html", "script_v1.md",
                   "script_final.md", "review.html", "report.md")
_CALL_STAGES = (*PIPELINE_STAGES, "brief_check", "patch", "source_check")
_CALL_ID = re.compile(r"(?:brief|brief_check|plan|script|critic|source_check|revise|patch):[a-zA-Z0-9_-]*:attempt[1-9][0-9]*")
_HINTS = {
    "PAUSED_QUOTA": "Khi hết thời gian chờ, chạy lại với cùng thư mục đầu ra để tiếp tục.",
    "NEEDS_REVIEW": "Kiểm tra các bước được đánh dấu trước khi tiếp tục.",
}


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _object(content):
    try:
        value = json.loads(content.decode("utf-8"))
        return value if isinstance(value, dict) else None
    except (UnicodeError, ValueError, RecursionError):
        return None


def _local(path, parent):
    try:
        return path.resolve() == parent.resolve() / path.name and not path.is_symlink()
    except (OSError, RuntimeError):
        return False


def _manifest(path):
    try:
        if _local(path, path.parent) and path.is_file():
            with path.open("rb") as handle:
                content = handle.read(_JSON_LIMIT + 1)
            if len(content) <= _JSON_LIMIT:
                return _object(content) or {}
    except OSError:
        pass
    return {}


def _timestamp(value):
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.utcoffset() is not None:
                return utc_stamp(parsed)
        except (ValueError, OverflowError):
            pass
    return None


def _status(value):
    return value if value in _STATUSES else "UNKNOWN"


def _call_detail(call, usage, tokens, seconds):
    errors = call.get("errors")
    valid = call.get("valid")
    validation = "unknown"
    if valid is True:
        validation = "validationPassed"
    elif valid is False:
        validation = "validationWarnings" if call.get("soft_errors_only") is True else "validationFailed"
    stage = call.get("stage")
    request_id = label(call.get("request_id"))
    return {
        "stage": stage if stage in _CALL_STAGES else "unknown", "attempt": number(call.get("attempt")),
        "request_id": request_id if request_id and _CALL_ID.fullmatch(request_id) else None,
        "provider": call["provider"] if call.get("provider") in PROVIDERS else None,
        "model": label(call.get("model")), "seconds": seconds, "validation": validation,
        "findings": len(errors) if isinstance(errors, list) else None, "tokens": tokens,
        **usage_counts({"usage_metadata": usage}),
    }


def _call_metadata(directory, attempts=None):
    path = directory / "calls.jsonl"
    stage_seconds = {}
    totals = {"calls": 0, "seconds": None, "tokens": None}
    provider, model = None, None
    brief_valid = False
    scope = "callLog"
    try:
        if not _local(path, directory) or not path.is_file():
            return {}, stage_seconds, provider, model, scope, brief_valid
        with path.open("rb") as handle:
            remaining = _CALL_LOG_LIMIT
            for _ in range(_CALL_LINE_LIMIT):
                line = handle.readline(remaining + 1)
                if not line:
                    break
                if len(line) > remaining:
                    scope = "partialCallLog"
                    break
                remaining -= len(line)
                call = _object(line)
                if call is None:
                    scope = "partialCallLog"
                    continue
                totals["calls"] += 1
                if call.get("provider") in PROVIDERS:
                    provider = call["provider"]
                    model = label(call.get("model"))
                usage = _mapping(call.get("usage"))
                tokens = number(usage.get("total_token_count"))
                if tokens is None:
                    tokens = number(usage.get("total_tokens"))
                if tokens is not None:
                    totals["tokens"] = (totals["tokens"] or 0) + tokens
                seconds = number(call.get("seconds"))
                stage = call.get("stage")
                if attempts is not None:
                    attempts.append(_call_detail(call, usage, tokens, seconds))
                if stage == "brief":
                    brief_valid = call.get("valid") is True
                if seconds is not None:
                    totals["seconds"] = (totals["seconds"] or 0) + seconds
                    if stage in PIPELINE_STAGES:
                        stage_seconds[stage] = stage_seconds.get(stage, 0) + seconds
            else:
                if handle.read(1):
                    scope = "partialCallLog"
    except OSError:
        if attempts is not None:
            attempts.clear()
        return {}, {}, None, None, scope, False
    if totals["seconds"] is not None:
        totals["seconds"] = round(totals["seconds"], 3)
    return totals, stage_seconds, provider, model, scope, brief_valid


def _completed_stages(directory):
    completed = [stage for stage, name in _STAGE_OUTPUTS.items() if _mtime(directory / name) is not None]
    # The script-only stop also renders script_final.md, before the critic has run.
    if (_mtime(directory / "script_v2.json") is not None
            or ("critic" in completed and _mtime(directory / "script_final.md") is not None)):
        completed.append("revise")
    return completed


def _error(manifest):
    value = manifest.get("error_code")
    if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", value):
        return label(value)
    error = manifest.get("error")
    if isinstance(error, str):
        for code in ("QUOTA_EXHAUSTED", "NO_ELIGIBLE_PROVIDER", "AUTH_FAILURE", "SERVER_FAILURE",
                     "REQUEST_TOO_LARGE", "RATE_LIMIT", "EDGE_BLOCKED"):
            if re.search(rf"\b{code}\b", error):
                return code
    return None


def _run(path, manifest, updated, *, attempts=None):
    log_totals, stage_seconds, provider, model, log_scope, brief_valid = _call_metadata(path.parent, attempts)
    status = _status(manifest.get("status"))
    error = manifest.get("error")
    if status == "FAILED" and isinstance(error, str) and QUOTA_PATTERN.search(error):
        status = "PAUSED_QUOTA"
    completed = _completed_stages(path.parent)
    # A scoped run can validate individual chapter briefs before writing the episode brief.
    # For minimal manifests, a validated brief call can stand in for the missing artifact.
    if status == "PAUSED_QUOTA" and "scope" not in manifest and brief_valid and "brief" not in completed:
        completed.insert(0, "brief")
    stages = {}
    for stage in completed:
        seconds = stage_seconds.get(stage)
        stages[stage] = {"status": "COMPLETED", "seconds": round(seconds, 3) if seconds is not None else None,
                         "source": "reported" if seconds is not None else "unknown"}
    current = None
    if status in ("RUNNING", "FAILED", "PAUSED_QUOTA"):
        current = next((stage for stage in PIPELINE_STAGES if stage not in completed), None)
    client = manifest.get("client")
    if provider is None and isinstance(client, str):
        slug, _, configured = client.partition(":")
        if slug in PROVIDERS:
            provider, model = slug, label(configured.split(",")[0])
        elif client.startswith("gemini-"):
            provider, model = "gemini", label(client.split(",")[0])
    usage_total = _mapping(_mapping(manifest.get("usage")).get("total"))
    manifest_totals = {"calls": number(manifest.get("model_calls")), "seconds": number(manifest.get("seconds")),
                       # The writer substitutes zeros for missing token counts.
                       "tokens": number(usage_total.get("total")) or None}
    values, total_scopes = {}, {}
    for key, fallback in manifest_totals.items():
        logged = log_totals.get(key)
        values[key] = logged if logged is not None else fallback
        if values[key] is not None:
            total_scopes[key] = log_scope if logged is not None else "latestInvocation"
    scopes = set(total_scopes.values())
    totals_scope = next(iter(scopes)) if len(scopes) == 1 else None
    reasons = manifest.get("review_reasons")
    if status == "NEEDS_REVIEW":
        values["review_reasons_count"] = len(reasons) if isinstance(reasons, list) else 0
    source_check_incomplete = manifest.get("source_check_failed") or manifest.get("source_check_quota_exhausted")
    run = {
        "id": label(path.parent.name, basename=True), "status": status, "completed": completed,
        "current": current, "stages": stages, "provider": provider, "model": model, "error_code": _error(manifest),
        "note": "Đối chiếu nguồn chưa xong một phần" if source_check_incomplete else None,
        "totals_scope": totals_scope, "total_scopes": total_scopes,
        "started_at": _timestamp(manifest.get("started_utc")), "updated_at": updated,
        "resume_at": _timestamp(manifest.get("resume_at")), "hint": _HINTS.get(status), **values,
        "sources": {key: "reported" if value is not None else "unknown" for key, value in values.items()},
    }
    if attempts is not None:
        chapters = _mapping(manifest.get("scope")).get("chapters")
        run.update({
            "chapters": [value for value in chapters[:500] if type(value) is int and number(value) is not None]
            if isinstance(chapters, list) else [],
            "elapsed_seconds": number(manifest.get("seconds")),
            "call_seconds": log_totals.get("seconds"),
            "call_log_scope": log_scope if log_totals else None,
            "attempts_truncated": log_totals.get("calls", 0) > len(attempts),
            "attempts": list(attempts),
            "outputs": [name for name in _DETAIL_OUTPUTS if _mtime(path.parent / name) is not None],
            "results": {name: stage for stage, name in _RESULT_FILES.items()
                        if stage in completed and _result_path(path.parent, stage) is not None},
        })
    return run


def _candidates(root, filename):
    try:
        for directory in root.iterdir():
            path = directory / filename
            if not _local(directory, root) or not directory.is_dir():
                continue
            mtime = _mtime(path)
            if mtime is None and filename == "season.json" and _locked(directory):
                mtime = directory.stat().st_mtime
            if mtime is not None:
                yield mtime, path
    except OSError:
        return


def _mtime(path):
    try:
        if _local(path, path.parent) and path.is_file():
            return path.stat().st_mtime
    except OSError:
        pass
    return None


def _locked(directory):
    markers = (path / "gate_lock.json" for path in (directory, directory.parent))
    return any(marker.is_symlink() or marker.exists() for marker in markers)


def _season(path, manifest, updated):
    totals = _mapping(manifest.get("totals"))
    values = {key: number(totals.get(key)) for key in ("calls", "tokens", "seconds")}
    if not values["tokens"]:
        values["tokens"] = None
    status = _status(manifest.get("status"))
    return {
        "id": label(path.parent.name, basename=True), "status": status, "hint": _HINTS.get(status),
        "kind": "season", "updated_at": updated, **values,
        "sources": {key: "reported" if value is not None else "unknown" for key, value in values.items()},
    }


def _detail_ref(manifest):
    return sha256(os.fsencode(manifest.absolute())).hexdigest()[:24]


def _run_candidates(runs_dir, seasons_dir):
    for mtime, path in nlargest(RUN_LIMIT, _candidates(seasons_dir, "season.json"), key=lambda item: item[0]):
        manifest = _manifest(path)
        if _locked(path.parent):
            yield mtime, path, {"label": _LOCK_LABEL, "status": _status(manifest.get("status"))}, None
            continue
        if not manifest:
            continue
        updated = utc_stamp(datetime.fromtimestamp(mtime, timezone.utc))
        yield mtime, path, _season(path, manifest, updated), None
        episode_rows = manifest.get("episodes")
        if isinstance(episode_rows, list):
            seen = set()
            for row in episode_rows:
                if name := label(_mapping(row).get("dir"), basename=True):
                    if name in seen:
                        continue
                    seen.add(name)
                    directory = path.parent / name
                    episode = directory / "run_manifest.json"
                    if (_local(directory, path.parent) and not _locked(directory)
                            and (episode_mtime := _mtime(episode)) is not None):
                        yield episode_mtime, episode, None, path.parent.name
    for mtime, path in _candidates(runs_dir, "run_manifest.json"):
        if not _locked(path.parent):
            yield mtime, path, None, None

def _recent_entries(runs_dir, seasons_dir):
    return nlargest(RUN_LIMIT, _run_candidates(runs_dir, seasons_dir), key=lambda item: item[0])


def read_runs(runs_dir, seasons_dir, *, detail_ref=None):
    runs = []
    seen = set()
    for mtime, path, ready, season_id in _recent_entries(runs_dir, seasons_dir):
        if path in seen:
            continue
        seen.add(path)
        if ready is not None:
            if detail_ref is None:
                runs.append(ready)
            continue
        if _locked(path.parent):
            continue
        name = label(path.parent.name, basename=True)
        ref = _detail_ref(path) if name else None
        if detail_ref is not None and ref != detail_ref:
            continue
        manifest = _manifest(path)
        if not manifest:
            continue
        updated = utc_stamp(datetime.fromtimestamp(mtime, timezone.utc))
        attempts = deque(maxlen=_DETAIL_CALL_LIMIT) if detail_ref is not None else None
        run = _run(path, manifest, updated, attempts=attempts)
        if ref is not None:
            run["detail_ref"] = ref
        if public_season := label(season_id, basename=True):
            run["season_id"] = public_season
        runs.append(run)
    return runs


def _result_path(directory, stage):
    path = directory / _RESULT_FILES[stage]
    try:
        if _local(path, directory) and path.is_file():
            stat = path.stat()
            if stat.st_nlink == 1 and 0 < stat.st_size <= _RESULT_LIMIT:
                return path
    except OSError:
        pass
    return None


def read_result(runs_dir, seasons_dir, ref, stage):
    if stage not in _RESULT_FILES:
        return None
    for _, manifest, ready, _ in _recent_entries(runs_dir, seasons_dir):
        if ready is not None or _detail_ref(manifest) != ref:
            continue
        directory = manifest.parent
        if _locked(directory) or not _manifest(manifest) or stage not in _completed_stages(directory):
            return None
        path = _result_path(directory, stage)
        if path is None:
            return None
        try:
            with path.open("rb") as handle:
                body = handle.read(_RESULT_LIMIT + 1)
        except OSError:
            return None
        if 0 < len(body) <= _RESULT_LIMIT and not _locked(directory):
            content_type = "text/html" if path.suffix == ".html" else "text/plain"
            return f"{content_type}; charset=utf-8", body
        return None
    return None
