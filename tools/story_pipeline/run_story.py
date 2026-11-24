"""Run a whole story episode by episode (a "season").

Each episode is one pipeline run (tools/story_pipeline/run_pipeline.py) in episode mode:
earlier chapters become a recap from story memory, and nothing after the episode is loaded.

    python -m tools.story_pipeline.run_story --chapters 1-5 --episodes 1,2-3,4-5 \\
        --model <chain> --season-dir .local/story_seasons/<name>

or `--episode-size 3` to cut the range into episodes of three chapters.

Running the same command again continues the season: completed episodes are skipped, an
interrupted one is resumed from its saved stage outputs. When the provider's quota runs out
the season stops cleanly (status PAUSED_QUOTA) so it can be continued later. The season
directory holds season.json and season.md (an index with each episode's report and review
page); story memory is shared across episodes as usual.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.story_memory.memory_v0 import StoryMemory  # noqa: E402
from tools.story_pipeline import run_pipeline  # noqa: E402
from tools.story_pipeline.facts import StoryFacts  # noqa: E402
from tools.story_pipeline.llm import QUOTA_PATTERN, LLMClient  # noqa: E402
from tools.story_pipeline.profile import NarrativeProfile, load_profile  # noqa: E402
from tools.story_pipeline.source import parse_range  # noqa: E402

SEASON_VERSION = "STORY_SEASON/v0"
DEFAULT_SEASON_ROOT = REPO / ".local" / "story_seasons"


def plan_episodes(first: int, last: int, episodes: Optional[str] = None,
                  episode_size: Optional[int] = None) -> List[Tuple[int, int]]:
    """Episode chapter ranges covering first..last, in order, without gaps or overlaps."""
    if episodes:
        ranges = [parse_range(part.strip()) for part in episodes.split(",") if part.strip()]
    else:
        size = 1 if episode_size is None else episode_size
        if size < 1:
            raise ValueError("episode size must be at least 1")
        ranges = [(start, min(start + size - 1, last)) for start in range(first, last + 1, size)]
    expected = first
    for start, end in ranges:
        if start != expected or end < start:
            raise ValueError(f"episodes must cover chapters {first}-{last} in order without gaps "
                             f"or overlaps; got {start}-{end} where {expected} was expected")
        expected = end + 1
    if expected != last + 1:
        raise ValueError(f"episodes stop at chapter {expected - 1}, but the season runs to {last}")
    return ranges


def episode_dir(season_dir: Path, index: int, chapters: Tuple[int, int]) -> Path:
    start, end = chapters
    return season_dir / (f"ep{index:02d}_ch{start}" if start == end else f"ep{index:02d}_ch{start}-{end}")


def _read_manifest(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads((path / "run_manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _episode_row(index: int, chapters: Tuple[int, int], path: Path, manifest: Optional[Dict[str, Any]],
                 season_dir: Path, skipped: bool = False) -> Dict[str, Any]:
    row: Dict[str, Any] = {"episode": index, "chapters": list(chapters),
                           "dir": str(path.relative_to(season_dir)), "status": "NOT_RUN"}
    if manifest is None:
        return row
    row.update({"status": manifest.get("status"), "calls": manifest.get("model_calls", 0),
                "seconds": manifest.get("seconds", 0), "error": manifest.get("error"),
                "skipped_as_completed": skipped,
                "tokens": (manifest.get("usage") or {}).get("total", {}).get("total", 0)})
    try:
        report = json.loads((path / "report.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return row
    row["gates_needing_review"] = sorted(g for g, info in report["gates"].items() if info["status"] != "PASS")
    row["findings_left"] = len(report.get("findings", []))
    row["word_count"] = report.get("final_check", {}).get("word_count")
    return row


def season_markdown(season: Dict[str, Any]) -> str:
    lines = [f"# Mùa truyện — {season['story_id']}", "",
             f"- Trạng thái: **{season['status']}**",
             f"- Chương {season['chapters'][0]}–{season['chapters'][1]}, {len(season['episodes'])} tập",
             f"- Tổng: {season['totals']['calls']} lần gọi mô hình, {season['totals']['tokens']:,} token, "
             f"{season['totals']['seconds']} giây (chỉ tính các lần chạy trong mùa này)", ""]
    if season.get("stop_reason"):
        lines += [f"> Dừng: {season['stop_reason']}", ""]
    lines += ["| Tập | Chương | Trạng thái | Từ | Lỗi còn lại | Gate cần xem | Mở |", "|---|---|---|---|---|---|---|"]
    for row in season["episodes"]:
        start, end = row["chapters"]
        links = (f"[báo cáo]({row['dir']}/report.md) · [review]({row['dir']}/review.html)"
                 if row.get("findings_left") is not None else "")
        gates = ", ".join(g.replace("GATE_", "") for g in row.get("gates_needing_review", [])) or "—"
        lines.append(f"| {row['episode']} | {start}–{end} | {row['status']} | {row.get('word_count') or '—'} | "
                     f"{row.get('findings_left', '—')} | {gates} | {links} |")
    return "\n".join(lines) + "\n"


def season_html(season: Dict[str, Any]) -> str:
    """The season index as a small self-contained page (review_page's colours and fonts)."""
    from html import escape
    from tools.story_pipeline.review_page import _STYLE

    cards = []
    for row in season["episodes"]:
        start, end = row["chapters"]
        links = (f"<a href='{escape(row['dir'])}/review.html'>Chấm (review)</a> · "
                 f"<a href='{escape(row['dir'])}/script_final.md'>Kịch bản</a> · "
                 f"<a href='{escape(row['dir'])}/report.md'>Báo cáo</a>") if row.get("findings_left") is not None else ""
        gates = ", ".join(g.replace("GATE_", "") for g in row.get("gates_needing_review", [])) or "không"
        status = escape(str(row["status"]))
        cards.append(f"<section class='q'><b>Tập {row['episode']}</b> · chương {start}–{end} · "
                     f"<span class='{status}'>{status}</span><br>"
                     f"<span class='muted'>{row.get('word_count') or '—'} từ · {row.get('findings_left', '—')} lỗi "
                     f"còn lại · gate cần xem: {escape(gates)}</span><br>{links}</section>")
    stop = f"<p class='muted'>Dừng: {escape(season['stop_reason'])}</p>" if season.get("stop_reason") else ""
    totals = season["totals"]
    return ("<!doctype html><html lang='vi'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>Mùa {escape(str(season['story_id']))}</title><style>{_STYLE}"
            ".COMPLETED{color:var(--ok);font-weight:600}.FAILED{color:var(--crit);font-weight:600}"
            "a{color:inherit}</style></head><body><main>"
            f"<h1>Mùa truyện — {escape(str(season['story_id']))}</h1>"
            f"<div class='meta'>{escape(season['status'])} · chương {season['chapters'][0]}–{season['chapters'][1]} · "
            f"{len(season['episodes'])} tập · {totals['calls']} lần gọi · {totals['tokens']:,} token</div>{stop}"
            f"<form>{''.join(cards)}</form>"
            "<p class='muted'>Chấm từng tập trong trang review của tập đó.</p></main></body></html>")


def run_season(client: LLMClient, manifest_path: Path | str, ranges: Sequence[Tuple[int, int]],
               profile: NarrativeProfile, season_dir: Path, *, memory: Optional[StoryMemory],
               source_root: Optional[str] = None, facts: Optional[StoryFacts] = None,
               stop_on_failure: bool = True, run: Callable[..., Dict[str, Any]] = run_pipeline.run,
               options: Optional[Dict[str, Any]] = None,
               progress: Callable[[str], None] = lambda message: None) -> Dict[str, Any]:
    """Run every episode in order and write season.json and season.md after each one."""
    season_dir.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    status, stop_reason, story_id = "COMPLETED", None, None
    totals = {"calls": 0, "tokens": 0, "seconds": 0.0}
    options = options or {}
    for index, chapters in enumerate(ranges, start=1):
        path = episode_dir(season_dir, index, chapters)
        previous = _read_manifest(path)
        scope, background = run_pipeline.episode_scope(manifest_path, chapters[0], chapters[1], source_root,
                                                       recap=True)
        story_id = scope.story_id
        review = options.get("owner_review")
        if previous and previous.get("status") == "COMPLETED" and not (
                review and run_pipeline.pending_owner_errors(path, review)):
            progress(f"episode {index} (chapters {chapters[0]}-{chapters[1]}): already completed")
            rows.append(_episode_row(index, chapters, path, previous, season_dir, skipped=True))
            continue
        progress(f"episode {index} (chapters {chapters[0]}-{chapters[1]})")
        started = time.time()
        episode_options = options
        if invocation := options.get("invocation"):
            # An episode can also be resumed through run_pipeline. Save its actual
            # spoiler scope and recap setting instead of the season-wide arguments.
            episode_invocation = invocation | {"chapters": f"{chapters[0]}-{chapters[1]}", "recap": True}
            episode_options = options | {"invocation": episode_invocation}
        manifest = run(client, scope, profile, path, facts=facts, resume=previous is not None,
                       background=background, memory=memory,
                       progress=lambda message, i=index: progress(f"  ep{i}: {message}"), **episode_options)
        row = _episode_row(index, chapters, path, manifest, season_dir)
        rows.append(row)
        totals["calls"] += row.get("calls", 0)
        totals["tokens"] += row.get("tokens", 0)
        totals["seconds"] = round(totals["seconds"] + (time.time() - started), 1)
        failed = manifest.get("status") == "FAILED"
        source_check_quota = manifest.get("source_check_quota_exhausted")
        if source_check_quota or (failed and QUOTA_PATTERN.search(manifest.get("error") or "")):
            stage = " khi đối chiếu nguyên tác" if source_check_quota else ""
            status = "PAUSED_QUOTA"
            stop_reason = f"tập {index} hết quota{stage}. Chạy lại cùng lệnh để tiếp tục từ chỗ dừng."
            break
        if failed:
            if stop_on_failure:
                status, stop_reason = "FAILED", f"tập {index} lỗi: {manifest.get('error')}"
                break
            status = "COMPLETED_WITH_FAILURES"
        _write_season(season_dir, story_id, ranges, rows, totals, "RUNNING", None)
    else:
        if any(r["status"] == "FAILED" for r in rows):
            status = "COMPLETED_WITH_FAILURES"
    rows += [_episode_row(i, c, episode_dir(season_dir, i, c), _read_manifest(episode_dir(season_dir, i, c)),
                          season_dir)
             for i, c in enumerate(ranges, start=1) if i > len(rows)]
    return _write_season(season_dir, story_id, ranges, rows, totals, status, stop_reason)


def _write_season(season_dir: Path, story_id: Optional[str], ranges: Sequence[Tuple[int, int]],
                  rows: List[Dict[str, Any]], totals: Dict[str, Any], status: str,
                  stop_reason: Optional[str]) -> Dict[str, Any]:
    season = {"season_version": SEASON_VERSION, "story_id": story_id, "status": status,
              "stop_reason": stop_reason, "chapters": [ranges[0][0], ranges[-1][1]],
              "episodes": rows, "totals": totals}
    (season_dir / "season.json").write_text(json.dumps(season, ensure_ascii=False, indent=1) + "\n",
                                            encoding="utf-8")
    (season_dir / "season.md").write_text(season_markdown(season), encoding="utf-8")
    (season_dir / "season.html").write_text(season_html(season), encoding="utf-8")
    (season_dir / "season_script.md").write_text(season_script(season_dir, rows), encoding="utf-8")
    return season


def season_script(season_dir: Path, rows: Sequence[Dict[str, Any]]) -> str:
    """Every finished episode's narration in order, to read the season as viewers hear it."""
    parts = ["# Kịch bản cả mùa", ""]
    for row in rows:
        path = season_dir / row["dir"] / "script_final.txt"
        label = f"## Tập {row['episode']} (chương {row['chapters'][0]}–{row['chapters'][1]})"
        body = path.read_text(encoding="utf-8").strip() if path.is_file() else "_(chưa có kịch bản)_"
        parts += [label, "", body, ""]
    return "\n".join(parts)


def build_parser() -> argparse.ArgumentParser:
    parser = run_pipeline.build_parser()
    parser.description = __doc__
    parser.add_argument("--episodes", default=None, help="comma list of chapter ranges, e.g. 1,2-3,4-5")
    parser.add_argument("--episode-size", type=int, default=None, help="chapters per episode (default 1)")
    parser.add_argument("--season-dir", default=None, help="season directory (default .local/story_seasons/<story>)")
    parser.add_argument("--keep-going", action="store_true",
                        help="continue with the next episode after a failure that is not a quota stop")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    first, last = parse_range(args.chapters)
    try:
        ranges = plan_episodes(first, last, args.episodes, args.episode_size)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    scope, _ = run_pipeline.episode_scope(args.manifest, first, first, args.source_root)
    destination = args.season_dir or args.resume
    season_dir = Path(destination) if destination else DEFAULT_SEASON_ROOT / scope.story_id
    previous = [_read_manifest(episode_dir(season_dir, index, chapters))
                for index, chapters in enumerate(ranges, start=1)]
    existing = [manifest for manifest in previous if manifest is not None]
    try:
        run_pipeline.prepare_routing(args, season_dir, existing[0] if existing else None)
        for manifest in existing[1:]:
            run_pipeline.check_routing_identity(args, manifest.get("invocation") or {})
    except ValueError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    client = run_pipeline.make_client(args)
    if client is None:
        return 2
    memory = None if args.no_memory else StoryMemory(args.memory, scope.story_id)
    profile = load_profile(args.profile).with_length(args.min_words, args.max_words)
    facts = StoryFacts.load(args.facts) if args.facts else None
    print(f"season dir: {season_dir}  episodes: {', '.join(f'{a}-{b}' for a, b in ranges)}", flush=True)
    options = run_pipeline.run_options(args)
    if args.locked:
        options["locked"] = True
    else:
        options["invocation"] = run_pipeline.invocation_of(args)
    season = run_season(client, args.manifest, ranges, profile, season_dir, memory=memory,
                        source_root=args.source_root, facts=facts, stop_on_failure=not args.keep_going,
                        options=options, progress=lambda m: print(m, flush=True))
    print(f"season: {season['status']}  calls: {season['totals']['calls']}  index: {season_dir / 'season.md'}")
    if season.get("stop_reason"):
        print(f"stopped: {season['stop_reason']}")
    return 0 if season["status"] in ("COMPLETED", "PAUSED_QUOTA") else 1


if __name__ == "__main__":
    raise SystemExit(main())
