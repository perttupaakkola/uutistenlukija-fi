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
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

PIPELINE_DIR = Path(__file__).parent
HISTORY_FILE = PIPELINE_DIR / "logs" / "metrics_history.json"
IMAGE_BACKFILL_FILE = PIPELINE_DIR / "logs" / "image_backfill.json"
METRICS_FILE = PIPELINE_DIR / "logs" / "metrics.json"
CONTENT_DIR = PIPELINE_DIR.parent / "content" / "posts"

WEBHOOK = (
    os.environ.get("DISCORD_METRICS_WEBHOOK")
    or os.environ.get("DISCORD_PIPELINE_WEBHOOK")
    or ""
)

DISCORD_MAX_LEN = 1900  # safe limit below 2000


# ── Data loading ──────────────────────────────────────────────────────────────

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


def _load_metrics_runs() -> list[dict]:
    """Load raw per-run records from metrics.json for detailed failure analysis."""
    if not METRICS_FILE.exists():
        return []
    try:
        data = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _load_image_backfill() -> list[dict]:
    if not IMAGE_BACKFILL_FILE.exists():
        return []
    try:
        data = json.loads(IMAGE_BACKFILL_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


# ── Aggregation helpers ───────────────────────────────────────────────────────

def _days_in_range(history: list[dict], start: datetime, end: datetime) -> list[dict]:
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
            v = v.get(p, 0) if isinstance(v, dict) else 0
        if isinstance(v, (int, float)):
            total += v
    return int(total)


def _avg(days: list[dict], *path: str) -> float | None:
    vals = []
    for d in days:
        v = d
        for p in path:
            v = v.get(p) if isinstance(v, dict) else None
        if isinstance(v, (int, float)):
            vals.append(v)
    return round(sum(vals) / len(vals), 1) if vals else None


def _pct(n: int, d: int) -> str:
    return f"{n / d * 100:.0f}%" if d else "—"


def _trend(curr, prev, higher_is_better=True) -> str:
    if curr is None or prev is None or prev == 0:
        return "➖"
    delta_pct = (curr - prev) / abs(prev) * 100
    if higher_is_better:
        return "✅" if delta_pct > 5 else ("⚠️" if delta_pct >= -5 else "❌")
    else:
        return "✅" if delta_pct < -5 else ("⚠️" if delta_pct <= 5 else "❌")


def _delta(curr, prev, unit="", higher_is_better=True, fmt=".0f") -> str:
    if curr is None:
        return "—"
    curr_str = f"{curr:{fmt}}{unit}"
    if prev is None or prev == 0:
        return curr_str
    delta = curr - prev
    sign = "+" if delta >= 0 else ""
    icon = _trend(curr, prev, higher_is_better)
    return f"{curr_str} ({sign}{delta:{fmt}}{unit} {icon})"


# ── Section builders ──────────────────────────────────────────────────────────

def _section_core(this_week, prev_week) -> list[str]:
    published_curr = _sum(this_week, "content", "published")
    published_prev = _sum(prev_week, "content", "published")
    runs_curr = _sum(this_week, "runs", "total")
    success_curr = _sum(this_week, "runs", "success")
    runs_prev = _sum(prev_week, "runs", "total")
    success_prev = _sum(prev_week, "runs", "success")
    sr_curr = round(success_curr / runs_curr * 100, 1) if runs_curr else None
    sr_prev = round(success_prev / runs_prev * 100, 1) if runs_prev else None
    avg_dur = _avg(this_week, "duration", "avg_sec")
    avg_dur_prev = _avg(prev_week, "duration", "avg_sec")

    lines = ["**📊 Viikon tunnusluvut**"]
    lines.append(f"  Artikkeleita julkaistu: **{published_curr}**  {_delta(published_curr, published_prev, '', True)}")
    lines.append(f"  Pipeline-ajoja: {runs_curr}  ({success_curr} onnistui)")
    if sr_curr is not None:
        lines.append(f"  Onnistumisprosentti: **{sr_curr}%**  {_delta(sr_curr, sr_prev, '%', True)}")
    if avg_dur is not None:
        lines.append(f"  Keskim. ajon kesto: {avg_dur}s  {_delta(avg_dur, avg_dur_prev, 's', False)}")
    return lines


def _section_daily(this_week) -> list[str]:
    if not this_week:
        return []
    lines = ["**📅 Päiväkohtainen erittely**"]
    for day in sorted(this_week, key=lambda d: d["date"]):
        date_str = datetime.strptime(day["date"], "%Y-%m-%d").strftime("%d.%m")
        runs = day.get("runs", {})
        total = runs.get("total", 0)
        success = runs.get("success", 0)
        published = day.get("content", {}).get("published", 0)
        sr = f"{success/total*100:.0f}%" if total else "—"
        lines.append(f"  {date_str}  ajoja:{total}  ok:{success} ({sr})  julk:{published}")
    return lines


def _section_failures(this_week, all_runs: list[dict], week_start: datetime, week_end: datetime) -> list[str]:
    """Top 3 failure reasons from errors_sample in history + raw runs in window."""
    # Collect from history errors_sample
    error_counter: Counter = Counter()
    for day in this_week:
        for err in day.get("errors_sample", []):
            # Normalise
            e = err.lower()
            if "no articles" in e or "empty" in e or "scan" in e:
                error_counter["Ei artikkeleita (tyhjä skannaus)"] += 1
            elif "timeout" in e or "exit code 124" in e:
                error_counter["Rewriter timeout"] += 1
            elif "build" in e or "hugo" in e:
                error_counter["Hugo-buildaus epäonnistui"] += 1
            elif "broken pipe" in e:
                error_counter["Broken pipe (skanneri)"] += 1
            elif "import" in e or "nameerror" in e or "attributeerror" in e:
                error_counter["Python-importtivirhe"] += 1
            elif "api" in e or "openai" in e or "openrouter" in e:
                error_counter["LLM API -virhe"] += 1
            else:
                error_counter[err[:40]] += 1

    # Also scan raw run records in the week window
    for run in all_runs:
        try:
            ts = datetime.fromisoformat(run.get("timestamp", "").replace("Z", "+00:00"))
            if not (week_start <= ts < week_end):
                continue
        except Exception:
            continue
        if run.get("success"):
            continue
        err = (run.get("error") or "").lower()
        if err:
            if "no articles" in err or "empty" in err:
                error_counter["Ei artikkeleita (tyhjä skannaus)"] += 1
            elif "timeout" in err:
                error_counter["Rewriter timeout"] += 1
            elif "build" in err:
                error_counter["Hugo-buildaus epäonnistui"] += 1

    if not error_counter:
        return []

    total_errors = sum(error_counter.values())
    lines = [f"**❌ Top 3 vikasyytä** (yhteensä {total_errors} virhettä)"]
    for i, (reason, count) in enumerate(error_counter.most_common(3), 1):
        pct = f"{count/total_errors*100:.0f}%"
        lines.append(f"  {i}. {reason} — {count}x ({pct})")
    return lines


def _section_images(this_week) -> list[str]:
    img_total = _sum(this_week, "images", "total")
    if img_total == 0:
        # Try from image_backfill
        backfill = _load_image_backfill()
        if not backfill:
            return []
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        recent = [r for r in backfill if r.get("timestamp", "") >= week_ago]
        if not recent:
            recent = backfill  # fallback: show all-time
        sources: Counter = Counter(r.get("source") or "none" for r in recent)
        total = sum(sources.values())
        ok = sum(1 for r in recent if r.get("status") == "ok")
        failed = sum(1 for r in recent if r.get("status") == "failed")
        lines = [f"**🖼 Kuvat** (backfill, {len(recent)} artikkelia)"]
        for src, cnt in sources.most_common():
            lines.append(f"  {src.capitalize()}: {cnt} ({_pct(cnt, total)})")
        if failed:
            lines.append(f"  ⚠️ Epäonnistui: {failed}")
        return lines

    img_unsplash = _sum(this_week, "images", "unsplash")
    img_pexels = _sum(this_week, "images", "pexels")
    img_ai = _sum(this_week, "images", "ai")
    img_fallback = _sum(this_week, "images", "fallback")

    lines = [f"**🖼 Kuvat** (viikon {img_total} artikkelia)"]
    if img_unsplash:
        lines.append(f"  Unsplash: {img_unsplash} ({_pct(img_unsplash, img_total)})")
    if img_pexels:
        lines.append(f"  Pexels:   {img_pexels} ({_pct(img_pexels, img_total)})")
    if img_ai:
        lines.append(f"  AI-gen:   {img_ai} ({_pct(img_ai, img_total)})")
    if img_fallback:
        lines.append(f"  Fallback: {img_fallback} ({_pct(img_fallback, img_total)}) ⚠️")
    if img_total == img_unsplash + img_pexels + img_ai + img_fallback == 0:
        lines.append("  Ei kuvia tällä viikolla")
    return lines


def _section_backfill() -> list[str]:
    """Backfill progress — articles expanded this week, remaining."""
    if not CONTENT_DIR.exists():
        return []
    import re
    articles = list(CONTENT_DIR.glob("**/*.md"))
    total = len(articles)
    if not total:
        return []

    # Count articles by word count tiers
    tier_counts = {"<50": 0, "50-200": 0, "200-500": 0, "500+": 0}
    this_week_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).timestamp()
    expanded_this_week = 0

    for art in articles:
        try:
            text = art.read_text(encoding="utf-8", errors="ignore")
            # Strip frontmatter
            body = re.sub(r'^---.*?---\s*', '', text, flags=re.DOTALL)
            words = len(body.split())
            if words < 50:
                tier_counts["<50"] += 1
            elif words < 200:
                tier_counts["50-200"] += 1
            elif words < 500:
                tier_counts["200-500"] += 1
            else:
                tier_counts["500+"] += 1
            # Expanded this week = recently modified + word count >=200
            if art.stat().st_mtime >= this_week_cutoff and words >= 200:
                expanded_this_week += 1
        except Exception:
            pass

    thin = tier_counts["<50"] + tier_counts["50-200"]
    lines = [f"**📈 Sisällön tila** ({total} artikkelia yhteensä)"]
    lines.append(f"  Laajennettu tällä viikolla: {expanded_this_week}")
    lines.append(f"  Ohut sisältö (<200 sanaa): {thin} ({_pct(thin, total)})")
    if tier_counts["<50"]:
        lines.append(f"    • Kriittisen ohut (<50): {tier_counts['<50']}")
    lines.append(f"  Hyvä sisältö (500+ sanaa): {tier_counts['500+']} ({_pct(tier_counts['500+'], total)})")
    return lines


