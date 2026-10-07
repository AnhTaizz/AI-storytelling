"""Live execution adapter V1.1 for the locked DEV3 P3 blind prediction run (M4-04B3H).

V1.1 is adapter V1 with one change: the sealed-input loader follows the DEV3 input layout
recorded, structure only, by M4-04B3H2. V1 assumed the DEV2 layout and failed closed on
the real package; it is preserved unchanged as historical evidence and is not eligible
for a live run. Nothing outside the input layout differs from V1.

Execution mechanics only. Extraction semantics stay in the accepted B3G runner core:
Draft V1.1 validation, compilation, repair eligibility, blocker sanitation and the
one-repair limit are imported, never re-implemented. This module composes that core
with the B3F request builder, the durable executor, the persistent global pacer and
the accepted Gemini transport. It accepts no gold path and imports no evaluator.
"""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
import zipfile

import yaml

from tools.story_extraction import m4_04b3h0_dev3_decision_lock_v1 as decision_lock
from tools.story_extraction.dev3_seal_v1 import INPUT_ARTIFACT, check_input_zero_gold
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext
from tools.story_extraction.draft_compiler_v1_1 import prepare_story_extraction_draft_v1_1
from tools.story_extraction.durable_research_executor_v1 import (
    DURABLE_EXECUTOR_VERSION,
    CheckpointIntegrityError,
    DurableJobSpec,
    DurableResearchExecutor,
    JobState,
    PersistentRollingOperationPacer,
)
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError, load_runtime_config
from tools.story_extraction.m4_04b3f_dev3_p3_protocol_v1 import (
    CASE_IDS,
    CONCURRENCY,
    CREDENTIAL_SLOT,
    DEV3_GOLD_SHA256,
    DEV3_INPUT_SHA256,
    DRAFT_VERSION,
    EXPECTED_BASE_COMMIT,
    EXTRACTOR_ID,
    GLOBAL_MAX_PROVIDER_OPERATIONS,
    GLOBAL_ROLLING_WINDOW_SECONDS,
    MAX_PROVIDER_ATTEMPTS_PER_JOB,
    MAX_STRUCTURAL_REPAIRS_PER_CASE,
    MODEL,
    PROTOCOL_ID,
    REPO_ROOT,
    RUNTIME_VERSION,
    TEMPERATURE,
    WINDOW_COOLDOWN_SECONDS,
    Dev3ProtocolError,
    canonical_json_bytes,
    normalized_file_sha256,
    sha256_bytes,
    validate_protocol_file,
)
from tools.story_extraction.run_m4_04b2_dev_predictions_v1 import (
    GeminiDevWindowTransport,
    _execute_to_terminal,
    _job_telemetry,
    _write_bytes_atomic,
)
from tools.story_extraction.run_m4_04b3g_dev3_p3_predictions_v1 import (
    LOCKED_PROTOCOL_SHA256,
    CaseInput,
    Dev3RunnerError,
    FirstSuccessLedger,
    ProviderFirstSuccess,
    _validate_member_name,
    compile_raw_response,
    execute_case,
    preflight as b3g_preflight,
)
from tools.story_ingestion.light_novel_adapter_v0 import ingest_manifest_file


RUNNER_ID = "M4_04B3H_DEV3_P3_LIVE_EXECUTION_ADAPTER_V1_1"
TASK_ID = "M4-04B3H"
LIVE_AUTHORIZATION_TOKEN = "M4-04B3H"
ADAPTER_PATH = "tools/story_extraction/run_m4_04b3h_dev3_p3_live_v1_1.py"
DECISION_RECORD_SHA256 = "5826854dfe6828ebea67e0d4c089fbda148fcc89da9efc80f1afb244aa329735"
EXECUTOR_PROTOCOL_ID = f"{PROTOCOL_ID}:{LOCKED_PROTOCOL_SHA256}:H0:{DECISION_RECORD_SHA256}"
PROCESS_ID = "M4_04B3H_P3"
PROCESS_VERSION = "v1.1"

PREDICTION_RESULT_ID = "M4_04B3H_DEV3_P3_PREDICTION_RESULT_V1"
PREDICTION_MANIFEST_ID = "M4_04B3H_DEV3_P3_PREDICTION_MANIFEST_V1"
PUBLIC_LOCK_STATUS = "M4_04B3H_DEV3_P3_PREDICTIONS_LOCKED"
PUBLIC_LOCK_PATH = REPO_ROOT / "benchmarks/m4_extraction/M4_04B3H_DEV3_P3_PREDICTION_LOCK.yaml"
DEFAULT_PRIVATE_ROOT = REPO_ROOT / ".local/m4_04b3h_dev3_predictions"
PRIVATE_DIRECTORIES = (
    "checkpoints", "input", "raw", "drafts", "compiled", "failures", "case_results", "telemetry",
)
TERMINAL_STATUSES = ("STRUCTURAL_VALID", "STRUCTURAL_FAILURE", "TRANSPORT_FAILURE")

