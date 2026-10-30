"""Regenerate the M4-04B4C adversarial and K4/K5 records from synthetic fixtures only.

Usage (repository root): python tests/story_extraction/generate_m4_04b4c_reports_v1.py
"""
from __future__ import annotations

from pathlib import Path
import sys

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import m4_v1_2_adversarial_harness as harness  # noqa: E402
import m4_v1_2_grounding_metrics as metrics  # noqa: E402

REPO = HERE.parents[1]
ADVERSARIAL = REPO / "benchmarks/m4_extraction/M4_04B4C_ADVERSARIAL_RESULTS.yaml"
METRICS = REPO / "benchmarks/m4_extraction/M4_04B4C_GROUNDING_METRICS.yaml"


def adversarial_record() -> dict:
    records = harness.run_all()
    return {"artifact": "M4_04B4C_ADVERSARIAL_RESULTS_V1", "source_text": "SYNTHETIC_ONLY",
            "summary": harness.summary(records), "cases": records}


def metrics_record() -> dict:
    return {"artifact": "M4_04B4C_GROUNDING_METRICS_V1", "source_text": "SYNTHETIC_ONLY",
            "k4": metrics.k4_resolution_rates(), "k5": metrics.k5_overhead()}


def render(value: dict) -> str:
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=100)


if __name__ == "__main__":
    ADVERSARIAL.write_text(render(adversarial_record()), encoding="utf-8")
    METRICS.write_text(render(metrics_record()), encoding="utf-8")
    print("written")
