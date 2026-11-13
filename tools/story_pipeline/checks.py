"""Deterministic script checks (no model): length, language integrity, clean deliverable.

These cover the mechanically checkable hard invariants of Script Quality Contract v0:
SQ-INV-14 (length), SQ-INV-15 (target-language integrity), SQ-INV-16 (clean deliverable).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List

# Hiragana, katakana, CJK ideographs, half-width katakana, CJK punctuation.
_CJK = re.compile(r"[　-〿぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]")
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


def cjk_characters(text: str) -> List[str]:
    return _CJK.findall(text)


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
    words = count_words(text)
    cjk = cjk_characters(text) if target_language != "ja" else []
    artifacts = find_artifacts(text)
    return {
        "word_count": words,
        "length_ok": min_words <= words <= max_words,
        "length_target": [min_words, max_words],
        "cjk_count": len(cjk),
        "cjk_sample": "".join(cjk[:20]),
        "language_ok": not cjk,
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
            f"language: script contains {report['cjk_count']} Japanese/Chinese characters "
            f"(e.g. {report['cjk_sample']!r}); write every name and word in the target language "
            f"using Latin romanization")
    for artifact in report["artifacts"]:
        errors.append(f"clean deliverable: remove {artifact}; sections must be plain spoken narration")
    return errors
