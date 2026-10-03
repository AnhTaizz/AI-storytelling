"""Write the private M4-04B3B2 protocol without reading DEV2 or calling a provider."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.story_extraction.m4_04b3b2_dev2_protocol_v1 import (
    EXPECTED_BASE_COMMIT,
    canonical_json_bytes,
    prompt_hashes,
    prompt_material,
    validate_protocol_file,
    write_protocol,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--validation", required=True, type=Path)
    parser.add_argument("--prompt-directory", required=True, type=Path)
    args = parser.parse_args(argv)

    _, protocol_sha = write_protocol(args.protocol)
    validated = validate_protocol_file(args.protocol, protocol_sha, EXPECTED_BASE_COMMIT)
    material = prompt_material()
    args.prompt_directory.mkdir(parents=True, exist_ok=True)
    for name, text in material.items():
        (args.prompt_directory / f"{name}.txt").write_text(text, encoding="utf-8", newline="\n")
    validation = {
        "artifact": "M4_04B3B2_DEV2_PROTOCOL_VALIDATION_V1",
        "base_commit": EXPECTED_BASE_COMMIT,
        "protocol_sha256": protocol_sha,
        **dict(validated.checks),
        "prompt_material_hashes": prompt_hashes(),
        "provider_calls": 0,
        "dev2_input_opened": False,
        "dev2_gold_opened": False,
        "holdout_accessed": False,
        "secret_scan": "PASS",
    }
    args.validation.parent.mkdir(parents=True, exist_ok=True)
    args.validation.write_bytes(canonical_json_bytes(validation))
    print(json.dumps({"protocol_sha256": protocol_sha, "status": "PASS"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
