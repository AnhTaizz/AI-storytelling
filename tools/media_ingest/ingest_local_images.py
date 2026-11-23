"""Copy user-supplied local images into a private, deduplicated image collection.

Only file headers are inspected; image pixels are never decoded. Blank CSV values
use the CLI defaults (or null/empty-list for optional metadata). Volume and chapter
labels remain strings so identifiers such as "extra-1" are preserved.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import struct
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import yaml


PREFIXES = {"roshidere": "rsd", "otonari_no_tenshi": "otn", "kaoru_hana": "khr",
            "otonari_no_tenshi_after_the_rain": "otra"}
CATEGORIES = ("manga_panel", "character_emotion", "illustration", "other")
RIGHTS_BASES = ("purchased_copy", "official_promo", "own_screenshot", "original_art", "unknown")
EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
CSV_FIELDS = ("filename", "category", "characters", "emotion", "volume", "chapter",
              "source", "rights_basis", "notes")
REPO_ROOT = Path(__file__).resolve().parents[2]
PROTECTED_ROOT = (REPO_ROOT / "data/sample/roshidere").resolve()
ALLOWED_OUTPUT = PROTECTED_ROOT / "images"


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _check_path(path: Path) -> Path:
    resolved = path.resolve()
    if _within(resolved, PROTECTED_ROOT) and not _within(resolved, ALLOWED_OUTPUT):
        raise ValueError(f"protected path is outside the image output folder: {path}")
    return resolved


def _exact(stream, count: int) -> bytes:
    data = stream.read(count)
    if len(data) != count:
        raise ValueError("truncated image header")
    return data


def read_dimensions(path: Path) -> tuple[int, int]:
    """Read PNG, JPEG SOFn, GIF, or WebP VP8/VP8L/VP8X dimensions.

    Raise ValueError on malformed/truncated or unsupported dimension headers.
    This intentionally does not validate compressed image contents.
    """
    with path.open("rb") as stream:
        signature = stream.read(12)
        stream.seek(0)
        if signature.startswith(b"\x89PNG\r\n\x1a\n"):
            header = _exact(stream, 29)
            if header[8:16] != b"\x00\x00\x00\rIHDR":
                raise ValueError("missing PNG IHDR")
            dimensions = struct.unpack(">II", header[16:24])
        elif signature[:6] in (b"GIF87a", b"GIF89a"):
            dimensions = struct.unpack("<HH", _exact(stream, 13)[6:10])
        elif signature.startswith(b"\xff\xd8"):
            dimensions = _jpeg_dimensions(stream)
        elif signature[:4] == b"RIFF" and signature[8:12] == b"WEBP":
            dimensions = _webp_dimensions(stream)
        else:
            raise ValueError("unsupported image header")
    if min(dimensions) <= 0:
        raise ValueError("zero image dimension")
    return dimensions


def _jpeg_dimensions(stream) -> tuple[int, int]:
    _exact(stream, 2)
    sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                   0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while True:
        if _exact(stream, 1) != b"\xff":
            raise ValueError("invalid JPEG marker")
        marker = _exact(stream, 1)[0]
        while marker == 0xFF:
            marker = _exact(stream, 1)[0]
        if marker in (0x00, 0xD9, 0xDA):
            raise ValueError("JPEG has no dimension header")
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            continue
        length = struct.unpack(">H", _exact(stream, 2))[0]
        if length < 2:
            raise ValueError("invalid JPEG segment length")
        payload = _exact(stream, length - 2)
        if marker in sof_markers:
            if len(payload) < 6 or not payload[5] or len(payload) != 6 + 3 * payload[5]:
                raise ValueError("invalid JPEG SOF header")
            height, width = struct.unpack(">HH", payload[1:5])
            return width, height


def _webp_dimensions(stream) -> tuple[int, int]:
    header = _exact(stream, 12)
    end = struct.unpack("<I", header[4:8])[0] + 8
    if end > os.fstat(stream.fileno()).st_size or end < 12:
        raise ValueError("invalid WebP container size")
    while stream.tell() + 8 <= end:
        chunk = _exact(stream, 8)
        kind, size = chunk[:4], struct.unpack("<I", chunk[4:])[0]
        start = stream.tell()
        next_chunk = start + size + (size % 2)
        if next_chunk > end:
            raise ValueError("truncated WebP chunk")
        if kind == b"VP8 ":
            if size < 10:
                raise ValueError("truncated VP8 header")
            data = _exact(stream, 10)
            if data[0] & 1 or data[3:6] != b"\x9d\x01\x2a":
                raise ValueError("invalid VP8 keyframe header")
            width, height = struct.unpack("<HH", data[6:10])
            return width & 0x3FFF, height & 0x3FFF
        if kind == b"VP8L":
            if size < 5:
                raise ValueError("truncated VP8L header")
            data = _exact(stream, 5)
            if data[0] != 0x2F or data[4] & 0xE0:
                raise ValueError("invalid VP8L header")
            bits = int.from_bytes(data[1:5], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if kind == b"VP8X":
            if size != 10:
                raise ValueError("invalid VP8X header size")
            data = _exact(stream, 10)
            return int.from_bytes(data[4:7], "little") + 1, int.from_bytes(data[7:10], "little") + 1
        stream.seek(next_chunk)
    raise ValueError("WebP has no dimension header")


def _labels(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    _check_path(path)
    labels = {}
    try:
        stream = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as error:
        raise ValueError(f"cannot read labels CSV: {error}") from error
    with stream:
        reader = csv.DictReader(stream, strict=True)
        fields = reader.fieldnames or []
        if "filename" not in fields or len(fields) != len(set(fields)) or set(fields) - set(CSV_FIELDS):
            raise ValueError("labels CSV needs a filename header and only supported, unique columns")
        for line, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"labels CSV row {line}: wrong number of columns")
            row = {key: value.strip() for key, value in row.items()}
            filename = row["filename"]
            relative = PurePosixPath(filename)
            if (not filename or relative.is_absolute() or ".." in relative.parts
                    or "\\" in filename or ":" in filename or relative.as_posix() != filename):
                raise ValueError(f"labels CSV row {line}: filename must be a relative forward-slash path")
            if filename in labels:
                raise ValueError(f"labels CSV row {line}: repeated filename {filename!r}")
            for key, choices in (("category", CATEGORIES), ("rights_basis", RIGHTS_BASES)):
                value = row.get(key, "")
                if value and value not in choices:
                    raise ValueError(f"labels CSV row {line}: unknown {key} {value!r}; choose from {', '.join(choices)}")
            labels[filename] = row
    return labels


def _files(root: Path, exclude: Path | None = None):
    """Walk deterministically, without following links or entering protected paths."""
    def on_error(error):
        raise error

    for directory, directories, files in os.walk(root, followlinks=False, onerror=on_error):
        retained = []
        for name in sorted(directories):
            child = Path(directory) / name
            if child.is_symlink() or (hasattr(child, "is_junction") and child.is_junction()):
                continue
            try:
                resolved = _check_path(child)
            except ValueError:
                continue
            if exclude is None or not _within(resolved, exclude):
                retained.append(name)
        directories[:] = retained
        for name in sorted(files):
            child = Path(directory) / name
            if child.is_symlink():
                continue
            try:
                _check_path(child)
            except ValueError:
                continue
            yield child


def _manifest(path: Path, series: str) -> dict:
    if not path.exists():
        return {"series": series, "schema_version": 1, "policy": "local_private_only", "aggregate": {}, "images": []}
    _check_path(path)
    with path.open("r", encoding="utf-8") as stream:
        manifest = yaml.safe_load(stream)
    if (not isinstance(manifest, dict) or manifest.get("series") != series
            or manifest.get("schema_version") != 1 or manifest.get("policy") != "local_private_only"
            or not isinstance(manifest.get("images"), list)):
        raise ValueError("existing manifest has an incompatible series, schema, policy, or images list")
    for record in manifest["images"]:
        if (not isinstance(record, dict) or record.get("category") not in CATEGORIES
                or record.get("rights_basis") not in RIGHTS_BASES
                or not isinstance(record.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
                or not isinstance(record.get("path"), str)
                or not isinstance(record.get("image_id"), str)):
            raise ValueError("existing manifest contains an invalid image record")
    return manifest


def _highest_number(out: Path, manifest: dict, prefix: str) -> int:
    number = 0
    for record in manifest["images"]:
        for value in (record["image_id"], PurePosixPath(record["path"]).name):
            match = re.fullmatch(rf"{prefix}[-_](\d+)(?:\.[^.]+)?", value)
            if match:
                number = max(number, int(match[1]))
    if out.exists():
        for path in _files(out):
            match = re.fullmatch(rf"{prefix}_(\d+)\.[^.]+", path.name, re.IGNORECASE)
            if match:
                number = max(number, int(match[1]))
    return number


def _atomic_manifest(path: Path, manifest: dict) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, prefix=".images-manifest-", suffix=".tmp",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            yaml.safe_dump(manifest, stream, sort_keys=False, allow_unicode=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def ingest(args) -> None:
    incoming = _check_path(args.incoming)
    out = _check_path(args.out or REPO_ROOT / "data/sample" / args.series / "images")
    if not incoming.is_dir():
        raise ValueError(f"incoming directory does not exist: {incoming}")
    if _within(incoming, out):
        raise ValueError("output must not equal or contain the incoming directory")
    if out.exists() and not out.is_dir():
        raise ValueError(f"output is not a directory: {out}")
    labels = _labels(args.labels)
    manifest_path = out / "IMAGES_MANIFEST.yaml"
    _check_path(manifest_path)
    manifest = _manifest(manifest_path, args.series)
    prefix = PREFIXES[args.series]
    number = _highest_number(out, manifest, prefix)
    seen = {record["sha256"] for record in manifest["images"]}
    accepted, skipped = [], []
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for path in sorted(_files(incoming, exclude=out), key=lambda item: item.relative_to(incoming).as_posix()):
        if path.suffix.lower() not in EXTENSIONS:
            continue
        filename = path.relative_to(incoming).as_posix()
        try:
            width, height = read_dimensions(path)
        except (OSError, ValueError, struct.error):
            skipped.append((filename, "unreadable_header"))
            continue
        if min(width, height) < args.min_side:
            skipped.append((filename, "too_small"))
            continue
        digest = hashlib.sha256()
        byte_size = 0
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
                byte_size += len(block)
        sha256 = digest.hexdigest()
        if sha256 in seen:
            skipped.append((filename, "duplicate"))
            continue
        row = labels.get(filename, {})
        category = row.get("category") or "other"
        number += 1
        relative = f"{category}/{prefix}_{number:04d}{path.suffix.lower()}"
        destination = out / relative
        if _check_path(destination) != destination or destination.exists():
            raise ValueError(f"destination already exists or traverses a link: {destination}")
        record = {
            "image_id": f"{prefix}-{number:04d}", "path": relative, "category": category,
            "characters": [name.strip() for name in row.get("characters", "").split(";") if name.strip()],
            "emotion": row.get("emotion") or None, "volume": row.get("volume") or None,
            "chapter": row.get("chapter") or None, "width": width, "height": height,
            "byte_size": byte_size, "sha256": sha256, "original_filename": filename,
            "source": row.get("source") or args.source, "rights_basis": row.get("rights_basis") or args.rights_basis,
            "notes": row.get("notes") or None, "ingested_at": timestamp,
        }
        accepted.append((path, destination, record))
        seen.add(sha256)
    print("APPLY" if args.apply else "DRY RUN (no files written)")
    for _, _, record in accepted:
        print(f"accepted: {record['original_filename']} -> {record['path']}")
    for filename, reason in skipped:
        print(f"skipped: {filename} ({reason})")
    print(f"accepted={len(accepted)} skipped={len(skipped)}")
    if not args.apply:
        return
    manifest["images"].extend(record for _, _, record in accepted)
    aggregate = {"total": len(manifest["images"]), "per_category": dict.fromkeys(CATEGORIES, 0),
                 "per_rights_basis": dict.fromkeys(RIGHTS_BASES, 0)}
    for record in manifest["images"]:
        aggregate["per_category"][record["category"]] += 1
        aggregate["per_rights_basis"][record["rights_basis"]] += 1
    manifest["aggregate"] = aggregate
    out.mkdir(parents=True, exist_ok=True)
    for path, destination, _ in accepted:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with path.open("rb") as source, destination.open("xb") as target:
            shutil.copyfileobj(source, target)
    _atomic_manifest(manifest_path, manifest)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", required=True, choices=PREFIXES)
    parser.add_argument("--incoming", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--source", default="")
    parser.add_argument("--rights-basis", choices=RIGHTS_BASES, default="unknown")
    parser.add_argument("--min-side", type=int, default=300)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.min_side < 1:
        parser.error("--min-side must be a positive integer")
    try:
        ingest(args)
    except (ValueError, csv.Error, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
