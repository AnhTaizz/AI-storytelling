"""Run the story pipeline end to end: Brief -> Plan -> Script -> Critic -> Revision.

Usage (from the repository root, with Gemini keys in .env):

    python -m tools.story_pipeline.run_pipeline --chapters 1 --model <gemini-model>

Outputs go to .local/story_pipeline_runs/<run id>/ (git-ignored). Use --resume <run dir>
to reuse stage outputs already written there (saves API calls after a failure).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.story_pipeline import PIPELINE_VERSION, checks, stages  # noqa: E402
from tools.story_pipeline.facts import StoryFacts  # noqa: E402
from tools.story_pipeline.llm import CallLog, LLMClient, StageFailed  # noqa: E402
from tools.story_pipeline.profile import DEFAULT_PROFILE_PATH, NarrativeProfile, load_profile  # noqa: E402
from tools.story_pipeline.source import StoryScope, load_scope, parse_range  # noqa: E402

DEFAULT_MANIFEST = REPO / "data/sample/otonari_no_tenshi/wn_jp/LIGHT_NOVEL_SOURCE_MANIFEST_SAMPLE_V0.yaml"
DEFAULT_OUT_ROOT = REPO / ".local" / "story_pipeline_runs"
STAGES = ("brief", "plan", "script", "critic", "revise")

GATES = {
    "GATE_FACTUAL_GROUNDING": {"FACTUAL_ERROR", "UNSUPPORTED_INVENTION", "CAUSALITY_ERROR",
                               "SOURCE_GROUNDING_FAILURE", "OTHER"},
    "GATE_EPISTEMIC_INTEGRITY": {"EPISTEMIC_ERROR"},
    "GATE_TEMPORAL_STATE_INTEGRITY": {"TEMPORAL_ERROR", "CHARACTER_STATE_ERROR", "RELATIONSHIP_ERROR"},
    "GATE_SPOILER_DISCIPLINE": {"PREMATURE_SPOILER"},
}
SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


# --------------------------------------------------------------------------- io helpers


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cached(path: Path, resume: bool, produce: Callable[[], Any]) -> Any:
    if resume and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    obj = produce()
    write_json(path, obj)
    return obj


def script_markdown(script: Dict[str, Any], label: str) -> str:
    return f"<!-- {label} | title idea: {script['title_idea']} -->\n\n{checks.script_text(script)}\n"


# --------------------------------------------------------------------------- report


SUPPORTED_TYPES = {"SUPPORTED_FACT", "SUPPORTED_INFERENCE", "ATTRIBUTED_REPORT"}


def coverage_gate(critic: Optional[Dict[str, Any]], briefs: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, Any]:
    """CORE brief events that no supported script claim cites (critic brief_refs)."""
    if critic is None or not briefs:
        return {"status": "PLAN_ONLY",
                "note": "Every CORE brief event is assigned to a plan beat (checked). Script-level "
                        "coverage needs a critic run."}
    core = [ref for ref, event in stages.event_index(briefs).items() if event["importance"] == "CORE"]
    cited = {ref for unit in critic["units"] for claim in unit["claims"]
             if claim["claim_type"] in SUPPORTED_TYPES for ref in claim["brief_refs"]}
    missing = [ref for ref in core if ref not in cited]
    return {"status": "FLAG" if missing else "PASS", "core_events": len(core), "not_cited": missing,
            "note": "Based on the brief items the critic cites for supported claims; a missing "
                    "event may still be narrated without being cited."}


def gate_report(critic: Optional[Dict[str, Any]], check: Dict[str, Any],
                briefs: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    undetermined: List[Dict[str, Any]] = []
    claim_counts: Dict[str, int] = {}
    if critic is not None:
        for unit in critic["units"]:
            for claim in unit["claims"]:
                claim_counts[claim["claim_type"]] = claim_counts.get(claim["claim_type"], 0) + 1
                if claim["claim_type"] == "UNDETERMINED":
                    undetermined.append({"unit_id": unit["unit_id"], **claim})
                elif claim["claim_type"] in stages.PROBLEM_TYPES:
                    findings.append({"unit_id": unit["unit_id"], **claim})

    gates: Dict[str, Dict[str, Any]] = {}
    for gate, categories in GATES.items():
        hits = [f for f in findings if (f["failure_category"] or "OTHER") in categories]
        if critic is None:
            status = "NOT_CHECKED"
        elif any(f["severity"] in ("CRITICAL", "HIGH") for f in hits):
            status = "FAIL"
        elif hits:
            status = "FLAG"
        else:
            status = "PASS"
        gates[gate] = {"status": status,
                       "findings": {s: sum(1 for f in hits if f["severity"] == s) for s in SEVERITY_ORDER}}
    gates["GATE_OUTPUT_INTEGRITY"] = {
        "status": "PASS" if check["language_ok"] and check["clean_ok"] else "FAIL",
        "cjk_count": check["cjk_count"], "artifacts": check["artifacts"]}
    gates["GATE_REQUEST_COMPLIANCE"] = {
        "status": "PASS" if check["length_ok"] else "FLAG",
        "word_count": check["word_count"], "length_target": check["length_target"]}
    gates["GATE_NECESSARY_COVERAGE"] = coverage_gate(critic, briefs)
    return {"gates": gates, "claim_counts": claim_counts,
            "findings": sorted(findings, key=lambda f: SEVERITY_ORDER.index(f["severity"])),
            "undetermined": undetermined}


STATUS_VI = {"PASS": "ĐẠT", "FLAG": "CẦN XEM", "FAIL": "KHÔNG ĐẠT",
             "NOT_CHECKED": "CHƯA KIỂM TRA", "PLAN_ONLY": "CHỈ KIỂM Ở PLAN"}


def report_markdown(manifest: Dict[str, Any], report: Dict[str, Any]) -> str:
    lines = [
        f"# Báo cáo chạy pipeline — {manifest['run_id']}",
        "",
        f"- Phạm vi: {manifest['scope']['label']} (story `{manifest['scope']['story_id']}`)",
        f"- Mô hình: `{manifest['client']}`",
        f"- Profile: `{manifest['profile']['profile_id']}`, "
        f"{manifest['profile']['min_words']}–{manifest['profile']['max_words']} từ",
        f"- Số lần gọi mô hình: {manifest['model_calls']} — thời gian: {manifest['seconds']} giây",
        f"- Trạng thái: **{manifest['status']}**",
        "",
        "> Đây là kiểm tra tự động sơ bộ, không phải verdict chính thức theo "
        "`SCRIPT_QUALITY_CONTRACT/v0`. Critic là một mô hình và có thể bỏ sót lỗi.",
        "",
        "## Các gate",
        "",
        "| Gate | Trạng thái | Chi tiết |",
        "|---|---|---|",
    ]
    for gate, info in report["gates"].items():
        detail = {k: v for k, v in info.items() if k != "status"}
        lines.append(f"| {gate} | {STATUS_VI.get(info['status'], info['status'])} | "
                     f"`{json.dumps(detail, ensure_ascii=False)}` |")
    lines += ["", "## Phân loại claim (bản cuối)", ""]
    for claim_type, count in sorted(report["claim_counts"].items()):
        lines.append(f"- {claim_type}: {count}")
    lines += ["", "## Lỗi còn lại trong bản cuối", ""]
    if not report["findings"]:
        lines.append("Không có.")
    for f in report["findings"]:
        lines.append(f"- **{f['severity']}** {f['claim_type']} / {f['failure_category']} ({f['unit_id']}): "
                     f"{f['claim']}\n  - Lý do: {f['explanation']}\n  - Gợi ý: {f['suggested_fix']}")
    if report["undetermined"]:
        lines += ["", "## Cần người xem (UNDETERMINED)", ""]
        for f in report["undetermined"]:
            lines.append(f"- ({f['unit_id']}) {f['claim']} — {f['explanation']}")
    lines += ["", "## Lịch sử phiên bản", ""]
    for entry in manifest["versions"]:
        lines.append(f"- v{entry['version']}: {entry['word_count']} từ, "
                     f"{entry['problem_claims']} claim có vấn đề (CRITICAL/HIGH: {entry['high_or_worse']})")
    lines += ["", "Kịch bản cuối: `script_final.md`.", ""]
    return "\n".join(lines)


REVIEW_QUESTIONS = [
    ("factual", "Đúng sự thật: kịch bản có nói điều gì sai hoặc không có trong truyện không? (ghi rõ câu)"),
    ("coverage", "Đủ ý: có thiếu sự kiện quan trọng nào khiến người xem hiểu sai không?"),
    ("spoiler", "Spoiler: có lộ thông tin của chương sau phạm vi không?"),
    ("hook", "Mở đầu có khiến bạn muốn nghe tiếp không?"),
    ("flow", "Mạch kể và nhịp độ có hợp lý không?"),
    ("voice", "Đọc thành tiếng có tự nhiên, đúng giọng kênh không?"),
    ("usable", "Có dùng được làm kịch bản không? Cần sửa bao nhiêu phút?"),
]


def review_form(manifest: Dict[str, Any]) -> str:
    """A short human review sheet for the project owner, saved next to the script."""
    lines = [f"# Phiếu chấm kịch bản — {manifest['run_id']}", "",
             f"Phạm vi: {manifest['scope']['label']} — mô hình: `{manifest['client']}`", "",
             "Chấm mỗi mục 1–5 (5 = tốt nhất) và ghi chú ngắn. Đọc `script_final.md` trước, "
             "đối chiếu `report.md` nếu cần.", "",
             "| Mục | Câu hỏi | Điểm (1–5) | Ghi chú |", "|---|---|---|---|"]
    lines += [f"| {key} | {question} |  |  |" for key, question in REVIEW_QUESTIONS]
    lines += ["", "Lỗi cụ thể (trích câu trong kịch bản → vì sao sai):", "", "- ", "",
              "Kết luận: ☐ Dùng được ngay ☐ Sửa nhẹ ☐ Sửa nhiều ☐ Không dùng được", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- orchestration


def run(client: LLMClient, scope: StoryScope, profile: NarrativeProfile, out_dir: Path, *,
        facts: Optional[StoryFacts] = None, max_repairs: int = 2, revision_rounds: int = 1,
        revise_severities: Sequence[str] = ("CRITICAL", "HIGH", "MEDIUM"),
        stop_after: str = "revise", resume: bool = False,
        progress: Callable[[str], None] = lambda message: None) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    log = CallLog()
    started = time.time()
    manifest: Dict[str, Any] = {
        "pipeline_version": PIPELINE_VERSION,
        "run_id": out_dir.name,
        "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "client": getattr(client, "name", "unknown"),
        "scope": {"story_id": scope.story_id, "label": scope.label(),
                  "chapters": [c.order for c in scope.chapters],
                  "document_ids": [c.document_id for c in scope.chapters]},
        "profile": profile.to_dict(),
        "facts_supplied": facts is not None,
        "settings": {"max_repairs": max_repairs, "revision_rounds": revision_rounds,
                     "revise_severities": list(revise_severities), "stop_after": stop_after},
        "prompt_fingerprints": stages.prompt_fingerprints(),
        "versions": [],
        "status": "RUNNING",
    }
    write_json(out_dir / "run_manifest.json", manifest)

    def finish(status: str, error: Optional[str] = None) -> Dict[str, Any]:
        manifest["status"] = status
        if error:
            manifest["error"] = error
        manifest["model_calls"] = len(log.entries)
        manifest["seconds"] = round(time.time() - started, 1)
        write_json(out_dir / "run_manifest.json", manifest)
        calls_path = out_dir / "calls.jsonl"
        mode = "a" if resume and calls_path.exists() else "w"
        with calls_path.open(mode, encoding="utf-8") as handle:
            for entry in log.entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return manifest

    try:
        briefs: List[Dict[str, Any]] = []
        for chapter in scope.chapters:
            progress(f"brief: chapter {chapter.order}")
            briefs.append(cached(out_dir / "briefs" / f"chapter_{chapter.order:03d}.json", resume,
                                 lambda: stages.run_brief(client, scope, chapter, profile, briefs,
                                                          facts, log, max_repairs)))
        if stop_after == "brief":
            return finish("STOPPED_AFTER_BRIEF")

        progress("plan")
        plan = cached(out_dir / "plan.json", resume,
                      lambda: stages.run_plan(client, scope, briefs, profile, log, max_repairs))
        if stop_after == "plan":
            return finish("STOPPED_AFTER_PLAN")

        progress("script v1")
        script = cached(out_dir / "script_v1.json", resume,
                        lambda: stages.run_script(client, scope, briefs, plan, profile, log, max_repairs))
        (out_dir / "script_v1.md").write_text(script_markdown(script, "v1"), encoding="utf-8")
        critic: Optional[Dict[str, Any]] = None
        version = 1
        if stop_after != "script":
            while True:
                units = checks.split_units(checks.script_text(script))
                progress(f"critic v{version}")
                critic = cached(out_dir / f"critic_v{version}.json", resume,
                                lambda: stages.run_critic(client, scope, briefs, units, profile,
                                                          log, max_repairs, version))
                problems = stages.findings_for_revision(critic, SEVERITY_ORDER)
                check = checks.check_script(script, profile.min_words, profile.max_words,
                                            profile.target_language)
                manifest["versions"].append({
                    "version": version, "word_count": check["word_count"],
                    "problem_claims": len(problems),
                    "high_or_worse": sum(1 for p in problems if p["severity"] in ("CRITICAL", "HIGH"))})
                to_fix = stages.findings_for_revision(critic, revise_severities)
                if stop_after == "critic" or not to_fix or version > revision_rounds:
                    break
                version += 1
                progress(f"revise -> v{version} ({len(to_fix)} findings)")
                previous, previous_units = script, units
                script = cached(out_dir / f"script_v{version}.json", resume,
                                lambda: stages.run_revision(client, scope, briefs, plan, previous,
                                                            to_fix, previous_units, profile, log,
                                                            max_repairs, version))
                (out_dir / f"script_v{version}.md").write_text(script_markdown(script, f"v{version}"),
                                                              encoding="utf-8")
        final_check = checks.check_script(script, profile.min_words, profile.max_words,
                                          profile.target_language)
        (out_dir / "script_final.md").write_text(script_markdown(script, f"final v{version}"),
                                                 encoding="utf-8")
        report = gate_report(critic, final_check, briefs)
        report["final_version"] = version
        report["final_check"] = final_check
        write_json(out_dir / "report.json", report)
        status = "COMPLETED" if critic is not None else "STOPPED_AFTER_SCRIPT"
        finish(status)
        (out_dir / "report.md").write_text(report_markdown(manifest, report), encoding="utf-8")
        (out_dir / "review_form.md").write_text(review_form(manifest), encoding="utf-8")
        return manifest
    except StageFailed as exc:
        return finish("FAILED", str(exc))
    except RuntimeError as exc:  # e.g. GeminiTransportError after transport retries
        return finish("FAILED", f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST),
                        help="LIGHT_NOVEL_INGESTION/v0 manifest (default: tracked sample, chapters 1-5)")
    parser.add_argument("--source-root", default=None, help="directory holding the manifest paths")
    parser.add_argument("--chapters", default="1", help="chapter range, e.g. 1 or 1-5 (also the spoiler boundary)")
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE_PATH), help="Narrative Profile YAML")
    parser.add_argument("--min-words", type=int, default=None, help="override profile minimum length")
    parser.add_argument("--max-words", type=int, default=None, help="override profile maximum length")
    parser.add_argument("--model", default=None, help="Gemini model id (default: GEMINI_MODEL in .env)")
    parser.add_argument("--temperature", type=float, default=0.4)
    parser.add_argument("--dotenv", default=str(REPO / ".env"))
    parser.add_argument("--facts", default=None, help="optional story_facts/v0 JSON from upstream extraction")
    parser.add_argument("--max-repairs", type=int, default=2, help="validation-feedback repairs per call")
    parser.add_argument("--revision-rounds", type=int, default=1, help="critic-guided revision rounds")
    parser.add_argument("--revise-severities", default="CRITICAL,HIGH,MEDIUM",
                        help="comma list of severities sent to revision")
    parser.add_argument("--stop-after", choices=STAGES, default="revise")
    parser.add_argument("--out", default=None, help="run directory (default: .local/story_pipeline_runs/<id>)")
    parser.add_argument("--resume", default=None, help="existing run directory; reuse its stage outputs")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    scope = load_scope(args.manifest, parse_range(args.chapters), args.source_root)
    profile = load_profile(args.profile).with_length(args.min_words, args.max_words)
    facts = StoryFacts.load(args.facts) if args.facts else None

    from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError
    from tools.story_pipeline.llm import GeminiLLMClient
    try:
        client = GeminiLLMClient(args.model, dotenv_path=args.dotenv, temperature=args.temperature)
    except GeminiConfigError as exc:
        print(f"config error: {exc}. Copy .env.example to .env and fill GEMINI_API_KEY_1 "
              f"(and GEMINI_MODEL or --model).", file=sys.stderr)
        return 2

    if args.resume:
        out_dir, resume = Path(args.resume), True
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = Path(args.out) if args.out else DEFAULT_OUT_ROOT / f"{stamp}_ch{scope.first}-{scope.last}"
        resume = False
    print(f"run dir: {out_dir}", flush=True)
    manifest = run(client, scope, profile, out_dir, facts=facts, max_repairs=args.max_repairs,
                   revision_rounds=args.revision_rounds,
                   revise_severities=[s.strip() for s in args.revise_severities.split(",") if s.strip()],
                   stop_after=args.stop_after, resume=resume,
                   progress=lambda message: print(f"  ... {message}", flush=True))
    print(f"status: {manifest['status']}  calls: {manifest['model_calls']}  seconds: {manifest['seconds']}")
    if manifest.get("error"):
        print(f"error: {manifest['error']}")
    if (out_dir / "report.md").exists():
        print(f"report: {out_dir / 'report.md'}")
    return 0 if manifest["status"] != "FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
