"""A self-contained HTML page for the owner's review of a run (review.html).

The M1 contract needs a person's verdict, and reading a script against its source in three
files is slow. The page puts each script paragraph next to the brief items its claims cite
and the source passages behind them, marks every finding on the sentence it is about, and
ends with the review form; a button copies the filled form as Markdown in the same layout as
review_form.md. Everything is inline: no network, no external files.
"""

from __future__ import annotations

import html
import json
from typing import Any, Dict, List, Mapping, Sequence, Tuple

SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW")

_STYLE = """
:root { --bg:#fbfbfa; --fg:#1d1d1f; --muted:#6b6b70; --card:#ffffff; --line:#e3e3e6;
        --mark:#fff2b3; --crit:#b3261e; --high:#c2410c; --med:#a16207; --low:#4b5563;
        --ok:#15803d; --chip:#eef1f5; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
        --bg:#141416; --fg:#ececf0; --muted:#a0a0a8; --card:#1d1d21; --line:#33333a;
        --mark:#5c4a00; --crit:#f2867d; --high:#fb923c; --med:#facc15; --low:#9ca3af;
        --ok:#4ade80; --chip:#2a2d33; } }
:root[data-theme="dark"] { --bg:#141416; --fg:#ececf0; --muted:#a0a0a8; --card:#1d1d21; --line:#33333a;
        --mark:#5c4a00; --crit:#f2867d; --high:#fb923c; --med:#facc15; --low:#9ca3af;
        --ok:#4ade80; --chip:#2a2d33; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
       font:15px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:1100px; margin:0 auto; padding:24px 16px 64px; }
h1 { font-size:1.4rem; margin:0 0 4px; } h2 { font-size:1.1rem; margin:32px 0 12px; }
.meta, .muted { color:var(--muted); font-size:.9rem; }
table { border-collapse:collapse; width:100%; font-size:.9rem; }
td, th { border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }
.unit { display:grid; grid-template-columns:minmax(0,1.2fr) minmax(0,1fr); gap:16px;
        background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; margin:12px 0; }
@media (max-width:760px) { .unit { grid-template-columns:1fr; } }
.uid { font-weight:600; color:var(--muted); font-size:.8rem; }
mark { background:var(--mark); color:inherit; border-radius:3px; padding:0 2px; }
.finding { border-left:3px solid var(--low); padding:4px 10px; margin:8px 0; font-size:.9rem; }
.finding.CRITICAL { border-color:var(--crit); } .finding.HIGH { border-color:var(--high); }
.finding.MEDIUM { border-color:var(--med); }
.sev { font-weight:600; font-size:.75rem; letter-spacing:.03em; }
.chip { display:inline-block; background:var(--chip); border-radius:999px; padding:0 8px; font-size:.75rem;
        margin-right:4px; }
.brief { font-size:.88rem; margin:6px 0; }
.src { font-size:.88rem; white-space:pre-wrap; margin:4px 0; }
details summary { cursor:pointer; color:var(--muted); font-size:.85rem; }
.PASS { color:var(--ok); font-weight:600; } .FLAG { color:var(--med); font-weight:600; }
.FAIL { color:var(--crit); font-weight:600; }
form .q { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px; margin:10px 0; }
form label { margin-right:12px; white-space:nowrap; }
textarea { width:100%; min-height:60px; background:var(--bg); color:var(--fg); border:1px solid var(--line);
           border-radius:6px; padding:6px; font:inherit; }
button { font:inherit; padding:8px 14px; border-radius:8px; border:1px solid var(--line);
         background:var(--chip); color:var(--fg); cursor:pointer; }
"""

_SCRIPT = """
(function () {
  var form = document.getElementById('review');
  var key = 'review:' + form.dataset.run;
  function save() {
    var data = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name) return;
      if ((el.type === 'radio') && !el.checked) return;
      data[el.name] = el.value;
    });
    try { localStorage.setItem(key, JSON.stringify(data)); } catch (e) {}
    return data;
  }
  try {
    var saved = JSON.parse(localStorage.getItem(key) || '{}');
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!(el.name in saved)) return;
      if (el.type === 'radio') el.checked = (el.value === saved[el.name]); else el.value = saved[el.name];
    });
  } catch (e) {}
  form.addEventListener('input', save);
  document.getElementById('copy').addEventListener('click', function () {
    var data = save();
    var questions = JSON.parse(form.dataset.questions);
    var lines = ['# Phiếu chấm kịch bản — ' + form.dataset.run, '', 'Người chấm: chủ dự án.', '',
                 '| Mục | Câu hỏi | Điểm (1–5) | Ghi chú |', '|---|---|---|---|'];
    questions.forEach(function (q) {
      var note = (data[q[0] + '_note'] || '').replace(/\\|/g, '/').replace(/\\n/g, ' ');
      lines.push('| ' + q[0] + ' | ' + q[1] + ' | ' + (data[q[0]] || '') + ' | ' + note + ' |');
    });
    lines.push('', 'Lỗi cụ thể (trích câu trong kịch bản → vì sao sai):', '', data.errors || '- ', '');
    var verdicts = ['Dùng được ngay', 'Sửa nhẹ', 'Sửa nhiều', 'Không dùng được'];
    lines.push('Kết luận: ' + verdicts.map(function (v) { return (data.verdict === v ? '☑ ' : '☐ ') + v; }).join(' '));
    var text = lines.join('\\n') + '\\n';
    document.getElementById('out').value = text;
    try { navigator.clipboard.writeText(text); } catch (e) {}
  });
})();
"""


