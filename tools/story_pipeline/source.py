"""Load the requested chapter range through the frozen M3 ingestion adapter.

Only chapters inside the requested scope are loaded, so nothing beyond the
spoiler boundary can reach any prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from tools.story_ingestion.light_novel_adapter_v0 import ingest_manifest_file


@dataclass(frozen=True)
class Passage:
    passage_id: str  # "<chapter order>.<paragraph ordinal>", e.g. "1.12"
    text: str


@dataclass(frozen=True)
class Chapter:
    order: int
    document_id: str
    title: str
    passages: Tuple[Passage, ...]

    @property
    def passage_ids(self) -> frozenset:
        return frozenset(p.passage_id for p in self.passages)

    def render(self) -> str:
        """Prompt rendering: one passage per line, prefixed by its id."""
        return "\n".join(f"[{p.passage_id}] {p.text}" for p in self.passages)


@dataclass(frozen=True)
class StoryScope:
    story_id: str
    source_language: str
    chapters: Tuple[Chapter, ...]

    @property
    def first(self) -> int:
        return self.chapters[0].order

    @property
    def last(self) -> int:
        return self.chapters[-1].order

    def label(self) -> str:
        if self.first == self.last:
            return f"chapter {self.first}"
        return f"chapters {self.first}-{self.last}"


def parse_range(text: str) -> Tuple[int, int]:
    """'3' -> (3, 3); '1-5' -> (1, 5)."""
    parts = text.split("-")
    if len(parts) == 1:
        start = end = int(parts[0])
    elif len(parts) == 2:
        start, end = int(parts[0]), int(parts[1])
    else:
        raise ValueError(f"invalid chapter range: {text!r}")
    if start < 1 or end < start:
        raise ValueError(f"invalid chapter range: {text!r}")
    return start, end


def load_scope(manifest_path: Path | str, chapter_range: Tuple[int, int],
               source_root: Optional[Path | str] = None) -> StoryScope:
    start, end = chapter_range
    result = ingest_manifest_file(Path(manifest_path),
                                  Path(source_root) if source_root else None)
    chapters: List[Chapter] = []
    for doc in result.documents:
        if not start <= doc.order <= end:
            continue
        passages = []
        for seg in doc.segments:
            loc = seg["locator"]
            text = doc.text[loc["char_start"]:loc["char_end_exclusive"]].strip()
            if text:
                passages.append(Passage(seg["position"]["display"], text))
        title = passages[0].text.splitlines()[0] if passages else f"chapter {doc.order}"
        chapters.append(Chapter(doc.order, doc.document_id, title, tuple(passages)))
    found = {c.order for c in chapters}
    missing = [n for n in range(start, end + 1) if n not in found]
    if missing:
        raise ValueError(f"chapters not in manifest: {missing}")
    return StoryScope(result.story_id, result.manifest.get("source_language", "unknown"),
                      tuple(chapters))
