"""Freeze gate, frozen-package validation, and Task Q run-plan binding.

The frozen fixture is derived from the *reviewed ZIP bytes* (never from an
editable working directory) and from a separately authored human sign-off bound
to that ZIP's SHA-256.  A primary probe enters the frozen population only when
its human decision is APPROVED; any other primary decision blocks the freeze
(POST_REVIEW_FIX_REQUIRED) rather than silently shrinking the population.

This module contains no fixture content; tests use synthetic data only.
"""
import csv
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from tools.story_benchmark import probe_consistency
from tools.story_benchmark.multi_gold_metrics import (
    GoldEvidenceValidationError,
    normalize_gold_evidence_sets,
)
from tools.story_benchmark.validate_independent_validation_fixture_v1 import (
    validate_human_signoff_artifact,
)

FROZEN_REQUIRED_FILES = {
    "frozen_primary_fixture.yaml",
    "frozen_probe_inventory.csv",
    "human_signoff_v3.csv",
    "freeze_record.json",
    "manifest.json",
}
CANONICAL_NAME = "canonical_primary_fixture.yaml"
INVENTORY_NAME = "final_probe_inventory_v3.csv"
# Keys whose presence would mean evaluation output leaked into a frozen input.
RESULT_KEY_RE = re.compile(
    r"^(hit|recall|success|mrr|score|scores|metrics|results|ranked_results|ranking|task_q_results)(@\d+)?$",
    re.IGNORECASE,
)

# Pre-registered protocol (INDEPENDENT_VALIDATION_FIXTURE_V1_SPEC.md, section 6).
PREREGISTERED_PROTOCOL = {
    "methods": {
        "K": {
            "method_id": "DENSE_E5_LARGE_V1",
            "model": "intfloat/multilingual-e5-large",
            "revision": "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3",
            "notes": "CPU, fp32, parent chunks, 'query: ' / 'passage: ', normalized cosine ranking.",
        },
        "M": {
            "method_id": "BGE_RERANKER_V2_M3_TOP30_V1",
            "model": "BAAI/bge-reranker-v2-m3",
            "revision": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
            "candidate_pool": "Exactly K CUTOFF_FILTERED Top-30",
            "ordering": "raw classification logits DESC",
            "tie_break": ["k_rank ASC", "chunk_id ASC"],
        },
        "O": {
            "method_id": "KM_CONSENSUS_RANK_SUM_V1",
            "candidate_pool": "Exactly K/M Top-30",
            "ordering": "rank_sum = k_rank + m_rank ASC",
            "tie_break": ["max(k_rank, m_rank) ASC", "min(k_rank, m_rank) ASC", "chunk_id ASC"],
            "evaluated_ranking": "Consensus Top-30 followed by unchanged K tail (> 30)",
        },
    },
    "candidate_depth": 30,
    "top_k": 10,
    "primary_comparison": "O vs M on Top-10 metrics; K is a secondary historical baseline",
    "primary_endpoint": "Full Evidence Success@10",
    "metric_names": ["Full Evidence Success@10", "Required Evidence Recall@10", "Hit@10", "MRR"],
    "metric_definitions": "multi-gold: Hit/MRR over union; Recall best path; Success any complete path",
    "descriptive_classifications": [
        "DESCRIPTIVE_SUPPORT", "MIXED_TRADE_OFF", "NO_OBSERVED_GAIN", "NOT_EVALUABLE",
    ],
    "statistics": {
        "paired_bootstrap": {"B": 10000, "seed": 42, "ci": 0.95,
                             "note": "identical resample probe indices for M and O; macro from per-probe contributions"},
        "primary_binary_tests": ["exact McNemar", "paired permutation"],
        "secondary_metrics_status": "EXPLORATORY; non-significance is not equivalence",
    },
    "anti_tuning_contract": (
        "No tuning of candidate depth, consensus weights, rank tie-breakers, or post-hoc "
        "thresholds after observing validation results; any adjustment voids generalization "
        "claims and requires a new held-out set."
    ),
}


class FreezeNotEligible(RuntimeError):
    def __init__(self, status: str, reasons: List[str]):
        super().__init__(f"{status}: {reasons}")
        self.status = status
        self.reasons = reasons


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _zip_member(zf: zipfile.ZipFile, name: str) -> bytes:
    matches = [n for n in zf.namelist() if n.rsplit("/", 1)[-1] == name]
    if len(matches) != 1:
        raise FreezeNotEligible("BLOCKED", [f"source package must contain exactly one {name}"])
    return zf.read(matches[0])


