"""Check M4 V4 conventions: the V3 checks plus R-TIME-03 (an event's date on the event's own anchor).

    python -m tools.story_extraction.check_annotation_conventions_v3 \
        --batch B.json --source S.txt [--source S2.txt] [--base BASE.json] [--out OUT.json]

Reports contain identifiers and counts. Exit status is 0 with or without findings,
or 2 for refused input. Use align_date_anchors only for development rescoring.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path

from tools.story_extraction import check_annotation_conventions_v1 as v1
from tools.story_extraction import check_annotation_conventions_v2 as v2
from tools.story_extraction.draft_sentence_evidence_v1 import _enclosing, _sentence_spans

RULE = "R-TIME-03"
RULES = (*v2.RULES, RULE)


def _sentence(evidence: v1._Evidence, ref_id: str) -> tuple | None:
    """(source hash, line start byte, sentence start, sentence end) of a verified span, or None."""
    quoted, _ = evidence.read(ref_id)
    span = evidence.refs[ref_id]["span"]
    raw = evidence.sources[span["source_sha256"]]
    start, end = span["byte_start"], span["byte_end_exclusive"]
    left = max(raw.rfind(b"\r", 0, start), raw.rfind(b"\n", 0, start)) + 1
    breaks = [i for i in (raw.find(b"\r", start), raw.find(b"\n", start)) if i >= 0]
    right = min(breaks, default=len(raw))
    if end > right:
        return None
    line = raw[left:right].decode("utf-8")
    offset = len(raw[left:start].decode("utf-8"))
    dialogue, narration = _sentence_spans(line)
    bounds = _enclosing(dialogue, offset, offset + len(quoted)) or _enclosing(narration, offset, offset + 1)
    return None if bounds is None else (span["source_sha256"], left, *bounds)


def _sufficient(assertion: dict) -> list[str]:
    return [ref for group in assertion.get("support", {}).get("evidence_sets", [])
            if group.get("label") == "SUFFICIENT" for ref in group.get("evidence_ref_ids", [])]


def _audit(batch: dict, sources, base: dict) -> list[dict]:
    """One finding per AFFIRMED AnchorDate on a NAMED_TIME anchor dated in the sentence of exactly one event."""
    records = batch.get("candidate_records", {})
    assertions = v1._index(records, "assertions")
    propositions = {**v1._index(base, "propositions"), **v1._index(records, "propositions")}
    refs = {**v1._index(base, "evidence_refs"), **v1._index(records, "evidence_refs")}
    anchors = {**v1._index(base, "temporal_anchors"), **v1._index(records, "temporal_anchors")}
    events = {**v1._index(base, "events"), **v1._index(records, "events")}
    evidence = v1._Evidence(refs, sources)

    def sentences(assertion):
        return {key for ref in _sufficient(assertion) if (key := _sentence(evidence, ref)) is not None}

    affirmed = [a for a in assertions.values() if a.get("polarity") == "AFFIRMED"]
    event_sentences: dict[str, set] = {}
    for assertion in affirmed:
        prop = propositions.get(assertion.get("proposition_id"), {})
        if prop.get("predicate") == "Occurred":
            event = prop["args"]["event"]["ref"]
            event_sentences.setdefault(event, set()).update(sentences(assertion))
    findings = []
    for assertion in affirmed:
        prop = propositions.get(assertion.get("proposition_id"), {})
        if prop.get("predicate") != "AnchorDate":
            continue
        named = prop["args"]["anchor"]["ref"]
        if anchors.get(named, {}).get("anchor_kind") != "NAMED_TIME":
            continue
        dated = sentences(assertion)
        timed = sorted(e for e, found in event_sentences.items() if dated & found)
        if len(timed) == 1 and events.get(timed[0], {}).get("anchor_id") in anchors:
            findings.append({"assertion": assertion["id"], "proposition": prop["id"], "named_anchor": named,
                             "event_anchor": events[timed[0]]["anchor_id"]})
    return findings


def check_batch(batch: dict, sources: dict[str, bytes] | Iterable[bytes], base: dict | None = None) -> dict:
    """Return the V2 report with the additional R-TIME-03 findings."""
    sources = sources if isinstance(sources, dict) else tuple(sources)
    report = v2.check_batch(batch, sources, base)
    findings = _audit(batch, sources, base or {})
    report["rules_checked"] = list(RULES)
    report["counts"][RULE] = len(findings)
    report["findings"].extend(
        {"rule": RULE, "code": "DATE_ON_NAMED_TIME_OF_EVENT",
         "record_ids": sorted({f["assertion"], f["proposition"], f["named_anchor"]})} for f in findings)
    report["findings"].sort(key=lambda issue: (issue["rule"], issue["code"], issue["record_ids"]))
    return report


def _redirect(value, old: str, new: str) -> None:
    """Point ANCHOR arguments and anchored validity bounds at `new` instead of `old`, in place."""
    if isinstance(value, dict):
        if value.get("kind") == "ANCHOR":
            for key in ("ref", "anchor_id"):
                if value.get(key) == old:
                    value[key] = new
        for child in value.values():
            _redirect(child, old, new)
    elif isinstance(value, list):
        for child in value:
            _redirect(child, old, new)


def _mentions_anchor(value, anchor: str) -> bool:
    if isinstance(value, dict):
        if value.get("kind") == "ANCHOR" and anchor in (value.get("ref"), value.get("anchor_id")):
            return True
        return any(_mentions_anchor(child, anchor) for child in value.values())
    if isinstance(value, list):
        return any(_mentions_anchor(child, anchor) for child in value)
    return False


def align_date_anchors(batch: dict, sources: dict[str, bytes] | Iterable[bytes],
                       base: dict | None = None) -> tuple[dict, dict]:
    """Align R-TIME-03 findings in a deep copy, for development rescoring only."""
    base = base or {}
    sources = sources if isinstance(sources, dict) else tuple(sources)
    findings = _audit(batch, sources, base)
    new_batch = deepcopy(batch)
    records = new_batch.get("candidate_records", {})
    local = {key: v1._index(records, key) for key in ("assertions", "propositions", "temporal_anchors")}
    report = {"flagged": len(findings), "aligned": 0, "refused": Counter(), "relations_dropped": 0,
              "anchors_dropped": 0, "duplicates_dropped": 0}
    dropped, moved = set(), set()
    for finding in findings:
        if not (finding["assertion"] in local["assertions"] and finding["proposition"] in local["propositions"]
                and finding["named_anchor"] in local["temporal_anchors"]):
            report["refused"]["REFUSED_BASE"] += 1
            continue
        target, date = finding["event_anchor"], local["propositions"][finding["proposition"]]["args"]["date"]
        same_date = [a["id"] for a in local["assertions"].values() if a["polarity"] == "AFFIRMED"
                     and (p := local["propositions"].get(a["proposition_id"], {})).get("predicate") == "AnchorDate"
                     and p["args"]["anchor"]["ref"] == target and p["args"]["date"] == date]
        _redirect(records, finding["named_anchor"], target)
        if same_date:
            dropped.add(finding["assertion"])
            report["duplicates_dropped"] += 1
        moved.add(finding["named_anchor"])
        report["aligned"] += 1
    for assertion in local["assertions"].values():
        prop = local["propositions"].get(assertion["proposition_id"], {})
        if prop.get("predicate") == "TemporalRelation" and moved \
                and prop["args"]["subject"]["ref"] == prop["args"]["object"]["ref"]:
            dropped.add(assertion["id"])
            report["relations_dropped"] += 1
    premises = {p for a in records.get("assertions", [])
                for d in a.get("support", {}).get("derivations", []) for p in d.get("premise_assertion_ids", [])}
    dropped -= premises
    orphaned = {local["assertions"][a]["proposition_id"] for a in dropped}
    records["assertions"] = [a for a in records.get("assertions", []) if a["id"] not in dropped]
    still_used = {a["proposition_id"] for a in records["assertions"]}
    still_used |= {p["args"][k]["ref"] for p in records.get("propositions", []) for k in p.get("args", {})
                   if isinstance(p["args"][k], dict) and p["args"][k].get("kind") == "PROPOSITION"}
    records["propositions"] = [p for p in records.get("propositions", [])
                               if p["id"] not in orphaned - still_used]
    unused = {anchor for anchor in moved if not _mentions_anchor(records, anchor)}
    records["temporal_anchors"] = [t for t in records.get("temporal_anchors", []) if t["id"] not in unused]
    report["anchors_dropped"] = len(unused)
    report["refused"] = dict(sorted(report["refused"].items()))
    return new_batch, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--base", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        batch = json.loads(args.batch.read_text(encoding="utf-8"))
        base = json.loads(args.base.read_text(encoding="utf-8")) if args.base else None
        report = check_batch(batch, [path.read_bytes() for path in args.source], base)
        output = json.dumps(report, sort_keys=True, ensure_ascii=False) + "\n"
        if args.out:
            args.out.write_text(output, encoding="utf-8", newline="\n")
        else:
            print(output, end="")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print("error: refused input or inaccessible report destination", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
