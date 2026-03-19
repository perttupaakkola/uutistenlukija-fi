#!/usr/bin/env python3
"""
Main Pipeline Runner — orchestrates scan → rewrite → publish.

Flags:
  --quick       Scan + rewrite + publish only (skip Hugo build). For frequent cron runs.
  --build-only  Run Hugo build only (no scanning/rewriting).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scanner import scan_all_feeds
from firehose import poll_firehose
from rewriter import rewrite_articles
from publisher import publish_articles, build_site
from dedup import filter_new_articles, mark_published
from image_gen import generate_images_for_articles


LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


def log_run(stage: str, data: dict):
    """Log pipeline run data."""
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(LOG_DIR, f"{timestamp}_{stage}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def run(quick: bool = False, build_only: bool = False):
    """Execute the pipeline.

    Args:
        quick: If True, skip the Hugo build step (scan + rewrite + publish only).
        build_only: If True, only run the Hugo build (no scanning/rewriting).
    """
    print("=" * 60)
    print(f"Uutistenlukija Pipeline — {datetime.now(timezone.utc).isoformat()}")
    if quick:
        print("  Mode: --quick (skip build)")
    elif build_only:
        print("  Mode: --build-only")
    print("=" * 60)

    if build_only:
        print("\n🔨 Hugo-sivuston rakennus...")
        success = build_site()
        if success:
            print("\n✅ Rakennus valmis!")
        else:
            print("\n❌ Rakennus epäonnistui.")
        return success

    # Step 1: Scan RSS feeds + Firehose
    print("\n📡 Vaihe 1: RSS-syötteiden skannaus...")
    rss_articles = scan_all_feeds()

    print("\n🔥 Vaihe 1b: Firehose-pollaus...")
    try:
        fh_articles = poll_firehose()
        print(f"[firehose] +{len(fh_articles)} articles from Firehose")
    except Exception as e:
        print(f"[firehose] Skipping (error): {e}")
        fh_articles = []

    # Merge: prefer RSS articles (already have richer metadata), Firehose fills gaps
    # Dedup by URL hash across both sets
    seen_url_hashes = {a.get("_url_hash") for a in rss_articles if a.get("_url_hash")}
    fh_new = [a for a in fh_articles if a.get("_url_hash") not in seen_url_hashes]
    articles = rss_articles + fh_new
    print(f"[pipeline] RSS: {len(rss_articles)} + Firehose new: {len(fh_new)} = {len(articles)} total")

    if not articles:
        print("❌ Ei artikkeleita löytynyt. Keskeytetään.")
        return False

    log_run("scanned", {"count": len(articles), "rss_count": len(rss_articles), "firehose_new": len(fh_new), "articles": articles})

    # Step 1b: Deduplication
    print("\n🔍 Vaihe 1b: Duplikaattien suodatus...")
    articles = filter_new_articles(articles)
    if not articles:
        print("ℹ️  Kaikki artikkelit on jo julkaistu. Ei uusia artikkeleita.")
        return True

    # Step 2: Rewrite with AI
    print(f"\n✍️  Vaihe 2: {len(articles)} artikkelin uudelleenkirjoitus...")
    try:
        rewritten = rewrite_articles(articles)
    except ValueError as e:
        print(f"❌ {e}")
        return False

    if not rewritten:
        print("❌ Uudelleenkirjoitus epäonnistui. Keskeytetään.")
        return False

    log_run("rewritten", {"count": len(rewritten), "articles": rewritten})

    # Step 2b: Generate header images (optional, failures don't block publishing)
    print(f"\n🖼️  Vaihe 2b: Kuvien generointi...")
    try:
        rewritten = generate_images_for_articles(rewritten)
        image_count = sum(1 for a in rewritten if a.get("image"))
        print(f"[image_gen] {image_count}/{len(rewritten)} artikkelia sai kuvan")
    except Exception as e:
        print(f"[image_gen] Kuvien generointi epäonnistui (artikkelit julkaistaan ilman kuvia): {e}")

    # Step 3: Publish
    print(f"\n📝 Vaihe 3: {len(rewritten)} artikkelin julkaisu...")
    created = publish_articles(rewritten)
    log_run("published", {"count": len(created), "files": created})

    # Mark published articles for deduplication
    mark_published(rewritten)

    if quick:
        print(f"\n✅ Valmis! {len(created)} artikkelia julkaistu (build ohitettu).")
        return True

    # Step 4: Build
    print("\n🔨 Vaihe 4: Hugo-sivuston rakennus...")
    success = build_site()

    if success:
        print(f"\n✅ Valmis! {len(created)} artikkelia julkaistu.")
    else:
        print("\n⚠️  Artikkelit julkaistu, mutta sivuston rakennus epäonnistui.")

    return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Uutistenlukija Pipeline")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Scan + rewrite + publish only, skip Hugo build (for frequent cron runs)",
    )
    parser.add_argument(
        "--build-only",
        action="store_true",
        help="Only run Hugo build (no scanning/rewriting)",
    )
    args = parser.parse_args()

    if args.quick and args.build_only:
        print("❌ Cannot use --quick and --build-only together.")
        sys.exit(1)

    success = run(quick=args.quick, build_only=args.build_only)
    sys.exit(0 if success else 1)
