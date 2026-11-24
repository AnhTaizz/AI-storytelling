"""Read the synthetic DEV cases and verify their content-addressed manifest."""
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from tools.model_bench.scoring import METHODS

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "model_bench_dev" / "v1"
GROUPS = ("event_extraction", "disambiguation", "causal_relation", "event_ordering",
          "hallucination_detection", "spoiler_detection", "narrative_plan", "vietnamese_script",
          "script_correction", "structured_output")
DIFFICULTIES = ("easy", "medium", "hard")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_case(case, group):
    case_id = case["id"]
    method = case["scoring_method"]
    passage = case["input"]["passage"]
    if (case["group"] != group or case["difficulty"] not in DIFFICULTIES or method not in METHODS
            or case["gold_status"] != "draft_needs_owner_review" or case["source"] != "synthetic"
            or not case["input"]["instruction"] or not case["expected_behaviour"]):
        raise ValueError(f"{case_id}: invalid case metadata")
    spans = case["evidence_spans"]
    if not spans or any(not span["quote"] or not 0 <= span["start"] < span["end"] <= len(passage)
                        or passage[span["start"]:span["end"]] != span["quote"] for span in spans):
        raise ValueError(f"{case_id}: evidence must point into the case passage")
    gold = case["gold"]
    if (method == "rubric_human" and (gold is not None or not case["rubric"])
            or method != "rubric_human" and gold is None):
        raise ValueError(f"{case_id}: missing gold or rubric")
    if method in {"set_f1", "order_kendall"} and (
            not isinstance(gold, list) or len(set(map(canonical_json, gold))) != len(gold)):
        raise ValueError(f"{case_id}: gold must be a list of distinct values")
    if method == "json_schema":
        Draft202012Validator.check_schema(gold["schema"])
        Draft202012Validator(gold["schema"]).validate(gold["example"])


def load_dataset(directory=DATA):
    manifest = json.loads((directory / "MANIFEST.json").read_text(encoding="utf-8"))
    cases, hashes = [], {}
    names = {f"{group}.jsonl" for group in GROUPS}
    if (manifest["version"] != 1 or set(manifest["files"]) != names
            or {path.name for path in directory.glob("*.jsonl")} != names):
        raise ValueError("Unexpected DEV manifest version or file set")
    for group in GROUPS:
        name = f"{group}.jsonl"
        raw = (directory / name).read_bytes()
        hashes[name] = digest(raw)
        if hashes[name] != manifest["files"][name]:
            raise ValueError(f"DEV file hash mismatch: {name}")
        for line in raw.decode("utf-8").splitlines():
            case = json.loads(line)
            validate_case(case, group)
            cases.append(case)
    dataset_hash = digest(canonical_json(hashes).encode("utf-8"))
    if dataset_hash != manifest["dataset_sha256"] or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("DEV dataset hash mismatch or duplicate case IDs")
    return dataset_hash, cases
