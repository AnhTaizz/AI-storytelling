"""Language lexicons for the pipeline's deterministic checks.

Checks work on language-independent *concepts* (for example `degree_extreme` or
`reported`); each language contributes the phrases that express them in
`tools/story_pipeline/lexicons/<code>.yaml`. Comparing concepts rather than words lets a
script in one language be checked against a brief or a source in another. Supporting a new
language means adding one YAML file; tests/story_pipeline validates every file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

import yaml

LEXICON_DIR = Path(__file__).resolve().parent / "lexicons"

# Words that raise degree, frequency, scope, certainty, firmness or reputation.
STRENGTH_CONCEPTS = frozenset({
    "degree_extreme", "completeness", "quantity_large", "universality", "frequency_always",
    "certainty", "firmness", "reputation", "intensity_fill",
})
# Markers that something is reported, only apparent, guessed, or figurative.
HEDGE_CONCEPTS = frozenset({"reported", "appearance", "speculation", "metaphor"})
KINDS = {"strength": STRENGTH_CONCEPTS, "hedge": HEDGE_CONCEPTS}


class LexiconError(ValueError):
    pass


@dataclass(frozen=True)
class Lexicon:
    language: str
    word_boundaries: bool
    chars_per_event: int  # source text length per expected brief event (scripts differ in density)
    phrases: Dict[str, Dict[str, Tuple[str, ...]]]  # kind -> concept -> phrases
    clause_markers: Tuple[str, ...] = ()  # conjunctions that start a new clause
    contrast_endings: Tuple[str, ...] = ()  # clause-final connectives that close a contrast ("…が、")
    contrast_openers: Tuple[str, ...] = ()  # words that open a contrasting part ("but …")

    def clauses(self, text: str) -> List[str]:
        """Split at punctuation and at this language's clause conjunctions."""
        parts = re.split(r"[,;.!?、。，；()（）]+", text)
        if self.clause_markers:
            alternatives = "|".join(re.escape(m) for m in sorted(self.clause_markers, key=len, reverse=True))
            pattern = rf"(?<!\w)(?:{alternatives})(?!\w)" if self.word_boundaries else f"(?:{alternatives})"
            parts = [piece for part in parts for piece in re.split(pattern, part, flags=re.IGNORECASE)]
        return [p.strip() for p in parts if p and p.strip()]

    def contrast_parts(self, text: str) -> List[str]:
        """Split text where a contrast starts or ends; joined, the parts give back `text`.

        A hedge belongs to its side of a contrast: in 「クラスが違うので詳しくは知らないが、
        噂通りなら…」 the rumour marker does not reach "different class" (live run 8).
        Text with no contrast stays one part, so hedges keep their whole-sentence reach.
        """
        parts: List[str] = []
        closed = True  # the previous piece ended a contrasting part
        for piece in (p for p in re.split(r"(?<=[,;、，；])", text) if p):
            if closed or self._opens_contrast(piece):
                parts.append(piece)
            else:
                parts[-1] += piece
            tail = re.sub(r"[\s,;、，；]+$", "", piece).casefold()
            closed = any(tail.endswith(e) for e in self.contrast_endings)
        return parts

    def _opens_contrast(self, piece: str) -> bool:
        head = piece.lstrip().casefold()
        return any(head.startswith(o) and not (self.word_boundaries and head[len(o):len(o) + 1].isalnum())
                   for o in self.contrast_openers)

    def find(self, text: str, kind: str) -> List[Tuple[str, str]]:
        """(concept, phrase) for every phrase of `kind` that occurs in `text`."""
        folded = text.casefold()
        found = []
        for concept, phrases in sorted(self.phrases.get(kind, {}).items()):
            for phrase in phrases:
                if self._occurs(phrase, folded):
                    found.append((concept, phrase))
        return found

    def concepts(self, text: str, kind: str) -> Set[str]:
        return {concept for concept, _ in self.find(text, kind)}

    def _occurs(self, phrase: str, folded: str) -> bool:
        if not self.word_boundaries:
            return phrase in folded
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", folded) is not None


def available_languages() -> List[str]:
    return sorted(p.stem for p in LEXICON_DIR.glob("*.yaml"))


def validate(data: dict, expected_language: str) -> List[str]:
    """Problems with one lexicon file (empty list when it is well-formed)."""
    problems = []
    if data.get("language") != expected_language:
        problems.append(f"language must be {expected_language!r}")
    if not isinstance(data.get("word_boundaries"), bool):
        problems.append("word_boundaries must be true or false")
    for field in ("clause_markers", "contrast_endings", "contrast_openers"):
        markers = data.get(field, [])
        if not isinstance(markers, list) or not all(
                isinstance(m, str) and m.strip() and m == m.casefold().strip() for m in markers):
            problems.append(f"{field} must be a list of non-empty, trimmed lowercase phrases")
    cpe = data.get("chars_per_event")
    if not isinstance(cpe, int) or isinstance(cpe, bool) or cpe <= 0:
        problems.append("chars_per_event must be a positive integer")
    seen: Dict[str, str] = {}
    for kind, allowed in KINDS.items():
        section = data.get(kind)
        if not isinstance(section, dict) or not section:
            problems.append(f"{kind} must map concepts to phrases")
            continue
        missing = sorted(allowed - set(section))
        unknown = sorted(set(section) - allowed)
        if missing:
            problems.append(f"{kind}: missing concepts {missing}")
        if unknown:
            problems.append(f"{kind}: unknown concepts {unknown}")
        for concept, phrases in section.items():
            if not isinstance(phrases, list) or not phrases:
                problems.append(f"{kind}.{concept}: needs at least one phrase")
                continue
            for phrase in phrases:
                if not isinstance(phrase, str) or not phrase.strip() or phrase != phrase.casefold().strip():
                    problems.append(f"{kind}.{concept}: phrase {phrase!r} must be non-empty, trimmed lowercase")
                elif phrase in seen:
                    problems.append(f"phrase {phrase!r} appears in both {seen[phrase]} and {kind}.{concept}")
                else:
                    seen[phrase] = f"{kind}.{concept}"
    return problems


def lexicon_code(language: str) -> str:
    """Primary subtag of a language tag: "zh-Hant" -> "zh", "KO" -> "ko"."""
    return language.split("-")[0].strip().lower()


@lru_cache(maxsize=None)
def load(language: str) -> Optional[Lexicon]:
    """The lexicon for a language tag (by its primary subtag), or None when there is none yet."""
    language = lexicon_code(language)
    path = LEXICON_DIR / f"{language}.yaml"
    if not language or not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    problems = validate(data, language)
    if problems:
        raise LexiconError(f"{path.name}: " + "; ".join(problems))
    phrases = {kind: {concept: tuple(values) for concept, values in data[kind].items()} for kind in KINDS}
    return Lexicon(language, data["word_boundaries"], data["chars_per_event"], phrases,
                   tuple(data.get("clause_markers", [])), tuple(data.get("contrast_endings", [])),
                   tuple(data.get("contrast_openers", [])))


def missing_languages(*languages: str) -> FrozenSet[str]:
    return frozenset(lang for lang in languages if load(lang) is None)
