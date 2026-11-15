"""Narrative Plan checks and owner review (M8).

The plan decides presentation (order, pacing, emphasis, hook, callbacks); it may not create
story truth (docs/TARGET_ARCHITECTURE.md, section 5 item 6). Refs and CORE coverage are hard
checks in stages.plan_semantic_errors. This module adds:

- `plan_checks`: deterministic findings. A callback whose setup comes after its payoff is a
  soft error, fed back to the plan's repair loop (`plan_soft_errors`). The rest are advisory,
  for the reviewer: pacing (a beat whose words per event is under half the episode average
  while it holds a CORE event; a MINOR-only or event-less beat taking over a quarter of the
  words) and new facts in the plan's free text (a capitalised name that appears in no brief
  or glossary, or a number absent from the cited events). The free-text heuristics are
  crude: sentence-initial words and common nouns written with a capital can be flagged, and
  a fact without a name or number is not seen.
- `coverage`: CORE covered, SUPPORTING used, callbacks used and which came from M6 retrieval.
- `render_markdown` / `render_html` / `plan_review_form` / `parse_plan_review` /
  `plan_review_edits` / `apply_plan_review`: the owner keeps, drops or moves beats, changes
  their word budget and adds a note, before the script is written. A beat holding a CORE
  event is never dropped.
"""

from __future__ import annotations

import copy
import html
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from tools.story_pipeline.review_page import _STYLE

_EVENT_REF = re.compile(r"^c(\d+)\.E(\d+)$")
_WORD = re.compile(r"(?<![\w])([^\W\d_][\w'’-]*)", re.UNICODE)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_FORM_LINE = re.compile(r"^\s*-\s*`(?P<beat>B\d+)`\s*bỏ:\s*\[(?P<drop>[ xX])\]\s*\|\s*vị trí:\s*(?P<pos>\d+)\s*\|"
                        r"\s*số từ:\s*(?P<words>\d+)\s*\|\s*ghi chú:(?P<note>.*)$")


def _event_key(ref: str) -> Tuple[int, int]:
    match = _EVENT_REF.match(ref)
    return (int(match.group(1)), int(match.group(2))) if match else (10 ** 6, 10 ** 6)


