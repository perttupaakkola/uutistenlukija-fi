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
import time
from datetime import datetime, timezone

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scanner import scan_all_feeds
from rewriter import rewrite_articles
from publisher import publish_articles, build_site
from dedup import filter_new_articles, mark_published
from image_gen import generate_images_for_articles


LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
METRICS_FILE = os.path.join(LOG_DIR, "metrics.json")

# Threshold: warn if any step exceeds this many seconds
SLOW_STEP_THRESHOLD_SEC = 300  # 5 minutes


def log_run(stage: str, data: dict):
    """Log pipeline run data."""
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(LOG_DIR, f"{timestamp}_{stage}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _time_step(name: str, fn, metrics: dict, *args, **kwargs):
    """Execute a function, measure its duration, and record in metrics."""
    t0 = time.monotonic()
    error = None
    result = None
    try:
        result = fn(*args, **kwargs)
    except Exception as e:
        error = str(e)
        raise
    finally:
        elapsed = round(time.monotonic() - t0, 2)
        step_info = {"duration_sec": elapsed}
        if error:
            step_info["error"] = error
        if elapsed > SLOW_STEP_THRESHOLD_SEC:
            step_info["slow"] = True
            print(f"  ⚠️  {name} took {elapsed:.1f}s (>{SLOW_STEP_THRESHOLD_SEC}s threshold)")
        else:
            print(f"  ⏱️  {name}: {elapsed:.1f}s")
        metrics["steps"][name] = step_info
    return result


def _append_metrics(metrics: dict):
    """Append run metrics to the metrics.json log file."""
    os.makedirs(LOG_DIR, exist_ok=True)
    existing = []
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, IOError):
            existing = []
    existing.append(metrics)
    # Keep last 200 runs to prevent unbounded growth
    existing = existing[-200:]
    with open(METRICS_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)


