#!/usr/bin/env python3
"""
backfill_images.py — Backfill hero images for articles missing front matter `image` field.

Strategy:
  1. Scan content/posts/*.md for articles missing `image`
  2. Try Unsplash first (hotlink, free, landscape-oriented)
  3. Fall back to Pexels if Unsplash returns nothing (downloaded locally)
  4. Update front matter in-place
  5. Log every result to pipeline/logs/image_backfill.json

Usage:
    python3 backfill_images.py                   # full run
    python3 backfill_images.py --dry-run         # preview without writing
    python3 backfill_images.py --limit 20        # first N missing articles
    python3 backfill_images.py --source unsplash # force Unsplash only
    python3 backfill_images.py --source pexels   # force Pexels only
    python3 backfill_images.py --offset 100      # skip first N missing (for resuming)

Rate limits:
    Unsplash: 50 req/hr (demo) — script batches 20 at a time, 2s between requests
    Pexels:   200 req/hr       — each query covers up to 80 results (in-memory cache)

Requirements:
    UNSPLASH_ACCESS_KEY and/or PEXELS_API_KEY env vars (loaded from pipeline/.env)
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Load .env from pipeline dir
_ENV_FILE = Path(__file__).parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip('"\''))

# Import existing image modules
sys.path.insert(0, str(Path(__file__).parent))
import unsplash as _unsplash
import pexels as _pexels

CONTENT_DIR = Path(__file__).parent.parent / "content" / "posts"
LOGS_DIR = Path(__file__).parent / "logs"
BACKFILL_LOG = LOGS_DIR / "image_backfill.json"

BATCH_SIZE = 20         # articles per batch
BATCH_PAUSE = 2.0       # seconds between batches (rate limit headroom)
REQUEST_DELAY = 1.5     # seconds between individual API calls within a batch


# ── Front matter helpers ──────────────────────────────────────────────────────

def _parse_fm(text: str) -> tuple[dict, str, str]:
    """Return (meta_dict, fm_block, body)."""
    if not text.startswith("---"):
        return {}, "", text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, "", text
    fm_block = text[3:end]
    body = text[end + 4:].strip()
    meta: dict = {}
    current_list_key = None
    for line in fm_block.splitlines():
        if re.match(r"^\s{2,}- ", line):
            if current_list_key:
                item = re.sub(r"^\s+-\s+", "", line).strip().strip('"\'')
                meta.setdefault(current_list_key, []).append(item)
            continue
        m = re.match(r'^(\w[\w_-]*):\s*(.*)', line)
        if m:
            current_list_key = None
            key, val = m.group(1), m.group(2).strip().strip('"\'')
            if val == "":
                current_list_key = key
                meta[key] = []
            elif val.lower() == "true":
                meta[key] = True
            elif val.lower() == "false":
                meta[key] = False
            else:
                meta[key] = val
    return meta, fm_block, body


def _inject_image_fields(text: str, image_data: dict) -> str:
    """Inject image front matter fields into article text.

    Inserts after the `description:` line (or `categories:` block, or title).
    All fields are written cleanly even if they already exist (overwrite).
    """
    image = image_data.get("url") or image_data.get("local_path", "")
    image_alt = image_data.get("alt", "")[:125]
    image_credit = image_data.get("credit", "")
    image_source = image_data.get("image_source_url", "") or image_data.get("pexels_url", "") or image_data.get("photo_page", "")
    image_thumb = image_data.get("thumb_url") or image_data.get("thumb_path") or image

    # Build insertion block
    new_fields = [
        f'image: "{image}"',
        f'image_alt: "{image_alt}"',
        f'image_credit: "{image_credit}"',
        f'image_source_url: "{image_source}"',
        f'image_thumb: "{image_thumb}"',
    ]

    # Remove any existing image_* fields first to avoid duplicates
    cleaned = re.sub(r'^image(?:_\w+)?:.*\n?', '', text, flags=re.MULTILINE)

    # Find insertion point: after description line if it exists
    insertion_marker = None
    for pattern in [r'^description:.*$', r'^categories:', r'^author:', r'^title:.*$']:
        m = re.search(pattern, cleaned, re.MULTILINE)
        if m:
            insertion_marker = m.end()
            break

    if insertion_marker is None:
        # Insert before closing ---
        end = cleaned.find("\n---", 3)
        insertion_marker = end if end != -1 else len(cleaned)

    inserted = cleaned[:insertion_marker] + "\n" + "\n".join(new_fields) + cleaned[insertion_marker:]
    return inserted


# ── Main backfill logic ───────────────────────────────────────────────────────

def find_missing_image_articles(limit: int | None = None, offset: int = 0) -> list[Path]:
    """Return list of article Paths that have no `image` front matter field."""
    all_files = sorted(CONTENT_DIR.glob("*.md"))
    missing = []
    for fpath in all_files:
        text = fpath.read_text(encoding="utf-8")
        meta, _, _ = _parse_fm(text)
        if meta.get("draft") is True:
            continue
        if not meta.get("image", "").strip():
            missing.append(fpath)

    missing = missing[offset:]
    if limit:
        missing = missing[:limit]
    return missing


def fetch_image(title: str, category: str, slug: str, source: str, content: str = "") -> dict | None:
    """Try Unsplash then Pexels. Returns image data dict or None."""
    if source in ("unsplash", "both"):
        result = _unsplash.fetch_image_for_article(
            title, category, content=content, inter_request_delay=0
        )
        if result:
            result["source"] = "unsplash"
            result["image_source_url"] = result.get("photo_page", "")
            return result

    if source in ("pexels", "both"):
        result = _pexels.fetch_image_for_article(
            title, category, content=content, slug=slug, download=True, inter_request_delay=0
        )
        if result and result.get("local_path"):
            result["source"] = "pexels"
            result["url"] = result["local_path"]
            result["image_source_url"] = result.get("pexels_url", "")
            return result

    return None


def load_log() -> list:
    if BACKFILL_LOG.exists():
        try:
            return json.loads(BACKFILL_LOG.read_text())
        except json.JSONDecodeError:
            pass
    return []


def save_log(entries: list) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    existing = load_log()
    existing.extend(entries)
    BACKFILL_LOG.write_text(json.dumps(existing, indent=2))


def run(
    dry_run: bool = False,
    limit: int | None = None,
    offset: int = 0,
    source: str = "both",
) -> dict:
    """Main backfill entry point."""
    missing = find_missing_image_articles(limit=limit, offset=offset)
    total = len(missing)

    print(f"🖼  Image backfill — {total} articles missing images (source={source}, dry_run={dry_run})")

    if not total:
        print("✅ Nothing to backfill.")
        return {"total": 0, "ok": 0, "failed": 0, "skipped": 0, "entries": []}

    ok_count = 0
    failed_count = 0
    log_entries = []

    # Process in batches
    for batch_start in range(0, total, BATCH_SIZE):
        batch = missing[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"\n── Batch {batch_num}/{total_batches} ({len(batch)} articles) ──")

        for fpath in batch:
            text = fpath.read_text(encoding="utf-8")
            meta, _, body = _parse_fm(text)

            title = meta.get("title", fpath.stem)
            cats = meta.get("categories", [])
            category = cats[0] if isinstance(cats, list) and cats else "Kotimaa"
            slug = fpath.stem

            entry = {
                "file": fpath.name,
                "title": title,
                "category": category,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": None,
                "source": None,
                "image_url": None,
            }

            if dry_run:
                # Query the API but don't write any files
                kw = _unsplash.extract_keywords(title, category)
                result = fetch_image(title, category, slug, source, content=body)
                time.sleep(REQUEST_DELAY)
                if result:
                    img_url = (result.get("url") or result.get("local_path") or "")[:80]
                    src = result.get("source", "?")
                    credit = result.get("credit", "")
                    print(f"  ✅ [{src:8s}] {title[:45]:45s}")
                    print(f"             kw='{kw}'")
                    print(f"             url={img_url}")
                    print(f"             credit={credit}")
                    entry["status"] = "dry_run_ok"
                    entry["image_url"] = img_url
                    ok_count += 1
                else:
                    print(f"  ❌ [no result] {title[:50]}")
                    print(f"             kw='{kw}'")
                    entry["status"] = "dry_run_failed"
                    failed_count += 1
                entry["keywords"] = kw
            else:
                result = fetch_image(title, category, slug, source, content=body)
                time.sleep(REQUEST_DELAY)

                if result:
                    new_text = _inject_image_fields(text, result)
                    fpath.write_text(new_text, encoding="utf-8")
                    ok_count += 1
                    entry["status"] = "ok"
                    entry["source"] = result.get("source")
                    entry["image_url"] = result.get("url") or result.get("local_path")
                    print(f"  ✅ [{result.get('source','?'):8s}] {fpath.name[:50]}")
                else:
                    failed_count += 1
                    entry["status"] = "failed"
                    print(f"  ❌ [no result ] {fpath.name[:50]}")

            log_entries.append(entry)

        # Pause between batches to stay well within rate limits
        if batch_start + BATCH_SIZE < total:
            print(f"  … pausing {BATCH_PAUSE}s before next batch")
            time.sleep(BATCH_PAUSE)

    if not dry_run:
        save_log(log_entries)

    result_summary = {
        "total": total,
        "ok": ok_count,
        "failed": failed_count,
        "skipped": 0,
        "entries": log_entries,
    }

    print(f"\n{'[dry-run] ' if dry_run else ''}Done: {ok_count} ok, {failed_count} failed / {total} total")
    return result_summary


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    source = "both"
    limit = None
    offset = 0

    if "--source" in args:
        idx = args.index("--source")
        if idx + 1 < len(args):
            source = args[idx + 1]
            if source not in ("unsplash", "pexels", "both"):
                print(f"Unknown source '{source}'. Use: unsplash, pexels, both", file=sys.stderr)
                sys.exit(1)

    if "--limit" in args:
        idx = args.index("--limit")
        if idx + 1 < len(args):
            limit = int(args[idx + 1])

    if "--offset" in args:
        idx = args.index("--offset")
        if idx + 1 < len(args):
            offset = int(args[idx + 1])

    run(dry_run=dry_run, limit=limit, offset=offset, source=source)


if __name__ == "__main__":
    main()
