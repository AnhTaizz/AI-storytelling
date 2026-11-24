"""Plan a model benchmark offline or execute one pinned, owner-approved repeat."""
import argparse
from contextlib import nullcontext
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time
from uuid import uuid4

from jsonschema import ValidationError

from tools.llm_infra.pipeline_clients import (ProviderFailure, build_adapter, configured_secrets,
                                               transport_budget)
from tools.llm_infra.quota_state import QuotaStateStore
from tools.model_bench.dataset import GROUPS, ROOT, canonical_json, load_dataset
from tools.model_bench.planning import (DEFAULT_MAX_OUTPUT, PROMPT_VERSION, SYSTEM, TEMPERATURE,
                                        approval_sha256, display, make_plan, plan_markdown,
                                        quota_text, user_prompt)
from tools.model_bench.registry import PROVIDERS, select_model
from tools.model_bench.reporting import METRICS, write_reports, write_text
from tools.model_bench.scoring import score

RUNS = ROOT / ".local" / "model_bench_runs"


def _commit():
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, check=False)
    except FileNotFoundError:
        return None
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", commit) else None


class FakeClient:
    """Return fixture answers through the same response contract as a provider."""
    def __init__(self, model, cases):
        self.models = (model,)
        self.cases = {case["id"]: case for case in cases}

    def complete(self, *, system, user, request_id, model, max_output_tokens):
        case = self.cases[request_id]
        method, answer = case["scoring_method"], case["gold"]
        if method == "json_schema":
            answer = answer["example"]
        if method == "rubric_human":
            answer = "Phản hồi giả lập để kiểm tra phiếu đánh giá."
        return {"raw_content": canonical_json({"answer": answer}), "transport_attempts": [{}]}


def _select_cases(cases, groups, case_ids, limit):
    if set(case_ids) - {case["id"] for case in cases}:
        raise ValueError("Unknown case ID")
    selected = [case for case in cases if (not groups or case["group"] in groups)
                and (not case_ids or case["id"] in case_ids)][:limit]
    if not selected:
        raise ValueError("No cases match the selection")
    return selected


def _reject_constant(_value):
    raise ValueError("Invalid JSON number")


def _answer(pairs):
    parsed = dict(pairs)
    if len(parsed) != len(pairs):
        raise ValueError("Duplicate JSON key")
    return parsed


def _run_case(client, model, max_output, case, *, live=False, secrets=()):
    row = {"case_id": case["id"], "group": case["group"], "score": None, "review": None,
           "outcome": "error", "error": None, **dict.fromkeys(METRICS)}
    row["repairs"] = 0
    started = time.monotonic()
    try:
        with transport_budget() if live else nullcontext():
            response = client.complete(system=SYSTEM, user=user_prompt(case), model=model,
                                       request_id=case["id"], max_output_tokens=max_output)
    except ProviderFailure:
        row["error"] = "provider_failure"
        row["latency_ms"] = round((time.monotonic() - started) * 1000)
        return row
    row["latency_ms"] = round((time.monotonic() - started) * 1000)
    for metric in ("input_tokens", "output_tokens", "reasoning_tokens"):
        value = (response.get("usage") or {}).get(metric)
        row[metric] = value if type(value) is int and value >= 0 else None
    attempts = response.get("transport_attempts")
    if isinstance(attempts, list) and attempts:
        row.update(requests=len(attempts), retries=len(attempts) - 1)
    reported = response.get("model_reported")
    if reported is not None and reported not in (model, model.removesuffix(":free")):
        row["error"] = "model_mismatch"
        return row
    raw = response.get("raw_content")
    if not isinstance(raw, str) or any(secret in raw for secret in secrets):
        row["error"] = "invalid_response"
        return row
    try:
        envelope = json.loads(raw, parse_constant=_reject_constant, object_pairs_hook=_answer)
        if not isinstance(envelope, dict) or set(envelope) != {"answer"}:
            raise ValueError("Invalid response envelope")
        candidate = envelope["answer"]
        if case["scoring_method"] == "rubric_human" and (
                not isinstance(candidate, str) or not candidate.strip()
                or any(secret in candidate for secret in secrets)):
            raise ValueError("Invalid review candidate")
        # Refuse unpaired surrogate escapes before checkpointing candidate text.
        canonical_json(candidate).encode("utf-8")
        row.update(score(case, candidate), outcome="complete")
    except (ValueError, RecursionError):
        row["error"] = "invalid_response"
    return row


def _read_checkpoints(path, case_ids, *, live):
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        if live:
            raise ValueError("Incomplete live checkpoint. Reconcile the last dispatch before resuming.")
        raw = raw[:raw.rfind(b"\n") + 1]
        path.write_bytes(raw)
    rows = [json.loads(line) for line in raw.decode("utf-8").split("\n") if line]
    saved_ids = [row["case_id"] for row in rows]
    if saved_ids != case_ids[:len(saved_ids)]:
        raise ValueError("Checkpoint cases do not match the selected order")
    return rows