# ── Main builder ──────────────────────────────────────────────────────────────

def build_digest(history: list[dict], ref_date: datetime | None = None) -> str:
    now = ref_date or datetime.now(timezone.utc)

    # Last full week (Mon–Sun before today)
    days_since_monday = now.weekday()
    this_week_end = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
    this_week_start = this_week_end - timedelta(days=7)
    prev_week_start = this_week_start - timedelta(days=7)
    prev_week_end = this_week_start

    this_week = _days_in_range(history, this_week_start, this_week_end)
    prev_week = _days_in_range(history, prev_week_start, prev_week_end)

    if not this_week:
        # Fall back: most recent 7 days available
        if history:
            sorted_hist = sorted(history, key=lambda d: d["date"])
            this_week = sorted_hist[-7:]
            this_week_start = datetime.strptime(this_week[0]["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            this_week_end = datetime.strptime(this_week[-1]["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
        else:
            return "📊 **Viikkokooste** — ei dataa saatavilla."

    week_label = (
        f"{this_week_start.strftime('%d.%m')}–"
        f"{(this_week_end - timedelta(days=1)).strftime('%d.%m.%Y')}"
    )

    all_runs = _load_metrics_runs()

    sections = [
        [f"📊 **Viikkokooste — {week_label}**", ""],
        _section_core(this_week, prev_week),
        [""],
        _section_daily(this_week),
        [""],
        _section_failures(this_week, all_runs, this_week_start, this_week_end),
        [""],
        _section_images(this_week),
        [""],
        _section_backfill(),
        [""],
        [f"_Generoitu {now.strftime('%Y-%m-%d %H:%M UTC')}_"],
    ]

    lines = []
    for section in sections:
        lines.extend(section)

    # Remove consecutive blank lines
    result = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        result.append(line)
        prev_blank = is_blank

    return "\n".join(result)


# ── Discord posting ───────────────────────────────────────────────────────────

def _post_chunk(message: str, webhook: str) -> bool:
    payload = json.dumps({"content": message}).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Hermes-Uutistenlukija/1.0"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[weekly_digest] Posted chunk ({resp.status})")
            return resp.status in (200, 204)
    except urllib.error.HTTPError as e:
        print(f"[weekly_digest] HTTP {e.code}: {e.read(200).decode('utf-8', 'replace')}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[weekly_digest] Failed: {e}", file=sys.stderr)
        return False


def post(message: str, webhook: str) -> bool:
    """Post message to Discord, splitting into chunks if needed."""
    if len(message) <= DISCORD_MAX_LEN:
        return _post_chunk(message, webhook)
    # Split at paragraph boundaries (blank lines)
    chunks, current = [], []
    current_len = 0
    for line in message.splitlines(keepends=True):
        if current_len + len(line) > DISCORD_MAX_LEN and current:
            chunks.append("".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += len(line)
    if current:
        chunks.append("".join(current))

    ok = True
    for i, chunk in enumerate(chunks, 1):
        print(f"[weekly_digest] Posting chunk {i}/{len(chunks)}")
        ok = _post_chunk(chunk.rstrip(), webhook) and ok
    return ok


# ── CLI ───────────────────────────────────────────────────────────────────────

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
