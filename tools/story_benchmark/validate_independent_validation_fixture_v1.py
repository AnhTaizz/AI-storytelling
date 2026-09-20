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
