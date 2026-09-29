"""Cross-artifact consistency checks for canonical validation probes.

One canonical probe record is the only authoritative source for a probe's
question, expected answer, propositions, proposition support, and gold sets.
Every review artifact (semantic audit, human review guide, inventory, sign-off
template) is a projection of that record and must match it exactly.

Proposition-support model
-------------------------
Each proposition lists one or more ``supporting_evidence`` entries.  Each entry
names a chunk that *independently* supports the complete proposition, together
with the exact source span (offsets + excerpt) that justifies it.  From this
model the gold evidence sets are fully determined: they must equal the minimal
hitting sets of the per-proposition support families.  That single rule
enforces coverage (every gold set supports every proposition), minimality (no
superfluous chunk), and completeness (every complete alternative path is
represented), for single-gold and multi-gold probes alike.

This module contains no fixture content; tests use synthetic data only.
"""
from itertools import combinations
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set

from tools.story_benchmark.multi_gold_metrics import (
    GoldEvidenceValidationError,
    normalize_gold_evidence_sets,
)

PASSING_CLASSIFICATIONS = {"DIRECTLY_EXPLICIT", "STRONGLY_ENTAILED"}
# Fields that Task Q evaluates and that every review projection must repeat verbatim.
EVALUATED_FIELDS = ("category", "cutoff_chapter", "question", "expected_answer", "gold_evidence_sets")
# Fields the semantic audit carries in addition to the evaluated fields.
AUDIT_FIELDS = EVALUATED_FIELDS + (
    "question_vi",
    "expected_answer_vi",
    "propositions",
    "minimality",
)
MAX_SUPPORT_UNION = 16


def proposition_support(proposition: Mapping[str, Any]) -> FrozenSet[str]:
    """Return the chunk IDs that independently support one proposition.

    Legacy audit rows carry a single ``supporting_chunk_id``; they are read as a
    one-element support family so historical packages can be checked (and fail)
    under the same rule.
    """
    evidence = proposition.get("supporting_evidence")
    if isinstance(evidence, list):
        return frozenset(
            entry.get("chunk_id") for entry in evidence
            if isinstance(entry, Mapping) and isinstance(entry.get("chunk_id"), str)
        )
    legacy = proposition.get("supporting_chunk_id")
    return frozenset([legacy]) if isinstance(legacy, str) and legacy else frozenset()


def minimal_hitting_sets(families: Sequence[FrozenSet[str]]) -> Set[FrozenSet[str]]:
    """Return every inclusion-minimal chunk set intersecting each family."""
    if not families or any(not family for family in families):
        return set()
    universe = sorted(frozenset().union(*families))
    if len(universe) > MAX_SUPPORT_UNION:
        raise ValueError(f"support union too large ({len(universe)} chunks)")
    found: List[FrozenSet[str]] = []
    for size in range(1, len(universe) + 1):
        for combo in combinations(universe, size):
            candidate = frozenset(combo)
            if any(prior <= candidate for prior in found):
                continue
            if all(candidate & family for family in families):
                found.append(candidate)
    return set(found)


def check_proposition_gold_coverage(probe: Mapping[str, Any]) -> List[str]:
    """Check that gold sets are exactly implied by the proposition-support model."""
    probe_id = probe.get("probe_id", "<unknown>")
    issues: List[str] = []
    propositions = probe.get("propositions")
    if not isinstance(propositions, list) or not propositions:
        return [f"{probe_id}: no propositions"]
    try:
        gold_sets = [frozenset(s) for s in normalize_gold_evidence_sets(probe)]
    except GoldEvidenceValidationError as exc:
        return [f"{probe_id}: invalid gold evidence: {exc}"]

    families: List[FrozenSet[str]] = []
    for proposition in propositions:
        pid = proposition.get("proposition_id", "<unknown>")
        support = proposition_support(proposition)
        if not support:
            issues.append(f"{probe_id} {pid}: proposition has no supporting chunk")
            continue
        families.append(support)
        for index, gold_set in enumerate(gold_sets, 1):
            if not support & gold_set:
                issues.append(
                    f"{probe_id} {pid}: gold set {index} {sorted(gold_set)} contains none of "
                    f"its supporting chunks {sorted(support)}"
                )
    if issues:
        return issues

    for index, gold_set in enumerate(gold_sets, 1):
        for chunk_id in sorted(gold_set):
            if all(family & (gold_set - {chunk_id}) for family in families):
                issues.append(
                    f"{probe_id}: chunk {chunk_id} in gold set {index} is not required by any "
                    "proposition (non-minimal gold set)"
                )
    implied = minimal_hitting_sets(families)
    missing = implied - set(gold_sets)
    for path in sorted(sorted(p) for p in missing):
        issues.append(f"{probe_id}: complete alternative path {path} is not represented")
    return issues


