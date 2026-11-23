"""Script Quality Gate review kit: a contract-complete review form per script, the verdict it
implies, and the gate result over the protocol's sample (M9_SCRIPT_QUALITY_GATE_PROTOCOL/v0).

    python -m tools.story_pipeline.gate_review lock <season dir> --manifest M --profile P --last-chapter 17
    python -m tools.story_pipeline.gate_review form <run or season dir> ...   # write gate_review_form.md
    python -m tools.story_pipeline.gate_review score <form or dir> ...        # verdict per form
    python -m tools.story_pipeline.gate_review summary <form or dir> ... [--out DIR]

The form follows SCRIPT_QUALITY_CONTRACT/v0 (sections 15-18). The request record and the
pipeline's own remaining findings are filled in; the critic's findings are candidates that
the reviewer confirms or rejects. Gate statuses and both verdicts are computed from the
form, never typed: a confirmed HIGH or CRITICAL finding fails its gate, a MEDIUM one makes
it conditional, and a semantic gate the reviewer has not audited is not determined. Only a
human reviewer's form yields an official PASS or PASS_WITH_MINOR_EDITS (contract section 16).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import yaml

REPO = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO / "benchmarks" / "m1_script_quality" / "SCRIPT_QUALITY_CONTRACT_V0.yaml"
FORM_NAME = "gate_review_form.md"
RESULT_NAME = "gate_review_result.json"
FORM_VERSION = "GATE_REVIEW_FORM/v0"
PROTOCOL_ID = "M9_SCRIPT_QUALITY_GATE_PROTOCOL/v0"
REQUIRED_SCRIPTS = 4          # protocol: four episodes, chapters 6-17
PASS_FRACTION = 0.75          # protocol: at least 75% PASS or PASS_WITH_MINOR_EDITS

# Short code used in the form, gate id, Vietnamese label.
GATES: Tuple[Tuple[str, str, str], ...] = (
    ("FACTUAL", "GATE_FACTUAL_GROUNDING", "Đúng sự thật trong phạm vi nguồn"),
    ("EPISTEMIC", "GATE_EPISTEMIC_INTEGRITY", "Giữ đúng mức chắc chắn và nguồn của thông tin"),
    ("TEMPORAL", "GATE_TEMPORAL_STATE_INTEGRITY", "Đúng trình tự, trạng thái, quan hệ"),
    ("SPOILER", "GATE_SPOILER_DISCIPLINE", "Không lộ gì ngoài phạm vi"),
    ("COVERAGE", "GATE_NECESSARY_COVERAGE", "Không thiếu điều người xem cần biết"),
    ("OUTPUT", "GATE_OUTPUT_INTEGRITY", "Bản giao dùng được (ngôn ngữ, không rác)"),
    ("REQUEST", "GATE_REQUEST_COMPLIANCE", "Đúng yêu cầu (độ dài, phạm vi)"),
)
DIMENSION_LABELS: Dict[str, Tuple[str, str]] = {
    "HOOK_STRENGTH": ("Mở đầu", "1: không có lý do nghe tiếp, hoặc gây hiểu lầm · 3: rõ nhưng chung chung · "
                      "5: riêng cho truyện này, đúng profile, hút người nghe một cách trung thực"),
    "NARRATIVE_FLOW": ("Mạch kể", "1: kể lại theo thứ tự nguồn hoặc nhảy khó hiểu · 3: hiểu được, vài đoạn chuyển "
                       "cần sửa · 5: có cấu trúc chủ ý, luôn theo dõi được dòng thời gian"),
    "PACING": ("Nhịp độ", "1: độn chữ nhiều hoặc cao trào bị vội · 3: không đều ở vài chỗ · "
               "5: thời lượng luôn tương xứng với tầm quan trọng"),
    "EMOTIONAL_IMPACT": ("Cảm xúc", "1: hụt hoặc thổi phồng quá chất liệu · 3: có nhưng chưa chạm · "
                         "5: chạm đúng mức chất liệu cho phép"),
    "HUMOR_COMMENTARY_QUALITY": ("Hài hước, bình luận", "1: chung chung, lệch giọng hoặc lấn át · 3: chấp nhận "
                                 "được, chưa đều · 5: cụ thể, đúng giọng, đúng liều lượng của profile"),
    "CALLBACK_QUALITY": ("Gợi lại (callback)", "1: chi tiết cài và trả trong phạm vi bị bỏ rời · 3: nối được một "
                         "phần · 5: nối tự nhiên"),
    "NARRATION_NATURALNESS": ("Tự nhiên khi đọc", "1: như bản dịch hoặc văn viết · 3: phần lớn tự nhiên, vài câu "
                              "cứng hoặc quá suồng sã · 5: đọc thành tiếng tự nhiên, đúng giọng"),
    "OVERALL_USEFULNESS": ("Dùng được tổng thể", "1: không dùng làm điểm xuất phát được · 3: bản nháp dùng được, "
                           "cần sửa thật · 5: thu âm được sau một lượt sửa nhẹ"),
}
_YES = {"có", "co", "yes", "y", "x", "rồi", "roi"}
_NO = {"không", "khong", "no", "n"}
_NOT_APPLICABLE = {"n/a", "na", "không áp dụng", "khong ap dung"}
_FIELD = re.compile(r"^-\s*(?P<label>[^:]+?)\s*:\s*(?P<value>.*)$")


@lru_cache(maxsize=1)
def contract() -> Dict[str, Any]:
    """Gate, severity, dimension and taxonomy vocabularies read from the frozen contract."""
    data = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    gates = data["hard_gates"]
    taxonomy = {item["id"]: item["gate"] for item in data["failure_taxonomy"]["integrity"]}
    for item in data["failure_taxonomy"]["integrity"]:
        for subtype in item["subtypes"]:
            taxonomy[subtype] = item["gate"]
    known = {gate["id"] for gate in gates["gates"]}
    if known != {gate for _, gate, _ in GATES}:
        raise ValueError("contract gates differ from the review kit's gate list")
    dims = data["soft_dimensions"]["dimensions"]
    if [d["id"] for d in dims] != list(DIMENSION_LABELS):
        raise ValueError("contract soft dimensions differ from the review kit's list")
    return {
        "version": data["contract_version"],
        "material": tuple(gates["material_severities"]),
        "audited": tuple(gates["human_audit_required_in_v0"]),
        "severities": tuple(level["id"] for level in data["severity_levels"]),
        "dimensions": tuple((d["id"], bool(d["may_be_not_applicable"])) for d in dims),
        "edit_costs": tuple(data["edit_cost_levels"]),
        "taxonomy": taxonomy,
    }


# ---------------------------------------------------------------------------- form writing


def _cell(value: Any) -> str:
    text = " ".join(str(value if value is not None else "").split())
    return text.replace("|", "/")


def _candidates(report: Mapping[str, Any]) -> List[Dict[str, str]]:
    """The pipeline's remaining findings and mechanical flags, as rows for the reviewer to decide."""
    taxonomy = contract()["taxonomy"]
    codes = {gate: code for code, gate, _ in GATES}
    rows = []
    for item in list(report.get("findings") or []) + list(report.get("undetermined") or []):
        category = item.get("failure_category") or ""
        gate = codes.get(taxonomy.get(category, ""), "")
        evidence = item.get("source_quote") or ", ".join(item.get("brief_refs") or []) or "absent"
        rows.append({"source": "critic", "gate": gate, "code": category or item.get("claim_type", ""),
                     "severity": item.get("severity") or "", "passage": item.get("claim") or "",
                     "evidence": evidence, "reason": item.get("explanation") or "",
                     "fix": item.get("suggested_fix") or ""})
    check = report.get("final_check") or {}
    if check and check.get("length_ok") is False:
        rows.append({"source": "máy", "gate": "REQUEST", "code": "LENGTH_NONCOMPLIANCE", "severity": "",
                     "passage": "(cả kịch bản)", "evidence": f"đếm được {check.get('word_count')} từ, "
                     f"yêu cầu {check.get('length_target')}", "reason": "Ngoài khoảng độ dài; người chấm "
                     "chọn mức độ theo công sửa (contract 14.1).", "fix": ""})
    if check.get("foreign_script_count") or check.get("artifacts"):
        rows.append({"source": "máy", "gate": "OUTPUT", "code": "OUTPUT_INTEGRITY_FAILURE", "severity": "",
                     "passage": check.get("foreign_script_sample") or "(xem report.md)",
                     "evidence": f"{check.get('foreign_script_count', 0)} ký tự lạ, artifact: "
                     f"{len(check.get('artifacts') or [])}", "reason": "Cờ của kiểm tra máy.", "fix": ""})
    return rows


