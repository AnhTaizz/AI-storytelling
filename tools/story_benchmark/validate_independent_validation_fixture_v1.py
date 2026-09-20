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