def check_minimality_records(probe: Mapping[str, Any]) -> List[str]:
    """Minimality records must reference exactly the current gold-set chunks."""
    probe_id = probe.get("probe_id", "<unknown>")
    records = probe.get("minimality")
    if not isinstance(records, list) or not records:
        return [f"{probe_id}: missing minimality records"]
    try:
        gold_union = set().union(*map(set, normalize_gold_evidence_sets(probe)))
    except GoldEvidenceValidationError as exc:
        return [f"{probe_id}: invalid gold evidence: {exc}"]
    recorded = [r.get("chunk_id") for r in records if isinstance(r, Mapping)]
    issues = []
    if len(recorded) != len(set(recorded)):
        issues.append(f"{probe_id}: duplicate minimality records")
    for chunk_id in sorted(set(recorded) - gold_union, key=str):
        issues.append(f"{probe_id}: stale minimality record for non-gold chunk {chunk_id}")
    for chunk_id in sorted(gold_union - set(recorded)):
        issues.append(f"{probe_id}: gold chunk {chunk_id} has no minimality record")
    return issues


def check_evidence_spans(
    probe: Mapping[str, Any], chunk_texts: Mapping[str, str]
) -> List[str]:
    """Every support excerpt must be the exact, untruncated chunk slice at its offsets."""
    probe_id = probe.get("probe_id", "<unknown>")
    issues: List[str] = []
    for proposition in probe.get("propositions") or []:
        pid = proposition.get("proposition_id", "<unknown>")
        entries = proposition.get("supporting_evidence")
        if not isinstance(entries, list) or not entries:
            issues.append(f"{probe_id} {pid}: missing supporting_evidence entries")
            continue
        for entry in entries:
            chunk_id = entry.get("chunk_id")
            text = chunk_texts.get(chunk_id)
            if text is None:
                issues.append(f"{probe_id} {pid}: unknown support chunk {chunk_id}")
                continue
            offsets = entry.get("source_offsets")
            excerpt = entry.get("source_excerpt")
            if (
                not isinstance(offsets, list) or len(offsets) != 2
                or not all(isinstance(o, int) for o in offsets)
                or not 0 <= offsets[0] < offsets[1] <= len(text)
            ):
                issues.append(f"{probe_id} {pid}: invalid offsets {offsets!r} for {chunk_id}")
                continue
            if not isinstance(excerpt, str) or not excerpt.strip():
                issues.append(f"{probe_id} {pid}: empty excerpt for {chunk_id}")
            elif text[offsets[0]:offsets[1]] != excerpt:
                issues.append(
                    f"{probe_id} {pid}: excerpt for {chunk_id} is not the exact source slice "
                    f"at {offsets} (truncated or stale)"
                )
    return issues


def check_classifications(probe: Mapping[str, Any]) -> List[str]:
    probe_id = probe.get("probe_id", "<unknown>")
    return [
        f"{probe_id} {p.get('proposition_id')}: classification {p.get('classification')!r} "
        "is not accepted for a primary probe"
        for p in probe.get("propositions") or []
        if p.get("classification") not in PASSING_CLASSIFICATIONS
    ]


def semantic_status(probe: Mapping[str, Any]) -> str:
    return "PASS" if not check_classifications(probe) else "FAIL"


def _normalized(field: str, value: Any) -> Any:
    if field == "gold_evidence_sets":
        try:
            return normalize_gold_evidence_sets({"gold_evidence_sets": value})
        except GoldEvidenceValidationError:
            return ("<invalid>", repr(value))
    return value


def compare_probe_fields(
    canonical: Mapping[str, Any],
    other: Mapping[str, Any],
    label: str,
    fields: Iterable[str] = EVALUATED_FIELDS,
) -> List[Dict[str, Any]]:
    """Return one mismatch record per field that differs from the canonical probe."""
    mismatches = []
    for field in fields:
        expected = _normalized(field, canonical.get(field))
        actual = _normalized(field, other.get(field))
        if expected != actual:
            mismatches.append({
                "probe_id": canonical.get("probe_id"),
                "artifact": label,
                "field": field,
            })
    return mismatches


def audit_projection(probe: Mapping[str, Any]) -> Dict[str, Any]:
    """Semantic-audit row generated from a canonical probe."""
    row = {field: probe.get(field) for field in AUDIT_FIELDS}
    row.update({
        "probe_id": probe["probe_id"],
        "partition": "primary",
        "gold_schema_version": 2,
        "technical_status": semantic_status(probe),
        "agent_recommendation": probe.get("agent_recommendation"),
        "human_decision": "PENDING_REVIEW",
    })
    return row


def expected_facts(probe: Mapping[str, Any]) -> List[str]:
    """Evaluation facts are derived from propositions, never maintained separately."""
    return [p["proposition_en"] for p in probe.get("propositions") or []]


def _quote(text: str) -> str:
    return "  > " + text.replace("\r\n", "\n").replace("\n", "\n  > ")


