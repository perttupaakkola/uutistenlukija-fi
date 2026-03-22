#!/usr/bin/env python3
"""
content_backup.py — daily backup of all published articles to JSON

Exports: title, slug, date, categories, tags, image, image_thumb, description, body
Output:  backups/content-YYYY-MM-DD.json
Retains: last 7 daily backups, rotates older ones

Usage:
    python3 pipeline/content_backup.py [--dry-run] [--output PATH]

Cron (daily 02:00 UTC):
    0 2 * * * cd /path/to/project && python3 pipeline/content_backup.py >> pipeline/logs/content-backup.log 2>&1
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent          # pipeline/
PROJECT_DIR  = SCRIPT_DIR.parent
CONTENT_DIR  = PROJECT_DIR / "content" / "posts"
BACKUP_DIR   = PROJECT_DIR / "backups"
KEEP_DAYS    = 7
BACKUP_PREFIX = "content-"


# ── Frontmatter parser ────────────────────────────────────────────────────────

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split --- frontmatter --- from body. Returns (meta_dict, body_str)."""
    meta: dict = {}
    body = text

    m = re.match(r'^---\s*\n(.*?)\n---\s*\n?(.*)', text, re.DOTALL)
    if not m:
        return meta, body

    fm_raw = m.group(1)
    body   = m.group(2).strip()

    # Very simple YAML-ish parser (no dependency on pyyaml)
    # Handles: key: value, key: "value", lists (- item), multi-line strings skipped
    current_key = None
    list_buffer: list[str] = []

    def flush_list():
        nonlocal current_key, list_buffer
        if current_key and list_buffer:
            meta[current_key] = list_buffer[:]
        current_key = None
        list_buffer = []

    for line in fm_raw.splitlines():
        # List item
        if re.match(r'^\s+-\s+', line):
            val = re.sub(r'^\s+-\s+', '', line).strip().strip('"\'')
            if current_key is not None:
                list_buffer.append(val)
            continue

        # Key: value
        kv = re.match(r'^(\w[\w_-]*)\s*:\s*(.*)', line)
        if kv:
            flush_list()
            key   = kv.group(1)
            value = kv.group(2).strip().strip('"\'')
            if value == '':
                # Start of a list or nested block
                current_key = key
                list_buffer = []
            else:
                # Booleans
                if value.lower() == 'true':
                    value = True
                elif value.lower() == 'false':
                    value = False
                meta[key] = value

    flush_list()
    return meta, body


# ── Article loader ────────────────────────────────────────────────────────────

def load_articles(content_dir: Path) -> list[dict]:
    articles = []
    skipped  = 0

    for path in sorted(content_dir.glob("**/*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            meta, body = _parse_frontmatter(text)

            # Skip drafts and index files
            if meta.get("draft") is True:
                skipped += 1
                continue
            if path.name.startswith("_index"):
                skipped += 1
                continue

            slug = path.stem  # filename without .md

            article = {
                "slug":         slug,
                "title":        meta.get("title", ""),
                "date":         meta.get("date", ""),
                "categories":   meta.get("categories", []),
                "tags":         meta.get("tags", []),
                "author":       meta.get("author", ""),
                "description":  meta.get("description", ""),
                "image":        meta.get("image", ""),
                "image_thumb":  meta.get("image_thumb", ""),
                "image_alt":    meta.get("image_alt", ""),
                "image_credit": meta.get("image_credit", ""),
                "draft":        meta.get("draft", False),
                "body":         body,
            }
            articles.append(article)
        except Exception as e:
            print(f"[content-backup] WARN: skipping {path.name}: {e}", file=sys.stderr)
            skipped += 1

    print(f"[content-backup] Loaded {len(articles)} articles ({skipped} skipped)")
    return articles


# ── Rotation ──────────────────────────────────────────────────────────────────

def rotate_backups(backup_dir: Path, keep: int = KEEP_DAYS) -> int:
    """Delete backups older than `keep` days. Returns count deleted."""
    pattern = re.compile(rf"^{re.escape(BACKUP_PREFIX)}(\d{{4}}-\d{{2}}-\d{{2}})\.json$")
    backups = []
    for f in backup_dir.glob(f"{BACKUP_PREFIX}*.json"):
        m = pattern.match(f.name)
        if m:
            backups.append((m.group(1), f))

    backups.sort(key=lambda x: x[0], reverse=True)  # newest first
    deleted = 0
    for date_str, path in backups[keep:]:
        print(f"[content-backup] Rotating old backup: {path.name}")
        path.unlink()
        deleted += 1
    return deleted


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Daily content backup to JSON.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and count articles but don't write backup")
    parser.add_argument("--output", default="",
                        help="Override output file path")
    args = parser.parse_args()

    now      = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = BACKUP_DIR / f"{BACKUP_PREFIX}{date_str}.json"

    if not CONTENT_DIR.exists():
        print(f"[content-backup] ERROR: content dir not found: {CONTENT_DIR}", file=sys.stderr)
        return 1

    articles = load_articles(CONTENT_DIR)

    if not articles:
        print("[content-backup] WARNING: 0 articles found — nothing to back up", file=sys.stderr)
        return 1

    backup = {
        "generated_at":   now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "article_count":  len(articles),
        "source_dir":     str(CONTENT_DIR),
        "articles":       articles,
    }

    if args.dry_run:
        size_est = len(json.dumps(backup))
        print(f"[content-backup] Dry run — would write {len(articles)} articles "
              f"(~{size_est // 1024} KB) to {out_path}")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(backup, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    size_kb = out_path.stat().st_size // 1024
    print(f"[content-backup] Wrote {len(articles)} articles ({size_kb} KB) → {out_path}")

    deleted = rotate_backups(BACKUP_DIR)
    if deleted:
        print(f"[content-backup] Rotated {deleted} old backup(s) (keeping last {KEEP_DAYS})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
