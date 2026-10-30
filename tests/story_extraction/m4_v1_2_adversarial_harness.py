"""Synthetic adversarial cases for STORY_EXTRACTION_DRAFT_V1_2 (M4-04B4C).

Implements M4_DRAFT_V1_2_ADVERSARIAL_TEST_SPEC.md ADV-01..28 plus ADV-29..33 and
positive/negative controls. All Japanese text is invented here. Each case returns a
record of expected and actual outcomes, resolver statuses, compiler status and whether
the compiled span equals the span the scenario intends.

``span_matches_intent`` False with outcome VALID marks a *semantic residue*: the anchor
is unique and mechanically correct, but points where the scenario did not intend. V1.2
does not and cannot detect that structurally.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unicodedata
from typing import Any, Callable, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture_builder as fx  # noqa: E402

from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext  # noqa: E402
from tools.story_extraction.draft_compiler_v1_2 import (  # noqa: E402
    DraftCompilationErrorV1_2,
    compile_story_extraction_draft_v1_2,
)
from tools.story_extraction.extraction_contract_guard_v1 import validate_batch_guarded  # noqa: E402


def context_for(text: str) -> DraftCompilerContext:
    ingestion, base = fx.ingest_text(text)
    scope = fx.Builder(ingestion, base).batch()["scope"]
    return DraftCompilerContext(base, scope["passage_inputs"], scope["as_of_position"],
                                scope["profile_id"], "adv-v1-2", "v1", "adv", ingestion)


def empty_draft() -> dict[str, Any]:
    return {"draft_version": "STORY_EXTRACTION_DRAFT_V1_2", "evidence": [], "mentions": [],
            "entities": [], "events": [], "anchors": [], "propositions": [], "assertions": [],
            "unresolved_locators": []}


def locator(handle, passage, quote, before=None, after=None, role="DEPICTION"):
    record = {"handle": handle, "passage_handle": passage, "quote": quote, "role": role}
    if before is not None:
        record["context_before"] = before
    if after is not None:
        record["context_after"] = after
    return record


def refers(passage, quote, before=None, after=None, kind="CHARACTER", n=1,
           evidence=None) -> dict[str, Any]:
    """One mention + entity + RefersTo assertion grounded on the mention's own text."""
    draft = empty_draft()
    add_refers(draft, passage, quote, before, after, kind, n, evidence)
    return draft


def add_refers(draft, passage, quote, before=None, after=None, kind="CHARACTER", n=1,
               evidence=None):
    draft["mentions"].append(locator(f"M{n}", passage, quote, before, after))
    draft["evidence"].append(evidence or locator(f"EV{n}", passage, quote, before, after))
    draft["entities"].append({"handle": f"E_NEW_{n}", "kind": kind})
    draft["propositions"].append({"handle": f"PROP{n}", "predicate": "RefersTo", "args": {
        "mention": {"kind": "MENTION", "handle": f"M{n}"},
        "entity": {"kind": "ENTITY", "handle": f"E_NEW_{n}"}}})
    draft["assertions"].append({"handle": f"A{n}", "proposition_handle": f"PROP{n}",
                                "polarity": "AFFIRMED", "epistemic_status": "EXPLICIT",
                                "support": {"evidence_sets": [{"label": "SUFFICIENT",
                                                               "evidence_handles": [f"EV{n}"]}],
                                            "derivations": []}})
    return draft


def _passage_base(context, passage):
    index = int(passage[1:]) - 1
    return context.passage_inputs[index]["passage_ref"]["span"]["char_start"]