# The sealed DEV3 input layout, as recorded by the M4-04B3H2 structure-only diagnostic:
# member names, JSON key names and counts. No narrative content informed it. Every file of
# a case sits at one fixed path; no other filename is ever derived or searched for. That
# source_manifest.json is the frozen M3 manifest is a hypothesis: it is tested only by
# loading that one path through the unchanged M3 adapter, with no fallback.
SEALED_INPUT_CONTRACT = {
    "provenance": "MECHANICAL_LAYOUT_RECORDED_BY_M4_04B3H2_STRUCTURE_ONLY_DIAGNOSTIC",
    "member_count": 51,
    "manifest_member": "input_manifest.json",
    "manifest_keys": (
        "artifact", "case_count", "case_order", "cases", "draft_interface",
        "extractor_surface", "files", "source_family",
    ),
    "artifact": INPUT_ARTIFACT,
    "draft_interface": DRAFT_VERSION,
    "case_fields": ("as_of_position", "case_id", "members", "passage_inputs", "profile_id"),
    "case_members": {
        "base_document": "cases/{case_id}/base_document.json",
        "ingestion_report": "cases/{case_id}/ingestion_report.json",
        "prepared_input": "cases/{case_id}/prepared_draft_input.json",
        "source_unit": "cases/{case_id}/source/unit.txt",
        "m3_manifest": "cases/{case_id}/source_manifest.json",
    },
}

# Execution checkout: every tracked file is byte-identical to its repository blob, except
# these two. The DEV2-era locks pin the SHA-256 of their CRLF working copies, so they are
# materialized with CRLF. Neither file belongs to the P3 extractor stack.
CRLF_BOUND_HISTORICAL_FILES = {
    "schemas/story_extraction/story_extraction_draft_v1.schema.json":
        "498edf8dba8d45b80380a180d1383787f5c0e4ecea5060254883cc27c7d83e80",
    "tools/story_extraction/draft_compiler_v1.py":
        "bcd15328cefafe86dd8e686fb35a155b2cb2c261b20017486ed106e85371d836",
}
ENVIRONMENT_METHOD = "ISOLATED_CLONE_AUTOCRLF_FALSE_WITH_TWO_FILE_CRLF_ATTRIBUTE_EXCEPTION"
REQUIRED_SUITES = ("canonical_story", "story_ingestion", "story_extraction", "script_quality", "story_benchmark")

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_PUBLIC_TOKEN = re.compile(r"^[A-Za-z0-9_.:/-]{1,200}$")


class LiveExecutionError(RuntimeError):
    """A fail-closed binding, input, environment or artifact error with no private text."""


class TransportTerminalFailure(RuntimeError):
    """The durable job ended without a first success. Carries a sanitized category only."""

    def __init__(self, job_id: str, category: str) -> None:
        self.job_id = job_id
        self.category = category
        super().__init__(f"Durable job reached a terminal transport failure: {category}")


# ---------------------------------------------------------------------------
# Execution environment
# ---------------------------------------------------------------------------

