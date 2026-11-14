"""Narrative Profile: per-channel presentation choices (Script Quality Contract v0, section 3)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from math import ceil, floor
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULT_PROFILE_PATH = Path(__file__).resolve().parent / "profiles" / "vi_light_novel_recap.yaml"

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
    plot_recap: bool = False
    length_ratio: tuple[float, float] | None = None

    @property
    def target_language_name(self) -> str:
        return LANGUAGE_NAMES.get(self.target_language, self.target_language)

    @property
    def brief_language_name(self) -> str:
        return LANGUAGE_NAMES.get(self.brief_language, self.brief_language)

    def with_length(self, min_words: int | None, max_words: int | None) -> "NarrativeProfile":
        if min_words is None and max_words is None:
            return self
        lo = self.min_words if min_words is None else min_words
        hi = self.max_words if max_words is None else max_words
        if lo < 1 or hi < lo:
            raise ValueError(f"invalid length range {lo}-{hi}")
        return replace(self, min_words=lo, max_words=hi, length_ratio=None)

    def for_full_length(self, full_units: int) -> "NarrativeProfile":
        """Convert the episode's full length in the target language into a spoken budget."""
        if self.length_ratio is None:
            raise ValueError("this profile uses a fixed length")
        lo, hi = self.length_ratio
        if full_units < 1:
            raise ValueError("full episode length must be positive")
        low = max(1, ceil(full_units * lo))
        high = max(low, floor(full_units * hi))
        return self.with_length(low, high)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def render(self) -> str:
        return yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False)


def load_profile(path: Path | str = DEFAULT_PROFILE_PATH) -> NarrativeProfile:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    length = data.pop("length_words")
    if "length_ratio" in data:
        lo, hi = data["length_ratio"]
        if not 0 < lo <= hi <= 1:
            raise ValueError("length_ratio must be an increasing range within (0, 1]")
        data["length_ratio"] = (lo, hi)
    return NarrativeProfile(min_words=int(length["min"]), max_words=int(length["max"]),
                            call_to_action=bool(data.pop("call_to_action", False)), **data)
