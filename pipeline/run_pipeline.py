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
from firehose import poll_firehose
from research import enrich_with_research
from rewriter import rewrite_articles
from publisher import publish_articles, build_site
from generate_descriptions import generate_for_article_dict
from dedup import filter_new_articles, check_published_duplicates, mark_published
from image_gen import generate_images_for_articles
from pexels import fetch_images_for_articles as pexels_fetch_images
from unsplash import fetch_images_for_articles as unsplash_fetch_images
from health_check import notify_discord_failure, notify_discord_warning, write_metrics


LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

# Alert if total pipeline exceeds this many seconds
PIPELINE_WARN_TIMEOUT = 900  # 15 minutes


class StepTimer:
    """Context manager for timing pipeline steps and recording results."""

    def __init__(self, name: str):
        self.name = name
        self.start: float = 0.0
        self.duration: float = 0.0
        self.success: bool = True
        self.error: str = ""
        self.meta: dict = {}

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.duration = time.time() - self.start
        if exc_type:
            self.success = False
            self.error = str(exc_val)
        return False  # don't swallow exceptions

    def set(self, **kwargs):
        """Store additional metadata for this step."""
        self.meta.update(kwargs)

    def to_dict(self) -> dict:
        d = {"duration_sec": round(self.duration, 2), "success": self.success}
        if self.error:
            d["error"] = self.error
        d.update(self.meta)
        return d