def _blob_oid(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def classify_tracked_files(entries: Iterable[tuple[str, str, bytes]]) -> dict[str, Any]:
    """Classify (path, index blob id, working bytes) triples against the locked rule."""
    total = identical = 0
    exceptions: dict[str, str] = {}
    violations: list[str] = []
    for path, blob_oid, data in entries:
        total += 1
        if path in CRLF_BOUND_HISTORICAL_FILES:
            lf = data.replace(b"\r\n", b"\n")
            pure_crlf = b"\r\n" in data and data.count(b"\n") == data.count(b"\r\n")
            if pure_crlf and _blob_oid(lf) == blob_oid and sha256_bytes(data) == CRLF_BOUND_HISTORICAL_FILES[path]:
                exceptions[path] = sha256_bytes(data)
            else:
                violations.append(path)
        elif _blob_oid(data) == blob_oid:
            identical += 1
        else:
            violations.append(path)
    missing = sorted(set(CRLF_BOUND_HISTORICAL_FILES) - set(exceptions))
    return {
        "tracked_files": total,
        "byte_identical_to_blob": identical,
        "crlf_exception_files": dict(sorted(exceptions.items())),
        "violations": sorted(set(violations) | set(missing)),
    }


def _git(repo_root: Path, *arguments: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *arguments], capture_output=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise LiveExecutionError("Execution checkout cannot be inspected") from error


def verify_execution_environment(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Fail closed unless this checkout is the locked byte-exact execution environment."""
    autocrlf = _git(repo_root, "config", "--get", "core.autocrlf").decode("utf-8").strip()
    if autocrlf != "false":
        raise LiveExecutionError("Execution checkout must use core.autocrlf=false")
    if _git(repo_root, "status", "--porcelain", "--untracked-files=no").strip():
        raise LiveExecutionError("Execution checkout has modified tracked files")
    listing = _git(repo_root, "ls-files", "-s", "-z").decode("utf-8")
    entries = []
    for entry in filter(None, listing.split("\0")):
        meta, path = entry.split("\t", 1)
        entries.append((path, meta.split()[1], (repo_root / path).read_bytes()))
    report = classify_tracked_files(entries)
    if report["violations"]:
        raise LiveExecutionError("Execution checkout bytes differ from the locked environment")
    return {
        "method": ENVIRONMENT_METHOD,
        "source_commit": _git(repo_root, "rev-parse", "HEAD").decode("utf-8").strip(),
        "core_autocrlf": autocrlf,
        **report,
    }


def validate_environment_record(record: Any) -> dict[str, str]:
    """Validate the public execution-environment record without touching a checkout."""
    if not isinstance(record, Mapping):
        raise LiveExecutionError("Environment record must be a mapping")
    files = record.get("tracked_files")
    exceptions = record.get("crlf_exception_files")
    suites = record.get("full_offline_suites")
    if (
        record.get("method") != ENVIRONMENT_METHOD
        or record.get("core_autocrlf") != "false"
        or not re.fullmatch(r"[0-9a-f]{40}", str(record.get("source_commit")))
    ):
        raise LiveExecutionError("Environment record identity mismatch")
    if exceptions != CRLF_BOUND_HISTORICAL_FILES:
        raise LiveExecutionError("Environment record CRLF exception list mismatch")
    if (
        type(files) is not int
        or record.get("byte_identical_to_blob") != files - len(CRLF_BOUND_HISTORICAL_FILES)
        or record.get("violations") != []
    ):
        raise LiveExecutionError("Environment record byte-identity accounting mismatch")
    if not isinstance(suites, Mapping) or set(suites) != set(REQUIRED_SUITES):
        raise LiveExecutionError("Environment record suite list mismatch")
    for name in REQUIRED_SUITES:
        suite = suites[name]
        if (
            not isinstance(suite, Mapping)
            or type(suite.get("tests")) is not int
            or suite["tests"] < 1
            or suite.get("failures") != 0
            or suite.get("errors") != 0
            or suite.get("result") != "PASS"
        ):
            raise LiveExecutionError("Environment record suite is not fully green: " + name)
    return {"identity": "PASS", "byte_identity": "PASS", "crlf_exceptions": "PASS", "full_suites": "PASS"}


# ---------------------------------------------------------------------------
# Locked bindings
# ---------------------------------------------------------------------------

def verify_locked_bindings(protocol_path: Path):
    """Verify the B3F protocol, the H0 decision record and both protected stacks."""
    try:
        validated = validate_protocol_file(
            protocol_path,
            expected_sha256=LOCKED_PROTOCOL_SHA256,
            expected_base_commit=EXPECTED_BASE_COMMIT,
        )
    except (Dev3ProtocolError, OSError) as error:
        raise LiveExecutionError("Locked P3 protocol verification failed") from error
    try:
        decision_lock.locked_decision_record()
        decision_lock.validate_public_lock()
        decision_lock.validate_protected_stacks()
    except (decision_lock.DecisionLockError, Dev3ProtocolError, OSError) as error:
        raise LiveExecutionError("H0 decision record or protected stack verification failed") from error
    if (
        decision_lock.DECISION_RECORD_SHA256 != DECISION_RECORD_SHA256
        or decision_lock.P3_PROTOCOL_SHA256 != LOCKED_PROTOCOL_SHA256
    ):
        raise LiveExecutionError("H0 decision record identity mismatch")
    return validated


def build_guard(validated, input_archive: Path, expected_input_sha256: str) -> Callable[[], None]:
    """Re-verify every locked identity. Called before each case and provider operation."""

    def guard() -> None:
        try:
            validated.assert_unchanged()
            decision_lock.locked_decision_record()
            decision_lock.validate_protected_stacks()
            archive_sha256 = sha256_bytes(input_archive.read_bytes())
        except (Dev3ProtocolError, decision_lock.DecisionLockError, OSError) as error:
            raise CheckpointIntegrityError("Locked protocol or protected stack changed") from error
        if archive_sha256 != expected_input_sha256:
            raise CheckpointIntegrityError("Authorized DEV3 input archive changed")

    return guard


# ---------------------------------------------------------------------------
# DEV3 input loader (input archive only)
# ---------------------------------------------------------------------------

def verify_archive_identity(input_archive: Path, expected_input_sha256: str = DEV3_INPUT_SHA256) -> bytes:
    """Hash the archive before anything opens it. The gold package is always rejected."""
    if any("gold" in part.lower() for part in input_archive.parts):
        raise LiveExecutionError("Gold-like input path is forbidden")
    try:
        data = input_archive.read_bytes()
    except OSError as error:
        raise LiveExecutionError("DEV3 input archive is unavailable") from error
    actual = sha256_bytes(data)
    if actual == DEV3_GOLD_SHA256:
        raise LiveExecutionError("DEV3 gold package is forbidden")
    if actual != expected_input_sha256:
        raise LiveExecutionError("DEV3 input archive hash mismatch")
    return data


def read_safe_inventory(archive_bytes: bytes) -> dict[str, bytes]:
    """Return member bytes after rejecting every unsafe or unexpected member name."""
    entries: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
            for info in archive.infolist():
                name = info.filename
                # zipfile rewrites separators on some platforms; the stored name is authoritative.
                if (
                    info.is_dir()
                    or info.orig_filename != name
                    or "\\" in name
                    or ":" in name
                    or (info.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise LiveExecutionError("Input archive member is forbidden")
                try:
                    _validate_member_name(name)
                except Dev3RunnerError as error:
                    raise LiveExecutionError("Input archive member is forbidden") from error
                if name.lower() in {existing.lower() for existing in entries}:
                    raise LiveExecutionError("Input archive has duplicate members")
                entries[name] = archive.read(info)
    except (OSError, zipfile.BadZipFile) as error:
        raise LiveExecutionError("Authorized DEV3 input archive is unreadable") from error
    if len(entries) != SEALED_INPUT_CONTRACT["member_count"]:
        raise LiveExecutionError("Input archive member count mismatch")
    if check_input_zero_gold(entries):
        raise LiveExecutionError("Gold marker found in the input archive")
    return entries


def extract_verified(entries: Mapping[str, bytes], input_root: Path) -> None:
    """Materialize the members and verify every extracted byte against the archive."""
    root = input_root.resolve()
    existing = sorted(p.relative_to(input_root).as_posix() for p in input_root.rglob("*") if p.is_file()) \
        if input_root.exists() else []
    if existing and existing != sorted(entries):
        raise LiveExecutionError("Extracted input inventory mismatch")
    for name, data in entries.items():
        target = (input_root / Path(*name.split("/"))).resolve()
        if root not in target.parents:
            raise LiveExecutionError("Input member escapes the authorized root")
        if not existing:
            _write_bytes_atomic(target, data)
        if not target.is_file() or target.read_bytes() != data:
            raise LiveExecutionError("Extracted input byte mismatch")


def _json_member(entries: Mapping[str, bytes], member: Any) -> Any:
    if not isinstance(member, str) or member not in entries:
        raise LiveExecutionError("Input manifest references an unknown member")
    try:
        return json.loads(entries[member].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise LiveExecutionError("Authorized input member is invalid") from error


def case_member_paths(case_id: str) -> dict[str, str]:
    """The five fixed archive paths of one case, keyed by role."""
    return {
        role: template.format(case_id=case_id)
        for role, template in SEALED_INPUT_CONTRACT["case_members"].items()
    }


def validate_case_members(case_id: str, members: Any) -> dict[str, str]:
    """Require a case row's member list to be exactly the five fixed paths of that case."""
    expected = case_member_paths(case_id)
    if not isinstance(members, list) or any(not isinstance(member, str) for member in members):
        raise LiveExecutionError("Case member list must be a list of strings")
    if len(members) != len(set(members)):
        raise LiveExecutionError("Case member list has duplicate members")
    for member in members:
        try:
            _validate_member_name(member)
        except Dev3RunnerError as error:
            raise LiveExecutionError("Case member list has a forbidden member") from error
    listed, fixed = set(members), set(expected.values())
    if any(member.startswith("cases/") and not member.startswith(f"cases/{case_id}/") for member in listed):
        raise LiveExecutionError("Case member list references another case")
    if fixed - listed:
        raise LiveExecutionError("Case member list is missing a fixed member")
    if listed - fixed:
        raise LiveExecutionError("Case member list has an unexpected member")
    return expected


def load_case_inputs(
    input_archive: Path,
    input_root: Path,
    *,
    expected_input_sha256: str = DEV3_INPUT_SHA256,
) -> list[CaseInput]:
    """Rebuild the ten CaseInput objects from the hash-verified input archive only."""
    entries = read_safe_inventory(verify_archive_identity(input_archive, expected_input_sha256))
    extract_verified(entries, input_root)
    manifest = _json_member(entries, SEALED_INPUT_CONTRACT["manifest_member"])
    if (
        not isinstance(manifest, dict)
        or set(manifest) != set(SEALED_INPUT_CONTRACT["manifest_keys"])
        or manifest.get("artifact") != SEALED_INPUT_CONTRACT["artifact"]
        or manifest.get("case_count") != len(CASE_IDS)
        or manifest.get("draft_interface") != SEALED_INPUT_CONTRACT["draft_interface"]
    ):
        raise LiveExecutionError("DEV3 input manifest identity mismatch")
    rows = manifest.get("cases")
    if (
        manifest.get("case_order") != list(CASE_IDS)
        or not isinstance(rows, list)
        or any(not isinstance(row, dict) for row in rows)
        or [row.get("case_id") for row in rows] != list(CASE_IDS)
    ):
        raise LiveExecutionError("DEV3 case identity or order mismatch")
    members_by_case: dict[str, dict[str, str]] = {}
    for row in rows:
        if set(row) != set(SEALED_INPUT_CONTRACT["case_fields"]):
            raise LiveExecutionError("DEV3 input manifest case row keys differ from the fixed layout")
        members_by_case[row["case_id"]] = validate_case_members(row["case_id"], row["members"])
    fixed_inventory = {SEALED_INPUT_CONTRACT["manifest_member"]} | {
        member for members in members_by_case.values() for member in members.values()
    }
    if set(entries) != fixed_inventory:
        raise LiveExecutionError("Input archive inventory differs from the fixed layout")

    cases: list[CaseInput] = []
    for row in rows:
        case_id = row["case_id"]
        members = members_by_case[case_id]
        base = _json_member(entries, members["base_document"])
        prepared = _json_member(entries, members["prepared_input"])
        report = _json_member(entries, members["ingestion_report"])
        m3_manifest = input_root / Path(*members["m3_manifest"].split("/"))
        try:
            ingestion = ingest_manifest_file(m3_manifest, m3_manifest.parent)
        except Exception as error:
            raise LiveExecutionError("Frozen M3 ingestion failed") from error
        if (
            not isinstance(report, dict)
            or report.get("corpus_fingerprint_sha256") != ingestion.fingerprint
            or report.get("round_trip_verified") is not True
        ):
            raise LiveExecutionError("M3 ingestion binding mismatch")
        context = DraftCompilerContext(
            base_document=base,
            passage_inputs=row["passage_inputs"],
            as_of_position=row["as_of_position"],
            profile_id=row["profile_id"],
            process_id=PROCESS_ID,
            process_version=PROCESS_VERSION,
            run_id=f"P3_{case_id}",
            ingestion=ingestion,
        )
        try:
            reproduced = prepare_story_extraction_draft_v1_1(context)
        except Exception as error:
            raise LiveExecutionError("Prepared Draft V1.1 input cannot be reproduced") from error
        if reproduced != prepared:
            raise LiveExecutionError("Prepared Draft V1.1 input does not reproduce exactly")
        cases.append(CaseInput(case_id, prepared, context))
    return cases


# ---------------------------------------------------------------------------
# Durable provider adapter
# ---------------------------------------------------------------------------

def select_locked_credential(config: Any) -> Any:
    """Return the single gemini_slot_3 credential. No other slot can be selected."""
    selected = [item for item in config.credentials if item.slot_id == CREDENTIAL_SLOT]
    if len(selected) != 1:
        raise LiveExecutionError("Locked credential slot is unavailable or ambiguous")
    return selected[0]


def build_durable_stack(
    checkpoint_root: Path, *, forbidden_secrets: tuple[str, ...] = ()
) -> tuple[PersistentRollingOperationPacer, DurableResearchExecutor]:
    """Instantiate the accepted pacer and executor with the locked limits."""
    pacer = PersistentRollingOperationPacer(
        checkpoint_root / "global_pacing.json",
        max_operations=GLOBAL_MAX_PROVIDER_OPERATIONS,
        window_seconds=GLOBAL_ROLLING_WINDOW_SECONDS,
    )
    executor = DurableResearchExecutor(
        checkpoint_root / "jobs",
        protocol_id=EXECUTOR_PROTOCOL_ID,
        window_cooldown_seconds=WINDOW_COOLDOWN_SECONDS,
        forbidden_secrets=forbidden_secrets,
    )
    return pacer, executor


class DurableFirstSuccessProvider:
    """B3G FirstSuccessProvider backed by durable, checkpointed execution windows."""

    def __init__(
        self,
        executor: DurableResearchExecutor,
        transport: Callable[[DurableJobSpec, int, str], Mapping[str, Any]],
        guard: Callable[[], None],
        *,
        counts_real_provider_operations: bool,
    ) -> None:
        self._executor = executor
        self._transport = transport
        self._guard = guard
        self.counts_real_provider_operations = counts_real_provider_operations
        self.actual_provider_operations = 0
        self.journal: list[dict[str, Any]] = []

    def first_success(self, spec: DurableJobSpec) -> ProviderFirstSuccess:
        self._guard()
        before = int(self._executor.ensure_job(spec)["total_provider_operations"])
        record = _execute_to_terminal(self._executor, spec, self._transport)
        self._guard()
        recorded = int(record["total_provider_operations"]) - before
        if not 0 <= recorded <= MAX_PROVIDER_ATTEMPTS_PER_JOB:
            raise CheckpointIntegrityError("Durable provider-operation accounting is invalid")
        real = recorded if self.counts_real_provider_operations else 0
        self.actual_provider_operations += real
        entry = {
            "job_id": spec.job_id,
            "request_fingerprint": spec.request_fingerprint,
            "state": record["state"],
            "raw_response": None,
            "raw_response_sha256": None,
            "telemetry": _job_telemetry(record),
        }
        self.journal.append(entry)
        if record["state"] != JobState.SUCCEEDED_LOCKED.value:
            raise TransportTerminalFailure(spec.job_id, str(record["transitions"][-1]["reason"]))
        success = record["first_success"]
        raw = success.get("raw_response")
        if not isinstance(raw, str) or sha256_bytes(raw.encode("utf-8")) != success.get("response_sha256"):
            raise CheckpointIntegrityError("Locked first-success response identity mismatch")
        entry.update(raw_response=raw, raw_response_sha256=success["response_sha256"])
        return ProviderFirstSuccess(raw, real, success["response_sha256"])


# ---------------------------------------------------------------------------
# Private artifacts and case execution
# ---------------------------------------------------------------------------

def private_layout(private_root: Path) -> dict[str, Path]:
    """Create the private artifact layout. A root inside the repository must be ignored."""
    root = private_root.resolve()
    repository = REPO_ROOT.resolve()
    if root == repository or (repository in root.parents and root.relative_to(repository).parts[0] != ".local"):
        raise LiveExecutionError("Private artifacts must live under ignored local storage")
    layout = {name: root / name for name in PRIVATE_DIRECTORIES}
    for path in layout.values():
        path.mkdir(parents=True, exist_ok=True)
    layout["root"] = root
    return layout


def _write_once(path: Path, data: bytes) -> str:
    """Write an immutable private artifact. An existing different artifact is an error."""
    if path.exists():
        if path.read_bytes() != data:
            raise LiveExecutionError("Immutable private artifact differs: " + path.name)
    else:
        _write_bytes_atomic(path, data)
    return sha256_bytes(data)


def _persist_attempt(layout: Mapping[str, Path], case: CaseInput, phase: str, entry: Mapping[str, Any]):
    raw = entry["raw_response"]
    draft, batch, validation = compile_raw_response(raw, case)
    raw_sha256 = _write_once(layout["raw"] / f"{case.case_id}_{phase}.txt", raw.encode("utf-8"))
    if raw_sha256 != entry["raw_response_sha256"]:
        raise LiveExecutionError("Raw response identity mismatch")
    draft_sha256 = None
    if draft is not None:
        draft_sha256 = _write_once(
            layout["drafts"] / f"{case.case_id}_{phase}.json", canonical_json_bytes(draft)
        )
    public = {
        "job_id": entry["job_id"],
        "request_fingerprint": entry["request_fingerprint"],
        "raw_response_sha256": raw_sha256,
        "draft_sha256": draft_sha256,
        "validation": validation,
        "transport": entry["telemetry"],
    }
    return public, batch, validation


def execute_cases(
    cases: Sequence[CaseInput],
    provider: DurableFirstSuccessProvider,
    layout: Mapping[str, Path],
    guard: Callable[[], None],
) -> list[dict[str, Any]]:
    """Run the B3G case semantics in locked order and persist every private artifact."""
    if [case.case_id for case in cases] != list(CASE_IDS):
        raise LiveExecutionError("Loaded DEV3 case order differs from the lock")
    ledger = FirstSuccessLedger()
    results: list[dict[str, Any]] = []
    for case in cases:
        guard()
        mark = len(provider.journal)
        outcome = failure = None
        try:
            outcome = execute_case(
                case, provider, ledger=ledger,
                offline_only=not provider.counts_real_provider_operations,
            )
        except TransportTerminalFailure as error:
            failure = error
        calls = provider.journal[mark:]
        expected_jobs = [f"M4B3F_P3_{case.case_id}_PRIMARY", f"M4B3F_P3_{case.case_id}_REPAIR_1"]
        if (
            not 1 <= len(calls) <= 1 + MAX_STRUCTURAL_REPAIRS_PER_CASE
            or [item["job_id"] for item in calls] != expected_jobs[: len(calls)]
        ):
            raise LiveExecutionError("Case job sequence differs from the locked protocol")
        for item in calls:
            _write_once(layout["telemetry"] / f"{item['job_id']}.json", canonical_json_bytes(item["telemetry"]))

        attempts, batch, validation = [], None, None
        for phase, item in zip(("primary", "repair_1"), calls):
            if item["raw_response"] is not None:
                public, batch, validation = _persist_attempt(layout, case, phase, item)
                attempts.append(public)
        if outcome is not None:
            if (
                len(attempts) != len(calls)
                or outcome["repair_count"] != len(calls) - 1
                or outcome["primary_request_fingerprint"] != calls[0]["request_fingerprint"]
                or outcome["terminal_validation"] != validation
                or outcome["compiled_batch"] != batch
                or outcome["quality_or_coverage_retries"] != 0
            ):
                raise LiveExecutionError("Runner core outcome differs from the persisted attempts")
            terminal_status = outcome["terminal_status"]
        else:
            terminal_status = "TRANSPORT_FAILURE"
            validation = {
                "pass": False,
                "category": "TRANSPORT_FAILURE",
                "phase": "PRIMARY" if len(calls) == 1 else "REPAIR",
                "transport_category": failure.category,
            }
            batch = None

        compiled_sha256 = failure_sha256 = None
        if terminal_status == "STRUCTURAL_VALID":
            compiled_sha256 = _write_once(
                layout["compiled"] / f"{case.case_id}.json", canonical_json_bytes(batch)
            )
        else:
            failure_sha256 = _write_once(
                layout["failures"] / f"{case.case_id}.json",
                canonical_json_bytes(
                    {"case_id": case.case_id, "terminal_status": terminal_status, "validation": validation}
                ),
            )
        repair_call = calls[1] if len(calls) > 1 else None
        item = {
            "case_id": case.case_id,
            "primary": attempts[0] if attempts else {
                "job_id": calls[0]["job_id"],
                "request_fingerprint": calls[0]["request_fingerprint"],
                "raw_response_sha256": None,
                "draft_sha256": None,
                "validation": validation,
                "transport": calls[0]["telemetry"],
            },
            "repair_used": repair_call is not None,
            "repair": None if repair_call is None else (attempts[1] if len(attempts) > 1 else {
                "job_id": repair_call["job_id"],
                "request_fingerprint": repair_call["request_fingerprint"],
                "raw_response_sha256": None,
                "draft_sha256": None,
                "validation": validation,
                "transport": repair_call["telemetry"],
            }),
            "terminal_status": terminal_status,
            "terminal_draft_sha256": attempts[-1]["draft_sha256"] if attempts else None,
            "compiled_batch_sha256": compiled_sha256,
            "terminal_failure_sha256": failure_sha256,
            "durable_provider_operations": sum(
                int(call["telemetry"]["total_provider_operations"]) for call in calls
            ),
        }
        _write_once(layout["case_results"] / f"{case.case_id}.json", canonical_json_bytes(item))
        results.append(item)
        print(json.dumps({"case_id": case.case_id, "repair_used": item["repair_used"],
                          "terminal_status": terminal_status}, sort_keys=True), flush=True)
    return results


# ---------------------------------------------------------------------------
# Immutable prediction set and public lock
# ---------------------------------------------------------------------------

def prediction_set_identity(results: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """Deterministic identity of the terminal prediction set, analogous to accepted B3C."""
    identities = []
    for item in results:
        repair = item["repair"]
        identity = {
            "case_id": item["case_id"],
            "primary_request_fingerprint": item["primary"]["request_fingerprint"],
            "primary_raw_response_sha256": item["primary"]["raw_response_sha256"],
            "repair_used": item["repair_used"],
            "repair_request_fingerprint": None if repair is None else repair["request_fingerprint"],
            "repair_raw_response_sha256": None if repair is None else repair["raw_response_sha256"],
            "terminal_status": item["terminal_status"],
            "terminal_draft_sha256": item["terminal_draft_sha256"],
            "compiled_batch_sha256": item["compiled_batch_sha256"],
            "terminal_failure_sha256": item["terminal_failure_sha256"],
        }
        for name, value in identity.items():
            if name.endswith(("sha256", "fingerprint")) and value is not None and not _HEX64.fullmatch(str(value)):
                raise LiveExecutionError("Prediction identity is not a SHA-256 value: " + name)
        if type(identity["repair_used"]) is not bool or identity["terminal_status"] not in TERMINAL_STATUSES:
            raise LiveExecutionError("Prediction identity is invalid")
        identities.append(identity)
    if [item["case_id"] for item in identities] != list(CASE_IDS):
        raise LiveExecutionError("Prediction set must contain every case in the locked order")
    return identities, sha256_bytes(canonical_json_bytes(identities))


def build_prediction_result(
    results: Sequence[Mapping[str, Any]],
    *,
    input_sha256: str,
    pacing: Mapping[str, Any],
    real_provider_operations: int,
) -> dict[str, Any]:
    identities, prediction_set_sha256 = prediction_set_identity(results)
    counts = {status: sum(item["terminal_status"] == status for item in results) for status in TERMINAL_STATUSES}
    return {
        "artifact": PREDICTION_RESULT_ID,
        "task_id": TASK_ID,
        "runner_id": RUNNER_ID,
        "adapter_sha256": normalized_file_sha256(REPO_ROOT / ADAPTER_PATH),
        "protocol_sha256": LOCKED_PROTOCOL_SHA256,
        "decision_record_sha256": DECISION_RECORD_SHA256,
        "dev3_input_sha256": input_sha256,
        "extractor_id": EXTRACTOR_ID,
        "model": MODEL,
        "credential_slot": CREDENTIAL_SLOT,
        "temperature": TEMPERATURE,
        "json_mode": True,
        "concurrency": CONCURRENCY,
        "runtime": RUNTIME_VERSION,
        "durable_executor": DURABLE_EXECUTOR_VERSION,
        "case_order": list(CASE_IDS),
        "terminal_case_count": len(results),
        "terminal_counts": counts,
        "repair_count": sum(bool(item["repair_used"]) for item in results),
        "durable_provider_operations": sum(int(item["durable_provider_operations"]) for item in results),
        "real_provider_operations": int(real_provider_operations),
        "prediction_set_sha256": prediction_set_sha256,
        "prediction_identities": identities,
        "predictions": [dict(item) for item in results],
        "global_pacing": dict(pacing),
        "dev3_gold_opened": False,
        "holdout_opened": False,
        "scoring_performed": False,
    }


def _assert_public_safe(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or not _PUBLIC_TOKEN.fullmatch(key):
                raise LiveExecutionError("Public lock key is not public-safe: " + path)
            _assert_public_safe(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_public_safe(child, f"{path}[{index}]")
    elif isinstance(value, str):
        if not _PUBLIC_TOKEN.fullmatch(value):
            raise LiveExecutionError("Public lock value is not public-safe: " + path)
    elif value is not None and type(value) not in (bool, int, float):
        raise LiveExecutionError("Public lock value type is not public-safe: " + path)


def build_public_prediction_lock(result: Mapping[str, Any]) -> dict[str, Any]:
    """Metadata-only public summary: identities, counts and hashes. No private content."""
    identities, prediction_set_sha256 = prediction_set_identity(result["predictions"])
    if (
        result.get("artifact") != PREDICTION_RESULT_ID
        or prediction_set_sha256 != result.get("prediction_set_sha256")
        or identities != result.get("prediction_identities")
        or result.get("terminal_case_count") != len(CASE_IDS)
        or result.get("dev3_gold_opened") is not False
        or result.get("holdout_opened") is not False
        or result.get("scoring_performed") is not False
    ):
        raise LiveExecutionError("Prediction result is not a complete terminal blind run")
    pacing = result["global_pacing"]
    cases = []
    for item, identity in zip(result["predictions"], identities):
        validation = (item["repair"] or item["primary"])["validation"]
        cases.append({
            **identity,
            "primary_draft_sha256": item["primary"]["draft_sha256"],
            "repair_draft_sha256": None if item["repair"] is None else item["repair"]["draft_sha256"],
            "terminal_failure_category": validation.get("category"),
            "durable_provider_operations": item["durable_provider_operations"],
        })
    lock = {
        "task": TASK_ID,
        "status": PUBLIC_LOCK_STATUS,
        "runner_id": RUNNER_ID,
        "adapter": {"path": ADAPTER_PATH, "sha256": result["adapter_sha256"]},
        "protocol_sha256": result["protocol_sha256"],
        "decision_record_sha256": result["decision_record_sha256"],
        "dev3_input_sha256": result["dev3_input_sha256"],
        "case_order": list(result["case_order"]),
        "extractor": {
            "identity": result["extractor_id"],
            "model": result["model"],
            "credential_slot": result["credential_slot"],
            "temperature": result["temperature"],
            "json_mode": result["json_mode"],
            "concurrency": result["concurrency"],
            "runtime": result["runtime"],
            "durable_executor": result["durable_executor"],
        },
        "execution": {
            "terminal_case_count": result["terminal_case_count"],
            "structural_valid_count": result["terminal_counts"]["STRUCTURAL_VALID"],
            "structural_failure_count": result["terminal_counts"]["STRUCTURAL_FAILURE"],
            "transport_failure_count": result["terminal_counts"]["TRANSPORT_FAILURE"],
            "repairs_used": result["repair_count"],
            "provider_operations": result["durable_provider_operations"],
            "real_provider_operations": result["real_provider_operations"],
            "interpretation": "STRUCTURAL_CONFORMANCE_ONLY_NOT_EXTRACTION_QUALITY",
        },
        "pacing": {
            "max_provider_operations": pacing["max_provider_operations"],
            "rolling_window_seconds": pacing["rolling_window_seconds"],
            "reservation_count": pacing["reservation_count"],
            "wait_count": pacing["wait_count"],
            "max_rolling_reservations_observed": pacing["max_rolling_reservations_observed"],
            "restart_persistent": pacing["restart_persistent"],
            "invariant": pacing["invariant"],
        },
        "cases": cases,
        "prediction_set_sha256": prediction_set_sha256,
        "predictions_locked": True,
        "all_cases_terminal_before_lock": True,
        "DEV3_gold_opened": False,
        "holdout_opened": False,
        "scoring_performed": False,
    }
    _assert_public_safe(lock)
    return lock


def write_public_prediction_lock(path: Path, lock: Mapping[str, Any]) -> str:
    _assert_public_safe(lock)
    data = yaml.safe_dump(dict(lock), sort_keys=False, default_flow_style=False, width=120).encode("utf-8")
    _write_bytes_atomic(path, data)
    return sha256_bytes(data)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def preflight(
    *,
    protocol_path: Path,
    input_archive: Path,
    private_root: Path,
    expected_input_sha256: str = DEV3_INPUT_SHA256,
    check_environment: bool = True,
):
    """Every offline gate, in order. Performs no provider operation and loads no credential."""
    environment = verify_execution_environment() if check_environment else None
    validated = verify_locked_bindings(protocol_path)
    verify_archive_identity(input_archive, expected_input_sha256)
    if expected_input_sha256 == DEV3_INPUT_SHA256:
        try:
            b3g_preflight(protocol_path=protocol_path, input_archive=input_archive)
        except Dev3RunnerError as error:
            raise LiveExecutionError("Runner core preflight failed") from error
    layout = private_layout(private_root)
    cases = load_case_inputs(input_archive, layout["input"], expected_input_sha256=expected_input_sha256)
    guard = build_guard(validated, input_archive, expected_input_sha256)
    guard()
    return environment, layout, cases, guard


def run(
    *,
    protocol_path: Path,
    input_archive: Path,
    private_root: Path,
    public_lock_path: Path = PUBLIC_LOCK_PATH,
    expected_input_sha256: str = DEV3_INPUT_SHA256,
    transport: Optional[Callable[[DurableJobSpec, int, str], Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """Blind run. Without an injected transport this is the real, irreversible execution."""
    real = transport is None
    if real != (expected_input_sha256 == DEV3_INPUT_SHA256):
        raise LiveExecutionError(
            "Only the accepted transport may run the sealed DEV3 input, and it may run nothing else"
        )
    _, layout, cases, guard = preflight(
        protocol_path=protocol_path,
        input_archive=input_archive,
        private_root=private_root,
        expected_input_sha256=expected_input_sha256,
        check_environment=real,
    )
    secrets: tuple[str, ...] = ()
    credential = None
    if real:
        try:
            config = load_runtime_config()
        except GeminiConfigError as error:
            raise LiveExecutionError("Runtime credential configuration is invalid") from error
        credential = select_locked_credential(config)
        secrets = tuple(item._api_key for item in config.credentials)
    pacer, executor = build_durable_stack(layout["checkpoints"], forbidden_secrets=secrets)
    if real:
        transport = GeminiDevWindowTransport(credential, pacer, guard)
    provider = DurableFirstSuccessProvider(executor, transport, guard, counts_real_provider_operations=real)
    results = execute_cases(cases, provider, layout, guard)
    guard()
    result = build_prediction_result(
        results,
        input_sha256=expected_input_sha256,
        pacing=pacer.snapshot(),
        real_provider_operations=provider.actual_provider_operations,
    )
    _write_bytes_atomic(layout["root"] / f"{PREDICTION_RESULT_ID}.json", canonical_json_bytes(result))
    _write_bytes_atomic(
        layout["root"] / f"{PREDICTION_MANIFEST_ID}.json",
        canonical_json_bytes({
            "artifact": PREDICTION_MANIFEST_ID,
            "protocol_sha256": LOCKED_PROTOCOL_SHA256,
            "decision_record_sha256": DECISION_RECORD_SHA256,
            "dev3_input_sha256": expected_input_sha256,
            "case_order": list(CASE_IDS),
            "entries": result["prediction_identities"],
            "prediction_set_sha256": result["prediction_set_sha256"],
            "predictions_locked": True,
        }),
    )
    write_public_prediction_lock(public_lock_path, build_public_prediction_lock(result))
    print(json.dumps({"prediction_set_sha256": result["prediction_set_sha256"],
                      "terminal": result["terminal_case_count"]}, sort_keys=True), flush=True)
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preflight", "run"), required=True)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--input-archive", required=True, type=Path)
    parser.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE_ROOT)
    parser.add_argument("--public-lock", type=Path, default=PUBLIC_LOCK_PATH)
    parser.add_argument("--authorize-live-provider-operations", default="")
    args = parser.parse_args(argv)
    try:
        if args.mode == "preflight":
            environment, _, cases, _ = preflight(
                protocol_path=args.protocol, input_archive=args.input_archive, private_root=args.private_root
            )
            print(json.dumps({"cases": len(cases), "environment": environment["method"],
                              "provider_operations": 0, "status": "PREFLIGHT_PASS"}, sort_keys=True))
            return 0
        if args.authorize_live_provider_operations != LIVE_AUTHORIZATION_TOKEN:
            raise LiveExecutionError("Run mode requires the explicit live authorization token")
        run(
            protocol_path=args.protocol,
            input_archive=args.input_archive,
            private_root=args.private_root,
            public_lock_path=args.public_lock,
        )
    except (LiveExecutionError, Dev3RunnerError, Dev3ProtocolError, CheckpointIntegrityError) as error:
        print(f"M4_04B3H_EXECUTION_STOPPED_FAIL_CLOSED: {type(error).__name__}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
