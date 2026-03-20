#!/usr/bin/env python3
"""
metrics_report.py — Uutistenlukija.fi daily metrics summary
Posts to Discord #metrics channel.

Collects:
  - Pipeline health (from logs/metrics.json)
  - Article counts (from content/posts/)
  - Category distribution
  - GA4 traffic (TODO: disabled — OAuth client needs re-enabling in GCP console)

Usage:
  python3 metrics_report.py                 # post to Discord
  python3 metrics_report.py --dry-run       # print report, no Discord post
  python3 metrics_report.py --days 7        # report window (default: 1)
"""

import argparse
import glob
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PIPELINE_DIR = Path(__file__).parent
CONTENT_DIR = PIPELINE_DIR.parent / "content" / "posts"
METRICS_FILE = PIPELINE_DIR / "logs" / "metrics.json"

DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
# #metrics channel
DISCORD_METRICS_CHANNEL = os.environ.get("DISCORD_METRICS_CHANNEL", "1482720741790060554")


# ---------------------------------------------------------------------------
# Pipeline stats
# ---------------------------------------------------------------------------
def load_pipeline_runs(days: int = 1) -> list:
    """Load recent pipeline runs from metrics.json."""
    if not METRICS_FILE.exists():
        return []
    try:
        with open(METRICS_FILE) as f:
            runs = json.load(f)
        if not isinstance(runs, list):
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        recent = []
        for run in runs:
            ts_raw = run.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_raw)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    recent.append(run)
            except ValueError:
                pass
        return recent
    except Exception as e:
        print(f"[metrics] Could not load metrics.json: {e}", file=sys.stderr)
        return []


def pipeline_summary(runs: list) -> dict:
    """Summarise pipeline run data."""
    if not runs:
        return {
            "run_count": 0,
            "success_rate": 0,
            "articles_published": 0,
            "avg_duration_min": 0,
            "slow_steps": [],
            "errors": [],
        }

    success_count = sum(1 for r in runs if r.get("success"))
    articles = sum(r.get("article_count", 0) for r in runs)
    durations = [r.get("total_duration_sec", 0) for r in runs]
    avg_duration = sum(durations) / len(durations) if durations else 0

    # Step timing totals across runs
    step_totals = defaultdict(list)
    for run in runs:
        for step, info in run.get("steps", {}).items():
            step_totals[step].append(info.get("duration_sec", 0))

    # Flag steps averaging > 5 min
    slow_steps = []
    for step, times in step_totals.items():
        avg = sum(times) / len(times)
        if avg > 300:
            slow_steps.append((step, avg))
    slow_steps.sort(key=lambda x: -x[1])

    # Recent errors
    errors = []
    for run in runs:
        for err in run.get("errors", []):
            errors.append(err)

    return {
        "run_count": len(runs),
        "success_rate": success_count / len(runs) * 100,
        "articles_published": articles,
        "avg_duration_min": avg_duration / 60,
        "slow_steps": slow_steps,
        "errors": errors[-5:],  # last 5
    }


# ---------------------------------------------------------------------------
# Content stats
# ---------------------------------------------------------------------------
def content_stats(days: int = 1) -> dict:
    """Count articles and categories from content/posts/."""
    files = sorted(CONTENT_DIR.glob("*.md"))
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=days - 1)

    by_date = Counter()
    total_cats = Counter()
    recent_cats = Counter()

    for path in files:
        fname = path.stem  # e.g. 2026-03-20-title
        parts = fname.split("-")
        article_date = None
        if len(parts) >= 3:
            try:
                article_date = datetime.strptime("-".join(parts[:3]), "%Y-%m-%d").date()
                by_date[str(article_date)] += 1
            except ValueError:
                pass

        # Parse category from frontmatter (fast, no full YAML parse)
        cat = None
        try:
            with open(path) as f:
                in_fm = False
                in_categories = False
                for line in f:
                    line = line.rstrip()
                    if line == "---":
                        if not in_fm:
                            in_fm = True
                            continue
                        else:
                            break  # end of frontmatter
                    if not in_fm:
                        continue
                    if line.startswith("categories:"):
                        in_categories = True
                        continue
                    if in_categories:
                        if line.startswith("  - "):
                            cat = line.strip()[2:].strip()
                            break
                        elif line and not line.startswith(" "):
                            in_categories = False
        except Exception:
            pass

        if cat:
            total_cats[cat] += 1
            if article_date and article_date >= cutoff:
                recent_cats[cat] += 1

    # Build day-by-day counts for window
    daily = {}
    for i in range(days):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        daily[d] = by_date.get(d, 0)

    return {
        "total_articles": len(files),
        "recent_articles": sum(daily.values()),
        "daily": daily,
        "top_categories_total": total_cats.most_common(8),
        "top_categories_recent": recent_cats.most_common(8),
    }


