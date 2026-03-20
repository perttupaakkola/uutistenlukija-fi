#!/usr/bin/env python3
"""
lighthouse_check.py — Lighthouse/PageSpeed audit for uutistenlukija.fi.

Primary:  Google PageSpeed Insights API (free, no key needed)
Fallback: Lighthouse CLI if `lighthouse` or `npx lighthouse` is available

Usage:
    python3 lighthouse_check.py                    # homepage + latest article
    python3 lighthouse_check.py --url <url>        # specific URL only
    python3 lighthouse_check.py --dry-run          # print, don't post or save
    python3 lighthouse_check.py --strategy mobile  # mobile (default) or desktop

Score history: pipeline/logs/lighthouse.json (last 30 runs)
Posts summary to Discord #metrics. Flags any score drop > 5 points vs previous run.

Discord target: DISCORD_WEBHOOK_METRICS or DISCORD_BOT_TOKEN env var.
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

PSI_API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
SCORE_DROP_THRESHOLD = 5  # alert if any category drops more than this many points

CATEGORIES = ["performance", "accessibility", "best-practices", "seo"]
CATEGORY_LABELS = {
    "performance": "Perf",
    "accessibility": "A11y",
    "best-practices": "BP",
    "seo": "SEO",
}


# ── PageSpeed Insights (primary) ──────────────────────────────────────────────

def run_psi(url: str, strategy: str = "mobile") -> dict:
    """Run PageSpeed Insights API. Returns parsed response dict."""
    params = urllib.parse.urlencode({
        "url": url,
        "strategy": strategy,
        "category": ["performance", "accessibility", "best-practices", "seo"],
    }, doseq=True)
    full_url = f"{PSI_API}?{params}"
    print(f"  [PSI/{strategy}] {url[:70]} ...", flush=True)

    req = urllib.request.Request(
        full_url,
        headers={"User-Agent": "uutistenlukija-lighthouse/1.0"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def extract_psi_scores(data: dict) -> dict:
    """Extract category scores and key metrics from PSI response."""
    cats = data.get("lighthouseResult", {}).get("categories", {})
    audits = data.get("lighthouseResult", {}).get("audits", {})

    def cat_score(key):
        c = cats.get(key, {})
        score = c.get("score")
        return score  # 0.0–1.0 or None

    def audit_display(key):
        a = audits.get(key, {})
        return a.get("displayValue", "n/a")

    return {
        "performance":    cat_score("performance"),
        "accessibility":  cat_score("accessibility"),
        "best-practices": cat_score("best-practices"),
        "seo":            cat_score("seo"),
        "lcp":  audit_display("largest-contentful-paint"),
        "cls":  audit_display("cumulative-layout-shift"),
        "tbt":  audit_display("total-blocking-time"),
        "fcp":  audit_display("first-contentful-paint"),
        "si":   audit_display("speed-index"),
    }


# ── Lighthouse CLI (fallback) ─────────────────────────────────────────────────

def find_lighthouse_cli() -> str | None:
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
    return None


def run_lighthouse_cli(url: str, cmd: str, strategy: str = "mobile") -> dict:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        output_path = f.name

    emulation = "--screenEmulation.disabled" if strategy == "desktop" else ""
    cli_cmd = cmd.split() + [
        url,
        "--output=json",
        f"--output-path={output_path}",
        "--chrome-flags=--headless --no-sandbox --disable-gpu",
        "--only-categories=performance,accessibility,best-practices,seo",
        "--quiet",
    ]
    if emulation:
        cli_cmd.append(emulation)

    subprocess.run(cli_cmd, capture_output=True, text=True, timeout=120)
    report_path = Path(output_path)
    if not report_path.exists():
        raise RuntimeError(f"Lighthouse produced no output for {url}")

    report = json.loads(report_path.read_text())
    report_path.unlink(missing_ok=True)

    cats = report.get("categories", {})
    audits = report.get("audits", {})

    def cat_score(key):
        return cats.get(key, {}).get("score")

    def audit_display(key):
        return audits.get(key, {}).get("displayValue", "n/a")

    return {
        "performance":    cat_score("performance"),
        "accessibility":  cat_score("accessibility"),
        "best-practices": cat_score("best-practices"),
        "seo":            cat_score("seo"),
        "lcp":  audit_display("largest-contentful-paint"),
        "cls":  audit_display("cumulative-layout-shift"),
        "tbt":  audit_display("total-blocking-time"),
        "fcp":  audit_display("first-contentful-paint"),
        "si":   audit_display("speed-index"),
    }


# ── Runner ────────────────────────────────────────────────────────────────────

def run_audit(url: str, strategy: str = "mobile") -> dict:
    """Run audit using PSI (with retry), falling back to Lighthouse CLI."""
    psi_error = None
    for attempt in range(3):
        try:
            if attempt > 0:
                wait = 15 * attempt
                print(f"  Retrying PSI in {wait}s (attempt {attempt+1}/3)...", flush=True)
                time.sleep(wait)
            data = run_psi(url, strategy)
            scores = extract_psi_scores(data)
            scores["source"] = "psi"
            return scores
        except urllib.error.HTTPError as e:
            psi_error = e
            if e.code == 429:
                print(f"  PSI rate limited (429), will retry...", flush=True)
                continue
            print(f"  PSI failed HTTP {e.code}, trying Lighthouse CLI...", flush=True)
            break
        except Exception as e:
            psi_error = e
            print(f"  PSI failed ({e}), trying Lighthouse CLI...", flush=True)
            break

    cli = find_lighthouse_cli()
    if cli:
        try:
            scores = run_lighthouse_cli(url, cli, strategy)
            scores["source"] = "lighthouse-cli"
            return scores
        except Exception as cli_err:
            raise RuntimeError(f"Both PSI and Lighthouse CLI failed. PSI: {psi_error}, CLI: {cli_err}")

    raise RuntimeError(f"PSI failed and no Lighthouse CLI found. PSI error: {psi_error}")


# ── History ───────────────────────────────────────────────────────────────────

def load_history() -> list:
    if LIGHTHOUSE_LOG.exists():
        try:
            return json.loads(LIGHTHOUSE_LOG.read_text())
        except json.JSONDecodeError:
            pass
    return []


def save_history(history: list, entry: dict) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    history.append(entry)
    history = history[-30:]  # keep 30 runs
    LIGHTHOUSE_LOG.write_text(json.dumps(history, indent=2))


def find_prev_scores(history: list, key: str) -> dict:
    """Find the most recent scores for a given URL key."""
    for run in reversed(history):
        result = run.get("results", {}).get(key)
        if result and "scores" in result:
            return result["scores"]
    return {}


# ── Reporting ─────────────────────────────────────────────────────────────────

def fmt_score(score) -> str:
    if score is None:
        return "n/a"
    return str(int(round(score * 100)))


def score_emoji(score) -> str:
    if score is None:
        return "⚪"
    if score >= 0.9:
        return "🟢"
    if score >= 0.5:
        return "🟡"
    return "🔴"


def detect_drops(scores: dict, prev: dict) -> list[str]:
    """Return list of alert strings for score drops > threshold."""
    alerts = []
    for cat in CATEGORIES:
        cur = scores.get(cat)
        prv = prev.get(cat)
        if cur is None or prv is None:
            continue
        drop = round((prv - cur) * 100)
        if drop > SCORE_DROP_THRESHOLD:
            label = CATEGORY_LABELS.get(cat, cat)
            alerts.append(f"⚠️ **{label}** dropped {drop} pts ({fmt_score(prv)} → {fmt_score(cur)})")
    return alerts


def format_discord_message(results: list, history: list, strategy: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"## 🔦 Lighthouse ({strategy}) — {now}"]

    all_alerts = []

    for result in results:
        url = result["url"]
        key = result["key"]
        scores = result["scores"]
        prev = find_prev_scores(history, key)

        # Page label
        if "posts" not in url:
            label = "🏠 Etusivu"
        else:
            slug = url.rstrip("/").split("/")[-1]
            label = f"📄 {slug[:40]}"

        lines.append(f"\n**{label}**")
        lines.append(f"`{url}`")

        score_parts = []
        for cat in CATEGORIES:
            cur = scores.get(cat)
            prv = prev.get(cat)
            s = fmt_score(cur)
            em = score_emoji(cur)
            delta = ""
            if cur is not None and prv is not None:
                diff = round((cur - prv) * 100)
                if diff > 0:
                    delta = f" **(+{diff})**"
                elif diff < 0:
                    delta = f" **({diff})**"
            lbl = CATEGORY_LABELS[cat]
            score_parts.append(f"{em} {lbl} **{s}**{delta}")

        lines.append("  ".join(score_parts))
        lines.append(
            f"> LCP {scores.get('lcp','n/a')}  ·  "
            f"CLS {scores.get('cls','n/a')}  ·  "
            f"TBT {scores.get('tbt','n/a')}  ·  "
            f"FCP {scores.get('fcp','n/a')}"
        )

        # Drops
        alerts = detect_drops(scores, prev)
        all_alerts.extend(alerts)

    if all_alerts:
        lines.append("\n**🚨 Score drops detected:**")
        lines.extend(all_alerts)

    return "\n".join(lines)


def post_to_discord(message: str) -> bool:
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
            print(f"Webhook error: {e.code}", file=sys.stderr)

    if BOT_TOKEN:
        url = f"https://discord.com/api/v10/channels/{METRICS_CHANNEL_ID}/messages"
        payload = json.dumps({"content": message}).encode()
        req = urllib.request.Request(
            url, data=payload,
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
            print(f"Bot token error: {e.code}", file=sys.stderr)

    return False


def get_latest_article_url() -> str:
    posts = sorted(CONTENT_DIR.glob("*.md"), reverse=True)
    for post in posts[:10]:
        text = post.read_text()
        if re.search(r"^draft:\s*true", text, re.MULTILINE):
            continue
        return f"{SITE_URL}/posts/{post.stem}/"
    return f"{SITE_URL}/posts/"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    strategy = "mobile"
    specific_url = None

    if "--strategy" in args:
        idx = args.index("--strategy")
        if idx + 1 < len(args):
            strategy = args[idx + 1]

    if "--url" in args:
        idx = args.index("--url")
        if idx + 1 < len(args):
            specific_url = args[idx + 1]

    print(f"🔦 Lighthouse check (strategy={strategy}, dry_run={dry_run})", flush=True)

    if specific_url:
        targets = [("custom", specific_url)]
    else:
        targets = [
            ("home", SITE_URL + "/"),
            ("article", get_latest_article_url()),
        ]

    history = load_history()
    run_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategy": strategy,
        "results": {},
    }
    results = []

    for key, url in targets:
        print(f"\n→ Auditing: {url}", flush=True)
        try:
            scores = run_audit(url, strategy)
            run_entry["results"][key] = {"url": url, "scores": scores}
            results.append({"key": key, "url": url, "scores": scores})
            src = scores.pop("source", "psi")
            print(
                f"  [{src}] Perf={fmt_score(scores['performance'])} "
                f"A11y={fmt_score(scores['accessibility'])} "
                f"BP={fmt_score(scores['best-practices'])} "
                f"SEO={fmt_score(scores['seo'])}"
            )
            scores["source"] = src  # restore
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            run_entry["results"][key] = {"url": url, "error": str(e)}

    if not results:
        print("No results obtained.", file=sys.stderr)
        sys.exit(1)

    message = format_discord_message(results, history, strategy)
    print(f"\n--- Discord message ---\n{message}\n---")

    if not dry_run:
        save_history(history, run_entry)
        ok = post_to_discord(message)
        print("✅ Posted to #metrics" if ok else "⚠️  Discord post failed (no webhook/token configured)")
    else:
        print("(dry-run: not posting or saving)")


if __name__ == "__main__":
    main()
