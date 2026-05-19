"""
Pipeline metrics report — post daily summary to #metrics via Discord webhook.

Reads logs/metrics.json (written by run_pipeline.py after each run).
Formats the content funnel, image source breakdown, step timings, and
trend vs previous period.

Usage:
    python3 metrics_report.py [--hours N] [--dry-run] [--webhook URL]

Env:
    DISCORD_METRICS_WEBHOOK   preferred (separate #metrics channel)
    DISCORD_PIPELINE_WEBHOOK  fallback

Cron example (08:00 Helsinki = 06:00 UTC):
    0 6 * * * cd /home/pertt/.openclaw/workspace/projects/uutistenlukija && \
        python3 pipeline/metrics_report.py >> pipeline/logs/metrics_report.log 2>&1
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

METRICS_FILE = Path(__file__).parent / "logs" / "metrics.json"

WEBHOOK = (
    os.environ.get("DISCORD_METRICS_WEBHOOK")
    or os.environ.get("DISCORD_PIPELINE_WEBHOOK")
    or ""
)


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_all() -> list[dict]:
    if not METRICS_FILE.exists():
        return []
    try:
        records = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            return []
        return records
    except Exception as e:
        print(f"[metrics_report] Failed to read metrics.json: {e}", file=sys.stderr)
        return []


def _filter_by_hours(records: list[dict], hours: int) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = []
    for r in records:
        try:
            ts = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
            if ts >= cutoff:
                result.append(r)
        except Exception:
            pass
    return result


# ── Aggregation helpers ───────────────────────────────────────────────────────

def _step(rec: dict, name: str) -> dict:
    return rec.get("steps", {}).get(name, {})


def _sum(records: list[dict], path: str) -> int:
    """Sum a dot-path value across records. e.g. 'steps.scanner.total'"""
    parts = path.split(".")
    total = 0
    for r in records:
        v = r
        for p in parts:
            if isinstance(v, dict):
                v = v.get(p)
            else:
                v = None
                break
        if isinstance(v, (int, float)):
            total += v
    return int(total)


def _avg_duration(records: list[dict], step_name: str) -> float | None:
    vals = [
        _step(r, step_name).get("duration_sec", 0)
        for r in records
        if step_name in r.get("steps", {})
    ]
    return round(sum(vals) / len(vals), 1) if vals else None


def _pct(num: int, denom: int) -> str:
    if not denom:
        return "—"
    return f"{num / denom * 100:.0f}%"


# ── Report builder ────────────────────────────────────────────────────────────

def build_report(records: list[dict], hours: int) -> str:
    if not records:
        label = "24h" if hours == 24 else f"{hours}h"
        return f"📊 **Pipeline — viimeiset {label}**\n_Ei dataa saatavilla._"

    total_runs   = len(records)
    success_runs = sum(1 for r in records if r.get("success"))
    failed_runs  = total_runs - success_runs
    success_rate = success_runs / total_runs * 100 if total_runs else 0

    # Content funnel
    scanned   = _sum(records, "steps.scanner.total")
    rss_in    = _sum(records, "steps.scanner.rss_count")
    fh_in     = _sum(records, "steps.scanner.firehose_count")
    after_dedup = _sum(records, "steps.dedup.remaining")
    rewritten = _sum(records, "steps.rewriter.output_count")
    qg_passed = _sum(records, "steps.quality_gate.passed")
    published = sum(r.get("article_count", 0) for r in records)

    # Image sources
    # Only count image stats from runs where the images step actually ran
    runs_with_images = [r for r in records if "images" in r.get("steps", {})]
    img_total    = _sum(runs_with_images, "steps.images.total")
    img_unsplash = _sum(runs_with_images, "steps.images.unsplash")
    img_pexels   = _sum(runs_with_images, "steps.images.pexels")
    img_ai       = _sum(runs_with_images, "steps.images.ai")
    img_fallback = _sum(runs_with_images, "steps.images.fallback")
    articles_in_img_runs = sum(r.get("article_count", 0) for r in runs_with_images)
    img_none = articles_in_img_runs - img_total if articles_in_img_runs > img_total else 0

    # Step timings (avg across runs)
    step_names = ["scanner", "dedup", "research", "rewriter", "images", "build"]
    step_avgs: dict[str, float] = {}
    for s in step_names:
        v = _avg_duration(records, s)
        if v is not None:
            step_avgs[s] = v

    # Total duration
    durations = [r["total_duration_sec"] for r in records if "total_duration_sec" in r]
    avg_total = round(sum(durations) / len(durations), 0) if durations else 0
    max_total = round(max(durations), 0) if durations else 0

    # Errors
    all_errors: list[str] = []
    for r in records:
        for e in r.get("errors", []):
            if e and len(all_errors) < 5:
                all_errors.append(str(e)[:160])

    # Status emoji
    if success_rate >= 90:
        status = "✅"
    elif success_rate >= 70:
        status = "⚠️"
    else:
        status = "🚨"

    label = "24h" if hours == 24 else f"{hours}h"
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"📊 **Pipeline-raportti — {label} | {now_str}**",
        "",
        f"{status} **Ajot:** {success_runs}/{total_runs} onnistui ({success_rate:.0f}%)",
        "",
        "**📥 Sisältöputki:**",
    ]

    # Funnel
    lines.append(f"  Skannattu:  **{scanned}**" + (f"  (RSS {rss_in} + Firehose {fh_in})" if rss_in or fh_in else ""))
    if after_dedup:
        dropped_dedup = scanned - after_dedup
        lines.append(f"  Deduplikointi: **{after_dedup}** jäljellä  (-{dropped_dedup} poistettiin)")
    if rewritten:
        lines.append(f"  Kirjoitettu uudelleen: **{rewritten}**  ({_pct(rewritten, after_dedup or scanned)} läpäisi)")
    if qg_passed:
        dropped_qg = rewritten - qg_passed
        lines.append(f"  Laadun tarkistus: **{qg_passed}** hyväksytty" + (f"  (-{dropped_qg} hylätty)" if dropped_qg else ""))
    lines.append(f"  ✅ Julkaistu: **{published}** artikkelia")

    # Image breakdown
    if runs_with_images and (img_total or img_fallback or img_none):
        lines.append("")
        lines.append("**🖼 Kuvat:**")
        if img_unsplash:
            lines.append(f"  Unsplash: {img_unsplash}")
        if img_pexels:
            lines.append(f"  Pexels:   {img_pexels}")
        if img_ai:
            lines.append(f"  AI-gen:   {img_ai}")
        if img_fallback:
            lines.append(f"  Kategoriakuva (fallback): {img_fallback}")
        if img_none:
            lines.append(f"  Ei kuvaa: {img_none} ⚠️")

    # Step timings
    if step_avgs:
        lines.append("")
        lines.append("**⏱ Vaiheiden kestoajat (avg/ajo):**")
        step_labels = {
            "scanner": "Skanneri",
            "dedup": "Dedup",
            "research": "Tutkimus",
            "rewriter": "Uudelleenkirjoitus",
            "images": "Kuvat",
            "build": "Hugo build",
        }
        for s, dur in step_avgs.items():
            lines.append(f"  {step_labels.get(s, s)}: {dur}s")
        lines.append(f"  **Yhteensä (avg): {int(avg_total)}s, max {int(max_total)}s**")

    # Errors
    if all_errors:
        lines.append("")
        lines.append("**⚠️ Virheet:**")
        for e in all_errors:
            lines.append(f"  • {e}")
    elif failed_runs:
        lines.append(f"\n⚠️ {failed_runs} epäonnistunutta ajoa — tarkista lokit.")

    return "\n".join(lines)


# ── Discord posting ───────────────────────────────────────────────────────────

def post(message: str, webhook: str) -> bool:
    payload = json.dumps({"content": message}).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Hermes-Uutistenlukija/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status in (200, 204)
            print(f"[metrics_report] Posted ({resp.status})")
            return ok
    except urllib.error.HTTPError as e:
        body = e.read(200).decode("utf-8", errors="replace")
        print(f"[metrics_report] HTTP {e.code}: {body}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[metrics_report] Failed: {e}", file=sys.stderr)
        return False


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Post pipeline metrics report to Discord.")
    parser.add_argument("--hours", type=int, default=24,
                        help="Lookback window in hours (default: 24)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print report without posting")
    parser.add_argument("--webhook", default="",
                        help="Override Discord webhook URL")
    args = parser.parse_args()

    webhook = args.webhook or WEBHOOK

    all_records = _load_all()
    records = _filter_by_hours(all_records, args.hours)
    report = build_report(records, args.hours)

    if args.dry_run:
        print(report)
        return 0

    if not webhook:
        print("[metrics_report] No webhook configured. Set DISCORD_METRICS_WEBHOOK or DISCORD_PIPELINE_WEBHOOK.", file=sys.stderr)
        print(report)
        return 1

    return 0 if post(report, webhook) else 1


if __name__ == "__main__":
    sys.exit(main())
