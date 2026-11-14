"""Prepare raw chapter files for the frozen M3 adapter (LIGHT_NOVEL_INGESTION/v0).

M3 makes one passage from each run of non-blank lines. That fits sources that put a blank
line between paragraphs (the Japanese sample). Many web novels, Korean ones in particular,
end every paragraph with a single line break; M3 then turns a whole chapter into one
passage and evidence can no longer point at anything. This tool rewrites such files with a
blank line between paragraphs and writes the manifest M3 needs. M3 itself is unchanged; the
prepared files are the source of record, and SOURCE_PREPARATION.json keeps the hash of each
original file.

Usage (from the repository root):

    python -m tools.story_pipeline.prepare_source --input-dir <raw chapter files> \\
        --out .local/sources/<story> --story-id <id> --language ko

Then run the pipeline with `--manifest .local/sources/<story>/manifest.yaml`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.story_ingestion.light_novel_adapter_v0 import paragraph_spans, scan_lines  # noqa: E402

PREPARATION_VERSION = "SOURCE_PREPARATION/v0"
LAYOUTS = ("auto", "lines", "keep")
# A chapter whose paragraphs average this many lines is either hard-wrapped or uses one
# line per paragraph.
DENSE_LINES_PER_PARAGRAPH = 4.0
# In a one-line-per-paragraph file most lines end a sentence; in a hard-wrapped file few do.
SENTENCE_END_SHARE = 0.7
_SENTENCE_END = tuple(".!?…。！？」』”’\"')）")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,100}$")


def layout_stats(text: str) -> Dict[str, Any]:
    """How the text looks to M3: lines, paragraphs, and how many lines end a sentence."""
    lines = scan_lines(text)
    content = [text[line.char_start:line.char_end].strip() for line in lines if not line.blank]
    paragraphs = len(paragraph_spans(lines))
    ended = sum(1 for line in content if line.endswith(_SENTENCE_END))
    return {
        "lines": len(content),
        "paragraphs": paragraphs,
        "lines_per_paragraph": round(len(content) / paragraphs, 2) if paragraphs else 0.0,
        "sentence_end_share": round(ended / len(content), 2) if content else 0.0,
    }


def is_dense(stats: Dict[str, Any]) -> bool:
    return stats["lines_per_paragraph"] >= DENSE_LINES_PER_PARAGRAPH


def decide_layout(stats: Dict[str, Any], layout: str = "auto") -> str:
    """`lines` (each line becomes a paragraph) or `keep`."""
    if layout != "auto":
        return layout
    return "lines" if is_dense(stats) and stats["sentence_end_share"] >= SENTENCE_END_SHARE else "keep"


def split_lines_into_paragraphs(text: str) -> str:
    """Each non-blank line becomes its own paragraph; line content is kept exactly."""
    content = [text[line.char_start:line.char_end] for line in scan_lines(text) if not line.blank]
    return "\n\n".join(content) + "\n"


def layout_warning(label: str, text: str) -> Optional[str]:
    """A warning when M3 would pack many lines into few passages, else None."""
    stats = layout_stats(text)
    if not is_dense(stats):
        return None
    return (f"{label}: {stats['lines']} lines in {stats['paragraphs']} passage(s); the source "
            f"probably ends paragraphs with a single line break. Prepare it with "
            f"python -m tools.story_pipeline.prepare_source")


def _natural_key(path: Path) -> List[Any]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", path.name)]


def prepare(files: Sequence[Path], out_dir: Path, story_id: str, language: str,
            layout: str = "auto") -> Dict[str, Any]:
    """Write prepared chapter files, manifest.yaml and SOURCE_PREPARATION.json into `out_dir`."""
    if layout not in LAYOUTS:
        raise ValueError(f"layout must be one of {LAYOUTS}")
    if not _ID.match(story_id):
        raise ValueError(f"story id {story_id!r} must be letters, digits and . _ : - only")
    if not files:
        raise ValueError("no chapter files given")
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    documents, records = [], []
    for order, path in enumerate(sorted(files, key=_natural_key), start=1):
        original = path.read_bytes()
        text = original.decode("utf-8-sig")
        stats = layout_stats(text)
        if not stats["lines"]:
            raise ValueError(f"{path.name} has no text")
        decision = decide_layout(stats, layout)
        prepared = (split_lines_into_paragraphs(text) if decision == "lines" else text).encode("utf-8")
        name = f"chapter_{order:03d}.txt"
        (raw_dir / name).write_bytes(prepared)
        sha = hashlib.sha256(prepared).hexdigest()
        documents.append({"document_id": f"srcdoc-{story_id}-{order:04d}", "order": order,
                          "path": f"raw/{name}", "expected_sha256": sha,
                          "editorial_label": f"Document {order}"})
        records.append({
            "order": order, "original_name": path.name,
            "original_sha256": hashlib.sha256(original).hexdigest(), "prepared_sha256": sha,
            "layout": decision, "before": stats, "after": layout_stats(prepared.decode("utf-8")),
            "warning": layout_warning(name, prepared.decode("utf-8")),
        })
    manifest = {"contract_version": "LIGHT_NOVEL_INGESTION/v0", "story_id": story_id,
                "stream_id": f"stream-{story_id}-main", "source_language": language,
                "documents": documents}
    (out_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
                                           encoding="utf-8")
    record = {"preparation_version": PREPARATION_VERSION, "requested_layout": layout, "documents": records}
    (out_dir / "SOURCE_PREPARATION.json").write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n",
                                                     encoding="utf-8")
    return record


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", type=Path, required=True, help="directory of raw chapter .txt files")
    parser.add_argument("--out", type=Path, required=True, help="output directory (keep it under .local/)")
    parser.add_argument("--story-id", required=True)
    parser.add_argument("--language", required=True, help="source language tag, for example ko or ja")
    parser.add_argument("--layout", choices=LAYOUTS, default="auto",
                        help="auto: detect one-line-per-paragraph files; lines: always split; keep: never")
    args = parser.parse_args(argv)
    try:
        record = prepare(sorted(args.input_dir.glob("*.txt")), args.out, args.story_id, args.language,
                         args.layout)
    except (ValueError, UnicodeDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for doc in record["documents"]:
        print(f"{doc['original_name']} -> chapter_{doc['order']:03d}.txt  layout={doc['layout']}  "
              f"passages {doc['before']['paragraphs']} -> {doc['after']['paragraphs']}")
        if doc["warning"]:
            print(f"  warning: {doc['warning']}")
    print(f"manifest: {args.out / 'manifest.yaml'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