def render_review_guide(probes: Sequence[Mapping[str, Any]], header_lines: Sequence[str]) -> str:
    """Deterministically render the Vietnamese human review guide from canonical probes.

    The guide shows the exact English question and expected answer that will be
    evaluated, followed by Vietnamese aids, so reviewers inspect evaluated text.
    """
    out = ["# Hướng dẫn Product Owner rà soát\n"]
    out.extend(f"- {line}\n" for line in header_lines)
    out.append("\n")
    for probe in probes:
        out.append(f"## {probe['probe_id']} — {probe['category']} — cutoff {probe['cutoff_chapter']}\n\n")
        out.append(f"**Câu hỏi được đánh giá (nguyên văn):** {probe['question']}\n\n")
        out.append(f"**Đáp án kỳ vọng được đánh giá (nguyên văn):** {probe['expected_answer']}\n\n")
        out.append(f"**Câu hỏi (tiếng Việt, tham khảo):** {probe.get('question_vi', '')}\n\n")
        out.append(f"**Đáp án (tiếng Việt, tham khảo):** {probe.get('expected_answer_vi', '')}\n\n")
        out.append("**Các tập gold hợp lệ:**\n\n")
        for index, gold_set in enumerate(probe["gold_evidence_sets"], 1):
            out.append(f"- Đường {index}: `{', '.join(gold_set)}`\n")
        out.append("\n**Đối chiếu mệnh đề:**\n\n")
        for prop in probe.get("propositions") or []:
            support_ids = ", ".join(e["chunk_id"] for e in prop.get("supporting_evidence") or [])
            out.append(
                f"- `{prop['proposition_id']}` — `{prop['classification']}` — "
                f"{prop.get('proposition_vi', '')}\n\n"
                f"  Mệnh đề (EN): {prop.get('proposition_en', '')}\n\n"
                f"  Chunk hỗ trợ độc lập: `{support_ids}`\n\n"
            )
            for entry in prop.get("supporting_evidence") or []:
                out.append(f"  Nguồn `{entry['chunk_id']}` {entry['source_offsets']}:\n\n")
                out.append(_quote(entry["source_excerpt"]) + "\n\n")
            out.append(f"  Lý do: {prop.get('rationale_vi', '')}\n\n")
        out.append("**Quyết định Product Owner:** `PENDING_REVIEW`\n\n")
    return "".join(out)


INVENTORY_FIELDS = [
    "probe_id", "partition", "category", "cutoff", "gold_schema_version",
    "gold_set_count", "semantic_status", "alternative_evidence_status",
    "agent_recommendation", "human_decision", "notes",
]
SIGNOFF_FIELDS = [
    "probe_id", "partition", "agent_recommendation", "human_decision",
    "human_notes", "reviewed_at", "reviewer_role", "source_package_filename",
    "source_package_sha256",
]


def inventory_row(probe: Mapping[str, Any]) -> Dict[str, str]:
    return {
        "probe_id": probe["probe_id"],
        "partition": "primary",
        "category": probe["category"],
        "cutoff": str(probe["cutoff_chapter"]),
        "gold_schema_version": "2",
        "gold_set_count": str(len(probe["gold_evidence_sets"])),
        "semantic_status": semantic_status(probe),
        "alternative_evidence_status": probe.get("alternative_evidence_status", ""),
        "agent_recommendation": probe.get("agent_recommendation", ""),
        "human_decision": "PENDING_REVIEW",
        "notes": "Generated from canonical fixture; no human approval inferred.",
    }


def write_projection_artifacts(
    out_dir,
    fixture: Mapping[str, Any],
    non_primary_inventory: Sequence[Mapping[str, str]],
    guide_header_lines: Sequence[str],
    package_filename: str,
) -> None:
    """Write the canonical fixture and every review projection generated from it."""
    import csv
    import json
    from pathlib import Path

    import yaml

    out = Path(out_dir)
    probes = fixture["probes"]
    (out / "canonical_primary_fixture.yaml").write_text(
        yaml.safe_dump(dict(fixture), allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8", newline="\n",
    )
    (out / "primary_semantic_audit_v3.jsonl").write_text(
        "".join(
            json.dumps(audit_projection(p), ensure_ascii=False, sort_keys=True) + "\n"
            for p in probes
        ),
        encoding="utf-8", newline="\n",
    )
    (out / "human_review_guide_vi_v3.md").write_text(
        render_review_guide(probes, guide_header_lines), encoding="utf-8", newline="\n"
    )
    rows = [inventory_row(p) for p in probes] + [dict(r) for r in non_primary_inventory]
    with (out / "final_probe_inventory_v3.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=INVENTORY_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with (out / "human_signoff_template_v3.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SIGNOFF_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "probe_id": row["probe_id"],
                "partition": row["partition"],
                "agent_recommendation": row["agent_recommendation"],
                "human_decision": "PENDING_REVIEW",
                "human_notes": "",
                "reviewed_at": "",
                "reviewer_role": "",
                "source_package_filename": package_filename,
                "source_package_sha256": "",
            })


def check_probe(
    probe: Mapping[str, Any], chunk_texts: Optional[Mapping[str, str]] = None
) -> List[str]:
    """All single-probe structural checks against the canonical record."""
    issues = []
    issues += check_classifications(probe)
    issues += check_proposition_gold_coverage(probe)
    issues += check_minimality_records(probe)
    if chunk_texts is not None:
        issues += check_evidence_spans(probe, chunk_texts)
    return issues