def execute(directory, metadata, cases, client_factory, *, resume=False, secrets=()):
    live = metadata["mode"] == "live"
    manifest = directory / "run.json"
    checkpoint = directory / "results.jsonl"
    in_flight = directory / "live_in_flight"
    lease = directory / "run.lock"
    if not resume:
        directory.mkdir(parents=True)
    with lease.open("x", encoding="utf-8") as stream:
        stream.write(f"{os.getpid()}\n")
    try:
        if resume:
            if manifest.read_text(encoding="utf-8") != canonical_json(metadata) + "\n":
                raise ValueError("Resume settings do not match run metadata")
        else:
            write_text(manifest, canonical_json(metadata) + "\n")
            checkpoint.touch(exist_ok=False)
        case_ids = [case["id"] for case in cases]
        rows = _read_checkpoints(checkpoint, case_ids, live=live)
        if live and in_flight.exists():
            if not rows or in_flight.read_text(encoding="utf-8").strip() != rows[-1]["case_id"]:
                raise ValueError("Live dispatch status is unknown. Reconcile it before resuming.")
            in_flight.unlink()
        client = client_factory() if len(rows) < len(cases) else None
        model = metadata["model"]
        if client is not None and tuple(client.models) != (model,):
            raise ValueError("Client must pin exactly the selected model")
        for case in cases[len(rows):]:
            if live:
                with in_flight.open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(case["id"] + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            row = _run_case(client, model, metadata["max_output_tokens"], case, live=live, secrets=secrets)
            with checkpoint.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(canonical_json(row) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            rows.append(row)
            if live:
                in_flight.unlink()
                if row["error"] in {"provider_failure", "model_mismatch"}:
                    break
        write_reports(directory, metadata, cases, rows)
        return rows
    finally:
        lease.unlink()


def _validate_approval(path, fingerprint):
    document = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(document, dict) or document.get("plan_sha256") != fingerprint
            or not isinstance(document.get("approved_by"), str) or not document["approved_by"].strip()
            or document.get("m9_quota_clear") is not True):
        raise ValueError("Approval must match the dry-run fingerprint and confirm owner and M9 quota clearance")


def _arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=PROVIDERS, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--group", choices=GROUPS, action="append", default=[])
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_const", const="dry-run", dest="mode")
    mode.add_argument("--offline-fake", action="store_const", const="offline-fake", dest="mode")
    mode.add_argument("--live", action="store_const", const="live", dest="mode")
    parser.set_defaults(mode="dry-run")
    parser.add_argument("--approved-plan", type=Path)
    parser.add_argument("--plan-md", action="store_true", help="print the owner approval table in Markdown")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    if (args.limit is not None and args.limit <= 0) or args.max_output_tokens <= 0:
        parser.error("Limit and output reserve must be positive")
    if (args.mode == "live") != (args.approved_plan is not None):
        parser.error("--live requires --approved-plan, which is accepted only in live mode")
    if args.mode != "dry-run" and args.plan_md:
        parser.error("--plan-md requires dry-run")
    if (args.resume and args.output_dir is None) or (
            args.mode == "dry-run" and (args.output_dir is not None or args.resume)):
        parser.error("--resume needs an execution mode and --output-dir")
    return parser, args


def main(argv=None):
    parser, args = _arguments(argv)
    try:
        model = select_model(args.provider, args.model)
        dataset_hash, cases = load_dataset()
        cases = _select_cases(cases, args.group, args.case, args.limit)
        metadata = {"dataset_sha256": dataset_hash, "prompt_version": PROMPT_VERSION,
                    "provider": args.provider, "model": args.model, "temperature": TEMPERATURE,
                    "max_output_tokens": args.max_output_tokens, "json_mode": model["json_mode"],
                    "git_commit": _commit(), "mode": args.mode, "case_ids": [c["id"] for c in cases]}
        case_plans = make_plan(model, cases, args.max_output_tokens)
        fingerprint = approval_sha256(metadata, model, case_plans)
        metadata["plan_sha256"] = fingerprint
        if args.mode == "dry-run":
            if args.plan_md:
                print(plan_markdown(model, case_plans, fingerprint), end="")
            else:
                tokens = sum(item["input"] for item in case_plans)
                out = len(cases) * args.max_output_tokens
                print(f"Dry run: {len(cases)} cases × 1 model ({args.provider} / {args.model})")
                print(f"Estimated requests: {len(cases)}. Tokens: {tokens} input + {out} reserved output = {tokens + out}.")
                print(f"Context: {display(model['context_tokens'])}. Output cap: {display(model['max_output_tokens'])}.")
                print(f"Quota ({model['quota_scope']}): {quota_text(model)}")
                for item in case_plans:
                    if item["flags"]:
                        print(f"Over limit: {item['case_id']} ({', '.join(item['flags'])})")
            return 0
        directory = args.output_dir or RUNS / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        secrets = ()
        if args.mode == "live":
            _validate_approval(args.approved_plan, fingerprint)
            if metadata["git_commit"] is None:
                raise ValueError("Live requires a known git revision")
            if args.model == "openrouter/free" or any(item["flags"] for item in case_plans):
                raise ValueError("Live requires a named, pinned model and a plan without flagged cases")
            settings = dict(os.environ)
            secrets = configured_secrets(settings)

            def factory():
                try:
                    return build_adapter(args.provider, settings, QuotaStateStore(RUNS / "quota.sqlite3"),
                                         model=args.model, temperature=TEMPERATURE, strict=True, secrets=secrets)
                except Exception:
                    raise ValueError("Provider adapter configuration failed") from None
        else:
            def factory():
                return FakeClient(args.model, cases)

        rows = execute(directory, metadata, cases, factory, resume=args.resume, secrets=secrets)
        print(f"Checkpointed {len(rows)} of {len(cases)} cases. Outputs: {directory}")
        return int(len(rows) != len(cases) or any(row["outcome"] == "error" for row in rows))
    except ValidationError:
        parser.error("Invalid registry or dataset schema")
    except (OSError, ValueError, KeyError) as error:
        if args.mode == "live":
            # Avoid printing filesystem, configuration or response details from live execution.
            parser.exit(2, "Live run refused or stopped. Check its approval, pin, quota plan and checkpoints.\n")
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
