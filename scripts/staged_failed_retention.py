#!/usr/bin/env python3
"""Archive stale staged failed queue records with a manifest.

Default is dry-run. There is intentionally no delete mode.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FAILED_DIR = ROOT / "pipeline" / "queues" / "staged" / "failed"
ARCHIVE_ROOT = ROOT / "pipeline" / "queues" / "staged" / "failed_archive"
DEFAULT_BUCKET = "stale_ready_expired"


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def failure_text(data: dict[str, Any]) -> str:
    failure = data.get("failure") or data.get("failure_reason") or data.get("reason") or ""
    if isinstance(failure, dict):
        return json.dumps(failure, ensure_ascii=False)
    return str(failure)


def normalize_reason(text: str) -> str:
    s = (text or "").lower()
    if "stale_ready_expired" in s or ("stale" in s and "ready" in s and "expired" in s):
        return "stale_ready_expired"
    if "duplicate" in s:
        return "duplicate"
    if "content too short" in s or "too short" in s:
        return "content_too_short"
    if "insufficient_confidence" in s or "insufficient confidence" in s or "confidence" in s:
        return "insufficient_confidence"
    if "quality" in s:
        return "quality_gate"
    if "thin" in s:
        return "thin_source"
    if "timeout" in s or "context overflow" in s or "runtime" in s or "exception" in s:
        return "writer_runtime"
    return "unknown"


def record_time(path: Path, data: dict[str, Any]) -> datetime:
    for key in ("failed_at", "queued_at", "created_at", "completed_at"):
        value = data.get(key)
        if isinstance(value, str) and value:
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def collect(max_age_hours: float, bucket: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    now = datetime.now(timezone.utc)
    matches: list[dict[str, Any]] = []
    buckets: dict[str, int] = {}
    for path in sorted(FAILED_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
        data = read_json(path)
        reason = normalize_reason(failure_text(data))
        buckets[reason] = buckets.get(reason, 0) + 1
        age_hours = max(0.0, (now - record_time(path, data)).total_seconds() / 3600)
        if reason != bucket or age_hours < max_age_hours:
            continue
        st = path.stat()
        matches.append({"file": path.name, "source_path": str(path.relative_to(ROOT)), "size_bytes": st.st_size, "age_hours": round(age_hours, 2), "bucket": reason})
    return matches, buckets


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive stale staged failed queue records with manifest (no delete mode).")
    parser.add_argument("--max-age-hours", type=float, default=120.0)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET, help="Only archive this normalized bucket")
    parser.add_argument("--execute", action="store_true", help="Actually move files into archive batch directory")
    parser.add_argument("--archive-root", type=Path, default=ARCHIVE_ROOT)
    args = parser.parse_args()
    if args.max_age_hours <= 0:
        raise SystemExit("--max-age-hours must be positive")
    if args.bucket != DEFAULT_BUCKET:
        raise SystemExit("Only stale_ready_expired is allowed for this initial archive-only procedure")
    generated_at = datetime.now(timezone.utc).isoformat()
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    batch_dir = args.archive_root / batch_id
    matches, buckets = collect(args.max_age_hours, args.bucket)
    total_bytes = sum(item["size_bytes"] for item in matches)
    manifest = {
        "mode": "archive" if args.execute else "dry_run_no_moves",
        "generated_at": generated_at,
        "repo_root": str(ROOT),
        "failed_dir": str(FAILED_DIR.relative_to(ROOT)),
        "archive_dir": str(batch_dir.relative_to(ROOT)),
        "max_age_hours": args.max_age_hours,
        "bucket": args.bucket,
        "matched_count": len(matches),
        "matched_bytes": total_bytes,
        "queue_buckets_before": dict(sorted(buckets.items())),
        "restore_note": "To restore, move files listed in items[].archive_path (or archive_dir/file) back to pipeline/queues/staged/failed/ after confirming no filename conflict.",
        "items": matches,
    }
    if args.execute and matches:
        batch_dir.mkdir(parents=True, exist_ok=False)
        for item in matches:
            src = ROOT / item["source_path"]
            dest = batch_dir / item["file"]
            shutil.move(str(src), str(dest))
            item["archive_path"] = str(dest.relative_to(ROOT))
        manifest["moved_count"] = len(matches)
        manifest["moved_bytes"] = total_bytes
    else:
        manifest["moved_count"] = 0
        manifest["moved_bytes"] = 0
    manifest_dir = args.archive_root / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{batch_id}_{args.bucket}_{int(args.max_age_hours)}h.json"
    manifest["manifest_path"] = str(manifest_path.relative_to(ROOT))
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {k: manifest[k] for k in ("mode", "manifest_path", "archive_dir", "matched_count", "matched_bytes", "moved_count", "moved_bytes", "max_age_hours", "bucket", "restore_note")}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
