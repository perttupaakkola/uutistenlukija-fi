#!/usr/bin/env python3
"""Hash-pinned, reversible stale-outbox archiver. Defaults to dry-run."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))

from pipeline.publish_preflight import evaluate_publish_preflight  # noqa: E402

PLAN_SCHEMA = "uutistenlukija.stale_outbox_archive_plan.v1"
MANIFEST_SCHEMA = "uutistenlukija.stale_outbox_archive.v1"
OUTBOX_PREFIX = Path("pipeline/queues/staged/outbox")
ARCHIVE_PREFIX = Path("pipeline/queues/staged/failed_archive")
ARCHIVE_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(value: Any) -> Path:
    path = Path(str(value))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("path must be repository-relative")
    return path


def _archive_id(value: Any) -> str:
    archive_id = str(value)
    if not ARCHIVE_ID_PATTERN.fullmatch(archive_id):
        raise ValueError("invalid archive id")
    return archive_id


def _utc_timestamp(value: Any, *, label: str) -> tuple[datetime, str]:
    raw = str(value or "")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid {label}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{label} must be timezone-aware UTC")
    canonical = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return parsed.astimezone(timezone.utc), canonical


def _inside(root: Path, relative: Path, prefix: Path) -> Path:
    root = root.resolve()
    prefix_path = (root / prefix).resolve()
    candidate = (root / relative).resolve()
    if prefix_path != root and root not in prefix_path.parents:
        raise ValueError("required repository subtree escapes root")
    if candidate != prefix_path and prefix_path not in candidate.parents:
        raise ValueError("path escapes required repository subtree")
    return candidate


def _entry(root: Path, raw: Any, archive_id: str) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("archive entry must be an object")
    source = _relative(raw.get("source"))
    destination = _relative(raw.get("destination"))
    digest = str(raw.get("sha256") or "")
    record_time, record_time_text = _utc_timestamp(raw.get("record_time"), label="record_time")
    stale_before, stale_before_text = _utc_timestamp(raw.get("stale_before"), label="stale_before")
    if raw.get("record_time_field") != "completed_at" or record_time > stale_before:
        raise ValueError("invalid stale timestamp evidence")
    if source.parent != OUTBOX_PREFIX or source.suffix != ".json":
        raise ValueError("source must be an explicit staged outbox JSON")
    expected_destination = ARCHIVE_PREFIX / archive_id / "stale_outbox" / source.name
    if destination != expected_destination or destination.name != source.name:
        raise ValueError("destination is not bound to archive id and source basename")
    if not SHA256_PATTERN.fullmatch(digest):
        raise ValueError("invalid entry sha256")
    _inside(root, source, OUTBOX_PREFIX)
    _inside(root, destination, ARCHIVE_PREFIX / archive_id / "stale_outbox")
    return {
        "source": source.as_posix(), "destination": destination.as_posix(), "sha256": digest,
        "record_time_field": "completed_at", "record_time": record_time_text,
        "stale_before": stale_before_text,
    }


def _validated_entries(root: Path, raw_entries: Any, archive_id: str, *, label: str) -> list[dict[str, str]]:
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError(f"{label} must be a non-empty list")
    entries = [_entry(root, raw, archive_id) for raw in raw_entries]
    sources = [entry["source"] for entry in entries]
    destinations = [entry["destination"] for entry in entries]
    if len(sources) != len(set(sources)) or len(destinations) != len(set(destinations)):
        raise ValueError(f"duplicate {label} path")
    return entries


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_plan(root: Path, plan_path: Path, archive_id: str) -> list[dict[str, str]]:
    archive_id = _archive_id(archive_id)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("invalid plan schema")
    stale_before, stale_before_text = _utc_timestamp(plan.get("stale_before"), label="stale_before")
    raw_entries = plan.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError("plan entries must be a non-empty list")
    entries = []
    seen = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise ValueError("plan entry must be an object")
        source = _relative(raw.get("source"))
        expected = str(raw.get("sha256") or "")
        if source.parent != OUTBOX_PREFIX or source.suffix != ".json" or not SHA256_PATTERN.fullmatch(expected):
            raise ValueError("source must be an explicit staged outbox JSON")
        if source.as_posix() in seen:
            raise ValueError("duplicate source")
        seen.add(source.as_posix())
        target = ARCHIVE_PREFIX / archive_id / "stale_outbox" / source.name
        source_path = _inside(root, source, OUTBOX_PREFIX)
        target_path = _inside(root, target, ARCHIVE_PREFIX / archive_id / "stale_outbox")
        if not source_path.is_file() or sha256(source_path) != expected:
            raise ValueError(f"source missing or hash drift: {source}")
        if target_path.exists():
            raise ValueError(f"archive collision: {target}")
        record = json.loads(source_path.read_text(encoding="utf-8"))
        record_time, record_time_text = _utc_timestamp(record.get("completed_at"), label="completed_at")
        if record_time > stale_before:
            raise ValueError(f"record is newer than stale_before: {source}")
        if evaluate_publish_preflight(record).action == "publish":
            raise ValueError(f"publish-eligible packet cannot be archived: {source}")
        entries.append({
            "source": source.as_posix(), "destination": target.as_posix(), "sha256": expected,
            "record_time_field": "completed_at", "record_time": record_time_text,
            "stale_before": stale_before_text,
        })
    return sorted(entries, key=lambda entry: entry["source"])


def apply_plan(root: Path, plan_path: Path, archive_id: str, *, apply: bool = False) -> dict:
    archive_id = _archive_id(archive_id)
    entries = load_plan(root, plan_path, archive_id)
    manifest_path = root / ARCHIVE_PREFIX / archive_id / "stale_outbox-manifest.json"
    if apply and manifest_path.exists():
        raise ValueError("archive manifest already exists")
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "reversible": True,
        "reason": "stale_non_publish_eligible_outbox",
        "selection": "explicit_hash_pinned_plan",
        "archive_id": archive_id,
        "stale_before": entries[0]["stale_before"],
        "status": "dry_run" if not apply else "applying",
        "entries": entries,
    }
    if not apply:
        return manifest
    _write_json(manifest_path, manifest)
    moved: list[dict[str, str]] = []
    try:
        for entry in entries:
            source = root / entry["source"]
            destination = root / entry["destination"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
            moved.append(entry)
            manifest["status"] = "partial"
            manifest["moved_entries"] = list(moved)
            _write_json(manifest_path, manifest)
            if sha256(destination) != entry["sha256"]:
                raise RuntimeError(f"destination hash mismatch: {entry['destination']}")
        manifest["status"] = "applied"
    except Exception:
        manifest["status"] = "partial"
        manifest["moved_entries"] = moved
        _write_json(manifest_path, manifest)
        raise
    _write_json(manifest_path, manifest)
    return {**manifest, "manifest": manifest_path.relative_to(root).as_posix()}


def rollback(root: Path, manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("reversible") is not True:
        raise ValueError("invalid rollback manifest")
    archive_id = _archive_id(manifest.get("archive_id"))
    expected_manifest = (root.resolve() / ARCHIVE_PREFIX / archive_id / "stale_outbox-manifest.json").resolve()
    if manifest_path.resolve() != expected_manifest:
        raise ValueError("manifest path is not bound to archive id")
    _, manifest_cutoff = _utc_timestamp(manifest.get("stale_before"), label="stale_before")
    all_entries = _validated_entries(root, manifest.get("entries"), archive_id, label="entries")
    if any(entry["stale_before"] != manifest_cutoff for entry in all_entries):
        raise ValueError("entry stale_before does not match manifest")
    status = manifest.get("status")
    if status == "applied":
        entries = all_entries
    elif status == "partial":
        entries = _validated_entries(root, manifest.get("moved_entries"), archive_id, label="moved_entries")
        if any(entry["stale_before"] != manifest_cutoff for entry in entries):
            raise ValueError("moved entry stale_before does not match manifest")
        allowed = {tuple(sorted(entry.items())) for entry in all_entries}
        if any(tuple(sorted(entry.items())) not in allowed for entry in entries):
            raise ValueError("moved_entries must be an exact subset of entries")
    else:
        raise ValueError("manifest status is not rollback eligible")
    for entry in entries:
        source = root / _relative(entry["source"])
        destination = root / _relative(entry["destination"])
        if source.exists():
            raise ValueError(f"rollback source collision: {entry['source']}")
        if not destination.is_file() or sha256(destination) != entry["sha256"]:
            raise ValueError(f"rollback destination missing or hash drift: {entry['destination']}")
    for entry in reversed(entries):
        source = root / entry["source"]
        destination = root / entry["destination"]
        source.parent.mkdir(parents=True, exist_ok=True)
        destination.rename(source)
    return {"schema": MANIFEST_SCHEMA, "status": "rolled_back", "restored": len(entries)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--archive-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", type=Path)
    args = parser.parse_args()
    if bool(args.plan) == bool(args.rollback):
        parser.error("provide exactly one of --plan or --rollback")
    result = rollback(args.root, args.rollback) if args.rollback else apply_plan(
        args.root, args.plan, args.archive_id, apply=args.apply
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
