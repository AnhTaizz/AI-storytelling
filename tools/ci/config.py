"""Shared paths and policy configuration for tools/ci."""

from __future__ import annotations

import importlib.util
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

REPO = Path(__file__).resolve().parents[2]
TESTS = REPO / "tests"
TOOLS = REPO / "tools"
GATES_FILE = TESTS / "environment_gates.yaml"
POLICY_DIR = Path(__file__).resolve().parent / "policy"

# Heavy optional dependencies a gate may wait for. Anything else must be installable
# from the requirements files and therefore must not be gated.
OPTIONAL_HEAVY_MODULES = frozenset({"torch", "sentence_transformers", "transformers", "FlagEmbedding"})


def suites() -> List[str]:
    """Test suites are the directories under tests/ that contain test_*.py files."""
    return sorted(p.name for p in TESTS.iterdir()
                  if p.is_dir() and not p.name.startswith((".", "_")) and any(p.glob("test_*.py")))


@dataclass(frozen=True)
class Gate:
    tests: Tuple[str, ...]
    requires_modules: Tuple[str, ...]
    requires_paths: Tuple[str, ...]
    reason: str

    def unmet(self) -> List[str]:
        missing = [f"module {m}" for m in self.requires_modules if importlib.util.find_spec(m) is None]
        missing += [f"path {p}" for p in self.requires_paths if not (REPO / p).exists()]
        return missing


def load_gates(path: Path = GATES_FILE) -> List[Gate]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    gates = []
    for raw in data.get("gates", []):
        gates.append(Gate(tuple(raw["tests"]), tuple(raw.get("requires_modules", [])),
                          tuple(raw.get("requires_paths", [])), str(raw["reason"])))
    return gates


def gate_index(gates: List[Gate]) -> Dict[str, Gate]:
    index: Dict[str, Gate] = {}
    for gate in gates:
        for test_id in gate.tests:
            index[test_id] = gate
    return index


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def is_git_ignored(relative_path: str) -> bool:
    result = subprocess.run(["git", "check-ignore", "-q", "--no-index", relative_path], cwd=REPO)
    return result.returncode == 0
