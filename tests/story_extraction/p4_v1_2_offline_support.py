"""Offline support for M4-04B4C runner tests: V1.2 synthetic datasets and transports.

Every transport here subclasses ``OfflineTransport`` and returns scripted outcomes.
No provider is contacted and no DEV, validation or holdout material is read.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import zipfile

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture_builder as fx  # noqa: E402
from p3_v1_1_offline_support import FakeClock  # noqa: E402,F401

from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext  # noqa: E402
from tools.story_extraction.draft_compiler_v1_2 import (  # noqa: E402
    prepare_story_extraction_draft_v1_2,
)
from tools.story_extraction.draft_v1_2_oracle_projection_v1 import (  # noqa: E402
    project_gold_to_draft_v1_2,
)
from tools.story_extraction.durable_research_executor_v1 import (  # noqa: E402
    DurableTransportFailure,
)
from tools.story_extraction.m4_draft_v1_2_candidate_p4_v1 import (  # noqa: E402
    CANDIDATE_ID,
    candidate_definition,
    canonical_json_bytes,
)
from tools.story_extraction.run_m4_draft_v1_2_predictions_v1 import (  # noqa: E402
    OfflineTransport,
    process_version,
)
from tools.story_ingestion import light_novel_adapter_v0 as adapter  # noqa: E402


def oracle_v1_2(name: str, case_id: str) -> str:
    ingestion, base, gold = fx.build(name)
    scope = gold["scope"]
    context = DraftCompilerContext(base, scope["passage_inputs"], scope["as_of_position"],
                                   scope["profile_id"], CANDIDATE_ID, process_version(),
                                   f"P4V12_{case_id}", ingestion)
    draft, _, report = project_gold_to_draft_v1_2(gold, context)
    assert not report["unrepresentable"]
    return json.dumps(draft, ensure_ascii=False, sort_keys=True)


def write_dataset(root: Path, cases: list[tuple[str, str]], dataset_id: str = "SYNTHETIC_P4_SET_V1"
                  ) -> tuple[Path, Path, str]:
    members: dict[str, bytes] = {}
    rows = []
    for case_id, name in cases:
        data = fx.CASES[name][0].encode("utf-8")
        manifest = {"contract_version": "LIGHT_NOVEL_INGESTION/v0", "story_id": "story-syn-m4",
                    "stream_id": "stream-syn-m4", "source_language": "en",
                    "documents": [{"document_id": "srcdoc-syn-m4", "order": 1, "path": "unit.txt",
                                   "expected_sha256": hashlib.sha256(data).hexdigest()}]}
        source_dir = root / "_m3_build" / case_id
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "unit.txt").write_bytes(data)
        ingestion = adapter.ingest(manifest, source_dir)
        base = ingestion.canonical_skeleton()
        scope = fx.build(name)[2]["scope"]
        context = DraftCompilerContext(base, scope["passage_inputs"], scope["as_of_position"],
                                       scope["profile_id"], CANDIDATE_ID, process_version(),
                                       f"P4V12_{case_id}", ingestion)
        prefix = f"cases/{case_id}/"
        members[prefix + "source/unit.txt"] = data
        members[prefix + "source/m3_manifest.json"] = canonical_json_bytes(manifest)
        members[prefix + "base_document.json"] = canonical_json_bytes(base)
        members[prefix + "prepared_input.json"] = canonical_json_bytes(
            prepare_story_extraction_draft_v1_2(context))
        rows.append({"case_id": case_id, "base_document_member": prefix + "base_document.json",
                     "m3_manifest_member": prefix + "source/m3_manifest.json",
                     "prepared_input_member": prefix + "prepared_input.json",
                     "passage_inputs": scope["passage_inputs"],
                     "as_of_position": scope["as_of_position"], "profile_id": scope["profile_id"]})
    members["INPUT_MANIFEST.json"] = canonical_json_bytes({
        "artifact": dataset_id, "draft_interface": "STORY_EXTRACTION_DRAFT_V1_2",
        "case_count": len(rows), "cases": rows})
    archive = root / "input.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for name in sorted(members):
            bundle.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), members[name])
    input_root = root / "input"
    for name, data in members.items():
        target = input_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return archive, input_root, hashlib.sha256(archive.read_bytes()).hexdigest()


def write_candidate_lock(root: Path) -> tuple[Path, str]:
    payload = canonical_json_bytes(candidate_definition())
    path = root / "candidate_lock_v1_2.json"
    path.write_bytes(payload)
    return path, hashlib.sha256(payload).hexdigest()


class ScriptedOfflineTransport(OfflineTransport):
    """("ok", raw[, usage[, version]]), ("fail", category) or ("crash",) per job id."""

    def __init__(self, script: dict[str, list[tuple]]) -> None:
        self.script = {key: list(value) for key, value in script.items()}
        self.calls: list[str] = []
        self.specs: dict[str, object] = {}

    def __call__(self, spec, window, request_id):
        self.calls.append(spec.job_id)
        self.specs[spec.job_id] = spec
        queue = self.script.get(spec.job_id)
        if not queue:
            raise AssertionError(f"Unscripted call for {spec.job_id}")
        outcome = queue.pop(0)
        if outcome[0] == "fail":
            raise DurableTransportFailure(outcome[1], provider_attempts=1, attempts=[
                {"model": spec.model, "slot_id": spec.credential_slot}])
        if outcome[0] == "crash":
            raise RuntimeError("simulated crash")
        usage = outcome[2] if len(outcome) > 2 else {"prompt_token_count": 100,
                                                      "candidates_token_count": 50,
                                                      "total_token_count": 150}
        return {"raw_content": outcome[1], "model_requested": spec.model,
                "slot_id": spec.credential_slot,
                "model_reported_if_available": outcome[3] if len(outcome) > 3 else "scripted-v1",
                "usage_metadata": usage, "provider_response_metadata": {},
                "transport_attempts": [{"model": spec.model, "slot_id": spec.credential_slot}],
                "attempt_accounting": {"total_provider_attempts": 1}}
