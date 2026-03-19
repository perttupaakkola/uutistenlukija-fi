#!/usr/bin/env python3
"""
Main Pipeline Runner — orchestrates scan → rewrite → publish.

Flags:
  --quick       Scan + rewrite + publish only (skip Hugo build). For frequent cron runs.
  --build-only  Run Hugo build only (no scanning/rewriting).

Per-step timeout guard: each step has a configurable max runtime. If exceeded,
the step is killed and marked as timed_out. Optional steps (image_gen, research)
are skipped gracefully; mandatory steps (rewriter) abort the pipeline.

Step timeouts (configurable via STEP_TIMEOUTS):
  - scanner:   10 min
  - firehose:  10 min
  - dedup:      5 min
  - research:  10 min
  - rewriter:  10 min
  - image_gen: 45 min  ← dominant bottleneck, optional
  - publisher:  5 min
  - build:      5 min
"""

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scanner import scan_all_feeds
from firehose import poll_firehose
from research import enrich_with_research
from rewriter import rewrite_articles
from publisher import publish_articles, build_site
from dedup import filter_new_articles, check_published_duplicates, mark_published
from image_gen import generate_images_for_articles


LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
METRICS_FILE = os.path.join(LOG_DIR, "metrics.json")
METRICS_MAX_RUNS = 200

# Per-step timeouts in seconds. Override here to tune.
STEP_TIMEOUTS = {
    "scanner":   600,   # 10 min
    "firehose":  600,   # 10 min
    "dedup":     300,   #  5 min
    "research":  600,   # 10 min
    "rewriter":  600,   # 10 min
    "image_gen": 2700,  # 45 min — image gen is slow by design
    "publisher": 300,   #  5 min
    "build":     300,   #  5 min
}


# ---------------------------------------------------------------------------
# Timeout guard
# ---------------------------------------------------------------------------

class StepTimeoutError(Exception):
    """Raised when a pipeline step exceeds its allowed runtime."""


def _handle_sigalrm(signum, frame):
    raise StepTimeoutError("Step exceeded timeout")