# ---------------------------------------------------------------------------
# GA4 (stub)
# ---------------------------------------------------------------------------
def ga4_stats() -> dict | None:
    """Fetch traffic data from Google Analytics 4 Data API.

    TODO: Currently disabled — OAuth client for project uutistenlukija-fi
    has been disabled in GCP console. To re-enable:
      1. Go to console.cloud.google.com → APIs & Services → Credentials
      2. Re-enable the OAuth 2.0 client ID used by gog CLI
      3. Ensure 'Google Analytics Data API' is enabled for the project
      4. Re-run `gog` auth flow to get a fresh token with analytics.readonly scope

    Returns None when unavailable.
    """
    return None  # TODO: implement when OAuth is fixed


# ---------------------------------------------------------------------------
# Format report
# ---------------------------------------------------------------------------
def format_report(
    pipeline: dict,
    content: dict,
    ga4: dict | None,
    days: int,
) -> str:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    window = "viimeinen 24h" if days == 1 else f"viimeiset {days} päivää"

    lines = [
        f"📊 **Uutistenlukija.fi — Metrics Report** ({window}, {now_str})",
        "",
    ]

    # --- Articles ---
    lines.append("**📰 Artikkelit**")
    lines.append(f"• Yhteensä tietokannassa: **{content['total_articles']}**")
    lines.append(
        f"• Julkaistu ({window}): **{content['recent_articles']}**"
    )

    # Daily breakdown if multi-day
    if days > 1 and content.get("daily"):
        for d, count in sorted(content["daily"].items(), reverse=True):
            lines.append(f"  - {d}: {count}")

    if content.get("top_categories_recent"):
        top = ", ".join(
            f"{cat} ({n})" for cat, n in content["top_categories_recent"][:5]
        )
        lines.append(f"• Kategoriat ({window}): {top}")
    lines.append("")

    # --- Pipeline ---
    lines.append("**⚙️ Pipeline**")
    if pipeline["run_count"] == 0:
        lines.append("• ⚠️ Ei pipeline-ajoja raportin aikaikkunassa")
    else:
        lines.append(f"• Ajoja: **{pipeline['run_count']}**")
        lines.append(f"• Onnistumisprosentti: **{pipeline['success_rate']:.0f}%**")
        lines.append(
            f"• Avg kesto: **{pipeline['avg_duration_min']:.1f} min**"
        )
        if pipeline["slow_steps"]:
            slow = ", ".join(
                f"{s} ({t/60:.0f}min)" for s, t in pipeline["slow_steps"]
            )
            lines.append(f"• 🐢 Hitaat steppit: {slow}")
        if pipeline["errors"]:
            lines.append(f"• ❌ Virheitä: {len(pipeline['errors'])}")
    lines.append("")

    # --- GA4 ---
    lines.append("**📈 Liikenne (GA4)**")
    if ga4 is None:
        lines.append(
            "• ⚠️ GA4 Data API ei käytettävissä — OAuth client disabled GCP:ssä. "
            "Pyydä Perttua re-enabloimaan OAuth client projektissa uutistenlukija-fi."
        )
    else:
        # Populated when GA4 works
        lines.append(f"• Sivulataukset: **{ga4.get('pageviews', 0)}**")
        lines.append(f"• Uniikkeja kävijöitä: **{ga4.get('users', 0)}**")
        if ga4.get("top_pages"):
            lines.append("• Top artikkelit:")
            for page, views in ga4["top_pages"][:5]:
                lines.append(f"  - {page}: {views}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Discord post
# ---------------------------------------------------------------------------
def post_to_discord(content: str, dry_run: bool = False) -> bool:
    if dry_run:
        print("=== DRY RUN — Discord post would be: ===")
        print(content)
        return True

    payload = json.dumps({"content": content}).encode()

    # Try webhook first
    if DISCORD_WEBHOOK_URL:
        try:
            req = urllib.request.Request(
                DISCORD_WEBHOOK_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status in (200, 204):
                    print("[metrics] Posted via webhook ✓")
                    return True
        except Exception as e:
            print(f"[metrics] Webhook failed: {e}", file=sys.stderr)

    # Fall back to bot token
    if DISCORD_BOT_TOKEN:
        try:
            url = f"https://discord.com/api/v10/channels/{DISCORD_METRICS_CHANNEL}/messages"
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status in (200, 201):
                    print("[metrics] Posted via bot token ✓")
                    return True
        except Exception as e:
            print(f"[metrics] Bot token post failed: {e}", file=sys.stderr)

    print(
        "[metrics] ⚠ Could not post to Discord — set DISCORD_WEBHOOK_URL or DISCORD_BOT_TOKEN in .env",
        file=sys.stderr,
    )
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Uutistenlukija metrics reporter")
    parser.add_argument("--dry-run", action="store_true", help="Print report, don't post")
    parser.add_argument("--days", type=int, default=1, help="Reporting window in days (default: 1)")
    args = parser.parse_args()

    # Load .env if present
    env_path = PIPELINE_DIR.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    pipeline = pipeline_summary(load_pipeline_runs(args.days))
    content = content_stats(args.days)
    ga4 = ga4_stats()

    report = format_report(pipeline, content, ga4, args.days)
    post_to_discord(report, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
