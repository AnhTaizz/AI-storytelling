"""Write and machine-validate the private M4-04B2R continuation protocol."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.story_extraction.m4_04b2_dev_protocol_v1 import canonical_json_bytes
from tools.story_extraction.m4_04b2r_continuation_v2 import (
    PRIMARY_SHA256,
    REPAIR_SHA256,
    validate_protocol_file,
    write_protocol,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--validation", required=True, type=Path)
    parser.add_argument("--snapshot-v2", required=True, type=Path)
    parser.add_argument("--impact", required=True, type=Path)
    parser.add_argument("--guard", required=True, type=Path)
    parser.add_argument("--guard-tests", required=True, type=Path)
    parser.add_argument("--guarded-evaluator", required=True, type=Path)
    parser.add_argument("--resume-runner", required=True, type=Path)
    args = parser.parse_args()
    paths = {
        "snapshot_v2_path": args.snapshot_v2,
        "impact_path": args.impact,
        "guard_path": args.guard,
        "guard_test_path": args.guard_tests,
        "guarded_evaluator_path": args.guarded_evaluator,
        "resume_runner_path": args.resume_runner,
    }
    _, sha = write_protocol(args.protocol, **paths)
    validate_protocol_file(args.protocol, expected_sha256=sha, **paths)
    validation = {
        "artifact": "M4_04B2R_CONTINUATION_PROTOCOL_VALIDATION_V2",
        "protocol_sha256": sha,
        "parse": "PASS",
        "schema": "PASS",
        "snapshot_v1_identity": "PASS",
        "snapshot_v2_identity": "PASS",
        "impact_analysis": "PASS",
        "prompt_identity": "PASS",
        "generation_settings": "PASS",
        "historical_response_hashes": "PASS",
        "repair_consumed_state": "PASS",
        "dev_gold_barrier": "PASS",
        "holdout_barrier": "PASS",
        "primary_response_sha256": PRIMARY_SHA256,
        "repair_response_sha256": REPAIR_SHA256,
    }
    args.validation.parent.mkdir(parents=True, exist_ok=True)
    args.validation.write_bytes(canonical_json_bytes(validation))
    print(json.dumps({"protocol_sha256": sha, "status": "PASS"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
