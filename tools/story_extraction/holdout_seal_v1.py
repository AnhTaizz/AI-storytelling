"""Checks used to seal a fresh extraction holdout (M4_FRESH_HOLDOUT_V1).

Pure functions over plain data: package separation, the gold completeness gate, the blindness
manifest, the evaluation snapshot and the readiness gate. No source text, model, API or network.
"""
import hashlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SNAPSHOT_ID = "M4_EVALUATION_PROTOCOL_SNAPSHOT_V1"
PROFILE_ID = "STORY_UNDERSTANDING_CORE_V0"
GOLD_STATUS = ("AGENT_DRAFT_SEALED_GOLD", "NOT_HUMAN_CONFIRMED")
CATEGORIES = (
    "SIMPLE_EVENT", "ENTITY_RESOLUTION", "STATE_CHANGE", "RELATIONSHIP_STATE", "KNOWLEDGE_OR_BELIEF",
    "REPORTED_INFORMATION", "CONCEALMENT_OR_REVEAL", "CAUSALITY", "TEMPORAL_RELATION",
    "LONG_RANGE_OR_MULTI_EVIDENCE", "AMBIGUITY", "MIXED_PARATEXT_PROSE",
)

# Keys that may never appear anywhere inside the input package an extractor is allowed to read.
FORBIDDEN_INPUT_KEYS = frozenset({
    "candidate_records", "assertions", "propositions", "mentions", "entities", "events", "temporal_anchors",
    "evidence_refs", "extraction_provenance", "predicate", "role", "evidence_role", "epistemic_status",
    "required_assertions", "acceptable_assertions", "acceptable_assertion_ids", "out_of_scope_fact_classes",
    "gold_batch", "gold_completeness", "gold_status", "line_coverage", "literal_variants", "narrow_span_segments",
    "categories", "holdout_protocol_issues", "evaluation_case_spec", "adjudications", "expected_metrics", "notes",
})

SNAPSHOT_FILES = (
    "docs/research/m4/M4_EXTRACTION_EVALUATION_PROTOCOL_V0.md",
    "tools/story_extraction/evaluate_extraction_v0.py",
    "tools/story_extraction/extraction_contract_v0.py",
    "schemas/story_extraction/story_extraction_batch_v0.schema.json",
    "tests/story_extraction/test_extraction_evaluation_calibration_v0.py",
    "tests/story_extraction/test_story_extraction_contract_v0.py",
    "tests/story_extraction/fixture_builder.py",
)
PROFILE_SOURCE = "docs/research/m4/M4_EXTRACTION_EVALUATION_PROTOCOL_V0.md"
PROFILE_HEADING = "## 4. Development Extraction Profile"

READINESS_CONDITIONS = (
    "exact_semantic_exposure_registry_exists",
    "selection_locked_before_annotation",
    "selected_cases_remain_fixed",
    "all_gold_cases_complete_for_profile",
    "all_gold_batches_conform_to_frozen_m2",
    "input_and_gold_packages_separate",
    "gold_is_agent_draft_and_unreviewed",
    "scorer_snapshot_bound",
    "blindness_manifest_forbids_gold_before_prediction_lock",
    "no_model_prompt_or_extractor_selected_or_run",
)


