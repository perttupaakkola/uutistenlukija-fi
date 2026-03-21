"""
safe_delete.py — Tier-aware article deletion guard.

ANY script that removes articles from content/posts/ MUST use this module.
Tier 1 articles (Yle, BBC, Reuters, HS, IS, Iltalehti, MTV…) cannot be
auto-deleted. They are quarantined to pipeline/quarantine/ for manual review.

Usage:
    from safe_delete import safe_delete_articles
    deleted, quarantined = safe_delete_articles(paths, reason="duplicate")
"""

import os
import re
import shutil
from datetime import datetime, timezone
from typing import List, Tuple

_CONTENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "content", "posts")
_QUARANTINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quarantine")


def _read_source_tier(filepath: str) -> int:
    """Read source_tier from article frontmatter. Returns 2 if not found."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read(2000)  # only need frontmatter
        m = re.search(r"^source_tier:\s*(\d+)", content, re.MULTILINE)
        if m:
            return int(m.group(1))
    except OSError:
        pass
    return 2  # default to standard if unreadable


def _read_source_name(filepath: str) -> str:
    """Read source_name from article frontmatter."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read(2000)
        m = re.search(r'^source_name:\s*"?([^"\n]+)"?', content, re.MULTILINE)
        if m:
            return m.group(1).strip()
    except OSError:
        pass
    return "unknown"


def safe_delete_articles(
    paths: List[str],
    reason: str = "unspecified",
    dry_run: bool = False,
) -> Tuple[List[str], List[str]]:
    """
    Delete articles, protecting Tier 1 sources.

    Tier 1 articles are moved to pipeline/quarantine/ (NOT deleted).
    A quarantine manifest is written alongside each file.
    Tier 2/3 articles are deleted outright.

    Returns:
        (deleted, quarantined) — lists of file paths
    """
    deleted: List[str] = []
    quarantined: List[str] = []

    os.makedirs(_QUARANTINE_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    for path in paths:
        if not os.path.isabs(path):
            path = os.path.join(_CONTENT_DIR, path)

        if not os.path.exists(path):
            print(f"[safe_delete] File not found, skipping: {path}")
            continue

        tier = _read_source_tier(path)
        source = _read_source_name(path)
        basename = os.path.basename(path)

        if tier == 1:
            # PROTECTED — quarantine, never auto-delete
            q_name = f"{ts}_{basename}"
            q_path = os.path.join(_QUARANTINE_DIR, q_name)
            manifest_path = q_path + ".reason"
            if not dry_run:
                shutil.move(path, q_path)
                with open(manifest_path, "w") as mf:
                    mf.write(
                        f"file: {basename}\n"
                        f"source: {source}\n"
                        f"tier: {tier}\n"
                        f"reason: {reason}\n"
                        f"quarantined_at: {datetime.now(timezone.utc).isoformat()}\n"
                        f"\nThis is a TIER 1 (protected) article. Manual review required before permanent deletion.\n"
                    )
            print(f"[safe_delete] 🔒 QUARANTINED (T1/{source}): {basename} → {q_name}  reason={reason}")
            quarantined.append(path)
        else:
            # Tier 2/3 — safe to delete
            if not dry_run:
                os.remove(path)
            print(f"[safe_delete] 🗑️  DELETED (T{tier}/{source}): {basename}  reason={reason}")
            deleted.append(path)

    if dry_run:
        print(f"[safe_delete] DRY RUN — would delete {len(deleted)}, quarantine {len(quarantined)}")
    else:
        print(f"[safe_delete] Done — deleted {len(deleted)}, quarantined {len(quarantined)}")

    return deleted, quarantined


def list_quarantine() -> List[dict]:
    """Return list of quarantined articles with their reasons."""
    if not os.path.isdir(_QUARANTINE_DIR):
        return []
    results = []
    for fname in sorted(os.listdir(_QUARANTINE_DIR)):
        if fname.endswith(".reason"):
            continue
        reason_path = os.path.join(_QUARANTINE_DIR, fname + ".reason")
        entry = {"file": fname, "path": os.path.join(_QUARANTINE_DIR, fname)}
        if os.path.exists(reason_path):
            with open(reason_path) as rf:
                entry["reason_text"] = rf.read()
        results.append(entry)
    return results


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="Tier-aware article deletion")
    parser.add_argument("paths", nargs="*", help="Article file paths to delete")
    parser.add_argument("--reason", default="manual", help="Deletion reason")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list-quarantine", action="store_true", help="Show quarantined articles")
    args = parser.parse_args()

    if args.list_quarantine:
        items = list_quarantine()
        if not items:
            print("Quarantine is empty.")
        for item in items:
            print(f"\n── {item['file']}")
            print(item.get("reason_text", "(no reason file)"))
        sys.exit(0)

    if not args.paths:
        print("No paths provided. Use --list-quarantine to see quarantined articles.")
        sys.exit(0)

    safe_delete_articles(args.paths, reason=args.reason, dry_run=args.dry_run)
