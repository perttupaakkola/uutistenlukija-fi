#!/usr/bin/env python3
"""
lighthouse_check.py — Run Lighthouse on uutistenlukija.fi and post scores to Discord #metrics.

Usage:
    python3 lighthouse_check.py                    # runs on homepage + latest article
    python3 lighthouse_check.py --url <url>        # run on specific URL
    python3 lighthouse_check.py --dry-run          # print without posting

Requirements:
    npm install -g lighthouse  (or: npx lighthouse is used as fallback)
    DISCORD_WEBHOOK_METRICS env var (webhook URL for #metrics channel)

Score history is appended to pipeline/logs/lighthouse.json
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SITE_URL = "https://uutistenlukija.fi"
CONTENT_DIR = Path(__file__).parent.parent / "content" / "posts"
LOGS_DIR = Path(__file__).parent / "logs"
LIGHTHOUSE_LOG = LOGS_DIR / "lighthouse.json"
METRICS_WEBHOOK = os.getenv("DISCORD_WEBHOOK_METRICS", "")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
METRICS_CHANNEL_ID = "1482720741790060554"

SCORE_EMOJI = {
    "good": "🟢",   # >= 90
    "ok": "🟡",     # >= 50
    "bad": "🔴",    # < 50
}


def score_emoji(score: float) -> str:
    if score >= 0.9:
        return SCORE_EMOJI["good"]
    if score >= 0.5:
        return SCORE_EMOJI["ok"]
    return SCORE_EMOJI["bad"]


def find_lighthouse() -> str:
    """Find lighthouse binary (global install or npx)."""
    for candidate in ["lighthouse", "npx lighthouse"]:
        try:
            result = subprocess.run(
                candidate.split() + ["--version"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError(
        "Lighthouse not found. Install with: npm install -g lighthouse"
    )


def run_lighthouse(url: str, lighthouse_cmd: str) -> dict:
    """Run Lighthouse on URL, return parsed JSON report."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        output_path = f.name

    cmd = lighthouse_cmd.split() + [
        url,
        "--output=json",
        f"--output-path={output_path}",
        "--chrome-flags=--headless --no-sandbox --disable-gpu",
        "--only-categories=performance,accessibility,best-practices,seo",
        "--quiet",
    ]

    print(f"  Running: {' '.join(cmd[:3])} {url} ...", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if not Path(output_path).exists():
        raise RuntimeError(
            f"Lighthouse produced no output for {url}.\n"
            f"stderr: {result.stderr[:500]}"
        )

    with open(output_path) as f:
        report = json.load(f)

    Path(output_path).unlink(missing_ok=True)
    return report


def extract_scores(report: dict) -> dict:
    """Pull category scores + key metrics from Lighthouse report."""
    cats = report.get("categories", {})
    audits = report.get("audits", {})

    def cat_score(key):
        cat = cats.get(key, {})
        return cat.get("score")  # 0.0–1.0 or None

    def audit_val(key):
        a = audits.get(key, {})
        return a.get("displayValue", "n/a")

    return {
        "performance": cat_score("performance"),
        "accessibility": cat_score("accessibility"),
        "best_practices": cat_score("best-practices"),
        "seo": cat_score("seo"),
        "lcp": audit_val("largest-contentful-paint"),
        "cls": audit_val("cumulative-layout-shift"),
        "tbt": audit_val("total-blocking-time"),
        "fcp": audit_val("first-contentful-paint"),
    }


def get_latest_article_url() -> str:
    """Find URL of most recently published article."""
    posts = sorted(CONTENT_DIR.glob("*.md"), reverse=True)
    for post in posts[:10]:
        content = post.read_text()
        m = re.search(r'^draft:\s*true', content, re.MULTILINE)
        if m:
            continue
        # Build URL from filename: YYYY-MM-DD-slug.md -> /posts/YYYY-MM-DD-slug/
        slug = post.stem
        return f"{SITE_URL}/posts/{slug}/"
    return f"{SITE_URL}/posts/"


def load_history() -> list:
    if LIGHTHOUSE_LOG.exists():
        try:
            return json.loads(LIGHTHOUSE_LOG.read_text())
        except json.JSONDecodeError:
            pass
    return []


def save_history(history: list) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    # Keep last 100 entries
    history = history[-100:]
    LIGHTHOUSE_LOG.write_text(json.dumps(history, indent=2))


def format_score(score) -> str:
    if score is None:
        return "n/a"
    return str(int(round(score * 100)))


def score_delta(current, previous) -> str:
    if current is None or previous is None:
        return ""
    diff = round((current - previous) * 100)
    if diff > 0:
        return f" (+{diff})"
    if diff < 0:
        return f" ({diff})"
    return ""


def build_discord_message(results: list, previous_run: dict | None) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"## 🔦 Lighthouse — {now}\n"]

    for entry in results:
        url = entry["url"]
        s = entry["scores"]
        label = "🏠 Etusivu" if url == SITE_URL + "/" or url == SITE_URL else "📄 Artikkeli"
        key = "home" if "posts" not in url else "article"
        prev = (previous_run or {}).get(key, {}).get("scores", {})

        perf = format_score(s["performance"])
        a11y = format_score(s["accessibility"])
        bp   = format_score(s["best_practices"])
        seo  = format_score(s["seo"])

        pd = score_delta(s["performance"],   prev.get("performance"))
        ad = score_delta(s["accessibility"], prev.get("accessibility"))
        bd = score_delta(s["best_practices"],prev.get("best_practices"))
        sd = score_delta(s["seo"],           prev.get("seo"))

        ep = score_emoji(s["performance"]   or 0)
        ea = score_emoji(s["accessibility"] or 0)
        eb = score_emoji(s["best_practices"]or 0)
        es = score_emoji(s["seo"]           or 0)

        lines.append(f"**{label}** `{url}`")
        lines.append(
            f"{ep} Perf **{perf}**{pd}  "
            f"{ea} A11y **{a11y}**{ad}  "
            f"{eb} BP **{bp}**{bd}  "
            f"{es} SEO **{seo}**{sd}"
        )
        lines.append(
            f"> LCP {s['lcp']}  ·  CLS {s['cls']}  ·  TBT {s['tbt']}  ·  FCP {s['fcp']}"
        )
        lines.append("")

    return "\n".join(lines).strip()


