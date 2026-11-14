"""Story memory v0: a file-backed store of chapter briefs plus derived, spoiler-safe views.

Storage (one JSON file per chapter, under `<root>/<story_id>/chapters/`):
    {"format": "story_memory/v0", "chapter_order": 3, "source_version": "<sha256 of source bytes>",
     "brief_fingerprint": "<sha256 of brief prompts+schema+language>", "producer": "...", "brief": {...}}

A stored brief is reused only when both the source bytes and the brief-producing setup are
unchanged, so editing a chapter or the brief prompt invalidates exactly what it should.

Derived views are pure functions over a list of briefs. Callers decide which chapters to
pass; `as_of` and `recap_context` never look past the chapter they are given, so a view
built for an episode cannot contain later chapters.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

MEMORY_FORMAT = "story_memory/v0"


class StoryMemory:
    def __init__(self, root: Path | str, story_id: str) -> None:
        if not story_id or "/" in story_id or story_id.startswith("."):
            raise ValueError(f"invalid story id {story_id!r}")
        self.directory = Path(root) / story_id / "chapters"

    def _path(self, order: int) -> Path:
        return self.directory / f"chapter_{order:03d}.json"

    def get_brief(self, order: int, source_version: str, brief_fingerprint: str) -> Optional[Dict[str, Any]]:
        path = self._path(order)
        if not path.is_file():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if (record.get("format") != MEMORY_FORMAT or record.get("chapter_order") != order
                or record.get("source_version") != source_version
                or record.get("brief_fingerprint") != brief_fingerprint):
            return None
        return record["brief"]

    def put_brief(self, order: int, source_version: str, brief_fingerprint: str,
                  brief: Dict[str, Any], producer: str) -> Path:
        if brief.get("chapter_order") != order:
            raise ValueError(f"brief is for chapter {brief.get('chapter_order')}, not {order}")
        record = {"format": MEMORY_FORMAT, "chapter_order": order, "source_version": source_version,
                  "brief_fingerprint": brief_fingerprint, "producer": producer, "brief": brief}
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(order)
        # Write-then-rename so an interrupted run never leaves a half-written record.
        handle, tmp = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return path

    def stored_chapters(self) -> List[int]:
        if not self.directory.is_dir():
            return []
        return sorted(int(p.stem.split("_")[1]) for p in self.directory.glob("chapter_*.json"))


# --------------------------------------------------------------------------- views


def _names(character: Dict[str, Any]) -> Set[str]:
    raw = [character["romanized_name"], character["name"], *character.get("aliases", [])]
    return {" ".join(n.split()).casefold() for n in raw if n and n.strip()}


def as_of(briefs: Sequence[Dict[str, Any]], order: int) -> List[Dict[str, Any]]:
    """Briefs of chapters up to and including `order`, in chapter order."""
    return sorted((b for b in briefs if b["chapter_order"] <= order), key=lambda b: b["chapter_order"])


def build_roster(briefs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge chapter-local characters into one roster.

    Two chapter characters are the same person when they share any name, romanization or
    alias (case- and space-insensitive). A character matching several roster entries is
    merged into the earliest and reported, because that usually means an alias is shared.
    """
    entries: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for brief in sorted(briefs, key=lambda b: b["chapter_order"]):
        n = brief["chapter_order"]
        for character in brief["characters"]:
            names = _names(character)
            matches = [e for e in entries if e["_names"] & names]
            if len(matches) > 1:
                warnings.append(f"c{n}.{character['id']} ({character['romanized_name']}) matches several "
                                f"characters: {[e['romanized_name'] for e in matches]}; merged into the first")
            if matches:
                entry = matches[0]
                entry["_names"] |= names
                for alias in [character["name"], character["romanized_name"], *character.get("aliases", [])]:
                    if alias not in entry["aliases"] and alias not in (entry["name"], entry["romanized_name"]):
                        entry["aliases"].append(alias)
            else:
                entry = {"key": f"P{len(entries) + 1}", "name": character["name"],
                         "romanized_name": character["romanized_name"], "aliases": list(character.get("aliases", [])),
                         "first_chapter": n, "chapters": [], "refs": [], "facts": [], "_names": names}
                entries.append(entry)
            if n not in entry["chapters"]:
                entry["chapters"].append(n)
            entry["refs"].append(f"c{n}.{character['id']}")
            entry["facts"] += [{"chapter": n, **fact} for fact in character.get("facts", [])]
    for entry in entries:
        del entry["_names"]
    return {"characters": entries, "warnings": warnings}


def ref_index(roster: Dict[str, Any]) -> Dict[str, str]:
    """Chapter-local character ref ("c2.CH1") -> roster key ("P1")."""
    return {ref: entry["key"] for entry in roster["characters"] for ref in entry["refs"]}


def relationship_timeline(briefs: Sequence[Dict[str, Any]], roster: Dict[str, Any]) -> List[Dict[str, Any]]:
    """For each pair of roster characters, the relationship state stated in each chapter, in order."""
    refs = ref_index(roster)
    names = {e["key"]: e["romanized_name"] for e in roster["characters"]}
    pairs: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for brief in sorted(briefs, key=lambda b: b["chapter_order"]):
        n = brief["chapter_order"]
        for rel in brief["relationships"]:
            keys = [refs.get(f"c{n}.{cid}") for cid in rel["between"]]
            if None in keys or keys[0] == keys[1]:
                continue
            pair = tuple(sorted(keys))
            pairs.setdefault(pair, []).append({"chapter": n, "state": rel["state"], "evidence": rel["evidence"]})
    return [{"between": list(pair), "names": [names[k] for k in pair], "states": states}
            for pair, states in sorted(pairs.items())]


def recap_context(briefs: Sequence[Dict[str, Any]], before: int) -> Optional[Dict[str, Any]]:
    """Compact background for an episode that starts at chapter `before`.

    Only chapters strictly earlier than `before` contribute. Contains what a recap or a
    callback may use: per-chapter summary, ending state and CORE events (with refs), the
    merged roster, and the latest stated relationship between each pair.
    """
    earlier = [b for b in as_of(briefs, before - 1)]
    if not earlier:
        return None
    roster = build_roster(earlier)
    chapters = []
    for brief in earlier:
        n = brief["chapter_order"]
        chapters.append({
            "chapter": n,
            "summary": brief["chapter_summary"],
            "ending_state": brief["ending_state"],
            "core_events": [{"ref": f"c{n}.{e['id']}", "summary": e["summary"]}
                            for e in brief["events"] if e["importance"] == "CORE"],
            "unknowns": brief["unknowns"],
        })
    latest = [{"between": item["names"], "state": item["states"][-1]["state"],
               "as_of_chapter": item["states"][-1]["chapter"]}
              for item in relationship_timeline(earlier, roster)]
    return {
        "format": "story_memory_recap/v0",
        "covers_chapters": [b["chapter_order"] for b in earlier],
        "chapters": chapters,
        "characters": [{"name": e["name"], "romanized_name": e["romanized_name"], "aliases": e["aliases"],
                        "first_chapter": e["first_chapter"]} for e in roster["characters"]],
        "relationships_latest": latest,
        "roster_warnings": roster["warnings"],
    }


def recap_event_refs(recap: Optional[Dict[str, Any]]) -> Set[str]:
    if not recap:
        return set()
    return {e["ref"] for chapter in recap["chapters"] for e in chapter["core_events"]}
