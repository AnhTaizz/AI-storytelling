"""M7 brief verification: check every Story Brief item against the source it cites.

Errors born in the brief cannot be seen by the critic, which judges the script against the
brief (live runs: "phản ứng dữ dội" for a flat refusal; "there is no rumour that she failed"
labelled as a rumour). This stage gives a fact checker the chapter's source and every brief
item (ref, label, cited passages) and asks for the items with a problem, each with a corrected
text and label. Corrections are applied to the episode's copy of the brief only when the
corrected brief still passes every brief check; the rest are reported for the reviewer.
Item refs follow the retrieval scheme (c3.E2, c3.CH1.F2, c3.R1).
"""

from __future__ import annotations

import copy
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

from tools.story_pipeline import stages
from tools.story_pipeline.llm import CallLog, LLMClient, run_json_stage, schema_errors
from tools.story_pipeline.profile import LANGUAGE_NAMES, NarrativeProfile
from tools.story_pipeline.source import Chapter
from tools.story_retrieval.brief_retrieval_v1 import render_items

VERDICT_VI = {"NOT_SUPPORTED": "nguồn không có", "CONTRADICTS_SOURCE": "trái nguồn",
              "STRONGER_THAN_SOURCE": "mạnh hơn nguồn", "WRONG_LABEL": "sai nhãn",
              "WRONG_SPEAKER": "sai người nói"}

COVERAGE_GAPS_DEV = {
    "type": "array",
    "items": {
        "type": "object", "additionalProperties": False,
        "required": ["kind", "ref", "claim", "epistemic", "evidence"],
        "properties": {
            "kind": {"enum": ["MISSING_CORE", "MISSING_CLAIM", "MISSING_EVIDENCE", "CORE_PRIORITY", "REVIEW"]},
            "ref": {"type": ["string", "null"]},
            "claim": {"type": "string", "pattern": r"\S"},
            "epistemic": {"enum": list(stages.EPISTEMIC_LABELS)},
            "evidence": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {
                "type": "object", "additionalProperties": False, "required": ["passage_id", "quote"],
                "properties": {"passage_id": {"type": "string"}, "quote": {"type": "string", "minLength": 1}},
            }},
        },
    },
}

COVERAGE_INSTRUCTIONS_DEV = """The instruction to leave omissions unreported applies to findings.
Return coverage_gaps as a separate advisory list. Read the chapter in order and identify
source-supported central story events and their necessary atomic claims before comparing them
with the entire Brief. A paraphrase or combination of items with the same meaning is sufficient.
Skip incidental and repeated details.

Report MISSING_CORE for a central event missing as an event, even when another event alludes to it.
Report MISSING_CLAIM for each other necessary claim that is absent or materially incomplete,
MISSING_EVIDENCE when a claim is present but its citations do not jointly support it, and
CORE_PRIORITY for a central event present as a lower-priority event. Give the affected item ref
where one exists. For MISSING_CORE use null. For MISSING_EVIDENCE and CORE_PRIORITY use an existing ref.
Use REVIEW when the source or the match is ambiguous or the claim relies on inference. Check the
neighboring passages for an omitted subject, speaker, or antecedent and cite the passages that
establish it. Do not count a wrong actor, reversed sequence, changed cause, or stronger certainty
as equivalent. Keep speech and thoughts attributed to the right character and uncertainty in
both the text and epistemic label. Write one claim per row in the Brief language. Cite verbatim
source spans under their own passage IDs. Include all jointly necessary spans, such as both sides
of a causal or order relation, using one sufficient set when
alternatives exist. Repeated mentions do not require duplicate findings. Return [] if no gap exists."""


def item_lines(brief: Dict[str, Any], *, coverage_dev: bool = False) -> List[str]:
    return [f"- {i.ref} [{i.kind}, {i.epistemic}{', ' + i.importance if i.importance else ''}] "
            f"(cites {', '.join(i.evidence)}): "
            + (f"{i.text} [quote: {i.quote}]" if coverage_dev else i.summary) for i in render_items(brief)]


