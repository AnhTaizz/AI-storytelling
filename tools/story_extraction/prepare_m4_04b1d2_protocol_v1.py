"""Programmatically create and validate the private M4-04B1D2 protocol."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from tools.story_extraction.gemini_key_pool_v1 import load_runtime_config
from tools.story_extraction.m4_04b1d2_confirmation_protocol_v1 import (
    EXPECTED_BASE_COMMIT,
    write_canonical_confirmation_protocol,
    write_protocol_validation_result,
)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--validation-result", required=True, type=Path)
    parser.add_argument("--base-commit", default=EXPECTED_BASE_COMMIT)
    parser.add_argument("--dotenv", default=Path(".env"), type=Path)
    args = parser.parse_args(argv)

    validated = write_canonical_confirmation_protocol(
        args.protocol, base_commit=args.base_commit
    )
    config = load_runtime_config(args.dotenv)
    result = write_protocol_validation_result(
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
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
