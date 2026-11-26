"""Generate an offline Vietnamese review sheet for the DEV dataset."""
import argparse
from html import escape
import json
from pathlib import Path

from tools.model_bench.dataset import DIFFICULTIES, GROUPS, ROOT, case_sha256, load_dataset
from tools.model_bench.reporting import write_text

OUTPUT = ROOT / ".local" / "model_bench_review" / "review_v1.html"
GROUP_LABELS = dict(zip(GROUPS, ("Trích xuất sự kiện", "Phân biệt tên và cách xưng hô",
                                 "Quan hệ nhân quả", "Thứ tự sự kiện", "Phát hiện chi tiết bịa",
                                 "Phát hiện tiết lộ quá mốc", "Dàn ý kể chuyện", "Viết lời kể tiếng Việt",
                                 "Phát hiện và sửa lỗi kịch bản", "Đầu ra có cấu trúc")))
LEVEL_LABELS = dict(zip(DIFFICULTIES, ("Dễ", "Vừa", "Khó")))
DECISIONS = {"approved": "Duyệt", "needs_change": "Cần sửa", "rejected": "Từ chối"}

HEAD = """<!doctype html>
<html lang="vi">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Duyệt bộ ca benchmark DEV v1</title>
<style>
  :root { color-scheme: light dark; --bg: #f1f4f5; --paper: #fff; --ink: #183033;
          --muted: #4b6467; --line: #b8c8ca; --accent: #075b52; --mark: #f8e5a6; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #111b1c; --paper: #192829; --ink: #e1ecec; --muted: #b0c5c5;
            --line: #4a6566; --accent: #91e0d4; --mark: #534621; }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font: 1rem/1.6 system-ui, 'Segoe UI', sans-serif; }
  main { max-width: 62rem; padding: 2.5rem clamp(1rem, 4vw, 3rem); margin: auto; }
  h1, h2, h3, h4 { line-height: 1.25; }
  h1 { font-size: clamp(1.8rem, 5vw, 2.7rem); margin: 0 0 .5rem; }
  p { margin: .5rem 0 1rem; }
  .toolbar, article { padding: clamp(1rem, 3vw, 1.5rem); border: 1px solid var(--line);
                      background: var(--paper); border-radius: .55rem; margin-bottom: 1rem; }
  .toolbar { display: grid; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr));
             gap: .8rem; align-items: end; }
  label.control { display: grid; gap: .25rem; }
  input, select, textarea, button { font: inherit; }
  input:not([type=radio]), select, textarea, button { padding: .4rem .6rem; width: 100%;
      border: 1px solid var(--line); border-radius: .3rem; color: var(--ink); background: var(--bg); }
  button { cursor: pointer; color: var(--paper); background: var(--accent); font-weight: 650; }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  h2 { border-bottom: 1px solid var(--line); padding-bottom: .45rem; margin: 2rem 0 .8rem; }
  h3, legend { color: var(--accent); }
  article h4 { margin: 0; font-size: 1.1rem; overflow-wrap: anywhere; }
  blockquote { margin: .5rem 0 1rem; border-left: .2rem solid var(--line); padding-left: 1rem;
               white-space: pre-wrap; }
  mark { color: inherit; background: var(--mark); }
  pre { white-space: pre-wrap; overflow-wrap: anywhere; padding: .6rem .8rem; background: var(--bg); }
  fieldset { border: 1px solid var(--line); border-radius: .3rem; margin: 1rem 0 .7rem; }
  fieldset label { display: inline-block; margin-right: 1rem; }
  textarea { resize: vertical; }
  code, .meta { color: var(--muted); overflow-wrap: anywhere; }
  .meta { font-size: .87rem; }
  [hidden] { display: none !important; }
</style>
"""

