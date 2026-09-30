"""Regenerate Canonical Story v0 synthetic fixtures and the conformance report.

Usage (from the repository root):
    python -m tests.canonical_story.generate_fixtures

Deterministic: no timestamps, sorted keys. Tests assert that committed files
match this output, so fixtures cannot drift from the builder.
"""
import json
from pathlib import Path

from tests.canonical_story.fixture_builder import EXTRA_VALID_CASES, INVALID_CASES, VALID_CASES

ALL_VALID_CASES = {**VALID_CASES, **EXTRA_VALID_CASES}
from tools.canonical_story.conformance_v0 import REGISTRY_PATH, REPO_ROOT, SCHEMA_PATH, validate_document

HERE = Path(__file__).resolve().parent
VALID_DIR = HERE / "fixtures" / "valid"
INVALID_DIR = HERE / "fixtures" / "invalid"
REPORT_PATH = HERE / "conformance_report_v0.json"


def dump(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def expected_files() -> dict:
    files = {}
    for name, build in ALL_VALID_CASES.items():
        files[VALID_DIR / name] = dump(build())
    for name, (build, _, _) in INVALID_CASES.items():
        files[INVALID_DIR / name] = dump(build())
    return files


def build_report() -> dict:
    report = {
        "schema": SCHEMA_PATH.relative_to(REPO_ROOT).as_posix(),
        "registry": REGISTRY_PATH.relative_to(REPO_ROOT).as_posix(),
        "layers": {
            "structural": "JSON Schema Draft 2020-12 validation (shape, enums, required fields)",
            "semantic": "Conformance validator: reference, predicate, support-path, derivation, "
                        "evidence-set, temporal-bound and epistemic integrity",
        },
        "valid_fixtures": {},
        "invalid_fixtures": {},
    }
    for name, build in ALL_VALID_CASES.items():
        report["valid_fixtures"][name] = validate_document(build())
    for name, (build, layer, fragment) in INVALID_CASES.items():
        result = validate_document(build())
        report["invalid_fixtures"][name] = {
            "expected_layer": layer,
            "expected_fragment": fragment,
            "rejected": not result["pass"],
            "result": result,
        }
    return report


def main() -> None:
    for path, text in expected_files().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    REPORT_PATH.write_text(dump(build_report()), encoding="utf-8", newline="\n")
    print(f"wrote {len(ALL_VALID_CASES)} valid, {len(INVALID_CASES)} invalid fixtures and {REPORT_PATH.name}")


if __name__ == "__main__":
    main()
