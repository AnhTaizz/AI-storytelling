"""Light Novel source adapter v0 (LIGHT_NOVEL_INGESTION/v0).

M3 establishes WHERE evidence came from. It reads an ordered set of controlled
plain-text documents and produces source-layer records only:

    manifest -> SourceDocument / SourceSegment / TEXT_RANGE_V0 locators
             -> SourcePassageRef (adapter-level, mechanical)
             -> Canonical Story v0 source-layer skeleton

It performs no story interpretation: no entities, events, propositions,
assertions, mentions, or evidence roles. Those belong to M4.

The adapter never changes source text. Bytes are hashed, strictly decoded as
UTF-8 and sliced; nothing is stripped, normalized or re-encoded.

No network, model, database or embedding is used.

Contract: docs/research/m3/M3_LIGHT_NOVEL_INGESTION_CONTRACT_V0.md
"""
import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.canonical_story.conformance_v0 import validate_document  # noqa: E402

CONTRACT_VERSION = "LIGHT_NOVEL_INGESTION/v0"
ADAPTER_VERSION = "light_novel_adapter_v0/0.1.0"
SEGMENTATION_VERSION = "PARAGRAPH_SEGMENT_V0"
LOCATOR_KIND = "TEXT_RANGE_V0"
PASSAGE_REF_KIND = "SOURCE_PASSAGE_REF_V0"
MEDIA_KIND = "LIGHT_NOVEL_TEXT"
CANONICAL_SCHEMA_VERSION = "canonical_story/v0"
AUTHORITY_POLICY = "DEFAULT_V0"
FINGERPRINT_DOMAIN = "LIGHT_NOVEL_CORPUS_FINGERPRINT_V0"
SEGMENT_ID_DOMAIN = "LIGHT_NOVEL_SEGMENT_ID_V0"

MANIFEST_SCHEMA_PATH = REPO_ROOT / "schemas/light_novel_ingestion/light_novel_source_manifest_v0.schema.json"

EVIDENCE_ROLES = ("DEPICTION", "RETROSPECTIVE", "IN_WORLD_REPORT", "NARRATION_SUMMARY", "PARATEXT")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

# Line terminators recognised by PARAGRAPH_SEGMENT_V0. Nothing else ends a line.
LINE_TERMINATOR = re.compile(r"\r\n|\n|\r")
TERMINATOR_NAMES = {"\r\n": "CRLF", "\n": "LF", "\r": "CR"}

# Characters that make a line blank when the line contains nothing else.
# A fixed list, so the result does not depend on the Unicode tables of the
# Python version in use.
BLANK_CODE_POINTS = (
    0x0009, 0x000B, 0x000C, 0x0020, 0x0085, 0x00A0, 0x1680,
    0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200A,
    0x2028, 0x2029, 0x202F, 0x205F, 0x3000,
)
BLANK_CHARACTERS = frozenset(chr(cp) for cp in BLANK_CODE_POINTS)
BOM_CHARACTER = chr(0xFEFF)