def post_to_discord(message: str) -> bool:
    """Post to #metrics via webhook, falling back to bot token."""
    if METRICS_WEBHOOK:
        payload = json.dumps({"content": message}).encode()
        req = urllib.request.Request(
            METRICS_WEBHOOK,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 204)
        except urllib.error.HTTPError as e:
            print(f"Webhook POST failed: {e.code} {e.reason}", file=sys.stderr)

    if BOT_TOKEN:
        url = f"https://discord.com/api/v10/channels/{METRICS_CHANNEL_ID}/messages"
        payload = json.dumps({"content": message}).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bot {BOT_TOKEN}",
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 201)
        except urllib.error.HTTPError as e:
            print(f"Bot token POST failed: {e.code} {e.reason}", file=sys.stderr)

    return False


def main():
    dry_run = "--dry-run" in sys.argv
    specific_url = None
    if "--url" in sys.argv:
        idx = sys.argv.index("--url")
        if idx + 1 < len(sys.argv):
            specific_url = sys.argv[idx + 1]

    print("🔦 Lighthouse CI check starting...")
    lighthouse_cmd = find_lighthouse()
    print(f"  Using: {lighthouse_cmd}")

    urls_to_check = []
    if specific_url:
        urls_to_check = [("custom", specific_url)]
    else:
        article_url = get_latest_article_url()
        urls_to_check = [
            ("home", SITE_URL + "/"),
            ("article", article_url),
        ]

    history = load_history()
    previous_run = history[-1] if history else None

    run_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": {}
    }
    results_list = []

    for key, url in urls_to_check:
        print(f"\n→ Checking: {url}")
        try:
            report = run_lighthouse(url, lighthouse_cmd)
            scores = extract_scores(report)
            run_entry["results"][key] = {"url": url, "scores": scores}
            results_list.append({"url": url, "scores": scores})
            print(f"  Performance: {format_score(scores['performance'])}")
            print(f"  Accessibility: {format_score(scores['accessibility'])}")
            print(f"  Best Practices: {format_score(scores['best_practices'])}")
            print(f"  SEO: {format_score(scores['seo'])}")
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            run_entry["results"][key] = {"url": url, "error": str(e)}

    if not results_list:
        print("No results to report.", file=sys.stderr)
        sys.exit(1)

    message = build_discord_message(results_list, previous_run)
    print(f"\n--- Discord message ---\n{message}\n---")

    if not dry_run:
        history.append(run_entry)
        save_history(history)
        ok = post_to_discord(message)
        if ok:
            print("✅ Posted to #metrics")
        else:
            print("⚠️  Discord post failed (no webhook/token configured?)")
    else:
        print("(dry-run: not posting)")


if __name__ == "__main__":
    main()
