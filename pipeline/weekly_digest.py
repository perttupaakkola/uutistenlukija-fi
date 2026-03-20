#!/usr/bin/env python3
"""
Weekly pipeline metrics digest — week-over-week comparison.

Reads pipeline/logs/metrics_history.json (built by metrics_history.py).
Posts a formatted summary to Discord #metrics every Monday 09:00 Helsinki (07:00 UTC).

Usage:
    python3 pipeline/weekly_digest.py [--dry-run] [--webhook URL]

Env:
    DISCORD_METRICS_WEBHOOK   preferred
    DISCORD_PIPELINE_WEBHOOK  fallback

Cron (Monday 07:00 UTC = 09:00 Helsinki):
    0 7 * * 1 cd /home/pertt/.openclaw/workspace/projects/uutistenlukija && \
        python3 pipeline/weekly_digest.py >> pipeline/logs/weekly_digest.log 2>&1
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

PIPELINE_DIR = Path(__file__).parent
HISTORY_FILE = PIPELINE_DIR / "logs" / "metrics_history.json"

WEBHOOK = (
    os.environ.get("DISCORD_METRICS_WEBHOOK")
    or os.environ.get("DISCORD_PIPELINE_WEBHOOK")
    or ""
)


def _load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        print(f"[weekly_digest] {HISTORY_FILE} not found. Run metrics_history.py first.", file=sys.stderr)
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[weekly_digest] Failed to read history: {e}", file=sys.stderr)
        return []


def _days_in_range(history: list[dict], start: datetime, end: datetime) -> list[dict]:
    """Filter history records whose date falls in [start, end)."""
    result = []
    for rec in history:
        try:
            d = datetime.strptime(rec["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if start <= d < end:
                result.append(rec)
        except Exception:
            pass
    return result


def _sum(days: list[dict], *path: str) -> int:
    total = 0
    for d in days:
        v = d
        for p in path:
            if isinstance(v, dict):
                v = v.get(p, 0)
            else:
                v = 0
                break
        if isinstance(v, (int, float)):
            total += v
    return int(total)


def _avg(days: list[dict], *path: str) -> float | None:
    vals = []
    for d in days:
        v = d
        for p in path:
            if isinstance(v, dict):
                v = v.get(p)
            else:
                v = None
                break
        if isinstance(v, (int, float)):
            vals.append(v)
    return round(sum(vals) / len(vals), 1) if vals else None


def _pct(n: int, d: int) -> str:
    return f"{n / d * 100:.1f}%" if d else "—"


def _trend(curr, prev, higher_is_better=True) -> str:
    """Return ✅/⚠️/❌ trend indicator."""
    if curr is None or prev is None or prev == 0:
        return "➖"
    delta_pct = (curr - prev) / abs(prev) * 100
    if higher_is_better:
        if delta_pct > 5:
            return "✅"
        elif delta_pct >= -5:
            return "⚠️"
        else:
            return "❌"
    else:
        # Lower is better (e.g. errors, duration)
        if delta_pct < -5:
            return "✅"
        elif delta_pct <= 5:
            return "⚠️"
        else:
            return "❌"


def _delta_str(curr, prev, unit="", higher_is_better=True) -> str:
    """Format value with delta vs previous period."""
    if curr is None:
        return "—"
    curr_str = f"{curr}{unit}"
    if prev is None or prev == 0:
        return curr_str
    delta = curr - prev
    sign = "+" if delta >= 0 else ""
    icon = _trend(curr, prev, higher_is_better)
    return f"{curr_str}  ({sign}{delta:.0f}{unit} {icon})"


def build_digest(history: list[dict], ref_date: datetime | None = None) -> str:
    """Build the weekly digest message."""
    now = ref_date or datetime.now(timezone.utc)

    # This week: Mon 00:00 → Sun 23:59 (last full week before now)
    # We report on the week that just ended (last Mon–Sun)
    days_since_monday = now.weekday()  # 0=Mon
    this_week_end = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
    this_week_start = this_week_end - timedelta(days=7)
    prev_week_start = this_week_start - timedelta(days=7)
    prev_week_end = this_week_start

    this_week = _days_in_range(history, this_week_start, this_week_end)
    prev_week = _days_in_range(history, prev_week_start, prev_week_end)

    if not this_week:
        # Fall back to most recent 7 days of data available
        if history:
            latest = sorted(history, key=lambda d: d["date"])[-7:]
            this_week = latest
            this_week_start_str = latest[0]["date"]
            this_week_end_str = latest[-1]["date"]
        else:
            return "📊 **Viikkokooste** — ei dataa saatavilla."
        week_label = f"{this_week_start_str} – {this_week_end_str}"
    else:
        week_label = f"{this_week_start.strftime('%d.%m')}–{(this_week_end - timedelta(days=1)).strftime('%d.%m.%Y')}"

    # Core metrics
    published_curr = _sum(this_week, "content", "published")
    published_prev = _sum(prev_week, "content", "published")

    runs_curr = _sum(this_week, "runs", "total")
    success_curr = _sum(this_week, "runs", "success")
    runs_prev = _sum(prev_week, "runs", "total")
    success_prev = _sum(prev_week, "runs", "success")
    success_rate_curr = round(success_curr / runs_curr * 100, 1) if runs_curr else None
    success_rate_prev = round(success_prev / runs_prev * 100, 1) if runs_prev else None

    # Avg rewrite duration
    rewrite_curr = _avg(this_week, "step_avg_sec", "rewriter")
    rewrite_prev = _avg(prev_week, "step_avg_sec", "rewriter")

    # Image breakdown
    img_total = _sum(this_week, "images", "total")
    img_unsplash = _sum(this_week, "images", "unsplash")
    img_pexels = _sum(this_week, "images", "pexels")
    img_ai = _sum(this_week, "images", "ai")
    img_fallback = _sum(this_week, "images", "fallback")

    # Errors
    errors_curr = _sum(this_week, "error_count")
    errors_prev = _sum(prev_week, "error_count")

    # Days active
    days_active = len(this_week)

    lines = [
        f"📊 **Viikkokooste — {week_label}**",
        f"_{days_active} aktiivista päivää, {runs_curr} pipeline-ajoa_",
        "",
        "**📰 Julkaisut:**",
        f"  Tällä viikolla:  **{published_curr}** artikkelia  {_delta_str(published_curr, published_prev, '', True)}",
        "",
        "**✅ Pipeline-suorituskyky:**",
    ]

    if success_rate_curr is not None:
        lines.append(f"  Onnistumisprosentti: **{success_rate_curr}%**  {_delta_str(success_rate_curr, success_rate_prev, '%', True)}")
    else:
        lines.append("  Onnistumisprosentti: —")

    if rewrite_curr is not None:
        lines.append(f"  Uudelleenkirjoitusaika (avg): **{rewrite_curr}s**  {_delta_str(rewrite_curr, rewrite_prev, 's', False)}")

    if errors_curr or errors_prev:
        lines.append(f"  Virheitä: **{errors_curr}**  {_delta_str(errors_curr, errors_prev, '', False)}")

    # Image breakdown
    if img_total > 0:
        lines.append("")
        lines.append("**🖼 Kuvat (viikon yhteensä):**")
        if img_unsplash:
            lines.append(f"  Unsplash:  {img_unsplash}  ({_pct(img_unsplash, img_total)})")
        if img_pexels:
            lines.append(f"  Pexels:    {img_pexels}  ({_pct(img_pexels, img_total)})")
        if img_ai:
            lines.append(f"  AI-gen:    {img_ai}  ({_pct(img_ai, img_total)})")
        if img_fallback:
            lines.append(f"  Fallback:  {img_fallback}  ({_pct(img_fallback, img_total)}) ⚠️")

    lines.append("")
    lines.append(f"_Generoitu {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_")

    return "\n".join(lines)


def post(message: str, webhook: str) -> bool:
    payload = json.dumps({"content": message}).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status in (200, 204)
            print(f"[weekly_digest] Posted ({resp.status})")
            return ok
    except urllib.error.HTTPError as e:
        body = e.read(200).decode("utf-8", errors="replace")
        print(f"[weekly_digest] HTTP {e.code}: {body}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[weekly_digest] Failed: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Post weekly pipeline metrics digest to Discord.")
    parser.add_argument("--dry-run", action="store_true", help="Print digest without posting")
    parser.add_argument("--webhook", default="", help="Override Discord webhook URL")
    args = parser.parse_args()

    history = _load_history()
    digest = build_digest(history)

    webhook = args.webhook or WEBHOOK

    if args.dry_run:
        print(digest)
        return 0

    if not webhook:
        print("[weekly_digest] No webhook configured. Set DISCORD_METRICS_WEBHOOK or DISCORD_PIPELINE_WEBHOOK.", file=sys.stderr)
        print(digest)
        return 1

    return 0 if post(digest, webhook) else 1


if __name__ == "__main__":
    sys.exit(main())