def request_record(run_dir: Path) -> Dict[str, Any]:
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    scope, profile = manifest.get("scope") or {}, manifest.get("profile") or {}
    chapters = scope.get("chapters") or []
    background = manifest.get("background_chapters") or []
    check = report.get("final_check") or {}
    last = max(chapters) if chapters else None
    recap = f"; tóm tắt chương {min(background)}–{max(background)} từ story memory" if background else ""
    return {
        "run_id": manifest.get("run_id") or run_dir.name,
        "scope": f"{scope.get('label', '')}; thông tin được phép tới hết chương {last}",
        "boundary": f"nguyên văn {scope.get('label', '')} (review.html, mục nguồn){recap}",
        "language": f"{profile.get('target_language', '')}; {profile.get('narration', '')}",
        "length": f"{profile.get('min_words')}–{profile.get('max_words')} từ",
        "tolerance": "khoảng của profile là giới hạn cứng (đã gồm dung sai)",
        "counting": f"số từ của lời dẫn tách theo khoảng trắng; đếm được {check.get('word_count')}",
        "spoiler": f"NONE: không gì sau chương {last}",
        "profile": f"{profile.get('profile_id', '')}: {profile.get('tone', '')}; hài hước "
                   f"{profile.get('humor_level', '')}; bình luận {profile.get('commentary_intensity', '')}; "
                   f"mở đầu {profile.get('hook_style', '')}",
        "model": manifest.get("client") or "unknown",
        "candidates": _candidates(report),
    }