def read_source_package(source_zip: Path) -> Dict[str, Any]:
    with zipfile.ZipFile(source_zip) as zf:
        fixture = yaml.safe_load(_zip_member(zf, CANONICAL_NAME).decode("utf-8"))
        inventory_text = _zip_member(zf, INVENTORY_NAME).decode("utf-8")
    inventory = list(csv.DictReader(io.StringIO(inventory_text)))
    return {"fixture": fixture, "inventory": inventory, "inventory_text": inventory_text}


def check_freeze_eligibility(
    source_zip: Path,
    signoff_path: Path,
    expected_package_sha256: str,
    technical_gate_pass: bool,
    privacy_pass: bool,
    task_q_executed: bool,
) -> Dict[str, Any]:
    """Return {status, eligible, reasons, signoff_rows, source}; never raises for gate failures."""
    reasons: List[str] = []
    if not Path(signoff_path).is_file():
        return {"status": "WAITING_FOR_PRODUCT_OWNER", "eligible": False,
                "reasons": ["human sign-off artifact not found"]}
    package_sha = sha256_path(source_zip)
    if package_sha != expected_package_sha256:
        return {"status": "BLOCKED", "eligible": False,
                "reasons": [f"source package hash {package_sha} != expected {expected_package_sha256}"]}
    source = read_source_package(source_zip)
    with Path(signoff_path).open(encoding="utf-8", newline="") as f:
        signoff_rows = list(csv.DictReader(f))

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        inventory_path = Path(tmp) / INVENTORY_NAME
        inventory_path.write_text(source["inventory_text"], encoding="utf-8")
        structural = validate_human_signoff_artifact(Path(signoff_path), inventory_path, Path(source_zip))
    if not structural["pass"]:
        return {"status": "INCOMPLETE_HUMAN_SIGNOFF", "eligible": False, "reasons": structural["issues"]}

    primary_ids = {p["probe_id"] for p in source["fixture"]["probes"]}
    decisions = {r["probe_id"]: r["human_decision"] for r in signoff_rows}
    non_approved = sorted(pid for pid in primary_ids if decisions.get(pid) != "APPROVED")
    if non_approved:
        return {"status": "POST_REVIEW_FIX_REQUIRED", "eligible": False,
                "reasons": [f"primary probes not APPROVED: {non_approved}"]}
    if not technical_gate_pass:
        reasons.append("technical gate did not pass")
    if not privacy_pass:
        reasons.append("privacy gate did not pass")
    if task_q_executed:
        reasons.append("Task Q already executed; holdout integrity lost")
    if reasons:
        return {"status": "BLOCKED", "eligible": False, "reasons": reasons}
    return {"status": "ELIGIBLE", "eligible": True, "reasons": [],
            "signoff_rows": signoff_rows, "source": source}


def _deterministic_zip(src_dir: Path, zip_path: Path, date_time=(2026, 1, 1, 0, 0, 0)) -> str:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(src_dir.iterdir(), key=lambda p: p.name):
            info = zipfile.ZipInfo(f"{src_dir.name}/{path.name}")
            info.date_time = date_time
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zf.writestr(info, path.read_bytes())
    return sha256_path(zip_path)


