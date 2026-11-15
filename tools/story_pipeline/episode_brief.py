"""Episode Story Brief: the reviewable factual boundary of a requested scope (M7).

docs/TARGET_ARCHITECTURE.md puts a Story Brief between retrieval and the Narrative Plan and
lets the user "approve / edit / continue" before planning. The chapter briefs already are the
truth boundary; this module presents them as one episode-level document, deterministically:

- `build_episode_brief` gathers the episode's chapters (events, characters with facts,
  relationships, unknowns, forbidden inferences, closing hooks), an `uncertain` list of every
  item that is not EXPLICIT, and the earlier-chapter background (recap CORE events and M6
  callbacks). Every item keeps its ref (`c3.E2`, `c3.CH1.F2`, `c3.R1`, the scheme of
  tools/story_retrieval/brief_retrieval_v1.py) and its evidence passage ids.
- `render_markdown` / `render_html` show it to the owner; the page puts each item next to the
  source passages it cites.
- `brief_review_form` / `parse_brief_review` / `apply_brief_review`: the owner marks items
  wrong (with a correction) or to drop; the run applies those edits to its own briefs before
  planning and records every change. Story memory is never changed.
"""

from __future__ import annotations

import copy
import html
import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from tools.story_pipeline.review_page import _STYLE, _passage_order

FORMAT = "EPISODE_STORY_BRIEF/v1"
_REF = r"c\d+\.(?:E\d+|CH\d+\.F\d+|R\d+)"
_FORM_LINE = re.compile(rf"^\s*-\s*\[(?P<wrong>[ xX])\]\s*sai\s*\[(?P<drop>[ xX])\]\s*bỏ\s*`(?P<ref>{_REF})`(?P<rest>.*)$")
_ARROW = re.compile(r"\s(?:→|->)\s*")


