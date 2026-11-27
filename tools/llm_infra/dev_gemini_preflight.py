"""Check a one-shot Gemini DEV request lock and local declarations offline."""

import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time

from tools.llm_infra.gemini_config import inspect_settings, merged_settings, state_path
from tools.llm_infra.quota_state import QuotaStateStore
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError, _KEY_PATTERN


def check_requests(path, expected_hash, model, dispatch_budget, output_cap):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected_hash:
        raise ValueError("Request lock hash mismatch")
    lock = json.loads(raw)
    if (
        lock["model"] != model or type(lock["max_output_tokens"]) is not int
        or lock["max_output_tokens"] != output_cap or output_cap < 1
        or type(lock["max_dispatches"]) is not int or not isinstance(lock["cases"], list)
        or not 1 <= len(lock["cases"]) <= lock["max_dispatches"] <= dispatch_budget
        or any(type(lock[name]) is not int or lock[name] != 0 for name in ("retry", "repair", "fallback"))
    ):
        raise ValueError("Request lock disagrees with the approved one-shot budget")

    cases = set()
    for row in lock["cases"]:
        case = row["id"]
        filename = f"requests/{case}.json"
        if not re.fullmatch(r"[A-Za-z0-9_-]+", case) or case in cases or row["request"] != filename:
            raise ValueError("Invalid request case or path")
        cases.add(case)
        request_path = path.parent / filename
        if request_path.resolve().parent != path.parent.resolve() / "requests":
            raise ValueError("Request resolves outside the source-only request directory")
        payload = request_path.read_bytes()
        if len(payload) != row["request_bytes"] or sha256(payload).hexdigest() != row["request_sha256"]:
            raise ValueError("Request payload hash or size mismatch")
        request = json.loads(payload)
        generation = request["generationConfig"]
        if (set(request) != {"systemInstruction", "contents", "generationConfig"}
                or type(generation.get("candidateCount")) is not int or generation["candidateCount"] != 1
                or type(generation.get("maxOutputTokens")) is not int or generation["maxOutputTokens"] != output_cap):
            raise ValueError("Unexpected request fields or generation budget")
    return len(cases)


def read_attestation(path, today):
    entry = json.loads(path.read_bytes())
    if (
        set(entry) != {"scope", "source", "confirmed_on", "pool_revision", "credential_access", "free_tier",
                       "operator_eligibility"}
        or entry["scope"] != "ai-storytelling:gemini-dev"
        or entry["source"] not in ("owner_project_chat", "owner_project_review")
        or not re.fullmatch(r"[1-9][0-9]*", entry["pool_revision"])
        or any(entry[name] not in ("active", "unverified", "revoked")
               for name in ("credential_access", "free_tier", "operator_eligibility"))
    ):
        raise ValueError("Invalid owner declaration record")
    confirmed_on = date.fromisoformat(entry["confirmed_on"])
    if confirmed_on > today or confirmed_on.isoformat() != entry["confirmed_on"]:
        raise ValueError("Invalid owner declaration date")
    return entry


def preflight(request_lock, expected_hash, model, dispatch_budget, output_cap, *, dotenv, attestation,
              environ=None, today=None, clock=time.time):
    # Passing these checks gives only local evidence. This tool never opens a provider client.
    report = {"dispatches": 0, "provider_status": "NOT_CONTACTED", "environment_status": "NOT_VERIFIED"}
    try:
        report["verified_payloads"] = check_requests(request_lock, expected_hash, model, dispatch_budget, output_cap)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {**report, "status": "BLOCKED_PLAN"}

    try:
        entry = read_attestation(attestation, today or date.today())
    except FileNotFoundError:
        return {**report, "status": "BLOCKED_OWNER_ATTESTATION", "reason": "MISSING"}
    except (OSError, ValueError, TypeError, KeyError):
        return {**report, "status": "BLOCKED_OWNER_ATTESTATION", "reason": "INVALID"}
    for field in ("credential_access", "free_tier", "operator_eligibility"):
        if entry[field] != "active":
            return {**report, "status": "BLOCKED_OWNER_ATTESTATION", "reason": field}

    try:
        local = merged_settings(dotenv, {})
        process = os.environ if environ is None else environ
        settings = {**local, **process}
        if any(settings.get(name) for name in ("GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GEMINI_BASE_URL",
                                               "GOOGLE_VERTEX_BASE_URL")):
            return {**report, "status": "BLOCKED_CREDENTIAL_OR_CONFIG", "reason": "ENDPOINT_OVERRIDE"}
        pool_settings = ("GEMINI_API_KEY_", "GEMINI_PROJECT_LABEL_", "GEMINI_PROJECT_BILLING_")
        if entry["pool_revision"] != settings.get("GEMINI_DEV_POOL_REVISION", "1") or any(
            value != local.get(name) for name, value in process.items()
            if name.startswith(pool_settings) or name == "GEMINI_KEYS_FREE_TIER_CONFIRMED"
        ):
            return {**report, "status": "BLOCKED_OWNER_ATTESTATION", "reason": "POOL_CHANGED"}

        settings.setdefault("GEMINI_KEYS_FREE_TIER_CONFIRMED", "true")
        config = inspect_settings(settings, model=model)
        config.policy.check_models((model,))
        # The loader keeps the first copy of a key. Honor billing exclusions on its other copies.
        excluded = {value.strip() for name, value in settings.items() if (match := _KEY_PATTERN.fullmatch(name))
                    and settings.get(f"GEMINI_PROJECT_BILLING_{int(match[1])}", "").strip()
                    not in ("", "FREE_TIER_CONFIRMED")}
        credential = next((slot for slot in config.credentials if slot._api_key not in excluded
                           and config.policy.billing[slot.slot_id] == "FREE_TIER_CONFIRMED"), None)
        if credential is None:
            return {**report, "status": "BLOCKED_CREDENTIAL_OR_CONFIG", "reason": "NO_ELIGIBLE_KEY"}
        store_path = state_path(settings) if settings.get("LLM_QUOTA_STATE_PATH") else (
            dotenv.parent / ".local" / "llm_quota_state.sqlite3"
        )
        store = QuotaStateStore(store_path, clock=clock)
        if store.blocked_until("gemini", model, credential.group_id, clock()) is not None:
            return {**report, "status": "BLOCKED_LOCAL_QUOTA"}
    except (GeminiConfigError, OSError, ValueError):
        return {**report, "status": "BLOCKED_CREDENTIAL_OR_CONFIG"}

    return {**report, "status": "PASSED_OFFLINE", "selected_slot": credential.slot_id}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_lock", type=Path)
    parser.add_argument("--requests-sha256", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--dispatch-budget", type=int, required=True)
    parser.add_argument("--output-cap", type=int, required=True)
    parser.add_argument("--dotenv", type=Path, default=Path(".env"))
    parser.add_argument("--attestation", type=Path)
    args = parser.parse_args(argv)
    attestation = args.attestation or args.dotenv.parent / ".local" / "gemini-dev-owner-attestation.json"
    report = preflight(args.request_lock, args.requests_sha256, args.model, args.dispatch_budget, args.output_cap,
                       dotenv=args.dotenv, attestation=attestation)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASSED_OFFLINE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
