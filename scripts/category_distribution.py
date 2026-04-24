#!/usr/bin/env python3
"""
category_distribution.py — Daily category distribution report for uutistenlukija.fi

Counts published articles per category, compares against targets,
writes results to static/api/category-stats.json, and optionally
posts a summary to #metrics via DISCORD_METRICS_WEBHOOK.

Usage:
    python3 scripts/category_distribution.py [--post-discord] [--dry-run]

Cron: daily 07:30 UTC (after source_stats.py at 07:00)
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR  = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
CONTENT_DIR = PROJECT_DIR / "content" / "posts"
OUTPUT_FILE = PROJECT_DIR / "static" / "api" / "category-stats.json"
ENV_FILES   = [
    PROJECT_DIR / ".env",
    PROJECT_DIR / "pipeline" / ".env",
    Path("/workspace/.env"),
]

DISCORD_WEBHOOK_ENV = "DISCORD_METRICS_WEBHOOK"

# Target distribution (%) — matches editorial goals
TARGETS = {
    "Kotimaa":    25,
    "Ulkomaat":   20,
    "Talous":     20,
    "Urheilu":    10,
    "Kulttuuri":   7,
    "Teknologia": 15,
    "Tiede":       3,
}

# Alert threshold: flag if actual % deviates more than this from target
ALERT_THRESHOLD = 5  # percentage points


def load_env(paths) -> dict[str, str]:
    env: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def count_articles() -> dict[str, int]:
    """Count published articles per category by scanning frontmatter."""
    counts: dict[str, int] = defaultdict(int)
    if not CONTENT_DIR.exists():
        return counts

    for path in CONTENT_DIR.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        # Extract categories from YAML frontmatter (simple parse, no deps)
        in_fm = False
        in_cats = False
        for line in text.splitlines():
            if line.strip() == "---":
                if not in_fm:
                    in_fm = True
                    continue
                else:
                    break  # end of frontmatter
            if not in_fm:
                continue

            stripped = line.strip()
            if stripped.startswith("categories:"):
                in_cats = True
                # Inline list: categories: [Kotimaa]
                rest = stripped[len("categories:"):].strip()
                if rest.startswith("["):
                    cats = rest.strip("[]").split(",")
                    for cat in cats:
                        cat = cat.strip().strip('"').strip("'")
                        if cat:
                            counts[cat] += 1
                    in_cats = False
                continue

            if in_cats:
                if stripped.startswith("- "):
                    cat = stripped[2:].strip().strip('"').strip("'")
                    counts[cat] += 1
                elif not stripped.startswith("#") and stripped:
                    in_cats = False  # new key

    return dict(counts)


def build_stats(counts: dict[str, int]) -> dict:
    total = sum(counts.values())
    categories = []
    alerts = []

    for cat in sorted(TARGETS.keys()):
        count = counts.get(cat, 0)
        actual_pct = round(count / total * 100, 1) if total else 0
        target_pct = TARGETS[cat]
        delta = round(actual_pct - target_pct, 1)
        over = actual_pct > target_pct + ALERT_THRESHOLD
        under = actual_pct < target_pct - ALERT_THRESHOLD

        entry = {
            "category": cat,
            "count": count,
            "pct": actual_pct,
            "target_pct": target_pct,
            "delta": delta,
            "status": "over" if over else ("under" if under else "ok"),
        }
        categories.append(entry)

        if over:
            alerts.append(f"{cat}: {actual_pct}% (+{delta}% over target {target_pct}%)")
        elif under:
            alerts.append(f"{cat}: {actual_pct}% ({delta}% under target {target_pct}%)")

    # Other categories not in target list
    other_total = sum(v for k, v in counts.items() if k not in TARGETS)
    if other_total:
        categories.append({
            "category": "Muu",
            "count": other_total,
            "pct": round(other_total / total * 100, 1) if total else 0,
            "target_pct": None,
            "delta": None,
            "status": "other",
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_articles": total,
        "categories": categories,
        "alerts": alerts,
        "alert_threshold_pct": ALERT_THRESHOLD,
    }


def format_discord_message(stats: dict) -> str:
    total = stats["total_articles"]
    cats  = stats["categories"]
    alerts = stats["alerts"]
    ts = stats["generated_at"][:10]

    lines = [f"📊 **Kategoriajaukauma** — {ts} ({total} artikkelia yhteensä)", ""]

    # Table rows
    lines.append("```")
    lines.append(f"{'Kategoria':<14} {'Art.':>5}  {'%':>5}  {'Tavoite':>7}  {'Ero':>6}  Status")
    lines.append("-" * 56)
    for c in cats:
        if c["target_pct"] is None:
            continue
        delta_str = f"{c['delta']:+.1f}%" if c["delta"] is not None else "—"
        status_icon = "✅" if c["status"] == "ok" else ("🔺" if c["status"] == "over" else "🔻")
        lines.append(
            f"{c['category']:<14} {c['count']:>5}  {c['pct']:>4.1f}%  "
            f"{c['target_pct']:>5}%  {delta_str:>7}  {status_icon}"
        )
    lines.append("```")

    if alerts:
        lines.append("")
        lines.append("⚠️ **Poikkeamat (yli 5pp tavoitteesta):**")
        for a in alerts:
            lines.append(f"  • {a}")

    return "\n".join(lines)


def post_to_discord(webhook_url: str, message: str, dry_run: bool = False) -> bool:
    if dry_run:
        print(f"[category_distribution] DRY RUN — would post:\n{message}")
        return True
    payload = json.dumps({"content": message}).encode()
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except urllib.error.HTTPError as e:
        print(f"[category_distribution] Discord error: {e.code} {e.reason}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[category_distribution] Discord error: {e}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Category distribution reporter")
    parser.add_argument("--post-discord", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    counts = count_articles()
    if not counts:
        print("[category_distribution] No articles found in content/posts/")
        return 0

    stats = build_stats(counts)
    total = stats["total_articles"]
    alerts = stats["alerts"]

    print(f"[category_distribution] {total} articles counted across {len(counts)} categories")
    for c in stats["categories"]:
        print(f"  {c['category']:<14} {c['count']:>4}  {c['pct']:>4.1f}%  (target: {c.get('target_pct','—')}%)")

    if alerts:
        print(f"\n[category_distribution] {len(alerts)} alerts:")
        for a in alerts:
            print(f"  ⚠ {a}")

    # Write JSON for static API
    if not args.dry_run:
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with OUTPUT_FILE.open("w") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
        print(f"\n[category_distribution] Written to {OUTPUT_FILE.relative_to(PROJECT_DIR)}")

    # Discord post
    if args.post_discord or args.dry_run:
        env = load_env(ENV_FILES)
        webhook_url = os.environ.get(DISCORD_WEBHOOK_ENV) or env.get(DISCORD_WEBHOOK_ENV, "")
        if not webhook_url:
            print(f"[category_distribution] {DISCORD_WEBHOOK_ENV} not set — skipping Discord post")
        else:
            msg = format_discord_message(stats)
            ok = post_to_discord(webhook_url, msg, dry_run=args.dry_run)
            if ok and not args.dry_run:
                print("[category_distribution] Posted to Discord #metrics ✓")

    return 0


if __name__ == "__main__":
    sys.exit(main())
