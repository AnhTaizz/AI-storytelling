"""Create the canonical private M4-04B2 protocol and validation evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from tools.story_extraction.gemini_key_pool_v1 import load_runtime_config
from tools.story_extraction.m4_04b2_dev_protocol_v1 import (
    extract_input_members_only,
    write_protocol,
    write_validation_result,
)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--protocol", required=True, type=Path)
    prepare.add_argument("--validation-result", required=True, type=Path)
    prepare.add_argument("--dotenv", default=Path(".env"), type=Path)
    extract = subparsers.add_parser("extract-input")
    extract.add_argument("--package", required=True, type=Path)
    extract.add_argument("--destination", required=True, type=Path)
    extract.add_argument("--result", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.command == "prepare":
        validated = write_protocol(args.protocol)
        config = load_runtime_config(args.dotenv)
        result = write_validation_result(
            args.validation_result,
            validated,
            forbidden_secrets=tuple(item._api_key for item in config.credentials),
        )
        print(
            json.dumps(
                {
                    "credential_slot_count": len(config.credentials),
                    "protocol_sha256": result["protocol_sha256"],
                    "validation": "PASS",
                },
                sort_keys=True,
            )
        )
        return 0

    result = extract_input_members_only(args.package, args.destination)
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"input_members": len(result["extracted_members"]), "status": "PASS"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