def render_form(record: Mapping[str, Any]) -> str:
    c = contract()
    lines = [
        f"# Phiếu chấm Script Quality Gate — {record['run_id']}", "",
        f"<!-- {FORM_VERSION}; {c['version']}; {PROTOCOL_ID} -->", "",
        "Đọc `script_final.md`, đối chiếu nguyên văn trong `review.html`. Chỉ ghi vào các ô trống; "
        "gate và verdict do lệnh `score` tự tính. Không dùng ký tự `|` trong ô.", "",
        "## 0. Yêu cầu (tự điền)", "",
        f"- Kịch bản / run: {record['run_id']}",
        f"- Phạm vi: {record['scope']}",
        f"- Ranh giới sự thật: {record['boundary']}",
        f"- Ngôn ngữ và giọng: {record['language']}",
        f"- Độ dài mục tiêu: {record['length']}",
        f"- Dung sai: {record['tolerance']}",
        f"- Cách đếm: {record['counting']}",
        f"- Chế độ spoiler: {record['spoiler']}",
        f"- Profile: {record['profile']}",
        f"- Mô hình: {record['model']}", "",
        "## 1. Người chấm", "",
        "- Người chấm: ",
        "- Loại người chấm (người/AI): ",
        "- Ngày: ", "",
        "## 2. Phần A — Lỗi", "",
        "Dòng `critic`/`máy` là đề xuất: ghi `có` vào cột Xác nhận nếu đúng, `không` nếu sai, và sửa Mức độ "
        "nếu cần. Lỗi bạn tự tìm: thêm dòng, Nguồn `người chấm`, Xác nhận `có`. Mức độ: CRITICAL, HIGH "
        "(hai mức này làm hỏng gate), MEDIUM, LOW. Gate: " + ", ".join(code for code, _, _ in GATES)
        + " (nhiều gate cách nhau bằng dấu phẩy; để trống thì suy ra từ Mã lỗi).", "",
        "| # | Nguồn | Xác nhận | Gate | Mã lỗi | Mức độ | Trích kịch bản | Bằng chứng nguồn | Lý do | Gợi ý sửa |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for number, row in enumerate(record["candidates"], 1):
        lines.append("| " + " | ".join(_cell(v) for v in (number, row["source"], "", row["gate"], row["code"],
                                                            row["severity"], row["passage"], row["evidence"],
                                                            row["reason"], row["fix"])) + " |")
    start = len(record["candidates"]) + 1
    lines += [f"| {n} | người chấm | | | | | | | | |" for n in range(start, start + 3)]
    lines += ["", "## 3. Gate đã kiểm tra", "",
              "Ghi `có` khi bạn đã đọc kịch bản đối chiếu nguồn cho gate đó. Gate máy kiểm tra không cần.", "",
              "| Gate | Nội dung | Đã kiểm tra | Ghi chú |", "|---|---|---|---|"]
    for code, gate, label in GATES:
        lines.append(f"| {code} | {label} | {'' if gate in c['audited'] else 'không cần'} | |")
    lines += ["", "## 4. Phần B — Chất lượng kể", "",
              "Điểm 1–5 (hoặc `N/A` nếu tiêu chí không áp dụng). Mỗi điểm cần một trích đoạn và lý do; "
              "điểm thiếu bằng chứng không hợp lệ. Không lấy trung bình.", "",
              "| Tiêu chí | Mã | Điểm | Trích đoạn | Lý do | Mốc 1 · 3 · 5 |", "|---|---|---|---|---|---|"]
    for dim, optional in c["dimensions"]:
        label, anchors = DIMENSION_LABELS[dim]
        lines.append(f"| {label}{' (có thể N/A)' if optional else ''} | {dim} | | | | {anchors} |")
    lines += ["", "## 5. Chi phí sửa", "",
              "MINIMAL: sửa từ · MODERATE: viết lại, làm nhẹ hoặc bỏ vài câu, giữ cấu trúc · MAJOR: dựng lại "
              "đoạn hoặc sửa lỗi rải khắp · REWRITE: viết lại nhanh hơn sửa.", "",
              "- Chi phí sửa: ",
              "- Mọi lỗi còn lại đều sửa tại chỗ được (có/không): ", ""]
    return "\n".join(lines)


def _run_dirs(paths: Iterable[Path]) -> List[Path]:
    """Run directories under each path: the path itself, or every episode of a season."""
    found = []
    for path in paths:
        if (path / "season.json").is_file():
            season = json.loads((path / "season.json").read_text(encoding="utf-8"))
            found += [path / row["dir"] for row in season.get("episodes") or [] if row.get("dir")]
        elif (path / "run_manifest.json").is_file():
            found.append(path)
        else:
            raise ValueError(f"not a run or season directory: {path}")
    return found


def write_forms(paths: Sequence[Path], *, force: bool = False) -> List[Path]:
    written = []
    for run_dir in _run_dirs(paths):
        target = run_dir / FORM_NAME
        if target.exists() and not force:
            raise FileExistsError(f"{target} exists; it may hold a review (use --force to replace it)")
        target.write_text(render_form(request_record(run_dir)), encoding="utf-8")
        written.append(target)
    return written


# ---------------------------------------------------------------------------- form reading


def _yes_no(value: str) -> Optional[bool]:
    value = value.strip().lower()
    return True if value in _YES else False if value in _NO else None


def _tables(text: str) -> Dict[str, List[List[str]]]:
    """Table rows keyed by the first header cell; separator rows dropped."""
    tables: Dict[str, List[List[str]]] = {}
    key = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            key = None
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if key is None:
            key = cells[0]
            tables[key] = []
        elif not all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            tables[key].append(cells)
    return tables


def _fields(text: str) -> Dict[str, str]:
    values = {}
    for line in text.splitlines():
        match = _FIELD.match(line.strip())
        if match:
            values[match["label"]] = match["value"].strip()
    return values


@dataclass
class Review:
    path: str
    reviewer: str = ""
    human: Optional[bool] = None
    confirmed: List[Dict[str, Any]] = field(default_factory=list)
    pending: List[Dict[str, Any]] = field(default_factory=list)
    audited: Dict[str, bool] = field(default_factory=dict)
    ratings: Dict[str, Optional[int]] = field(default_factory=dict)
    edit_cost: Optional[str] = None
    local_fix: Optional[bool] = None
    errors: List[str] = field(default_factory=list)


def parse_form(text: str, path: str = "") -> Review:
    c = contract()
    review = Review(path)
    if FORM_VERSION not in text:
        review.errors.append(f"not a {FORM_VERSION} form")
        return review
    values, tables = _fields(text), _tables(text)
    review.reviewer = values.get("Người chấm", "")
    kind = values.get("Loại người chấm (người/AI)", "").strip().lower()
    review.human = True if kind in {"người", "nguoi", "human"} else False if kind in {"ai", "model"} else None
    if not review.reviewer:
        review.errors.append("reviewer name missing")
    if review.human is None:
        review.errors.append("reviewer kind must be người or AI")
    codes = {code: gate for code, gate, _ in GATES}
    for row in tables.get("#", []):
        row = (row + [""] * 10)[:10]
        number, source, decision, gate_text, code, severity, passage, evidence, reason, fix = row
        if not any((gate_text, code, severity, passage)):
            continue
        accepted = _yes_no(decision)
        item = {"number": number, "source": source, "code": code, "severity": severity.upper(),
                "passage": passage, "evidence": evidence, "reason": reason, "fix": fix}
        names = [g.strip().upper() for g in gate_text.split(",") if g.strip()]
        unknown = [g for g in names if g not in codes]
        gates = [codes[g] for g in names if g in codes] or (
            [c["taxonomy"][code]] if code in c["taxonomy"] else [])
        item["gates"] = gates
        if accepted is False:
            continue
        if accepted is None:
            if source.lower() in {"critic", "máy", "may"}:
                review.pending.append(item)
            else:
                review.errors.append(f"finding {number}: Xác nhận must be có or không")
            continue
        problems = []
        if unknown or not gates:
            problems.append("needs a gate")
        if item["severity"] not in c["severities"]:
            problems.append("needs a severity")
        if not passage or not reason or not evidence:
            problems.append("needs a script passage, boundary evidence (or absent) and a reason")
        if problems:
            review.errors.append(f"finding {number}: " + "; ".join(problems))
        else:
            review.confirmed.append(item)
    for row in tables.get("Gate", []):
        row = (row + [""] * 4)[:4]
        if row[0] in codes:
            review.audited[codes[row[0]]] = _yes_no(row[2]) is True
    for row in tables.get("Tiêu chí", []):
        row = (row + [""] * 6)[:6]
        dim, score, quote, reason = row[1], row[2].strip(), row[3], row[4]
        optional = dict(c["dimensions"]).get(dim)
        if optional is None:
            continue
        if score.lower() in _NOT_APPLICABLE:
            if optional:
                review.ratings[dim] = None
            else:
                review.errors.append(f"{dim} cannot be N/A")
            continue
        if not re.fullmatch(r"[1-5]", score):
            review.errors.append(f"{dim} needs a rating 1-5")
        elif not quote or not reason:
            review.errors.append(f"{dim} rating needs a quoted passage and a reason")
        else:
            review.ratings[dim] = int(score)
    missing = [dim for dim, _ in c["dimensions"] if dim not in review.ratings]
    if missing and not any(dim in e for dim in missing for e in review.errors):
        review.errors.append("ratings missing: " + ", ".join(missing))
    cost = values.get("Chi phí sửa", "").strip().upper()
    if cost in c["edit_costs"]:
        review.edit_cost = cost
    else:
        review.errors.append("edit cost must be one of " + ", ".join(c["edit_costs"]))
    review.local_fix = _yes_no(values.get("Mọi lỗi còn lại đều sửa tại chỗ được (có/không)", ""))
    if review.local_fix is None and review.confirmed:
        review.errors.append("say whether every remaining finding has a local fix (có/không)")
    return review


# ---------------------------------------------------------------------------- verdicts


def gate_statuses(review: Review, *, official: bool) -> Dict[str, str]:
    """Contract section 15. In the official reading only a human's audit counts."""
    c = contract()
    statuses = {}
    for _, gate, _ in GATES:
        severities = {f["severity"] for f in review.confirmed if gate in f["gates"]}
        audit_needed = gate in c["audited"]
        human_ok = review.human is True or not official
        if severities & set(c["material"]) and (human_ok or not audit_needed):
            statuses[gate] = "GATE_FAIL"
        elif audit_needed and not (review.audited.get(gate) and human_ok):
            statuses[gate] = "GATE_NOT_DETERMINED"
        elif any(gate in f["gates"] for f in review.pending):
            statuses[gate] = "GATE_NOT_DETERMINED"
        elif "MEDIUM" in severities:
            statuses[gate] = "GATE_CONDITIONAL"
        else:
            statuses[gate] = "GATE_PASS"
    return statuses


def verdict(statuses: Mapping[str, str], ratings: Mapping[str, Optional[int]], edit_cost: str,
            local_fix: Optional[bool], open_findings: int) -> str:
    """Contract section 16, rows in order; a finding without a local fix makes the cost MAJOR."""
    if "GATE_FAIL" in statuses.values() or edit_cost == "REWRITE":
        return "FAIL"
    if open_findings and local_fix is False and edit_cost in ("MINIMAL", "MODERATE"):
        edit_cost = "MAJOR"
    scores = [score for score in ratings.values() if score is not None]
    if ("GATE_NOT_DETERMINED" in statuses.values() or any(score <= 2 for score in scores)
            or edit_cost == "MAJOR"):
        return "REVIEW_REQUIRED"
    if (all(status == "GATE_PASS" for status in statuses.values()) and min(scores, default=5) >= 3
            and (ratings.get("OVERALL_USEFULNESS") or 0) >= 4 and edit_cost == "MINIMAL"):
        return "PASS"
    return "PASS_WITH_MINOR_EDITS"


def score_review(review: Review) -> Dict[str, Any]:
    result: Dict[str, Any] = {"form": review.path, "form_version": FORM_VERSION, "reviewer": review.reviewer,
                              "reviewer_kind": {True: "human", False: "ai"}.get(review.human),
                              "errors": list(review.errors), "pending_candidates": len(review.pending),
                              "findings": review.confirmed, "ratings": review.ratings,
                              "edit_cost": review.edit_cost, "local_fix": review.local_fix}
    if review.errors:
        result.update(status="INCOMPLETE", trace_verdict=None, official_verdict=None)
        return result
    for kind, official in (("trace", False), ("official", True)):
        statuses = gate_statuses(review, official=official)
        result[f"{kind}_gates"] = statuses
        result[f"{kind}_verdict"] = verdict(statuses, review.ratings, review.edit_cost, review.local_fix,
                                            len(review.confirmed))
    result["status"] = "SCORED"
    return result


def _forms(paths: Iterable[Path]) -> List[Path]:
    forms = []
    for path in paths:
        if path.is_file():
            forms.append(path)
        else:
            forms += [run_dir / FORM_NAME for run_dir in _run_dirs([path])]
    return forms


def score_forms(paths: Sequence[Path]) -> List[Dict[str, Any]]:
    results = []
    for form in _forms(paths):
        if not form.is_file():
            results.append({"form": str(form), "status": "MISSING", "errors": ["form not written"]})
            continue
        result = score_review(parse_form(form.read_text(encoding="utf-8"), str(form)))
        (form.parent / RESULT_NAME).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n",
                                               encoding="utf-8")
        results.append(result)
    return results