def _display_names(glossary: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """Source name, romanization or alias (casefolded) -> the glossary's display name."""
    names: Dict[str, str] = {}
    for entry in (glossary or {}).get("characters", []):
        for name in [*entry.get("source_names", []), entry["display"], *entry.get("also_allowed", [])]:
            names.setdefault(str(name).casefold(), entry["display"])
    return names


def _display(character: Mapping[str, Any], names: Mapping[str, str]) -> str:
    for name in [character["name"], character["romanized_name"], *character.get("aliases", [])]:
        if str(name).casefold() in names:
            return names[str(name).casefold()]
    return character["romanized_name"]


def _chapter(brief: Mapping[str, Any], names: Mapping[str, str]) -> Dict[str, Any]:
    n = brief["chapter_order"]
    who = {c["id"]: _display(c, names) for c in brief["characters"]}
    events = [{"ref": f"c{n}.{e['id']}", "summary": e["summary"], "importance": e["importance"],
               "epistemic": e["epistemic"], "evidence": list(e["evidence"]),
               "participants": [who.get(p, p) for p in e.get("participants", [])],
               "location": e.get("location"), "consequence": e.get("consequence")} for e in brief["events"]]
    characters = [{"ref": f"c{n}.{c['id']}", "display": who[c["id"]], "name": c["name"],
                   "aliases": list(c.get("aliases", [])),
                   "facts": [{"ref": f"c{n}.{c['id']}.F{i}", "text": f["text"], "epistemic": f["epistemic"],
                              "evidence": list(f["evidence"])} for i, f in enumerate(c["facts"], start=1)]}
                  for c in brief["characters"]]
    relationships = [{"ref": f"c{n}.R{i}", "between": [who.get(c, c) for c in r["between"]], "state": r["state"],
                      "epistemic": r["epistemic"], "evidence": list(r["evidence"])}
                     for i, r in enumerate(brief["relationships"], start=1)]
    return {"chapter": n, "summary": brief["chapter_summary"], "ending_state": brief["ending_state"],
            "events": events, "characters": characters, "relationships": relationships,
            "unknowns": list(brief.get("unknowns", [])),
            "forbidden_inferences": list(brief.get("forbidden_inferences", [])),
            "closing_hook": brief.get("closing_hook")}


def build_episode_brief(scope: Any, briefs: Sequence[Mapping[str, Any]], recap: Optional[Mapping[str, Any]],
                        glossary: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The episode's declared factual boundary. `briefs` are the episode's chapter briefs;
    earlier chapters appear only through `recap` (marked as background)."""
    names = _display_names(glossary)
    chapters = [_chapter(b, names) for b in sorted(briefs, key=lambda b: b["chapter_order"])]
    uncertain = []
    for chapter in chapters:
        for event in chapter["events"]:
            if event["epistemic"] != "EXPLICIT":
                uncertain.append({"ref": event["ref"], "kind": "event", "text": event["summary"],
                                  "epistemic": event["epistemic"], "evidence": event["evidence"]})
        for character in chapter["characters"]:
            for fact in character["facts"]:
                if fact["epistemic"] != "EXPLICIT":
                    uncertain.append({"ref": fact["ref"], "kind": "fact", "text": f"{character['display']}: {fact['text']}",
                                      "epistemic": fact["epistemic"], "evidence": fact["evidence"]})
        for relation in chapter["relationships"]:
            if relation["epistemic"] != "EXPLICIT":
                uncertain.append({"ref": relation["ref"], "kind": "relationship",
                                  "text": f"{' – '.join(relation['between'])}: {relation['state']}",
                                  "epistemic": relation["epistemic"], "evidence": relation["evidence"]})
    background = None
    if recap:
        background = {"note": "earlier chapters (background, not this episode's content)",
                      "core_events": [dict(e, chapter=c["chapter"]) for c in recap.get("chapters", [])
                                      for e in c.get("core_events", [])],
                      "callbacks": [dict(c) for c in recap.get("callbacks", [])],
                      "relationships": [dict(r) for r in recap.get("relationships", [])]}
    orders = [c["chapter"] for c in chapters]
    counts = {"events": sum(len(c["events"]) for c in chapters),
              "core_events": sum(1 for c in chapters for e in c["events"] if e["importance"] == "CORE"),
              "facts": sum(len(ch["facts"]) for c in chapters for ch in c["characters"]),
              "relationships": sum(len(c["relationships"]) for c in chapters),
              "uncertain": len(uncertain),
              "unknowns": sum(len(c["unknowns"]) for c in chapters)}
    return {"format": FORMAT,
            "scope": {"story_id": getattr(scope, "story_id", None), "label": scope.label() if hasattr(scope, "label") else None,
                      "chapters": [min(orders), max(orders)] if orders else [], "spoiler_cutoff": max(orders, default=None)},
            "chapters": chapters, "uncertain": uncertain, "background": background, "counts": counts}


# --------------------------------------------------------------------------- rendering

def _items(episode: Mapping[str, Any]) -> List[Tuple[str, str, str, str, List[str]]]:
    """(ref, label, text, epistemic, evidence) for every reviewable item, in brief order."""
    out = []
    for chapter in episode["chapters"]:
        for e in chapter["events"]:
            out.append((e["ref"], f"sự kiện {e['importance']}", e["summary"], e["epistemic"], e["evidence"]))
        for c in chapter["characters"]:
            for f in c["facts"]:
                out.append((f["ref"], f"về {c['display']}", f["text"], f["epistemic"], f["evidence"]))
        for r in chapter["relationships"]:
            out.append((r["ref"], f"quan hệ {' – '.join(r['between'])}", r["state"], r["epistemic"], r["evidence"]))
    return out


def render_markdown(episode: Mapping[str, Any]) -> str:
    scope = episode["scope"]
    lines = [f"# Story Brief — {scope.get('label') or ''}", "",
             f"Truyện `{scope.get('story_id')}`, chương {scope['chapters'][0]}–{scope['chapters'][-1]} "
             f"(không dùng gì sau chương {scope['spoiler_cutoff']}).", "",
             "Đây là ranh giới sự thật mà plan và kịch bản phải theo. Mục có nhãn khác EXPLICIT là chưa chắc "
             "(lời đồn, vẻ bề ngoài, phỏng đoán, ẩn dụ) và phải giữ nguyên mức độ đó.", ""]
    for chapter in episode["chapters"]:
        lines += [f"## Chương {chapter['chapter']}", "", chapter["summary"], "", "### Sự kiện", ""]
        for e in chapter["events"]:
            label = "" if e["epistemic"] == "EXPLICIT" else f" _[{e['epistemic']}]_"
            lines.append(f"- `{e['ref']}` **{e['importance']}** {e['summary']}{label} — nguồn {', '.join(e['evidence'])}")
        lines += ["", "### Nhân vật", ""]
        for c in chapter["characters"]:
            lines.append(f"- **{c['display']}** ({c['name']})")
            for f in c["facts"]:
                label = "" if f["epistemic"] == "EXPLICIT" else f" _[{f['epistemic']}]_"
                lines.append(f"  - `{f['ref']}` {f['text']}{label} — nguồn {', '.join(f['evidence'])}")
        if chapter["relationships"]:
            lines += ["", "### Quan hệ", ""]
            for r in chapter["relationships"]:
                lines.append(f"- `{r['ref']}` {' – '.join(r['between'])}: {r['state']} — nguồn {', '.join(r['evidence'])}")
        if chapter["unknowns"]:
            lines += ["", "### Chưa biết", ""] + [f"- {u}" for u in chapter["unknowns"]]
        if chapter["forbidden_inferences"]:
            lines += ["", "### Không được suy ra", ""] + [f"- {u}" for u in chapter["forbidden_inferences"]]
        hook = chapter.get("closing_hook") or {}
        if hook.get("text"):
            lines += ["", f"**Cái móc cuối chương:** {hook['text']}"]
        lines.append("")
    if episode["uncertain"]:
        lines += ["## Mục chưa chắc chắn", ""]
        lines += [f"- `{u['ref']}` [{u['epistemic']}] {u['text']}" for u in episode["uncertain"]]
        lines.append("")
    background = episode.get("background")
    if background:
        lines += ["## Bối cảnh từ các chương trước", ""]
        lines += [f"- `{e['ref']}` {e['summary']}" for e in background["core_events"]]
        if background["callbacks"]:
            lines += ["", "Sự kiện cũ có thể gài lại (callback):", ""]
            lines += [f"- `{c['ref']}` {c['summary']} — nguồn {', '.join(c.get('evidence', []))}"
                      for c in background["callbacks"]]
        lines.append("")
    counts = episode["counts"]
    lines.append(f"Tổng: {counts['events']} sự kiện ({counts['core_events']} CORE), {counts['facts']} sự thật, "
                 f"{counts['relationships']} quan hệ, {counts['uncertain']} mục chưa chắc.")
    return "\n".join(lines) + "\n"


def _esc(text: Any) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def render_html(episode: Mapping[str, Any], passages: Mapping[str, str]) -> str:
    """Self-contained review page: every item beside the source passages it cites."""
    scope = episode["scope"]
    parts = ["<!doctype html><html lang='vi'><head><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width, initial-scale=1'>",
             f"<title>Story Brief {_esc(scope.get('label'))}</title><style>{_STYLE}"
             ".uncertain{border-left:3px solid var(--med);padding-left:10px}</style></head><body><main>",
             f"<h1>Story Brief — {_esc(scope.get('label'))}</h1>",
             f"<div class='meta'>story <code>{_esc(scope.get('story_id'))}</code> · không dùng gì sau chương "
             f"{_esc(scope.get('spoiler_cutoff'))} · {episode['counts']['uncertain']} mục chưa chắc</div>",
             "<p class='muted'>Mỗi mục nằm cạnh các đoạn nguồn nó trích. Mục viền vàng là chưa chắc chắn "
             "(lời đồn, vẻ bề ngoài, phỏng đoán, ẩn dụ). Sửa hoặc bỏ mục bằng <code>brief_review_form.md</code>.</p>"]
    for chapter in episode["chapters"]:
        parts.append(f"<h2>Chương {_esc(chapter['chapter'])}</h2><p>{_esc(chapter['summary'])}</p>")
        items = [i for i in _items(episode) if i[0].startswith(f"c{chapter['chapter']}.")]
        for ref, label, text, epistemic, evidence in items:
            css = "" if epistemic == "EXPLICIT" else " uncertain"
            source = "".join(f"<div class='src'><b>[{_esc(pid)}]</b> {_esc(passages.get(pid, '(không có)'))}</div>"
                             for pid in sorted(evidence, key=_passage_order))
            parts.append(f"<section class='unit' id='{_esc(ref)}'><div class='{css.strip()}'>"
                         f"<div class='uid'>{_esc(ref)}</div><span class='chip'>{_esc(label)}</span>"
                         f"<span class='chip'>{_esc(epistemic)}</span><div>{_esc(text)}</div></div>"
                         f"<div><details open><summary>Nguồn ({len(evidence)})</summary>{source}</details></div></section>")
        for title, values in (("Chưa biết", chapter["unknowns"]), ("Không được suy ra", chapter["forbidden_inferences"])):
            if values:
                parts.append(f"<h3>{title}</h3><ul>" + "".join(f"<li>{_esc(v)}</li>" for v in values) + "</ul>")
    background = episode.get("background")
    if background:
        parts.append("<h2>Bối cảnh từ các chương trước</h2><ul>")
        parts += [f"<li><code>{_esc(e['ref'])}</code> {_esc(e['summary'])}</li>" for e in background["core_events"]]
        parts += [f"<li><code>{_esc(c['ref'])}</code> (callback) {_esc(c['summary'])}</li>" for c in background["callbacks"]]
        parts.append("</ul>")
    parts.append("</main></body></html>")
    return "".join(parts)


# --------------------------------------------------------------------------- owner review

def brief_review_form(episode: Mapping[str, Any]) -> str:
    lines = [f"# Phiếu duyệt Story Brief — {episode['scope'].get('label') or ''}", "",
             "Mỗi dòng là một mục của brief. Để sửa: đánh `[x] sai` và viết nội dung đúng sau `→` ở cuối dòng.",
             "Để bỏ hẳn mục: đánh `[x] bỏ`. Dòng nào để trống là đúng. Sau đó chạy lại với `--resume <thư mục>`.", ""]
    current = None
    for ref, label, text, epistemic, _ in _items(episode):
        chapter = ref.split(".")[0]
        if chapter != current:
            current = chapter
            lines += ["", f"## Chương {chapter[1:]}", ""]
        tag = f"{label}, {epistemic}" if epistemic != "EXPLICIT" else label
        lines.append(f"- [ ] sai [ ] bỏ `{ref}` ({tag}) {' '.join(text.split())}")
    return "\n".join(lines) + "\n"


def parse_brief_review(text: str) -> List[Dict[str, Optional[str]]]:
    """Marked lines of a filled form: drop wins over correct; a correction is the text after
    the last arrow (None when the owner marked an item wrong without saying what is right)."""
    edits = []
    for line in text.splitlines():
        match = _FORM_LINE.match(line)
        if not match:
            continue
        drop, wrong = match.group("drop") != " ", match.group("wrong") != " "
        if drop:
            edits.append({"ref": match.group("ref"), "action": "drop", "text": None})
        elif wrong:
            pieces = _ARROW.split(match.group("rest"))
            correction = pieces[-1].strip() if len(pieces) > 1 else ""
            edits.append({"ref": match.group("ref"), "action": "correct", "text": correction or None})
    return edits


def _locate(briefs: Sequence[Dict[str, Any]], ref: str) -> Optional[Tuple[Dict[str, Any], str, Any]]:
    match = re.fullmatch(r"c(\d+)\.(?:(E\d+)|(CH\d+)\.F(\d+)|R(\d+))", ref)
    if not match:
        return None
    brief = next((b for b in briefs if b["chapter_order"] == int(match.group(1))), None)
    if brief is None:
        return None
    if match.group(2):
        event = next((e for e in brief["events"] if e["id"] == match.group(2)), None)
        return (brief, "event", event) if event else None
    if match.group(3):
        character = next((c for c in brief["characters"] if c["id"] == match.group(3)), None)
        index = int(match.group(4)) - 1
        if character is None or not 0 <= index < len(character["facts"]):
            return None
        return brief, "fact", character["facts"][index]
    index = int(match.group(5)) - 1
    return (brief, "relationship", brief["relationships"][index]) if 0 <= index < len(brief["relationships"]) else None


def apply_brief_review(briefs: Sequence[Mapping[str, Any]], edits: Sequence[Mapping[str, Any]]
                       ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Edited copies of the briefs and a record of every change. Refs are resolved against the
    unedited briefs, so dropping c2.CH1.F1 does not shift c2.CH1.F2. An unknown ref or a
    correction without text is reported and not applied."""
    edited = copy.deepcopy([dict(b) for b in briefs])
    changes, rejected, drops = [], [], []
    for edit in edits:
        target = _locate(edited, edit["ref"])
        if target is None:
            rejected.append({**edit, "reason": "no such item in this episode's briefs"})
            continue
        brief, kind, item = target
        if edit["action"] == "drop":
            drops.append((brief, kind, item))
            changes.append({"ref": edit["ref"], "action": "drop", "kind": kind,
                            "core_event_dropped": kind == "event" and item["importance"] == "CORE"})
        elif not edit.get("text"):
            rejected.append({**edit, "reason": "marked wrong without a correction after →"})
        else:
            field = {"event": "summary", "fact": "text", "relationship": "state"}[kind]
            changes.append({"ref": edit["ref"], "action": "correct", "kind": kind, "old": item[field],
                            "new": edit["text"]})
            item[field] = edit["text"]
    for brief, kind, item in drops:
        if kind == "event":
            brief["events"] = [e for e in brief["events"] if e is not item]
        elif kind == "fact":
            for character in brief["characters"]:
                character["facts"] = [f for f in character["facts"] if f is not item]
        else:
            brief["relationships"] = [r for r in brief["relationships"] if r is not item]
    return edited, {"changes": changes, "rejected": rejected}


def dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"