def run(quick: bool = False, build_only: bool = False, max_articles: int = 0):
    """Execute the pipeline.

    Args:
        quick: If True, skip the Hugo build step (scan + rewrite + publish only).
        build_only: If True, only run the Hugo build (no scanning/rewriting).
        max_articles: If > 0, limit to this many articles per run.
    """
    run_start = time.monotonic()
    metrics = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "build-only" if build_only else ("quick" if quick else "full"),
        "success": False,
        "article_count": 0,
        "steps": {},
        "errors": [],
    }

    print("=" * 60)
    print(f"Uutistenlukija Pipeline — {metrics['timestamp']}")
    if quick:
        print("  Mode: --quick (skip build)")
    elif build_only:
        print("  Mode: --build-only")
    print("=" * 60)

    if build_only:
        print("\n🔨 Hugo-sivuston rakennus...")
        try:
            success = _time_step("build", build_site, metrics)
        except Exception as e:
            metrics["errors"].append(f"build: {e}")
            success = False
        metrics["success"] = bool(success)
        metrics["total_duration_sec"] = round(time.monotonic() - run_start, 2)
        _append_metrics(metrics)
        if success:
            print("\n✅ Rakennus valmis!")
        else:
            print("\n❌ Rakennus epäonnistui.")
        return success

    # Step 1: Scan RSS feeds
    print("\n📡 Vaihe 1: RSS-syötteiden skannaus...")
    try:
        articles = _time_step("scanner", scan_all_feeds, metrics)
    except Exception as e:
        metrics["errors"].append(f"scanner: {e}")
        metrics["total_duration_sec"] = round(time.monotonic() - run_start, 2)
        _append_metrics(metrics)
        print(f"❌ Skannaus epäonnistui: {e}")
        return False

    if not articles:
        print("❌ Ei artikkeleita löytynyt. Keskeytetään.")
        metrics["errors"].append("scanner: no articles found")
        metrics["total_duration_sec"] = round(time.monotonic() - run_start, 2)
        _append_metrics(metrics)
        return False

    log_run("scanned", {"count": len(articles), "articles": articles})

    # Step 1b: Deduplication
    print("\n🔍 Vaihe 1b: Duplikaattien suodatus...")
    try:
        articles = _time_step("dedup", filter_new_articles, metrics, articles)
    except Exception as e:
        metrics["errors"].append(f"dedup: {e}")
        metrics["total_duration_sec"] = round(time.monotonic() - run_start, 2)
        _append_metrics(metrics)
        print(f"❌ Dedup epäonnistui: {e}")
        return False

    if not articles:
        print("ℹ️  Kaikki artikkelit on jo julkaistu. Ei uusia artikkeleita.")
        metrics["success"] = True
        metrics["total_duration_sec"] = round(time.monotonic() - run_start, 2)
        _append_metrics(metrics)
        return True

    # Apply max_articles limit after dedup
    if max_articles > 0 and len(articles) > max_articles:
        print(f"  📏 Rajoitetaan {len(articles)} → {max_articles} artikkelia (--max-articles)")
        articles = articles[:max_articles]

    if not articles:
        print("ℹ️  Ei artikkeleita rajoituksen jälkeen.")
        metrics["success"] = True
        metrics["total_duration_sec"] = round(time.monotonic() - run_start, 2)
        _append_metrics(metrics)
        return True

    metrics["article_count"] = len(articles)

    # Step 2: Rewrite with AI
    print(f"\n✍️  Vaihe 2: {len(articles)} artikkelin uudelleenkirjoitus...")
    try:
        rewritten = _time_step("rewriter", rewrite_articles, metrics, articles)
    except ValueError as e:
        print(f"❌ {e}")
        metrics["errors"].append(f"rewriter: {e}")
        metrics["total_duration_sec"] = round(time.monotonic() - run_start, 2)
        _append_metrics(metrics)
        return False

    if not rewritten:
        print("❌ Uudelleenkirjoitus epäonnistui. Keskeytetään.")
        metrics["errors"].append("rewriter: returned empty")
        metrics["total_duration_sec"] = round(time.monotonic() - run_start, 2)
        _append_metrics(metrics)
        return False

    log_run("rewritten", {"count": len(rewritten), "articles": rewritten})

    # Step 2b: Generate header images (optional, failures don't block publishing)
    print(f"\n🖼️  Vaihe 2b: Kuvien generointi...")
    try:
        rewritten = _time_step("image_gen", generate_images_for_articles, metrics, rewritten)
        image_count = sum(1 for a in rewritten if a.get("image"))
        metrics["steps"]["image_gen"]["image_count"] = image_count
        print(f"[image_gen] {image_count}/{len(rewritten)} artikkelia sai kuvan")
    except Exception as e:
        metrics["errors"].append(f"image_gen: {e}")
        print(f"[image_gen] Kuvien generointi epäonnistui (artikkelit julkaistaan ilman kuvia): {e}")

    # Step 3: Publish
    print(f"\n📝 Vaihe 3: {len(rewritten)} artikkelin julkaisu...")
    try:
        created = _time_step("publisher", publish_articles, metrics, rewritten)
    except Exception as e:
        metrics["errors"].append(f"publisher: {e}")
        metrics["total_duration_sec"] = round(time.monotonic() - run_start, 2)
        _append_metrics(metrics)
        print(f"❌ Julkaisu epäonnistui: {e}")
        return False

    log_run("published", {"count": len(created), "files": created})

    # Mark published articles for deduplication
    mark_published(rewritten)

    if quick:
        print(f"\n✅ Valmis! {len(created)} artikkelia julkaistu (build ohitettu).")
        metrics["success"] = True
        metrics["total_duration_sec"] = round(time.monotonic() - run_start, 2)
        _append_metrics(metrics)
        return True

    # Step 4: Build
    print("\n🔨 Vaihe 4: Hugo-sivuston rakennus...")
    try:
        success = _time_step("build", build_site, metrics)
    except Exception as e:
        metrics["errors"].append(f"build: {e}")
        success = False

    metrics["success"] = bool(success) if success is not None else False
    metrics["total_duration_sec"] = round(time.monotonic() - run_start, 2)
    _append_metrics(metrics)

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
    parser.add_argument(
        "--max-articles",
        type=int,
        default=0,
        help="Limit to N articles per run (0 = unlimited)",
    )
    args = parser.parse_args()

    if args.quick and args.build_only:
        print("❌ Cannot use --quick and --build-only together.")
        sys.exit(1)

    success = run(quick=args.quick, build_only=args.build_only, max_articles=args.max_articles)
    sys.exit(0 if success else 1)
