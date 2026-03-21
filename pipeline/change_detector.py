"""
change_detector.py — Incremental build gating for Uutistenlukija pipeline.

Compares content/posts/*.md file hashes against a stored manifest to determine
whether a Hugo build is actually needed. Avoids full rebuilds on no-op runs.

Manifest format (pipeline/build_manifest.json):
{
  "last_build": "2026-03-21T14:00:00+00:00",
  "files": {
    "content/posts/some-article.md": {
      "hash": "abc123...",
      "mtime": 1742565600.0,
      "last_build": "2026-03-21T14:00:00+00:00"
    }
  }
}

Rules:
  - Build needed if any file hash changed since last build
  - Build needed if any file was added/deleted since last build
  - Build needed if > STALE_THRESHOLD_HOURS since last build (catches template changes)
  - Build skipped if none of the above apply
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from glob import glob
from typing import NamedTuple

# ── Config ──────────────────────────────────────────────────────────────────

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR  = os.path.dirname(_PIPELINE_DIR)

MANIFEST_FILE         = os.path.join(_PIPELINE_DIR, "build_manifest.json")
CONTENT_POSTS_GLOB    = os.path.join(_PROJECT_DIR, "content", "posts", "*.md")
STALE_THRESHOLD_HOURS = 6   # Force rebuild even if no file changes after this interval


# ── Types ────────────────────────────────────────────────────────────────────

class ChangeResult(NamedTuple):
    needs_build: bool
    reason: str          # human-readable explanation for logging


# ── Hashing ──────────────────────────────────────────────────────────────────

def _hash_file(path: str) -> str:
    """Return SHA-1 hex digest of file contents (fast enough for .md files)."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _rel(path: str) -> str:
    """Return path relative to project root for use as manifest key."""
    return os.path.relpath(path, _PROJECT_DIR)


# ── Manifest I/O ─────────────────────────────────────────────────────────────

def _load_manifest() -> dict:
    if os.path.exists(MANIFEST_FILE):
        try:
            with open(MANIFEST_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_build": None, "files": {}}


def _save_manifest(manifest: dict) -> None:
    try:
        with open(MANIFEST_FILE, "w") as f:
            json.dump(manifest, f, indent=2, default=str)
    except OSError as e:
        print(f"[change_detector] WARNING: could not write manifest: {e}")


# ── Public API ────────────────────────────────────────────────────────────────

def check_for_changes(new_articles_published: int = 0) -> ChangeResult:
    """
    Determine whether a Hugo build is needed.

    Args:
        new_articles_published: Number of articles published in the current run.
            If >0, build is always needed (new content to render).

    Returns:
        ChangeResult(needs_build, reason)
    """
    # New articles always need a build
    if new_articles_published > 0:
        return ChangeResult(True, f"{new_articles_published} new articles published")

    manifest = _load_manifest()
    now = datetime.now(timezone.utc)

    # Stale check — always rebuild after threshold regardless of file state
    last_build_str = manifest.get("last_build")
    if last_build_str:
        try:
            last_build = datetime.fromisoformat(last_build_str)
            age_hours = (now - last_build).total_seconds() / 3600
            if age_hours >= STALE_THRESHOLD_HOURS:
                return ChangeResult(
                    True,
                    f"stale: {age_hours:.1f}h since last build (threshold {STALE_THRESHOLD_HOURS}h)"
                )
        except ValueError:
            pass
    else:
        # Never built — build now
        return ChangeResult(True, "no previous build recorded")

    # File change detection
    stored = manifest.get("files", {})
    current_files = {_rel(p): p for p in glob(CONTENT_POSTS_GLOB)}

    # Added files
    added = set(current_files) - set(stored)
    if added:
        sample = sorted(added)[:3]
        return ChangeResult(True, f"{len(added)} new file(s): {', '.join(sample)}")

    # Deleted files
    deleted = set(stored) - set(current_files)
    if deleted:
        sample = sorted(deleted)[:3]
        return ChangeResult(True, f"{len(deleted)} deleted file(s): {', '.join(sample)}")

    # Modified files (hash check — only if mtime changed to avoid reading every file)
    for rel_path, abs_path in current_files.items():
        try:
            current_mtime = os.path.getmtime(abs_path)
        except OSError:
            continue
        stored_entry = stored.get(rel_path, {})
        if current_mtime != stored_entry.get("mtime"):
            # mtime changed — check hash to confirm actual content change
            try:
                current_hash = _hash_file(abs_path)
            except OSError:
                continue
            if current_hash != stored_entry.get("hash"):
                return ChangeResult(True, f"modified: {rel_path}")

    return ChangeResult(False, "no changes detected since last build")


def record_build() -> None:
    """
    Update the manifest after a successful Hugo build.
    Snapshots all current content/posts/*.md hashes and mtimes.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    files: dict = {}

    for abs_path in glob(CONTENT_POSTS_GLOB):
        rel_path = _rel(abs_path)
        try:
            files[rel_path] = {
                "hash":       _hash_file(abs_path),
                "mtime":      os.path.getmtime(abs_path),
                "last_build": now_iso,
            }
        except OSError:
            pass

    manifest = {
        "last_build": now_iso,
        "files": files,
    }
    _save_manifest(manifest)


def get_last_build() -> str | None:
    """Return ISO timestamp of last recorded build, or None."""
    return _load_manifest().get("last_build")


def invalidate() -> None:
    """Force next check to trigger a rebuild by clearing last_build."""
    manifest = _load_manifest()
    manifest["last_build"] = None
    _save_manifest(manifest)
    print("[change_detector] manifest invalidated — next run will force rebuild")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"

    if cmd == "check":
        result = check_for_changes()
        status = "BUILD" if result.needs_build else "SKIP"
        print(f"[{status}] {result.reason}")
        sys.exit(0 if result.needs_build else 2)   # 0=build, 2=skip, 1=error

    elif cmd == "record":
        record_build()
        manifest = _load_manifest()
        n = len(manifest.get("files", {}))
        print(f"[change_detector] manifest updated: {n} files, last_build={manifest['last_build']}")

    elif cmd == "invalidate":
        invalidate()

    elif cmd == "status":
        manifest = _load_manifest()
        lb = manifest.get("last_build", "never")
        n  = len(manifest.get("files", {}))
        print(f"last_build : {lb}")
        print(f"tracked    : {n} files")
        if lb and lb != "never":
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(lb)).total_seconds()
                print(f"age        : {age/3600:.1f}h")
            except ValueError:
                pass
        result = check_for_changes()
        print(f"verdict    : {'BUILD' if result.needs_build else 'SKIP'} — {result.reason}")

    else:
        print("Usage: change_detector.py check|record|invalidate|status")
        sys.exit(1)