def brief_check_errors(result: Dict[str, Any], brief: Dict[str, Any]) -> List[str]:
    refs = {i.ref for i in render_items(brief)}
    errors, seen = [], set()
    for index, finding in enumerate(result["findings"]):
        where = f"findings[{index}] {finding['ref']}"
        if finding["ref"] not in refs:
            errors.append(f"{where}: no such item; use the refs listed")
        if finding["ref"] in seen:
            errors.append(f"{where}: report each item once")
        seen.add(finding["ref"])
        if finding["verdict"] == "WRONG_LABEL" and not finding["corrected_label"]:
            errors.append(f"{where}: WRONG_LABEL needs corrected_label")
        if finding["verdict"] != "NOT_SUPPORTED" and not (finding["corrected_text"] or finding["corrected_label"]):
            errors.append(f"{where}: give corrected_text (or corrected_label); only NOT_SUPPORTED may remove an item")
    return errors


def coverage_gap_errors(result: Dict[str, Any], brief: Dict[str, Any], chapter: Chapter) -> List[str]:
    items = {item.ref: item for item in render_items(brief)}
    source = {passage.passage_id: passage.text for passage in chapter.passages}
    errors = []
    for index, gap in enumerate(result["coverage_gaps"]):
        where = f"coverage_gaps[{index}]"
        kind, ref = gap["kind"], gap["ref"]
        if (ref is not None and ref not in items or kind == "MISSING_CORE" and ref is not None
                or kind in ("CORE_PRIORITY", "MISSING_EVIDENCE") and ref is None):
            errors.append(f"{where}: invalid Brief ref for {kind}")
        elif kind == "CORE_PRIORITY" and (items[ref].kind != "event" or items[ref].importance == "CORE"):
            errors.append(f"{where}: CORE_PRIORITY needs a lower-priority event")
        for evidence in gap["evidence"]:
            passage = source.get(evidence["passage_id"])
            quote = evidence["quote"]
            if passage is None or not quote.strip() or not stages.quote_in_passages(quote, [passage]):
                errors.append(f"{where}: quote must appear in its cited chapter passage")
    return errors


def run_brief_check(client: LLMClient, chapter: Chapter, brief: Dict[str, Any], profile: NarrativeProfile,
                    source_language: str, log: CallLog, max_repairs: int, *, coverage_dev: bool = False
                    ) -> Dict[str, Any]:
    """In DEV, report advisory errors in the result. CallLog records fidelity validation."""
    response_schema = stages.load_schema("brief_check_v0")
    prompt_schema = response_schema
    if coverage_dev:
        prompt_schema = {**response_schema, "required": [*response_schema["required"], "coverage_gaps"],
                         "properties": {**response_schema["properties"], "coverage_gaps": COVERAGE_GAPS_DEV}}
        # Accept the envelope first so an invalid advisory cannot discard the findings.
        response_schema = {**response_schema, "properties": {**response_schema["properties"], "coverage_gaps": {}}}
    language = LANGUAGE_NAMES.get(source_language, source_language)
    system = stages.render("brief_check_system", brief_language_name=profile.brief_language_name,
                           source_language_name=language, schema=stages.dump(prompt_schema))
    lines = item_lines(brief, coverage_dev=coverage_dev)
    user = stages.render("brief_check_user", chapter_order=chapter.order, source_language_name=language,
                         source=stages.source_check_text([chapter]), item_count=len(lines), items="\n".join(lines))
    if coverage_dev:
        system += "\n\n" + COVERAGE_INSTRUCTIONS_DEV
        user += (f"\n\nBrief chapter summary: {brief['chapter_summary']}"
                 f"\nBrief ending state: {brief['ending_state']}")

    result = run_json_stage(client, stage="brief_check", system=system, user=user, schema=response_schema,
                            semantic_check=lambda r: brief_check_errors(r, brief),
                            max_repairs=0 if coverage_dev else max_repairs, log=log,
                            request_suffix=f"ch{chapter.order}")
    if coverage_dev:
        errors = schema_errors(prompt_schema, result) or coverage_gap_errors(result, brief, chapter)
        if errors:
            result.pop("coverage_gaps", None)
            result["coverage_errors"] = errors
    return result


