"""Run the story pipeline end to end: Brief -> Plan -> Script -> Critic -> Revision.

Usage (from the repository root, with Gemini keys in .env):

    python -m tools.story_pipeline.run_pipeline --chapters 1 --model <gemini-model>

Outputs go to .local/story_pipeline_runs/<run id>/ (git-ignored). Use --resume <run dir>
to reuse stage outputs already written there (saves API calls after a failure).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.story_memory import glossary_v0  # noqa: E402
from tools.story_memory.memory_v0 import StoryMemory, build_roster, recap_context  # noqa: E402
from tools.story_pipeline import PIPELINE_VERSION, checks, lexicon, review_page, review_summary, stages  # noqa: E402
from tools.story_pipeline.facts import StoryFacts  # noqa: E402
from tools.story_pipeline.llm import CallLog, LLMClient, StageFailed  # noqa: E402
from tools.story_pipeline.profile import DEFAULT_PROFILE_PATH, NarrativeProfile, load_profile  # noqa: E402
from tools.story_pipeline.source import Chapter, StoryScope, layout_warnings, load_scope, parse_range  # noqa: E402

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
        _usage_line(manifest.get("usage")),
        f"- Trạng thái: **{manifest['status']}**",
        _language_line(manifest.get("language_checks")),
        *[f"- **Cảnh báo nguồn:** {warning}" for warning in manifest.get("source_warnings", [])],
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
    if report.get("source_hedge_review"):
        lines += ["", "## Cần người xem: brief có thể đã bỏ mất rào đón của nguồn", "",
                  "Đoạn nguồn được trích có từ rào đón (lời đồn, vẻ bề ngoài, phỏng đoán, ẩn dụ) "
                  "nhưng mục brief viết như sự thật. Khoảng một nửa là đúng; phần còn lại là rào đón "
                  "nói về chuyện khác trong cùng đoạn. Không tự động sửa.", ""]
        for item in report["source_hedge_review"]:
            marks = ", ".join(f"{phrase} ({pid})" for _, phrase, pid in item["source_hedges"])
            lines.append(f"- {item['ref']}: {item['text'][:160]} — nguồn: {marks}")
    if report.get("source_strength_review"):
        lines += ["", "## Cần người xem: brief có thể mạnh hơn nguồn", "",
                  "Mục brief có từ tăng mức độ (luôn luôn, chắc chắn, mọi người, nổi tiếng...) mà các passage "
                  "được trích không có. Khoảng 4/10 là đúng; phần còn lại là cách nói nguồn có nhưng bộ từ vựng "
                  "chưa biết. Lỗi ở brief thì critic không thấy, vì critic so kịch bản với brief. Không tự động sửa.", ""]
        for item in report["source_strength_review"]:
            lines.append(f"- {item['ref']}: {item['text'][:160]} — từ: {', '.join(item['phrases'])} "
                         f"(nguồn: {', '.join(item['evidence'])})")
    if report.get("owner_review"):
        status_vi = {"applied": "đã sửa", "applied_but_flagged": "đã sửa, nhưng đoạn này vẫn bị báo lỗi (xem dưới)",
                     "still_present": "CÂU VẪN CÒN", "not_found": "KHÔNG TÌM THẤY câu này"}
        lines += ["", "## Góp ý của người duyệt", "",
                  "Các lỗi trong phiếu chấm được sửa bằng một vòng patch, rồi các đoạn đã đổi được kiểm lại.", ""]
        for item in report["owner_review"]:
            lines.append(f"- [{status_vi[item['status']]}] ({item['unit_id'] or '?'}) \"{item['quote']}\" → "
                         f"{item['why'] or ''}")
    if report.get("brief_gaps"):
        lines += ["", "## Brief bỏ sót (critic báo nhầm, nguồn xác nhận)", "",
                  "Critic so kịch bản với brief nên báo các chi tiết này là bịa; bước đối chiếu nguồn tìm thấy "
                  "chúng trong nguyên văn (mọi lần đối chiếu đều đồng ý), nên chúng không bị sửa và không tính "
                  "vào gate. Nên xem lại passage được dẫn.", ""]
        for gap in report["brief_gaps"]:
            lines.append(f"- ({gap['unit_id']}) {gap['claim']} — nguồn: {', '.join(gap['passage_ids'])}: "
                         f"{gap['source_explanation']}")
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


USAGE_FIELDS = {"prompt": "prompt_token_count", "output": "candidates_token_count",
                "thoughts": "thoughts_token_count", "total": "total_token_count"}


def _glossary_findings(units: Sequence[Dict[str, str]], glossary: Optional[Dict[str, Any]],
                       roster: Dict[str, Any], target_language: str) -> List[Dict[str, Any]]:
    """Name spellings and pronouns that differ from the story's glossary."""
    if not glossary:
        return []
    lex = lexicon.load(target_language)
    pronouns = lex.third_person_pronouns if lex else ()
    exceptions = lex.pronoun_exceptions if lex else ()
    return glossary_v0.check(units, glossary, roster) + glossary_v0.pronoun_check(units, glossary, pronouns, exceptions)