class IngestionError(Exception):
    """The adapter fails closed: any contract violation raises this error."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(obj: Any) -> bytes:
    """Deterministic serialization: sorted keys, two-space indent, LF, UTF-8, final newline."""
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _compact(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")


# --------------------------------------------------------------------------- manifest

def load_manifest(path: Path) -> Dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise IngestionError("MANIFEST_NOT_FOUND", str(path))
    try:
        text = path.read_bytes().decode("utf-8", errors="strict")
        data = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    except (UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise IngestionError("INVALID_MANIFEST", f"cannot parse manifest: {exc}") from exc
    return data


def validate_manifest(manifest: Any) -> None:
    schema = json.loads(MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(manifest), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.absolute_path) or "<root>"
        raise IngestionError("INVALID_MANIFEST", f"{where}: {first.message}")
    ids = [d["document_id"] for d in manifest["documents"]]
    orders = [d["order"] for d in manifest["documents"]]
    if len(set(ids)) != len(ids):
        raise IngestionError("DUPLICATE_DOCUMENT_ID", "document_id values must be unique")
    if len(set(orders)) != len(orders):
        raise IngestionError("DUPLICATE_DOCUMENT_ORDER", "order values must be unique")
    reserved = {manifest["story_id"], manifest["stream_id"]}
    if manifest["story_id"] == manifest["stream_id"] or reserved & set(ids):
        raise IngestionError("ID_COLLISION", "story_id, stream_id and document_id values must all differ")
    for doc in manifest["documents"]:
        _check_relative_path(doc["path"])


def _check_relative_path(raw: str) -> None:
    posix = PurePosixPath(raw)
    if "\\" in raw or posix.is_absolute() or re.match(r"^[A-Za-z]:", raw) or ".." in posix.parts:
        raise IngestionError("INVALID_SOURCE_PATH", f"path must be relative, forward-slash, without '..': {raw!r}")


# --------------------------------------------------------------------------- segmentation

@dataclass(frozen=True)
class Line:
    char_start: int
    char_end: int            # end of content, before the terminator
    byte_start: int
    byte_end: int            # end of content, before the terminator
    terminator: str          # "", "\n", "\r\n" or "\r"
    blank: bool


def scan_lines(text: str) -> List[Line]:
    """Split text into lines with exact code-point and UTF-8 byte offsets. Text is not modified."""
    lines: List[Line] = []
    cursor = 0
    byte_cursor = 0
    while cursor < len(text):
        match = LINE_TERMINATOR.search(text, cursor)
        content_end = match.start() if match else len(text)
        terminator = match.group(0) if match else ""
        content = text[cursor:content_end]
        content_bytes = len(content.encode("utf-8"))
        lines.append(Line(cursor, content_end, byte_cursor, byte_cursor + content_bytes, terminator,
                          all(ch in BLANK_CHARACTERS for ch in content)))
        cursor = content_end + len(terminator)
        byte_cursor += content_bytes + len(terminator)
    return lines


@dataclass(frozen=True)
class Span:
    char_start: int
    char_end_exclusive: int
    byte_start: int
    byte_end_exclusive: int


def paragraph_spans(lines: List[Line]) -> List[Span]:
    """PARAGRAPH_SEGMENT_V0: each maximal run of consecutive non-blank lines is one segment.

    A segment runs from the start of its first line to the end of the content of its
    last line. Line terminators inside the run are part of the segment; the terminator
    after the last line is not. A paragraph is never split because of its length.
    """
    spans: List[Span] = []
    run: List[Line] = []
    for line in lines + [None]:
        if line is not None and not line.blank:
            run.append(line)
        elif run:
            spans.append(Span(run[0].char_start, run[-1].char_end, run[0].byte_start, run[-1].byte_end))
            run = []
    return spans


# --------------------------------------------------------------------------- identity

def corpus_fingerprint(story_id: str, stream_id: str, documents: List[Tuple[int, str, str]]) -> str:
    """SHA-256 over a canonical serialization of the corpus identity.

    `documents` is a list of (order, document_id, document_version). Binds the contract
    version, story, stream, and the ordered documents. Filesystem location is not an input.
    """
    payload = {
        "contract_version": CONTRACT_VERSION,
        "story_id": story_id,
        "stream_id": stream_id,
        "documents": [{"order": o, "document_id": d, "version": v} for o, d, v in sorted(documents)],
    }
    return sha256_hex(FINGERPRINT_DOMAIN.encode("ascii") + b"\n" + _compact(payload))


def segment_id(story_id: str, document_id: str, document_version: str, span: Span, text_sha256: str) -> str:
    """Opaque deterministic SourceSegment id. No rule may interpret it.

    Derived from the document version, so any change to the document's bytes gives
    every segment of that document a new id. A stale reference cannot look valid.
    """
    payload = [SEGMENT_ID_DOMAIN, SEGMENTATION_VERSION, story_id, document_id, document_version,
               span.char_start, span.char_end_exclusive, text_sha256]
    return "seg-" + sha256_hex(_compact(payload))[:40]


# --------------------------------------------------------------------------- ingestion result

@dataclass
class IngestedDocument:
    document_id: str
    order: int
    version: str
    logical_path: str
    editorial_label: Optional[str]
    source_bytes: bytes
    text: str
    lines: List[Line]
    segments: List[Dict[str, Any]]


class IngestionResult:
    """In-memory result of one ingestion run. Holds exact source text for round-trip checks."""

    def __init__(self, manifest: Dict[str, Any], documents: List[IngestedDocument]):
        self.manifest = manifest
        self.story_id: str = manifest["story_id"]
        self.stream_id: str = manifest["stream_id"]
        self.documents = documents
        self.fingerprint = corpus_fingerprint(
            self.story_id, self.stream_id, [(d.order, d.document_id, d.version) for d in documents])
        self._segments: Dict[str, Tuple[IngestedDocument, Dict[str, Any]]] = {}
        for doc in documents:
            for seg in doc.segments:
                if seg["id"] in self._segments:
                    raise IngestionError("DUPLICATE_SEGMENT_ID", seg["id"])
                self._segments[seg["id"]] = (doc, seg)

    # ---- canonical source layer

    def canonical_skeleton(self) -> Dict[str, Any]:
        """Canonical Story v0 document with the source layer filled and every later collection empty."""
        story: Dict[str, Any] = {"id": self.story_id, "discourse_stream_id": self.stream_id}
        if self.manifest.get("story_editorial_label") is not None:
            story["editorial_label"] = self.manifest["story_editorial_label"]
        source_documents = []
        for doc in self.documents:
            record: Dict[str, Any] = {"id": doc.document_id, "story_id": self.story_id,
                                      "stream_id": self.stream_id, "version": doc.version,
                                      "media_kind": MEDIA_KIND}
            if doc.editorial_label is not None:
                record["editorial_label"] = doc.editorial_label
            source_documents.append(record)
        skeleton = {
            "schema_version": CANONICAL_SCHEMA_VERSION,
            "authority_policy": AUTHORITY_POLICY,
            "story": story,
            "source_documents": source_documents,
            "source_segments": [seg for doc in self.documents for seg in doc.segments],
            "evidence_refs": [], "mentions": [], "entities": [], "events": [], "temporal_anchors": [],
            "propositions": [], "extraction_provenance": [], "assertions": [],
        }
        report = validate_document(skeleton)
        if not report["pass"]:
            issues = list(report["structural"]["issues"][:3])
            issues += [i for s in report["semantic"].values() for i in s["issues"]][:3]
            raise IngestionError("CANONICAL_INCOMPATIBLE", "; ".join(str(i) for i in issues))
        return skeleton

    def ingestion_report(self) -> Dict[str, Any]:
        """Deterministic mechanical report. Contains hashes, counts and offsets; no source text."""
        documents = []
        for doc in self.documents:
            endings = {"LF": 0, "CRLF": 0, "CR": 0}
            for line in doc.lines:
                if line.terminator:
                    endings[TERMINATOR_NAMES[line.terminator]] += 1
            documents.append({
                "document_id": doc.document_id,
                "order": doc.order,
                "version": doc.version,
                "logical_path": doc.logical_path,
                "byte_length": len(doc.source_bytes),
                "char_length": len(doc.text),
                "line_count": len(doc.lines),
                "line_endings": endings,
                "begins_with_bom_character": doc.text.startswith(BOM_CHARACTER),
                "segment_count": len(doc.segments),
                "max_segment_chars": max(s["locator"]["char_end_exclusive"] - s["locator"]["char_start"]
                                         for s in doc.segments),
            })
        return {
            "contract_version": CONTRACT_VERSION,
            "adapter_version": ADAPTER_VERSION,
            "segmentation_version": SEGMENTATION_VERSION,
            "locator_kind": LOCATOR_KIND,
            "canonical_schema_version": CANONICAL_SCHEMA_VERSION,
            "story_id": self.story_id,
            "stream_id": self.stream_id,
            "source_language": self.manifest["source_language"],
            "corpus_fingerprint_sha256": self.fingerprint,
            "document_count": len(self.documents),
            "segment_count": sum(len(d.segments) for d in self.documents),
            "documents": documents,
            "round_trip_verified": True,
            "text_normalization_applied": False,
            "model_invoked": False,
        }

    # ---- source passage references

    def segment(self, segment_id_: str) -> Dict[str, Any]:
        if segment_id_ not in self._segments:
            raise IngestionError("UNKNOWN_SEGMENT", segment_id_)
        return self._segments[segment_id_][1]

    def segment_text(self, segment_id_: str) -> str:
        doc, seg = self._lookup(segment_id_)
        loc = seg["locator"]
        return doc.text[loc["char_start"]:loc["char_end_exclusive"]]

    def passage_ref(self, segment_id_: str, relative_start: Optional[int] = None,
                    relative_end_exclusive: Optional[int] = None) -> Dict[str, Any]:
        """Mechanical reference to an exact span inside one segment (the whole segment by default).

        This is an adapter-level record, not a Canonical Story record. It carries no
        evidence role: deciding the role is story interpretation and belongs to M4.
        """
        doc, seg = self._lookup(segment_id_)
        loc = seg["locator"]
        length = loc["char_end_exclusive"] - loc["char_start"]
        start = 0 if relative_start is None else relative_start
        end = length if relative_end_exclusive is None else relative_end_exclusive
        for value in (start, end):
            if isinstance(value, bool) or not isinstance(value, int):
                raise IngestionError("INVALID_SPAN", "span bounds must be integers")
        if not 0 <= start < end <= length:
            raise IngestionError("INVALID_SPAN", f"need 0 <= start < end <= {length}, got [{start}, {end})")
        char_start = loc["char_start"] + start
        char_end = loc["char_start"] + end
        segment_text = doc.text[loc["char_start"]:loc["char_end_exclusive"]]
        byte_start = loc["byte_start"] + len(segment_text[:start].encode("utf-8"))
        span_text = doc.text[char_start:char_end]
        byte_end = byte_start + len(span_text.encode("utf-8"))
        return {
            "kind": PASSAGE_REF_KIND,
            "story_id": self.story_id,
            "document_id": doc.document_id,
            "document_version": doc.version,
            "segment_id": seg["id"],
            "position": dict(seg["position"]),
            "relative_char_start": start,
            "relative_char_end_exclusive": end,
            "span": {
                "kind": LOCATOR_KIND,
                "source_sha256": doc.version,
                "char_start": char_start,
                "char_end_exclusive": char_end,
                "byte_start": byte_start,
                "byte_end_exclusive": byte_end,
                "span_text_sha256": sha256_hex(span_text.encode("utf-8")),
            },
        }

    def resolve_passage_text(self, ref: Dict[str, Any]) -> str:
        """Return the exact referenced text, after verifying the reference against this ingestion."""
        self.verify_passage_ref(ref)
        doc, _ = self._lookup(ref["segment_id"])
        return doc.text[ref["span"]["char_start"]:ref["span"]["char_end_exclusive"]]

    def verify_passage_ref(self, ref: Dict[str, Any]) -> None:
        """Fail closed unless the reference is exactly what this ingestion would produce."""
        if not isinstance(ref, dict) or ref.get("kind") != PASSAGE_REF_KIND:
            raise IngestionError("INVALID_PASSAGE_REF", "not a SOURCE_PASSAGE_REF_V0 record")
        doc, _ = self._lookup(ref.get("segment_id"))
        if ref.get("document_version") != doc.version:
            raise IngestionError("STALE_PASSAGE_REF", "reference was made against another document version")
        expected = self.passage_ref(ref["segment_id"], ref.get("relative_char_start"),
                                    ref.get("relative_char_end_exclusive"))
        if expected != ref:
            raise IngestionError("INVALID_PASSAGE_REF", "reference does not match the ingested source")
        span = ref["span"]
        if doc.source_bytes[span["byte_start"]:span["byte_end_exclusive"]].decode("utf-8") != \
                doc.text[span["char_start"]:span["char_end_exclusive"]]:
            raise IngestionError("INVALID_PASSAGE_REF", "byte range and character range disagree")

    def _lookup(self, segment_id_: Any) -> Tuple[IngestedDocument, Dict[str, Any]]:
        if segment_id_ not in self._segments:
            raise IngestionError("UNKNOWN_SEGMENT", str(segment_id_))
        return self._segments[segment_id_]


def materialize_evidence_ref(passage_ref: Dict[str, Any], evidence_role: str, evidence_id: str) -> Dict[str, Any]:
    """Build a Canonical Story v0 EvidenceRef from a passage reference.

    The CALLER supplies the evidence role and the id. This function checks mechanics
    only. It never infers, defaults or changes a role.
    """
    if not isinstance(passage_ref, dict) or passage_ref.get("kind") != PASSAGE_REF_KIND:
        raise IngestionError("INVALID_PASSAGE_REF", "not a SOURCE_PASSAGE_REF_V0 record")
    if evidence_role not in EVIDENCE_ROLES:
        raise IngestionError("INVALID_EVIDENCE_ROLE", f"role must be supplied by the caller, one of {EVIDENCE_ROLES}")
    if not isinstance(evidence_id, str) or not ID_PATTERN.match(evidence_id):
        raise IngestionError("INVALID_ID", f"evidence id does not satisfy the canonical Id rule: {evidence_id!r}")
    return {
        "id": evidence_id,
        "segment_id": passage_ref["segment_id"],
        "position": dict(passage_ref["position"]),
        "span": dict(passage_ref["span"]),
        "role": evidence_role,
    }


# --------------------------------------------------------------------------- ingestion

def ingest(manifest: Dict[str, Any], source_root: Path) -> IngestionResult:
    """Ingest the documents named by `manifest`, reading files under `source_root`."""
    validate_manifest(manifest)
    source_root = Path(source_root)
    documents: List[IngestedDocument] = []
    for entry in sorted(manifest["documents"], key=lambda d: d["order"]):
        path = source_root.joinpath(*PurePosixPath(entry["path"]).parts)
        if not path.is_file():
            raise IngestionError("SOURCE_NOT_FOUND", f"document {entry['document_id']}: {entry['path']}")
        source_bytes = path.read_bytes()
        version = sha256_hex(source_bytes)
        if version != entry["expected_sha256"]:
            raise IngestionError("SHA256_MISMATCH", f"document {entry['document_id']}: expected "
                                                    f"{entry['expected_sha256']}, found {version}")
        try:
            text = source_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise IngestionError("INVALID_UTF8", f"document {entry['document_id']}: {exc}") from exc
        lines = scan_lines(text)
        spans = paragraph_spans(lines)
        if not spans:
            raise IngestionError("EMPTY_DOCUMENT", f"document {entry['document_id']} has no non-blank text")
        segments = []
        for ordinal, span in enumerate(spans, start=1):
            segment_text = text[span.char_start:span.char_end_exclusive]
            text_sha = sha256_hex(segment_text.encode("utf-8"))
            segments.append({
                "id": segment_id(manifest["story_id"], entry["document_id"], version, span, text_sha),
                "document_id": entry["document_id"],
                "position": {"stream_id": manifest["stream_id"], "key": [entry["order"], ordinal],
                             "display": f"{entry['order']}.{ordinal}"},
                "locator": {
                    "kind": LOCATOR_KIND,
                    "source_sha256": version,
                    "char_start": span.char_start,
                    "char_end_exclusive": span.char_end_exclusive,
                    "byte_start": span.byte_start,
                    "byte_end_exclusive": span.byte_end_exclusive,
                    "segment_text_sha256": text_sha,
                    "document_order": entry["order"],
                    "paragraph_ordinal": ordinal,
                },
            })
        _verify_document(text, source_bytes, segments)
        documents.append(IngestedDocument(entry["document_id"], entry["order"], version, entry["path"],
                                          entry.get("editorial_label"), source_bytes, text, lines, segments))
    return IngestionResult(manifest, documents)


def _verify_document(text: str, source_bytes: bytes, segments: List[Dict[str, Any]]) -> None:
    """Exact round-trip and coverage checks. Any failure is a defect in the adapter and stops ingestion."""
    previous_end = 0
    for seg in segments:
        loc = seg["locator"]
        segment_text = text[loc["char_start"]:loc["char_end_exclusive"]]
        if not segment_text or loc["char_start"] < previous_end:
            raise IngestionError("ROUND_TRIP_FAILED", f"segment {seg['id']}: empty or overlapping span")
        if source_bytes[loc["byte_start"]:loc["byte_end_exclusive"]] != segment_text.encode("utf-8"):
            raise IngestionError("ROUND_TRIP_FAILED", f"segment {seg['id']}: byte range does not match")
        if sha256_hex(segment_text.encode("utf-8")) != loc["segment_text_sha256"]:
            raise IngestionError("ROUND_TRIP_FAILED", f"segment {seg['id']}: text hash does not match")
        _check_gap(text, previous_end, loc["char_start"])
        previous_end = loc["char_end_exclusive"]
    _check_gap(text, previous_end, len(text))


def _check_gap(text: str, start: int, end: int) -> None:
    """Text outside segments may contain only blank characters and line terminators."""
    for ch in text[start:end]:
        if ch not in BLANK_CHARACTERS and ch not in "\r\n":
            raise IngestionError("ROUND_TRIP_FAILED", f"non-blank text outside any segment near offset {start}")


def ingest_manifest_file(manifest_path: Path, source_root: Optional[Path] = None) -> IngestionResult:
    manifest_path = Path(manifest_path)
    manifest = load_manifest(manifest_path)
    return ingest(manifest, Path(source_root) if source_root is not None else manifest_path.parent)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Light Novel source adapter v0 (source layer only).")
    parser.add_argument("manifest", type=Path, help="source manifest (YAML or JSON)")
    parser.add_argument("--source-root", type=Path, default=None, help="default: the manifest's directory")
    parser.add_argument("--out", type=Path, default=None, help="directory for the skeleton and the report")
    args = parser.parse_args(argv)
    try:
        result = ingest_manifest_file(args.manifest, args.source_root)
        skeleton = result.canonical_skeleton()
        report = result.ingestion_report()
    except IngestionError as exc:
        print(f"INGESTION FAILED: {exc}", file=sys.stderr)
        return 1
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "canonical_source_layer.json").write_bytes(canonical_json_bytes(skeleton))
        (args.out / "ingestion_report.json").write_bytes(canonical_json_bytes(report))
    print(json.dumps({k: report[k] for k in ("contract_version", "adapter_version", "corpus_fingerprint_sha256",
                                              "document_count", "segment_count")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
