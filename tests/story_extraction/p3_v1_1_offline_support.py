"""Offline support for M4-04B4B tests: synthetic datasets, scripted transports, clocks.

All text is invented here. No DEV, validation or holdout material is read, and no
provider is contacted: transports return scripted responses or scripted failures.
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

from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext  # noqa: E402
from tools.story_extraction.draft_compiler_v1_1 import (  # noqa: E402
    migrate_draft_v1_to_v1_1,
    prepare_story_extraction_draft_v1_1,
)
from tools.story_extraction.draft_coverage_v1 import canonical_gold_to_draft_v1  # noqa: E402
from tools.story_extraction.durable_research_executor_v1 import (  # noqa: E402
    DurableTransportFailure,
)
from tools.story_extraction.m4_draft_v1_1_candidate_p3_v1 import (  # noqa: E402
    CANDIDATE_ID,
    canonical_json_bytes,
    candidate_definition,
)
from tools.story_extraction.run_m4_draft_v1_1_predictions_v1 import (  # noqa: E402
    CaseInput,
    process_version,
)
from tools.story_ingestion import light_novel_adapter_v0 as adapter  # noqa: E402


JA_REPEATED_NAME_TEXT = "真白は笑った。真白は窓を開けた。"


def oracle_context(name: str, case_id: str = "SYN_01") -> tuple[DraftCompilerContext, dict]:
    """Synthetic fixture context plus its oracle V1.1 draft (not a model output)."""
    ingestion, base, gold = fx.build(name)
    scope = gold["scope"]
    context = DraftCompilerContext(
        base, scope["passage_inputs"], scope["as_of_position"], scope["profile_id"],
        CANDIDATE_ID, process_version(), f"P3V11_{case_id}", ingestion,
    )
    draft, _ = canonical_gold_to_draft_v1(gold, context)
    return context, migrate_draft_v1_to_v1_1(draft)


def oracle_case(name: str, case_id: str = "SYN_01") -> tuple[CaseInput, dict]:
    context, draft = oracle_context(name, case_id)
    return CaseInput(case_id, prepare_story_extraction_draft_v1_1(context), context), draft


def japanese_repeated_name_case(case_id: str = "SYN_01") -> tuple[CaseInput, dict]:
    """One segment in which the name 真白 occurs twice; the oracle resolves the first."""
    ingestion, base = fx.ingest_text(JA_REPEATED_NAME_TEXT)
    builder = fx.Builder(ingestion, base)
    builder.named(1, "真白")
    gold = builder.batch()
    scope = gold["scope"]
    context = DraftCompilerContext(
        base, scope["passage_inputs"], scope["as_of_position"], scope["profile_id"],
        CANDIDATE_ID, process_version(), f"P3V11_{case_id}", ingestion,
    )
    draft, _ = canonical_gold_to_draft_v1(gold, context)
    return CaseInput(case_id, prepare_story_extraction_draft_v1_1(context), context), \
        migrate_draft_v1_to_v1_1(draft)


def write_dataset(root: Path, cases: list[tuple[str, str]], dataset_id: str = "SYNTHETIC_P3_SET_V1",
                  extra_members: dict[str, bytes] | None = None) -> tuple[Path, Path, str]:
    """Write a synthetic input archive and its extracted tree.

    ``cases`` is a list of (case_id, fixture_builder case name). Returns
    (archive, input_root, archive_sha256).
    """
    members: dict[str, bytes] = {}
    rows = []
    for case_id, name in cases:
        text, _ = fx.CASES[name]
        data = text.encode("utf-8")
        manifest = {
            "contract_version": "LIGHT_NOVEL_INGESTION/v0", "story_id": "story-syn-m4",
            "stream_id": "stream-syn-m4", "source_language": "en",
            "documents": [{"document_id": "srcdoc-syn-m4", "order": 1, "path": "unit.txt",
                           "expected_sha256": hashlib.sha256(data).hexdigest()}],
        }
        prefix = f"cases/{case_id}/"
        members[prefix + "source/unit.txt"] = data
        members[prefix + "source/m3_manifest.json"] = canonical_json_bytes(manifest)
        ingestion = adapter.ingest(manifest, _materialize_source(root, case_id, data))
        base = ingestion.canonical_skeleton()
        _, _, gold = fx.build(name)
        scope = gold["scope"]
        context = DraftCompilerContext(
            base, scope["passage_inputs"], scope["as_of_position"], scope["profile_id"],
            CANDIDATE_ID, process_version(), f"P3V11_{case_id}", ingestion,
        )
        members[prefix + "base_document.json"] = canonical_json_bytes(base)
        members[prefix + "prepared_input.json"] = canonical_json_bytes(
            prepare_story_extraction_draft_v1_1(context))
        rows.append({
            "case_id": case_id,
            "base_document_member": prefix + "base_document.json",
            "m3_manifest_member": prefix + "source/m3_manifest.json",
            "prepared_input_member": prefix + "prepared_input.json",
            "passage_inputs": scope["passage_inputs"],
            "as_of_position": scope["as_of_position"],
            "profile_id": scope["profile_id"],
        })
    members["INPUT_MANIFEST.json"] = canonical_json_bytes({
        "artifact": dataset_id,
        "draft_interface": "STORY_EXTRACTION_DRAFT_V1_1",
        "case_count": len(rows),
        "cases": rows,
    })
    members.update(extra_members or {})
    archive = root / "input.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            bundle.writestr(info, members[name])
    input_root = root / "input"
    for name, data in members.items():
        target = input_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return archive, input_root, hashlib.sha256(archive.read_bytes()).hexdigest()


def _materialize_source(root: Path, case_id: str, data: bytes) -> Path:
    directory = root / "_m3_build" / case_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "unit.txt").write_bytes(data)
    return directory


def write_candidate_lock(root: Path) -> tuple[Path, str]:
    payload = canonical_json_bytes(candidate_definition())
    path = root / "candidate_lock.json"
    path.write_bytes(payload)
    return path, hashlib.sha256(payload).hexdigest()


class FakeClock:
    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class ScriptedTransport:
    """Returns scripted outcomes per job id, in order. Never contacts a provider.

    An outcome is ("ok", raw_text[, usage[, model_version]]), ("fail", category) or
    ("crash",) which raises an unexpected exception inside the transport.
    """

    def __init__(self, script: dict[str, list[tuple]]) -> None:
        self.script = {key: list(value) for key, value in script.items()}
        self.calls: list[str] = []
        self.specs: dict[str, object] = {}

    def __call__(self, spec, window, request_id):
        self.calls.append(spec.job_id)
        self.specs[spec.job_id] = spec
        queue = self.script.get(spec.job_id)
        if not queue:
            raise AssertionError(f"Unscripted provider call for {spec.job_id}")
        outcome = queue.pop(0)
        if outcome[0] == "fail":
            raise DurableTransportFailure(
                outcome[1], provider_attempts=1,
                attempts=[{"model": spec.model, "slot_id": spec.credential_slot,
                           "classified_result": outcome[1]}],
            )
        if outcome[0] == "crash":
            raise RuntimeError("simulated process crash inside transport")
        raw = outcome[1]
        usage = outcome[2] if len(outcome) > 2 else {
            "prompt_token_count": 100, "candidates_token_count": 50, "total_token_count": 150}
        version = outcome[3] if len(outcome) > 3 else "scripted-model-version-1"
        return {
            "raw_content": raw,
            "model_requested": spec.model,
            "slot_id": spec.credential_slot,
            "model_reported_if_available": version,
            "usage_metadata": usage,
            "provider_response_metadata": {"response_id": request_id},
            "transport_attempts": [{"model": spec.model, "slot_id": spec.credential_slot,
                                    "classified_result": "SUCCESS"}],
            "attempt_accounting": {"total_provider_attempts": 1},
        }


def draft_json(draft: dict) -> str:
    return json.dumps(draft, ensure_ascii=False, sort_keys=True)
