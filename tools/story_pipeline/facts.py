"""Integration seam for upstream Story Extraction (M4): the `story_facts/v0` format.

The pipeline runs today with source passages only. When an extractor is selected,
project its output (for example a compiled Canonical Story batch viewed with
tools/canonical_story/view_v0.py) into this small format and pass it with
`--facts`. The Brief stage then receives the facts as hints next to the source,
and still has to cite source passages for everything it keeps.

Format:
{
  "format": "story_facts/v0",
  "chapters": [
    {"chapter_order": 1,
     "facts": [{"text": "...", "kind": "EVENT", "epistemic": "EXPLICIT",
                "evidence": ["1.12", "1.13"]}]}
  ]
}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from jsonschema import Draft202012Validator

FACTS_FORMAT = "story_facts/v0"

FACTS_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["format", "chapters"],
    "additionalProperties": False,
    "properties": {
        "format": {"const": FACTS_FORMAT},
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["chapter_order", "facts"],
                "additionalProperties": False,
                "properties": {
                    "chapter_order": {"type": "integer", "minimum": 1},
                    "facts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["text", "kind", "epistemic", "evidence"],
                            "additionalProperties": False,
                            "properties": {
                                "text": {"type": "string", "minLength": 1},
                                "kind": {"enum": ["EVENT", "STATE", "RELATION", "BELIEF",
                                                  "IDENTITY", "OTHER"]},
                                "epistemic": {"enum": ["EXPLICIT", "SUPPORTED_INFERENCE",
                                                       "REPORTED", "UNKNOWN"]},
                                "evidence": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                },
            },
        },
    },
}


class FactsError(ValueError):
    pass


class StoryFacts:
    def __init__(self, data: Dict[str, Any]) -> None:
        errors = [e.message for e in Draft202012Validator(FACTS_SCHEMA).iter_errors(data)]
        if errors:
            raise FactsError("invalid story_facts/v0: " + "; ".join(errors[:5]))
        self._by_chapter: Dict[int, List[Dict[str, Any]]] = {}
        for chapter in data["chapters"]:
            self._by_chapter.setdefault(chapter["chapter_order"], []).extend(chapter["facts"])

    @classmethod
    def load(cls, path: Path | str) -> "StoryFacts":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def for_chapter(self, order: int) -> List[Dict[str, Any]]:
        return list(self._by_chapter.get(order, []))

    def render_for_chapter(self, order: int) -> str:
        facts = self.for_chapter(order)
        if not facts:
            return ""
        lines = []
        for fact in facts:
            evidence = ",".join(fact["evidence"]) or "-"
            lines.append(f"- [{fact['kind']}/{fact['epistemic']}] {fact['text']} (evidence: {evidence})")
        return "\n".join(lines)