def usage_summary(entries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Calls and tokens per stage, from the provider's usage metadata (missing counts as 0)."""
    stages_: Dict[str, Dict[str, int]] = {}
    for entry in entries:
        row = stages_.setdefault(entry.get("stage", "?"), {"calls": 0, **{k: 0 for k in USAGE_FIELDS}})
        row["calls"] += 1
        usage = entry.get("usage") or {}
        for key, field in USAGE_FIELDS.items():
            row[key] += int(usage.get(field) or 0)
    total = {"calls": sum(r["calls"] for r in stages_.values()),
             **{k: sum(r[k] for r in stages_.values()) for k in USAGE_FIELDS}}
    return {"by_stage": stages_, "total": total}


def _usage_line(usage: Optional[Dict[str, Any]]) -> str:
    if not usage or not usage["total"]["calls"]:
        return "- Token: không có số liệu"
    total = usage["total"]
    biggest = max(usage["by_stage"].items(), key=lambda item: item[1]["total"])
    return (f"- Token: {total['total']:,} tổng ({total['prompt']:,} vào, {total['output']:,} ra, "
            f"{total['thoughts']:,} suy nghĩ) — tốn nhất: {biggest[0]} ({biggest[1]['total']:,})")


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


# --------------------------------------------------------------------------- owner review

OWNER_REVIEW_FILE = "owner_review.json"


def _form_path(out_dir: Path, form: Path | str) -> Path:
    form = Path(form)
    return form if form.is_absolute() or form.is_file() else out_dir / form


def pending_owner_errors(out_dir: Path, form: Path | str = "review_form.md") -> List[Dict[str, Optional[str]]]:
    """Quoted errors in the run's filled review form that no correction round has applied."""
    path = _form_path(out_dir, form)
    if not path.is_file():
        return []
    errors = [e for e in review_summary.parse_errors(path.read_text(encoding="utf-8")) if e["quote"]]
    done = _owner_rounds(out_dir)
    return [] if any(r["errors"] == errors for r in done) else errors


def _owner_rounds(out_dir: Path) -> List[Dict[str, Any]]:
    path = out_dir / OWNER_REVIEW_FILE
    return json.loads(path.read_text(encoding="utf-8"))["rounds"] if path.is_file() else []


def _last_version(out_dir: Path) -> int:
    versions = [int(m.group(1)) for p in out_dir.glob("script_v*.json")
                if (m := re.fullmatch(r"script_v(\d+)\.json", p.name))]
    return max(versions, default=0)


def plan_owner_rounds(out_dir: Path, form: Optional[Path | str]) -> List[Dict[str, Any]]:
    """Correction rounds from the owner's review, recorded in owner_review.json so a later
    resume replays them from the saved scripts. A new round starts after the last saved
    version when the form holds quoted errors that no earlier round applied."""
    rounds = _owner_rounds(out_dir)
    if form is not None:
        errors = pending_owner_errors(out_dir, form)
        last = _last_version(out_dir)
        if errors and last:
            rounds.append({"after_version": last, "form": str(_form_path(out_dir, form)), "errors": errors})
            write_json(out_dir / OWNER_REVIEW_FILE, {"rounds": rounds})
    return rounds


def write_review_form(out_dir: Path, text: str) -> None:
    """Write a fresh review form, keeping a filled one as review_form_reviewed_N.md: a resumed
    or corrected run must never erase the owner's scores."""
    path = out_dir / "review_form.md"
    if path.is_file():
        old = path.read_text(encoding="utf-8")
        parsed = review_summary.parse_form(old)
        if old != text and (parsed["reviewer"] or any(e["quote"] for e in review_summary.parse_errors(old))):
            index = 1
            while (out_dir / f"review_form_reviewed_{index}.md").exists():
                index += 1
            path.rename(out_dir / f"review_form_reviewed_{index}.md")
    path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- orchestration


def run(client: LLMClient, scope: StoryScope, profile: NarrativeProfile, out_dir: Path, *,
        facts: Optional[StoryFacts] = None, max_repairs: int = 2, revision_rounds: int = 1,
        revise_severities: Sequence[str] = ("CRITICAL", "HIGH", "MEDIUM"),
        stop_after: str = "revise", resume: bool = False,
        background: Sequence[Chapter] = (), memory: Optional[StoryMemory] = None,
        source_check: bool = True, source_check_samples: int = 1, full_revision_rounds: int = 1,
        full_recheck: bool = False, source_check_chunk: int = 4, owner_review: Optional[Path | str] = None,
        invocation: Optional[Dict[str, Any]] = None, progress: Callable[[str], None] = lambda message: None) -> Dict[str, Any]:
    """`scope` is the episode. `background` are earlier chapters, summarised from memory as a
    recap (never later chapters). With `memory`, chapter briefs are reused across runs."""
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
        "background_chapters": [c.order for c in background],
        "memory": str(memory.directory) if memory else None,
        "brief_sources": {},
        "settings": {"max_repairs": max_repairs, "revision_rounds": revision_rounds,
                     "revise_severities": list(revise_severities), "stop_after": stop_after,
                     "source_check": source_check, "source_check_samples": source_check_samples,
                     "full_recheck": full_recheck, "source_check_chunk": source_check_chunk,
                     "full_revision_rounds": full_revision_rounds},
        "invocation": invocation,
        "prompt_fingerprints": stages.prompt_fingerprints(),
        "language_checks": stages.audit_coverage(profile.target_language, profile.brief_language,
                                                 scope.source_language),
        "source_warnings": layout_warnings([*background, *scope.chapters]),
        "versions": [],
        "status": "RUNNING",
    }
    write_json(out_dir / "run_manifest.json", manifest)

    def finish(status: str, error: Optional[str] = None) -> Dict[str, Any]:
        manifest["status"] = status
        if error:
            manifest["error"] = error
        manifest["model_calls"] = len(log.entries)
        manifest["usage"] = usage_summary(log.entries)
        manifest["seconds"] = round(time.time() - started, 1)
        write_json(out_dir / "run_manifest.json", manifest)
        calls_path = out_dir / "calls.jsonl"
        mode = "a" if resume and calls_path.exists() else "w"
        with calls_path.open(mode, encoding="utf-8") as handle:
            for entry in log.entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return manifest

    try:
        fingerprint = stages.brief_fingerprint(profile, scope.source_language)
        all_briefs: List[Dict[str, Any]] = []
        for chapter in sorted([*background, *scope.chapters], key=lambda c: c.order):
            progress(f"brief: chapter {chapter.order}")

            def produce(chapter: Chapter = chapter) -> Dict[str, Any]:
                stale: List[str] = []
                if memory is not None:
                    stored = memory.get_brief(chapter.order, chapter.version, fingerprint)
                    # A stored brief must still pass today's checks: validators added after it
                    # was written (live run 6 reused a brief the new hedge check would reject).
                    stale = stages.brief_semantic_errors(stored, chapter, scope.source_language,
                                                         profile.brief_language) if stored is not None else []
                    if stored is not None and not stale:
                        manifest["brief_sources"][str(chapter.order)] = "memory"
                        return stored
                    if stale:
                        manifest.setdefault("stale_memory", {})[str(chapter.order)] = stale[:5]
                brief = stages.run_brief(client, scope, chapter, profile, all_briefs, facts, log, max_repairs)
                manifest["brief_sources"][str(chapter.order)] = "model (memory stale)" if stale else "model"
                if memory is not None:
                    memory.put_brief(chapter.order, chapter.version, fingerprint, brief,
                                     getattr(client, "name", "unknown"))
                return brief

            all_briefs.append(cached(out_dir / "briefs" / f"chapter_{chapter.order:03d}.json", resume, produce))
        briefs = [b for b in all_briefs if b["chapter_order"] >= scope.first]
        recap = recap_context(all_briefs, scope.first) if background else None
        if recap is not None:
            write_json(out_dir / "memory_recap.json", recap)
        if stop_after == "brief":
            return finish("STOPPED_AFTER_BRIEF")

        # One spelling per character (tools/story_memory/glossary_v0.py), kept with the memory.
        roster = build_roster(all_briefs)
        glossary = None
        writer_profile = profile
        if memory is not None:
            glossary_file = memory.directory.parent / "glossary.yaml"
            glossary = glossary_v0.sync(glossary_file, roster)
            manifest["glossary"] = {"path": str(glossary_file), "characters": len(glossary["characters"]),
                                    "confirmed": glossary_v0.confirmed(glossary)}
            name_rules = glossary_v0.rules(glossary)
            if name_rules:
                writer_profile = dataclasses.replace(profile, name_policy=f"{profile.name_policy}\n{name_rules}")

        progress("plan")
        plan = cached(out_dir / "plan.json", resume,
                      lambda: stages.run_plan(client, scope, briefs, profile, log, max_repairs, recap))
        if stop_after == "plan":
            return finish("STOPPED_AFTER_PLAN")

        progress("script v1")
        script = cached(out_dir / "script_v1.json", resume,
                        lambda: stages.run_script(client, scope, briefs, plan, writer_profile, log, max_repairs,
                                                  recap))
        (out_dir / "script_v1.md").write_text(script_markdown(script, "v1"), encoding="utf-8")
        declared_pronouns = script.get("pronouns")  # a full revision may drop them
        critic: Optional[Dict[str, Any]] = None
        verified: List[Dict[str, Any]] = []
        passages = {p.passage_id: p.text for c in [*background, *scope.chapters] for p in c.passages}
        version = 1
        owner_rounds = plan_owner_rounds(out_dir, owner_review) if resume else []
        owner_findings: List[Dict[str, Any]] = []
        owner_unplaced: List[Dict[str, Optional[str]]] = []
        brief_gaps: List[Dict[str, Any]] = []
        checked_units: List[Dict[str, str]] = []  # the previous version's paragraphs
        if stop_after != "script":
            while True:
                units = checks.split_units(checks.script_text(script))
                # Paragraphs a patch round left untouched keep their earlier verdicts; only
                # changed ones go to the critic and the source check again.
                carried = {} if full_recheck or critic is None else stages.unchanged_units(units, checked_units)
                fresh_units = [u for u in units if u["unit_id"] not in carried]
                progress(f"critic v{version} ({len(fresh_units)}/{len(units)} paragraphs)")
                previous_critic = critic
                critic = cached(out_dir / f"critic_v{version}.json", resume,
                                lambda: stages.merge_critic(
                                    units, stages.run_critic(client, scope, briefs, fresh_units, profile, log,
                                                             max_repairs, version, recap) if fresh_units else None,
                                    previous_critic, carried))
                audit = stages.strength_audit(critic, briefs, recap, units, profile.target_language,
                                              profile.brief_language)
                audit += stages.hedge_audit(critic, briefs, recap, units, profile.target_language,
                                            profile.brief_language)
                audit += stages.attribution_audit(critic, briefs, units, passages, profile.target_language,
                                                  profile.brief_language)
                audit += _glossary_findings(units, glossary, roster, profile.target_language)
                carried_verified = stages.carry_findings(verified, carried)
                carried_gaps = stages.carry_findings(brief_gaps, carried)
                verified, brief_gaps = [], []
                if source_check and fresh_units:
                    progress(f"source check v{version}")
                    flags = [f for f in stages.critic_flags(critic) if f["unit_id"] not in carried]
                    samples, results = [], []
                    # A few paragraphs per call: whole-script calls missed most defects that
                    # calls on four paragraphs found (run 17 v1: 2 against 7).
                    size = source_check_chunk if source_check_chunk > 0 else len(fresh_units)
                    chunks = [fresh_units[i:i + size] for i in range(0, len(fresh_units), size)]
                    skipped = False
                    for index, chunk in enumerate(chunks, start=1):
                        ids = {u["unit_id"] for u in chunk}
                        chunk_flags = [f for f in flags if f["unit_id"] in ids]
                        part = index if len(chunks) > 1 else 0
                        for sample in range(1, max(1, source_check_samples) + 1):
                            name = (f"source_check_v{version}" + (f"_c{part}" if part else "")
                                    + (f"_s{sample}" if sample > 1 else "") + ".json")
                            try:
                                result = cached(out_dir / name, resume,
                                                lambda: stages.run_source_check(client, scope, chunk, profile, log,
                                                                                max_repairs, version, sample,
                                                                                chunk_flags, part))
                            except StageFailed as exc:
                                # A second verifier that cannot answer must not sink the episode
                                # (season S2): record it and go on with the other checks.
                                manifest.setdefault("source_check_failed", []).append(
                                    {"version": version, "chunk": part, "sample": sample, "error": str(exc)[:300]})
                                continue
                            if result is None:
                                manifest["source_check_skipped"] = (f"episode source is longer than "
                                                                    f"{stages.SOURCE_CHECK_MAX_CHARS} characters")
                                skipped = True
                                break
                            samples.append(stages.source_check_findings(result, passages))
                            results.append(result)
                        if skipped:
                            break
                    verified = stages.merge_source_findings(samples)
                    # Critic findings the source does support are gaps in the brief, not
                    # errors in the script: they leave revision and the gates.
                    brief_gaps = stages.overturned_flags(results, flags)
                verified += carried_verified
                brief_gaps += carried_gaps
                if brief_gaps:
                    critic = stages.without_claims(critic, brief_gaps)
                checked_units = units
                audit += verified
                write_json(out_dir / f"strength_audit_v{version}.json", audit)
                problems = stages.findings_for_revision(critic, SEVERITY_ORDER) + audit
                check = checks.check_script(script, profile.min_words, profile.max_words,
                                            profile.target_language)
                manifest["versions"].append({
                    "version": version, "word_count": check["word_count"],
                    "problem_claims": len(problems), "strength_audit": len(audit),
                    "critic_overturned": len(brief_gaps), "rechecked_units": len(fresh_units),
                    "high_or_worse": sum(1 for p in problems if p["severity"] in ("CRITICAL", "HIGH"))})
                to_fix = stages.findings_for_revision(critic, revise_severities) + \
                    [f for f in audit if f["severity"] in revise_severities]
                # The owner's quoted errors are fixed in a patch round after the version they reviewed.
                owner_round = next((r for r in owner_rounds if r["after_version"] == version), None)
                located: List[Dict[str, Any]] = []
                if owner_round:
                    located, unplaced = stages.locate_owner_errors(owner_round["errors"], units)
                    owner_findings += located
                    owner_unplaced += unplaced
                    to_fix = located + to_fix
                if stop_after == "critic" or not to_fix or (version > revision_rounds and not located):
                    break
                version += 1
                previous, previous_units = script, units
                # Later rounds edit only the sentences at fault: a full rewrite to fix the last
                # few findings put new errors into correct text (live run 13, v2).
                patching = bool(located) or version - 1 > full_revision_rounds
                progress(f"{'patch' if patching else 'revise'} -> v{version} ({len(to_fix)} findings)")
                script = cached(out_dir / f"script_v{version}.json", resume,
                                lambda: stages.run_patch(client, scope, briefs, previous, to_fix, previous_units,
                                                         writer_profile, log, max_repairs, version) if patching
                                else stages.run_revision(client, scope, briefs, plan, previous,
                                                         to_fix, previous_units, writer_profile, log,
                                                         max_repairs, version, recap))
                (out_dir / f"script_v{version}.md").write_text(script_markdown(script, f"v{version}"),
                                                              encoding="utf-8")
        final_check = checks.check_script(script, profile.min_words, profile.max_words,
                                          profile.target_language)
        (out_dir / "script_final.md").write_text(script_markdown(script, f"final v{version}"),
                                                 encoding="utf-8")
        # The narration alone (no comment line, no Markdown), ready for a voice-over tool.
        (out_dir / "script_final.txt").write_text(checks.script_text(script).strip() + "\n", encoding="utf-8")
        final_units = checks.split_units(checks.script_text(script))
        final_audit = (stages.strength_audit(critic, briefs, recap, final_units, profile.target_language,
                                             profile.brief_language)
                       + stages.hedge_audit(critic, briefs, recap, final_units, profile.target_language,
                                            profile.brief_language)
                       + stages.attribution_audit(critic, briefs, final_units, passages, profile.target_language,
                                                  profile.brief_language)
                       + _glossary_findings(final_units, glossary, roster, profile.target_language)
                       + verified if critic is not None else [])
        if glossary is not None:
            lex = lexicon.load(profile.target_language)
            adopted = glossary_v0.adopt_pronouns(memory.directory.parent / "glossary.yaml", script.get("pronouns") or declared_pronouns,
                                                 lex.third_person_pronouns if lex else (), out_dir.name)
            if adopted:
                manifest["glossary"]["pronouns_adopted"] = adopted
        report = gate_report(critic, final_check, briefs, final_audit)
        report["source_hedge_review"] = [
            item for chapter, brief in zip(sorted([*background, *scope.chapters], key=lambda c: c.order), all_briefs)
            if chapter.order >= scope.first
            for item in stages.source_hedge_review(brief, chapter, scope.source_language, profile.brief_language)]
        report["source_strength_review"] = [
            item for chapter, brief in zip(sorted([*background, *scope.chapters], key=lambda c: c.order), all_briefs)
            if chapter.order >= scope.first
            for item in stages.source_strength_review(brief, chapter, scope.source_language, profile.brief_language)]
        report["brief_gaps"] = [{k: g[k] for k in ("unit_id", "claim", "claim_type", "explanation",
                                                    "source_explanation", "passage_ids")} for g in brief_gaps]
        final_text = stages._squash(checks.script_text(script))
        # "applied" only means the quoted sentence is gone; a rewrite can still be wrong
        # (live trial: one of five), so a paragraph with findings left is called out.
        flagged = {f["unit_id"] for f in report["findings"]}

        def owner_status(finding: Dict[str, Any]) -> str:
            if stages._squash(finding["claim"]) in final_text:
                return "still_present"
            return "applied_but_flagged" if finding["unit_id"] in flagged else "applied"

        report["owner_review"] = [
            {"quote": f["claim"], "why": f["explanation"], "unit_id": f["unit_id"], "status": owner_status(f)}
            for f in owner_findings] + [{"quote": e["quote"], "why": e["why"], "unit_id": None,
                                         "status": "not_found"} for e in owner_unplaced]
        if owner_rounds:
            manifest["owner_review"] = {"rounds": len(owner_rounds), **{
                status: sum(1 for o in report["owner_review"] if o["status"] == status)
                for status in ("applied", "applied_but_flagged", "still_present", "not_found")}}
        report["final_version"] = version
        report["final_check"] = final_check
        write_json(out_dir / "report.json", report)
        status = "COMPLETED" if critic is not None else "STOPPED_AFTER_SCRIPT"
        finish(status)
        (out_dir / "report.md").write_text(report_markdown(manifest, report), encoding="utf-8")
        write_review_form(out_dir, review_form(manifest))
        (out_dir / "review.html").write_text(
            review_page.render_review_page(manifest, report, final_units, critic, all_briefs, passages,
                                           REVIEW_QUESTIONS), encoding="utf-8")
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
    parser.add_argument("--full-revision-rounds", type=int, default=1,
                        help="revision rounds that may rewrite the script; later rounds only patch sentences")
    parser.add_argument("--source-check-samples", type=int, default=1,
                        help="independent source-check calls per group of paragraphs; their findings are pooled")
    parser.add_argument("--source-check-chunk", type=int, default=4,
                        help="paragraphs per source-check call (0: the whole script in one call)")
    parser.add_argument("--apply-review", nargs="?", const="review_form.md", default=None, metavar="FORM",
                        help="with --resume: fix the quoted errors of a filled review form (default: the run's "
                             "review_form.md) in one patch round, then recheck the changed paragraphs")
    parser.add_argument("--full-recheck", action="store_true",
                        help="send every paragraph to the critic and the source check in every version "
                             "(default: only paragraphs that changed since the previous version)")
    parser.add_argument("--no-source-check", action="store_true",
                        help="skip the second verifier that reads the script against the source text")
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE_PATH), help="Narrative Profile YAML")
    parser.add_argument("--min-words", type=int, default=None, help="override profile minimum length")
    parser.add_argument("--max-words", type=int, default=None, help="override profile maximum length")
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