def gate_result(results: Sequence[Mapping[str, Any]], required: int = REQUIRED_SCRIPTS,
                pass_fraction: float = PASS_FRACTION) -> Dict[str, Any]:
    """The protocol's rule: every script reviewed by a human, none FAIL, no CRITICAL finding,
    and at least `pass_fraction` of them PASS or PASS_WITH_MINOR_EDITS."""
    reasons = []
    scored = [r for r in results if r.get("status") == "SCORED"]
    if len(results) < required:
        reasons.append(f"{len(results)} of {required} scripts in the sample")
    if len(scored) < len(results):
        reasons.append(f"{len(results) - len(scored)} forms incomplete or missing")
    if any(r.get("reviewer_kind") != "human" for r in scored):
        reasons.append("a form was not filled by a human reviewer")
    verdicts = [r["official_verdict"] for r in scored]
    critical = sum(f["severity"] == "CRITICAL" for r in scored for f in r["findings"])
    passed = sum(v in ("PASS", "PASS_WITH_MINOR_EDITS") for v in verdicts)
    needed = math.ceil(pass_fraction * max(len(results), required))
    if reasons:
        outcome = "NOT_EVALUATED"
    elif "FAIL" in verdicts or critical or passed < needed:
        outcome = "FAIL"
    else:
        outcome = "PASS"
    return {"protocol": PROTOCOL_ID, "outcome": outcome, "reasons": reasons, "scripts": len(results),
            "passed": passed, "needed": needed, "critical_findings": critical,
            "verdicts": {v: verdicts.count(v) for v in ("PASS", "PASS_WITH_MINOR_EDITS", "REVIEW_REQUIRED", "FAIL")},
            "edit_costs": {c: sum(r.get("edit_cost") == c for r in scored) for c in contract()["edit_costs"]}}


