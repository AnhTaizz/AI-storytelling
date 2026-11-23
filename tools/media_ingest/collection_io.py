"""Shared file helpers for the local image collections: confined paths, atomic CSV/JSON
writes and manifest aggregates."""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from tools.media_ingest import ingest_local_images as local


def save_report(path: Path, result: dict) -> None:
    """Write JSON atomically, so readers and interrupted runs see a complete file."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(result, indent=2), encoding="utf-8")
    for attempt in range(10):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            # Windows readers/indexers may briefly hold a destination handle.
            if attempt == 9:
                raise
            time.sleep(0.1 * (attempt + 1))


def safe(root: Path, relative: str) -> Path:
    """Resolve a path that must stay strictly inside the collection root."""
    path = (root / relative).resolve()
    if path == root.resolve() or not path.is_relative_to(root.resolve()):
        raise ValueError("path outside collection")
    return path


def write_csv(path: Path, rows: list[dict]) -> None:
    """Write rows atomically as UTF-8 CSV with a BOM; nothing is written for no rows."""
    if not rows:
        return
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def aggregate(manifest: dict) -> None:
    """Recompute the manifest's per-category and per-rights-basis totals in place."""
    result = {"total": len(manifest["images"]), "per_category": dict.fromkeys(local.CATEGORIES, 0),
              "per_rights_basis": dict.fromkeys(local.RIGHTS_BASES, 0)}
    for record in manifest["images"]:
        result["per_category"][record["category"]] += 1
        result["per_rights_basis"][record["rights_basis"]] += 1
    manifest["aggregate"] = result