def episode_scope(manifest_path: Path | str, start: int, end: int, source_root: Optional[str] = None,
                  recap: bool = False) -> Tuple[StoryScope, List[Chapter]]:
    """The episode's chapters, and in recap mode the earlier chapters as background."""
    if recap and start > 1:
        full = load_scope(manifest_path, (1, end), source_root)
        background = [c for c in full.chapters if c.order < start]
        scope = StoryScope(full.story_id, full.source_language, tuple(c for c in full.chapters if c.order >= start))
        return scope, background
    return load_scope(manifest_path, (start, end), source_root), []


def make_client(args: argparse.Namespace) -> Optional[LLMClient]:
    """The Gemini client for the CLI, or None (with a message) when keys are missing."""
    from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError
    from tools.story_pipeline.llm import GeminiLLMClient
    try:
        return GeminiLLMClient(args.model, dotenv_path=args.dotenv, temperature=args.temperature)
    except GeminiConfigError as exc:
        print(f"config error: {exc}. Copy .env.example to .env and fill GEMINI_API_KEY_1 "
              f"(and GEMINI_MODEL or --model).", file=sys.stderr)
        return None


def run_options(args: argparse.Namespace) -> Dict[str, Any]:
    """Keyword arguments for `run` taken from the shared command-line options."""
    return {"max_repairs": args.max_repairs, "revision_rounds": args.revision_rounds,
            "revise_severities": [s.strip() for s in args.revise_severities.split(",") if s.strip()],
            "stop_after": args.stop_after, "source_check": not args.no_source_check,
            "source_check_samples": args.source_check_samples, "source_check_chunk": args.source_check_chunk,
            "full_revision_rounds": args.full_revision_rounds, "full_recheck": args.full_recheck,
            "owner_review": args.apply_review}


