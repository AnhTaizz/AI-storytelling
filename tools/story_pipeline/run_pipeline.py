"""Run the story pipeline end to end: Brief -> Plan -> Script -> Critic -> Revision.

Usage (from the repository root, with Gemini keys in .env):

    python -m tools.story_pipeline.run_pipeline --chapters 1 --model <gemini-model>

Outputs go to .local/story_pipeline_runs/<run id>/ (git-ignored). Use --resume <run dir>
to reuse stage outputs already written there (saves API calls after a failure).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.story_memory.memory_v0 import StoryMemory, recap_context  # noqa: E402
from tools.story_pipeline import PIPELINE_VERSION, checks, stages  # noqa: E402
from tools.story_pipeline.facts import StoryFacts  # noqa: E402
from tools.story_pipeline.llm import CallLog, LLMClient, StageFailed  # noqa: E402
from tools.story_pipeline.profile import DEFAULT_PROFILE_PATH, NarrativeProfile, load_profile  # noqa: E402
from tools.story_pipeline.source import Chapter, StoryScope, load_scope, parse_range  # noqa: E402

DEFAULT_MANIFEST = REPO / "data/sample/otonari_no_tenshi/wn_jp/LIGHT_NOVEL_SOURCE_MANIFEST_SAMPLE_V0.yaml"
DEFAULT_OUT_ROOT = REPO / ".local" / "story_pipeline_runs"
DEFAULT_MEMORY_ROOT = REPO / ".local" / "story_memory"
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


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def cached(path: Path, resume: bool, inputs: Any, produce: Callable[[], Any]) -> Any:
    """Only reuse an artifact for the same inputs, including its upstream dependencies."""
    key = digest(inputs)
    receipt = path.with_suffix(".cache.json")
    if resume and path.is_file() and receipt.is_file():
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            if json.loads(receipt.read_text(encoding="utf-8")) == [key, digest(obj)]:
                return obj
        except (ValueError, OSError):
            pass  # rebuild an incomplete checkpoint
    obj = produce()
    write_json(path, obj)
    write_json(receipt, [key, digest(obj)])
    return obj


def review_units(script: Dict[str, Any]) -> List[Dict[str, str]]:
    return [{"unit_id": "TITLE", "text": script["title_idea"]}, *checks.split_units(checks.script_text(script))]


def script_markdown(script: Dict[str, Any], label: str) -> str:
    return f"<!-- {label} | title idea: {script['title_idea']} -->\n\n{checks.script_text(script)}\n"


# --------------------------------------------------------------------------- report


def coverage_gate(critic: Optional[Dict[str, Any]], briefs: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, Any]:
    """CORE brief events that no supported script claim cites (critic brief_refs)."""
    if critic is None or not briefs:
        return {"status": "PLAN_ONLY",
                "note": "Every CORE brief event is assigned to a plan beat (checked). Script-level "
                        "coverage needs a critic run."}
    core = [ref for ref, event in stages.event_index(briefs).items() if event["importance"] == "CORE"]
    cited = {ref for unit in critic["units"] if unit["unit_id"] != "TITLE"
             for claim in unit["claims"] if claim["claim_type"] in stages.SUPPORTED_CLAIM_TYPES
             for ref in claim["brief_refs"]}
    missing = [ref for ref in core if ref not in cited]
    return {"status": "FLAG" if missing else "PASS", "core_events": len(core), "not_cited": missing,
            "note": "Based on the brief items the critic cites for supported claims; a missing "
                    "event may still be narrated without being cited."}


def gate_report(critic: Optional[Dict[str, Any]], check: Dict[str, Any],
                briefs: Optional[Sequence[Dict[str, Any]]] = None,
                audit: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
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
    findings += list(audit)  # deterministic strength audit (stages.strength_audit)

    gates: Dict[str, Dict[str, Any]] = {}
    for gate, categories in GATES.items():
        hits = [f for f in findings if (f["failure_category"] or "OTHER") in categories]
        unresolved = [u for u in undetermined if (u["failure_category"] or "OTHER") in categories]
        if critic is None:
            status = "NOT_CHECKED"
        elif any(f["severity"] in ("CRITICAL", "HIGH") for f in hits):
            status = "FAIL"
        elif hits or unresolved:
            status = "FLAG"
        else:
            status = "PASS"
        gates[gate] = {"status": status, "undetermined": len(unresolved),
                       "findings": {s: sum(1 for f in hits if f["severity"] == s) for s in SEVERITY_ORDER}}
    gates["GATE_OUTPUT_INTEGRITY"] = {
        "status": "PASS" if check["language_ok"] and check["clean_ok"] else "FAIL",
        "foreign_script_count": check["foreign_script_count"], "artifacts": check["artifacts"]}
    gates["GATE_REQUEST_COMPLIANCE"] = {
        "status": "PASS" if check["length_ok"] else "FLAG",
        "word_count": check["word_count"], "length_target": check["length_target"]}
    gates["GATE_NECESSARY_COVERAGE"] = coverage_gate(critic, briefs)
    return {"gates": gates, "claim_counts": claim_counts,
            "findings": sorted(findings, key=lambda f: SEVERITY_ORDER.index(f["severity"])),
            "undetermined": undetermined}


STATUS_VI = {"PASS": "ĐẠT", "FLAG": "CẦN XEM", "FAIL": "KHÔNG ĐẠT",
             "NOT_CHECKED": "CHƯA KIỂM TRA", "PLAN_ONLY": "CHỈ KIỂM Ở PLAN"}


def _language_line(coverage: Optional[Dict[str, Any]]) -> str:
    if not coverage or not coverage["missing_lexicons"]:
        return "- Kiểm tra theo ngôn ngữ: đầy đủ (mức độ, rào đón trong brief)"
    return (f"- Kiểm tra theo ngôn ngữ: **THIẾU** từ điển cho {coverage['missing_lexicons']} — "
            f"kiểm tra mức độ: {'có' if coverage['strength_audit'] else 'KHÔNG chạy'}, "
            f"rào đón trong brief: {'có' if coverage['brief_hedge_check'] else 'KHÔNG chạy'} "
            f"(thêm tools/story_pipeline/lexicons/<mã>.yaml)")


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
        _language_line(manifest.get("language_checks")),
        "",
        "> Đây là kiểm tra tự động sơ bộ, không phải verdict chính thức theo "
        "`SCRIPT_QUALITY_CONTRACT/v0`. Critic là một mô hình và có thể bỏ sót lỗi.",
        "",
        "## Các gate",
        "",
        "| Gate | Trạng thái | Chi tiết |",
        "|---|---|---|",
    ]
    if "compression" in report:
        size = report["compression"]
        basis = {"estimated_translation": "ước tính độ dài bản dịch đầy đủ", "source_count": "đếm văn bản nguồn",
                 "user_supplied": "độ dài bản đầy đủ do người dùng cung cấp"}[size["basis"]]
        lines[2:2] = [f"- Tỷ lệ lời kể: {size['actual_ratio']:.1%} trên {size['full_target_units']} đơn vị "
                       f"({basis})."]
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
        for evidence in f.get("source_evidence", []):
            lines.append(f"  - [{evidence['passage_id']}] {evidence['quote']}")
    if report.get("source_hedge_review"):
        lines += ["", "## Cần người xem: brief có thể đã bỏ mất rào đón của nguồn", "",
                  "Đoạn nguồn được trích có từ rào đón (lời đồn, vẻ bề ngoài, phỏng đoán, ẩn dụ) "
                  "nhưng mục brief viết như sự thật. Khoảng một nửa là đúng; phần còn lại là rào đón "
                  "nói về chuyện khác trong cùng đoạn. Không tự động sửa.", ""]
        for item in report["source_hedge_review"]:
            marks = ", ".join(f"{phrase} ({pid})" for _, phrase, pid in item["source_hedges"])
            lines.append(f"- {item['ref']}: {item['text'][:160]} — nguồn: {marks}")
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
    ("payoff", "Đoạn nào trả lời điều tiêu đề gợi ra? Nếu kết mở, kịch bản dừng đúng ở đâu trong truyện?"),
    ("usable", "Có dùng được làm kịch bản không? Cần sửa bao nhiêu phút?"),
]


def review_form(manifest: Dict[str, Any], plan: Dict[str, Any], script: Dict[str, Any]) -> str:
    """A short human review sheet for the project owner, saved next to the script."""
    opening = checks.split_units(checks.script_text(script))
    lines = [f"# Phiếu chấm kịch bản — {manifest['run_id']}", "",
             f"Phạm vi: {manifest['scope']['label']} — mô hình: `{manifest['client']}`", "",
             f"**Tiêu đề dự kiến** — {script['title_idea']}", "",
             f"**Ý mở theo dàn ý** — {plan['hook']['idea']}", "",
             "**Đoạn mở thực tế**", "", opening[0]["text"] if opening else "(trống)", "",
             "Đọc thành tiếng 30 giây đầu. Người xem chờ điều gì sau khi đọc tiêu đề? "
             "Ghi câu đầu tiên thực hiện lời hứa đó và đánh dấu đoạn trả lời ở phần sau.", "",
             "Chấm mỗi mục 1–5 (5 = tốt nhất) và ghi chú ngắn. Đọc `script_final.md` trước, "
             "đối chiếu `report.md` nếu cần.", "",
             "| Mục | Câu hỏi | Điểm (1–5) | Ghi chú |", "|---|---|---|---|"]
    lines += [f"| {key} | {question} |  |  |" for key, question in REVIEW_QUESTIONS]
    if manifest["profile"].get("plot_recap"):
        lines.append("| Ngôi kể | Ngoài các lời thoại có người nói rõ ràng, người kể có giữ ngôi thứ ba "
                     "từ đầu đến cuối không? |  |  |")
    lines += ["", "Lỗi cụ thể (trích câu trong kịch bản → vì sao sai):", "", "- ", "",
              "Kết luận: ☐ Dùng được ngay ☐ Sửa nhẹ ☐ Sửa nhiều ☐ Không dùng được", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- orchestration


def run(client: LLMClient, scope: StoryScope, profile: NarrativeProfile, out_dir: Path, *,
        facts: Optional[StoryFacts] = None, max_repairs: int = 2, revision_rounds: int = 1,
        revise_severities: Sequence[str] = ("CRITICAL", "HIGH", "MEDIUM"),
        stop_after: str = "revise", resume: bool = False,
        background: Sequence[Chapter] = (), memory: Optional[StoryMemory] = None,
        full_target_units: Optional[int] = None,
        progress: Callable[[str], None] = lambda message: None) -> Dict[str, Any]:
    """`scope` is the episode. `background` are earlier chapters, summarised from memory as a
    recap (never later chapters). With `memory`, chapter briefs are reused across runs."""
    if any(c.order >= scope.first for c in background):
        raise ValueError("recap chapters must precede the episode")
    if full_target_units is not None and (full_target_units < 1 or profile.length_ratio is None):
        raise ValueError("full-target-units needs a positive full length and a ratio profile")
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
        "stage_models": getattr(client, "stage_models", {}),
        "facts_supplied": facts is not None,
        "background_chapters": [c.order for c in background],
        "memory": str(memory.directory) if memory else None,
        "brief_sources": {},
        "settings": {"max_repairs": max_repairs, "revision_rounds": revision_rounds,
                     "revise_severities": list(revise_severities), "stop_after": stop_after},
        "prompt_fingerprints": stages.prompt_fingerprints(),
        "language_checks": stages.audit_coverage(profile.target_language, profile.brief_language,
                                                 scope.source_language),
        "versions": [],
        "status": "RUNNING",
    }
    write_json(out_dir / "run_manifest.json", manifest)

    def finish(status: str, error: Optional[str] = None) -> Dict[str, Any]:
        manifest["status"] = status
        if error:
            manifest["error"] = error
        manifest["model_calls"] = len(log.entries)
        manifest["usage_by_stage_model"] = log.usage_summary()
        manifest["seconds"] = round(time.time() - started, 1)
        write_json(out_dir / "run_manifest.json", manifest)
        calls_path = out_dir / "calls.jsonl"
        mode = "a" if resume and calls_path.exists() else "w"
        with calls_path.open(mode, encoding="utf-8") as handle:
            for entry in log.entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return manifest

    try:
        # Keep stage outputs as plain JSON. The adjacent receipts bind them to this
        # run context and to the actual upstream artifacts each stage consumed.
        context = digest([manifest["pipeline_version"], manifest["prompt_fingerprints"],
                          scope.story_id, scope.source_language, profile.to_dict(),
                          [(c.order, c.document_id, c.version, c.title, c.render())
                           for c in [*background, *scope.chapters]], manifest["scope"],
                          manifest["client"], getattr(client, "temperature", None), max_repairs])
        same_language = (scope.source_language.split("-")[0].lower()
                         == profile.target_language.split("-")[0].lower())
        def model_route(stage: str) -> Any:
            return manifest["stage_models"].get(stage, manifest["client"])

        need_estimate = profile.length_ratio is not None and not same_language and full_target_units is None
        all_briefs: List[Dict[str, Any]] = []
        for chapter in sorted([*background, *scope.chapters], key=lambda c: c.order):
            progress(f"brief: chapter {chapter.order}")

            chapter_facts = facts.for_chapter(chapter.order) if facts else []
            estimate_language = profile.target_language if need_estimate else None
            fingerprint = stages.brief_fingerprint(profile, estimate_language)
            brief_setup = digest([fingerprint, model_route("brief"), scope.source_language, chapter_facts,
                                  stages.known_characters_text(all_briefs)])

            def produce(chapter: Chapter = chapter) -> Dict[str, Any]:
                stale: List[str] = []
                if memory is not None:
                    stored = memory.get_brief(chapter.order, chapter.version, brief_setup)
                    # A stored brief must still pass today's checks: validators added after it
                    # was written (live run 6 reused a brief the new hedge check would reject).
                    stale = stages.brief_semantic_errors(stored, chapter, scope.source_language,
                                                         profile.brief_language) if stored is not None else []
                    if stored is not None and estimate_language and not (
                            type(stored.get("full_target_units_estimate")) is int
                            and stored["full_target_units_estimate"] > 0):
                        stale.append("full_target_units_estimate is missing or invalid")
                    if stored is not None and not stale:
                        manifest["brief_sources"][str(chapter.order)] = "memory"
                        return stored
                    if stale:
                        manifest.setdefault("stale_memory", {})[str(chapter.order)] = stale[:5]
                brief = stages.run_brief(client, scope, chapter, profile, all_briefs, facts, log, max_repairs,
                                         estimate_language)
                manifest["brief_sources"][str(chapter.order)] = "model (memory stale)" if stale else "model"
                if memory is not None:
                    memory.put_brief(chapter.order, chapter.version, brief_setup, brief,
                                     getattr(client, "name", "unknown"))
                return brief

            all_briefs.append(cached(out_dir / "briefs" / f"chapter_{chapter.order:03d}.json", resume,
                                     [context, brief_setup], produce))
        briefs = [b for b in all_briefs if b["chapter_order"] >= scope.first]
        recap = recap_context(all_briefs, scope.first) if background else None
        if recap is not None:
            write_json(out_dir / "memory_recap.json", recap)
        if profile.length_ratio:
            if full_target_units is not None:
                baseline, basis = full_target_units, "user_supplied"
            elif same_language:
                baseline = sum(checks.count_length(p.text, profile.target_language)
                               for chapter in scope.chapters for p in chapter.passages)
                basis = "source_count"
            else:
                baseline = sum(b["full_target_units_estimate"] for b in briefs)
                basis = "estimated_translation"
            manifest["compression"] = {"range": list(profile.length_ratio), "full_target_units": baseline,
                                       "basis": basis, "language": profile.target_language}
            profile = profile.for_full_length(baseline)
            manifest["profile"] = profile.to_dict()
        if stop_after == "brief":
            return finish("STOPPED_AFTER_BRIEF")

        progress("plan")
        plan_inputs = [context, briefs, recap, profile.to_dict(), model_route("plan")]
        plan = cached(out_dir / "plan.json", resume, plan_inputs,
                      lambda: stages.run_plan(client, scope, briefs, profile, log, max_repairs, recap))
        if stop_after == "plan":
            return finish("STOPPED_AFTER_PLAN")

        progress("script v1")
        script_inputs = [plan_inputs, plan, model_route("script")]
        script = cached(out_dir / "script_v1.json", resume, script_inputs,
                        lambda: stages.run_script(client, scope, briefs, plan, profile, log, max_repairs,
                                                  recap))
        (out_dir / "script_v1.md").write_text(script_markdown(script, "v1"), encoding="utf-8")
        critic: Optional[Dict[str, Any]] = None
        version = 1
        if stop_after != "script":
            while True:
                units = review_units(script)
                progress(f"critic v{version}")
                critic = cached(out_dir / f"critic_v{version}.json", resume, [plan_inputs, script, model_route("critic")],
                                lambda: stages.run_critic(client, scope, briefs, units, profile,
                                                          log, max_repairs, version, recap, background))
                audit = stages.strength_audit(critic, briefs, recap, units, profile.target_language,
                                              profile.brief_language)
                audit += stages.hedge_audit(critic, briefs, recap, units, profile.target_language,
                                            profile.brief_language)
                write_json(out_dir / f"strength_audit_v{version}.json", audit)
                problems = stages.findings_for_revision(critic, SEVERITY_ORDER) + audit
                check = checks.check_script(script, profile.min_words, profile.max_words,
                                            profile.target_language)
                manifest["versions"].append({
                    "version": version, "word_count": check["word_count"],
                    "problem_claims": len(problems), "strength_audit": len(audit),
                    "high_or_worse": sum(1 for p in problems if p["severity"] in ("CRITICAL", "HIGH"))})
                to_fix = stages.findings_for_revision(critic, revise_severities) + \
                    [f for f in audit if f["severity"] in revise_severities]
                missing_core = coverage_gate(critic, briefs)["not_cited"] if profile.plot_recap else []
                if stop_after == "critic" or not (to_fix or missing_core) or version > revision_rounds:
                    break
                version += 1
                progress(f"revise -> v{version} ({len(to_fix)} findings)")
                previous, previous_units = script, units
                script = cached(out_dir / f"script_v{version}.json", resume,
                                [script_inputs, previous, to_fix, missing_core, model_route("revise")],
                                lambda: stages.run_revision(client, scope, briefs, plan, previous,
                                                            to_fix, previous_units, profile, log,
                                                            max_repairs, version, recap, missing_core))
                (out_dir / f"script_v{version}.md").write_text(script_markdown(script, f"v{version}"),
                                                              encoding="utf-8")
        final_check = checks.check_script(script, profile.min_words, profile.max_words,
                                          profile.target_language)
        (out_dir / "script_final.md").write_text(script_markdown(script, f"final v{version}"),
                                                 encoding="utf-8")
        final_units = review_units(script)
        final_audit = (stages.strength_audit(critic, briefs, recap, final_units, profile.target_language,
                                             profile.brief_language)
                       + stages.hedge_audit(critic, briefs, recap, final_units, profile.target_language,
                                            profile.brief_language) if critic is not None else [])
        report = gate_report(critic, final_check, briefs, final_audit)
        report["source_hedge_review"] = [
            item for chapter, brief in zip(sorted([*background, *scope.chapters], key=lambda c: c.order), all_briefs)
            if chapter.order >= scope.first
            for item in stages.source_hedge_review(brief, chapter, scope.source_language, profile.brief_language)]
        if "compression" in manifest:
            report["compression"] = {**manifest["compression"],
                                     "actual_ratio": final_check["word_count"] / manifest["compression"]["full_target_units"]}
        report["final_version"] = version
        report["final_check"] = final_check
        write_json(out_dir / "report.json", report)
        status = "COMPLETED" if critic is not None else "STOPPED_AFTER_SCRIPT"
        finish(status)
        (out_dir / "report.md").write_text(report_markdown(manifest, report), encoding="utf-8")
        (out_dir / "review_form.md").write_text(review_form(manifest, plan, script), encoding="utf-8")
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
    parser.add_argument("--recap", action="store_true",
                        help="episode mode: chapters before --chapters become recap/callback background")
    parser.add_argument("--memory", default=str(DEFAULT_MEMORY_ROOT),
                        help="story memory directory; chapter briefs are reused across runs")
    parser.add_argument("--no-memory", action="store_true", help="do not read or write story memory")
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE_PATH), help="Narrative Profile YAML")
    parser.add_argument("--min-words", type=int, default=None, help="override profile minimum length")
    parser.add_argument("--max-words", type=int, default=None, help="override profile maximum length")
    parser.add_argument("--full-target-units", type=int,
                        help="length of an unabridged target-language version of just this episode; "
                             "Vietnamese counts whitespace-separated units")
    parser.add_argument("--stage-model", action="append", default=[], metavar="STAGE=MODEL[,FALLBACK]",
                        help="override a stage's Gemini model chain; repeat for multiple stages")
    parser.add_argument("--model", default=None,
                        help="Gemini model id, or a comma-separated fallback chain tried in order when a "
                             "model is overloaded or out of quota (default: GEMINI_MODEL)")
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
    parser = build_parser()
    args = parser.parse_args(argv)
    routes = {}
    for spec in args.stage_model:
        stage, sep, chain = spec.partition("=")
        if stage not in STAGES or not sep or not all(m.strip() for m in chain.split(",")) or stage in routes:
            parser.error(f"invalid --stage-model {spec!r}, expected a unique STAGE=MODEL[,FALLBACK]")
        routes[stage] = chain
    start, end = parse_range(args.chapters)
    background: List[Chapter] = []
    if args.recap and start > 1:
        full = load_scope(args.manifest, (1, end), args.source_root)
        background = [c for c in full.chapters if c.order < start]
        scope = StoryScope(full.story_id, full.source_language, tuple(c for c in full.chapters if c.order >= start))
    else:
        scope = load_scope(args.manifest, (start, end), args.source_root)
    memory = None if args.no_memory else StoryMemory(args.memory, scope.story_id)
    profile = load_profile(args.profile)
    if args.min_words is not None or args.max_words is not None:
        profile = profile.with_length(args.min_words, args.max_words)
    if args.full_target_units is not None and (args.full_target_units < 1 or profile.length_ratio is None):
        parser.error("--full-target-units requires a positive count and ratio-based length")
    facts = StoryFacts.load(args.facts) if args.facts else None

    from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError
    from tools.story_pipeline.llm import GeminiLLMClient
    try:
        client = GeminiLLMClient(args.model, stage_models=routes, dotenv_path=args.dotenv, temperature=args.temperature)
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
                   stop_after=args.stop_after, resume=resume, background=background, memory=memory,
                   full_target_units=args.full_target_units,
                   progress=lambda message: print(f"  ... {message}", flush=True))
    print(f"status: {manifest['status']}  calls: {manifest['model_calls']}  seconds: {manifest['seconds']}")
    if manifest.get("error"):
        print(f"error: {manifest['error']}")
    if (out_dir / "report.md").exists():
        print(f"report: {out_dir / 'report.md'}")
    return 0 if manifest["status"] != "FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
