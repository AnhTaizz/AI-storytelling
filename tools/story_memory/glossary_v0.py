"""Per-story name glossary: how each character is written in the script.

Briefs romanize names chapter by chapter, so one character can reach the script under
several spellings, and the right convention depends on the audience: Vietnamese viewers
know Chinese novels by Sino-Vietnamese names (Lâm Uyển Nhi), not pinyin (Lin Wan'er). The
glossary is the one place that decides. It lives next to the story memory
(`<memory root>/<story id>/glossary.yaml`) and is built from the roster. New characters are
added with their brief romanization; the owner can then edit `display` and `also_allowed`,
and those edits are never overwritten. The pipeline tells the writer to use the display
names (and the `pronoun`, when set, so episodes do not drift between "cậu" and "anh") and
flags any other known spelling of the same character.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml

GLOSSARY_FORMAT = "STORY_GLOSSARY/v0"
_LATIN = re.compile(r"^[^\W\d_]", re.UNICODE)


def glossary_path(memory_root: Path | str, story_id: str) -> Path:
    if not story_id or "/" in story_id or story_id.startswith("."):
        raise ValueError(f"invalid story id {story_id!r}")
    return Path(memory_root) / story_id / "glossary.yaml"


def _latin(name: str) -> bool:
    """Written in a Latin-based script (romanized), as opposed to kanji, kana or Hangul."""
    return bool(name) and all(ord(ch) < 0x2E80 for ch in name) and bool(_LATIN.match(name))


def _key(name: str) -> str:
    return " ".join(name.split()).casefold()


def load(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {"format": GLOSSARY_FORMAT, "characters": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if data.get("format") != GLOSSARY_FORMAT or not isinstance(data.get("characters"), list):
        raise ValueError(f"{path}: not a {GLOSSARY_FORMAT} file")
    for entry in data["characters"]:
        if not isinstance(entry.get("display"), str) or not entry["display"].strip():
            raise ValueError(f"{path}: every character needs a non-empty display name")
    return data


def sync(path: Path, roster: Dict[str, Any]) -> Dict[str, Any]:
    """Add roster characters that the glossary does not know yet, and write it back.

    A roster character is known when any of its names matches an entry's source names.
    Existing entries keep their display names and allowed variants: those are the owner's.
    New source names of a known character are added to its entry so later matching works.
    """
    glossary = load(path)
    changed = not path.is_file()
    for character in roster["characters"]:
        names = [character["name"], character["romanized_name"], *character.get("aliases", [])]
        keys = {_key(n) for n in names if n}
        entry = next((e for e in glossary["characters"]
                      if keys & {_key(n) for n in [*e["source_names"], e["display"], *e.get("also_allowed", [])]}),
                     None)
        if entry is None:
            glossary["characters"].append({
                "display": character["romanized_name"],
                "also_allowed": [n for n in character.get("aliases", []) if _latin(n)
                                 and _key(n) != _key(character["romanized_name"])],
                "source_names": [n for n in names if n and not _latin(n)],
                "first_chapter": character.get("first_chapter"),
                "pronoun": None,
                "confirmed": False,
            })
            changed = True
            continue
        for name in names:
            if name and not _latin(name) and name not in entry["source_names"]:
                entry["source_names"].append(name)
                changed = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        header = ("# Character names for the script. Edit `display` (and `also_allowed`) to choose the\n"
                  "# spelling viewers hear, for example Sino-Vietnamese names for a Chinese novel; set\n"
                  "# `pronoun` (cậu, cô, anh...) so every episode refers to the character the same way; then\n"
                  "# set confirmed: true. The pipeline adds new characters but never overwrites your edits.\n")
        path.write_text(header + yaml.safe_dump(glossary, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return glossary


def rules(glossary: Dict[str, Any]) -> str:
    """The instruction given to the writer (appended to the profile's name policy)."""
    if not glossary["characters"]:
        return ""
    lines = ["Character names: write each character exactly as listed here, never another romanization."]
    for entry in glossary["characters"]:
        source = ", ".join(entry["source_names"]) or "?"
        also = f" (also acceptable: {', '.join(entry['also_allowed'])})" if entry.get("also_allowed") else ""
        pronoun = f"; always refer to them as \"{entry['pronoun']}\"" if entry.get("pronoun") else ""
        lines.append(f"- {source} → {entry['display']}{also}{pronoun}")
    return "\n".join(lines)


def check(units: Sequence[Dict[str, str]], glossary: Dict[str, Any], roster: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Findings for every paragraph that writes a character under a spelling the glossary
    does not allow (any other romanization the briefs used for that character)."""
    findings: List[Dict[str, Any]] = []
    for entry in glossary["characters"]:
        allowed = {_key(entry["display"]), *(_key(n) for n in entry.get("also_allowed", []))}
        sources = {_key(n) for n in entry["source_names"]}
        wrong = set()
        for character in roster["characters"]:
            names = [character["name"], character["romanized_name"], *character.get("aliases", [])]
            if sources & {_key(n) for n in names} or _key(character["romanized_name"]) in allowed:
                wrong |= {n for n in names if n and _latin(n) and _key(n) not in allowed}
        # A wrong form that is part of an allowed one ("Amane" inside "Fujimiya Amane") is not wrong.
        wrong = {w for w in wrong if not any(_key(w) in a for a in allowed)}
        for unit in units:
            for form in sorted(wrong, key=len, reverse=True):
                if re.search(rf"(?<!\w){re.escape(form)}(?!\w)", unit["text"]):
                    findings.append({
                        "unit_id": unit["unit_id"], "claim": form, "claim_type": "UNSUPPORTED_STORY_CLAIM",
                        "failure_category": "OTHER", "severity": "MEDIUM", "brief_refs": [], "source": "glossary",
                        "concepts": [], "phrases": [],
                        "explanation": f"Tên \"{form}\" không theo bảng tên của truyện; nhân vật này phải viết là "
                                       f"\"{entry['display']}\".",
                        "suggested_fix": f"Thay \"{form}\" bằng \"{entry['display']}\".",
                    })
                    break
    return findings


_SENTENCE = re.compile(r"[^.!?…]+[.!?…]?")


def pronoun_check(units: Sequence[Dict[str, str]], glossary: Dict[str, Any], pronouns: Sequence[str],
                  exceptions: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """Sentences that refer to a named character with a pronoun the glossary does not give.

    Season S1 called Amane "cậu" in two episodes and "anh" in the third. A sentence is judged
    only when every glossary character it names has a pronoun, so a character whose pronoun
    is not set never causes a finding; any pronoun the glossary assigns to someone is
    allowed, since it may point at a character the sentence does not name. Nouns that start
    like a pronoun ("anh chàng") are blanked out first. `pronouns` comes from the script
    language's lexicon.
    """
    if not pronouns:
        return []
    findings = []
    for unit in units:
        for match in _SENTENCE.finditer(unit["text"]):
            sentence = match.group(0).strip()
            folded = sentence.casefold()
            named = [e for e in glossary["characters"]
                     if any(re.search(rf"(?<!\w){re.escape(n.casefold())}(?!\w)", folded)
                            for n in [e["display"], *e.get("also_allowed", [])] if n)]
            if not named or any(not e.get("pronoun") for e in named):
                continue
            for phrase in sorted(exceptions, key=len, reverse=True):
                folded = re.sub(rf"(?<!\w){re.escape(phrase)}(?!\w)", " ", folded)
            # A pronoun may point at a character the sentence does not name ("Mahiru đỡ cậu"),
            # so every pronoun the glossary assigns is allowed; others are drift.
            allowed = {e["pronoun"].casefold() for e in glossary["characters"] if e.get("pronoun")}
            wrong = [p for p in pronouns if p not in allowed and re.search(rf"(?<!\w){re.escape(p)}(?!\w)", folded)]
            if wrong:
                expected = ", ".join(f"{e['display']} là \"{e['pronoun']}\"" for e in named)
                findings.append({
                    "unit_id": unit["unit_id"], "claim": sentence, "claim_type": "UNSUPPORTED_STORY_CLAIM",
                    "failure_category": "OTHER", "severity": "MEDIUM", "brief_refs": [], "source": "glossary",
                    "concepts": [], "phrases": wrong,
                    "explanation": f"Câu dùng đại từ {', '.join(repr(w) for w in wrong)} trong khi bảng tên quy định "
                                   f"{expected}; các tập phải gọi nhân vật giống nhau.",
                    "suggested_fix": f"Đổi đại từ cho đúng bảng tên ({expected}).",
                })
    return findings


def confirmed(glossary: Dict[str, Any]) -> Optional[bool]:
    """True when the owner confirmed every name, False when some are still defaults, None when empty."""
    if not glossary["characters"]:
        return None
    return all(entry.get("confirmed") for entry in glossary["characters"])
