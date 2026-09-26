"""
Validator for INDEPENDENT_VALIDATION_FIXTURE_V1 (TASK M1-30CH-P)

Validates the 25-probe independent validation fixture:
- schema and unique IDs
- source-chunk existence and chapter cutoff
- required evidence count and multi-chunk constraints
- 5 categories x 5 probes balance
- duplicate question and overlap audit with LONG_RANGE_PROBE_V1
- annotation status and human review readiness
- corpus fingerprint integrity
- privacy compliance
"""
import csv
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

EXPECTED_PROBE_COUNT = 25
EXPECTED_PER_CATEGORY = 5
CATEGORIES = [
    "CHRONOLOGY",
    "RELATIONSHIP_PROGRESSION",
    "CALLBACK",
    "TEMPORAL_STATE",
    "SPOILER_BOUNDARY",
]
CORPUS_FINGERPRINT_SHA256 = "7f9bb8106d6d50acd2b3760738c0b8040f36ab547c2d2f7eade1ca0b9a827ff8"
CHUNKS_JSONL_SHA256 = "10ef5681ad1b2db0882c150efa24804cd0fca56bb38e0ffb772d22494e1e40fb"
VALID_ANNOTATION_STATUSES = {"PENDING_REVIEW", "APPROVED", "NEEDS_REVISION", "REJECTED"}
VALID_HUMAN_DECISIONS = {"APPROVED", "NEEDS_REVISION", "REJECTED", "DEFERRED"}
VALID_SEMANTIC_CLASSIFICATIONS = {
    "DIRECTLY_EXPLICIT",
    "STRONGLY_ENTAILED",
    "INTERPRETIVE_INFERENCE",
    "AMBIGUOUS",
    "UNSUPPORTED",
}
VALID_ALTERNATIVE_CLASSIFICATIONS = {
    "NO_ALTERNATIVE_FOUND",
    "PARTIAL_ALTERNATIVE_FOUND",
    "COMPLETE_ALTERNATIVE_FOUND",
    "UNCERTAIN",
}
CHUNK_ID_RE = re.compile(r"ch\d{3}_c\d{4}")
PROBE_ID_RE = re.compile(r"\bV_[A-Z]+_\d{2}\b")


class FixtureValidationError(RuntimeError):
    pass


