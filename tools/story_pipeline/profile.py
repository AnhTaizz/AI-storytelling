"""Narrative Profile: per-channel presentation choices (Script Quality Contract v0, section 3)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULT_PROFILE_PATH = Path(__file__).resolve().parent / "profiles" / "vi_youtube_casual_v0.yaml"

LANGUAGE_NAMES = {"vi": "Vietnamese", "en": "English", "ja": "Japanese"}


@dataclass(frozen=True)
class NarrativeProfile:
    profile_id: str
    target_language: str
    brief_language: str
    audience: str
    narration: str
    tone: str
    humor_level: str
    commentary_intensity: str
    hook_style: str
    min_words: int
    max_words: int
    call_to_action: bool
    name_policy: str

    @property
    def target_language_name(self) -> str:
        return LANGUAGE_NAMES.get(self.target_language, self.target_language)

    @property
    def brief_language_name(self) -> str:
        return LANGUAGE_NAMES.get(self.brief_language, self.brief_language)

    def with_length(self, min_words: int | None, max_words: int | None) -> "NarrativeProfile":
        lo = self.min_words if min_words is None else min_words
        hi = self.max_words if max_words is None else max_words
        if lo < 1 or hi < lo:
            raise ValueError(f"invalid length range {lo}-{hi}")
        return replace(self, min_words=lo, max_words=hi)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def render(self) -> str:
        return yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False)


def load_profile(path: Path | str = DEFAULT_PROFILE_PATH) -> NarrativeProfile:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    length = data.pop("length_words")
    return NarrativeProfile(min_words=int(length["min"]), max_words=int(length["max"]),
                            call_to_action=bool(data.pop("call_to_action", False)), **data)
