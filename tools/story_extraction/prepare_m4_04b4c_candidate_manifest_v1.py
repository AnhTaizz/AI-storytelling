"""Write or check the public M4-04B4C (P4 / Draft V1.2) candidate manifest. Offline only.

Usage: python -m tools.story_extraction.prepare_m4_04b4c_candidate_manifest_v1 [--check]
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Optional

import yaml

from tools.story_extraction.m4_draft_v1_1_candidate_p3_v1 import git_head
from tools.story_extraction.m4_draft_v1_2_candidate_p4_v1 import (
    CANDIDATE_MANIFEST_ID,
    REPO_ROOT,
    TASK_ID,
    candidate_definition,
    candidate_definition_sha256,
    environment_observed,
)

MANIFEST_PATH = REPO_ROOT / "benchmarks/m4_extraction/M4_04B4C_DRAFT_V1_2_CANDIDATE_MANIFEST.yaml"


def build_manifest(base_commit: Optional[str]) -> dict[str, Any]:
    return {
        "artifact": CANDIDATE_MANIFEST_ID,
        "task": TASK_ID,
        "status": "CANDIDATE_PREPARED_PENDING_ORCHESTRATOR_REVIEW",
        "base_commit": base_commit,
        "candidate_definition_sha256": candidate_definition_sha256(),
        "qualification": {"development_candidate_accepted": False,
                          "independent_validation_approved": False,
                          "production_qualified": False, "live_execution_enabled": False,
                          "provider_calls_made_in_this_task": 0},
        "definition": candidate_definition(),
        "environment_observed_at_lock": environment_observed(),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        committed = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
        ok = (committed["candidate_definition_sha256"] == candidate_definition_sha256()
              and committed["definition"] == candidate_definition())
        print("CANDIDATE_MANIFEST_MATCH" if ok else "CANDIDATE_MANIFEST_MISMATCH")
        return 0 if ok else 1
    MANIFEST_PATH.write_text(yaml.safe_dump(build_manifest(git_head()), sort_keys=False,
                                            allow_unicode=True, width=100), encoding="utf-8")
    print(MANIFEST_PATH.relative_to(REPO_ROOT).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