def lf_sha256(data):
    """SHA-256 of the bytes with CRLF normalised to LF (the form stored in git)."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def file_sha256(relative_path, root=REPO_ROOT):
    return lf_sha256((Path(root) / relative_path).read_bytes())


def profile_definition(text, heading=PROFILE_HEADING):
    """The profile section of the evaluation protocol: from its heading up to the next same-level heading."""
    text = text.replace("\r\n", "\n")
    start = text.index(heading)
    following = re.search(r"^## ", text[start + len(heading):], re.M)
    end = start + len(heading) + following.start() if following else len(text)
    return text[start:end]


def profile_definition_sha256(root=REPO_ROOT):
    text = (Path(root) / PROFILE_SOURCE).read_text(encoding="utf-8")
    return hashlib.sha256(profile_definition(text).encode("utf-8")).hexdigest()


def compute_snapshot(root=REPO_ROOT):
    return {
        "snapshot_id": SNAPSHOT_ID,
        "files": {name: file_sha256(name, root) for name in SNAPSHOT_FILES},
        "profile": {"id": PROFILE_ID, "source": PROFILE_SOURCE, "heading": PROFILE_HEADING,
                    "definition_sha256": profile_definition_sha256(root)},
    }


def snapshot_mismatches(recorded, root=REPO_ROOT):
    """Names whose current hash differs from the recorded snapshot (empty list: the scorer is unchanged)."""
    current = compute_snapshot(root)
    changed = [name for name in SNAPSHOT_FILES if recorded.get("files", {}).get(name) != current["files"][name]]
    if set(recorded.get("files", {})) != set(SNAPSHOT_FILES):
        changed.append("<file list>")
    if recorded.get("profile", {}).get("definition_sha256") != current["profile"]["definition_sha256"]:
        changed.append("<profile definition>")
    return changed


def forbidden_keys(value, path="$"):
    """Paths of every forbidden key inside a JSON-like value."""
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_INPUT_KEYS:
                found.append(f"{path}.{key}")
            found.extend(forbidden_keys(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(forbidden_keys(child, f"{path}[{index}]"))
    return found


def check_input_package(entries):
    """`entries` maps archive member name -> parsed JSON. Returns a list of issues (empty: no gold leaked)."""
    issues = []
    for name, value in sorted(entries.items()):
        if "gold" in name.lower():
            issues.append(f"{name}: member name refers to gold")
        issues.extend(f"{name}: {where}" for where in forbidden_keys(value))
    return issues


def check_package_separation(input_names, gold_names, input_sha256, gold_sha256):
    issues = []
    if input_sha256 == gold_sha256:
        issues.append("input and gold package have the same hash")
    shared = set(input_names) & set(gold_names)
    if shared:
        issues.append(f"members present in both packages: {sorted(shared)}")
    return issues


def gold_completeness_gate(case_records, expected_cases):
    """Every case must be COMPLETE_FOR_PROFILE with a coverage note for every eligible segment."""
    issues = []
    if len(case_records) != expected_cases:
        issues.append(f"expected {expected_cases} cases, found {len(case_records)}")
    for record in case_records:
        case = record.get("case_id", "<unknown>")
        if record.get("gold_completeness") != "COMPLETE_FOR_PROFILE":
            issues.append(f"{case}: GOLD_COMPLETENESS_UNRESOLVED ({record.get('gold_completeness')})")
        if record.get("extraction_profile") != PROFILE_ID:
            issues.append(f"{case}: profile is not {PROFILE_ID}")
        covered = {note.get("segment") for note in record.get("line_coverage", [])}
        if covered != set(range(1, record.get("window_size", 0) + 1)):
            issues.append(f"{case}: coverage notes do not cover every eligible segment")
        if list(record.get("gold_status", [])) != list(GOLD_STATUS):
            issues.append(f"{case}: gold is not labelled as an unconfirmed agent draft")
        if set(record.get("categories", [])) - set(CATEGORIES) or not record.get("categories"):
            issues.append(f"{case}: category labels missing or unknown")
        if set(record.get("required_assertions", [])) & set(record.get("acceptable_assertions", [])):
            issues.append(f"{case}: an assertion is both required and optional")
    return issues


def gold_batch_labels(batch):
    """Issues with how a gold batch is labelled: it must be an unreviewed annotation, never a confirmed one."""
    issues = []
    if batch.get("process", {}).get("method") != "HUMAN_ANNOTATION":
        issues.append("process method is not HUMAN_ANNOTATION")
    for assertion in batch.get("candidate_records", {}).get("assertions", []):
        review = assertion.get("review", {})
        if review.get("state") != "UNREVIEWED" or "reviewer_kind" in review:
            issues.append(f"{assertion.get('id')}: review is not UNREVIEWED")
    return issues


def build_blindness_manifest(input_sha256, gold_sha256, selection_lock_sha256, snapshot_sha256):
    return {
        "manifest": "M4_03_HOLDOUT_BLINDNESS_MANIFEST", "holdout": "M4_FRESH_HOLDOUT_V1",
        "input_package_sha256": input_sha256, "gold_package_sha256": gold_sha256,
        "selection_lock_sha256": selection_lock_sha256, "evaluation_snapshot_sha256": snapshot_sha256,
        "extractor_access_allowed": {"input_package": True, "gold_package": False},
        "gold_may_be_opened_after": {"predictions_locked_and_hashed": True},
        "gold_status": list(GOLD_STATUS),
        "contamination_state": "CLEAN",
        "contamination_rule": "gold opened before the prediction package is locked and hashed => CONTAMINATED",
    }


def check_blindness_manifest(manifest):
    issues = []
    hashes = [manifest.get(key) for key in ("input_package_sha256", "gold_package_sha256", "selection_lock_sha256",
                                            "evaluation_snapshot_sha256")]
    if not all(isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes):
        issues.append("a package, lock or snapshot hash is missing or malformed")
    if manifest.get("input_package_sha256") == manifest.get("gold_package_sha256"):
        issues.append("input and gold package hashes are identical")
    if manifest.get("extractor_access_allowed") != {"input_package": True, "gold_package": False}:
        issues.append("extractor access must be: input allowed, gold forbidden")
    if manifest.get("gold_may_be_opened_after") != {"predictions_locked_and_hashed": True}:
        issues.append("gold may only be opened after predictions are locked and hashed")
    return issues


def holdout_state(gold_opened_before_prediction_lock):
    return "CONTAMINATED" if gold_opened_before_prediction_lock else "CLEAN"


def readiness(conditions):
    """`conditions` maps each readiness condition to a bool. Any missing or false condition blocks sealing."""
    unknown = set(conditions) - set(READINESS_CONDITIONS)
    if unknown:
        raise ValueError(f"unknown readiness conditions: {sorted(unknown)}")
    failed = [name for name in READINESS_CONDITIONS if conditions.get(name) is not True]
    return {"status": "M4_HOLDOUT_NOT_READY" if failed else "M4_FRESH_HOLDOUT_V1_SEALED", "failed": failed}