def run(context, draft, intended: Optional[dict[str, tuple[str, int]]] = None) -> dict[str, Any]:
    """Compile and classify. ``intended`` maps locator handle -> (passage, offset)."""
    try:
        batch, report = compile_story_extraction_draft_v1_2(deepcopy(draft), context)
    except DraftCompilationErrorV1_2 as error:
        codes = sorted({blocker.code for blocker in error.blockers})
        return {"actual": "INVALID", "codes": codes,
                "resolver": sorted({item.get("status") for item in error.report["locators"]
                                    if item.get("status")}),
                "compiler": "BLOCKED", "span_matches_intent": None,
                "hints": sorted({hint for item in error.report["locators"]
                                 for hint in item.get("hints", [])}),
                "declaration_checks": [], "advisories": []}
    assert validate_batch_guarded(batch, context.base_document, context.ingestion)["pass"]
    statuses = sorted({item["status"] for item in report["locators"]})
    matches = None
    if intended:
        records = batch["candidate_records"]
        spans = {}
        for record in records["evidence_refs"]:
            spans[record["id"].rsplit("-", 1)[-1]] = (record["segment_id"],
                                                      record["span"]["char_start"])
        evidence = {item["id"]: item for item in records["evidence_refs"]}
        for record in records["mentions"]:
            ref = evidence[record["evidence_ref_id"]]
            spans[record["id"].rsplit("-", 1)[-1]] = (ref["segment_id"], ref["span"]["char_start"])
        matches = True
        for handle, (passage, offset) in intended.items():
            segment = context.passage_inputs[int(passage[1:]) - 1]["passage_ref"]["segment_id"]
            if spans.get(handle) != (segment, _passage_base(context, passage) + offset):
                matches = False
    declared = report["counts"]["declared_unresolved"]
    return {"actual": "EXPLICITLY_UNRESOLVED" if declared else "VALID", "codes": [],
            "resolver": statuses, "compiler": "COMPILED", "span_matches_intent": matches,
            "hints": [],
            "declaration_checks": sorted(item["declaration_check"]
                                         for item in report["declared_unresolved"]),
            "advisories": sorted({item["code"] for item in report["advisories"]})}


TWO = "真白は笑った。真白は窓を開けた。"
DIALOGUE = "真白は「はい」と答えた。遥も「はい」と答えた。"
# 25 repetitions (100 code points): the R1 specification said nine, but with nine the
# 16- and 32-character contexts reach a text boundary and still disambiguate.
REPEATED = "「はい」" * 25


def _occurred(draft, n, quote, passage="P1"):
    draft["events"].append({"handle": f"EVT{n}", "event_kind": "GENERIC", "anchor_handle": f"T{n}"})
    draft["anchors"].append({"handle": f"T{n}", "anchor_kind": "EVENT_TIME", "event_handle": f"EVT{n}"})
    draft["evidence"].append(locator(f"EV{n + 10}", passage, quote))
    draft["propositions"].append({"handle": f"PROP{n + 10}", "predicate": "Occurred",
                                  "args": {"event": {"kind": "EVENT", "handle": f"EVT{n}"}}})
    draft["assertions"].append({"handle": f"A{n + 10}", "proposition_handle": f"PROP{n + 10}",
                                "polarity": "AFFIRMED", "epistemic_status": "EXPLICIT",
                                "support": {"evidence_sets": [{"label": "SUFFICIENT",
                                                               "evidence_handles": [f"EV{n + 10}"]}],
                                            "derivations": []}})


def _named_as(draft, entity, name, evidence_handles, extra_sets=()):
    draft["propositions"].append({"handle": "PROP50", "predicate": "NamedAs", "args": {
        "entity": {"kind": "ENTITY", "handle": entity},
        "name": {"kind": "LITERAL", "value_type": "STRING", "value": name},
        "name_kind": {"kind": "TOKEN", "vocabulary": "name_kind", "value": "GIVEN"}}})
    draft["assertions"].append({"handle": "A50", "proposition_handle": "PROP50",
                                "polarity": "AFFIRMED", "epistemic_status": "EXPLICIT",
                                "validity": {"start": {"kind": "OPEN"}, "end": {"kind": "OPEN"}},
                                "support": {"evidence_sets": [{"label": "SUFFICIENT",
                                                               "evidence_handles": evidence_handles},
                                                              *extra_sets],
                                            "derivations": []}})


def _case(case_id, title, expected, build: Callable[[], tuple], explanation,
          expected_span=None, expected_codes=(), expected_extra=None):
    return {"id": case_id, "title": title, "expected": expected, "build": build,
            "expected_span_matches_intent": expected_span, "expected_codes": list(expected_codes),
            "expected_extra": expected_extra or {}, "explanation": explanation}


