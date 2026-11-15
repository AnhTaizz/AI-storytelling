"""Deterministic script checks (no model): length, language integrity, clean deliverable.

These cover the mechanically checkable hard invariants of Script Quality Contract v0:
SQ-INV-14 (length), SQ-INV-15 (target-language integrity), SQ-INV-16 (clean deliverable).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List

# Writing systems a script may contain only when its target language uses them. A name left
# in the source's own script (kanji, kana, Hangul, ...) is contamination in a Latin-script
# script (SQ-INV-15). Hangul was missing before; it was found while preparing Korean sources.
SCRIPTS = {
    "cjk_punctuation": "\u3000-\u303f",
    "han": "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff",
    "kana": "\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f",
    "hangul": "\u1100-\u11ff\u3130-\u318f\uac00-\ud7af",
    "thai": "\u0e00-\u0e7f",
    "cyrillic": "\u0400-\u04ff",
    "arabic": "\u0600-\u06ff",
}
LANGUAGE_SCRIPTS = {
    "ja": {"han", "kana", "cjk_punctuation"},
    "zh": {"han", "cjk_punctuation"},
    "ko": {"hangul", "han", "cjk_punctuation"},
    "th": {"thai"},
    "ru": {"cyrillic"},
    "uk": {"cyrillic"},
    "ar": {"arabic"},
}
# Languages written without spaces between words: length is counted in characters.
SPACELESS_LANGUAGES = {"ja", "zh", "th"}
_WORD = re.compile(r"\w", re.UNICODE)
_ARTIFACTS = [
    (re.compile(r"```"), "code fence"),
    (re.compile(r"^\s{0,3}#{1,6}\s", re.MULTILINE), "Markdown heading"),
    (re.compile(r"\*\*"), "Markdown bold marker"),
    (re.compile(r"\[[^\]]{0,40}\]"), "bracketed placeholder or stage note"),
    (re.compile(r"\{[^}]{0,40}\}"), "template placeholder"),
    (re.compile(r"\b(TODO|TBD|FIXME|PLACEHOLDER)\b", re.IGNORECASE), "unfinished marker"),
    (re.compile(r"\b(as an ai|language model|story brief|narrative plan|beat_id|B\d+:)", re.IGNORECASE),
     "pipeline or meta text"),
]


def count_words(text: str) -> int:
    """Whitespace tokens that contain at least one letter or digit."""
    return sum(1 for token in text.split() if _WORD.search(token))


def _base(language: str) -> str:
    return language.split("-")[0].strip().lower()


def foreign_script_characters(text: str, target_language: str) -> List[str]:
    """Characters from writing systems the target language does not use."""
    allowed = LANGUAGE_SCRIPTS.get(_base(target_language), set())
    ranges = "".join(r for name, r in SCRIPTS.items() if name not in allowed)
    return re.findall(f"[{ranges}]", text) if ranges else []


def count_length(text: str, target_language: str) -> int:
    """Words for languages that separate words with spaces; characters for the others."""
    if _base(target_language) in SPACELESS_LANGUAGES:
        return sum(1 for ch in text if not ch.isspace())
    return count_words(text)


def find_artifacts(text: str) -> List[str]:
    found = []
    for pattern, label in _ARTIFACTS:
        match = pattern.search(text)
        if match:
            found.append(f"{label}: {match.group(0)!r}")
    return found


def script_text(script: Dict[str, Any]) -> str:
    return "\n\n".join(section["text"].strip() for section in script["sections"])


def split_units(text: str) -> List[Dict[str, str]]:
    """Deterministic paragraph segmentation used as critic review units."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units = []
    for index, paragraph in enumerate(paragraphs, start=1):
        units.append({
            "unit_id": f"P{index:03d}",
            "sha256": hashlib.sha256(paragraph.encode("utf-8")).hexdigest()[:16],
            "text": paragraph,
        })
    return units


def check_script(script: Dict[str, Any], min_words: int, max_words: int,
                 target_language: str) -> Dict[str, Any]:
    text = script_text(script)
    words = count_length(text, target_language)
    foreign = foreign_script_characters(text, target_language)
    artifacts = find_artifacts(text)
    return {
        "word_count": words,
        "length_ok": min_words <= words <= max_words,
        "length_target": [min_words, max_words],
        "foreign_script_count": len(foreign),
        "foreign_script_sample": "".join(foreign[:20]),
        "language_ok": not foreign,
        "artifacts": artifacts,
        "clean_ok": not artifacts,
    }


def script_check_errors(report: Dict[str, Any]) -> List[str]:
    errors = []
    if not report["length_ok"]:
        lo, hi = report["length_target"]
        errors.append(
            f"length: script has {report['word_count']} words; required {lo}-{hi} words "
            f"(counted as whitespace-separated tokens across all sections)")
    if not report["language_ok"]:
        errors.append(
            f"language: script contains {report['foreign_script_count']} characters from a writing system "
            f"the target language does not use (e.g. {report['foreign_script_sample']!r}); write every "
            f"name and word in the target language "
            f"using Latin romanization")
    for artifact in report["artifacts"]:
        errors.append(f"clean deliverable: remove {artifact}; sections must be plain spoken narration")
    return errors