def run_step(name: str, fn, *args, **kwargs):
    """
    Run a pipeline step with a configurable timeout.

    Returns:
        (result, duration_sec, timed_out)
        - result:     return value of fn, or None if timed out / errored
        - duration_sec: wall-clock seconds the step ran
        - timed_out:  True if the step was killed by the timeout guard
    """
    timeout = STEP_TIMEOUTS.get(name, 600)
    start = time.monotonic()
    timed_out = False
    result = None

    old_handler = signal.signal(signal.SIGALRM, _handle_sigalrm)
    signal.alarm(timeout)
    try:
        result = fn(*args, **kwargs)
    except StepTimeoutError:
        timed_out = True
        elapsed = time.monotonic() - start
        print(f"⏱️  [{name}] Timeout after {elapsed:.0f}s (limit {timeout}s) — skipping step")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

    duration = time.monotonic() - start
    return result, duration, timed_out


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def log_run(stage: str, data: dict):
    """Write a named stage snapshot to logs/ (scanned / rewritten / published)."""
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(LOG_DIR, f"{timestamp}_{stage}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def append_metrics(record: dict):
    """Append a run record to metrics.json, capping at METRICS_MAX_RUNS."""
    os.makedirs(LOG_DIR, exist_ok=True)
    runs = []
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, "r", encoding="utf-8") as f:
                runs = json.load(f)
            if not isinstance(runs, list):
                runs = []
        except (json.JSONDecodeError, IOError):
            runs = []

    runs.append(record)
    # Keep only the most recent N runs
    if len(runs) > METRICS_MAX_RUNS:
        runs = runs[-METRICS_MAX_RUNS:]

    with open(METRICS_FILE, "w", encoding="utf-8") as f:
        json.dump(runs, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run(quick: bool = False, build_only: bool = False, firehose_only: bool = False):
    """Execute the pipeline.

    Args:
        quick:         Skip Hugo build (scan + rewrite + publish only).
        build_only:    Only run Hugo build (no scanning/rewriting).
        firehose_only: Poll Firehose only (skip RSS + build).
    """
    pipeline_start = time.monotonic()
    run_timestamp = datetime.now(timezone.utc).isoformat()
    step_metrics = {}   # step_name → {duration_sec, timed_out, error}
    run_errors = []

    print("=" * 60)
    print(f"Uutistenlukija Pipeline — {run_timestamp}")
    if quick:
        print("  Mode: --quick (skip build)")
    elif build_only:
        print("  Mode: --build-only")
    elif firehose_only:
        print("  Mode: --firehose-only")
    print("=" * 60)

    if build_only:
        print("\n🔨 Hugo-sivuston rakennus...")
        result, dur, timed_out = run_step("build", build_site)
        step_metrics["build"] = {"duration_sec": dur, "timed_out": timed_out}
        if timed_out or not result:
            print("\n❌ Rakennus epäonnistui.")
            return False
        print("\n✅ Rakennus valmis!")
        return True

    # ------------------------------------------------------------------
    # Step 1: Scan sources
    # ------------------------------------------------------------------
    rss_articles = []
    fh_articles = []
    fh_new = []

    if firehose_only:
        print("\n🔥 Vaihe 1: Firehose-pollaus (RSS ohitettu)...")
        fh_articles, dur, timed_out = run_step("firehose", poll_firehose)
        step_metrics["firehose"] = {"duration_sec": dur, "timed_out": timed_out}
        if timed_out or fh_articles is None:
            fh_articles = []
        articles = fh_articles
        print(f"[pipeline] Firehose: {len(articles)} articles")
    else:
        print("\n📡 Vaihe 1: RSS-syötteiden skannaus...")
        rss_result, dur, timed_out = run_step("scanner", scan_all_feeds)
        step_metrics["scanner"] = {"duration_sec": dur, "timed_out": timed_out}
        if timed_out or rss_result is None:
            if timed_out:
                run_errors.append("scanner: timed out")
            rss_articles = []
        else:
            rss_articles = rss_result

        print("\n🔥 Vaihe 1b: Firehose-pollaus...")
        fh_result, dur, timed_out = run_step("firehose", poll_firehose)
        step_metrics["firehose"] = {"duration_sec": dur, "timed_out": timed_out}
        if timed_out or fh_result is None:
            print(f"[firehose] Skipping (timed out or error)")
            fh_articles = []
        else:
            fh_articles = fh_result
            print(f"[firehose] +{len(fh_articles)} articles from Firehose")

        seen_url_hashes = {a.get("_url_hash") for a in rss_articles if a.get("_url_hash")}
        fh_new = [a for a in fh_articles if a.get("_url_hash") not in seen_url_hashes]
        articles = rss_articles + fh_new
        print(f"[pipeline] RSS: {len(rss_articles)} + Firehose new: {len(fh_new)} = {len(articles)} total")

    if not articles:
        print("❌ Ei artikkeleita löytynyt. Keskeytetään.")
        append_metrics({
            "timestamp": run_timestamp,
            "success": False,
            "article_count": 0,
            "total_duration_sec": round(time.monotonic() - pipeline_start, 2),
            "steps": step_metrics,
            "errors": run_errors + ["no articles found"],
        })
        return False

    log_run("scanned", {
        "count": len(articles),
        "rss_count": len(rss_articles),
        "firehose_new": len(fh_new),
        "articles": articles,
    })

    # ------------------------------------------------------------------
    # Step 1b: Deduplication
    # ------------------------------------------------------------------
    print("\n🔍 Vaihe 1b: Duplikaattien suodatus...")
    dedup_start = time.monotonic()
    try:
        articles = filter_new_articles(articles)
        if articles:
            articles = check_published_duplicates(articles)
        dedup_dur = time.monotonic() - dedup_start
        step_metrics["dedup"] = {"duration_sec": round(dedup_dur, 2), "timed_out": False}
    except Exception as e:
        dedup_dur = time.monotonic() - dedup_start
        step_metrics["dedup"] = {"duration_sec": round(dedup_dur, 2), "timed_out": False, "error": str(e)}

    if not articles:
        print("ℹ️  Kaikki artikkelit on jo julkaistu. Ei uusia artikkeleita.")
        append_metrics({
            "timestamp": run_timestamp,
            "success": True,
            "article_count": 0,
            "total_duration_sec": round(time.monotonic() - pipeline_start, 2),
            "steps": step_metrics,
            "errors": run_errors,
            "note": "all duplicates",
        })
        return True

    # ------------------------------------------------------------------
    # Step 1c: Research enrichment (optional — timeout skips gracefully)
    # ------------------------------------------------------------------
    print(f"\n🔍 Vaihe 1c: Lähdeartikkelien haku ({len(articles)} artikkelia)...")
    research_result, dur, timed_out = run_step("research", enrich_with_research, articles)
    step_metrics["research"] = {"duration_sec": round(dur, 2), "timed_out": timed_out}
    if timed_out:
        run_errors.append("research: timed out — continuing without enrichment")
        print("[research] Timed out — continuing without enrichment")
    elif research_result is not None:
        articles = research_result

    # ------------------------------------------------------------------
    # Step 2: Rewrite (mandatory)
    # ------------------------------------------------------------------
    print(f"\n✍️  Vaihe 2: {len(articles)} artikkelin uudelleenkirjoitus...")
    rewrite_result, dur, timed_out = run_step("rewriter", rewrite_articles, articles)
    step_metrics["rewriter"] = {"duration_sec": round(dur, 2), "timed_out": timed_out}

    if timed_out:
        run_errors.append("rewriter: timed out")
        print("❌ Rewriter timed out. Keskeytetään.")
        append_metrics({
            "timestamp": run_timestamp,
            "success": False,
            "article_count": 0,
            "total_duration_sec": round(time.monotonic() - pipeline_start, 2),
            "steps": step_metrics,
            "errors": run_errors,
        })
        return False

    if not rewrite_result:
        err_msg = "rewriter: returned empty"
        run_errors.append(err_msg)
        print(f"❌ {err_msg}. Keskeytetään.")
        append_metrics({
            "timestamp": run_timestamp,
            "success": False,
            "article_count": 0,
            "total_duration_sec": round(time.monotonic() - pipeline_start, 2),
            "steps": step_metrics,
            "errors": run_errors,
        })
        return False

    rewritten = rewrite_result
    log_run("rewritten", {"count": len(rewritten), "articles": rewritten})

    # ------------------------------------------------------------------
    # Step 2b: Image generation (optional — timeout skips gracefully)
    # ------------------------------------------------------------------
    print(f"\n🖼️  Vaihe 2b: Kuvien generointi ({len(rewritten)} artikkelia, max {STEP_TIMEOUTS['image_gen']//60} min)...")
    img_result, dur, timed_out = run_step("image_gen", generate_images_for_articles, rewritten)
    step_metrics["image_gen"] = {"duration_sec": round(dur, 2), "timed_out": timed_out}

    if timed_out:
        run_errors.append(f"image_gen: timed out after {dur:.0f}s — publishing without images")
        print(f"[image_gen] Timed out after {dur:.0f}s — julkaistaan ilman kuvia")
    elif img_result is not None:
        rewritten = img_result
        image_count = sum(1 for a in rewritten if a.get("image"))
        print(f"[image_gen] {image_count}/{len(rewritten)} artikkelia sai kuvan")
    else:
        print("[image_gen] Kuvien generointi epäonnistui — jatketaan ilman kuvia")

    # ------------------------------------------------------------------
    # Step 3: Publish (mandatory)
    # ------------------------------------------------------------------
    print(f"\n📝 Vaihe 3: {len(rewritten)} artikkelin julkaisu...")
    pub_start = time.monotonic()
    created = publish_articles(rewritten)
    step_metrics["publisher"] = {"duration_sec": round(time.monotonic() - pub_start, 2), "timed_out": False}
    log_run("published", {"count": len(created), "files": created})
    mark_published(rewritten)

    if quick:
        total = round(time.monotonic() - pipeline_start, 2)
        print(f"\n✅ Valmis! {len(created)} artikkelia julkaistu (build ohitettu).")
        append_metrics({
            "timestamp": run_timestamp,
            "success": True,
            "article_count": len(created),
            "total_duration_sec": total,
            "steps": step_metrics,
            "errors": run_errors,
        })
        return True

    # ------------------------------------------------------------------
    # Step 4: Build (optional — failure still counts as partial success)
    # ------------------------------------------------------------------
    print("\n🔨 Vaihe 4: Hugo-sivuston rakennus...")
    build_result, dur, timed_out = run_step("build", build_site)
    step_metrics["build"] = {"duration_sec": round(dur, 2), "timed_out": timed_out}

    total = round(time.monotonic() - pipeline_start, 2)

    if timed_out:
        run_errors.append("build: timed out")
        print(f"\n⚠️  {len(created)} artikkelia julkaistu, mutta build aikakatkaistiin.")
        success = True  # Articles published; build timeout is non-fatal
    elif build_result:
        print(f"\n✅ Valmis! {len(created)} artikkelia julkaistu. ({total:.0f}s)")
        success = True
    else:
        run_errors.append("build: failed")
        print("\n⚠️  Artikkelit julkaistu, mutta sivuston rakennus epäonnistui.")
        success = True  # Still partial success — articles are there

    append_metrics({
        "timestamp": run_timestamp,
        "success": success,
        "article_count": len(created),
        "total_duration_sec": total,
        "steps": step_metrics,
        "errors": run_errors,
    })
    return success


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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
        "--firehose-only",
        action="store_true",
        help="Poll Firehose only (skip RSS scan and Hugo build)",
    )
    args = parser.parse_args()

    if args.quick and args.build_only:
        print("❌ Cannot use --quick and --build-only together.")
        sys.exit(1)

    success = run(
        quick=args.quick,
        build_only=args.build_only,
        firehose_only=args.firehose_only,
    )
    sys.exit(0 if success else 1)