# Options a resumed run takes from its own manifest unless given again on the command line.
RESUMABLE_OPTIONS = ("manifest", "source_root", "chapters", "recap", "memory", "no_memory", "full_revision_rounds",
                     "source_check_samples", "source_check_chunk", "full_recheck", "no_source_check", "profile",
                     "min_words", "max_words", "model", "temperature", "facts", "max_repairs", "revision_rounds",
                     "revise_severities", "stop_after")


def invocation_of(args: argparse.Namespace) -> Dict[str, Any]:
    return {key: getattr(args, key) for key in RESUMABLE_OPTIONS if hasattr(args, key)}


def given_options(parser: argparse.ArgumentParser, argv: Optional[List[str]]) -> Set[str]:
    """The options actually typed on the command line (not filled from defaults)."""
    for action in parser._actions:
        action.default = argparse.SUPPRESS
    return set(vars(parser.parse_args(argv)))


def _legacy_invocation(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """What a run made before invocations were recorded can still tell about its options."""
    chapters = manifest["scope"]["chapters"]
    settings = manifest.get("settings", {})
    client = manifest.get("client", "")
    out: Dict[str, Any] = {"chapters": f"{chapters[0]}-{chapters[-1]}",
                           "recap": bool(manifest.get("background_chapters")),
                           "min_words": manifest["profile"].get("min_words"),
                           "max_words": manifest["profile"].get("max_words")}
    if client.startswith("gemini:"):
        out["model"] = client.split(":", 1)[1]
    if settings:
        out.update(max_repairs=settings["max_repairs"], revision_rounds=settings["revision_rounds"],
                   revise_severities=",".join(settings["revise_severities"]), stop_after=settings["stop_after"],
                   no_source_check=not settings.get("source_check", True),
                   source_check_samples=settings.get("source_check_samples", 2),
                   # Runs before grouping checked the whole script in one call.
                   source_check_chunk=settings.get("source_check_chunk", 0),
                   full_revision_rounds=settings.get("full_revision_rounds", 1),
                   full_recheck=settings.get("full_recheck", False))
    return out


def restore_invocation(args: argparse.Namespace, given: Set[str], run_dir: Path) -> List[str]:
    """Fill the options a resumed run was started with, except those given again; returns
    the names restored. A resume with other check settings would redo stages it has saved."""
    path = run_dir / "run_manifest.json"
    if not path.is_file():
        return []
    manifest = json.loads(path.read_text(encoding="utf-8"))
    recorded = manifest.get("invocation") or _legacy_invocation(manifest)
    restored = []
    for key, value in recorded.items():
        if key in RESUMABLE_OPTIONS and key not in given and getattr(args, key, value) != value:
            setattr(args, key, value)
            restored.append(key)
    return restored


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.resume:
        restored = restore_invocation(args, given_options(build_parser(), argv), Path(args.resume))
        if restored:
            print(f"resume: using the run's own {', '.join(restored)}", flush=True)
    start, end = parse_range(args.chapters)
    scope, background = episode_scope(args.manifest, start, end, args.source_root, args.recap)
    memory = None if args.no_memory else StoryMemory(args.memory, scope.story_id)
    profile = load_profile(args.profile).with_length(args.min_words, args.max_words)
    facts = StoryFacts.load(args.facts) if args.facts else None
    client = make_client(args)
    if client is None:
        return 2

    if args.resume:
        out_dir, resume = Path(args.resume), True
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = Path(args.out) if args.out else DEFAULT_OUT_ROOT / f"{stamp}_ch{scope.first}-{scope.last}"
        resume = False
    print(f"run dir: {out_dir}", flush=True)
    for warning in layout_warnings([*background, *scope.chapters]):
        print(f"warning: {warning}", flush=True)
    manifest = run(client, scope, profile, out_dir, facts=facts, resume=resume, background=background,
                   memory=memory, progress=lambda message: print(f"  ... {message}", flush=True),
                   invocation=invocation_of(args), **run_options(args))
    print(f"status: {manifest['status']}  calls: {manifest['model_calls']}  seconds: {manifest['seconds']}")
    if manifest.get("error"):
        print(f"error: {manifest['error']}")
    if (out_dir / "report.md").exists():
        print(f"report: {out_dir / 'report.md'}")
    return 0 if manifest["status"] != "FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
