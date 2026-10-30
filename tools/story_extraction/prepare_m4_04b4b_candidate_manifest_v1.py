"""Write the public M4-04B4B candidate manifest (offline, no provider, no dataset).

Usage: python -m tools.story_extraction.prepare_m4_04b4b_candidate_manifest_v1 [--check]
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any, Optional

import yaml

from tools.story_extraction.m4_draft_v1_1_candidate_p3_v1 import (
    CANDIDATE_ID,
    CANDIDATE_MANIFEST_ID,
    FORBIDDEN_ARCHIVE_SHA256,
    HASH_POLICY,
    REPO_ROOT,
    TASK_ID,
    bound_file_hashes,
    candidate_definition,
    candidate_definition_sha256,
    git_head,
    prompt_hashes,
    prompt_size,
)

MANIFEST_PATH = REPO_ROOT / "benchmarks/m4_extraction/M4_04B4B_DRAFT_V1_1_CANDIDATE_MANIFEST.yaml"


def build_manifest(base_commit: Optional[str]) -> dict[str, Any]:
    definition = candidate_definition()
    return {
        "artifact": CANDIDATE_MANIFEST_ID,
        "task": TASK_ID,
        "status": "CANDIDATE_PREPARED_PENDING_ORCHESTRATOR_REVIEW",
        "base_commit": base_commit,
        "candidate_id": CANDIDATE_ID,
        "candidate_definition_sha256": candidate_definition_sha256(),
        "hash_policy": {
            "identity": HASH_POLICY,
            "verification_hash": "content_sha256_lf",
            "content_sha256_lf": "SHA-256 of file bytes after CRLF to LF; lone CR is kept",
            "git_blob_sha1_lf": "git blob id of the LF content (equals the committed blob)",
            "raw_sha256_observed": "informational; raw bytes on the platform that wrote this file",
            "source_text_policy": "raw source text is never normalized; M3 hashes raw bytes",
        },
        "qualification": {
            "production_qualified": False,
            "approved_for_blind_validation": False,
            "extraction_quality_measured": False,
            "provider_calls_made_in_this_task": 0,
        },
        "generation": definition["generation"],
        "durable_execution": definition["durable_execution"],
        "compiler_binding": definition["compiler_binding"],
        "evaluation_snapshot": definition["evaluation_snapshot"],
        "repair_policy": definition["repair_policy"],
        "request_construction": definition["request_construction"],
        "prompt_hashes": prompt_hashes(),
        "prompt_size": prompt_size(),
        "forbidden_input_archives": dict(sorted(FORBIDDEN_ARCHIVE_SHA256.items())),
        "files": bound_file_hashes(),
    }


def render(manifest: dict[str, Any]) -> str:
    return yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=100)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="compare the committed manifest with the current candidate")
    args = parser.parse_args(argv)
    if args.check:
        committed = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
        current = build_manifest(committed.get("base_commit"))
        for record in (committed, current):
            for item in record["files"].values():
                item.pop("raw_sha256_observed", None)
                item.pop("observed_line_endings", None)
        if committed != current:
            print("CANDIDATE_MANIFEST_MISMATCH")
            return 1
        print("CANDIDATE_MANIFEST_MATCH")
        return 0
    MANIFEST_PATH.write_text(render(build_manifest(git_head())), encoding="utf-8")
    print(MANIFEST_PATH.relative_to(REPO_ROOT).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
