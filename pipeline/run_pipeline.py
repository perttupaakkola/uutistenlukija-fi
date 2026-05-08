#!/usr/bin/env python3
"""
Main Pipeline Runner — orchestrates scan → rewrite → publish.

Flags:
  --quick       Scan + rewrite + publish only (skip Hugo build). For frequent cron runs.
  --build-only  Run Hugo build only (no scanning/rewriting).
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scanner import scan_all_feeds
from firehose import poll_firehose
from research import enrich_with_research
from monica_writer import rewrite_articles
from publisher import publish_articles, build_site
from dedup import filter_new_articles, check_published_duplicates, dedup_within_batch, mark_published
from story_packet import queue_root
from pexels import fetch_images_for_articles as pexels_fetch_images
from unsplash import fetch_images_for_articles as unsplash_fetch_images


def _article_seed_digest(article: dict) -> str:
    title = str(article.get("title", "") or "")
    description = str(article.get("description", "") or "")
    seed = article.get("link") or f"{title}|{description}"
    return hashlib.sha1(str(seed).encode("utf-8", errors="ignore")).hexdigest()[:10]


def _recent_monica_attempt_digests(cooldown_hours: int = 12) -> set[str]:
    """Return story-packet digests recently sent to Monica.

    Monica packet filenames end with the stable seed digest used by
    story_packet.build_story_packet(). If the same source item keeps cycling
    through the buffer, skip it before research/rewriter work for a short
    cooldown. This prevents one repeated item from consuming unattended cycles
    while still allowing it to be retried later if it remains genuinely fresh.
    """
    root = queue_root()
    if not root.exists():
        return set()
    cutoff = time.time() - (cooldown_hours * 3600)
    digests: set[str] = set()
    for box in ("inbox", "outbox", "quarantine"):
        path = root / box
        if not path.exists():
            continue
        for item in path.glob("*.json"):
            try:
                if item.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            stem = item.stem
            if "_" not in stem:
                continue
            digest = stem.rsplit("_", 1)[-1]
            if re.fullmatch(r"[0-9a-f]{10}", digest):
                digests.add(digest)
    return digests


def _drop_recent_monica_attempts(articles: list[dict], cooldown_hours: int = 12) -> list[dict]:
    attempted = _recent_monica_attempt_digests(cooldown_hours=cooldown_hours)
    if not attempted:
        return articles
    kept: list[dict] = []
    dropped: list[str] = []
    for article in articles:
        if _article_seed_digest(article) in attempted:
            dropped.append(str(article.get("title", "?"))[:80])
        else:
            kept.append(article)
    if dropped:
        print(f"[dedup:monica] skipped {len(dropped)} recently attempted Monica packet(s) ({cooldown_hours}h cooldown)")
        for title in dropped[:5]:
            print(f"[dedup:monica]   - {title}")
    return kept
# ── Resilient imports: stub on failure so a single missing function never kills the pipeline ──
def _stub_notify(*args, **kwargs):
    print(f"[resilience] Discord notification skipped (import failed)")

def _stub_write_metrics(record):
    path = os.path.join(LOG_DIR, "metrics.json")
    try:
        with open(path, "w") as f:
            json.dump(record, f, indent=2)
    except Exception:
        pass
    return path

def _stub_should_skip(service):
    return False, "stub"

def _stub_noop(*args, **kwargs):
    pass

def _stub_generate_description(*args, **kwargs):
    return ""

def _stub_generate_images(articles, *args, **kwargs):
    return articles

def _stub_check_for_changes(**kwargs):
    from types import SimpleNamespace
    return SimpleNamespace(needs_build=True, reason="stub (import failed)")

def _stub_run_gate(articles):
    from types import SimpleNamespace
    return SimpleNamespace(passed=articles, rejected=[], reject_reasons={}, stats={})

try:
    from health_check import notify_discord_failure, notify_discord_warning, notify_discord_crash, write_metrics
except ImportError as _ie:
    print(f"[resilience] WARNING: health_check import failed: {_ie}")
    notify_discord_failure = _stub_notify
    notify_discord_warning = _stub_notify
    notify_discord_crash = _stub_notify
    write_metrics = _stub_write_metrics

try:
    from metrics import append_run as _append_metrics_run
except ImportError as _ie:
    print(f"[resilience] WARNING: metrics import failed: {_ie}")
    _append_metrics_run = _stub_noop

try:
    from generate_descriptions import generate_for_article_dict
except ImportError as _ie:
    print(f"[resilience] WARNING: generate_descriptions import failed: {_ie}")
    generate_for_article_dict = _stub_generate_description

try:
    from image_gen import generate_images_for_articles
except ImportError as _ie:
    print(f"[resilience] WARNING: image_gen import failed: {_ie}")
    generate_images_for_articles = _stub_generate_images

try:
    from service_health import should_skip, record_success, record_failure
except ImportError as _ie:
    print(f"[resilience] WARNING: service_health import failed: {_ie}")
    should_skip = _stub_should_skip
    record_success = _stub_noop
    record_failure = _stub_noop

try:
    from change_detector import check_for_changes, record_build
except ImportError as _ie:
    print(f"[resilience] WARNING: change_detector import failed: {_ie}")
    check_for_changes = _stub_check_for_changes
    record_build = _stub_noop

try:
    from quality_gate import run_gate as _run_quality_gate
except ImportError as _ie:
    print(f"[resilience] WARNING: quality_gate import failed: {_ie}")
    _run_quality_gate = _stub_run_gate


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


def _ping_search_engines(new_urls: list[str] | None = None):
    """
    Notify search engines about new content via IndexNow.

    IndexNow is supported by Bing, Yandex, Naver and (via Cloudflare) partially
    by Google. It sends the specific new article URLs rather than a generic sitemap
    ping (which is deprecated for both Google and Bing as of 2023).

    Fire-and-forget: errors are logged but never raise.
    """
    import json
    INDEXNOW_KEY = "7faa209351614ee79057069917978b71"
    HOST = "uutistenlukija.fi"

    # Use provided URLs or fall back to just the sitemap URL path
    urls_to_ping = new_urls or [f"https://{HOST}/"]
    # Cap at 10 000 (IndexNow limit per batch)
    urls_to_ping = urls_to_ping[:10000]

    # IndexNow batch submission (Bing endpoint, accepted by all IndexNow partners)
    payload = {
        "host": HOST,
        "key": INDEXNOW_KEY,
        "keyLocation": f"https://{HOST}/{INDEXNOW_KEY}.txt",
        "urlList": urls_to_ping,
    }
    endpoint = "https://api.indexnow.org/IndexNow"
    try:
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            endpoint, body,
            {"Content-Type": "application/json; charset=utf-8",
             "User-Agent": "uutistenlukija-pipeline/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[sitemap-ping] IndexNow {resp.status} — {len(urls_to_ping)} URL(s) submitted")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")[:200]
        print(f"[sitemap-ping] IndexNow HTTP {e.code}: {body_text}")
    except Exception as e:
        print(f"[sitemap-ping] WARNING: IndexNow failed: {e}")


def log_run(stage: str, data: dict):
    """Log pipeline run data (legacy per-stage files)."""
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(LOG_DIR, f"{timestamp}_{stage}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


_REJECTED_DIR = os.path.join(os.path.dirname(__file__), "rejected")

# Finnish stopwords excluded from keyword-stuffing check
_KW_STOPWORDS = {
    "ja", "on", "ei", "se", "että", "oli", "kun", "tai", "myös",
    "sekä", "ovat", "oli", "en", "et", "hän", "me", "te", "he",
    "olla", "joka", "jo", "niin", "kuin", "siis",
}


def _save_rejected(article: dict, reason: str) -> None:
    """Persist a rejected article to pipeline/rejected/ for later review."""
    import json
    os.makedirs(_REJECTED_DIR, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    # Sanitize title for filename
    slug = re.sub(r"[^\w\-]", "_", article.get("title", "unknown")[:40])
    filename = f"{ts}_{slug}.json"
    path = os.path.join(_REJECTED_DIR, filename)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"reason": reason, "article": article}, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"[quality] Could not save rejected article: {e}")


def _quality_issues(content: str, title: str) -> list[str]:
    """Return list of quality issue strings (empty = passes all checks)."""
    issues = []

    # ── existing checks ───────────────────────────────────────────────────────
    word_count = len(content.split())
    if word_count < 150:
        issues.append(f"too short ({word_count} words)")
    if len(title) < 10:
        issues.append(f"title too short ({len(title)} chars)")
    if len(title) > 120:
        issues.append(f"title too long ({len(title)} chars)")

    # ── new checks ────────────────────────────────────────────────────────────

    # 1. Paragraph count
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    if len(paragraphs) < 3:
        issues.append(f"only {len(paragraphs)} paragraphs (min 3)")

    # 2. Lead paragraph length
    if paragraphs:
        lead_words = len(paragraphs[0].split())
        if lead_words < 30:
            issues.append(f"lead paragraph too short ({lead_words} words, min 30)")

    # 3. No list-only articles (>60% bullet lines)
    lines = [l for l in content.splitlines() if l.strip()]
    if lines:
        bullet_lines = sum(1 for l in lines if re.match(r"^\s*[-*]\s", l))
        bullet_ratio = bullet_lines / len(lines)
        if bullet_ratio > 0.60:
            issues.append(f"listicle ({bullet_ratio:.0%} bullet lines, max 60%)")

    # 4. Keyword stuffing — any single word >5% of total (excluding stopwords)
    words = re.findall(r"\b[a-zäöåA-ZÄÖÅ]{4,}\b", content.lower())
    content_words = [w for w in words if w not in _KW_STOPWORDS]
    if len(content_words) >= 20:  # only meaningful if we have enough words
        from collections import Counter
        freq = Counter(content_words)
        most_common_word, most_common_count = freq.most_common(1)[0]
        ratio = most_common_count / len(content_words)
        if ratio > 0.05:
            issues.append(
                f"keyword stuffing: '{most_common_word}' appears {most_common_count}× "
                f"({ratio:.1%} of content words, max 5%)"
            )

    return issues


def validate_articles(articles: list) -> tuple:
    """Drop articles that fail quality checks. Returns (valid, dropped_count, reject_reasons).

    reject_reasons is a dict mapping short reason keys to counts.
    Rejected articles are saved to pipeline/rejected/ with timestamp filenames
    for post-run review.
    """
    from collections import Counter
    valid = []
    dropped = 0
    reason_counter: Counter = Counter()

    for a in articles:
        content = a.get("content", "")
        title = a.get("title", "")

        issues = _quality_issues(content, title)

        if not a.get("category"):
            issues.append("no category")

        if issues:
            reason = ", ".join(issues)
            print(f"[quality] REJECTED: '{title[:60]}' — {reason}")
            _save_rejected(a, reason)
            dropped += 1
            # Bucket into short reason keys for metrics
            for issue in issues:
                if "too short" in issue:
                    reason_counter["too_short"] += 1
                elif "paragraphs" in issue:
                    reason_counter["few_paragraphs"] += 1
                elif "lead" in issue:
                    reason_counter["thin_lead"] += 1
                elif "listicle" in issue:
                    reason_counter["listicle"] += 1
                elif "stuffing" in issue:
                    reason_counter["keyword_stuffing"] += 1
                elif "category" in issue:
                    reason_counter["no_category"] += 1
                else:
                    reason_counter["other"] += 1
        else:
            valid.append(a)

    if dropped:
        print(f"[quality] {dropped} articles dropped, {len(valid)} passed quality gate")
    return valid, dropped, dict(reason_counter)


def run(quick: bool = False, build_only: bool = False, firehose_only: bool = False, max_articles: int = None, dedup_window: int = 24, incremental: bool = False, force: bool = False, ghost: bool = False):
    """Execute the pipeline."""
    pipeline_start = time.time()
    steps: dict = {}
    errors: list = []
    article_count = 0
    # Metrics accumulators
    _m_fetched = 0
    _m_deduped = 0
    _m_rewritten = 0
    _m_rejected = 0
    _m_avg_words = 0.0
    _m_sources: dict = {}
    _m_reject_reasons: dict = {}

    print("=" * 60)
    print(f"Uutistenlukija Pipeline — {datetime.now(timezone.utc).isoformat()}")
    if quick:
        print("  Mode: --quick (skip build)")
    elif build_only:
        print("  Mode: --build-only")
    elif firehose_only:
        print("  Mode: --firehose-only")
    elif incremental:
        print("  Mode: --incremental (skip build if no changes)")
    if force:
        print("  Flag: --force (override incremental check)")
    print("=" * 60)

    if build_only:
        if incremental and not force:
            _change = check_for_changes()
            if not _change.needs_build:
                print(f"\n⏭️  Build skipped — {_change.reason}")
                return True
            print(f"🔍 Change detected: {_change.reason}")
        print("\n🔨 Hugo-sivuston rakennus...")
        success, build_err = build_site()
        if success:
            record_build()
            try:
                from generate_dashboard import generate as _gen_dashboard
                _gen_dashboard()
            except Exception as _dash_err:
                print(f"[dashboard] WARNING: generation failed: {_dash_err}")
            _ping_search_engines()
            # Regenerate critical CSS partial
            try:
                import subprocess, sys as _sys
                _crit = subprocess.run(
                    [_sys.executable, "extract_critical_css.py"],
                    capture_output=True, text=True, cwd=os.path.dirname(__file__)
                )
                if _crit.returncode != 0:
                    print(f"[critical-css] WARNING: {_crit.stderr.strip()}")
                else:
                    print(f"[critical-css] {_crit.stdout.strip()}")
            except Exception as _crit_err:
                print(f"[critical-css] WARNING: regeneration failed: {_crit_err}")
            try:
                import subprocess, sys as _sys
                _schema = subprocess.run(
                    [_sys.executable, os.path.join(PROJECT_DIR, "scripts", "validate_structured_data.py"), "--public-dir", os.path.join(PROJECT_DIR, "public")],
                    capture_output=True, text=True, cwd=PROJECT_DIR
                )
                schema_output = "\n".join(filter(None, [_schema.stdout.strip(), _schema.stderr.strip()]))
                if schema_output:
                    print(schema_output)
                if _schema.returncode != 0:
                    print(f"[schema] WARNING: validator exited {_schema.returncode}")
            except Exception as _schema_err:
                print(f"[schema] WARNING: validation failed to run: {_schema_err}")
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
    _m_fetched = len(articles)
    # Source domain counts from scanner output
    from collections import Counter as _Counter
    _m_sources = dict(_Counter(
        a.get("source_domain") or a.get("source", "?") for a in articles
    ))

    steps["scanner"] = t_scan.to_dict()

    if not articles:
        if firehose_only and not errors:
            print("ℹ️  Firehose returned no new articles. Treating as a successful no-op.")
            _write_final_metrics(steps, errors, 0, time.time() - pipeline_start, success=True,
                                 fetched=_m_fetched, sources=_m_sources)
            return True

        if firehose_only and errors:
            msg = "Firehose returned no articles"
            notify_discord_failure("firehose", msg, context="; ".join(errors))
        else:
            msg = "No articles found after scan"
            notify_discord_failure("scanner", msg)
        errors.append(msg)
        _write_final_metrics(steps, errors, 0, time.time() - pipeline_start, success=False,
                             fetched=_m_fetched, sources=_m_sources)
        print("❌ Ei artikkeleita löytynyt. Keskeytetään.")
        return False

    log_run("scanned", {"count": len(articles), "rss_count": len(rss_articles), "firehose_new": len(fh_new), "articles": articles})

    # ── Step 1b: Dedup ─────────────────────────────────────────────────────────
    with StepTimer("dedup") as t_dedup:
        print("\n🔍 Vaihe 1b: Duplikaattien suodatus...")
        pre_dedup_count = len(articles)
        articles = filter_new_articles(articles)
        if articles:
            articles = check_published_duplicates(articles, window_hours=dedup_window)
        if articles:
            articles = dedup_within_batch(articles)
        _m_deduped = pre_dedup_count - len(articles)
        t_dedup.set(remaining=len(articles))

    steps["dedup"] = t_dedup.to_dict()

    if not articles:
        print("ℹ️  Kaikki artikkelit on jo julkaistu. Ei uusia artikkeleita.")
        _write_final_metrics(steps, errors, 0, time.time() - pipeline_start, success=True,
                             fetched=_m_fetched, deduped=_m_deduped, sources=_m_sources)
        return True

    # ── Step 1b.1: Monica attempt cooldown ───────────────────────────────────
    # Some high-scoring feed items can recur for hours and repeatedly consume
    # research + Monica capacity. If the same stable story-packet digest already
    # entered Monica's inbox/outbox/quarantine recently, let fresher candidates
    # use the rewrite buffer first.
    before_monica_cooldown = len(articles)
    articles = _drop_recent_monica_attempts(articles)
    _m_deduped += before_monica_cooldown - len(articles)
    if not articles:
        print("ℹ️  All candidates were recent Monica attempts. Treating as a successful no-op.")
        _write_final_metrics(steps, errors, 0, time.time() - pipeline_start, success=True,
                             fetched=_m_fetched, deduped=_m_deduped, sources=_m_sources)
        return True

    # ── Step 1c: Research ──────────────────────────────────────────────────────
    with StepTimer("research") as t_research:
        print(f"\n🔍 Vaihe 1c: Lähdeartikkelien haku ({len(articles)} artikkelia)...")
        articles = enrich_with_research(articles)
        t_research.set(enriched=len(articles))

    steps["research"] = t_research.to_dict()

    # ── Step 1d: Drop wire briefs with no source material ─────────────────────
    # Skip articles where total usable source text is < 50 words.
    # Below this threshold the rewriter can't produce 280+ word output.
    # "Total source words" = research words (web/rss) + description words (if research empty).
    # Minimum combined words (title + description + research) before rewriting.
    # Minimum combined source material before rewriting.
    # Must be 50+ words — anything less produces hallucinated filler.
    # Paywalled/thin sources are already skipped in research.py;
    # this is the final safety net.
    MIN_SOURCE_WORDS = 50
    pre_filter_count = len(articles)
    def _total_source_words(a: dict) -> int:
        title    = a.get("title", "")
        research = a.get("research", "")
        desc     = a.get("description", "")
        return len(title.split()) + len(desc.split()) + len(research.split())
    articles = [a for a in articles if _total_source_words(a) >= MIN_SOURCE_WORDS]
    skipped = pre_filter_count - len(articles)
    if skipped:
        print(f"[quality] Skipped {skipped} articles with < {MIN_SOURCE_WORDS} words source material")
    if not articles:
        print("ℹ️  No candidates had enough source material after research. Treating as a successful no-op.")
        _write_final_metrics(steps, errors, 0, time.time() - pipeline_start, success=True,
                             fetched=_m_fetched, deduped=_m_deduped, rewritten=0,
                             sources=_m_sources)
        return True

    # ── Step 1d.1: Prefer strongest evidence before max-article cap ──────────
    # The scanner order can put thin RSS/paywall fallbacks before well-supported
    # researched articles. If --max-articles cuts the list there, Monica may see
    # only weak packets and correctly return INSUFFICIENT_CONFIDENCE for all of
    # them, even though stronger candidates are available later in the batch.
    def _source_strength(a: dict) -> tuple[int, int, int, int]:
        research = a.get("research", "") or a.get("research_text", "") or ""
        desc = a.get("description", "") or ""
        research_words = len(str(research).split())
        desc_words = len(str(desc).split())
        # Named source labels are inserted by research.py as [Lähde: ...] blocks.
        source_blocks = str(research).lower().count("[lähde:") + str(research).lower().count("[source:")
        # Lower tier numbers are more trusted; invert for descending sort.
        tier_score = max(0, 4 - int(a.get("source_tier", 2) or 2))
        return (research_words, source_blocks, desc_words, tier_score)

    if articles:
        articles = sorted(articles, key=_source_strength, reverse=True)

    # ── Step 1d.2: Warn on Tier 3-only articles ──────────────────────────────
    for a in articles:
        tier = a.get("source_tier", 2)
        research = a.get("research", "")
        if tier == 3 and len(research.split()) < 100:
            print(f"[quality] ⚠️  T3-only article with thin research: '{a.get('title', '')[:60]}'")

    # ── Step 1e: Cap article candidates if --max-articles set ─────────────────
    # `max_articles` is the desired publish cap, not a guarantee that every
    # Monica attempt will survive confidence + quality gates. Keep a small
    # candidate buffer before rewriting so one thin/short draft does not turn a
    # healthy researched batch into a 0-publish cycle.
    publish_cap = max_articles
    if max_articles is not None and len(articles) > max_articles:
        rewrite_cap = min(len(articles), max_articles * 3)
        print(
            f"[pipeline] --max-articles {max_articles}: "
            f"keeping {rewrite_cap} candidates for rewrite buffer from {len(articles)}"
        )
        articles = articles[:rewrite_cap]

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
        _m_rewritten = len(rewritten)
        if rewritten:
            _m_avg_words = sum(len(a.get("content", "").split()) for a in rewritten) / len(rewritten)

    steps["rewriter"] = t_rewrite.to_dict()

    if not rewritten:
        if errors:
            notify_discord_failure("rewriter", "Rewriter produced 0 articles", f"Input was {len(articles)} articles")
        else:
            print("ℹ️  Rewriter produced no safe articles. Treating as a successful no-op.")
        _write_final_metrics(steps, errors, 0, time.time() - pipeline_start, success=not errors,
                             fetched=_m_fetched, deduped=_m_deduped, rewritten=_m_rewritten,
                             sources=_m_sources)
        if errors:
            print("❌ Uudelleenkirjoitus epäonnistui. Keskeytetään.")
            return False
        return True

    log_run("rewritten", {"count": len(rewritten), "articles": rewritten})

    # ── Step 2a: Quality gate ──────────────────────────────────────────────────
    _gate = _run_quality_gate(rewritten)
    rewritten = _gate.passed
    dropped_count = len(_gate.rejected)
    _m_reject_reasons = _gate.reject_reasons
    _m_rejected = dropped_count
    if dropped_count:
        steps["quality_gate"] = {
            "dropped": dropped_count,
            "passed": len(rewritten),
            "avg_score": _gate.stats.get("avg_score", 0),
            "threshold": _gate.stats.get("threshold", 0),
        }
    if not rewritten:
        notify_discord_failure("quality_gate", "All articles dropped by quality gate")
        _write_final_metrics(steps, errors, 0, time.time() - pipeline_start, success=False,
                             fetched=_m_fetched, deduped=_m_deduped, rewritten=_m_rewritten,
                             rejected=_m_rejected, sources=_m_sources, reject_reasons=_m_reject_reasons)
        return False

    # ── Step 2a2: Post-rewrite keyword dedup ──────────────────────────────────
    # Title dedup ran pre-rewrite (step 1b). Keyword dedup needs the rewritten
    # content body — runs here after quality gate so we only compare real articles.
    pre_kw_count = len(rewritten)
    rewritten = check_published_duplicates(rewritten, window_hours=dedup_window)
    rewritten = dedup_within_batch(rewritten)
    kw_dropped = pre_kw_count - len(rewritten)
    if kw_dropped:
        print(f"[dedup:kw] {kw_dropped} post-rewrite near-duplicates dropped")
        steps["kw_dedup"] = {"dropped": kw_dropped, "passed": len(rewritten)}
    if not rewritten:
        print("ℹ️  Kaikki kirjoitetut artikkelit hylättiin duplikaatteina. Ei uusia artikkeleita julkaistavaksi.")
        notify_discord_warning("dedup:kw", "All rewritten articles dropped as near-duplicates", f"Batch was {pre_kw_count} articles")
        _write_final_metrics(steps, errors, 0, time.time() - pipeline_start, success=True,
                             fetched=_m_fetched, deduped=_m_deduped, rewritten=_m_rewritten,
                             rejected=_m_rejected, sources=_m_sources, reject_reasons=_m_reject_reasons)
        return True

    if publish_cap is not None and len(rewritten) > publish_cap:
        print(f"[pipeline] publish cap {publish_cap}: limiting passed articles {len(rewritten)} → {publish_cap}")
        rewritten = rewritten[:publish_cap]

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
            _unsplash_skip, _unsplash_reason = should_skip("unsplash")
            if not _unsplash_key:
                print("[unsplash] No UNSPLASH_ACCESS_KEY — skipping")
            elif _unsplash_skip:
                print(f"[unsplash] Skipped — {_unsplash_reason}")
            elif (time.time() - image_step_start) < IMAGE_STEP_TIMEOUT:
                rewritten = unsplash_fetch_images(rewritten, delay=1.2)
                unsplash_count = sum(1 for a in rewritten if a.get("image") and not a.get("image_category_fallback"))
                print(f"[unsplash] {unsplash_count}/{len(rewritten)} images")
                if unsplash_count > 0:
                    record_success("unsplash")
                else:
                    record_failure("unsplash")

            # Pass 2: Pexels
            still_missing = [a for a in rewritten if _needs_image(a)]
            _pexels_skip, _pexels_reason = should_skip("pexels")
            if not _pexels_key:
                print("[pexels] No PEXELS_API_KEY — skipping")
            elif _pexels_skip:
                print(f"[pexels] Skipped — {_pexels_reason}")
            elif still_missing and (time.time() - image_step_start) < IMAGE_STEP_TIMEOUT:
                print(f"[pexels] Trying for {len(still_missing)} remaining articles...")
                _clear_fallback(still_missing)
                still_missing = pexels_fetch_images(still_missing, delay=0.5)
                pexels_count = sum(1 for a in still_missing if a.get("image") and not a.get("image_category_fallback"))
                print(f"[pexels] {pexels_count}/{len(still_missing)} images")
                if pexels_count > 0:
                    record_success("pexels")
                else:
                    record_failure("pexels")

            # Pass 3: AI (with total step timeout guard + service health check)
            no_image = [a for a in rewritten if not a.get("image")]
            elapsed = time.time() - image_step_start
            if no_image and elapsed >= IMAGE_STEP_TIMEOUT:
                print(f"[image_gen] Skipping AI gen — image step budget exhausted ({elapsed:.0f}s)")
                notify_discord_warning("images", f"Image step budget exhausted ({elapsed:.0f}s). {len(no_image)} articles have no image.")
            elif no_image:
                _kie_skip, _kie_reason = should_skip("kie_api")
                if _kie_skip:
                    print(f"[image_gen] Skipped — Kie.ai {_kie_reason}")
                else:
                    if _kie_reason == "probe":
                        print(f"[image_gen] Kie.ai skip window expired — sending probe request...")
                    remaining_budget = IMAGE_STEP_TIMEOUT - elapsed
                    print(f"[image_gen] AI gen for {len(no_image)} articles without image (budget: {remaining_budget:.0f}s)...")
                    no_image = generate_images_for_articles(no_image, max_total_sec=int(remaining_budget))
                    ai_count = sum(1 for a in no_image if a.get("image") and not a.get("image_category_fallback"))
                    print(f"[image_gen] {ai_count}/{len(no_image)} succeeded")
                    # Update service health based on outcome
                    if ai_count > 0:
                        record_success("kie_api")
                    else:
                        record_failure("kie_api")

            # Pass 4: Rescue — stock photo fallback for any AI-gen failures
            # Articles that failed AI gen (Kie.ai timeout/error) get a second Pexels attempt
            still_no_image = [a for a in rewritten if not a.get("image") or a.get("image_category_fallback")]
            if still_no_image and _pexels_key and (time.time() - image_step_start) < IMAGE_STEP_TIMEOUT:
                print(f"[rescue] {len(still_no_image)} articles still without image — Pexels rescue pass...")
                _clear_fallback(still_no_image)
                still_no_image = pexels_fetch_images(still_no_image, delay=0.3)
                rescue_count = sum(1 for a in still_no_image if a.get("image") and not a.get("image_category_fallback"))
                if rescue_count:
                    print(f"[rescue] {rescue_count}/{len(still_no_image)} rescued via Pexels")
                    pexels_count += rescue_count
            elif still_no_image and _unsplash_key and (time.time() - image_step_start) < IMAGE_STEP_TIMEOUT:
                print(f"[rescue] {len(still_no_image)} articles still without image — Unsplash rescue pass...")
                still_no_image = unsplash_fetch_images(still_no_image, delay=0.5)
                rescue_count = sum(1 for a in still_no_image if a.get("image") and not a.get("image_category_fallback"))
                if rescue_count:
                    print(f"[rescue] {rescue_count}/{len(still_no_image)} rescued via Unsplash")
                    unsplash_count += rescue_count

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
            import traceback as _tb
            t_publish.success = False
            t_publish.error = str(e)
            notify_discord_crash("publisher", e, tb=_tb.format_exc())
            errors.append(f"publisher: {e}")
        t_publish.set(files_created=len(created))

    steps["publisher"] = t_publish.to_dict()
    article_count = len(created)

    # ── Step 3b: Ghost CMS dual-publish (optional) ─────────────────────────────
    ghost_enabled = ghost or os.environ.get("GHOST_ENABLED", "").lower() in ("true", "1", "yes")
    ghost_publish_live = os.environ.get("GHOST_PUBLISH", "").lower() in ("true", "1", "yes")
    if ghost_enabled and rewritten:
        # Graceful skip if env vars not configured
        ghost_url = os.environ.get("GHOST_API_URL", "")
        ghost_key = os.environ.get("GHOST_ADMIN_API_KEY", "")
        if not ghost_url or not ghost_key:
            print(f"  👻 Ghost: skipped (GHOST_API_URL / GHOST_ADMIN_API_KEY not set)")
        else:
            try:
                from ghost_publisher import GhostPublisher
                gp = GhostPublisher()
                ghost_results = gp.publish_batch(rewritten, publish=ghost_publish_live)
                ghost_ok = sum(1 for _, url in ghost_results if url.startswith("http"))
                ghost_fail = len(ghost_results) - ghost_ok
                status_label = "published" if ghost_publish_live else "drafted"
                print(f"  👻 Ghost: {ghost_ok} {status_label}, {ghost_fail} failed")
                log_run("ghost_publish", {"ok": ghost_ok, "failed": ghost_fail, "status": status_label})
                if ghost_fail > 0:
                    failed_titles = [t for t, u in ghost_results if not u.startswith("http")]
                    notify_discord_warning("ghost_publisher", f"{ghost_fail} articles failed: {', '.join(failed_titles[:5])}")
            except Exception as e:
                # Ghost failure must NEVER block Hugo pipeline
                print(f"  ⚠️ Ghost publish failed (non-blocking): {e}")
                log_run("ghost_publish_error", {"error": str(e)})
    elif ghost_enabled:
        print(f"  👻 Ghost: no articles to publish")

    # ── Total time warning ─────────────────────────────────────────────────────
    elapsed_total = time.time() - pipeline_start
    if elapsed_total > PIPELINE_WARN_TIMEOUT:
        notify_discord_warning("pipeline", f"Total runtime {elapsed_total:.0f}s exceeds {PIPELINE_WARN_TIMEOUT}s threshold")

    if quick:
        _write_final_metrics(steps, errors, article_count, elapsed_total, success=True,
                             fetched=_m_fetched, deduped=_m_deduped, rewritten=_m_rewritten,
                             rejected=_m_rejected, avg_words=_m_avg_words,
                             sources=_m_sources, reject_reasons=_m_reject_reasons)
        print(f"\n✅ Valmis! {len(created)} artikkelia julkaistu (build ohitettu).")
        return True

    # ── Step 4: Build ──────────────────────────────────────────────────────────
    # Incremental gate: skip build if nothing changed (unless --force)
    _do_build = True
    if incremental and not force:
        _change = check_for_changes(new_articles_published=article_count)
        if not _change.needs_build:
            print(f"\n⏭️  Build skipped — {_change.reason}")
            _write_final_metrics(steps, errors, article_count, time.time() - pipeline_start, success=True,
                                fetched=_m_fetched, deduped=_m_deduped, rewritten=_m_rewritten,
                                rejected=_m_rejected, avg_words=_m_avg_words,
                                sources=_m_sources, reject_reasons=_m_reject_reasons)
            print(f"\n✅ Valmis! 0 uutta artikkelia, build ohitettu.")
            return True
        else:
            print(f"\n🔍 Change detected: {_change.reason}")

    with StepTimer("build") as t_build:
        print("\n🔨 Vaihe 4: Hugo-sivuston rakennus...")
        success, build_err = build_site()
        t_build.success = success
        if not success:
            notify_discord_failure("build", "Hugo build failed", context=build_err[:500] if build_err else "")
            errors.append(f"build failed: {build_err[:200]}" if build_err else "build failed")
        else:
            record_build()  # snapshot manifest after successful build
            # Regenerate pipeline dashboard after every successful build
            try:
                from generate_dashboard import generate as _gen_dashboard
                _gen_dashboard()
            except Exception as _dash_err:
                print(f"[dashboard] WARNING: generation failed: {_dash_err}")
            # Regenerate critical CSS partial (keeps it in sync if style.css changed)
            try:
                import subprocess, sys as _sys
                _crit = subprocess.run(
                    [_sys.executable, "extract_critical_css.py"],
                    capture_output=True, text=True, cwd=os.path.dirname(__file__)
                )
                if _crit.returncode != 0:
                    print(f"[critical-css] WARNING: {_crit.stderr.strip()}")
                else:
                    print(f"[critical-css] {_crit.stdout.strip()}")
            except Exception as _crit_err:
                print(f"[critical-css] WARNING: regeneration failed: {_crit_err}")
            try:
                import subprocess, sys as _sys
                _schema = subprocess.run(
                    [_sys.executable, os.path.join(PROJECT_DIR, "scripts", "validate_structured_data.py"), "--public-dir", os.path.join(PROJECT_DIR, "public")],
                    capture_output=True, text=True, cwd=PROJECT_DIR
                )
                schema_output = "\n".join(filter(None, [_schema.stdout.strip(), _schema.stderr.strip()]))
                if schema_output:
                    print(schema_output)
                if _schema.returncode != 0:
                    print(f"[schema] WARNING: validator exited {_schema.returncode}")
            except Exception as _schema_err:
                print(f"[schema] WARNING: validation failed to run: {_schema_err}")
            # Ping search engines with new article URLs via IndexNow
            if created:
                _new_urls = [f"https://uutistenlukija.fi/posts/{p.split('/')[-1].replace('.md','')}/"
                             for p in created]
                _ping_search_engines(_new_urls)
            else:
                _ping_search_engines()

    steps["build"] = t_build.to_dict()

    elapsed_total = time.time() - pipeline_start
    _write_final_metrics(steps, errors, article_count, elapsed_total, success=success,
                        fetched=_m_fetched, deduped=_m_deduped, rewritten=_m_rewritten,
                        rejected=_m_rejected, avg_words=_m_avg_words,
                        sources=_m_sources, reject_reasons=_m_reject_reasons)

    if success:
        print(f"\n✅ Valmis! {len(created)} artikkelia julkaistu.")
    else:
        print("\n⚠️  Artikkelit julkaistu, mutta sivuston rakennus epäonnistui.")

    return success


def _write_final_metrics(
    steps: dict,
    errors: list,
    article_count: int,
    total_sec: float,
    success: bool,
    *,
    fetched: int = 0,
    deduped: int = 0,
    rewritten: int = 0,
    rejected: int = 0,
    avg_words: float = 0.0,
    sources: dict | None = None,
    reject_reasons: dict | None = None,
):
    """Write structured metrics to logs/metrics.json and append to metrics.jsonl."""
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

    # Append to the lightweight metrics.jsonl log
    _append_metrics_run(
        fetched=fetched,
        deduped=deduped,
        rewritten=rewritten,
        rejected=rejected,
        published=article_count,
        avg_words=avg_words,
        sources=sources or {},
        reject_reasons=reject_reasons or {},
        duration_s=total_sec,
    )


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
    parser.add_argument(
        "--max-articles",
        type=int,
        default=None,
        metavar="N",
        help="Cap articles sent to rewriter at N (default: no limit). Use 1 for cron quality runs.",
    )
    parser.add_argument(
        "--dedup-window",
        type=int,
        default=48,
        metavar="HOURS",
        help="Cross-batch dedup window in hours (default: 48). Compare incoming articles against "
             "posts published within the last N hours. Use 0 to compare against all posts.",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Skip Hugo build if no content changes detected since last build (checks build_manifest.json).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Override incremental check and always run Hugo build.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate all imports and config without running the pipeline. Exits 0 if OK, 1 if broken.",
    )
    parser.add_argument(
        "--metrics-report",
        action="store_true",
        help="Print a summary of pipeline metrics for the last 7 days and exit.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        metavar="N",
        help="Number of days for --metrics-report (default: 7).",
    )
    parser.add_argument(
        "--ghost",
        action="store_true",
        help="Enable Ghost CMS dual-publish (also enabled by GHOST_ENABLED env var). "
             "Posts are created as drafts unless GHOST_PUBLISH=true.",
    )
    args = parser.parse_args()

    if args.dry_run:
        errors = []
        optional_imports = {"generate_descriptions", "image_gen"}
        # Validate all pipeline imports
        _imports = {
            "scanner": "scanner",
            "firehose": "firehose",
            "research": "research",
            "rewriter": "monica_writer",
            "publisher": "publisher",
            "generate_descriptions": "generate_descriptions",
            "dedup": "dedup",
            "image_gen": "image_gen",
            "pexels": "pexels",
            "unsplash": "unsplash",
            "health_check": "health_check",
            "metrics": "metrics",
            "service_health": "service_health",
            "change_detector": "change_detector",
            "quality_gate": "quality_gate",
        }
        for label, mod in _imports.items():
            try:
                __import__(mod)
                print(f"  ✅ {label}")
            except Exception as e:
                if label in optional_imports:
                    print(f"  ⚠️ {label}: optional import unavailable ({e})")
                else:
                    print(f"  ❌ {label}: {e}")
                    errors.append(label)

        # Validate env
        _env_keys = []
        for k in _env_keys:
            v = os.environ.get(k, "")
            if v:
                print(f"  ✅ {k} (set)")
            else:
                print(f"  ⚠️  {k} (not set)")

        if errors:
            print(f"\n❌ Dry run FAILED: {len(errors)} broken import(s): {', '.join(errors)}")
            sys.exit(1)
        else:
            print(f"\n✅ Dry run OK — all imports valid")
            sys.exit(0)

    if args.metrics_report:
        from metrics import print_report
        print_report(days=args.days)
        sys.exit(0)

    if args.quick and args.build_only:
        print("❌ Cannot use --quick and --build-only together.")
        sys.exit(1)

    success = run(quick=args.quick, build_only=args.build_only, firehose_only=args.firehose_only,
                  max_articles=args.max_articles, dedup_window=args.dedup_window,
                  incremental=args.incremental, force=args.force, ghost=args.ghost)
    sys.exit(0 if success else 1)
