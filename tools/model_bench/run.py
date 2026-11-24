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
from tools.model_bench.approval import LiveRefusal, approval_budget, load_approval
from tools.model_bench.dataset import DRAFT_GOLD_STATUS, GROUPS, ROOT, canonical_json, gold_statuses, load_dataset
from tools.model_bench.m9 import check_m9
from tools.model_bench.planning import (DEFAULT_MAX_OUTPUT, MAX_TRANSPORT_CALLS, PROMPT_VERSION,
                                        SCREENING_CASES, SCREENING_REQUEST_CAP, SCREENING_WAVES, SYSTEM, TEMPERATURE,
                                        approval_sha256, display, make_plan, plan_markdown,
                                        quota_text, user_prompt)
from tools.model_bench.registry import PROVIDERS, select_model
from tools.model_bench.reporting import METRICS, TOKEN_METRICS, efficiency, write_reports, write_text
from tools.model_bench.scoring import score

RUNS = ROOT / ".local" / "model_bench_runs"
SEASONS = ROOT / ".local" / "story_seasons"


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


def _attempt_metrics(record, error=None, *, secrets=()):
    attempts = record.get("transport_attempts")
    failures = record.get("failures")
    codes = [item.get("outcome") or item.get("code")
             for items in (attempts, failures) if isinstance(items, list)
             for item in items if isinstance(item, dict)]
    count = record.get("attempt_count")
    if count is None and isinstance(attempts, list):
        count = len(attempts)
    if count is None and error is not None:
        # ProviderAdapter suppresses the underlying router error in tracebacks.
        # The router still exposes its numeric attempt count on that exception.
        count = getattr(error.__context__, "attempts", None)
        if count is None and isinstance(failures, list):
            count = len(failures)
        if error.code == "DISPATCH_LIMIT":
            count = MAX_TRANSPORT_CALLS
        codes.append(error.code)
    minimum = 0 if error is not None else 1
    count = count if type(count) is int and minimum <= count <= MAX_TRANSPORT_CALLS else None
    safe_codes = list(dict.fromkeys(code for code in codes if isinstance(code, str) and code != "SUCCESS"
                                    and re.fullmatch(r"[A-Z][A-Z_0-9]{0,63}", code)
                                    and not any(secret in code for secret in secrets)))
    return {"requests": count, "retries": max(0, count - 1) if count is not None else None,
            "error_codes": safe_codes}


def _run_case(client, model, max_output, case, *, live=False, secrets=()):
    row = {"case_id": case["id"], "group": case["group"], "score": None, "review": None,
           "outcome": "error", "error": None, "tokens_source": "unknown", "budget_used": None,
           "budget_cap": None, **dict.fromkeys(METRICS)}
    row["repairs"] = 0
    started = time.monotonic()
    try:
        with transport_budget() if live else nullcontext():
            response = client.complete(system=SYSTEM, user=user_prompt(case), model=model,
                                       request_id=case["id"], max_output_tokens=max_output)
    except ProviderFailure as error:
        row.update(_attempt_metrics(error.metadata or {}, error, secrets=secrets))
        row["error"] = "provider_failure"
        row["latency_ms"] = round((time.monotonic() - started) * 1000)
        return row
    row["latency_ms"] = round((time.monotonic() - started) * 1000)
    for metric in TOKEN_METRICS:
        value = (response.get("usage") or {}).get(metric)
        row[metric] = value if type(value) is int and value >= 0 else None
    if any(row[metric] is not None for metric in TOKEN_METRICS):
        row["tokens_source"] = "estimated" if response.get("tokens_source") == "estimated" else "reported"
    row.update(_attempt_metrics(response, secrets=secrets))
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
                not isinstance(candidate, str) or not candidate.strip()):
            raise ValueError("Invalid review candidate")
        canonical_json(candidate).encode("utf-8")
        scored = score(case, candidate)
        # Reject unsafe text even if the raw envelope hid it behind JSON escapes.
        serialized = canonical_json(scored)
        serialized.encode("utf-8")
        if any(secret in serialized for secret in secrets):
            raise ValueError("Invalid review candidate")
        row.update(scored, outcome="complete")
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


