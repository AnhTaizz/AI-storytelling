"""Pipeline stages: prompt rendering plus semantic validation for each model call."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from string import Template
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from tools.story_memory.memory_v0 import recap_event_refs
from tools.story_pipeline import checks, lexicon
from tools.story_pipeline.facts import StoryFacts
from tools.story_pipeline.llm import CallLog, LLMClient, run_json_stage
from tools.story_pipeline.profile import LANGUAGE_NAMES, NarrativeProfile
from tools.story_pipeline.source import Chapter, StoryScope

REPO = Path(__file__).resolve().parents[2]
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
SCHEMA_DIR = REPO / "schemas" / "story_pipeline"

PROBLEM_TYPES = {"UNSUPPORTED_STORY_CLAIM", "STRENGTHENED_STORY_CLAIM",
                 "CONTRADICTED_STORY_CLAIM", "UNDETERMINED"}


def load_schema(name: str) -> Dict[str, Any]:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def render(name: str, **values: Any) -> str:
    return Template(load_prompt(name)).substitute(**values)


def brief_fingerprint(profile: NarrativeProfile) -> str:
    """Identity of everything that shapes a chapter brief except the model and the source."""
    digest = hashlib.sha256()
    for path in (PROMPT_DIR / "brief_system.md", PROMPT_DIR / "brief_user.md",
                 SCHEMA_DIR / "story_brief_v0.schema.json"):
        digest.update(path.read_bytes())
    digest.update(profile.brief_language.encode("utf-8"))
    return digest.hexdigest()


def prompt_fingerprints() -> Dict[str, str]:
    """sha256 of every prompt and schema file, recorded in the run manifest."""
    out = {}
    for path in sorted(PROMPT_DIR.glob("*.md")) + sorted(SCHEMA_DIR.glob("*.json")):
        out[str(path.relative_to(REPO))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


# --------------------------------------------------------------------------- briefs


def brief_semantic_errors(brief: Dict[str, Any], chapter: Chapter, source_language: Optional[str] = None,
                          brief_language: Optional[str] = None) -> List[str]:
    errors: List[str] = []
    if brief["chapter_order"] != chapter.order:
        errors.append(f"chapter_order must be {chapter.order}")
    valid_ids = chapter.passage_ids
    texts = {p.passage_id: p.text for p in chapter.passages}

    def check_evidence(where: str, evidence: Sequence[str], quote: str = "") -> None:
        bad = [e for e in evidence if e not in valid_ids]
        if bad:
            errors.append(f"{where}: evidence ids {bad} are not passages of chapter "
                          f"{chapter.order} (valid ids look like '{chapter.order}.1')")
            return
        if not quote_in_passages(quote, [texts[e] for e in evidence]):
            errors.append(f"{where}: quote {quote!r} does not appear verbatim in its cited passages "
                          f"{list(evidence)}; copy an exact excerpt from one of them")

    char_ids = [c["id"] for c in brief["characters"]]
    if len(set(char_ids)) != len(char_ids):
        errors.append("character ids must be unique")
    for character in brief["characters"]:
        for index, fact in enumerate(character["facts"]):
            check_evidence(f"characters {character['id']} facts[{index}]", fact["evidence"], fact["quote"])
    for index, rel in enumerate(brief["relationships"]):
        missing = [c for c in rel["between"] if c not in char_ids]
        if missing:
            errors.append(f"relationships[{index}] references unknown characters {missing}")
        check_evidence(f"relationships[{index}]", rel["evidence"], rel["quote"])
    event_ids = [e["id"] for e in brief["events"]]
    if len(set(event_ids)) != len(event_ids):
        errors.append("event ids must be unique")
    for event in brief["events"]:
        missing = [c for c in event["participants"] if c not in char_ids]
        if missing:
            errors.append(f"event {event['id']} references unknown characters {missing}")
        check_evidence(f"event {event['id']}", event["evidence"], event["quote"])
    if not any(e["importance"] == "CORE" for e in brief["events"]):
        errors.append("at least one event must have importance CORE")
    hook = brief["closing_hook"]
    if hook["text"]:
        if not hook["quote"] or not hook["evidence"]:
            errors.append("closing_hook: a closing hook needs a verbatim quote and its evidence passages")
        else:
            check_evidence("closing_hook", hook["evidence"], hook["quote"])
    if source_language and brief_language:
        errors += brief_hedge_errors(brief, chapter, source_language, brief_language)
    needed = min_events(chapter, source_language)
    if len(brief["events"]) < needed:
        errors.append(f"events: a chapter of {len(chapter.passages)} passages "
                      f"({chapter_length(chapter)} characters) needs at least {needed} events "
                      f"at the level of single actions and dialogue turns; you listed {len(brief['events'])}. "
                      f"Split merged events: each refusal, offer, decision, reveal or change of place is "
                      f"its own event")
    return errors


_SOURCE_SENTENCE = re.compile(r"[^.!?。！？]+[.!?。！？]*")
# Quoted speech in common scripts: Japanese brackets, curly and straight quotes, guillemets.
_DIALOGUE = re.compile(r"「[^」]*」|『[^』]*』|“[^”]*”|‘[^’]*’|\"[^\"]*\"|«[^»]*»")


def _quoted_sentences(quote: str, passages: Sequence[str]) -> str:
    """The source sentence(s) a quote was taken from (whitespace-insensitive)."""
    needle = _squash(quote).strip("「」『』\"'")
    for text in passages:
        if needle and needle in _squash(text):
            hits = [m.group(0) for m in _SOURCE_SENTENCE.finditer(text)
                    if (lambda sq: sq and (needle in sq or sq in needle))(_squash(m.group(0)))]
            return " ".join(hits) or text
    return ""


def _quote_scope(quote: str, sentence: str, lex: lexicon.Lexicon) -> str:
    """The parts of `sentence`, split at contrasts, that the quote overlaps.

    Hedges reach across a whole sentence but not across a contrast ("I don't know her well,
    but rumour says..."), so only those parts can hedge the quoted item.
    """
    needle = _squash(quote).strip("「」『』\"'")
    start = _squash(sentence).find(needle) if needle else -1
    if start < 0:
        return sentence
    end, offset, kept = start + len(needle), 0, []
    for part in lex.contrast_parts(sentence):
        length = len(_squash(part))
        if offset < end and offset + length > start:
            kept.append(part)
        offset += length
    return "".join(kept)


EPISTEMIC_LABELS = ("EXPLICIT", "REPORTED", "APPEARANCE", "SPECULATION", "FIGURATIVE")
LABEL_CONCEPT = {"REPORTED": "reported", "APPEARANCE": "appearance", "SPECULATION": "speculation",
                 "FIGURATIVE": "metaphor"}


def _labelled_items(brief: Dict[str, Any]) -> List[Tuple[str, str, str, List[str], str]]:
    """(where, text, quote, evidence, epistemic) for every fact, relationship and event."""
    items = []
    for character in brief["characters"]:
        for index, fact in enumerate(character["facts"]):
            items.append((f"characters {character['id']} facts[{index}]", fact["text"], fact["quote"],
                          fact["evidence"], fact.get("epistemic", "EXPLICIT")))
    for index, rel in enumerate(brief["relationships"]):
        items.append((f"relationships[{index}]", rel["state"], rel["quote"], rel["evidence"],
                      rel.get("epistemic", "EXPLICIT")))
    for event in brief["events"]:
        text = " ".join([event["summary"], event.get("consequence") or "", event["motivation"].get("text") or ""])
        items.append((f"event {event['id']}", text, event["quote"], event["evidence"],
                      event.get("epistemic", "EXPLICIT")))
    return items


def brief_hedge_errors(brief: Dict[str, Any], chapter: Chapter, source_language: str,
                       brief_language: str) -> List[str]:
    """Brief items must keep the source's hedging, and their epistemic label must agree.

    1. When the sentence an item quotes (on the quote's side of any contrast, see
       `_quote_scope`) marks it as reported, apparent, guessed or figurative
       (for example 「受けているらしく」), its `epistemic` label must not be EXPLICIT and its
       text must carry a hedge of that kind in the brief language. Live run 5's brief turned
       that hearsay into "frequently receives confessions".
    2. An item labelled anything but EXPLICIT must carry such a hedge in its text, whichever
       passage the hedge came from. This is what lets the model report hedges from cited
       passages it did not quote (live run 7) in a way the next stages can rely on.
    Phrases come from the lexicons; part 1 needs both languages' lexicons, part 2 only the
    brief language's (see audit_coverage).
    """
    src, dst = lexicon.load(source_language), lexicon.load(brief_language)
    texts = {p.passage_id: p.text for p in chapter.passages}
    errors = []
    for where, text, quote, evidence, label in _labelled_items(brief):
        rendered = dst.concepts(text, "hedge") if dst else set()
        kinds: Set[str] = set()
        if src is not None and dst is not None:
            sentence = _quote_scope(quote, _quoted_sentences(quote, [texts[e] for e in evidence if e in texts]),
                                    src)
            # Hedges inside dialogue are the character's way of speaking, not the narrator's
            # uncertainty (run 3: 「…気になるだろう」), so quoted speech is ignored.
            source_hedges = src.find(_DIALOGUE.sub(" ", sentence), "hedge")
            kinds = {concept for concept, _ in source_hedges}
            if kinds and label == "EXPLICIT":
                errors.append(f"{where}: the quoted source marks this as {sorted(kinds)} "
                              f"({', '.join(sorted({p for _, p in source_hedges}))}) but epistemic is EXPLICIT; "
                              f"set epistemic to "
                              f"{'FIGURATIVE' if 'metaphor' in kinds else 'REPORTED, APPEARANCE or SPECULATION'}")
        if dst is None:
            continue
        wanted = set(kinds)
        if label != "EXPLICIT":
            wanted.add(LABEL_CONCEPT[label])
        if not wanted:
            continue
        # A figure of speech must stay one. When the source marks several kinds at once, any
        # hedge will do: Korean 「붉어진 것처럼 보였다」 ("looked as if reddened") contains the
        # simile marker 처럼 but is an appearance (live run 11).
        required = {"metaphor"} if wanted == {"metaphor"} else set(lexicon.HEDGE_CONCEPTS)
        if rendered & required:
            continue
        examples = [p for c in sorted(wanted) for p in dst.phrases["hedge"].get(c, ())[:2]]
        errors.append(f"{where}: it is {label if label != 'EXPLICIT' else sorted(kinds)} but the text states it "
                      f"as plain fact; keep the hedge in the text (for example: {', '.join(examples)})")
    return errors


MAX_FACT_CLAUSES = 2
# A coordinated part this long is a statement of its own; a shorter one is a noun or adjective
# in a list ("trách nhiệm và cảm giác tội lỗi"). Words for spaced languages, else characters.
MIN_STATEMENT_WORDS = 5
MIN_STATEMENT_CHARS = 10


def _statements(text: str, lex: "lexicon.Lexicon") -> List[str]:
    """Coordinated parts of `text` that are long enough to be statements of their own."""
    def long_enough(part: str) -> bool:
        return (len(part.split()) >= MIN_STATEMENT_WORDS if lex.word_boundaries
                else len(_squash(part)) >= MIN_STATEMENT_CHARS)
    return [part for part in lex.coordinated_parts(text) if long_enough(part)]


def brief_atomicity_errors(brief: Dict[str, Any], brief_language: Optional[str]) -> List[str]:
    """Soft check: one fact per item. A fact that joins several clauses ("tops every exam
    and, reportedly, excels at sport") cannot carry one quote and one epistemic label. A fact
    labelled anything but EXPLICIT must be a single statement, because later checks treat the
    label as covering the whole fact."""
    lex = lexicon.load(brief_language) if brief_language else None
    if lex is None:
        return []
    errors = []
    for character in brief["characters"]:
        for index, fact in enumerate(character["facts"]):
            where = f"characters {character['id']} facts[{index}]"
            clauses = lex.clauses(fact["text"])
            label = fact.get("epistemic", "EXPLICIT")
            parts = _statements(fact["text"], lex)
            if len(clauses) > MAX_FACT_CLAUSES:
                errors.append(f"{where}: joins {len(clauses)} clauses; split it into separate facts, "
                              f"each with its own quote, evidence and epistemic")
            elif label != "EXPLICIT" and len(parts) > 1:
                # Live run 14: "reportedly worried, and sent messages" made the plain half a rumour too.
                errors.append(f"{where}: is {label} but joins {len(parts)} statements; a labelled fact must be "
                              f"one statement. Keep the {label.lower()} part here and put each other statement "
                              f"in its own fact with its own label")
    for event in brief["events"]:
        label = event.get("epistemic", "EXPLICIT")
        parts = _statements(event["summary"], lex)
        if label != "EXPLICIT" and len(parts) > 1:
            # A Korean season episode 2 brief joined "seemed to stop" and "bowed" under APPEARANCE,
            # and the script then hedged the plain bow ("dường như cúi đầu chào").
            errors.append(f"event {event['id']}: is {label} but joins {len(parts)} statements, so every part reads "
                          f"as {label.lower()}. Label the event by its main action (usually EXPLICIT) and keep the "
                          f"hedge words only on the part the source hedges, or split it into separate events")
    return errors


def _brief_free_text(brief: Dict[str, Any]) -> List[Tuple[str, str]]:
    """(where, text) for every field the brief writes in the brief language. Names, quotes
    and ids are left out: they are meant to keep the source script."""
    out = [("chapter_summary", brief.get("chapter_summary") or ""), ("ending_state", brief.get("ending_state") or ""),
           ("closing_hook", (brief.get("closing_hook") or {}).get("text") or "")]
    out += [(f"unknowns[{i}]", text) for i, text in enumerate(brief.get("unknowns", []))]
    out += [(f"forbidden_inferences[{i}]", text) for i, text in enumerate(brief.get("forbidden_inferences", []))]
    for character in brief["characters"]:
        out += [(f"characters {character['id']} facts[{i}]", f["text"]) for i, f in enumerate(character["facts"])]
    out += [(f"relationships[{i}]", r["state"]) for i, r in enumerate(brief["relationships"])]
    for event in brief["events"]:
        out += [(f"event {event['id']}", " ".join(str(event.get(k) or "") for k in ("summary", "consequence", "location"))),
                (f"event {event['id']} motivation", event["motivation"].get("text") or "")]
    return [(where, text) for where, text in out if isinstance(text, str) and text]


def brief_script_errors(brief: Dict[str, Any], brief_language: Optional[str]) -> List[str]:
    """Soft check: the brief's own text is in the brief language. Live runs 12 and 13 left
    Hangul (붉어) and a kanji (面) inside Vietnamese facts, from where they can reach the script."""
    if not brief_language:
        return []
    errors = []
    for where, text in _brief_free_text(brief):
        words = [w for w in text.split() if checks.foreign_script_characters(w, brief_language)]
        if words:
            errors.append(f"{where}: {', '.join(repr(w) for w in dict.fromkeys(words))} not written in "
                          f"{brief_language}; translate it (names stay in `name`, source text in `quote`)")
    return errors


PASSAGES_PER_EVENT = 15


def chapter_length(chapter: Chapter) -> int:
    return sum(len(_squash(p.text)) for p in chapter.passages)


def min_events(chapter: Chapter, source_language: Optional[str] = None) -> int:
    """Lower bound on brief events for a chapter.

    The first live run compressed 61 passages into 2 events, folding a character's refusal
    into "they talked briefly". The bound is measured in source characters with a density
    from the source language's lexicon (`chars_per_event`), because paragraphing differs
    across languages (Korean web novels often put every sentence on its own line). Without a
    lexicon it falls back to one event per 15 passages.
    """
    lex = lexicon.load(source_language) if source_language else None
    if lex is None:
        return max(2, -(-len(chapter.passages) // PASSAGES_PER_EVENT))
    return max(2, -(-chapter_length(chapter) // lex.chars_per_event))


_SPACE = re.compile(r"\s+")


def _squash(text: str) -> str:
    """Drop all whitespace (including full-width spaces) so line wrapping cannot break a match."""
    return _SPACE.sub("", text)


def quote_in_passages(quote: str, passages: Sequence[str]) -> bool:
    needle = _squash(quote).strip("「」『』\"'")
    return bool(needle) and any(needle in _squash(text) for text in passages)


def known_characters_text(briefs: Sequence[Dict[str, Any]]) -> str:
    seen: Dict[str, Dict[str, Any]] = {}
    for brief in briefs:
        for character in brief["characters"]:
            seen.setdefault(character["romanized_name"], character)
    if not seen:
        return "(none: this is the first chapter in scope)"
    return "\n".join(f"- {c['name']} / {c['romanized_name']} (aliases: {', '.join(c['aliases']) or '-'})"
                     for c in seen.values())


def run_brief(client: LLMClient, scope: StoryScope, chapter: Chapter, profile: NarrativeProfile,
              earlier_briefs: Sequence[Dict[str, Any]], facts: Optional[StoryFacts],
              log: CallLog, max_repairs: int) -> Dict[str, Any]:
    schema = load_schema("story_brief_v0")
    facts_block = ""
    if facts is not None:
        rendered = facts.render_for_chapter(chapter.order)
        if rendered:
            facts_block = ("\nUpstream extraction hints for this chapter (may be incomplete or "
                           "wrong: keep only what the source passages confirm, and cite them):\n"
                           f"{rendered}\n")
    system = render("brief_system",
                    source_language_name=LANGUAGE_NAMES.get(scope.source_language, scope.source_language),
                    example_id=f"{chapter.order}.12",
                    brief_language_name=profile.brief_language_name,
                    schema=dump(schema))
    user = render("brief_user", story_id=scope.story_id, chapter_order=chapter.order,
                  chapter_title=chapter.title, known_characters=known_characters_text(earlier_briefs),
                  facts_block=facts_block, chapter_text=chapter.render())
    return run_json_stage(client, stage="brief", system=system, user=user, schema=schema,
                          semantic_check=lambda b: brief_semantic_errors(b, chapter, scope.source_language,
                                                                         profile.brief_language),
                          soft_check=lambda b: (brief_atomicity_errors(b, profile.brief_language)
                                               + brief_script_errors(b, profile.brief_language)),
                          max_repairs=max_repairs, log=log, request_suffix=f"ch{chapter.order}")


def briefs_for_prompt(briefs: Sequence[Dict[str, Any]]) -> str:
    """Add global refs (c1.E3, c1.CH2) so later stages can cite brief items unambiguously."""
    out = []
    for brief in briefs:
        item = copy.deepcopy(brief)
        n = item["chapter_order"]
        for character in item["characters"]:
            character["ref"] = f"c{n}.{character['id']}"
        for event in item["events"]:
            event["ref"] = f"c{n}.{event['id']}"
        out.append(item)
    return dump(out)


NO_BACKGROUND = "(none: this episode starts at the beginning of the story)"


def background_text(recap: Optional[Dict[str, Any]]) -> str:
    """Earlier-chapter memory for an episode, rendered for prompts (see tools/story_memory)."""
    return dump(recap) if recap else NO_BACKGROUND


def event_index(briefs: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {f"c{b['chapter_order']}.{e['id']}": e for b in briefs for e in b["events"]}


# --------------------------------------------------------------------------- plan


def plan_semantic_errors(plan: Dict[str, Any], briefs: Sequence[Dict[str, Any]],
                         profile: NarrativeProfile, recap: Optional[Dict[str, Any]] = None) -> List[str]:
    """`briefs` are the episode's chapters; earlier CORE events in `recap` may be referenced
    (recap, callbacks) but only the episode's own CORE events must be covered."""
    errors: List[str] = []
    events = event_index(briefs)
    known = set(events) | recap_event_refs(recap)

    def check_refs(where: str, refs: Sequence[str]) -> None:
        bad = [r for r in refs if r not in known]
        if bad:
            errors.append(f"{where}: unknown event refs {bad}")

    check_refs("hook", plan["hook"]["event_refs"])
    beat_ids = [b["id"] for b in plan["beats"]]
    if len(set(beat_ids)) != len(beat_ids):
        errors.append("beat ids must be unique")
    covered = set()
    for beat in plan["beats"]:
        check_refs(f"beat {beat['id']}", beat["event_refs"])
        covered.update(beat["event_refs"])
    for index, cb in enumerate(plan["callbacks"]):
        check_refs(f"callbacks[{index}]", [cb["setup_ref"], cb["payoff_ref"]])
    omitted = [o["ref"] for o in plan["omitted_events"]]
    check_refs("omitted_events", omitted)
    core = [ref for ref, e in events.items() if e["importance"] == "CORE"]
    uncovered = [ref for ref in core if ref not in covered]
    if uncovered:
        errors.append(f"CORE events not covered by any beat: {uncovered}")
    omitted_core = [ref for ref in omitted if ref in events and events[ref]["importance"] == "CORE"]
    if omitted_core:
        errors.append(f"CORE events cannot be omitted: {omitted_core}")
    last = max(briefs, key=lambda b: b["chapter_order"]) if briefs else None
    if last is not None and last["closing_hook"]["text"] and not plan["closing_hook"]:
        errors.append(f"closing_hook: chapter {last['chapter_order']} ends on a closing hook "
                      f"({last['closing_hook']['text']!r}); say how the final beat lands it")
    total = sum(b["target_words"] for b in plan["beats"])
    if not profile.min_words <= total <= profile.max_words:
        errors.append(f"beat target_words sum to {total}; must be between "
                      f"{profile.min_words} and {profile.max_words}")
    return errors


def run_plan(client: LLMClient, scope: StoryScope, briefs: Sequence[Dict[str, Any]],
             profile: NarrativeProfile, log: CallLog, max_repairs: int,
             recap: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    schema = load_schema("narrative_plan_v0")
    system = render("plan_system", min_words=profile.min_words, max_words=profile.max_words,
                    target_language_name=profile.target_language_name, schema=dump(schema))
    user = render("plan_user", scope_label=scope.label(), profile=profile.render(),
                  briefs=briefs_for_prompt(briefs), background=background_text(recap))
    return run_json_stage(client, stage="plan", system=system, user=user, schema=schema,
                          semantic_check=lambda p: plan_semantic_errors(p, briefs, profile, recap),
                          max_repairs=max_repairs, log=log)


# --------------------------------------------------------------------------- script / revise


def script_structure_errors(script: Dict[str, Any], plan: Dict[str, Any]) -> List[str]:
    expected = [b["id"] for b in plan["beats"]]
    actual = [s["beat_id"] for s in script["sections"]]
    if actual != expected:
        return [f"sections must follow the plan beats exactly in order {expected}; got {actual}"]
    return []


def script_soft_errors(script: Dict[str, Any], profile: NarrativeProfile) -> List[str]:
    report = checks.check_script(script, profile.min_words, profile.max_words, profile.target_language)
    return checks.script_check_errors(report)


def _script_system(profile: NarrativeProfile) -> str:
    cta = ("End with a short call to action." if profile.call_to_action
           else "No call to action, no outro asking to like or subscribe: just end the story.")
    return render("script_system", target_language_name=profile.target_language_name,
                  name_policy=profile.name_policy, min_words=profile.min_words,
                  max_words=profile.max_words, cta_rule=cta, schema=dump(load_schema("script_v0")))


def run_script(client: LLMClient, scope: StoryScope, briefs: Sequence[Dict[str, Any]],
               plan: Dict[str, Any], profile: NarrativeProfile, log: CallLog,
               max_repairs: int, recap: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    user = render("script_user", scope_label=scope.label(), profile=profile.render(),
                  briefs=briefs_for_prompt(briefs), plan=dump(plan), background=background_text(recap))
    return run_json_stage(client, stage="script", system=_script_system(profile), user=user,
                          schema=load_schema("script_v0"),
                          semantic_check=lambda s: script_structure_errors(s, plan),
                          soft_check=lambda s: script_soft_errors(s, profile),
                          max_repairs=max_repairs, log=log, request_suffix="v1")


def findings_for_revision(critic: Dict[str, Any], severities: Sequence[str]) -> List[Dict[str, Any]]:
    out = []
    for unit in critic["units"]:
        for claim in unit["claims"]:
            if claim["claim_type"] in PROBLEM_TYPES and claim["claim_type"] != "UNDETERMINED" \
                    and claim["severity"] in severities:
                out.append({"unit_id": unit["unit_id"], **claim})
    return out


def run_revision(client: LLMClient, scope: StoryScope, briefs: Sequence[Dict[str, Any]],
                 plan: Dict[str, Any], script: Dict[str, Any], findings: List[Dict[str, Any]],
                 units: List[Dict[str, str]], profile: NarrativeProfile, log: CallLog,
                 max_repairs: int, version: int, recap: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    unit_text = {u["unit_id"]: u["text"] for u in units}
    lines = []
    for f in findings:
        lines.append(f"- [{f['severity']}] {f['claim_type']} ({f['failure_category']}) in paragraph: "
                     f"\"{unit_text.get(f['unit_id'], '')[:300]}\"\n  claim: {f['claim']}\n"
                     f"  why: {f['explanation']}\n  suggested fix: {f['suggested_fix']}")
    user = render("revise_user", scope_label=scope.label(), profile=profile.render(),
                  briefs=briefs_for_prompt(briefs), background=background_text(recap),
                  plan=dump(plan), script=dump(script),
                  min_words=profile.min_words, max_words=profile.max_words,
                  findings="\n".join(lines))
    return run_json_stage(client, stage="revise", system=_script_system(profile), user=user,
                          schema=load_schema("script_v0"),
                          semantic_check=lambda s: script_structure_errors(s, plan),
                          soft_check=lambda s: script_soft_errors(s, profile),
                          max_repairs=max_repairs, log=log, request_suffix=f"v{version}")


# --------------------------------------------------------------------------- patch

def patch_errors(patch: Dict[str, Any], units: Sequence[Dict[str, str]], target_language: str) -> List[str]:
    """Every edit names a paragraph, copies its span exactly once from it, and writes clean text."""
    unit_text = {u["unit_id"]: u["text"] for u in units}
    errors, seen = [], set()
    for index, edit in enumerate(patch["edits"]):
        where = f"edits[{index}] ({edit['unit_id']})"
        text = unit_text.get(_unit_id(edit["unit_id"]))
        if text is None:
            errors.append(f"{where}: no such paragraph")
            continue
        count = text.count(edit["old"])
        if count != 1:
            errors.append(f"{where}: \"old\" must occur exactly once in the paragraph (found {count}); "
                          f"copy it character for character")
        if edit["old"] == edit["new"]:
            errors.append(f"{where}: \"new\" is the same as \"old\"")
        if (_unit_id(edit["unit_id"]), edit["old"]) in seen:
            errors.append(f"{where}: the same span is edited twice")
        seen.add((_unit_id(edit["unit_id"]), edit["old"]))
        foreign = checks.foreign_script_characters(edit["new"], target_language)
        if foreign:
            errors.append(f"{where}: \"new\" contains characters from another writing system ({foreign[0]!r})")
    return errors


def apply_patch(script: Dict[str, Any], units: Sequence[Dict[str, str]], patch: Dict[str, Any]) -> Dict[str, Any]:
    """The script with each edit applied inside its own paragraph; nothing else changes.

    A paragraph emptied by deletions disappears. A whole beat cannot be deleted this way: if
    every paragraph of a section would go, the section is kept as it was."""
    replacements: Dict[str, str] = {}
    for unit in units:
        text = unit["text"]
        for edit in (e for e in patch["edits"] if _unit_id(e["unit_id"]) == unit["unit_id"]):
            new = edit["new"].strip()
            text = text.replace(edit["old"], new, 1)
        replacements[unit["text"]] = re.sub(r"[ \t]{2,}", " ", text).strip()
    sections = []
    for section in script["sections"]:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section["text"]) if p.strip()]
        text = "\n\n".join(r for r in (replacements.get(p, p) for p in paragraphs) if r)
        sections.append({**section, "text": text or section["text"]})
    return {**script, "sections": sections}


def run_patch(client: LLMClient, scope: StoryScope, briefs: Sequence[Dict[str, Any]], script: Dict[str, Any],
              findings: List[Dict[str, Any]], units: List[Dict[str, str]], profile: NarrativeProfile,
              log: CallLog, max_repairs: int, version: int) -> Dict[str, Any]:
    """A revision round that edits only the sentences at fault (see patch_user.md)."""
    schema = load_schema("script_patch_v0")
    lines = [f"- [{f['severity']}] in {f['unit_id']}: \"{f['claim']}\"\n  why: {f['explanation']}\n"
             f"  suggested fix: {f['suggested_fix']}" for f in findings]
    unit_lines = "\n\n".join(f"<{u['unit_id']}>\n{u['text']}\n</{u['unit_id']}>" for u in units)
    user = render("patch_user", scope_label=scope.label(), findings="\n".join(lines),
                  briefs=briefs_for_prompt(briefs), units=unit_lines, schema=dump(schema))
    patch = run_json_stage(client, stage="patch", system=_script_system(profile), user=user, schema=schema,
                           semantic_check=lambda p: patch_errors(p, units, profile.target_language),
                           max_repairs=max_repairs, log=log, request_suffix=f"v{version}")
    return apply_patch(script, units, patch)


# --------------------------------------------------------------------------- critic


def critic_semantic_errors(critic: Dict[str, Any], units: List[Dict[str, str]]) -> List[str]:
    errors: List[str] = []
    expected = [u["unit_id"] for u in units]
    actual = [u["unit_id"] for u in critic["units"]]
    if actual != expected:
        errors.append(f"units must be exactly {expected} in order; got {actual}")
    for unit in critic["units"]:
        for index, claim in enumerate(unit["claims"]):
            if claim["claim_type"] in PROBLEM_TYPES and claim["claim_type"] != "UNDETERMINED":
                if claim["severity"] is None or claim["failure_category"] is None:
                    errors.append(f"{unit['unit_id']} claims[{index}]: {claim['claim_type']} needs "
                                  f"severity and failure_category")
    return errors


WORDS_PER_CLAIM = 30


def critic_density_errors(critic: Dict[str, Any], units: List[Dict[str, str]]) -> List[str]:
    """Flag units the critic under-extracted. In the first live run it took about one claim
    per paragraph and passed strengthened and invented details it never isolated."""
    words = {u["unit_id"]: checks.count_words(u["text"]) for u in units}
    errors = []
    for unit in critic["units"]:
        if unit["no_claim_reason"]:
            continue
        needed = words.get(unit["unit_id"], 0) // WORDS_PER_CLAIM
        if len(unit["claims"]) < needed:
            errors.append(f"{unit['unit_id']}: {words[unit['unit_id']]} words but only {len(unit['claims'])} "
                          f"claims; extract every atomic claim separately (expected at least {needed}). "
                          f"Check each intensifier, frequency word, physical or emotional state and "
                          f"reported fact on its own")
    return errors


SUPPORTED_CLAIM_TYPES = {"SUPPORTED_FACT", "SUPPORTED_INFERENCE", "ATTRIBUTED_REPORT"}


def brief_item_texts(briefs: Sequence[Dict[str, Any]], recap: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Ref ("c1.E3", "c1.CH2") -> the brief text a claim citing it may rely on."""
    texts: Dict[str, str] = {}
    for brief in briefs:
        n = brief["chapter_order"]
        for character in brief["characters"]:
            parts = [character["name"], character["romanized_name"], *character["aliases"],
                     *(f["text"] for f in character["facts"])]
            texts[f"c{n}.{character['id']}"] = " ".join(parts)
        for event in brief["events"]:
            parts = [event["summary"], event.get("consequence") or "", event["motivation"].get("text") or ""]
            texts[f"c{n}.{event['id']}"] = " ".join(parts)
    for chapter in (recap or {}).get("chapters", []):
        for event in chapter["core_events"]:
            texts[event["ref"]] = event["summary"]
    return texts


def _strength_finding(unit_id: str, claim: str, refs: List[str], phrases: List[Tuple[str, str]],
                      source: str) -> Dict[str, Any]:
    words = [phrase for _, phrase in phrases]
    return {
        "unit_id": unit_id, "claim": claim,
        "claim_type": "STRENGTHENED_STORY_CLAIM", "failure_category": "EPISTEMIC_ERROR",
        "severity": "MEDIUM", "brief_refs": refs, "source": source,
        "concepts": sorted({concept for concept, _ in phrases}), "phrases": words,
        "explanation": f"Từ tăng mức độ {words} (khái niệm {sorted({c for c, _ in phrases})}) không có "
                       f"trong mục brief được trích ({', '.join(refs)}).",
        "suggested_fix": "Viết lại đúng mức độ của brief, bỏ hoặc làm nhẹ từ: " + ", ".join(words),
    }


def strength_audit(critic: Dict[str, Any], briefs: Sequence[Dict[str, Any]],
                   recap: Optional[Dict[str, Any]] = None,
                   units: Optional[Sequence[Dict[str, str]]] = None,
                   script_language: str = "vi", brief_language: Optional[str] = None) -> List[Dict[str, Any]]:
    """Deterministic second opinion on claims the critic accepted.

    Works on language-independent concepts (tools/story_pipeline/lexicon.py): a strengthening
    concept found in an accepted claim (script language) must also be expressed in the brief
    items it cites (brief language, which may differ). In live run 3 the critic accepted
    "everyone calls her by the nickname Angel" against "likened to an angel" and "eased a
    lot" against "eased". Returns [] when either language has no lexicon; callers report that
    through `audit_coverage`.
    """
    script_lex, brief_lex = lexicon.load(script_language), lexicon.load(brief_language or script_language)
    if script_lex is None or brief_lex is None:
        return []
    texts = brief_item_texts(briefs, recap)

    def unsupported(text: str, refs: Sequence[str]) -> List[Tuple[str, str]]:
        cited = brief_lex.concepts(" ".join(texts.get(ref, "") for ref in refs), "strength")
        return [(c, p) for c, p in script_lex.find(script_lex.without_audience_address(text), "strength")
                if c not in cited]

    findings = []
    for unit in critic["units"]:
        for claim in unit["claims"]:
            if claim["claim_type"] not in SUPPORTED_CLAIM_TYPES or not claim["brief_refs"]:
                continue
            extra = unsupported(claim["claim"], claim["brief_refs"])
            if extra:
                findings.append(_strength_finding(unit["unit_id"], claim["claim"], claim["brief_refs"],
                                                  extra, "strength_audit"))
    if units is not None:
        findings += _unit_text_audit(critic, units, findings, unsupported)
    return findings


def brief_items(briefs: Sequence[Dict[str, Any]], recap: Optional[Dict[str, Any]] = None) -> Dict[str, List[str]]:
    """Ref -> its individual statements (each character fact separately), for matching a
    script sentence to the one brief statement it retells."""
    return {ref: [text for text, _ in statements] for ref, statements in labelled_statements(briefs, recap).items()}


def labelled_statements(briefs: Sequence[Dict[str, Any]],
                        recap: Optional[Dict[str, Any]] = None) -> Dict[str, List[Tuple[str, str]]]:
    """Ref -> (statement, epistemic label) pairs; recap events count as EXPLICIT."""
    items: Dict[str, List[Tuple[str, str]]] = {}
    for brief in briefs:
        n = brief["chapter_order"]
        for character in brief["characters"]:
            items[f"c{n}.{character['id']}"] = [(f["text"], f.get("epistemic", "EXPLICIT"))
                                                for f in character["facts"]]
        for event in brief["events"]:
            text = " ".join([event["summary"], event.get("consequence") or "", event["motivation"].get("text") or ""])
            items[f"c{n}.{event['id']}"] = [(text, event.get("epistemic", "EXPLICIT"))]
    for chapter in (recap or {}).get("chapters", []):
        for event in chapter["core_events"]:
            items[event["ref"]] = [(event["summary"], "EXPLICIT")]
    return items


def _bigrams(text: str) -> set:
    squashed = _squash(text.casefold())
    return {squashed[i:i + 2] for i in range(len(squashed) - 1)}


def similarity(a: str, b: str) -> float:
    """Dice overlap of character bigrams: script-agnostic, needs no tokenizer."""
    x, y = _bigrams(a), _bigrams(b)
    return 2 * len(x & y) / (len(x) + len(y)) if x and y else 0.0


HEDGE_MATCH = 0.5  # minimum similarity for a script sentence to retell a hedged brief clause


def _hedged_clauses(statements: Sequence[Tuple[str, str]], lex: "lexicon.Lexicon") -> List[Tuple[str, Set[str]]]:
    """Clauses of brief statements that are hedged. A statement often joins several facts
    ("modest, and reportedly popular with the boys"); only a hedged clause counts. A statement
    labelled anything but EXPLICIT is hedged as a whole, since facts are meant to be atomic."""
    out = []
    for statement, label in statements:
        for clause in lex.clauses(statement):
            concepts = lex.concepts(clause, "hedge")
            if label != "EXPLICIT":
                concepts = concepts | {LABEL_CONCEPT[label]}
            if concepts and len(_squash(clause)) >= 8:
                out.append((clause.strip(), concepts))
    return out


def hedge_audit(critic: Dict[str, Any], briefs: Sequence[Dict[str, Any]],
                recap: Optional[Dict[str, Any]] = None, units: Optional[Sequence[Dict[str, str]]] = None,
                script_language: str = "vi", brief_language: Optional[str] = None) -> List[Dict[str, Any]]:
    """The script must keep the brief's hedges.

    For every paragraph, the hedged clauses of the brief items its claims cite are compared
    with the paragraph's own sentences. A sentence that retells such a clause (character-
    bigram similarity >= HEDGE_MATCH) but carries no hedge becomes a MEDIUM finding for
    revision. Matching needs the brief and the script in one language; otherwise nothing is
    checked and `audit_coverage` reports it. A first item-level version flagged sentences that
    retold the unhedged half of a statement; on live runs 4, 5 and 7 this version has no false
    positives.
    """
    brief_language = brief_language or script_language
    script_lex, brief_lex = lexicon.load(script_language), lexicon.load(brief_language)
    if script_lex is None or brief_lex is None or units is None:
        return []
    if lexicon.lexicon_code(script_language) != lexicon.lexicon_code(brief_language):
        return []
    items = labelled_statements(briefs, recap)
    unit_text = {u["unit_id"]: u["text"] for u in units}
    findings = []
    for unit in critic["units"]:
        refs = sorted({ref for claim in unit["claims"] for ref in claim["brief_refs"]})
        clauses = [(ref, clause, concepts) for ref in refs
                   for clause, concepts in _hedged_clauses(items.get(ref, []), brief_lex)]
        if not clauses:
            continue
        for match in _SENTENCE.finditer(unit_text.get(unit["unit_id"], "")):
            sentence = match.group(0).strip()
            if not sentence or script_lex.concepts(sentence, "hedge"):
                continue
            score, ref, clause, concepts = max((similarity(sentence, c), r, c, k) for r, c, k in clauses)
            if score < HEDGE_MATCH:
                continue
            examples = [p for c in sorted(concepts) for p in script_lex.phrases["hedge"][c][:2]]
            findings.append({
                "unit_id": unit["unit_id"], "claim": sentence,
                "claim_type": "STRENGTHENED_STORY_CLAIM", "failure_category": "EPISTEMIC_ERROR",
                "severity": "MEDIUM", "brief_refs": [ref], "source": "hedge_audit",
                "concepts": sorted(concepts), "phrases": [],
                "explanation": f"Brief ({ref}) ghi có rào đón {sorted(concepts)}: \"{clause[:120]}\"; "
                               f"câu kịch bản kể lại mà bỏ mất rào đón.",
                "suggested_fix": "Giữ lại sắc thái rào đón, ví dụ: " + ", ".join(examples),
            })
    return findings


ATTRIBUTION_MATCH = HEDGE_MATCH  # same threshold as the hedge audit


def _statement_sources(briefs: Sequence[Dict[str, Any]]) -> Dict[str, List[Tuple[str, str, List[str]]]]:
    """Ref -> (statement, quote, evidence) for every fact and event. Recap events carry no
    quote, so they are left out and never count as narration-only."""
    items: Dict[str, List[Tuple[str, str, List[str]]]] = {}
    for brief in briefs:
        n = brief["chapter_order"]
        for character in brief["characters"]:
            items[f"c{n}.{character['id']}"] = [(f["text"], f["quote"], f["evidence"]) for f in character["facts"]]
        for event in brief["events"]:
            text = " ".join([event["summary"], event.get("consequence") or ""])
            items[f"c{n}.{event['id']}"] = [(text, event["quote"], event["evidence"])]
    return items


def attribution_audit(critic: Dict[str, Any], briefs: Sequence[Dict[str, Any]],
                      units: Optional[Sequence[Dict[str, str]]], passages: Mapping[str, str],
                      script_language: str = "vi", brief_language: Optional[str] = None) -> List[Dict[str, Any]]:
    """Nobody may be made to say what the chapter only has them think, or what only the narrator says.

    Live run 10 had Amane explain to Mahiru ("giải thích rằng ...") that her look was like a
    lost child's. In the source (4.18) that is his thought, and the brief recorded it as such.
    For every paragraph, a clause that is the content of reported speech ("X giải thích rằng
    |...") is compared with the clauses of the brief statements its claims cite. If it retells
    (similarity >= ATTRIBUTION_MATCH) a statement that involves no speech at all (no verb of
    saying in its text and no dialogue in its quote or in any cited passage) better than any
    statement that does, the sentence becomes a MEDIUM finding for revision.

    On the saved scripts of live runs 2-10 (25 versions) this flags only the run-10 sentence.
    Needs the script and the brief in one language, with speech verbs in its lexicon.
    """
    brief_language = brief_language or script_language
    lex = lexicon.load(script_language)
    if (lex is None or units is None or not lex.speech_verbs
            or lexicon.lexicon_code(script_language) != lexicon.lexicon_code(brief_language)):
        return []
    sources = _statement_sources(briefs)
    unit_text = {u["unit_id"]: u["text"] for u in units}
    findings = []
    for unit in critic["units"]:
        refs = sorted({ref for claim in unit["claims"] for ref in claim["brief_refs"]})
        candidates = []
        for ref in refs:
            for text, quote, evidence in sources.get(ref, []):
                speech = (bool(_DIALOGUE.search(quote)) or lex.mentions_speech(text)
                          or any(_DIALOGUE.search(passages.get(e, "")) for e in evidence))
                candidates += [(ref, clause, speech) for clause in lex.clauses(text) if len(_squash(clause)) >= 8]
        if not candidates:
            continue
        for match in _SENTENCE.finditer(unit_text.get(unit["unit_id"], "")):
            sentence = match.group(0).strip()
            start = lex.reported_speech_start(sentence)
            if start is None:
                continue
            reported = sentence[start:]
            best = max(((similarity(clause, c), ref, c, speech) for clause in lex.clauses(reported)
                        for ref, c, speech in candidates), default=None)
            if best is None or best[0] < ATTRIBUTION_MATCH or best[3]:
                continue
            _, ref, clause, _ = best
            findings.append({
                "unit_id": unit["unit_id"], "claim": sentence,
                "claim_type": "UNSUPPORTED_STORY_CLAIM", "failure_category": "SOURCE_GROUNDING_FAILURE",
                "severity": "MEDIUM", "brief_refs": [ref], "source": "attribution_audit",
                "concepts": [], "phrases": [],
                "explanation": f"Câu kịch bản cho nhân vật nói ra điều mà brief ({ref}) ghi là suy nghĩ hoặc lời "
                               f"người kể, không phải lời thoại: \"{clause[:120]}\".",
                "suggested_fix": "Kể lại như suy nghĩ hoặc lời người kể (\"cậu nghĩ\", \"thật ra\"), "
                                 "không dùng \"nói/giải thích rằng\".",
            })
    return findings


def source_hedge_review(brief: Dict[str, Any], chapter: Chapter, source_language: str,
                        brief_language: str) -> List[Dict[str, Any]]:
    """Advisory list for a person: brief items with no hedge although a cited passage hedges.

    Wider than `brief_hedge_errors`, which only reads the sentence of the item's quote. Over
    live runs 2-7 about half of these were real (a metaphor stated as a nickname, 「そうだ」
    hearsay, 「ように見え」 dropped) and half were hedges about something else in the same
    passage, so they are reported, never sent back to the model.
    """
    src, dst = lexicon.load(source_language), lexicon.load(brief_language)
    if src is None or dst is None:
        return []
    texts = {p.passage_id: p.text for p in chapter.passages}
    items = [(f"c{brief['chapter_order']}.{c['id']}", f["text"], f["evidence"])
             for c in brief["characters"] for f in c["facts"]]
    items += [(f"c{brief['chapter_order']}.{e['id']}", e["summary"], e["evidence"]) for e in brief["events"]]
    review = []
    for ref, text, evidence in items:
        if dst.concepts(text, "hedge"):
            continue
        hedges = sorted({(concept, phrase, pid) for pid in evidence
                         for concept, phrase in src.find(_DIALOGUE.sub(" ", texts.get(pid, "")), "hedge")})
        if hedges:
            review.append({"ref": ref, "text": text, "source_hedges": [list(h) for h in hedges]})
    return review


def source_strength_review(brief: Dict[str, Any], chapter: Chapter, source_language: str,
                           brief_language: str) -> List[Dict[str, Any]]:
    """Advisory list for a person: brief items stronger than every passage they cite.

    The strength audit compares the script with the briefs, so a brief that already
    overstates ("thường xuyên nhận được lời tỏ tình" for 「学年問わず…らしく」, "chắc chắn" for
    「恐らく」) passes it. On the saved briefs of runs 2-15 about 4 in 10 listed items are real; the
    rest are wordings the source lexicon does not know, so nothing is sent back to the model.
    """
    src, dst = lexicon.load(source_language), lexicon.load(brief_language)
    if src is None or dst is None:
        return []
    texts = {p.passage_id: p.text for p in chapter.passages}
    n = brief["chapter_order"]
    items = [(f"c{n}.{c['id']}", f["text"], f["evidence"]) for c in brief["characters"] for f in c["facts"]]
    items += [(f"c{n}.{e['id']}", " ".join([e["summary"], e.get("consequence") or ""]), e["evidence"])
              for e in brief["events"]]
    review = []
    for ref, text, evidence in items:
        cited = src.concepts(" ".join(texts.get(pid, "") for pid in evidence), "strength")
        extra = sorted({(concept, phrase) for concept, phrase in dst.find(text, "strength") if concept not in cited})
        if extra:
            review.append({"ref": ref, "text": text, "phrases": [phrase for _, phrase in extra],
                           "concepts": [concept for concept, _ in extra], "evidence": list(evidence)})
    return review


def audit_coverage(script_language: str, brief_language: str, source_language: str) -> Dict[str, Any]:
    """Which deterministic language checks can run, so a missing lexicon is reported, not silent."""
    missing = sorted(lexicon.missing_languages(script_language, brief_language, source_language))
    return {
        "strength_audit": not ({script_language, brief_language} & set(missing)),
        "brief_hedge_check": not ({brief_language, source_language} & set(missing)),
        "script_hedge_audit": (not ({script_language, brief_language} & set(missing))
                               and lexicon.lexicon_code(script_language) == lexicon.lexicon_code(brief_language)),
        "attribution_audit": (not ({script_language, brief_language} & set(missing))
                              and lexicon.lexicon_code(script_language) == lexicon.lexicon_code(brief_language)
                              and bool(lexicon.load(script_language).speech_verbs)),
        "missing_lexicons": missing,
        "available_lexicons": lexicon.available_languages(),
    }


_SENTENCE = re.compile(r"[^.!?…。！？]*[.!?…。！？]?")


def _unit_text_audit(critic: Dict[str, Any], units: Sequence[Dict[str, str]], already: List[Dict[str, Any]],
                     unsupported: Callable[[str, Sequence[str]], List[Tuple[str, str]]]) -> List[Dict[str, Any]]:
    """Check the script's own wording, not just the critic's paraphrase of it.

    In live run 4 the script said "vô cùng áy náy" (extremely guilty) but the critic's claim
    read "khó chịu và áy náy", so the claim-level audit never saw the intensifier. Every
    strengthening concept in a paragraph must occur in some brief item cited by that
    paragraph's claims; paragraphs that cite nothing (pure commentary) are not judged.
    """
    unit_text = {u["unit_id"]: u["text"] for u in units}
    flagged = {(f["unit_id"], c) for f in already for c in f["concepts"]}
    findings = []
    for unit in critic["units"]:
        refs = sorted({ref for claim in unit["claims"] for ref in claim["brief_refs"]})
        text = unit_text.get(unit["unit_id"], "")
        if not refs or not text:
            continue
        for concept, phrase in unsupported(text, refs):
            if (unit["unit_id"], concept) in flagged:
                continue
            flagged.add((unit["unit_id"], concept))
            sentence = next((m.group(0).strip() for m in _SENTENCE.finditer(text)
                             if phrase in m.group(0).casefold()), text[:200])
            findings.append(_strength_finding(unit["unit_id"], sentence, refs, [(concept, phrase)],
                                              "strength_audit_text"))
    return findings


def normalize_critic(critic: Dict[str, Any]) -> Dict[str, Any]:
    """Acceptable claim types carry no severity/category, whatever the model wrote."""
    for unit in critic["units"]:
        for claim in unit["claims"]:
            if claim["claim_type"] not in PROBLEM_TYPES:
                claim["severity"] = None
                claim["failure_category"] = None
    return critic


def run_critic(client: LLMClient, scope: StoryScope, briefs: Sequence[Dict[str, Any]],
               units: List[Dict[str, str]], profile: NarrativeProfile, log: CallLog,
               max_repairs: int, version: int, recap: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    schema = load_schema("critic_v0")
    system = render("critic_system", target_language_name=profile.target_language_name,
                    schema=dump(schema))
    unit_lines = "\n\n".join(f"<{u['unit_id']}>\n{u['text']}\n</{u['unit_id']}>" for u in units)
    user = render("critic_user", scope_label=scope.label(), briefs=briefs_for_prompt(briefs),
                  background=background_text(recap),
                  unit_count=len(units), units=unit_lines)
    critic = run_json_stage(client, stage="critic", system=system, user=user, schema=schema,
                            semantic_check=lambda c: critic_semantic_errors(c, units),
                            soft_check=lambda c: critic_density_errors(c, units),
                            max_repairs=max_repairs, log=log, request_suffix=f"v{version}")
    return normalize_critic(critic)


# --------------------------------------------------------------------------- owner review

def locate_owner_errors(errors: Sequence[Dict[str, Optional[str]]], units: Sequence[Dict[str, str]]
                        ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Optional[str]]]]:
    """The reviewer's quoted errors as revision findings on the paragraph that contains the
    quote (whitespace-insensitive), and the errors that could not be placed."""
    located, unplaced = [], []
    for error in errors:
        quote = error.get("quote")
        unit = next((u for u in units if quote and _squash(quote) in _squash(u["text"])), None)
        if unit is None:
            unplaced.append(dict(error))
            continue
        why = error.get("why") or "Người duyệt đánh dấu câu này là sai."
        located.append({"unit_id": unit["unit_id"], "claim": quote, "claim_type": "OWNER_REVIEW",
                        "failure_category": "OTHER", "severity": "HIGH", "brief_refs": [], "source": "owner",
                        "concepts": [], "phrases": [], "explanation": why,
                        "suggested_fix": f"Sửa theo góp ý của người duyệt: {why}"})
    return located, unplaced


# --------------------------------------------------------------------------- incremental checks

def unchanged_units(units: Sequence[Dict[str, str]], previous: Sequence[Dict[str, str]]) -> Dict[str, str]:
    """Paragraphs whose text is byte-identical to a paragraph of the previous version:
    new unit id -> previous unit id. Patch rounds leave most paragraphs untouched (60-97%
    in saved runs), so their critic and source-check verdicts can be carried over."""
    pool: Dict[str, List[str]] = {}
    for unit in previous:
        pool.setdefault(unit["sha256"], []).append(unit["unit_id"])
    carried = {}
    for unit in units:
        ids = pool.get(unit["sha256"])
        if ids:
            carried[unit["unit_id"]] = ids.pop(0)
    return carried


def merge_critic(units: Sequence[Dict[str, str]], fresh: Optional[Dict[str, Any]],
                 previous: Optional[Dict[str, Any]], carried: Mapping[str, str]) -> Dict[str, Any]:
    """One critic result for every paragraph: the fresh verdicts for changed paragraphs and
    the previous version's for carried ones, under their new ids, in script order."""
    fresh_units = {u["unit_id"]: u for u in (fresh or {}).get("units", [])}
    old_units = {u["unit_id"]: u for u in (previous or {}).get("units", [])}
    merged = []
    for unit in units:
        uid = unit["unit_id"]
        entry = dict(old_units[carried[uid]], unit_id=uid) if uid in carried else fresh_units[uid]
        merged.append(entry)
    return {"units": merged}


def carry_findings(findings: Sequence[Dict[str, Any]], carried: Mapping[str, str]) -> List[Dict[str, Any]]:
    """The previous version's findings on carried paragraphs, under their new ids."""
    back = {old: new for new, old in carried.items()}
    return [dict(f, unit_id=back[f["unit_id"]]) for f in findings if f["unit_id"] in back]


# --------------------------------------------------------------------------- source check

# Above this much source text the check is skipped (and recorded), so a long episode cannot
# silently overflow the model's context; split such an episode instead.
SOURCE_CHECK_MAX_CHARS = 60000
SOURCE_CHECK_KINDS = {
    "CONTRADICTS_SOURCE": ("CONTRADICTED_STORY_CLAIM", "FACTUAL_ERROR"),
    "NOT_IN_SOURCE": ("UNSUPPORTED_STORY_CLAIM", "UNSUPPORTED_INVENTION"),
    "WRONG_SPEAKER": ("UNSUPPORTED_STORY_CLAIM", "SOURCE_GROUNDING_FAILURE"),
    "STRENGTHENED": ("STRENGTHENED_STORY_CLAIM", "EPISTEMIC_ERROR"),
    "WRONG_CAUSE": ("CONTRADICTED_STORY_CLAIM", "CAUSALITY_ERROR"),
}


def _unit_id(value: Any) -> str:
    """A paragraph id as the model wrote it, without the tag brackets the prompt shows
    ("<P001>" -> "P001"; season S2's fallback model copied them)."""
    return str(value).strip().strip("<>/").strip()


def source_check_text(chapters: Sequence[Chapter]) -> str:
    return "\n".join(f"[{p.passage_id}] {p.text}" for c in chapters for p in c.passages)


def critic_flags(critic: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The critic's problem claims, numbered F1, F2... for the source check to adjudicate.

    The critic judges the script against the briefs, so a detail that the source does say
    but the brief left out is reported as invented (season S2 episode 2: all four remaining
    findings). The source check reads the whole episode and can tell the two apart."""
    flags = []
    for unit in (critic or {}).get("units", []):
        for claim in unit["claims"]:
            if claim["claim_type"] in PROBLEM_TYPES and claim["claim_type"] != "UNDETERMINED":
                flags.append({"id": f"F{len(flags) + 1}", "unit_id": unit["unit_id"], **claim})
    return flags


_FLAG_KINDS = {"UNSUPPORTED_STORY_CLAIM": "not supported", "CONTRADICTED_STORY_CLAIM": "contradicted",
               "STRENGTHENED_STORY_CLAIM": "stated more strongly than the summary"}


def flagged_text(flags: Sequence[Dict[str, Any]]) -> str:
    if not flags:
        return "(none: return an empty critic_reviews list)"
    return "\n".join(f"{f['id']} ({f['unit_id']}, {_FLAG_KINDS.get(f['claim_type'], 'questioned')}): {f['claim']}"
                     for f in flags)


def source_check_errors(check: Dict[str, Any], units: Sequence[Dict[str, str]],
                        passage_ids: Set[str], flags: Sequence[Dict[str, Any]] = ()) -> List[str]:
    """Every paragraph listed once; quotes copied from their paragraph; passages in scope;
    every flagged statement answered once, IN_SOURCE with the passages that say it."""
    errors = []
    reviews = check.get("critic_reviews") or []
    answered = [r["id"].strip() for r in reviews]
    expected = [f["id"] for f in flags]
    if sorted(answered) != sorted(expected):
        errors.append(f"critic_reviews: answer each flagged statement exactly once ({expected}), got {answered}")
    for review in reviews:
        unknown = [pid for pid in review["passage_ids"] if pid not in passage_ids]
        if unknown:
            errors.append(f"critic_reviews {review['id']}: passage ids {unknown} are not in this episode's source")
        if review["verdict"] == "IN_SOURCE" and not review["passage_ids"]:
            errors.append(f"critic_reviews {review['id']}: IN_SOURCE needs the passage ids that say it")
    unit_text = {u["unit_id"]: u["text"] for u in units}
    listed = [_unit_id(p["unit_id"]) for p in check["paragraphs"]]
    missing = [u for u in unit_text if u not in listed]
    if missing or len(listed) != len(set(listed)) or set(listed) - set(unit_text):
        errors.append(f"paragraphs: list every paragraph exactly once ({len(unit_text)} paragraphs, "
                      f"missing {missing[:5]})")
    for paragraph in check["paragraphs"]:
        uid = _unit_id(paragraph["unit_id"])
        text = _squash(unit_text.get(uid, ""))
        for index, finding in enumerate(paragraph["findings"]):
            where = f"{uid} findings[{index}]"
            if _squash(finding["script_quote"]) not in text:
                errors.append(f"{where}: script_quote is not copied exactly from paragraph {uid}")
            unknown = [pid for pid in finding["passage_ids"] if pid not in passage_ids]
            if unknown:
                errors.append(f"{where}: passage ids {unknown} are not in this episode's source")
    return errors


def source_check_findings(check: Dict[str, Any], passages: Mapping[str, str]) -> List[Dict[str, Any]]:
    """Findings in the form the revision stage and the gate report use (all MEDIUM)."""
    findings = []
    for paragraph in check["paragraphs"]:
        for finding in paragraph["findings"]:
            claim_type, category = SOURCE_CHECK_KINDS[finding["kind"]]
            cited = "; ".join(f"[{pid}] {passages.get(pid, '')[:160]}" for pid in finding["passage_ids"])
            findings.append({
                "unit_id": _unit_id(paragraph["unit_id"]), "claim": finding["script_quote"],
                "claim_type": claim_type, "failure_category": category, "severity": "MEDIUM",
                "brief_refs": [], "source": "source_check", "kind": finding["kind"],
                "passage_ids": finding["passage_ids"], "concepts": [], "phrases": [],
                "explanation": finding["explanation"],
                "suggested_fix": f"Sửa hoặc bỏ cho đúng nguyên tác: {cited}",
            })
    return findings


def overturned_flags(checks: Sequence[Optional[Dict[str, Any]]],
                     flags: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Critic findings that the source check found in the source: every sample that answered
    said IN_SOURCE (one dissent keeps the finding). They are brief gaps, not script errors."""
    out = []
    for flag in flags:
        verdicts = [r for check in checks if check for r in check.get("critic_reviews") or []
                    if r["id"].strip() == flag["id"]]
        if verdicts and all(r["verdict"] == "IN_SOURCE" for r in verdicts):
            passages = []
            for review in verdicts:
                passages += [p for p in review["passage_ids"] if p not in passages]
            out.append({**flag, "passage_ids": passages, "source_explanation": verdicts[0]["explanation"]})
    return out


def without_claims(critic: Dict[str, Any], drop: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The critic result without the given claims (matched by paragraph, text and type)."""
    keys = {(f["unit_id"], f["claim"], f["claim_type"]) for f in drop}
    return {**critic, "units": [{**unit, "claims": [c for c in unit["claims"]
                                                     if (unit["unit_id"], c["claim"], c["claim_type"]) not in keys]}
                                for unit in critic["units"]]}


def merge_source_findings(samples: Sequence[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Union of several source-check calls. One call misses defects another catches (live
    runs 13-14), and in trials every reported finding was real, so findings are pooled; two
    findings on one paragraph whose quotes overlap count once (the first is kept)."""
    merged: List[Dict[str, Any]] = []
    for findings in samples:
        for finding in findings:
            quote = _squash(finding["claim"])
            if not any(f["unit_id"] == finding["unit_id"] and (quote in _squash(f["claim"]) or _squash(f["claim"]) in quote)
                       for f in merged):
                merged.append(finding)
    return merged


def run_source_check(client: LLMClient, scope: StoryScope, units: List[Dict[str, str]],
                     profile: NarrativeProfile, log: CallLog, max_repairs: int,
                     version: int, sample: int = 1,
                     flags: Sequence[Dict[str, Any]] = (), chunk: int = 0) -> Optional[Dict[str, Any]]:
    """Check the script against the episode's own source text, and answer for each critic
    flag (see critic_flags) whether the source says it. None when the episode is too long
    for one call (see SOURCE_CHECK_MAX_CHARS)."""
    source = source_check_text(scope.chapters)
    if len(source) > SOURCE_CHECK_MAX_CHARS:
        return None
    schema = load_schema("source_check_v0")
    language = LANGUAGE_NAMES.get(scope.source_language, scope.source_language)
    system = render("source_check_system", target_language_name=profile.target_language_name,
                    source_language_name=language, schema=dump(schema))
    unit_lines = "\n\n".join(f"<{u['unit_id']}>\n{u['text']}\n</{u['unit_id']}>" for u in units)
    user = render("source_check_user", scope_label=scope.label(), source_language_name=language,
                  source=source, unit_count=len(units), units=unit_lines, flagged=flagged_text(flags))
    ids = {p.passage_id for c in scope.chapters for p in c.passages}
    return run_json_stage(client, stage="source_check", system=system, user=user, schema=schema,
                          semantic_check=lambda c: source_check_errors(c, units, ids, flags),
                          max_repairs=max_repairs, log=log,
                          request_suffix=f"v{version}" + (f"c{chunk}" if chunk else "")
                          + (f"s{sample}" if sample > 1 else ""))

