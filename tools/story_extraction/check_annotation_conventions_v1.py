"""Deterministic, offline checker for the ten requested M4 conventions V1 rules.

Only AFFIRMED batch assertions and batch mentions/events are audited. Base
records supply lookups, never independent findings. STRING/DATE counters count
distinct batch (proposition id, argument name) pairs reached from those assertions;
nested PROPOSITION references inherit each outer assertion's SUFFICIENT evidence.
A literal is checked once per proposition, against the pooled SUFFICIENT evidence of
every AFFIRMED assertion that reaches it.

Findings contain identifiers only: assertion and proposition ids for assertion
checks, all assertion ids in a conflicting participant group, a mention id for
mention checks, or an event id for a reveal missing Conveys. Duplicate findings
are collapsed. No judged rules, schema validation, or calendar validation run.
All batch evidence spans and any referenced base evidence spans must be verifiable.
Byte offsets are authoritative; character offsets are not used.

    python -m tools.story_extraction.check_annotation_conventions_v1 \
        --batch B.json --source S.txt [--source S2.txt] [--base BASE.json] [--out OUT.json]

Reports contain no source text or literal values. Exit status is 0 even with
findings, or 2 for refused input; refusal diagnostics contain no input content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

RULE_IDS: tuple[str, ...] = (
    "R-ROLE-01", "R-ROLE-02", "R-EVT-02", "R-MEN-01", "R-MEN-02",
    "R-LIT-01", "R-LIT-02", "R-LIT-04", "R-LIT-05", "R-TIME-02",
)
HONORIFICS = ("さん", "くん", "君", "ちゃん", "様", "さま", "先輩", "先生", "殿", "氏")
PARTICLES = ("は", "が", "を", "に", "へ", "と", "で", "も", "の", "から", "まで", "より")
FRAMES = {
    "GENERIC": {"AGENT", "PATIENT", "THEME", "EXPERIENCER", "RECIPIENT", "WITNESS"},
    "TRANSFER": {"SOURCE", "RECIPIENT", "THEME", "AGENT", "WITNESS"},
    "UTTERANCE": {"AGENT", "RECIPIENT", "WITNESS"},
    "MOVEMENT": {"AGENT", "THEME", "WITNESS"},
    "ENCOUNTER": {"AGENT", "THEME", "WITNESS"},
    "ADDRESS_CHANGE": {"AGENT", "RECIPIENT", "WITNESS"},
    "REVEAL_TELL": {"SOURCE", "RECIPIENT", "WITNESS"},
    "REVEAL_DISCOVER": {"RECIPIENT", "THEME", "WITNESS"},
    "REVEAL_INFER": {"RECIPIENT"},
}
ASCII_LETTER = re.compile(r"[A-Za-z]")
DATE = re.compile(r"(?:\d{4}-\d{2}-\d{2}|\d{4}-\d{2}|--\d{2}-\d{2})")


def _index(records: dict, key: str) -> dict[str, dict]:
    rows = records.get(key, [])
    if not isinstance(rows, list):
        raise ValueError("Record collection must be a list")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("Record must have a string id")
        if row["id"] in result:
            raise ValueError("Duplicate record id")
        result[row["id"]] = row
    return result


class _Evidence:
    def __init__(self, refs: dict, sources: dict[str, bytes] | Iterable[bytes]):
        self.refs = refs
        self.sources = {}
        self.cache: dict[str, tuple[str, str]] = {}
        values = sources.values() if isinstance(sources, dict) else sources
        for raw in values:
            if not isinstance(raw, bytes):
                raise ValueError("Source must be raw bytes")
            self.sources[hashlib.sha256(raw).hexdigest()] = raw
        if isinstance(sources, dict) and any(
            key != hashlib.sha256(raw).hexdigest() for key, raw in sources.items()
        ):
            raise ValueError("Source map key does not match source hash")

    def read(self, ref_id: str) -> tuple[str, str]:
        """Verified span text and following source text; never guess a source."""
        if ref_id in self.cache:
            return self.cache[ref_id]
        try:
            span = self.refs[ref_id]["span"]
            raw = self.sources[span["source_sha256"]]
            start, end = span["byte_start"], span["byte_end_exclusive"]
            if (span["kind"] != "TEXT_RANGE_V0" or type(start) is not int
                    or type(end) is not int or not 0 <= start <= end <= len(raw)):
                raise ValueError("Invalid text range")
            quoted = raw[start:end]
            if hashlib.sha256(quoted).hexdigest() != span["span_text_sha256"]:
                raise ValueError("Span hash mismatch")
            raw.decode("utf-8")
            result = quoted.decode("utf-8"), raw[end:].decode("utf-8")
        except (KeyError, TypeError, UnicodeError) as exc:
            raise ValueError("Evidence source or span cannot be verified") from exc
        self.cache[ref_id] = result
        return result


def _walk(proposition_id: str, propositions: dict) -> Iterable[dict]:
    """Visit each reachable proposition once per outer assertion, guarding cycles."""
    pending = [proposition_id]
    seen = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        if current not in propositions:
            raise ValueError("Unknown proposition reference")
        proposition = propositions[current]
        yield proposition
        for arg in proposition.get("args", {}).values():
            if arg.get("kind") == "PROPOSITION":
                pending.append(arg["ref"])


def check_batch(batch: dict, sources: dict[str, bytes] | Iterable[bytes],
                base: dict | None = None) -> dict:
    """Check mechanical conventions, refusing unverifiable evidence with ValueError.

    Missing candidate collections are empty. Batch ids take precedence over base
    ids. Unasserted, NEGATED and OPEN propositions do not contribute literal checks.
    """
    if not isinstance(batch, dict) or not isinstance(batch.get("candidate_records", {}), dict):
        raise ValueError("Batch must contain a candidate-record object")
    if base is not None and not isinstance(base, dict):
        raise ValueError("Base must be an object")
    records = batch.get("candidate_records", {})
    local = {key: _index(records, key) for key in (
        "assertions", "events", "evidence_refs", "mentions", "propositions")}
    lookup = {key: {**_index(base or {}, key), **local[key]}
              for key in ("events", "evidence_refs", "propositions")}
    evidence = _Evidence(lookup["evidence_refs"], sources)
    for ref_id in local["evidence_refs"]:
        evidence.read(ref_id)

    findings: set[tuple[str, str, tuple[str, ...]]] = set()

    def add(rule: str, code: str, *ids: str) -> None:
        findings.add((rule, code, tuple(sorted(set(ids)))))

    assertions = [a for a in local["assertions"].values() if a.get("polarity") == "AFFIRMED"]
    checked = {"assertions": len(assertions), "mentions": len(local["mentions"]),
               "string_literals": 0, "date_literals": 0, "participates": 0}
    literals: dict[str, set[tuple[str, str]]] = {"STRING": set(), "DATE": set()}
    roles = defaultdict(list)
    occurred, conveys = set(), set()
    literal_reach: dict[str, tuple[list[str], list[str]]] = {}
    for assertion in assertions:
        pid = assertion["proposition_id"]
        if pid not in lookup["propositions"]:
            raise ValueError("Unknown assertion proposition")
        proposition = lookup["propositions"][pid]
        predicate, args = proposition.get("predicate"), proposition.get("args", {})
        ids = (assertion["id"], pid)
        if predicate in {"Participates", "Occurred", "Conveys"}:
            event_id = args["event"]["ref"]
            event = lookup["events"].get(event_id)
            kind = event.get("event_kind", "") if event is not None else ""
            if predicate == "Participates":
                checked["participates"] += 1
                role = args["role"]["value"]
                roles[event_id, args["participant"]["ref"]].append((role, assertion["id"]))
                if event is None:
                    add("R-ROLE-02", "UNKNOWN_EVENT", *ids)
                elif role not in FRAMES.get(kind, set()):
                    add("R-ROLE-02", "ROLE_NOT_IN_FRAME", *ids)
            elif predicate == "Occurred":
                occurred.add(event_id)
            else:
                conveys.add(event_id)
                if not kind.startswith("REVEAL_"):
                    add("R-EVT-02", "CONVEYS_ON_NON_REVEAL", *ids)
        if predicate == "TemporalRelation" and args["relation"].get("value") == "AFTER":
            add("R-TIME-02", "AFTER_RELATION", *ids)

        texts = [evidence.read(ref_id)[0]
                 for evidence_set in assertion.get("support", {}).get("evidence_sets", [])
                 if evidence_set.get("label") == "SUFFICIENT"
                 for ref_id in evidence_set.get("evidence_ref_ids", [])]
        for nested in _walk(pid, lookup["propositions"]):
            if nested["id"] in local["propositions"]:
                reach = literal_reach.setdefault(nested["id"], ([], []))
                reach[0].append(assertion["id"])
                reach[1].extend(texts)

    # A literal is judged against the SUFFICIENT evidence of every AFFIRMED assertion that
    # reaches its proposition (R-LIT-02: "at least one"), so an evidence-less SUGGESTED
    # assertion next to an evidenced one is not a finding.
    for nested_id, (assertion_ids, texts) in sorted(literal_reach.items()):
        nested = local["propositions"][nested_id]
        has_ascii = any(ASCII_LETTER.search(text) for text in texts)
        literal_ids = (nested_id, *assertion_ids)
        for name, arg in nested.get("args", {}).items():
            if arg.get("kind") != "LITERAL" or arg.get("value_type") not in literals:
                continue
            value_type, value = arg["value_type"], arg["value"]
            if not isinstance(value, str):
                raise ValueError("STRING and DATE literals must be strings")
            literals[value_type].add((nested_id, name))
            if value_type == "STRING":
                if ASCII_LETTER.search(value) and not has_ascii:
                    add("R-LIT-01", "TRANSLATED_LITERAL", *literal_ids)
                if not any(value in text for text in texts):
                    add("R-LIT-02", "NOT_VERBATIM", *literal_ids)
                if nested.get("predicate") == "NamedAs" and name == "name" and value.endswith(HONORIFICS):
                    add("R-LIT-04", "HONORIFIC_IN_NAME", *literal_ids)
            elif not DATE.fullmatch(value):
                add("R-LIT-05", "BAD_DATE_FORMAT", *literal_ids)

    for group in roles.values():
        if len({role for role, _ in group}) > 1:
            add("R-ROLE-01", "MULTIPLE_ROLES", *(aid for _, aid in group))
    for event in local["events"].values():
        if (event.get("event_kind", "").startswith("REVEAL_")
                and event["id"] in occurred and event["id"] not in conveys):
            add("R-EVT-02", "REVEAL_WITHOUT_CONVEYS", event["id"])
    for mention in local["mentions"].values():
        text, following = evidence.read(mention["evidence_ref_id"])
        if mention.get("surface_form") != text:
            add("R-MEN-01", "SURFACE_FORM_MISMATCH", mention["id"])
        if following.startswith(HONORIFICS) and not text.endswith(HONORIFICS):
            add("R-MEN-02", "HONORIFIC_OUTSIDE_SPAN", mention["id"])
        if text not in PARTICLES and text.endswith(PARTICLES):
            add("R-MEN-02", "TRAILING_PARTICLE", mention["id"])
    checked["string_literals"], checked["date_literals"] = len(literals["STRING"]), len(literals["DATE"])
    counts = Counter(rule for rule, _, _ in findings)
    return {"rules_checked": list(RULE_IDS), "counts": {rule: counts[rule] for rule in RULE_IDS},
            "findings": [{"rule": rule, "code": code, "record_ids": list(ids)}
                         for rule, code, ids in sorted(findings)], "checked": checked}


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
            args.out.write_text(output, encoding="utf-8")
        else:
            print(output, end="")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print("error: refused input or inaccessible report destination", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