def build_frozen_package(
    out_dir: Path,
    source_zip: Path,
    signoff_path: Path,
    expected_package_sha256: str,
    technical_gate_pass: bool,
    privacy_pass: bool,
    task_q_executed: bool,
    fixture_id: str,
    fixture_version: str,
    frozen_at: str,
    frozen_from_git_sha: str,
    extra_record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create the immutable frozen directory and ZIP; raise FreezeNotEligible on any gate failure."""
    gate = check_freeze_eligibility(
        source_zip, signoff_path, expected_package_sha256,
        technical_gate_pass, privacy_pass, task_q_executed,
    )
    if not gate["eligible"]:
        raise FreezeNotEligible(gate["status"], gate["reasons"])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    source = gate["source"]
    canonical = source["fixture"]
    decisions = {r["probe_id"]: r["human_decision"] for r in gate["signoff_rows"]}
    signoff_bytes = Path(signoff_path).read_bytes()
    signoff_sha = sha256_bytes(signoff_bytes)
    probes = canonical["probes"]

    frozen = {k: v for k, v in canonical.items() if k != "probes"}
    frozen.update({
        "fixture_id": fixture_id,
        "fixture_version": fixture_version,
        "status": "FROZEN",
        "frozen": True,
        "evaluation_allowed": True,
        "task_q_executed": False,
        "source_package_sha256": expected_package_sha256,
        "human_signoff_sha256": signoff_sha,
        "probes": probes,
    })
    (out_dir / "frozen_primary_fixture.yaml").write_text(
        yaml.safe_dump(frozen, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8", newline="\n",
    )
    fields = list(source["inventory"][0].keys())
    with (out_dir / "frozen_probe_inventory.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in source["inventory"]:
            writer.writerow({**row, "human_decision": decisions[row["probe_id"]]})
    (out_dir / "human_signoff_v3.csv").write_bytes(signoff_bytes)

    gold_counts = [len(normalize_gold_evidence_sets(p)) for p in probes]
    record = {
        "fixture_id": fixture_id,
        "fixture_version": fixture_version,
        "source_package_sha256": expected_package_sha256,
        "human_signoff_sha256": signoff_sha,
        "corpus_fingerprint_sha256": canonical.get("corpus_fingerprint_sha256"),
        "chunks_jsonl_sha256": canonical.get("chunks_jsonl_sha256"),
        "primary_probe_count": len(probes),
        "single_gold_count": sum(c == 1 for c in gold_counts),
        "multi_gold_count": sum(c > 1 for c in gold_counts),
        "frozen_at": frozen_at,
        "frozen_from_git_sha": frozen_from_git_sha,
        "evaluation_allowed": True,
        "task_q_executed": False,
        "human_decision_counts": {
            d: sum(v == d for v in decisions.values())
            for d in ("APPROVED", "REJECTED", "DEFERRED", "NEEDS_REVISION")
        },
    }
    record.update(extra_record or {})
    (out_dir / "freeze_record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    files = {
        p.name: {"sha256": sha256_path(p), "bytes": p.stat().st_size}
        for p in sorted(out_dir.iterdir()) if p.name != "manifest.json"
    }
    (out_dir / "manifest.json").write_text(
        json.dumps({"fixture_id": fixture_id, "fixture_version": fixture_version, "files": files},
                   indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    if zip_path.exists():
        raise FreezeNotEligible("BLOCKED", [f"refusing to overwrite existing frozen ZIP {zip_path.name}"])
    zip_sha = _deterministic_zip(out_dir, zip_path)
    return {"zip_path": zip_path, "zip_sha256": zip_sha, "record": record}


def _result_keys(obj: Any, path: str = "") -> List[str]:
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str) and RESULT_KEY_RE.match(key):
                found.append(f"{path}/{key}")
            found += _result_keys(value, f"{path}/{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found += _result_keys(value, f"{path}[{index}]")
    return found


def validate_frozen_fixture(
    frozen_zip: Path,
    source_zip: Path,
    expected_source_sha256: str,
    expected_primary_count: int,
) -> Dict[str, Any]:
    """Validate a frozen package purely from the frozen ZIP and the reviewed source ZIP."""
    issues: List[str] = []
    if sha256_path(source_zip) != expected_source_sha256:
        issues.append("source package hash mismatch")
    with zipfile.ZipFile(frozen_zip) as zf:
        members = {n.rsplit("/", 1)[-1]: zf.read(n) for n in zf.namelist()}
    if set(members) != FROZEN_REQUIRED_FILES:
        issues.append(
            f"frozen file set mismatch: missing={sorted(FROZEN_REQUIRED_FILES - set(members))}, "
            f"unexpected={sorted(set(members) - FROZEN_REQUIRED_FILES)}"
        )
        return {"pass": False, "issues": issues}

    manifest = json.loads(members["manifest.json"])
    for name, meta in manifest.get("files", {}).items():
        if name not in members or sha256_bytes(members[name]) != meta.get("sha256"):
            issues.append(f"manifest hash mismatch for {name}")
    if set(manifest.get("files", {})) != FROZEN_REQUIRED_FILES - {"manifest.json"}:
        issues.append("manifest file set mismatch")

    record = json.loads(members["freeze_record.json"])
    frozen = yaml.safe_load(members["frozen_primary_fixture.yaml"].decode("utf-8"))
    if record.get("source_package_sha256") != expected_source_sha256:
        issues.append("freeze record source package hash mismatch")
    if record.get("human_signoff_sha256") != sha256_bytes(members["human_signoff_v3.csv"]):
        issues.append("human sign-off hash mismatch")
    if frozen.get("human_signoff_sha256") != record.get("human_signoff_sha256"):
        issues.append("fixture and record disagree on sign-off hash")
    for flag, expected in (("frozen", True), ("evaluation_allowed", True), ("task_q_executed", False)):
        if frozen.get(flag) is not expected:
            issues.append(f"frozen fixture {flag} must be {expected}")
    if record.get("task_q_executed") is not False or record.get("evaluation_allowed") is not True:
        issues.append("freeze record flags invalid")

    try:
        source = read_source_package(source_zip)
    except FreezeNotEligible as exc:
        return {"pass": False, "issues": issues + exc.reasons}
    if frozen.get("probes") != source["fixture"]["probes"]:
        issues.append("frozen probes differ from the approved canonical fixture")
    probes = frozen.get("probes") or []
    if len(probes) != expected_primary_count or record.get("primary_probe_count") != len(probes):
        issues.append(f"primary count {len(probes)} != expected {expected_primary_count}")
    for probe in probes:
        try:
            normalize_gold_evidence_sets(probe)
        except GoldEvidenceValidationError as exc:
            issues.append(f"{probe.get('probe_id')}: malformed gold schema: {exc}")
        issues += probe_consistency.check_proposition_gold_coverage(probe)

    signoff = list(csv.DictReader(io.StringIO(members["human_signoff_v3.csv"].decode("utf-8"))))
    decisions = {r["probe_id"]: r for r in signoff}
    for row in signoff:
        if row.get("human_decision") not in {"APPROVED", "REJECTED", "DEFERRED", "NEEDS_REVISION"}:
            issues.append(f"{row.get('probe_id')}: incomplete human decision")
        if not (row.get("reviewed_at") or "").strip() or not (row.get("reviewer_role") or "").strip():
            issues.append(f"{row.get('probe_id')}: missing reviewer metadata")
        if row.get("source_package_sha256") != expected_source_sha256:
            issues.append(f"{row.get('probe_id')}: sign-off bound to a different package")
    for probe in probes:
        if decisions.get(probe["probe_id"], {}).get("human_decision") != "APPROVED":
            issues.append(f"{probe['probe_id']}: frozen primary probe is not APPROVED")

    leaked = _result_keys(frozen) + _result_keys(record)
    if leaked:
        issues.append(f"evaluation results embedded in frozen input: {leaked[:5]}")
    return {"pass": not issues, "issues": issues}


def build_task_q_run_plan(
    frozen_zip_sha256: str, git_sha: str, corpus_fingerprint: str, chunks_sha256: str
) -> Dict[str, Any]:
    return {
        "task": "TASK_Q",
        "status": "PREPARED_NOT_EXECUTED",
        "frozen_fixture_sha256": frozen_zip_sha256,
        "git_sha": git_sha,
        "corpus_fingerprint_sha256": corpus_fingerprint,
        "chunks_jsonl_sha256": chunks_sha256,
        "method_K": PREREGISTERED_PROTOCOL["methods"]["K"],
        "method_M": PREREGISTERED_PROTOCOL["methods"]["M"],
        "method_O": PREREGISTERED_PROTOCOL["methods"]["O"],
        "candidate_depth": PREREGISTERED_PROTOCOL["candidate_depth"],
        "top_k": PREREGISTERED_PROTOCOL["top_k"],
        "bootstrap_B": PREREGISTERED_PROTOCOL["statistics"]["paired_bootstrap"]["B"],
        "bootstrap_seed": PREREGISTERED_PROTOCOL["statistics"]["paired_bootstrap"]["seed"],
        "protocol": {k: v for k, v in PREREGISTERED_PROTOCOL.items() if k != "methods"},
    }


def validate_task_q_run_plan(plan: Dict[str, Any], frozen_zip: Path) -> Dict[str, Any]:
    issues = []
    if plan.get("frozen_fixture_sha256") != sha256_path(frozen_zip):
        issues.append("run plan is bound to a different frozen fixture hash")
    expected = build_task_q_run_plan(
        plan.get("frozen_fixture_sha256"), plan.get("git_sha"),
        plan.get("corpus_fingerprint_sha256"), plan.get("chunks_jsonl_sha256"),
    )
    for key, value in expected.items():
        if plan.get(key) != value:
            issues.append(f"run plan field {key} deviates from the pre-registered protocol")
    if not re.fullmatch(r"[0-9a-f]{40}", str(plan.get("git_sha", ""))):
        issues.append("run plan git_sha must be a full commit SHA")
    leaked = _result_keys(plan)
    if leaked:
        issues.append(f"run plan contains observed results: {leaked[:5]}")
    if plan.get("status") != "PREPARED_NOT_EXECUTED":
        issues.append("run plan status must be PREPARED_NOT_EXECUTED")
    return {"pass": not issues, "issues": issues}