def summary_markdown(results: Sequence[Mapping[str, Any]], gate: Mapping[str, Any]) -> str:
    lines = [f"# Kết quả Script Quality Gate — {gate['outcome']}", "",
             f"- Protocol: `{gate['protocol']}`",
             f"- Đạt (PASS hoặc PASS_WITH_MINOR_EDITS): {gate['passed']}/{gate['scripts']}, cần {gate['needed']}",
             f"- Lỗi CRITICAL: {gate['critical_findings']}",
             f"- Verdict: {gate['verdicts']}", f"- Chi phí sửa: {gate['edit_costs']}"]
    lines += [f"- Chưa đánh giá được: {reason}" for reason in gate["reasons"]]
    lines += ["", "| Phiếu | Trạng thái | Verdict chính thức | Verdict theo phiếu | Gate hỏng | Chi phí sửa |",
              "|---|---|---|---|---|---|"]
    for r in results:
        failed = [g for g, s in (r.get("official_gates") or {}).items() if s == "GATE_FAIL"]
        lines.append(f"| {r['form']} | {r['status']} | {r.get('official_verdict') or '—'} | "
                     f"{r.get('trace_verdict') or '—'} | {', '.join(failed) or '—'} | {r.get('edit_cost') or '—'} |")
    for r in results:
        if r.get("errors"):
            lines += ["", f"**{r['form']}**: " + "; ".join(r["errors"])]
    return "\n".join(lines) + "\n"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_lock(season_dir: Path, *, manifest: Path, source_root: Optional[Path], profile: Path,
               last_chapter: int, model: str, command: str) -> Path:
    """Protocol section 3: freeze the commit, profile, manifest and chapters 1..last before generating."""
    target = season_dir / "gate_lock.json"
    if target.exists():
        raise FileExistsError(f"{target} exists; the sample is already locked")
    data = json.loads(manifest.read_text(encoding="utf-8")) if manifest.suffix == ".json" else \
        yaml.safe_load(manifest.read_text(encoding="utf-8"))
    root = source_root or manifest.parent
    documents = sorted(data["documents"], key=lambda d: d["order"])
    chapters = {d["order"]: _sha256(root / d["path"]) for d in documents if d["order"] <= last_chapter}
    if sorted(chapters) != list(range(1, last_chapter + 1)):
        raise ValueError(f"manifest does not hold chapters 1-{last_chapter}")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "tools/story_pipeline"], cwd=REPO,
                           capture_output=True, text=True).stdout.strip()
    lock = {"protocol": PROTOCOL_ID, "locked_at": datetime.now(timezone.utc).isoformat(), "commit": commit or None,
            "pipeline_dirty": bool(dirty), "model": model, "command": command,
            "profile_sha256": _sha256(profile), "manifest_sha256": _sha256(manifest),
            "chapter_sha256": {str(k): v for k, v in sorted(chapters.items())}}
    season_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(lock, indent=1) + "\n", encoding="utf-8")
    return target


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("lock", "form", "score", "summary"))
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--force", action="store_true", help="form: replace an existing form")
    parser.add_argument("--out", type=Path, help="summary: directory for gate_summary.md/json")
    parser.add_argument("--manifest", type=Path, help="lock: source manifest")
    parser.add_argument("--source-root", type=Path, help="lock: directory holding the manifest paths")
    parser.add_argument("--profile", type=Path, help="lock: Narrative Profile YAML")
    parser.add_argument("--last-chapter", type=int, help="lock: last chapter of the sample")
    parser.add_argument("--model", default="", help="lock: model the sample uses")
    parser.add_argument("--run-command", default="", help="lock: the exact season command")
    args = parser.parse_args(argv)
    try:
        if args.command == "lock":
            if not (args.manifest and args.profile and args.last_chapter):
                parser.error("lock needs --manifest, --profile and --last-chapter")
            print(f"wrote {write_lock(args.paths[0], manifest=args.manifest, source_root=args.source_root, profile=args.profile, last_chapter=args.last_chapter, model=args.model, command=args.run_command)}")
            return 0
        if args.command == "form":
            for path in write_forms(args.paths, force=args.force):
                print(f"wrote {path}")
            return 0
        results = score_forms(args.paths)
    except (ValueError, FileExistsError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.command == "score":
        for r in results:
            print(f"{r['form']}: {r['status']} official={r.get('official_verdict')} trace={r.get('trace_verdict')}"
                  + (f" errors={r['errors']}" if r.get("errors") else ""))
        return 0 if all(r["status"] == "SCORED" for r in results) else 1
    gate = gate_result(results)
    text = summary_markdown(results, gate)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "gate_summary.md").write_text(text, encoding="utf-8")
        (args.out / "gate_summary.json").write_text(json.dumps({"gate": gate, "scripts": results},
                                                               ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
