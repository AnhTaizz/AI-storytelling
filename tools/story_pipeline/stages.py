"""Pipeline stages: prompt rendering plus semantic validation for each model call."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional, Sequence

from tools.story_memory.memory_v0 import recap_event_refs
from tools.story_pipeline import checks
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


def brief_semantic_errors(brief: Dict[str, Any], chapter: Chapter) -> List[str]:
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
    needed = min_events(len(chapter.passages))
    if len(brief["events"]) < needed:
        errors.append(f"events: a chapter of {len(chapter.passages)} passages needs at least {needed} events "
                      f"at the level of single actions and dialogue turns; you listed {len(brief['events'])}. "
                      f"Split merged events: each refusal, offer, decision, reveal or change of place is "
                      f"its own event")
    return errors


PASSAGES_PER_EVENT = 15


def min_events(passage_count: int) -> int:
    """Lower bound on brief events for a chapter. The first live run compressed 61 passages
    into 2 events, folding a character's refusal into "they talked briefly", and the script
    then left the refusal out entirely."""
    return max(2, -(-passage_count // PASSAGES_PER_EVENT))


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
                          semantic_check=lambda b: brief_semantic_errors(b, chapter),
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


# Words that raise degree, frequency, scope, certainty or reputation in Vietnamese narration.
# A supported claim containing one of them must find the same word in the brief item it cites.
STRENGTH_MARKERS = (
    "vô cùng", "cực kỳ", "cực kì", "hoàn toàn", "tuyệt đối", "rất nhiều", "vô số", "mọi người",
    "ai ai", "ai cũng", "tất cả mọi", "luôn luôn", "lúc nào cũng", "thường xuyên", "không bao giờ",
    "chưa bao giờ", "chắc chắn", "nhất định", "toàn thân", "từ đầu đến chân", "biệt danh",
)
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


def strength_audit(critic: Dict[str, Any], briefs: Sequence[Dict[str, Any]],
                   recap: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Deterministic second opinion on claims the critic accepted.

    In live run 3 the critic accepted "everyone calls her by the nickname Angel" (brief:
    "likened to an angel") and "his guilt eased a lot" (brief: "eased"). Such claims are
    returned as STRENGTHENED_STORY_CLAIM findings so they reach the revision step.
    """
    texts = brief_item_texts(briefs, recap)
    findings = []
    for unit in critic["units"]:
        for claim in unit["claims"]:
            if claim["claim_type"] not in SUPPORTED_CLAIM_TYPES or not claim["brief_refs"]:
                continue
            cited = " ".join(texts.get(ref, "") for ref in claim["brief_refs"]).casefold()
            text = claim["claim"].casefold()
            extra = [m for m in STRENGTH_MARKERS if m in text and m not in cited]
            if extra:
                findings.append({
                    "unit_id": unit["unit_id"], "claim": claim["claim"],
                    "claim_type": "STRENGTHENED_STORY_CLAIM", "failure_category": "EPISTEMIC_ERROR",
                    "severity": "MEDIUM", "brief_refs": claim["brief_refs"], "source": "strength_audit",
                    "explanation": f"Từ tăng mức độ {extra} không có trong mục brief được trích "
                                   f"({', '.join(claim['brief_refs'])}).",
                    "suggested_fix": "Viết lại đúng mức độ của brief, bỏ hoặc làm nhẹ từ: " + ", ".join(extra),
                })
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