def _locate(brief: Dict[str, Any], ref: str) -> Optional[Tuple[Dict[str, Any], str, List[Dict[str, Any]]]]:
    """(item dict, text field, containing list) for a ref of this brief."""
    local = ref.split(".", 1)[1]
    if local.startswith("E"):
        items = brief["events"]
        found = next((e for e in items if e["id"] == local), None)
        return (found, "summary", items) if found else None
    if local.startswith("R"):
        index = int(local[1:]) - 1
        items = brief["relationships"]
        return (items[index], "state", items) if 0 <= index < len(items) else None
    character_id, fact = local.split(".")
    character = next((c for c in brief["characters"] if c["id"] == character_id), None)
    index = int(fact[1:]) - 1
    if character is None or not 0 <= index < len(character["facts"]):
        return None
    return character["facts"][index], "text", character["facts"]


def _errors(brief: Dict[str, Any], chapter: Chapter, source_language: str, brief_language: str) -> List[str]:
    return (stages.brief_semantic_errors(brief, chapter, source_language, brief_language)
            + stages.brief_atomicity_errors(brief, brief_language))


def apply_corrections(brief: Dict[str, Any], findings: Sequence[Dict[str, Any]], chapter: Chapter,
                      source_language: str, brief_language: str
                      ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Apply each correction that keeps the brief valid; returns (brief, applied, rejected).

    A text or label correction is kept only if it introduces no new brief-check finding.
    A CORE event is never removed. Removals happen last so refs stay valid."""
    fixed = copy.deepcopy(brief)
    applied: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    removals = []
    baseline = Counter(_errors(fixed, chapter, source_language, brief_language))
    for finding in findings:
        located = _locate(fixed, finding["ref"])
        if located is None:
            rejected.append({**finding, "reason": "no such item"})
            continue
        item, field, container = located
        if not finding["corrected_text"] and not finding["corrected_label"]:
            if item.get("importance") == "CORE":
                rejected.append({**finding, "reason": "a CORE event is never removed automatically"})
            else:
                removals.append((finding, item, container))
            continue
        before = (item[field], item["epistemic"])
        if finding["corrected_text"]:
            item[field] = finding["corrected_text"]
        if finding["corrected_label"]:
            item["epistemic"] = finding["corrected_label"]
        current = Counter(_errors(fixed, chapter, source_language, brief_language))
        if current - baseline:
            item[field], item["epistemic"] = before
            rejected.append({**finding, "reason": "the corrected item fails the brief checks"})
            continue
        baseline = current
        applied.append({**finding, "before": before[0], "before_label": before[1]})
    for finding, item, container in removals:
        container.remove(item)
        applied.append({**finding, "before": item.get("summary") or item.get("text") or item.get("state"),
                        "before_label": item["epistemic"], "removed": True})
    return fixed, applied, rejected


def report_markdown(summary: Dict[str, Any]) -> str:
    """brief_check.md: what the check found per chapter, applied or left for the reviewer."""
    lines = ["# Kiểm chứng brief với nguồn (M7)", "",
             "Mỗi mục brief được đối chiếu với đoạn nguồn nó trích. Bản sửa nào vẫn qua mọi kiểm tra brief "
             "thì đã áp vào brief của lần chạy này (bộ nhớ truyện giữ nguyên); bản còn lại cần người xem.", ""]
    for chapter, info in sorted(summary.items(), key=lambda item: int(item[0])):
        lines.append(f"## Chương {chapter}")
        if "failed" in info:
            lines += ["", f"Không kiểm được: {info['failed']}", ""]
            continue
        lines += ["", f"{info['findings']} phát hiện; đã áp {len(info['applied'])}, cần xem {len(info['rejected'])}.", ""]
        for item in info["applied"]:
            action = "đã bỏ" if item.get("removed") else f"→ {item['corrected_text'] or ''} [{item['corrected_label'] or item['before_label']}]"
            lines.append(f"- [đã áp] {item['ref']} ({VERDICT_VI[item['verdict']]}): {item['before']} {action}")
        for item in info["rejected"]:
            lines.append(f"- [CẦN XEM] {item['ref']} ({VERDICT_VI[item['verdict']]}): {item['explanation']} "
                         f"— gợi ý: {item['corrected_text'] or 'bỏ mục'} ({item['reason']})")
        lines.append("")
    return "\n".join(lines)