def sha256_file(p: Path) -> str:
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def validate_validation_probes(
    probes_path: Path,
    chunks_path: Path,
    orig_probes_path: Optional[Path] = None,
    expected_probe_count: Optional[int] = EXPECTED_PROBE_COUNT,
    expected_per_category: Optional[int] = EXPECTED_PER_CATEGORY,
    check_intra_fixture_duplicates: bool = False,
) -> Dict[str, Any]:
    issues: List[str] = []

    if not probes_path.exists():
        issues.append(f"Validation probe file not found at {probes_path}")
        return {"pass": False, "issues": issues, "metrics": {}}

    if not chunks_path.exists():
        issues.append(f"Chunks file not found at {chunks_path}")
        return {"pass": False, "issues": issues, "metrics": {}}

    with open(probes_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    probes = data.get("probes", [])
    if expected_probe_count is not None:
        if len(probes) != expected_probe_count:
            issues.append(f"Expected {expected_probe_count} probes, got {len(probes)}")
    elif len(probes) < 1:
        issues.append("Validation probe file must contain at least 1 probe")

    # Load chunk metadata and verify fingerprint
    chunk_meta: Dict[str, int] = {}
    fingerprints = set()
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                chunk_meta[c["chunk_id"]] = c["chapter_number"]
                fingerprints.add(c.get("corpus_fingerprint_sha256"))

    if fingerprints != {CORPUS_FINGERPRINT_SHA256}:
        issues.append(f"Corpus fingerprint mismatch in chunks file: {fingerprints}")

    # Load original probes for overlap check if provided
    orig_chunk_sets = []
    orig_questions = []
    if orig_probes_path and orig_probes_path.exists():
        with open(orig_probes_path, "r", encoding="utf-8") as f:
            o_data = yaml.safe_load(f)
            for o_p in o_data.get("probes", []):
                orig_chunk_sets.append(set(o_p.get("required_evidence_chunk_ids", [])))
                orig_questions.append(o_p.get("question", "").strip().lower())

    probe_ids = set()
    questions = set()
    cat_counts = {c: 0 for c in CATEGORIES}
    status_counts = {s: 0 for s in VALID_ANNOTATION_STATUSES}
    seen_val_chunk_sets = {}

    multi_chunk_count = 0
    multi_chap_count = 0
    span_ge_5_count = 0
    span_ge_10_count = 0
    chapter_spans = []

    for p in probes:
        pid = p.get("probe_id")
        if not pid:
            issues.append("Empty probe_id found")
            continue

        if pid in probe_ids:
            issues.append(f"Duplicate probe_id {pid}")
        probe_ids.add(pid)

        cat = p.get("category")
        if not cat:
            issues.append(f"Empty category in {pid}")
        elif cat not in CATEGORIES:
            issues.append(f"Invalid category {cat} in {pid}")
        else:
            cat_counts[cat] += 1

        # Annotation status check
        status = p.get("annotation_status")
        if not status:
            issues.append(f"Missing annotation_status in {pid}")
        elif status not in VALID_ANNOTATION_STATUSES:
            issues.append(f"Invalid annotation_status {status} in {pid}")
        else:
            status_counts[status] += 1

        # Non-empty content fields
        for field in [
            "question",
            "expected_answer",
            "expected_facts",
            "difficulty_notes",
            "evidence_justification",
            "source_chapter_references",
        ]:
            if not p.get(field):
                issues.append(f"Empty or missing field '{field}' in {pid}")

        q_clean = p.get("question", "").strip().lower()
        if q_clean in questions:
            issues.append(f"Duplicate question text across validation probes in {pid}")
        questions.add(q_clean)

        # Check question against original probes
        if q_clean in orig_questions:
            issues.append(f"Question in {pid} duplicates an inquiry from original LONG_RANGE_PROBE_V1")

        cutoff = p.get("cutoff_chapter")
        if not cutoff or not (1 <= cutoff <= 30):
            issues.append(f"Invalid cutoff_chapter {cutoff} in {pid}")
            cutoff = 30

        if cat == "SPOILER_BOUNDARY" and cutoff >= 30:
            issues.append(f"SPOILER_BOUNDARY probe must have cutoff_chapter < 30 in {pid}")

        req = p.get("required_evidence_chunk_ids", [])
        sup = p.get("supporting_evidence_chunk_ids", [])

        if not req:
            issues.append(f"required_evidence_chunk_ids empty in {pid}")
        if len(req) < 2:
            issues.append(f"Validation probe {pid} must require at least 2 chunks, got {len(req)}")

        if len(req) != len(set(req)):
            issues.append(f"Duplicate chunk in required list in {pid}")
        if len(sup) != len(set(sup)):
            issues.append(f"Duplicate chunk in supporting list in {pid}")
        if set(req).intersection(set(sup)):
            issues.append(f"Intersection between required and supporting evidence in {pid}")

        # Check required chunk set against original probes
        req_set = set(req)
        for idx, o_set in enumerate(orig_chunk_sets):
            if req_set == o_set:
                issues.append(f"Required evidence set in {pid} is identical to original probe index {idx}")

        if check_intra_fixture_duplicates:
            for seen_pid, seen_set in seen_val_chunk_sets.items():
                if req_set == seen_set:
                    issues.append(f"Intra-fixture duplicate required evidence set: {pid} duplicates {seen_pid}")
            seen_val_chunk_sets[pid] = req_set

        req_chapters = []
        for cid in req:
            if cid not in chunk_meta:
                issues.append(f"Chunk {cid} not found in chunks.jsonl for {pid}")
            else:
                ch = chunk_meta[cid]
                req_chapters.append(ch)
                if ch > cutoff:
                    issues.append(f"Required evidence chunk {cid} (ch {ch}) exceeds cutoff {cutoff} in {pid}")

        for cid in sup:
            if cid not in chunk_meta:
                issues.append(f"Chunk {cid} not found in chunks.jsonl for {pid}")
            else:
                ch = chunk_meta[cid]
                if ch > cutoff:
                    issues.append(f"Supporting evidence chunk {cid} (ch {ch}) exceeds cutoff {cutoff} in {pid}")

        if req_chapters:
            earliest = min(req_chapters)
            latest = max(req_chapters)
            span = latest - earliest + 1

            if p.get("earliest_required_chapter") != earliest:
                issues.append(f"earliest_required_chapter mismatch in {pid}: expected {earliest}")
            if p.get("latest_required_chapter") != latest:
                issues.append(f"latest_required_chapter mismatch in {pid}: expected {latest}")
            if p.get("chapter_span") != span:
                issues.append(f"chapter_span mismatch in {pid}: expected {span}")
            if p.get("requires_multi_chunk") != (len(req) > 1):
                issues.append(f"requires_multi_chunk mismatch in {pid}")
            if p.get("requires_multi_chapter") != (len(set(req_chapters)) > 1):
                issues.append(f"requires_multi_chapter mismatch in {pid}")

            if len(req) > 1:
                multi_chunk_count += 1
            if len(set(req_chapters)) > 1:
                multi_chap_count += 1
            if span >= 5:
                span_ge_5_count += 1
            if span >= 10:
                span_ge_10_count += 1
            chapter_spans.append(span)

        forbidden = p.get("forbidden_future_chapters", [])
        expected_forbidden = list(range(cutoff + 1, 31)) if cutoff < 30 else []
        if forbidden != expected_forbidden:
            issues.append(f"forbidden_future_chapters mismatch in {pid}: expected {expected_forbidden}, got {forbidden}")

    # Category balance check
    if expected_per_category is not None:
        for cat in CATEGORIES:
            if cat_counts[cat] != expected_per_category:
                issues.append(f"Category {cat} has {cat_counts[cat]} probes, expected {expected_per_category}")
    else:
        for cat, cnt in cat_counts.items():
            if cnt > 0 and cat not in CATEGORIES:
                issues.append(f"Invalid category {cat} in fixture")

    metrics = {
        "probe_count": len(probes),
        "target_probe_count": EXPECTED_PROBE_COUNT,
        "per_category_counts": cat_counts,
        "annotation_status_counts": status_counts,
        "multi_chunk_probe_count": multi_chunk_count,
        "multi_chapter_probe_count": multi_chap_count,
        "span_ge_5_chapter_probe_count": span_ge_5_count,
        "span_ge_10_chapter_probe_count": span_ge_10_count,
        "minimum_chapter_span": min(chapter_spans) if chapter_spans else 0,
        "maximum_chapter_span": max(chapter_spans) if chapter_spans else 0,
    }

    return {
        "pass": len(issues) == 0,
        "issues": issues,
        "metrics": metrics,
    }


def find_privacy_leaks_in_manifest(manifest_text: str) -> List[str]:
    leaks = []
    if CHUNK_ID_RE.search(manifest_text):
        leaks.append("<chunk-id pattern>")
    if PROBE_ID_RE.search(manifest_text):
        leaks.append("<validation-probe-id pattern>")
    return leaks


def validate_source_gold_audit_and_partitions(
    draft_probes_path: Path,
    audit_path: Path,
    aux_def_path: Path,
    chunks_path: Path,
    expected_total_probes: int = 25,
) -> Dict[str, Any]:
    issues: List[str] = []

    if not draft_probes_path.exists():
        issues.append(f"Draft probes file not found: {draft_probes_path}")
        return {"pass": False, "issues": issues}
    if not audit_path.exists():
        issues.append(f"Audit file not found: {audit_path}")
        return {"pass": False, "issues": issues}
    if not aux_def_path.exists():
        issues.append(f"Auxiliary and deferred file not found: {aux_def_path}")
        return {"pass": False, "issues": issues}
    if not chunks_path.exists():
        issues.append(f"Chunks file not found: {chunks_path}")
        return {"pass": False, "issues": issues}

    # 1. Load chunks
    chunks: Dict[str, Dict[str, Any]] = {}
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                chunks[c["chunk_id"]] = c

    # 2. Load draft probes
    with open(draft_probes_path, "r", encoding="utf-8") as f:
        draft_data = yaml.safe_load(f)
    draft_probes = {p["probe_id"]: p for p in draft_data.get("probes", [])}

    # 3. Load auxiliary & deferred probes
    with open(aux_def_path, "r", encoding="utf-8") as f:
        aux_def_data = yaml.safe_load(f)
    aux_probes = {p["probe_id"]: p for p in aux_def_data.get("auxiliary_single_chunk_probes", [])}
    def_probes = {p["probe_id"]: p for p in aux_def_data.get("deferred_probes", [])}

    # 4. Partition disjointness and completeness check
    p_set = set(draft_probes.keys())
    a_set = set(aux_probes.keys())
    d_set = set(def_probes.keys())

    if p_set & a_set:
        issues.append(f"Partition overlap between primary and auxiliary: {sorted(list(p_set & a_set))}")
    if p_set & d_set:
        issues.append(f"Partition overlap between primary and deferred: {sorted(list(p_set & d_set))}")
    if a_set & d_set:
        issues.append(f"Partition overlap between auxiliary and deferred: {sorted(list(a_set & d_set))}")

    union_set = p_set | a_set | d_set
    if expected_total_probes is not None and len(union_set) != expected_total_probes:
        issues.append(f"Partition union count {len(union_set)} != expected total {expected_total_probes}")

    # 5. Load and validate audit records
    audit_records: Dict[str, Dict[str, Any]] = {}
    with open(audit_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            if line.strip():
                rec = json.loads(line)
                pid = rec.get("probe_id")
                if not pid:
                    issues.append(f"Line {line_num} in audit has empty probe_id")
                    continue
                if pid in audit_records:
                    issues.append(f"Duplicate audit record for probe_id {pid}")
                audit_records[pid] = rec

    # Check that primary draft probes and audit records match 1-to-1
    if p_set != set(audit_records.keys()):
        issues.append(f"Draft probe IDs and audit probe IDs do not match: draft={sorted(list(p_set))}, audit={sorted(list(audit_records.keys()))}")

    # Check each audit record in detail
    for pid, rec in audit_records.items():
        if pid not in draft_probes:
            continue
        dp = draft_probes[pid]

        # Consistency: Question, Answer, Cutoff
        if dp.get("question") != rec.get("question_original"):
            issues.append(f"Question mismatch in {pid} between draft and audit")
        if dp.get("expected_answer") != rec.get("expected_answer_original"):
            issues.append(f"Expected answer mismatch in {pid} between draft and audit")
        if dp.get("cutoff_chapter") != rec.get("cutoff_chapter"):
            issues.append(f"Cutoff chapter mismatch in {pid} between draft and audit")

        cutoff = rec.get("cutoff_chapter", 30)
        req_chunks = set(dp.get("required_evidence_chunk_ids", []))

        # Check minimality chunk list matches required chunks
        cf_chunks = [cf.get("chunk_id") for cf in rec.get("minimality_and_multi_evidence", [])]
        if cf_chunks != dp.get("required_evidence_chunk_ids", []):
            issues.append(f"Minimality chunk list mismatch in {pid}: {cf_chunks} != {dp.get('required_evidence_chunk_ids')}")

        # Check propositions
        props = rec.get("expected_propositions", [])
        if not props:
            issues.append(f"No expected_propositions in audit for {pid}")

        prop_chunks = set()
        for prop in props:
            pr_id = prop.get("proposition_id", "?")
            cid = prop.get("supporting_chunk_id")
            if not cid:
                issues.append(f"Empty supporting_chunk_id in proposition {pr_id} of {pid}")
                continue

            if cid not in chunks:
                issues.append(f"Supporting chunk {cid} in proposition {pr_id} of {pid} does not exist in corpus")
                continue

            prop_chunks.add(cid)
            chunk_data = chunks[cid]
            chunk_text = chunk_data.get("text", "")
            actual_ch = chunk_data.get("chapter_number")

            # Chapter metadata check
            if prop.get("chapter_number") != actual_ch:
                issues.append(f"Chapter metadata mismatch in proposition {pr_id} of {pid}: prop says {prop.get('chapter_number')}, chunk says {actual_ch}")

            # Cutoff check
            if actual_ch > cutoff:
                issues.append(f"Cutoff violation in proposition {pr_id} of {pid}: chunk {cid} (ch {actual_ch}) exceeds cutoff {cutoff}")

            # Character span bounds check
            s = prop.get("char_offset_start")
            e = prop.get("char_offset_end")
            excerpt = prop.get("exact_excerpt", "")

            if s is None or e is None or not (0 <= s < e <= len(chunk_text)):
                issues.append(f"Invalid character span bounds [{s}:{e}] for chunk len {len(chunk_text)} in proposition {pr_id} of {pid}")
                continue

            # Exact slice check
            actual_slice = chunk_text[s:e]
            if actual_slice != excerpt:
                issues.append(f"Source slice mismatch in proposition {pr_id} of {pid} ({cid} [{s}:{e}]): actual slice != exact_excerpt")

        # Proposition mapping completeness (no unmapped required chunk, no orphan proposition)
        if prop_chunks != req_chunks:
            issues.append(f"Proposition chunk mapping mismatch in {pid}: required={sorted(list(req_chunks))}, propositions={sorted(list(prop_chunks))}")

    return {
        "pass": len(issues) == 0,
        "issues": issues,
        "counts": {
            "primary": len(p_set),
            "auxiliary": len(a_set),
            "deferred": len(d_set),
            "total_accounted": len(union_set),
        }
    }


def validate_review_artifact_bundle(
    artifact_dir: Path,
    chunks_path: Path,
    orig_probes_path: Optional[Path] = None,
    expected_total_probes: int = 25,
) -> Dict[str, Any]:
    """Validate a complete private review bundle without judging story semantics.

    This adds cross-file and packaging checks to the lower-level fixture validators:
    exact source spans, partition coverage, PENDING_REVIEW status, draft/audit/review
    packet synchronization, derived statistics, and manifest hashes. Semantic
    correctness remains a human/source-reading responsibility.
    """
    issues: List[str] = []
    names = {
        "draft": "draft_probes.yaml",
        "audit": "source_gold_audit.jsonl",
        "packet": "human_review_packet.md",
        "revision": "revision_log.jsonl",
        "partitions": "auxiliary_and_deferred.yaml",
        "report": "validation_report.json",
        "log": "raw_test_log.txt",
        "manifest": "manifest.json",
    }
    paths = {key: artifact_dir / value for key, value in names.items()}
    for key, path in paths.items():
        if not path.exists():
            issues.append(f"Missing required artifact {key}: {path}")
    if issues:
        return {"pass": False, "issues": issues, "counts": {}, "metrics": {}}

    probe_result = validate_validation_probes(
        paths["draft"],
        chunks_path,
        orig_probes_path,
        expected_probe_count=None,
        expected_per_category=None,
        check_intra_fixture_duplicates=True,
    )
    issues.extend(probe_result.get("issues", []))

    audit_result = validate_source_gold_audit_and_partitions(
        paths["draft"],
        paths["audit"],
        paths["partitions"],
        chunks_path,
        expected_total_probes=expected_total_probes,
    )
    issues.extend(audit_result.get("issues", []))

    with open(paths["draft"], "r", encoding="utf-8") as f:
        draft_data = yaml.safe_load(f) or {}
    primary = {p["probe_id"]: p for p in draft_data.get("probes", [])}

    with open(paths["partitions"], "r", encoding="utf-8") as f:
        partition_data = yaml.safe_load(f) or {}
    auxiliary = {
        p["probe_id"]: p
        for p in partition_data.get("auxiliary_single_chunk_probes", [])
    }
    deferred = {
        p["probe_id"]: p for p in partition_data.get("deferred_probes", [])
    }

    audit_records: Dict[str, Dict[str, Any]] = {}
    with open(paths["audit"], "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                audit_records[rec["probe_id"]] = rec

    revision_records: Dict[str, Dict[str, Any]] = {}
    with open(paths["revision"], "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            pid = rec.get("probe_id")
            if not pid:
                issues.append(f"Revision log line {line_num} has no probe_id")
            elif pid in revision_records:
                issues.append(f"Duplicate revision log record for {pid}")
            else:
                revision_records[pid] = rec

    all_ids = set(primary) | set(auxiliary) | set(deferred)
    if set(revision_records) != all_ids:
        issues.append(
            "Revision log IDs do not match the complete partition union: "
            f"revision={sorted(revision_records)}, union={sorted(all_ids)}"
        )

    for partition_name, records in (
        ("primary", primary),
        ("auxiliary", auxiliary),
        ("deferred", deferred),
    ):
        for pid, record in records.items():
            status = record.get("annotation_status")
            if status != "PENDING_REVIEW":
                issues.append(
                    f"{pid} in {partition_name} has annotation_status={status!r}; "
                    "expected PENDING_REVIEW"
                )

    packet_text = paths["packet"].read_text(encoding="utf-8")
    packet_normalized = packet_text.replace("\r\n", "\n")
    for pid, draft in primary.items():
        audit = audit_records.get(pid)
        if audit is None:
            continue
        required_texts = [
            pid,
            draft.get("question", ""),
            draft.get("expected_answer", ""),
            audit.get("question_vi", ""),
            audit.get("expected_answer_vi", ""),
        ]
        required_texts.extend(draft.get("required_evidence_chunk_ids", []))
        for proposition in audit.get("expected_propositions", []):
            required_texts.extend(
                [
                    proposition.get("proposition_en", ""),
                    proposition.get("proposition_vi", ""),
                    proposition.get("exact_excerpt", ""),
                ]
            )
        for removal in audit.get("minimality_and_multi_evidence", []):
            required_texts.append(removal.get("missing_answer_part_if_removed", ""))
        for value in required_texts:
            normalized_value = value.replace("\r\n", "\n") if isinstance(value, str) else value
            if normalized_value and normalized_value not in packet_normalized:
                issues.append(f"Human review packet is not synchronized for {pid}")
                break

        if audit.get("human_review_status") != "PENDING_REVIEW":
            issues.append(
                f"{pid} audit human_review_status is not PENDING_REVIEW"
            )

    for pid, record in revision_records.items():
        if record.get("annotation_status") != "PENDING_REVIEW":
            issues.append(
                f"{pid} revision annotation_status is not PENDING_REVIEW"
            )

    chapter_by_chunk: Dict[str, int] = {}
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                chunk = json.loads(line)
                chapter_by_chunk[chunk["chunk_id"]] = chunk["chapter_number"]

    multi_chunk = 0
    multi_chapter = 0
    for probe in primary.values():
        required = probe.get("required_evidence_chunk_ids", [])
        chapters = {chapter_by_chunk[cid] for cid in required if cid in chapter_by_chunk}
        multi_chunk += len(required) > 1
        multi_chapter += len(chapters) > 1

    derived = {
        "primary": len(primary),
        "auxiliary": len(auxiliary),
        "deferred": len(deferred),
        "total": len(all_ids),
        "primary_multi_chunk": multi_chunk,
        "primary_multi_chapter": multi_chapter,
    }

    with open(paths["manifest"], "r", encoding="utf-8") as f:
        manifest = json.load(f)
    if manifest.get("statistics") != derived:
        issues.append(
            f"Manifest statistics mismatch: {manifest.get('statistics')} != {derived}"
        )
    manifest_files = manifest.get("files", {})
    if names["manifest"] in manifest_files:
        issues.append("Manifest must not contain a hash of itself")
    expected_hashed_files = set(names.values()) - {names["manifest"]}
    if set(manifest_files) != expected_hashed_files:
        issues.append(
            "Manifest file coverage mismatch: "
            f"{sorted(manifest_files)} != {sorted(expected_hashed_files)}"
        )
    for filename, metadata in manifest_files.items():
        file_path = artifact_dir / filename
        if not file_path.exists():
            continue
        actual_hash = sha256_file(file_path)
        if metadata.get("sha256") != actual_hash:
            issues.append(f"Manifest SHA-256 mismatch for {filename}")
        if metadata.get("bytes") != file_path.stat().st_size:
            issues.append(f"Manifest byte-size mismatch for {filename}")

    return {
        "pass": len(issues) == 0,
        "issues": issues,
        "counts": audit_result.get("counts", {}),
        "metrics": derived,
        "probe_metrics": probe_result.get("metrics", {}),
    }


def validate_review_gate_deliverables(
    gate_dir: Path,
    expected_total_probes: int = 25,
) -> Dict[str, Any]:
    """Validate the 8 review gate deliverables in M1_30CH_P_REVIEW_GATE.

    Checks:
    - All 8 required deliverables exist:
        1. review_packet_vi.md
        2. review_decisions.csv
        3. source_review_findings.jsonl
        4. multi_gold_feasibility.md
        5. prefreeze_readiness_report.md
        6. validation_report.json
        7. raw_test_log.txt
        8. manifest.json
    - review_decisions.csv has 25 probes, exactly partitioned (16 primary, 6 aux, 3 def),
      and 100% PENDING_REVIEW status.
    - source_review_findings.jsonl has 25 entries with valid audit verdicts.
    - manifest.json covers all other 7 files with verified sha256 and byte sizes.
    """
    issues: List[str] = []
    required_files = [
        "review_packet_vi.md",
        "review_decisions.csv",
        "source_review_findings.jsonl",
        "multi_gold_feasibility.md",
        "prefreeze_readiness_report.md",
        "validation_report.json",
        "raw_test_log.txt",
        "manifest.json",
    ]
    for rf in required_files:
        fp = gate_dir / rf
        if not fp.exists():
            issues.append(f"Missing required review gate deliverable: {rf}")

    if issues:
        return {"pass": False, "issues": issues, "metrics": {}}

    # 1. Validate review_decisions.csv
    csv_probes = {}
    csv_path = gate_dir / "review_decisions.csv"
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get("probe_id")
            if not pid:
                issues.append("Empty probe_id in review_decisions.csv")
                continue
            if pid in csv_probes:
                issues.append(f"Duplicate probe_id in review_decisions.csv: {pid}")
            csv_probes[pid] = row
            status = row.get("decision_status")
            if status != "PENDING_REVIEW":
                issues.append(f"Probe {pid} in review_decisions.csv has status={status!r}, expected PENDING_REVIEW")

    if len(csv_probes) != expected_total_probes:
        issues.append(f"review_decisions.csv has {len(csv_probes)} probes, expected {expected_total_probes}")

    p_count = sum(1 for r in csv_probes.values() if r.get("partition") == "primary")
    a_count = sum(1 for r in csv_probes.values() if r.get("partition") == "auxiliary")
    d_count = sum(1 for r in csv_probes.values() if r.get("partition") == "deferred")

    if p_count != 16:
        issues.append(f"Primary probe count in review_decisions.csv is {p_count}, expected 16")
    if a_count != 6:
        issues.append(f"Auxiliary probe count in review_decisions.csv is {a_count}, expected 6")
    if d_count != 3:
        issues.append(f"Deferred probe count in review_decisions.csv is {d_count}, expected 3")

    # 2. Validate source_review_findings.jsonl
    jsonl_probes = {}
    jsonl_path = gate_dir / "source_review_findings.jsonl"
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            if line.strip():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as e:
                    issues.append(f"Line {line_num} in source_review_findings.jsonl has invalid JSON: {e}")
                    continue
                pid = item.get("probe_id")
                if not pid:
                    issues.append(f"Line {line_num} in source_review_findings.jsonl has no probe_id")
                    continue
                if pid in jsonl_probes:
                    issues.append(f"Duplicate probe_id in source_review_findings.jsonl: {pid}")
                jsonl_probes[pid] = item
                if item.get("status") != "PENDING_REVIEW":
                    issues.append(f"Probe {pid} in findings has status={item.get('status')!r}, expected PENDING_REVIEW")

    if set(jsonl_probes.keys()) != set(csv_probes.keys()):
        issues.append("Mismatch between probe IDs in CSV and JSONL findings")

    # Check flagged auxiliary probes
    for flag_pid in ("V_TEMP_01", "V_SPOIL_03", "V_SPOIL_05"):
        if flag_pid in jsonl_probes:
            verdict = jsonl_probes[flag_pid].get("agent_audit_verdict")
            if verdict != "SOURCE_HALLUCINATION_DETECTED":
                issues.append(f"Expected SOURCE_HALLUCINATION_DETECTED for {flag_pid}, got {verdict}")

    # 3. Validate review_packet_vi.md content
    packet_path = gate_dir / "review_packet_vi.md"
    try:
        packet_content = packet_path.read_text(encoding="utf-8")
        for pid in csv_probes:
            if pid not in packet_content:
                issues.append(f"review_packet_vi.md does not contain reference to {pid}")
    except Exception as e:
        issues.append(f"Could not read review_packet_vi.md: {e}")

    # 4. Validate manifest.json
    manifest_path = gate_dir / "manifest.json"
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        issues.append(f"Could not parse manifest.json: {e}")
        manifest = {}

    if "manifest.json" in manifest.get("files", {}):
        issues.append("Manifest must not contain a hash of itself")

    expected_files = set(required_files) - {"manifest.json"}
    manifest_files = set(manifest.get("files", {}).keys())
    if manifest_files != expected_files:
        issues.append(f"Manifest file set mismatch: {manifest_files} != {expected_files}")

    for fname, meta in manifest.get("files", {}).items():
        fp = gate_dir / fname
        if not fp.exists():
            issues.append(f"File listed in manifest does not exist: {fname}")
            continue
        actual_hash = sha256_file(fp)
        if meta.get("sha256") != actual_hash:
            issues.append(f"Manifest SHA-256 mismatch for {fname}")
        if meta.get("bytes") != fp.stat().st_size:
            issues.append(f"Manifest byte-size mismatch for {fname}")

    metrics = {
        "total_probes": len(csv_probes),
        "primary_probes": p_count,
        "auxiliary_probes": a_count,
        "deferred_probes": d_count,
        "all_pending_review": len(issues) == 0,
        "manifest_files_verified": len(manifest_files),
    }

    return {
        "pass": len(issues) == 0,
        "issues": issues,
        "metrics": metrics,
    }


def validate_prefreeze_correction_deliverables(
    correction_dir: Path,
    chunks_path: Optional[Path] = None,
    expected_total_probes: int = 25,
) -> Dict[str, Any]:
    """
    Validates deliverables under M1_30CH_P_PREFREEZE_CORRECTION.
    Checks:
    - All 9 deliverables exist:
        1. canonical_probe_inventory.csv
        2. primary_gold_audit.jsonl
        3. corrected_human_review_packet_vi.md
        4. auxiliary_deferred_disposition.md
        5. evaluation_readiness.md
        6. correction_log.md
        7. validation_report.json
        8. raw_test_log.txt
        9. manifest.json
    - canonical_probe_inventory.csv has exactly 25 probes partitioned into:
        16 primary, 6 auxiliary, 3 deferred, with 100% PENDING_REVIEW human_decision.
      All chronology probes use canonical V_CHRONO_XX (no V_CHRO_ typos).
      Flagged auxiliary probes have audit_status REJECT_AS_CURRENTLY_WRITTEN.
    - primary_gold_audit.jsonl has 16 primary probes with:
        - 100% EXPLICITLY_STATED propositions
        - 100% exact character offset slice match into chunks.jsonl
        - Zero cutoff violations
        - Counterfactual minimality on all required chunks
        - human_review_status PENDING_REVIEW
    - corrected_human_review_packet_vi.md covers all 16 primary probes with empty sign-off fields.
    - auxiliary_deferred_disposition.md accounts for all 9 non-primary probes, confirms V_CALL_03 identity.
    - evaluation_readiness.md strictly distinguishes readiness states with EVALUATION_ALLOWED = NO.
    - correction_log.md documents REPORT_ONLY_TYPO resolution.
    - validation_report.json has valid schema, EVALUATION_ALLOWED = false, and 25 PENDING_REVIEW.
    - manifest.json verifies all 8 other files with matching SHA-256 and byte size.
    """
    issues: List[str] = []
    required_files = [
        "canonical_probe_inventory.csv",
        "primary_gold_audit.jsonl",
        "corrected_human_review_packet_vi.md",
        "auxiliary_deferred_disposition.md",
        "evaluation_readiness.md",
        "correction_log.md",
        "validation_report.json",
        "raw_test_log.txt",
        "manifest.json",
    ]
    for rf in required_files:
        fp = correction_dir / rf
        if not fp.exists():
            issues.append(f"Missing required prefreeze correction deliverable: {rf}")

    if issues:
        return {"pass": False, "issues": issues, "metrics": {}}

    # 1. Validate canonical_probe_inventory.csv
    csv_probes = {}
    csv_path = correction_dir / "canonical_probe_inventory.csv"
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get("probe_id")
            if not pid:
                issues.append("Empty probe_id in canonical_probe_inventory.csv")
                continue
            if pid in csv_probes:
                issues.append(f"Duplicate probe_id in canonical_probe_inventory.csv: {pid}")
            csv_probes[pid] = row

            if "V_CHRO_" in pid:
                issues.append(f"Found report-only typo probe_id {pid} in canonical_probe_inventory.csv")

            h_dec = row.get("human_decision")
            if h_dec != "PENDING_REVIEW":
                issues.append(f"Probe {pid} in inventory has human_decision={h_dec!r}, expected PENDING_REVIEW")

    if len(csv_probes) != expected_total_probes:
        issues.append(f"canonical_probe_inventory.csv has {len(csv_probes)} probes, expected {expected_total_probes}")

    p_count = sum(1 for r in csv_probes.values() if r.get("partition") == "primary")
    a_count = sum(1 for r in csv_probes.values() if r.get("partition") == "auxiliary")
    d_count = sum(1 for r in csv_probes.values() if r.get("partition") == "deferred")

    if p_count != 16:
        issues.append(f"Primary probe count in canonical_probe_inventory.csv is {p_count}, expected 16")
    if a_count != 6:
        issues.append(f"Auxiliary probe count in canonical_probe_inventory.csv is {a_count}, expected 6")
    if d_count != 3:
        issues.append(f"Deferred probe count in canonical_probe_inventory.csv is {d_count}, expected 3")

    for flag_pid in ("V_TEMP_01", "V_SPOIL_03", "V_SPOIL_05"):
        if flag_pid in csv_probes:
            ast = csv_probes[flag_pid].get("audit_status")
            if ast != "REJECT_AS_CURRENTLY_WRITTEN":
                issues.append(f"Expected REJECT_AS_CURRENTLY_WRITTEN for {flag_pid}, got {ast}")

    # 2. Validate primary_gold_audit.jsonl
    chunks_data = {}
    if chunks_path and chunks_path.exists():
        with open(chunks_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    c = json.loads(line)
                    chunks_data[c["chunk_id"]] = c

    audit_probes = {}
    audit_path = correction_dir / "primary_gold_audit.jsonl"
    with open(audit_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            if line.strip():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as e:
                    issues.append(f"Line {line_num} in primary_gold_audit.jsonl has invalid JSON: {e}")
                    continue
                pid = item.get("probe_id")
                if not pid:
                    issues.append(f"Line {line_num} in primary_gold_audit.jsonl has no probe_id")
                    continue
                if pid in audit_probes:
                    issues.append(f"Duplicate probe_id in primary_gold_audit.jsonl: {pid}")
                audit_probes[pid] = item

                if item.get("human_review_status") != "PENDING_REVIEW":
                    issues.append(f"Probe {pid} in audit has human_review_status={item.get('human_review_status')!r}, expected PENDING_REVIEW")

                cutoff = item.get("cutoff_chapter", 30)
                props = item.get("expected_propositions", [])
                if not props:
                    issues.append(f"Probe {pid} in primary_gold_audit.jsonl has no expected_propositions")

                for prop in props:
                    pr_id = prop.get("proposition_id")
                    cid = prop.get("supporting_chunk_id")
                    s = prop.get("char_offset_start")
                    e = prop.get("char_offset_end")
                    excerpt = prop.get("exact_excerpt")
                    supp = prop.get("support_level")
                    if supp != "EXPLICITLY_STATED":
                        issues.append(f"Proposition {pr_id} in {pid} has support_level={supp!r}, expected EXPLICITLY_STATED")

                    if chunks_data and cid in chunks_data:
                        actual_ch = chunks_data[cid].get("chapter_number", 0)
                        if actual_ch > cutoff:
                            issues.append(f"Proposition {pr_id} in {pid} violates cutoff: Ch {actual_ch} > cutoff {cutoff}")
                        actual_text = chunks_data[cid]["text"][s:e]
                        if actual_text != excerpt:
                            issues.append(f"Slice mismatch in {pid} {cid} [{s}:{e}] for prop {pr_id}")

    primary_csv_ids = {pid for pid, r in csv_probes.items() if r.get("partition") == "primary"}
    if set(audit_probes.keys()) != primary_csv_ids:
        issues.append(f"Audit probe IDs mismatch primary CSV IDs: {set(audit_probes.keys())} != {primary_csv_ids}")

    # 3. Validate corrected_human_review_packet_vi.md
    packet_content = (correction_dir / "corrected_human_review_packet_vi.md").read_text(encoding="utf-8")
    for pid in primary_csv_ids:
        if pid not in packet_content:
            issues.append(f"corrected_human_review_packet_vi.md does not contain {pid}")
    if "[X] PENDING_REVIEW" not in packet_content:
        issues.append("corrected_human_review_packet_vi.md missing default [X] PENDING_REVIEW")

    # 4. Validate auxiliary_deferred_disposition.md
    disp_content = (correction_dir / "auxiliary_deferred_disposition.md").read_text(encoding="utf-8")
    for pid in [p for p, r in csv_probes.items() if r.get("partition") in ("auxiliary", "deferred")]:
        if pid not in disp_content:
            issues.append(f"auxiliary_deferred_disposition.md missing reference to {pid}")
    if "REJECT_AS_CURRENTLY_WRITTEN" not in disp_content:
        issues.append("auxiliary_deferred_disposition.md missing REJECT_AS_CURRENTLY_WRITTEN recommendation")
    if "V_CALL_03" in disp_content:
        if "Chitose" not in disp_content or "crepe" not in disp_content:
            issues.append("V_CALL_03 missing Chitose/crepe identity description in disposition document")

    # 5. Validate evaluation_readiness.md
    readiness_content = (correction_dir / "evaluation_readiness.md").read_text(encoding="utf-8")
    for term in ["DATA_PREPARED", "TECHNICAL_VALIDATION_PASSED", "HUMAN_REVIEW_PENDING", "FROZEN", "EVALUATION_ALLOWED"]:
        if term not in readiness_content:
            issues.append(f"evaluation_readiness.md missing required status distinction: {term}")

    # 6. Validate correction_log.md
    log_content = (correction_dir / "correction_log.md").read_text(encoding="utf-8")
    if "REPORT_ONLY_TYPO" not in log_content:
        issues.append("correction_log.md missing REPORT_ONLY_TYPO classification")

    # 7. Validate validation_report.json
    try:
        val_rep = json.loads((correction_dir / "validation_report.json").read_text(encoding="utf-8"))
        if val_rep.get("evaluation_readiness_matrix", {}).get("EVALUATION_ALLOWED") is not False:
            issues.append("validation_report.json has EVALUATION_ALLOWED != false")
        if val_rep.get("human_decision_register", {}).get("PENDING_REVIEW") != expected_total_probes:
            issues.append("validation_report.json does not show all probes PENDING_REVIEW")
        if val_rep.get("human_decision_register", {}).get("APPROVED") != 0:
            issues.append("validation_report.json has APPROVED != 0")
    except Exception as e:
        issues.append(f"Could not parse or validate validation_report.json: {e}")

    # 8. Validate manifest.json
    try:
        manifest = json.loads((correction_dir / "manifest.json").read_text(encoding="utf-8"))
    except Exception as e:
        issues.append(f"Could not parse manifest.json: {e}")
        manifest = {}

    if "manifest.json" in manifest.get("files", {}):
        issues.append("Manifest must not contain a hash of itself")

    expected_manifest_files = set(required_files) - {"manifest.json"}
    manifest_files = set(manifest.get("files", {}).keys())
    if manifest_files != expected_manifest_files:
        issues.append(f"Manifest files mismatch: {manifest_files} != {expected_manifest_files}")

    for fname, meta in manifest.get("files", {}).items():
        fp = correction_dir / fname
        if not fp.exists():
            issues.append(f"File listed in manifest does not exist: {fname}")
            continue
        actual_hash = sha256_file(fp)
        if meta.get("sha256") != actual_hash:
            issues.append(f"Manifest SHA-256 mismatch for {fname}")
        if meta.get("bytes") != fp.stat().st_size:
            issues.append(f"Manifest byte-size mismatch for {fname}")

    metrics = {
        "total_probes": len(csv_probes),
        "primary_probes": p_count,
        "auxiliary_probes": a_count,
        "deferred_probes": d_count,
        "all_pending_review": len(issues) == 0,
        "manifest_files_verified": len(manifest_files),
    }

    return {
        "pass": len(issues) == 0,
        "issues": issues,
        "metrics": metrics,
    }


def validate_human_review_handoff_deliverables(
    handoff_dir: Path,
    expected_total_probes: int = 25,
    require_all_pending: bool = True,
) -> Dict[str, Any]:
    """Validates deliverables under M1_30CH_P_HUMAN_REVIEW_HANDOFF.

    Checks:
    - All 7 deliverables exist:
        1. protocol_reconciliation.md
        2. v_chrono_01_alternative_audit.md
        3. semantic_verification_provenance.md
        4. human_review_guide_vi.md
        5. human_decision_template.csv
        6. readiness_and_blockers.md
        7. manifest.json
    - human_decision_template.csv:
        - exactly 25 probes partitioned into 16 primary, 6 auxiliary, 3 deferred.
        - valid human_decision in VALID_ANNOTATION_STATUSES.
        - if require_all_pending is True, all 25 must have human_decision == 'PENDING_REVIEW'.
        - canonical probe IDs (no V_CHRO_ typos).
        - auxiliary probes V_TEMP_01, V_SPOIL_03, V_SPOIL_05 have agent_recommendation containing REJECT_AS_CURRENTLY_WRITTEN.
        - V_CHRONO_01 has agent_recommendation == 'PRIMARY_FREEZE_BLOCKER'.
    - protocol_reconciliation.md:
        - documents multi-gold protocol reconciliation and identifies status as PROPOSED.
    - v_chrono_01_alternative_audit.md:
        - contains 4-criteria audit for ch013_c0003 and ch013_c0004.
        - classifies V_CHRONO_01 as PRIMARY_FREEZE_BLOCKER.
        - specifies Gold Set 1 and Gold Set 2.
    - semantic_verification_provenance.md:
        - documents epistemic bounds and character-offset slice match mechanism.
    - human_review_guide_vi.md:
        - references all 25 probes and includes Vietnamese sign-off instructions.
    - readiness_and_blockers.md:
        - documents READY_FOR_HUMAN_REVIEW and EVALUATION_ALLOWED = NO.
    - manifest.json:
        - validates sha256 and byte sizes of all other 6 deliverables.
        - does not contain itself.
        - records blocker findings (v_chrono_01_status: PRIMARY_FREEZE_BLOCKER, evaluation_allowed: false).
    """
    issues: List[str] = []
    required_files = [
        "protocol_reconciliation.md",
        "v_chrono_01_alternative_audit.md",
        "semantic_verification_provenance.md",
        "human_review_guide_vi.md",
        "human_decision_template.csv",
        "readiness_and_blockers.md",
        "manifest.json",
    ]
    for rf in required_files:
        fp = handoff_dir / rf
        if not fp.exists():
            issues.append(f"Missing required human review handoff deliverable: {rf}")

    if issues:
        return {"pass": False, "issues": issues, "metrics": {}}

    # 1. Validate human_decision_template.csv
    csv_probes = {}
    csv_path = handoff_dir / "human_decision_template.csv"
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get("probe_id")
            if not pid:
                issues.append("Empty probe_id in human_decision_template.csv")
                continue
            if pid in csv_probes:
                issues.append(f"Duplicate probe_id in human_decision_template.csv: {pid}")
            if "V_CHRO_" in pid:
                issues.append(f"Report-only typo found in human_decision_template.csv: {pid}")
            csv_probes[pid] = row

            status = row.get("human_decision")
            if status not in VALID_ANNOTATION_STATUSES:
                issues.append(
                    f"Probe {pid} in human_decision_template.csv has invalid human_decision={status!r}, "
                    f"must be in {sorted(VALID_ANNOTATION_STATUSES)}"
                )
            if require_all_pending and status != "PENDING_REVIEW":
                issues.append(
                    f"Probe {pid} in human_decision_template.csv has human_decision={status!r}, "
                    "expected PENDING_REVIEW in initial handoff"
                )

    if len(csv_probes) != expected_total_probes:
        issues.append(
            f"human_decision_template.csv has {len(csv_probes)} probes, expected {expected_total_probes}"
        )

    p_count = sum(1 for r in csv_probes.values() if r.get("partition") == "primary")
    a_count = sum(1 for r in csv_probes.values() if r.get("partition") == "auxiliary")
    d_count = sum(1 for r in csv_probes.values() if r.get("partition") == "deferred")

    if p_count != 16:
        issues.append(f"Primary probe count in human_decision_template.csv is {p_count}, expected 16")
    if a_count != 6:
        issues.append(f"Auxiliary probe count in human_decision_template.csv is {a_count}, expected 6")
    if d_count != 3:
        issues.append(f"Deferred probe count in human_decision_template.csv is {d_count}, expected 3")

    for rej_id in ("V_TEMP_01", "V_SPOIL_03", "V_SPOIL_05"):
        if rej_id in csv_probes:
            rec = csv_probes[rej_id].get("agent_recommendation", "")
            if "REJECT_AS_CURRENTLY_WRITTEN" not in rec:
                issues.append(f"Expected REJECT_AS_CURRENTLY_WRITTEN recommendation for {rej_id}, got {rec}")

    if "V_CHRONO_01" in csv_probes:
        rec = csv_probes["V_CHRONO_01"].get("agent_recommendation", "")
        if "PRIMARY_FREEZE_BLOCKER" not in rec:
            issues.append(f"Expected PRIMARY_FREEZE_BLOCKER recommendation for V_CHRONO_01, got {rec}")

    # 2. Validate protocol_reconciliation.md
    proto_text = (handoff_dir / "protocol_reconciliation.md").read_text(encoding="utf-8")
    for req_term in ["PROPOSED", "MULTI_GOLD_PROTOCOL", "V_CHRONO_01"]:
        if req_term not in proto_text:
            issues.append(f"protocol_reconciliation.md missing required term: {req_term}")

    # 3. Validate v_chrono_01_alternative_audit.md
    chrono_text = (handoff_dir / "v_chrono_01_alternative_audit.md").read_text(encoding="utf-8")
    for req_term in ["ch013_c0003", "ch013_c0004", "PRIMARY_FREEZE_BLOCKER", "Tập Gold 1", "Tập Gold 2"]:
        if req_term not in chrono_text:
            issues.append(f"v_chrono_01_alternative_audit.md missing required term: {req_term}")

    # 4. Validate semantic_verification_provenance.md
    sem_text = (handoff_dir / "semantic_verification_provenance.md").read_text(encoding="utf-8")
    for req_term in ["EXPLICITLY_STATED", "Unicode", "chunks.jsonl", "40"]:
        if req_term not in sem_text:
            issues.append(f"semantic_verification_provenance.md missing required term: {req_term}")

    # 5. Validate human_review_guide_vi.md
    guide_text = (handoff_dir / "human_review_guide_vi.md").read_text(encoding="utf-8")
    for pid in csv_probes:
        if pid not in guide_text:
            issues.append(f"human_review_guide_vi.md missing reference to {pid}")
    if "PENDING_REVIEW" not in guide_text or "APPROVED" not in guide_text:
        issues.append("human_review_guide_vi.md missing human decision instructions")

    # 6. Validate readiness_and_blockers.md
    readiness_text = (handoff_dir / "readiness_and_blockers.md").read_text(encoding="utf-8")
    for req_term in ["READY_FOR_HUMAN_REVIEW", "EVALUATION_ALLOWED = NO", "PRIMARY_FREEZE_BLOCKER"]:
        if req_term not in readiness_text:
            issues.append(f"readiness_and_blockers.md missing required status marker: {req_term}")

    # 7. Validate manifest.json
    try:
        manifest = json.loads((handoff_dir / "manifest.json").read_text(encoding="utf-8"))
    except Exception as e:
        issues.append(f"Could not parse manifest.json: {e}")
        manifest = {}

    if "manifest.json" in manifest.get("files", {}):
        issues.append("Manifest must not contain a hash of itself")

    expected_manifest_files = set(required_files) - {"manifest.json"}
    manifest_files = set(manifest.get("files", {}).keys())
    if manifest_files != expected_manifest_files:
        issues.append(f"Manifest files mismatch: {manifest_files} != {expected_manifest_files}")

    for fname, meta in manifest.get("files", {}).items():
        fp = handoff_dir / fname
        if not fp.exists():
            issues.append(f"File listed in manifest does not exist: {fname}")
            continue
        actual_hash = sha256_file(fp)
        if meta.get("sha256") != actual_hash:
            issues.append(f"Manifest SHA-256 mismatch for {fname}")
        if meta.get("bytes") != fp.stat().st_size:
            issues.append(f"Manifest byte-size mismatch for {fname}")

    blocker_findings = manifest.get("blocker_findings", {})
    if blocker_findings.get("v_chrono_01_status") != "PRIMARY_FREEZE_BLOCKER":
        issues.append("Manifest blocker_findings v_chrono_01_status != PRIMARY_FREEZE_BLOCKER")
    if blocker_findings.get("evaluation_allowed") is not False:
        issues.append("Manifest blocker_findings evaluation_allowed != false")

    metrics = {
        "total_probes": len(csv_probes),
        "primary_probes": p_count,
        "auxiliary_probes": a_count,
        "deferred_probes": d_count,
        "status_distribution": {
            s: sum(1 for r in csv_probes.values() if r.get("human_decision") == s)
            for s in sorted(VALID_ANNOTATION_STATUSES)
        },
        "v_chrono_01_blocker_flagged": "V_CHRONO_01" in csv_probes and "PRIMARY_FREEZE_BLOCKER" in csv_probes["V_CHRONO_01"].get("agent_recommendation", ""),
        "evaluation_allowed": False,
        "manifest_files_verified": len(manifest_files),
    }

    return {
        "pass": len(issues) == 0,
        "issues": issues,
        "metrics": metrics,
    }


def _read_csv_by_probe(path: Path, issues: List[str], label: str) -> Dict[str, Dict[str, str]]:
    rows: Dict[str, Dict[str, str]] = {}
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            for line_number, row in enumerate(csv.DictReader(f), 2):
                probe_id = (row.get("probe_id") or "").strip()
                if not probe_id or not PROBE_ID_RE.fullmatch(probe_id):
                    issues.append(f"Invalid probe_id {probe_id!r} in {label} line {line_number}")
                    continue
                if probe_id in rows:
                    issues.append(f"Duplicate probe_id in {label}: {probe_id}")
                    continue
                rows[probe_id] = row
    except Exception as exc:
        issues.append(f"Could not parse {label}: {exc}")
    return rows


def _read_jsonl_by_probe(path: Path, issues: List[str], label: str) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    issues.append(f"Invalid JSON in {label} line {line_number}: {exc}")
                    continue
                probe_id = row.get("probe_id")
                if not isinstance(probe_id, str) or not PROBE_ID_RE.fullmatch(probe_id):
                    issues.append(f"Invalid probe_id {probe_id!r} in {label} line {line_number}")
                    continue
                if probe_id in rows:
                    issues.append(f"Duplicate probe_id in {label}: {probe_id}")
                    continue
                rows[probe_id] = row
    except Exception as exc:
        issues.append(f"Could not parse {label}: {exc}")
    return rows


def validate_human_signoff_artifact(
    signoff_path: Path,
    inventory_path: Path,
    source_package_path: Path,
) -> Dict[str, Any]:
    """Validate a separately authored human sign-off against an immutable package.

    The signed CSV is intentionally outside the reviewed ZIP.  Every row must
    bind to the exact ZIP SHA-256; changing the package makes the sign-off stale.
    This function validates structure and binding only.  It never creates or
    infers a human decision.
    """
    issues: List[str] = []
    for path, label in (
        (signoff_path, "human sign-off"),
        (inventory_path, "probe inventory"),
        (source_package_path, "source review package"),
    ):
        if not path.exists():
            issues.append(f"Missing {label}: {path}")
    if issues:
        return {"pass": False, "issues": issues, "metrics": {}}

    inventory = _read_csv_by_probe(inventory_path, issues, "probe inventory")
    signoff = _read_csv_by_probe(signoff_path, issues, "human sign-off")
    if set(signoff) != set(inventory):
        issues.append(
            "Human sign-off probe IDs do not exactly match the reviewed inventory: "
            f"signoff={sorted(signoff)}, inventory={sorted(inventory)}"
        )

    package_sha256 = sha256_file(source_package_path)
    for probe_id, row in signoff.items():
        decision = (row.get("human_decision") or "").strip()
        if decision not in VALID_HUMAN_DECISIONS:
            issues.append(
                f"Missing or invalid human decision for {probe_id}: {decision!r}; "
                f"expected one of {sorted(VALID_HUMAN_DECISIONS)}"
            )
        if not (row.get("reviewed_at") or "").strip():
            issues.append(f"Missing reviewed_at for {probe_id}")
        if not (row.get("reviewer_role") or "").strip():
            issues.append(f"Missing reviewer_role for {probe_id}")
        bound_hash = (row.get("source_package_sha256") or "").strip().lower()
        if bound_hash != package_sha256:
            issues.append(
                f"Stale or incorrect source_package_sha256 for {probe_id}: "
                f"{bound_hash!r} != {package_sha256}"
            )
        inventory_row = inventory.get(probe_id, {})
        if row.get("partition") != inventory_row.get("partition"):
            issues.append(f"Partition mismatch for {probe_id} in human sign-off")
        if row.get("agent_recommendation") != inventory_row.get("agent_recommendation"):
            issues.append(f"Agent recommendation mismatch for {probe_id} in human sign-off")

    return {
        "pass": len(issues) == 0,
        "issues": issues,
        "metrics": {
            "probe_count": len(signoff),
            "source_package_sha256": package_sha256,
            "complete_human_decisions": sum(
                1
                for row in signoff.values()
                if (row.get("human_decision") or "").strip() in VALID_HUMAN_DECISIONS
            ),
        },
    }


def validate_final_freeze_candidate_bundle(
    artifact_dir: Path,
    expected_total_probes: int = 25,
    expected_primary_probes: int = 16,
) -> Dict[str, Any]:
    """Validate the final *unsigned* preparation package and freeze-candidate gate.

    A structurally valid package may truthfully have a failed scientific gate
    (for example, unsupported propositions or complete alternative gold paths).
    ``pass`` describes package integrity; ``freeze_candidate_gate_pass`` describes
    whether the included technical evidence supports READY_FOR_HUMAN_SIGNOFF.
    """
    issues: List[str] = []
    required_files = {
        "final_probe_inventory.csv",
        "primary_semantic_audit.jsonl",
        "alternative_evidence_audit.jsonl",
        "v_chrono_01_deep_audit.md",
        "protocol_reconciliation.md",
        "semantic_verification_provenance.md",
        "human_review_guide_vi.md",
        "human_signoff_template.csv",
        "freeze_candidate_readiness.md",
        "validation_report.json",
        "raw_test_log.txt",
        "manifest.json",
    }
    for name in sorted(required_files):
        if not (artifact_dir / name).is_file():
            issues.append(f"Missing required final freeze-candidate deliverable: {name}")
    if issues:
        return {"pass": False, "issues": issues, "metrics": {}}

    inventory = _read_csv_by_probe(
        artifact_dir / "final_probe_inventory.csv", issues, "final_probe_inventory.csv"
    )
    if len(inventory) != expected_total_probes:
        issues.append(f"Inventory has {len(inventory)} probes, expected {expected_total_probes}")

    partition_ids: Dict[str, set] = {"primary": set(), "auxiliary": set(), "deferred": set()}
    for probe_id, row in inventory.items():
        partition = (row.get("partition") or "").strip()
        if partition not in partition_ids:
            issues.append(f"Invalid partition {partition!r} for {probe_id}")
            continue
        partition_ids[partition].add(probe_id)
        decision = (row.get("human_decision") or "").strip()
        if decision not in {"", "PENDING_REVIEW"}:
            issues.append(
                f"AI preparation package contains a non-pending human decision for {probe_id}: {decision}"
            )
        chunks = [c for c in (row.get("required_chunk_ids") or "").split(";") if c]
        if partition in {"primary", "auxiliary"} and not chunks:
            issues.append(f"Missing required chunks for included probe {probe_id}")
        if len(chunks) != len(set(chunks)):
            issues.append(f"Duplicate required chunk in inventory for {probe_id}")

    union_count = len(set().union(*partition_ids.values()))
    summed_count = sum(len(ids) for ids in partition_ids.values())
    if union_count != summed_count:
        issues.append("Partition overlap detected in final probe inventory")
    primary_ids = partition_ids["primary"]
    if len(primary_ids) != expected_primary_probes:
        issues.append(f"Primary partition has {len(primary_ids)} probes, expected {expected_primary_probes}")

    semantic = _read_jsonl_by_probe(
        artifact_dir / "primary_semantic_audit.jsonl", issues, "primary_semantic_audit.jsonl"
    )
    if set(semantic) != primary_ids:
        issues.append("Missing primary semantic audit or audit IDs do not match primary inventory")
    proposition_counts = {classification: 0 for classification in VALID_SEMANTIC_CLASSIFICATIONS}
    semantic_blockers = 0
    for probe_id, row in semantic.items():
        propositions = row.get("propositions")
        if not isinstance(propositions, list) or not propositions:
            issues.append(f"No proposition-level semantic audit for {probe_id}")
            continue
        for proposition in propositions:
            classification = proposition.get("classification")
            if classification not in VALID_SEMANTIC_CLASSIFICATIONS:
                issues.append(
                    f"Invalid semantic classification {classification!r} in {probe_id}"
                )
                continue
            proposition_counts[classification] += 1
            if classification in {"AMBIGUOUS", "UNSUPPORTED"}:
                semantic_blockers += 1

    alternatives = _read_jsonl_by_probe(
        artifact_dir / "alternative_evidence_audit.jsonl",
        issues,
        "alternative_evidence_audit.jsonl",
    )
    if set(alternatives) != primary_ids:
        issues.append("Alternative-evidence audit IDs do not match primary inventory")
    alternative_counts = {
        classification: 0 for classification in VALID_ALTERNATIVE_CLASSIFICATIONS
    }
    multi_gold_blockers = 0
    for probe_id, row in alternatives.items():
        classification = row.get("classification")
        if classification not in VALID_ALTERNATIVE_CLASSIFICATIONS:
            issues.append(f"Invalid alternative-evidence classification {classification!r} in {probe_id}")
            continue
        alternative_counts[classification] += 1
        if classification == "COMPLETE_ALTERNATIVE_FOUND":
            multi_gold_blockers += 1
            if not row.get("complete_alternative_gold_sets"):
                issues.append(f"Complete alternative gold path not recorded for {probe_id}")

    template = _read_csv_by_probe(
        artifact_dir / "human_signoff_template.csv", issues, "human_signoff_template.csv"
    )
    if set(template) != set(inventory):
        issues.append("Human sign-off template probe IDs do not match inventory")
    for probe_id, row in template.items():
        decision = (row.get("human_decision") or "").strip()
        if decision not in {"", "PENDING_REVIEW"}:
            issues.append(f"AI-created approval or decision in sign-off template for {probe_id}")
        if (row.get("source_package_sha256") or "").strip():
            issues.append(
                f"Unsigned in-package template must leave source_package_sha256 blank for {probe_id}"
            )

    try:
        report = json.loads((artifact_dir / "validation_report.json").read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append(f"Could not parse validation_report.json: {exc}")
        report = {}
    if report.get("task_q_executed") is not False:
        issues.append("validation_report.json must record task_q_executed=false")
    if report.get("evaluation_allowed") is not False:
        issues.append("validation_report.json must record evaluation_allowed=false")

    try:
        manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append(f"Could not parse manifest.json: {exc}")
        manifest = {}
    manifest_files = manifest.get("files", {})
    expected_manifest_files = required_files - {"manifest.json"}
    if set(manifest_files) != expected_manifest_files:
        issues.append(
            f"Manifest files mismatch: {sorted(manifest_files)} != {sorted(expected_manifest_files)}"
        )
    if "manifest.json" in manifest_files:
        issues.append("Manifest must not hash itself")
    for name, metadata in manifest_files.items():
        path = artifact_dir / name
        if not path.is_file():
            continue
        if metadata.get("sha256") != sha256_file(path):
            issues.append(f"Manifest SHA-256 mismatch for {name}")
        if metadata.get("bytes") != path.stat().st_size:
            issues.append(f"Manifest byte-size mismatch for {name}")

    freeze_candidate_gate_pass = semantic_blockers == 0 and multi_gold_blockers == 0
    if report.get("final_status") == "READY_FOR_HUMAN_SIGNOFF" and not freeze_candidate_gate_pass:
        issues.append("READY_FOR_HUMAN_SIGNOFF conflicts with recorded technical blockers")

    return {
        "pass": len(issues) == 0,
        "issues": issues,
        "metrics": {
            "total_probes": len(inventory),
            "primary_probes": len(primary_ids),
            "auxiliary_probes": len(partition_ids["auxiliary"]),
            "deferred_probes": len(partition_ids["deferred"]),
            "proposition_classification_counts": proposition_counts,
            "semantic_blockers": semantic_blockers,
            "alternative_classification_counts": alternative_counts,
            "multi_gold_blockers": multi_gold_blockers,
            "human_signoff_complete": False,
            "task_q_executed": False,
            "freeze_candidate_gate_pass": freeze_candidate_gate_pass,
        },
    }


def find_private_validation_content(public_paths: List[Path]) -> List[str]:
    """Return public files containing private fixture-level content markers."""
    findings: List[str] = []
    japanese_re = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
    private_key_re = re.compile(
        r"(?im)^\s*(question(?:_original)?|expected_answer(?:_original)?|exact_excerpt)\s*[:=]"
    )
    for path in public_paths:
        text = path.read_text(encoding="utf-8")
        markers = []
        if japanese_re.search(text):
            markers.append("Japanese prose")
        if CHUNK_ID_RE.search(text):
            markers.append("chunk ID")
        if PROBE_ID_RE.search(text):
            markers.append("private probe ID")
        if private_key_re.search(text):
            markers.append("private question/answer/excerpt field")
        if markers:
            findings.append(f"{path}: {', '.join(markers)}")
    return findings


if __name__ == "__main__":
    import sys
    base_dir = Path(__file__).resolve().parent.parent.parent
    probes_path = base_dir / ".local/story_integration/otonari_30ch/INDEPENDENT_VALIDATION_FIXTURE_V1/draft_probes.yaml"
    chunks_path = base_dir / ".local/story_integration/otonari_30ch/PARAGRAPH_PACK_V1/chunks.jsonl"
    orig_path = base_dir / ".local/story_integration/otonari_30ch/LONG_RANGE_PROBE_V1/probes.yaml"

    res = validate_validation_probes(probes_path, chunks_path, orig_path)
    if not res["pass"]:
        print("VALIDATION FAILED:")
        for issue in res["issues"]:
            print(f"  FAIL: {issue}")
        sys.exit(1)
    else:
        print("PASS: INDEPENDENT_VALIDATION_FIXTURE_V1 validation successful!")
        print(json.dumps(res["metrics"], indent=2))
        sys.exit(0)
