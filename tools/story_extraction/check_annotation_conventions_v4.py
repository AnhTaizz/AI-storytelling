"""Check M4 V5 conventions: the V4 checks plus R-EVR-02 (a mention outside dialogue takes its sentence's role).

    python -m tools.story_extraction.check_annotation_conventions_v4 \
        --batch B.json --source S.txt [--source S2.txt] [--base BASE.json] [--out OUT.json]

R-EVR-02 is checked mechanically as a consistency rule: outside dialogue, the SUFFICIENT evidence of a RefersTo or
NamedAs assertion must carry the role of the other evidence in the same sentence when all of that evidence shares one
role. Whether a sentence depicts, summarizes or looks back stays a judgement of the annotator.
Reports contain identifiers and counts. Exit status is 0 with or without findings, or 2 for refused input.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path

from tools.story_extraction import check_annotation_conventions_v1 as v1
from tools.story_extraction import check_annotation_conventions_v3 as v3
from tools.story_extraction.draft_mention_evidence_v1 import PREDICATES
from tools.story_extraction.draft_sentence_evidence_v1 import _enclosing, _sentence_spans

RULE = "R-EVR-02"
RULES = (*v3.RULES, RULE)


def _place(evidence: v1._Evidence, ref_id: str) -> tuple | None:
    """(sentence key, inside dialogue) of a verified span, or None when it crosses a line."""
    quoted, _ = evidence.read(ref_id)
    span = evidence.refs[ref_id]["span"]
    raw = evidence.sources[span["source_sha256"]]
    start, end = span["byte_start"], span["byte_end_exclusive"]
    left = max(raw.rfind(b"\r", 0, start), raw.rfind(b"\n", 0, start)) + 1
    breaks = [i for i in (raw.find(b"\r", start), raw.find(b"\n", start)) if i >= 0]
    if end > min(breaks, default=len(raw)):
        return None
    line = raw[left:min(breaks, default=len(raw))].decode("utf-8")
    offset = len(raw[left:start].decode("utf-8"))
    dialogue, narration = _sentence_spans(line)
    inside = _enclosing(dialogue, offset, offset + len(quoted))
    bounds = inside or _enclosing(narration, offset, offset + 1)
    return None if bounds is None else ((span["source_sha256"], left, *bounds), inside is not None)


def _audit(batch: dict, sources, base: dict) -> list[tuple[str, ...]]:
    records = batch.get("candidate_records", {})
    assertions = v1._index(records, "assertions")
    propositions = {**v1._index(base, "propositions"), **v1._index(records, "propositions")}
    refs = {**v1._index(base, "evidence_refs"), **v1._index(records, "evidence_refs")}
    evidence = v1._Evidence(refs, sources)
    mention_refs, other_roles = {}, {}
    for assertion in assertions.values():
        prop = propositions.get(assertion.get("proposition_id"), {})
        is_mention = prop.get("predicate") in PREDICATES
        for group in assertion.get("support", {}).get("evidence_sets", []):
            if group.get("label") != "SUFFICIENT":
                continue
            for ref_id in group.get("evidence_ref_ids", []):
                place = _place(evidence, ref_id)
                if place is None:
                    continue
                if is_mention:
                    if assertion.get("polarity") in ("AFFIRMED", "NEGATED") and not place[1]:
                        mention_refs.setdefault(ref_id, (place[0], assertion["id"], prop["id"]))
                else:
                    other_roles.setdefault(place[0], set()).add(refs[ref_id]["role"])
    findings = []
    for ref_id, (sentence, assertion_id, proposition_id) in sorted(mention_refs.items()):
        roles = other_roles.get(sentence, set())
        if len(roles) == 1 and refs[ref_id]["role"] not in roles:
            findings.append(tuple(sorted({ref_id, assertion_id, proposition_id})))
    return sorted(set(findings))


def check_batch(batch: dict, sources: dict[str, bytes] | Iterable[bytes], base: dict | None = None) -> dict:
    """Return the V3 report with the additional R-EVR-02 findings."""
    sources = sources if isinstance(sources, dict) else tuple(sources)
    report = v3.check_batch(batch, sources, base)
    findings = _audit(batch, sources, base or {})
    report["rules_checked"] = list(RULES)
    report["counts"][RULE] = len(findings)
    report["findings"].extend({"rule": RULE, "code": "MENTION_ROLE_DIFFERS_FROM_SENTENCE", "record_ids": list(ids)}
                              for ids in findings)
    report["findings"].sort(key=lambda issue: (issue["rule"], issue["code"], issue["record_ids"]))
    return report


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