def event_texts(briefs: Sequence[Mapping[str, Any]], recap: Optional[Mapping[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """ref -> {"text", "importance", "evidence", "earlier"} for episode and background events."""
    out: Dict[str, Dict[str, Any]] = {}
    for chapter in (recap or {}).get("chapters", []):
        for event in chapter["core_events"]:
            out[event["ref"]] = {"text": event["summary"], "importance": "CORE", "evidence": [], "earlier": True}
    for callback in (recap or {}).get("callbacks", []):
        out[callback["ref"]] = {"text": callback["summary"], "importance": callback.get("importance"),
                                "evidence": list(callback.get("evidence", [])), "earlier": True}
    for brief in briefs:
        n = brief["chapter_order"]
        for event in brief["events"]:
            text = " ".join(filter(None, [event["summary"], event.get("location"), event.get("consequence"),
                                          (event.get("motivation") or {}).get("text")]))
            out[f"c{n}.{event['id']}"] = {"text": text, "importance": event["importance"],
                                          "evidence": list(event["evidence"]), "earlier": False}
    return out


def known_names(briefs: Sequence[Mapping[str, Any]], recap: Optional[Mapping[str, Any]] = None,
                glossary: Optional[Mapping[str, Any]] = None) -> Set[str]:
    """Casefolded words of every name and every brief sentence: a capitalised word found here
    is not a new name."""
    words: Set[str] = set()

    def add(text: Optional[str]) -> None:
        words.update(w.casefold() for w in re.findall(r"[\w'’-]+", text or ""))

    for brief in briefs:
        add(brief.get("chapter_summary"))
        add(brief.get("ending_state"))
        for character in brief["characters"]:
            for name in [character["name"], character["romanized_name"], *character["aliases"]]:
                add(name)
            for fact in character["facts"]:
                add(fact["text"])
        for relation in brief["relationships"]:
            add(relation["state"])
        for event in brief["events"]:
            add(" ".join(filter(None, [event["summary"], event.get("location"), event.get("consequence"),
                                       (event.get("motivation") or {}).get("text")])))
    for text in event_texts([], recap).values():
        add(text["text"])
    for character in (recap or {}).get("roster", []) if isinstance((recap or {}).get("roster"), list) else []:
        add(" ".join(str(v) for v in character.values() if isinstance(v, str)))
    for entry in (glossary or {}).get("characters", []):
        add(entry.get("display"))
        for name in entry.get("also_allowed", []):
            add(name)
    return words


def _sentence_starts(text: str) -> Set[int]:
    starts = {0}
    for match in re.finditer(r"[.!?…:;\"“”(]\s*", text):
        starts.add(match.end())
    return starts


def new_names(text: Optional[str], known: Set[str]) -> List[str]:
    if not text:
        return []
    starts = _sentence_starts(text)
    found = []
    for match in _WORD.finditer(text):
        word = match.group(1)
        if not word[0].isupper() or match.start() in starts or word.casefold() in known or word in found:
            continue
        found.append(word)
    return found


def new_numbers(text: Optional[str], cited: str) -> List[str]:
    present = set(_NUMBER.findall(cited))
    return [n for n in dict.fromkeys(_NUMBER.findall(text or "")) if n not in present]


def plan_soft_errors(plan: Mapping[str, Any]) -> List[str]:
    """Clearly wrong plan choices, sent back to the plan's repair loop."""
    errors = []
    for index, callback in enumerate(plan["callbacks"]):
        if _event_key(callback["setup_ref"]) >= _event_key(callback["payoff_ref"]):
            errors.append(f"callbacks[{index}]: the setup {callback['setup_ref']} must come before the payoff "
                          f"{callback['payoff_ref']} in the story")
    return errors


def plan_checks(plan: Mapping[str, Any], briefs: Sequence[Mapping[str, Any]],
                recap: Optional[Mapping[str, Any]] = None, glossary: Optional[Mapping[str, Any]] = None
                ) -> Dict[str, Any]:
    events = event_texts(briefs, recap)
    names = known_names(briefs, recap, glossary)
    findings: List[Dict[str, Any]] = [{"kind": "callback_order", "where": message.split(":")[0], "severity": "soft",
                                       "message": message} for message in plan_soft_errors(plan)]
    total = sum(b["target_words"] for b in plan["beats"]) or 1
    refs = [r for b in plan["beats"] for r in b["event_refs"]]
    average = total / max(1, len(refs))
    for beat in plan["beats"]:
        importances = [events.get(r, {}).get("importance") for r in beat["event_refs"]]
        share = beat["target_words"] / total
        if "CORE" in importances and beat["target_words"] / len(beat["event_refs"]) < 0.5 * average:
            findings.append({"kind": "pacing_core_thin", "where": beat["id"], "severity": "advisory",
                             "message": f"{beat['id']} gives {beat['target_words'] / len(beat['event_refs']):.0f} words "
                                        f"per event while holding a CORE event (episode average {average:.0f})"})
        if share > 0.25 and (not beat["event_refs"] or all(i == "MINOR" for i in importances)):
            what = "no event" if not beat["event_refs"] else "only MINOR events"
            findings.append({"kind": "pacing_minor_heavy", "where": beat["id"], "severity": "advisory",
                             "message": f"{beat['id']} has {what} but takes {share:.0%} of the words"})
    texts = [("hook", plan["hook"]["idea"], plan["hook"]["event_refs"])]
    for beat in plan["beats"]:
        texts += [(f"{beat['id']}.commentary_idea", beat.get("commentary_idea"), beat["event_refs"]),
                  (f"{beat['id']}.emotional_note", beat.get("emotional_note"), beat["event_refs"])]
    for where, text, cited_refs in texts:
        cited = " ".join(events.get(r, {}).get("text", "") for r in cited_refs)
        for name in new_names(text, names):
            findings.append({"kind": "new_name", "where": where, "severity": "advisory",
                             "message": f"{where}: \"{name}\" is in no brief or glossary"})
        for number in new_numbers(text, cited):
            findings.append({"kind": "new_number", "where": where, "severity": "advisory",
                             "message": f"{where}: the number {number} is not in the cited events"})
    episode_events = {r: e for r, e in events.items() if not e["earlier"]}
    covered = set(refs)
    callback_refs = {c["ref"] for c in (recap or {}).get("callbacks", [])}
    used_setups = [c["setup_ref"] for c in plan["callbacks"]]
    coverage = {
        "core": sum(1 for e in episode_events.values() if e["importance"] == "CORE"),
        "core_covered": sum(1 for r, e in episode_events.items() if e["importance"] == "CORE" and r in covered),
        "supporting": sum(1 for e in episode_events.values() if e["importance"] == "SUPPORTING"),
        "supporting_used": sum(1 for r, e in episode_events.items() if e["importance"] == "SUPPORTING" and r in covered),
        "callbacks": len(plan["callbacks"]),
        "callbacks_from_retrieval": sorted({r for r in [*used_setups, *refs] if r in callback_refs}, key=_event_key),
    }
    return {"findings": findings, "coverage": coverage}


# --------------------------------------------------------------------------- review

def _esc(text: Any) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def render_markdown(plan: Mapping[str, Any], checks: Mapping[str, Any], events: Mapping[str, Mapping[str, Any]]) -> str:
    cov = checks["coverage"]
    lines = [f"# Narrative Plan — {plan['logline']}", "",
             f"- Sự kiện CORE được phủ: {cov['core_covered']}/{cov['core']}; SUPPORTING dùng: "
             f"{cov['supporting_used']}/{cov['supporting']}; callback: {cov['callbacks']} "
             f"(từ tìm kiếm M6: {', '.join(cov['callbacks_from_retrieval']) or 'không'})",
             f"- Tổng số từ dự kiến: {sum(b['target_words'] for b in plan['beats'])}", "",
             f"## Mở đầu (hook)", "", f"{plan['hook']['idea']} — {', '.join(plan['hook']['event_refs'])}", "",
             "## Các beat", ""]
    for index, beat in enumerate(plan["beats"], start=1):
        lines.append(f"### {index}. `{beat['id']}` — {beat['purpose']} ({beat['target_words']} từ)")
        for ref in beat["event_refs"]:
            event = events.get(ref, {})
            lines.append(f"- `{ref}` [{event.get('importance', '?')}] {event.get('text', '')}")
        if beat.get("emotional_note"):
            lines.append(f"- Cảm xúc: {beat['emotional_note']}")
        if beat.get("commentary_idea"):
            lines.append(f"- Bình luận: {beat['commentary_idea']}")
        lines.append("")
    if plan["callbacks"]:
        lines += ["## Callback", ""] + [f"- `{c['setup_ref']}` → `{c['payoff_ref']}`: {c['note']}"
                                         for c in plan["callbacks"]] + [""]
    lines += ["## Kiểm tra plan", ""]
    lines += [f"- [{f['severity']}] {f['message']}" for f in checks["findings"]] or ["Không có."]
    return "\n".join(lines) + "\n"


def render_html(plan: Mapping[str, Any], checks: Mapping[str, Any], events: Mapping[str, Mapping[str, Any]]) -> str:
    flagged: Dict[str, List[str]] = {}
    for finding in checks["findings"]:
        flagged.setdefault(finding["where"].split(".")[0], []).append(finding["message"])
    cov = checks["coverage"]
    parts = ["<!doctype html><html lang='vi'><head><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width, initial-scale=1'>",
             f"<title>Plan review</title><style>{_STYLE}.flag{{border-left:3px solid var(--med);padding-left:10px}}"
             "</style></head><body><main>",
             f"<h1>Narrative Plan</h1><p>{_esc(plan['logline'])}</p>",
             f"<div class='meta'>CORE {cov['core_covered']}/{cov['core']} · SUPPORTING {cov['supporting_used']}/"
             f"{cov['supporting']} · callback {cov['callbacks']} · "
             f"{sum(b['target_words'] for b in plan['beats'])} từ</div>",
             "<p class='muted'>Mỗi beat kèm các sự kiện brief nó kể và mã passage bằng chứng. Viền vàng là beat có "
             "cảnh báo. Sửa bằng <code>plan_review_form.md</code>.</p>",
             f"<h2>Hook</h2><p>{_esc(plan['hook']['idea'])}</p>"
             + "".join(f"<span class='chip'>{_esc(r)}</span>" for r in plan["hook"]["event_refs"])]
    for message in flagged.get("hook", []):
        parts.append(f"<div class='finding MEDIUM'>{_esc(message)}</div>")
    for index, beat in enumerate(plan["beats"], start=1):
        css = "flag" if beat["id"] in flagged else ""
        rows = "".join(f"<div class='brief'><span class='chip'>{_esc(r)}</span><span class='chip'>"
                       f"{_esc(events.get(r, {}).get('importance', '?'))}</span>{_esc(events.get(r, {}).get('text', ''))}"
                       f" <span class='muted'>[{_esc(', '.join(events.get(r, {}).get('evidence', [])))}]</span></div>"
                       for r in beat["event_refs"])
        notes = "".join(f"<div class='muted'>{_esc(label)}: {_esc(beat.get(key))}</div>"
                        for key, label in (("emotional_note", "Cảm xúc"), ("commentary_idea", "Bình luận"))
                        if beat.get(key))
        warn = "".join(f"<div class='finding MEDIUM'>{_esc(m)}</div>" for m in flagged.get(beat["id"], []))
        parts.append(f"<section class='unit' id='{_esc(beat['id'])}'><div class='{css}'><div class='uid'>{index}. "
                     f"{_esc(beat['id'])} · {beat['target_words']} từ</div><div>{_esc(beat['purpose'])}</div>{notes}"
                     f"{warn}</div><div>{rows or '<div class=muted>Không có sự kiện (bình luận).</div>'}</div></section>")
    if plan["callbacks"]:
        parts.append("<h2>Callback</h2><ul>" + "".join(
            f"<li><code>{_esc(c['setup_ref'])}</code> → <code>{_esc(c['payoff_ref'])}</code> {_esc(c['note'])}</li>"
            for c in plan["callbacks"]) + "</ul>")
    parts.append("</main></body></html>")
    return "".join(parts)


def plan_review_form(plan: Mapping[str, Any]) -> str:
    lines = ["# Phiếu duyệt Narrative Plan", "",
             "Mỗi dòng là một beat. Đánh `[x]` sau `bỏ:` để bỏ beat; đổi `vị trí:` để chuyển beat tới vị trí đó "
             "(1 = đầu tiên); đổi `số từ:` để đổi độ dài; viết sau `ghi chú:` điều người viết cần lưu ý.",
             "Dòng không đổi gì là giữ nguyên. Sau đó chạy lại với `--resume <thư mục>`. Beat có sự kiện CORE "
             "không bỏ được.", ""]
    for index, beat in enumerate(plan["beats"], start=1):
        lines.append(f"- `{beat['id']}` bỏ: [ ] | vị trí: {index} | số từ: {beat['target_words']} | ghi chú: "
                     f"  <!-- {' '.join(beat['purpose'].split())} -->")
    return "\n".join(lines) + "\n"


def parse_plan_review(text: str) -> List[Dict[str, Any]]:
    entries = []
    for line in text.splitlines():
        match = _FORM_LINE.match(line)
        if not match:
            continue
        note = re.sub(r"<!--.*?-->", "", match.group("note")).strip()
        entries.append({"beat": match.group("beat"), "drop": match.group("drop") != " ",
                        "position": int(match.group("pos")), "words": int(match.group("words")), "note": note or None})
    return entries


def plan_review_edits(plan: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The entries that change something compared with `plan` (an unchanged form is no review)."""
    current = {b["id"]: (index, b["target_words"]) for index, b in enumerate(plan["beats"], start=1)}
    edits = []
    for entry in entries:
        index, words = current.get(entry["beat"], (None, None))
        if entry["drop"] or entry["note"] or index is None or entry["position"] != index or entry["words"] != words:
            edits.append(dict(entry))
    return edits


def apply_plan_review(plan: Mapping[str, Any], edits: Sequence[Mapping[str, Any]],
                      events: Mapping[str, Mapping[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, List[Dict[str, Any]]]]:
    """Apply the owner's beat edits; returns (plan, {"changes": [...], "rejected": [...]})."""
    reviewed = copy.deepcopy(dict(plan))
    beats = {b["id"]: b for b in reviewed["beats"]}
    changes: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    order = [b["id"] for b in reviewed["beats"]]
    moves = []
    for edit in edits:
        beat = beats.get(edit["beat"])
        if beat is None:
            rejected.append({**edit, "reason": "no such beat"})
            continue
        if edit["drop"]:
            core = [r for r in beat["event_refs"] if events.get(r, {}).get("importance") == "CORE"]
            if core:
                rejected.append({**edit, "reason": f"the beat holds CORE events {core}"})
            else:
                order.remove(beat["id"])
                changes.append({"beat": beat["id"], "change": "dropped"})
            continue
        if edit["words"] != beat["target_words"]:
            if edit["words"] < 20:
                rejected.append({**edit, "reason": "a beat needs at least 20 words"})
            else:
                changes.append({"beat": beat["id"], "change": "words", "before": beat["target_words"],
                                "after": edit["words"]})
                beat["target_words"] = edit["words"]
        if edit["note"]:
            beat["purpose"] = f"{beat['purpose']} (Ghi chú người duyệt: {edit['note']})"
            changes.append({"beat": beat["id"], "change": "note", "note": edit["note"]})
        moves.append(edit)
    for edit in moves:
        if edit["beat"] in order and order.index(edit["beat"]) + 1 != edit["position"]:
            order.remove(edit["beat"])
            order.insert(max(0, min(len(order), edit["position"] - 1)), edit["beat"])
            changes.append({"beat": edit["beat"], "change": "moved", "position": edit["position"]})
    reviewed["beats"] = [beats[b] for b in order]
    kept = set(order)
    reviewed["callbacks"] = [c for c in reviewed["callbacks"]
                             if any(c["payoff_ref"] in beats[b]["event_refs"] for b in kept)
                             or not any(c["payoff_ref"] in b["event_refs"] for b in plan["beats"])]
    return reviewed, {"changes": changes, "rejected": rejected}


def scan(plans: Iterable[Tuple[str, Mapping[str, Any], Sequence[Mapping[str, Any]], Optional[Mapping[str, Any]]]]
         ) -> Dict[str, List[Tuple[str, str]]]:
    """Findings by kind over saved runs: (run, message) pairs."""
    out: Dict[str, List[Tuple[str, str]]] = {}
    for name, plan, briefs, recap in plans:
        for finding in plan_checks(plan, briefs, recap)["findings"]:
            out.setdefault(finding["kind"], []).append((name, finding["message"]))
    return out
