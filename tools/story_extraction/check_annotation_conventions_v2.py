"""Check M4 V3 conventions, including the evidence role of mentions in dialogue.

    python -m tools.story_extraction.check_annotation_conventions_v2 \
        --batch B.json --source S.txt [--source S2.txt] [--base BASE.json] [--out OUT.json]

Reports contain identifiers and counts. Exit status is 0 with or without findings,
or 2 for refused input. Use align_mention_roles only for development rescoring.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path

from tools.canonical_story.conformance_v0 import _supports
from tools.story_extraction import check_annotation_conventions_v1 as v1
from tools.story_extraction.draft_mention_evidence_v1 import PREDICATES
from tools.story_extraction.draft_sentence_evidence_v1 import _enclosing, _sentence_spans

RULE = "R-EVR-01"
RULES = (*v1.RULE_IDS, RULE)
_LINE_BREAK = re.compile(rb"[\r\n]")


def _has_wrong_dialogue_role(evidence: v1._Evidence, ref_id: str, segments: dict) -> bool:
    quoted, _ = evidence.read(ref_id)
    ref = evidence.refs[ref_id]
    if ref["role"] == "DEPICTION" or not quoted or "\r" in quoted or "\n" in quoted:
        return False

    span = ref["span"]
    source_hash = span["source_sha256"]
    raw = evidence.sources[source_hash]
    start, end = span["byte_start"], span["byte_end_exclusive"]
    left, right = 0, len(raw)
    segment = segments.get(ref.get("segment_id"))
    if segment is not None:
        locator = segment["locator"]
        left, right = locator["byte_start"], locator["byte_end_exclusive"]
        if locator["source_sha256"] != source_hash or not 0 <= left <= start < end <= right <= len(raw):
            raise ValueError("Evidence span is outside its source segment")

    # M4 paragraph segments start on a line boundary. Without a segment locator,
    # the containing source line gives the same quote context.
    left = max(left, raw.rfind(b"\r", left, start) + 1, raw.rfind(b"\n", left, start) + 1)
    line_break = _LINE_BREAK.search(raw, end, right)
    if line_break:
        right = line_break.start()
    offset = len(raw[left:start].decode("utf-8"))
    dialogues, _ = _sentence_spans(raw[left:right].decode("utf-8"))
    return _enclosing(dialogues, offset, offset + len(quoted)) is not None


def _evidence_sets(assertion: dict) -> Iterable[dict]:
    for support in _supports({"support": {}, **assertion}):
        yield from support.get("evidence_sets", [])


def _audit(batch: dict, sources: dict[str, bytes] | Iterable[bytes], base: dict) -> tuple:
    records = batch.get("candidate_records", {})
    assertions = v1._index(records, "assertions")
    propositions = {**v1._index(base, "propositions"), **v1._index(records, "propositions")}
    refs = {**v1._index(base, "evidence_refs"), **v1._index(records, "evidence_refs")}
    evidence = v1._Evidence(refs, sources)
    segments = v1._index(base, "source_segments")

    flagged = defaultdict(set)
    non_mention_refs = set()
    wrong_role = {}
    for assertion in assertions.values():
        pid = assertion.get("proposition_id")
        is_mention = propositions.get(pid, {}).get("predicate") in PREDICATES
        eligible = is_mention and assertion.get("polarity") in ("AFFIRMED", "NEGATED")
        for evidence_set in _evidence_sets(assertion):
            ref_ids = evidence_set.get("evidence_ref_ids", [])
            if not is_mention:
                non_mention_refs.update(ref_ids)
            if not eligible or evidence_set.get("label") != "SUFFICIENT":
                continue
            for ref_id in ref_ids:
                if ref_id not in wrong_role:
                    wrong_role[ref_id] = _has_wrong_dialogue_role(evidence, ref_id, segments)
                if wrong_role[ref_id]:
                    flagged[ref_id].add(tuple(sorted({assertion["id"], pid, ref_id})))
    return refs, flagged, non_mention_refs


def check_batch(batch: dict, sources: dict[str, bytes] | Iterable[bytes],
                base: dict | None = None) -> dict:
    """Return the V1 report with the additional R-EVR-01 findings."""
    sources = sources if isinstance(sources, dict) else tuple(sources)
    report = v1.check_batch(batch, sources, base)
    _, flagged, _ = _audit(batch, sources, base or {})
    findings = {ids for uses in flagged.values() for ids in uses}
    report["rules_checked"] = list(RULES)
    report["counts"][RULE] = len(findings)
    report["findings"].extend(
        {"rule": RULE, "code": "MENTION_ROLE_IN_DIALOGUE", "record_ids": list(ids)}
        for ids in findings
    )
    report["findings"].sort(key=lambda issue: (issue["rule"], issue["code"], issue["record_ids"]))
    return report


def _copy_base_refs(records: dict, base: dict, refs: dict, ref_ids: set[str]) -> None:
    """Give base evidence copies fresh candidate ids and redirect candidate citations."""
    occupied = {row["id"] for document in (base, records)
                for rows in document.values() if isinstance(rows, list)
                for row in rows if isinstance(row, dict) and "id" in row}
    occupied.add(base.get("story", {}).get("id"))
    assertions = records.get("assertions", [])
    for assertion in [*base.get("assertions", []), *assertions]:
        for support in _supports({"support": {}, **assertion}):
            for key in ("evidence_sets", "derivations"):
                occupied.update(row["id"] for row in support.get(key, []))

    replacements = {}
    number = 1
    for ref_id in sorted(ref_ids):
        while f"ev-r-evr-01-{number}" in occupied:
            number += 1
        new_id = f"ev-r-evr-01-{number}"
        number += 1
        replacements[ref_id] = new_id
        copy = deepcopy(refs[ref_id])
        copy.update(id=new_id, role="DEPICTION")
        records.setdefault("evidence_refs", []).append(copy)

    for assertion in assertions:
        for evidence_set in _evidence_sets(assertion):
            evidence_set["evidence_ref_ids"] = [
                replacements.get(ref_id, ref_id) for ref_id in evidence_set["evidence_ref_ids"]
            ]
    for mention in records.get("mentions", []):
        ref_id = mention["evidence_ref_id"]
        mention["evidence_ref_id"] = replacements.get(ref_id, ref_id)


def align_mention_roles(batch: dict, sources: dict[str, bytes] | Iterable[bytes],
                        base: dict | None = None) -> tuple[dict, dict]:
    """Align unshared flagged refs in a deep copy for development rescoring only.

    Counts, including by_from_role, are per distinct flagged evidence ref.
    """
    base = base or {}
    refs, flagged, non_mention_refs = _audit(batch, sources, base)
    new_batch = deepcopy(batch)
    records = new_batch.get("candidate_records", {})
    local_refs = v1._index(records, "evidence_refs")
    shared = flagged.keys() & non_mention_refs
    alignable = flagged.keys() - shared
    for ref_id in alignable & local_refs.keys():
        local_refs[ref_id]["role"] = "DEPICTION"
    if base_only := alignable - local_refs.keys():
        _copy_base_refs(records, base, refs, base_only)
    return new_batch, {
        "flagged": len(flagged),
        "aligned": len(alignable),
        "refused_shared": len(shared),
        "by_from_role": dict(sorted(Counter(refs[ref_id]["role"] for ref_id in flagged).items())),
    }


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
        report = check_batch(batch, (path.read_bytes() for path in args.source), base)
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