def _adv04():
    context = context_for(REPEATED)
    starts = [i for i in range(len(REPEATED)) if REPEATED.startswith("はい", i)]
    middle = starts[len(starts) // 2]
    return context, refers("P1", "はい", REPEATED[middle - 16:middle], REPEATED[middle + 2:middle + 18],
                           kind="OTHER"), None


def _adv05():
    context = context_for(REPEATED)
    draft = empty_draft()
    draft["unresolved_locators"] = [
        {"handle": "M1", "passage_handle": "P1", "quote": "はい", "reason": "REPEATED_IDENTICAL_CONTEXT"},
        {"handle": "EV1", "passage_handle": "P1", "quote": "はい", "reason": "REPEATED_IDENTICAL_CONTEXT"}]
    return context, draft, None


def _adv06(before):
    def build():
        context = context_for(DIALOGUE)
        draft = refers("P1", "遥")
        draft["evidence"].append(locator("EV9", "P1", "「はい」", before))
        _named_as(draft, "E_NEW_1", "遥", ["EV1"],
                  [{"label": "CORROBORATING", "evidence_handles": ["EV9"]}])
        return context, draft, {"EV9": ("P1", DIALOGUE.rindex("「はい」"))}
    return build


def _adv10():
    text = "……と言って、部屋を出た。"
    context = context_for(text)
    draft = empty_draft()
    _occurred(draft, 1, "部屋を出た")
    draft["entities"].append({"handle": "E_NEW_1", "kind": "CHARACTER", "placeholder": True})
    draft["propositions"].append({"handle": "PROP2", "predicate": "Participates", "args": {
        "event": {"kind": "EVENT", "handle": "EVT1"}, "participant": {"kind": "ENTITY", "handle": "E_NEW_1"},
        "role": {"kind": "TOKEN", "vocabulary": "participant_role", "value": "AGENT"}}})
    draft["assertions"].append({"handle": "A2", "proposition_handle": "PROP2", "polarity": "AFFIRMED",
                                "epistemic_status": "EXPLICIT", "support": {"evidence_sets": [
                                    {"label": "SUFFICIENT", "evidence_handles": ["EV11"]}],
                                    "derivations": []}})
    return context, draft, None


def _adv20(span_quote=None):
    def build():
        context = context_for("真白は窓を開けた。\n\n風が入った。")
        draft = refers("P1", "真白")
        if span_quote:
            draft["evidence"].append(locator("EV2", "P1", span_quote))
        else:
            draft["evidence"].append(locator("EV2", "P2", "風が入った"))
        draft["assertions"][0]["support"]["evidence_sets"][0]["evidence_handles"].append("EV2")
        return context, draft, None
    return build


def _adv23():
    context = context_for("真白は笑った。")
    draft = refers("P1", "真白")
    draft["entities"].append({"handle": "E_NEW_2", "kind": "OBJECT", "placeholder": True})
    draft["evidence"].append(locator("EV3", "P1", "真白は笑った"))
    draft["propositions"].append({"handle": "PROP3", "predicate": "Possesses", "args": {
        "holder": {"kind": "ENTITY", "handle": "E_NEW_1"}, "item": {"kind": "ENTITY", "handle": "E_NEW_2"}}})
    draft["assertions"].append({"handle": "A3", "proposition_handle": "PROP3", "polarity": "AFFIRMED",
                                "epistemic_status": "EXPLICIT",
                                "validity": {"start": {"kind": "OPEN"}, "end": {"kind": "OPEN"}},
                                "support": {"evidence_sets": [{"label": "SUFFICIENT",
                                                               "evidence_handles": ["EV3"]}],
                                            "derivations": []}})
    return context, draft, None


def _with(draft_builder, mutate):
    def build():
        context, draft, intended = draft_builder()
        mutate(draft)
        return context, draft, intended
    return build


def _simple(text, draft, intended=None):
    return lambda: (context_for(text), draft() if callable(draft) else draft, intended)


NFD = unicodedata.normalize("NFD", "真白が笑った。")

CASES = [
    _case("CTRL-POS", "positive control: unique name", "VALID",
          _simple("真白は笑った。", lambda: refers("P1", "真白"), {"M1": ("P1", 0)}),
          "Unique quote, no context.", expected_span=True),
    _case("CTRL-NEG", "negative control: absent quote", "INVALID",
          _simple("真白は笑った。", lambda: refers("P1", "遥")),
          "Quote absent.", expected_codes=["LOCATOR_QUOTE_NOT_FOUND"]),
    _case("ADV-01", "repeated name, distinguishing context", "VALID",
          _simple(TWO, lambda: refers("P1", "真白", "。", "は窓"), {"M1": ("P1", 7), "EV1": ("P1", 7)}),
          "Context selects the second 真白.", expected_span=True),
    _case("ADV-02", "repeated name, no context", "INVALID",
          _simple(TWO, lambda: refers("P1", "真白")),
          "Two candidates survive; no default.", expected_codes=["LOCATOR_AMBIGUOUS"]),
    _case("ADV-03", "context of the wrong occurrence", "VALID",
          _simple(TWO, lambda: refers("P1", "真白", None, "は笑"), {"M1": ("P1", 7)}),
          "Unique anchor at the first 真白 although the second was intended: semantic residue.",
          expected_span=False),
    _case("ADV-04", "identical context at bounded length", "INVALID", _adv04,
          "Middle occurrences share 16-character context on both sides.",
          expected_codes=["LOCATOR_AMBIGUOUS"]),
    _case("ADV-05", "declared repeated identical context", "EXPLICITLY_UNRESOLVED", _adv05,
          "Declared and justified; no records emitted.",
          expected_extra={"declaration_checks": ["CONSISTENT", "CONSISTENT"]}),
    _case("ADV-06", "repeated dialogue, correct speaker context", "VALID", _adv06("遥も"),
          "context_before 遥も selects 遥's line.", expected_span=True),
    _case("ADV-07", "repeated dialogue, context matching neither", "INVALID", _adv06("誰も"),
          "Quote exists; context eliminates every candidate.",
          expected_codes=["LOCATOR_CONTEXT_MISMATCH"]),
    _case("ADV-08", "overlapping matches", "VALID",
          _simple("あははは、と真白は笑った。",
                  lambda: refers("P1", "はは", "あ", kind="OTHER"), {"M1": ("P1", 1)}),
          "Overlapping candidates 1 and 2; context あ keeps offset 1.", expected_span=True),
    _case("ADV-09", "pronoun linked to a referent the text leaves open", "VALID",
          _simple("真白は笑った。（彼は誰だ）", lambda: add_refers(refers("P1", "真白"), "P1", "彼", n=2),
                  {"M2": ("P1", 8)}),
          "Position correct; the RefersTo is a semantic claim gold must judge.", expected_span=True),
    _case("ADV-10", "omitted subject", "VALID", _adv10,
          "No mention or evidence is fabricated for the absent subject; placeholder participant.",
          expected_extra={"no_mentions": True}),
    _case("ADV-11", "aliases with honorifics", "VALID",
          _simple("真白さんと真白ちゃん", lambda: add_refers(refers("P1", "真白さん"), "P1", "真白ちゃん", n=2),
                  {"M1": ("P1", 0), "M2": ("P1", 5)}),
          "Distinct unique quotes; aliasing is semantic.", expected_span=True),
    _case("ADV-12", "repeated honorific form", "INVALID",
          _simple("真白さん、真白さん。", lambda: refers("P1", "真白さん")),
          "Two identical candidates.", expected_codes=["LOCATOR_AMBIGUOUS"]),
    _case("ADV-13", "multiple candidate referents", "VALID",
          _simple("真白と真昼が来た。\n\n彼女は笑った。",
                  lambda: add_refers(refers("P1", "真白"), "P2", "彼女", n=2), {"M2": ("P2", 0)}),
          "Position correct; whether 彼女 is 真白 is semantic.", expected_span=True),
    _case("ADV-14", "model-supplied surface form", "INVALID",
          _simple("真白は笑った。", lambda: _set(refers("P1", "真白"), "mentions", 0, "surface_form", "真昼")),
          "surface_form is not a model field.", expected_codes=["DRAFT_SCHEMA_FAILURE"]),
    _case("ADV-15", "invented quote", "INVALID",
          _simple("真白は笑った。", lambda: refers("P1", "真昼")),
          "Quote absent.", expected_codes=["LOCATOR_QUOTE_NOT_FOUND"]),
    _case("ADV-16", "ruby dropped", "INVALID",
          _simple("｜真白《ましろ》は笑った。", lambda: refers("P1", "真白は笑った")),
          "Exact copy required.", expected_codes=["LOCATOR_QUOTE_NOT_FOUND"]),
    _case("ADV-17", "ruby kept", "VALID",
          _simple("｜真白《ましろ》は笑った。", lambda: refers("P1", "真白《ましろ》"), {"M1": ("P1", 1)}),
          "Exact span includes ruby markup.", expected_span=True),
    _case("ADV-18", "NFC quote, NFD source", "INVALID",
          _simple(NFD, lambda: _plus_evidence(refers("P1", "真白"), "が笑った")),
          "No normalization; hint only.", expected_codes=["LOCATOR_QUOTE_NOT_FOUND"],
          expected_extra={"hints": ["NORMALIZATION_VARIANT_PRESENT"]}),
    _case("ADV-19", "full-width digits", "INVALID",
          _simple("１２時に真白が来た。", lambda: _plus_evidence(refers("P1", "真白"), "12時")),
          "No width folding; hint only.", expected_codes=["LOCATOR_QUOTE_NOT_FOUND"],
          expected_extra={"hints": ["COMPATIBILITY_VARIANT_PRESENT"]}),
    _case("ADV-20", "multi-passage evidence set", "VALID", _adv20(),
          "Two exact spans in one SUFFICIENT set."),
    _case("ADV-21", "quote across passages", "INVALID", _adv20("開けた。\n\n風"),
          "Passages are separate texts.", expected_codes=["LOCATOR_QUOTE_NOT_FOUND"]),
    _case("ADV-22", "mention without RefersTo", "VALID",
          _simple("真白は笑った。", lambda: _plus_mention(refers("P1", "真白"), "笑った")),
          "Compiles; advisory raised.", expected_extra={"advisories": ["MENTION_WITHOUT_REFERSTO"]}),
    _case("ADV-23", "unsupported relation", "VALID", _adv23,
          "Structurally valid; gold must score it unsupported."),
    _case("ADV-24", "unsupported event", "VALID",
          _simple("真白は笑った。", lambda: _with_event(refers("P1", "真白"), "真白は笑った")),
          "Structurally valid; gold must score it unsupported."),
    _case("ADV-25", "wrong passage", "VALID",
          _simple("真白は笑った。\n\n真白は窓を開けた。", lambda: refers("P2", "真白"), {"M1": ("P1", 0)}),
          "Unique in P2 although P1 was intended: semantic residue.", expected_span=False),
    _case("ADV-26", "context crossing the passage start", "INVALID",
          _simple("真白は笑った。", lambda: refers("P1", "真白", "。")),
          "No text precedes the quote inside the passage.",
          expected_codes=["LOCATOR_CONTEXT_MISMATCH"]),
    _case("ADV-27", "determinism under reordering", "VALID",
          _simple(TWO, lambda: add_refers(refers("P1", "真白", None, "は笑"), "P1", "窓", n=2)),
          "Checked separately: identical canonical JSON under shuffled records."),
    _case("ADV-28", "occurrence field present", "INVALID",
          _simple(TWO, lambda: _set(refers("P1", "真白"), "mentions", 0, "occurrence", 2)),
          "No counting field exists.", expected_codes=["DRAFT_SCHEMA_FAILURE"]),
    _case("ADV-29", "wrong dialogue attribution", "VALID", _adv06("真白は"),
          "Unique anchor on 真白's line cited for a claim about 遥: semantic residue.",
          expected_span=False),
    _case("ADV-30", "unjustified unresolved declaration", "EXPLICITLY_UNRESOLVED",
          _simple("真白は笑った。", lambda: _declare(empty_draft(), "M1", "真白")),
          "Quote is unique; declaration counted as unjustified.",
          expected_extra={"declaration_checks": ["UNIQUE_WITHOUT_CONTEXT"]}),
    _case("ADV-31", "reference to a declared-unresolved locator", "INVALID",
          _simple(REPEATED, lambda: _declare(_drop(refers("P1", "はい", kind="OTHER"), "mentions"),
                                             "M1", "はい")),
          "Dependants of an unresolved locator must be omitted.",
          expected_codes=["REFERENCE_TO_UNRESOLVED_LOCATOR"]),
    _case("ADV-32", "invalid context length", "INVALID",
          _simple(TWO, lambda: refers("P1", "真白", "。" * 33)),
          "Context longer than 32 code points.", expected_codes=["DRAFT_SCHEMA_FAILURE"]),
    _case("ADV-33", "fabricated name literal", "VALID",
          _simple("真白は笑った。", lambda: _named(refers("P1", "真白"), "真昼")),
          "Literal values are not locators; gold must catch it (SC6 residue)."),
]


def _set(draft, field, index, key, value):
    draft[field][index][key] = value
    return draft


def _plus_evidence(draft, quote):
    draft["evidence"].append(locator("EV9", "P1", quote))
    draft["assertions"][0]["support"]["evidence_sets"].append(
        {"label": "CORROBORATING", "evidence_handles": ["EV9"]})
    return draft


def _plus_mention(draft, quote):
    draft["mentions"].append(locator("M9", "P1", quote))
    return draft


def _with_event(draft, quote):
    _occurred(draft, 1, quote)
    return draft


def _declare(draft, handle, quote):
    draft["unresolved_locators"].append({"handle": handle, "passage_handle": "P1", "quote": quote,
                                         "reason": "REPEATED_IDENTICAL_CONTEXT"})
    return draft


def _drop(draft, field):
    draft[field] = []
    return draft


def _named(draft, name):
    _named_as(draft, "E_NEW_1", name, ["EV1"])
    return draft


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    context, draft, intended = case["build"]()
    outcome = run(context, draft, intended)
    passed = outcome["actual"] == case["expected"]
    if case["expected_codes"]:
        passed = passed and set(case["expected_codes"]) <= set(outcome["codes"])
    if case["expected_span_matches_intent"] is not None:
        passed = passed and outcome["span_matches_intent"] is case["expected_span_matches_intent"]
    extra = case["expected_extra"]
    for key in ("hints", "declaration_checks", "advisories"):
        if key in extra:
            passed = passed and outcome[key] == extra[key]
    if extra.get("no_mentions"):
        passed = passed and not draft["mentions"]
    return {"id": case["id"], "title": case["title"], "expected": case["expected"],
            "expected_codes": case["expected_codes"],
            "expected_span_matches_intent": case["expected_span_matches_intent"],
            "actual": outcome["actual"], "codes": outcome["codes"],
            "resolver_statuses": outcome["resolver"], "compiler_status": outcome["compiler"],
            "span_matches_intent": outcome["span_matches_intent"], "hints": outcome["hints"],
            "declaration_checks": outcome["declaration_checks"],
            "advisories": outcome["advisories"], "explanation": case["explanation"],
            "pass": passed}


def run_all() -> list[dict[str, Any]]:
    return [evaluate_case(case) for case in CASES]


def summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    by = lambda key: sum(1 for item in records if item["actual"] == key)  # noqa: E731
    return {
        "cases": len(records),
        "pass": sum(item["pass"] for item in records),
        "valid": by("VALID"),
        "invalid": by("INVALID"),
        "explicitly_unresolved": by("EXPLICITLY_UNRESOLVED"),
        "semantic_residue_valid_at_unintended_span": sum(
            item["actual"] == "VALID" and item["span_matches_intent"] is False for item in records),
        "resolver_false_resolution": sum(
            item["actual"] == "VALID" and item["span_matches_intent"] is False
            and item["expected_span_matches_intent"] is not False for item in records),
    }


if __name__ == "__main__":
    print(json.dumps({"summary": summary(run_all())}, ensure_ascii=False, indent=2))