def _esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _marked(paragraph: str, quotes: Sequence[str]) -> str:
    """The paragraph, escaped, with every finding's quote highlighted where it occurs."""
    spans: List[Tuple[int, int]] = []
    for quote in quotes:
        quote = quote.strip().rstrip(".!?…")
        at = paragraph.find(quote) if len(quote) >= 4 else -1
        if at >= 0:
            spans.append((at, at + len(quote)))
    spans.sort()
    merged: List[Tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    out, cursor = [], 0
    for start, end in merged:
        out += [_esc(paragraph[cursor:start]), "<mark>", _esc(paragraph[start:end]), "</mark>"]
        cursor = end
    out.append(_esc(paragraph[cursor:]))
    return "".join(out)


def _passage_order(passage_id: str) -> Tuple[int, ...]:
    """Story order of a passage id: "4.7" before "4.11"."""
    try:
        return tuple(int(part) for part in passage_id.split("."))
    except ValueError:
        return (10 ** 9,)


def brief_index(briefs: Sequence[Dict[str, Any]]) -> Dict[str, List[Tuple[str, str, List[str]]]]:
    """Ref -> (text, epistemic label, evidence) for every fact and event."""
    items: Dict[str, List[Tuple[str, str, List[str]]]] = {}
    for brief in briefs:
        n = brief["chapter_order"]
        for character in brief["characters"]:
            items[f"c{n}.{character['id']}"] = [(f["text"], f.get("epistemic", "EXPLICIT"), f["evidence"])
                                                for f in character["facts"]]
        for event in brief["events"]:
            items[f"c{n}.{event['id']}"] = [(event["summary"], event.get("epistemic", "EXPLICIT"),
                                             event["evidence"])]
    return items


def render_review_page(manifest: Mapping[str, Any], report: Mapping[str, Any],
                       units: Sequence[Mapping[str, str]], critic: Mapping[str, Any] | None,
                       briefs: Sequence[Dict[str, Any]], passages: Mapping[str, str],
                       questions: Sequence[Tuple[str, str]]) -> str:
    items = brief_index(briefs)
    refs_by_unit: Dict[str, List[str]] = {}
    for unit in (critic or {}).get("units", []):
        refs_by_unit[unit["unit_id"]] = sorted({r for c in unit["claims"] for r in c["brief_refs"]})
    findings_by_unit: Dict[str, List[Mapping[str, Any]]] = {}
    for finding in report.get("findings", []):
        findings_by_unit.setdefault(finding["unit_id"], []).append(finding)

    scope = manifest["scope"]
    parts = [
        "<!doctype html><html lang='vi'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>Review {_esc(manifest['run_id'])}</title><style>{_STYLE}</style></head><body><main>",
        f"<h1>Review — {_esc(manifest['run_id'])}</h1>",
        f"<div class='meta'>{_esc(scope['label'])} · story <code>{_esc(scope['story_id'])}</code> · "
        f"{_esc(manifest.get('status', ''))} · {len(units)} đoạn · "
        f"{sum(len(v) for v in findings_by_unit.values())} lỗi còn lại</div>",
        "<p class='muted'>Mỗi đoạn kịch bản nằm cạnh các mục brief mà đoạn đó trích và nguyên văn passage "
        "nguồn. Phần được tô là chỗ có lỗi do bộ kiểm tra báo. Bộ kiểm tra có thể bỏ sót: hãy đọc cả đoạn.</p>",
        "<h2>Các gate</h2><table><tr><th>Gate</th><th>Trạng thái</th></tr>",
    ]
    for gate, info in report.get("gates", {}).items():
        parts.append(f"<tr><td>{_esc(gate)}</td><td class='{_esc(info['status'])}'>{_esc(info['status'])}</td></tr>")
    parts.append("</table><h2>Kịch bản và nguồn</h2>")

    for unit in units:
        uid = unit["unit_id"]
        findings = sorted(findings_by_unit.get(uid, []),
                          key=lambda f: SEVERITY_ORDER.index(f["severity"]) if f["severity"] in SEVERITY_ORDER else 9)
        left = [f"<div class='uid'>{_esc(uid)}</div>",
                f"<div>{_marked(unit['text'], [f['claim'] for f in findings])}</div>"]
        for f in findings:
            left.append(f"<div class='finding {_esc(f['severity'])}'><span class='sev'>{_esc(f['severity'])}</span> "
                        f"<span class='chip'>{_esc(f.get('source', 'critic'))}</span>"
                        f"<span class='chip'>{_esc(f['claim_type'])}</span><br>{_esc(f['explanation'])}"
                        + (f"<br><span class='muted'>Gợi ý: {_esc(f['suggested_fix'])}</span>"
                           if f.get("suggested_fix") else "") + "</div>")
        right, evidence = [], []
        for ref in refs_by_unit.get(uid, []):
            for text, label, ev in items.get(ref, []):
                right.append(f"<div class='brief'><span class='chip'>{_esc(ref)}</span>"
                             f"<span class='chip'>{_esc(label)}</span>{_esc(text)}</div>")
                evidence += [e for e in ev if e not in evidence]
        evidence += [p for f in findings for p in f.get("passage_ids", []) if p not in evidence]
        evidence.sort(key=_passage_order)
        if evidence:
            source = "".join(f"<div class='src'><b>[{_esc(pid)}]</b> {_esc(passages.get(pid, '(không có)'))}</div>"
                             for pid in evidence)
            right.append(f"<details open><summary>Nguồn ({len(evidence)} passage)</summary>{source}</details>")
        if not right:
            right.append("<div class='muted'>Đoạn này không trích mục brief nào (bình luận hoặc dẫn chuyện).</div>")
        parts.append(f"<section class='unit' id='{_esc(uid)}'><div>{''.join(left)}</div>"
                     f"<div>{''.join(right)}</div></section>")

    gaps = report.get("brief_gaps", [])
    if gaps:
        parts.append("<h2>Brief bỏ sót</h2><p class='muted'>Critic báo các câu này là bịa vì brief không có; "
                     "đối chiếu nguồn tìm thấy chúng trong nguyên văn, nên chúng được giữ và không tính lỗi. "
                     "Hãy kiểm tra passage được dẫn.</p><table><tr><th>Đoạn</th><th>Câu</th><th>Nguồn</th></tr>")
        for gap in gaps:
            cited = "".join(f"<div class='src'><b>[{_esc(pid)}]</b> {_esc(passages.get(pid, '(không có)'))}</div>"
                            for pid in gap["passage_ids"])
            parts.append(f"<tr><td><a href='#{_esc(gap['unit_id'])}'>{_esc(gap['unit_id'])}</a></td>"
                         f"<td>{_esc(gap['claim'])}<br><span class='muted'>{_esc(gap['source_explanation'])}</span></td>"
                         f"<td>{cited}</td></tr>")
        parts.append("</table>")
    advisory = [(item, "rào đón bị bỏ") for item in report.get("source_hedge_review", [])]
    advisory += [(item, "mạnh hơn nguồn: " + ", ".join(item["phrases"]))
                 for item in report.get("source_strength_review", [])]
    if advisory:
        parts.append("<h2>Brief cần xem</h2><p class='muted'>Lỗi nằm sẵn trong brief thì critic không thấy, "
                     "vì critic so kịch bản với brief. Danh sách này chỉ để người đọc kiểm tra; khoảng một nửa "
                     "là báo nhầm.</p><table><tr><th>Mục</th><th>Vì sao</th><th>Nội dung</th></tr>")
        for item, why in advisory:
            parts.append(f"<tr><td>{_esc(item['ref'])}</td><td>{_esc(why)}</td><td>{_esc(item['text'])}</td></tr>")
        parts.append("</table>")
    parts.append(f"<h2>Phiếu chấm</h2><form id='review' data-run='{_esc(manifest['run_id'])}' "
                 f"data-questions='{_esc(json.dumps(list(questions), ensure_ascii=False))}' "
                 f"onsubmit='return false'>")
    for key, question in questions:
        scores = "".join(f"<label><input type='radio' name='{_esc(key)}' value='{n}'> {n}</label>" for n in range(1, 6))
        parts.append(f"<div class='q'><b>{_esc(key)}</b> — {_esc(question)}<br>{scores}"
                     f"<textarea name='{_esc(key)}_note' placeholder='Ghi chú'></textarea></div>")
    verdicts = "".join(f"<label><input type='radio' name='verdict' value='{_esc(v)}'> {_esc(v)}</label>"
                       for v in ("Dùng được ngay", "Sửa nhẹ", "Sửa nhiều", "Không dùng được"))
    parts += [
        "<div class='q'><b>Lỗi cụ thể</b> (trích câu trong kịch bản → vì sao sai)"
        "<textarea name='errors' placeholder='- \"câu\" → vì sao sai'></textarea></div>",
        f"<div class='q'><b>Kết luận</b><br>{verdicts}</div>",
        "<button type='button' id='copy'>Chép phiếu dạng Markdown</button>",
        "<p class='muted'>Dán kết quả vào <code>review_form.md</code> trong thư mục của lần chạy.</p>",
        "<textarea id='out' readonly placeholder='Phiếu Markdown sẽ hiện ở đây'></textarea>",
        f"</form></main><script>{_SCRIPT}</script></body></html>",
    ]
    return "".join(parts)