def log_run(stage: str, data: dict):
    """Log pipeline run data (legacy per-stage files)."""
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(LOG_DIR, f"{timestamp}_{stage}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def validate_articles(articles: list) -> tuple:
    """Drop articles that fail quality checks. Returns (valid, dropped_count)."""
    valid = []
    dropped = 0
    for a in articles:
        issues = []
        content = a.get("content", "")
        title = a.get("title", "")
        word_count = len(content.split())

        if word_count < 150:
            issues.append(f"too short ({word_count} words)")
        if len(title) < 10:
            issues.append(f"title too short ({len(title)} chars)")
        if len(title) > 120:
            issues.append(f"title too long ({len(title)} chars)")
        if not a.get("category"):
            issues.append("no category")

        if issues:
            print(f"[quality] DROPPED: '{title[:60]}' — {', '.join(issues)}")
            dropped += 1
        else:
            valid.append(a)

    if dropped:
        print(f"[quality] {dropped} articles dropped, {len(valid)} passed quality gate")
    return valid, dropped


def run(quick: bool = False, build_only: bool = False, firehose_only: bool = False):
    """Execute the pipeline."""
    pipeline_start = time.time()
    steps: dict = {}
    errors: list = []
    article_count = 0

    print("=" * 60)
    print(f"Uutistenlukija Pipeline — {datetime.now(timezone.utc).isoformat()}")
    if quick:
        print("  Mode: --quick (skip build)")
    elif build_only:
        print("  Mode: --build-only")
    elif firehose_only:
        print("  Mode: --firehose-only")
    print("=" * 60)

    if build_only:
        print("\n🔨 Hugo-sivuston rakennus...")
        success, build_err = build_site()
        print("\n✅ Rakennus valmis!" if success else f"\n❌ Rakennus epäonnistui: {build_err}")
        return success

    # ── Step 1: Scan ───────────────────────────────────────────────────────────
    rss_articles = []
    fh_new = []

    with StepTimer("scanner") as t_scan:
        if firehose_only:
            rss_articles = []
            print("\n🔥 Vaihe 1: Firehose-pollaus (RSS ohitettu)...")
            try:
                fh_articles = poll_firehose()
            except Exception as e:
                fh_articles = []
                errors.append(f"firehose: {e}")
            articles = fh_articles
            fh_new = fh_articles
            print(f"[pipeline] Firehose: {len(articles)} articles")
        else:
            print("\n📡 Vaihe 1: RSS-syötteiden skannaus...")
            rss_articles = scan_all_feeds()

            print("\n🔥 Vaihe 1b: Firehose-pollaus...")
            try:
                fh_articles = poll_firehose()
                print(f"[firehose] +{len(fh_articles)} articles from Firehose")
            except Exception as e:
                print(f"[firehose] Skipping (error): {e}")
                fh_articles = []
                errors.append(f"firehose: {e}")

            seen_url_hashes = {a.get("_url_hash") for a in rss_articles if a.get("_url_hash")}
            fh_new = [a for a in fh_articles if a.get("_url_hash") not in seen_url_hashes]
            articles = rss_articles + fh_new
            print(f"[pipeline] RSS: {len(rss_articles)} + Firehose new: {len(fh_new)} = {len(articles)} total")

        t_scan.set(rss_count=len(rss_articles), firehose_count=len(fh_new), total=len(articles))

    steps["scanner"] = t_scan.to_dict()

    if not articles:
        msg = "No articles found after scan"
        notify_discord_failure("scanner", msg)
        errors.append(msg)
        _write_final_metrics(steps, errors, 0, time.time() - pipeline_start, success=False)
        print("❌ Ei artikkeleita löytynyt. Keskeytetään.")
        return False

    log_run("scanned", {"count": len(articles), "rss_count": len(rss_articles), "firehose_new": len(fh_new), "articles": articles})

    # ── Step 1b: Dedup ─────────────────────────────────────────────────────────
    with StepTimer("dedup") as t_dedup:
        print("\n🔍 Vaihe 1b: Duplikaattien suodatus...")
        articles = filter_new_articles(articles)
        if articles:
            articles = check_published_duplicates(articles)
        t_dedup.set(remaining=len(articles))

    steps["dedup"] = t_dedup.to_dict()

    if not articles:
        print("ℹ️  Kaikki artikkelit on jo julkaistu. Ei uusia artikkeleita.")
        _write_final_metrics(steps, errors, 0, time.time() - pipeline_start, success=True)
        return True

    # ── Step 1c: Research ──────────────────────────────────────────────────────
    with StepTimer("research") as t_research:
        print(f"\n🔍 Vaihe 1c: Lähdeartikkelien haku ({len(articles)} artikkelia)...")
        articles = enrich_with_research(articles)
        t_research.set(enriched=len(articles))

    steps["research"] = t_research.to_dict()

    # ── Step 1d: Drop wire briefs with no source material ─────────────────────
    # Skip articles with < 30 words in description AND no research text.
    # These produce sub-100 word output even after rewriting.
    MIN_SOURCE_WORDS = 30
    pre_filter_count = len(articles)
    articles = [
        a for a in articles
        if len(a.get("description", "").split()) >= MIN_SOURCE_WORDS
        or len(a.get("research", "").split()) >= 50
    ]
    skipped = pre_filter_count - len(articles)
    if skipped:
        print(f"[quality] Skipped {skipped} wire briefs (< {MIN_SOURCE_WORDS} desc words, no research)")

    # ── Step 2: Rewrite ────────────────────────────────────────────────────────
    rewritten = []
    with StepTimer("rewriter") as t_rewrite:
        print(f"\n✍️  Vaihe 2: {len(articles)} artikkelin uudelleenkirjoitus...")
        try:
            rewritten = rewrite_articles(articles)
        except ValueError as e:
            t_rewrite.success = False
            t_rewrite.error = str(e)
            notify_discord_failure("rewriter", str(e))
            errors.append(f"rewriter: {e}")
            print(f"❌ {e}")
        except Exception as e:
            t_rewrite.success = False
            t_rewrite.error = str(e)
            notify_discord_failure("rewriter", str(e))
            errors.append(f"rewriter: {e}")
            print(f"❌ Rewriter failed: {e}")
        t_rewrite.set(input_count=len(articles), output_count=len(rewritten))

    steps["rewriter"] = t_rewrite.to_dict()

    if not rewritten:
        notify_discord_failure("rewriter", "Rewriter produced 0 articles", f"Input was {len(articles)} articles")
        _write_final_metrics(steps, errors, 0, time.time() - pipeline_start, success=False)
        print("❌ Uudelleenkirjoitus epäonnistui. Keskeytetään.")
        return False

    log_run("rewritten", {"count": len(rewritten), "articles": rewritten})

    # ── Step 2a: Quality gate ──────────────────────────────────────────────────
    rewritten, dropped_count = validate_articles(rewritten)
    if dropped_count:
        steps["quality_gate"] = {"dropped": dropped_count, "passed": len(rewritten)}
    if not rewritten:
        notify_discord_failure("quality_gate", "All articles dropped by quality gate")
        _write_final_metrics(steps, errors, 0, time.time() - pipeline_start, success=False)
        return False

    # ── Step 2b: Images ────────────────────────────────────────────────────────
    unsplash_count = pexels_count = ai_count = fallback_count = 0
    image_step_start = time.time()
    IMAGE_STEP_TIMEOUT = 300  # 5 minutes hard cap

    with StepTimer("images") as t_images:
        print(f"\n🖼️  Vaihe 2b: Kuvien haku (Unsplash → Pexels → AI fallback)...")
        try:
            _unsplash_key = os.environ.get("UNSPLASH_ACCESS_KEY", "")
            _pexels_key = os.environ.get("PEXELS_API_KEY", "")

            def _needs_image(a):
                return not a.get("image") or a.get("image_category_fallback")

            def _clear_fallback(arts):
                for a in arts:
                    if a.get("image_category_fallback"):
                        a["image"] = ""
                        a["image_category_fallback"] = False

            # Pass 1: Unsplash
            if _unsplash_key and (time.time() - image_step_start) < IMAGE_STEP_TIMEOUT:
                rewritten = unsplash_fetch_images(rewritten, delay=1.2)
                unsplash_count = sum(1 for a in rewritten if a.get("image") and not a.get("image_category_fallback"))
                print(f"[unsplash] {unsplash_count}/{len(rewritten)} images")
            elif not _unsplash_key:
                print("[unsplash] No UNSPLASH_ACCESS_KEY — skipping")

            # Pass 2: Pexels
            still_missing = [a for a in rewritten if _needs_image(a)]
            if still_missing and _pexels_key and (time.time() - image_step_start) < IMAGE_STEP_TIMEOUT:
                print(f"[pexels] Trying for {len(still_missing)} remaining articles...")
                _clear_fallback(still_missing)
                still_missing = pexels_fetch_images(still_missing, delay=0.5)
                pexels_count = sum(1 for a in still_missing if a.get("image") and not a.get("image_category_fallback"))
                print(f"[pexels] {pexels_count}/{len(still_missing)} images")
            elif not _pexels_key:
                print("[pexels] No PEXELS_API_KEY — skipping")

            # Pass 3: AI (with total step timeout guard)
            no_image = [a for a in rewritten if not a.get("image")]
            elapsed = time.time() - image_step_start
            if no_image and elapsed < IMAGE_STEP_TIMEOUT:
                remaining_budget = IMAGE_STEP_TIMEOUT - elapsed
                print(f"[image_gen] AI gen for {len(no_image)} articles without image (budget: {remaining_budget:.0f}s)...")
                no_image = generate_images_for_articles(no_image, max_total_sec=int(remaining_budget))
                ai_count = sum(1 for a in no_image if a.get("image") and not a.get("image_category_fallback"))
                print(f"[image_gen] {ai_count}/{len(no_image)} succeeded")
            elif no_image and elapsed >= IMAGE_STEP_TIMEOUT:
                print(f"[image_gen] Skipping AI gen — image step budget exhausted ({elapsed:.0f}s)")
                notify_discord_warning("images", f"Image step budget exhausted ({elapsed:.0f}s). {len(no_image)} articles have no image.")

        except Exception as e:
            errors.append(f"images: {e}")
            print(f"[images] Kuvien haku epäonnistui: {e}")

        image_count = sum(1 for a in rewritten if a.get("image"))
        fallback_count = sum(1 for a in rewritten if a.get("image_category_fallback"))
        print(f"[images] Total: {image_count}/{len(rewritten)} "
              f"(Unsplash:{unsplash_count}, Pexels:{pexels_count}, AI:{ai_count}, fallback:{fallback_count})")

        if image_count == 0 and len(rewritten) > 0:
            notify_discord_warning("images", f"0 real images obtained for {len(rewritten)} articles")

        t_images.set(
            total=image_count,
            unsplash=unsplash_count,
            pexels=pexels_count,
            ai=ai_count,
            fallback=fallback_count,
        )

    steps["images"] = t_images.to_dict()

    # ── Step 2c: Meta descriptions ─────────────────────────────────────────────
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        with StepTimer("descriptions") as t_desc:
            print(f"\n📋 Vaihe 2c: Meta-kuvausten generointi...")
            desc_count = 0
            for article in rewritten:
                if not article.get("description"):
                    desc = generate_for_article_dict(article)
                    if desc:
                        article["description"] = desc
                        desc_count += 1
            print(f"[descriptions] {desc_count}/{len(rewritten)} artikkelia sai kuvauksen")
            t_desc.set(generated=desc_count)
        steps["descriptions"] = t_desc.to_dict()
    else:
        print(f"\n📋 Vaihe 2c: OPENAI_API_KEY puuttuu, meta-kuvaukset ohitetaan")

    # ── Step 3: Publish ────────────────────────────────────────────────────────
    created = []
    with StepTimer("publisher") as t_publish:
        print(f"\n📝 Vaihe 3: {len(rewritten)} artikkelin julkaisu...")
        try:
            created = publish_articles(rewritten)
            log_run("published", {"count": len(created), "files": created})
            mark_published(rewritten)
        except Exception as e:
            t_publish.success = False
            t_publish.error = str(e)
            notify_discord_failure("publisher", str(e))
            errors.append(f"publisher: {e}")
        t_publish.set(files_created=len(created))

    steps["publisher"] = t_publish.to_dict()
    article_count = len(created)

    # ── Total time warning ─────────────────────────────────────────────────────
    elapsed_total = time.time() - pipeline_start
    if elapsed_total > PIPELINE_WARN_TIMEOUT:
        notify_discord_warning("pipeline", f"Total runtime {elapsed_total:.0f}s exceeds {PIPELINE_WARN_TIMEOUT}s threshold")

    if quick:
        _write_final_metrics(steps, errors, article_count, elapsed_total, success=True)
        print(f"\n✅ Valmis! {len(created)} artikkelia julkaistu (build ohitettu).")
        return True

    # ── Step 4: Build ──────────────────────────────────────────────────────────
    with StepTimer("build") as t_build:
        print("\n🔨 Vaihe 4: Hugo-sivuston rakennus...")
        success, build_err = build_site()
        t_build.success = success
        if not success:
            notify_discord_failure("build", "Hugo build failed", context=build_err[:500] if build_err else "")
            errors.append(f"build failed: {build_err[:200]}" if build_err else "build failed")

    steps["build"] = t_build.to_dict()

    elapsed_total = time.time() - pipeline_start
    _write_final_metrics(steps, errors, article_count, elapsed_total, success=success)

    if success:
        print(f"\n✅ Valmis! {len(created)} artikkelia julkaistu.")
    else:
        print("\n⚠️  Artikkelit julkaistu, mutta sivuston rakennus epäonnistui.")

    return success


def _write_final_metrics(steps: dict, errors: list, article_count: int, total_sec: float, success: bool):
    """Write structured metrics to logs/metrics.json."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "success": success,
        "article_count": article_count,
        "total_duration_sec": round(total_sec, 2),
        "steps": steps,
        "errors": errors,
    }
    path = write_metrics(record)
    print(f"[metrics] Written to {path}")


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

    success = run(quick=args.quick, build_only=args.build_only, firehose_only=args.firehose_only)
    sys.exit(0 if success else 1)