SCRIPT = """<script>
const articles = Array.from(document.querySelectorAll('article'));
const byId = id => document.getElementById(id);
const matching = () => {
  const query = byId('search').value.trim().toLocaleLowerCase('vi');
  for (const card of articles) {
    card.hidden = (byId('group').value && card.dataset.group !== byId('group').value) ||
      (byId('level').value && card.dataset.level !== byId('level').value) ||
      !card.textContent.toLocaleLowerCase('vi').includes(query);
  }
  for (const section of document.querySelectorAll('section')) {
    section.hidden = !section.querySelector('article:not([hidden])');
  }
  const visible = articles.filter(card => !card.hidden).length;
  const decided = articles.filter(card => card.querySelector('input:checked')).length;
  byId('count').textContent = `Hiện ${visible}/${articles.length} ca · Đã chọn ${decided} ca`;
};
for (const id of ['search', 'group', 'level']) byId(id).addEventListener('input', matching);
document.querySelector('main').addEventListener('change', matching);
byId('export').addEventListener('click', () => {
  const reviewer = byId('reviewer').value.trim();
  if (!reviewer) { byId('reviewer').reportValidity(); byId('reviewer').focus(); return; }
  const date = new Date().toISOString().slice(0, 10);
  const cases = Object.create(null);
  for (const card of articles) {
    const decision = card.querySelector('input:checked');
    if (decision) cases[card.id] = {
      status: decision.value, reviewer, date, case_sha256: card.dataset.sha256,
      note: card.querySelector('textarea').value.trim()
    };
  }
  const payload = {dataset_sha256: byId('dataset').textContent, cases};
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2) + '\\n'],
                                           {type: 'application/json'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'GOLD_REVIEW.json';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
matching();
</script>
"""


def _highlight(passage, spans):
    merged = []
    for span in sorted(spans, key=lambda span: span["start"]):
        start, end = span["start"], span["end"]
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    segments, position = [], 0
    for start, end in merged:
        segments.extend((escape(passage[position:start]), "<mark>" + escape(passage[start:end]) + "</mark>"))
        position = end
    segments.append(escape(passage[position:]))
    return "".join(segments)


def _card(case):
    case_id = escape(case["id"])
    inputs = case["input"]
    radios = " ".join(f'<label><input type="radio" name="{case_id}" value="{value}"> {label}</label>'
                      for value, label in DECISIONS.items())
    key = "gold" if case["gold"] is not None else "rubric"
    gold = escape(json.dumps(case[key], ensure_ascii=False, indent=2))
    label = "Đáp án chuẩn" if key == "gold" else "Tiêu chí chấm của người duyệt"
    return f"""<article id="{case_id}" data-sha256="{case_sha256(case)}"
                     data-group="{case['group']}" data-level="{case['difficulty']}">
<h4>{case_id}</h4>
<p class="meta">{GROUP_LABELS[case['group']]} · {LEVEL_LABELS[case['difficulty']]}</p>
<strong>Đoạn trích</strong><blockquote>{_highlight(inputs['passage'], case['evidence_spans'])}</blockquote>
<p><strong>Yêu cầu</strong> {escape(inputs['instruction'])}</p>
<p><strong>Hành vi mong đợi</strong> {escape(case['expected_behaviour'])}</p>
<strong>{label}</strong><pre>{gold}</pre>
<p><strong>Cách chấm</strong> <code>{escape(case['scoring_method'])}</code></p>
<fieldset><legend>Quyết định</legend>{radios}</fieldset>
<label class="control">Ghi chú<textarea rows="2"></textarea></label>
</article>"""


def _options(labels):
    return '<option value="">Tất cả</option>' + "".join(
        f'<option value="{value}">{label}</option>' for value, label in labels.items())


def generate(path):
    dataset_hash, cases = load_dataset()
    parts = [HEAD, f"""<body><main>
<h1>Duyệt bộ ca benchmark DEV v1</h1>
<p>Các đoạn <mark>tô nền</mark> là bằng chứng có sẵn trong ca. Lưu các quyết định vào
<code>GOLD_REVIEW.json</code> trước khi đóng trang.</p>
<p class="meta">SHA-256 của bộ dữ liệu <code id="dataset">{dataset_hash}</code></p>
<div class="toolbar">
<label class="control">Tìm ca<input id="search" type="search" placeholder="Mã ca hoặc nội dung"></label>
<label class="control">Nhóm<select id="group">{_options(GROUP_LABELS)}</select></label>
<label class="control">Độ khó<select id="level">{_options(LEVEL_LABELS)}</select></label>
<label class="control">Người duyệt<input id="reviewer" required></label>
<button id="export" type="button">Xuất quyết định (JSON)</button>
<output id="count" aria-live="polite"></output>
</div>"""]
    for group, group_label in GROUP_LABELS.items():
        parts.append(f"<section><h2>{group_label}</h2>")
        for level, level_label in LEVEL_LABELS.items():
            parts.append(f"<section><h3>{level_label}</h3>")
            parts.extend(_card(case) for case in cases if (case["group"], case["difficulty"]) == (group, level))
            parts.append("</section>")
        parts.append("</section>")
    parts.extend(("</main>", SCRIPT, "</body></html>\n"))
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text(path, "\n".join(parts))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    generate(args.output)
    print(f"Phiếu duyệt: {args.output}")


if __name__ == "__main__":
    main()
