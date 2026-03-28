#!/usr/bin/env python3
"""CTR gap report for uutistenlukija.fi

Reads Search Console data (or uses frontmatter as fallback) and finds articles
with high impressions but low CTR — prime candidates for title/meta optimization.

Usage:
    python3 scripts/ctr_gap_report.py [--top N] [--output PATH] [--post-discord]
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent


def load_search_console_data(data_path: Path) -> list:
    """Load GSC data. Expected: list of {url, impressions, clicks, ctr, position}."""
    if not data_path.exists():
        return []
    try:
        data = json.loads(data_path.read_text())
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "rows" in data:
            return data["rows"]
    except (json.JSONDecodeError, KeyError):
        pass
    return []


def load_from_frontmatter(posts_dir: Path) -> list:
    """Fallback: score articles by title/description quality as CTR proxy."""
    articles = []
    for md_file in sorted(posts_dir.glob("*.md")):
        content = md_file.read_text(errors="replace")
        fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not fm_match:
            continue
        fm = fm_match.group(1)

        def get_field(key):
            m = re.search(rf"^{key}:\s*(.+)$", fm, re.MULTILINE)
            return m.group(1).strip().strip('"') if m else ""

        title = get_field("title")
        date = get_field("date")
        description = get_field("description")
        slug = md_file.stem
        desc_len = len(description)
        title_len = len(title)
        word_count = len(re.findall(r"\w+", content))

        ctr_gap_score = 0
        if title_len < 40:
            ctr_gap_score += 2
        if desc_len < 80:
            ctr_gap_score += 3
        if desc_len == 0:
            ctr_gap_score += 5
        if word_count < 200:
            ctr_gap_score += 1

        articles.append({
            "slug": slug,
            "title": title,
            "date": date,
            "description": description,
            "word_count": word_count,
            "title_length": title_len,
            "description_length": desc_len,
            "ctr_gap_score": ctr_gap_score,
            "source": "frontmatter_synthetic",
        })
    return articles


def analyze_gsc_data(rows: list, top_n: int) -> list:
    """Find CTR gaps: high impressions + low CTR in positions 4-20."""
    gaps = []
    for row in rows:
        impressions = row.get("impressions", 0)
        clicks = row.get("clicks", 0)
        ctr_raw = row.get("ctr", clicks / impressions if impressions > 0 else 0)
        # Normalise: GSC stores CTR as decimal (0.027) but fetch_search_console.py
        # may return percentage (2.7). Normalise to percentage for display.
        ctr = ctr_raw * 100 if ctr_raw < 1 else ctr_raw
        position = row.get("position", 99)

        if impressions >= 50 and ctr < 3.0 and 4 <= position <= 20:
            gaps.append({
                "url": row.get("url", row.get("page", "")),
                "query": row.get("query", ""),
                "impressions": impressions,
                "clicks": clicks,
                "ctr": round(ctr, 2),  # already in percent
                "position": round(position, 1),
                "potential_clicks": round(impressions * 0.05),
                "gap_size": round(impressions * (0.05 - ctr / 100)),
            })

    gaps.sort(key=lambda x: x["gap_size"], reverse=True)
    return gaps[:top_n]


def analyze_frontmatter_data(articles: list, top_n: int) -> list:
    """Return articles with highest CTR gap scores."""
    scored = sorted(articles, key=lambda x: x["ctr_gap_score"], reverse=True)
    return scored[:top_n]


def format_discord_message(report: dict) -> str:
    """Format report summary for Discord."""
    source = report["data_source"]
    generated = report["generated_at"]
    gaps = report["gaps"]

    if source == "google_search_console":
        lines = [f"📊 **CTR Gap Report** ({generated[:10]})"]
        lines.append(f"Found {len(gaps)} articles with high impressions but low CTR:\n")
        for i, g in enumerate(gaps[:5], 1):
            url_slug = g["url"].rstrip("/").split("/")[-1]
            lines.append(
                f"{i}. `{url_slug[:40]}` — "
                f"{g['impressions']} impr, {g['ctr']}% CTR, pos {g['position']} "
                f"(+{g['potential_clicks']} clicks potential)"
            )
        if not gaps:
            lines.append("✅ No significant CTR gaps found.")
    else:
        lines = [f"📊 **CTR Gap Report (synthetic)** ({generated[:10]})"]
        lines.append("No GSC data — showing articles needing title/description work:\n")
        for i, g in enumerate(gaps[:5], 1):
            title = g["title"][:45] + ("…" if len(g["title"]) > 45 else "")
            lines.append(
                f"{i}. {title} "
                f"(desc: {g['description_length']}ch, words: {g['word_count']}, score: {g['ctr_gap_score']})"
            )
    return "\n".join(lines)


def post_to_discord(message: str) -> bool:
    """Post message to Discord via webhook."""
    import urllib.request
    webhook = os.environ.get("DISCORD_METRICS_WEBHOOK", "")
    if not webhook:
        print("[ctr_gap_report] DISCORD_METRICS_WEBHOOK not set — skipping Discord post.")
        return False
    payload = json.dumps({"content": message}).encode()
    req = urllib.request.Request(
        webhook, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print(f"[ctr_gap_report] Discord post failed: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="CTR gap report for uutistenlukija.fi")
    parser.add_argument("--top", type=int, default=20,
                        help="Number of gap articles to report (default: 20)")
    parser.add_argument("--output", type=str, default="static/api/ctr-gap-report.json",
                        help="Output JSON path (relative to project root)")
    parser.add_argument("--post-discord", action="store_true",
                        help="Post summary to Discord #metrics webhook")
    args = parser.parse_args()

    gsc_path = PROJECT_DIR / "static" / "api" / "search-console-data.json"
    gsc_rows = load_search_console_data(gsc_path)
    now = datetime.now(timezone.utc).isoformat()

    if gsc_rows:
        print(f"[ctr_gap_report] Loaded {len(gsc_rows)} rows from GSC data.")
        gaps = analyze_gsc_data(gsc_rows, args.top)
        data_source = "google_search_console"
    else:
        print("[ctr_gap_report] No GSC data found, using frontmatter fallback.")
        posts_dir = PROJECT_DIR / "content" / "posts"
        articles = load_from_frontmatter(posts_dir)
        print(f"[ctr_gap_report] Analyzed {len(articles)} articles.")
        gaps = analyze_frontmatter_data(articles, args.top)
        data_source = "frontmatter_synthetic"

    report = {
        "generated_at": now,
        "data_source": data_source,
        "total_gaps_found": len(gaps),
        "gaps": gaps,
    }

    output_path = PROJECT_DIR / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[ctr_gap_report] Report written to {output_path} ({len(gaps)} gaps).")

    if args.post_discord:
        msg = format_discord_message(report)
        print(f"[ctr_gap_report] Discord message:\n{msg}")
        post_to_discord(msg)


if __name__ == "__main__":
    main()