def execute(directory, metadata, cases, client_factory, *, resume=False, secrets=(),
            budget=None, before_dispatch=None):
    live = metadata["mode"] == "live"
    if live and budget is None:
        raise LiveRefusal("Cần có sổ ngân sách để chạy benchmark trực tiếp.")
    manifest = directory / "run.json"
    checkpoint = directory / "results.jsonl"
    budget_path = directory / "budget.json"
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
            if live and budget.used < json.loads(budget_path.read_text(encoding="utf-8"))["budget_used"]:
                raise LiveRefusal("Sổ ngân sách không khớp với lần chạy cần tiếp tục.")
        else:
            write_text(manifest, canonical_json(metadata) + "\n")
            checkpoint.touch(exist_ok=False)
        case_ids = [case["id"] for case in cases]
        rows = _read_checkpoints(checkpoint, case_ids, live=live)
        if live and in_flight.exists():
            if not rows or in_flight.read_text(encoding="utf-8").strip() != rows[-1]["case_id"]:
                raise ValueError("Live dispatch status is unknown. Reconcile it before resuming.")
            in_flight.unlink()
        client = None
        model = metadata["model"]
        run_status = "COMPLETED"
        if live and budget.used == budget.cap:
            run_status = "BUDGET_EXHAUSTED"
        if live and not resume:
            _write_budget(budget_path, budget, "IN_PROGRESS")
        for case in cases[len(rows):]:
            if live:
                if budget.cap - budget.used < MAX_TRANSPORT_CALLS:
                    run_status = "BUDGET_EXHAUSTED"
                    break
                if before_dispatch is not None:
                    before_dispatch()
            if client is None:
                client = client_factory()
                if tuple(client.models) != (model,):
                    raise ValueError("Client must pin exactly the selected model")
            if live:
                reservation = budget.reserve()
                with in_flight.open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(case["id"] + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            row = _run_case(client, model, metadata["max_output_tokens"], case, live=live, secrets=secrets)
            status = metadata.get("gold_statuses", {}).get(case["id"], case["gold_status"])
            row.update(gold_status=status, gold_tier="approved" if status == "approved" else "draft")
            if row["review"] is not None:
                row["review"].update(gold_status=status, gold_tier=row["gold_tier"])
            if row["error"] is not None and (code := row["error"].upper()) not in row["error_codes"]:
                row["error_codes"].append(code)
            if live:
                budget.settle(reservation, row["requests"])
                row.update(budget_used=budget.used, budget_cap=budget.cap)
            row.update(efficiency(row, int(row["outcome"] == "complete")))
            with checkpoint.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(canonical_json(row) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            rows.append(row)
            if live:
                run_status = "COMPLETED"
                if budget.used == budget.cap:
                    run_status = "BUDGET_EXHAUSTED"
                elif row["error"] in {"provider_failure", "model_mismatch"} or row["requests"] is None:
                    run_status = "STOPPED"
                _write_budget(budget_path, budget, run_status)
                in_flight.unlink()
                if run_status != "COMPLETED":
                    break
        report_meta = metadata
        if live:
            state = _write_budget(budget_path, budget, run_status)
            report_meta = metadata | state
        write_reports(directory, report_meta, cases, rows)
        return rows
    finally:
        lease.unlink()


def _write_budget(path, budget, status):
    state = {"budget_used": budget.used, "budget_cap": budget.cap, "run_status": status}
    temporary = path.with_suffix(".tmp")
    write_text(temporary, canonical_json(state) + "\n")
    temporary.replace(path)
    return state


def _arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=PROVIDERS)
    parser.add_argument("--model")
    parser.add_argument("--screening", action="store_true", help="print the fixed Phase 7B screening table")
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
    parser.add_argument("--gold-review", type=Path, help="path to an owner-confirmed GOLD_REVIEW.json")
    parser.add_argument("--include-drafts", action="store_true")
    parser.add_argument("--seasons-dir", type=Path, default=SEASONS)
    parser.add_argument("--m9-clear-attested-by-owner", action="store_true")
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
    if args.screening:
        if (not args.plan_md or args.provider or args.model or args.group or args.case or args.limit
                or args.include_drafts or args.gold_review or args.max_output_tokens != DEFAULT_MAX_OUTPUT):
            parser.error("--screening requires --dry-run --plan-md and uses a fixed selection")
    elif not args.provider or not args.model:
        parser.error("--provider and --model are required")
    return parser, args


def _configuration(model, dataset_hash, cases, args, commit):
    metadata = {"dataset_sha256": dataset_hash, "prompt_version": PROMPT_VERSION,
                "provider": model["provider"], "model": model["model_id"], "temperature": TEMPERATURE,
                "max_output_tokens": args.max_output_tokens, "json_mode": model["json_mode"],
                "git_commit": commit, "mode": args.mode, "case_ids": [c["id"] for c in cases],
                "include_drafts": args.include_drafts}
    case_plans = make_plan(model, cases, args.max_output_tokens)
    metadata["plan_sha256"] = approval_sha256(metadata, model, case_plans)
    return metadata, case_plans


def main(argv=None):
    parser, args = _arguments(argv)
    try:
        dataset_hash, cases = load_dataset()
        commit = _commit()
        if args.screening:
            cases = _select_cases(cases, (), SCREENING_CASES, None)
            print(f"Revision at generation: `{display(commit)}`")
            print("\n**Pending on `main` after merge.** Regenerate the dry-run plan and per-model fingerprints.\n")
            for wave, candidates in SCREENING_WAVES:
                plans = []
                for provider, model_id, reason in candidates:
                    model = select_model(provider, model_id)
                    metadata, case_plans = _configuration(model, dataset_hash, cases, args, commit)
                    plans.append((model, case_plans, metadata["plan_sha256"], SCREENING_REQUEST_CAP, reason))
                print(plan_markdown(plans, wave=wave))
            return 0
        model = select_model(args.provider, args.model)
        cases = _select_cases(cases, args.group, args.case, args.limit)
        options = {"path": args.gold_review} if args.gold_review else {}
        statuses = gold_statuses(dataset_hash, cases, **options)
        if args.mode == "live":
            eligible = {"approved", DRAFT_GOLD_STATUS} if args.include_drafts else {"approved"}
            cases = [case for case in cases if statuses[case["id"]] in eligible]
            if not cases:
                raise LiveRefusal("Không có ca nào đủ điều kiện duyệt đáp án cho lựa chọn này.")
        metadata, case_plans = _configuration(model, dataset_hash, cases, args, commit)
        if args.mode == "dry-run":
            cap = len(cases) * MAX_TRANSPORT_CALLS
            if args.plan_md:
                print(plan_markdown([(model, case_plans, metadata["plan_sha256"], cap, "Selected model")]), end="")
            else:
                tokens = sum(item["input"] for item in case_plans)
                out = len(cases) * args.max_output_tokens
                print(f"Dry run: {len(cases)} cases × 1 model ({args.provider} / {args.model})")
                print(f"Estimated requests: {len(cases)}. Tokens: {tokens} input + {out} reserved output = {tokens + out}.")
                print(f"Worst-case request cap including retries: {cap}.")
                print(f"Context: {display(model['context_tokens'])}. Output cap: {display(model['max_output_tokens'])}.")
                print(f"Quota ({model['quota_scope']}): {quota_text(model)}")
                for item in case_plans:
                    if item["flags"]:
                        print(f"Over limit: {item['case_id']} ({', '.join(item['flags'])})")
            return 0
        directory = args.output_dir or RUNS / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        metadata["gold_statuses"] = {case["id"]: statuses[case["id"]] for case in cases}
        secrets = ()
        state = {}
        if args.mode == "live":
            approval = load_approval(args.approved_plan, metadata)
            metadata.update(plan_id=approval[0]["plan_id"], approval_content_sha256=approval[0]["content_sha256"],
                            m9_clear_attested_by_owner=args.m9_clear_attested_by_owner)
            if args.provider == "gemini":
                metadata["seasons_dir"] = str(args.seasons_dir.resolve())

            def clearance():
                check_m9(args.provider, args.seasons_dir, args.m9_clear_attested_by_owner)

            clearance()
            if metadata["git_commit"] is None:
                raise ValueError("Live requires a known git revision")
            if any(item["flags"] for item in case_plans):
                raise ValueError("Live requires a named, pinned model and a plan without flagged cases")
            settings = dict(os.environ)
            secrets = configured_secrets(settings)

            def factory():
                try:
                    return build_adapter(args.provider, settings, QuotaStateStore(RUNS / "quota.sqlite3"),
                                         model=args.model, temperature=TEMPERATURE, strict=True, secrets=secrets)
                except Exception:
                    raise ValueError("Provider adapter configuration failed") from None
            with approval_budget(RUNS / "approvals", approval, metadata, resume=args.resume) as budget:
                rows = execute(directory, metadata, cases, factory, resume=args.resume, secrets=secrets,
                               budget=budget, before_dispatch=clearance)
                state = json.loads((directory / "budget.json").read_text(encoding="utf-8"))
        else:
            def factory():
                return FakeClient(args.model, cases)
            rows = execute(directory, metadata, cases, factory, resume=args.resume)

        print(f"Checkpointed {len(rows)} of {len(cases)} cases. Outputs: {directory}")
        if state:
            print(state["run_status"])
        return int(state.get("run_status", "COMPLETED") != "COMPLETED"
                   or len(rows) != len(cases) or any(row["outcome"] == "error" for row in rows))
    except LiveRefusal as error:
        parser.exit(2, f"{error}\n")
    except ValidationError:
        parser.error("Invalid registry or dataset schema")
    except (OSError, ValueError, KeyError) as error:
        if args.mode == "live":
            # Avoid printing filesystem, configuration or response details from live execution.
            parser.exit(2, "Live run refused or stopped. Check its approval, pin, quota plan and checkpoints.\n")
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
