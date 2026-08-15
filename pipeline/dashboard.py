#!/usr/bin/env python3
"""
dashboard.py — Pipeline monitoring dashboard for uutistenlukija.fi

Parses pipeline/logs/ data and outputs a summary in one command.
No external dependencies. Reads:
  - pipeline/logs/publish-metrics.json  (JSONL per-run stats)
  - pipeline/logs/quality_gate_rejects.log (TSV rejection reasons)
  - pipeline/logs/feed-health.json     (per-feed health state)
  - content/posts/*.md                  (trending keywords)

Usage:
    python3 pipeline/dashboard.py              # last 24h
    python3 pipeline/dashboard.py --hours 48   # last 48h
    python3 pipeline/dashboard.py --json       # machine-readable JSON
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT  = SCRIPT_DIR.parent

# Finnish stopwords to exclude from trending keywords
STOPWORDS = {
    # Conjunctions / particles
    "että", "joka", "jotka", "kun", "ja", "tai", "sekä", "vaan", "mutta",
    "jos", "joten", "koska", "kuin", "niin", "myös", "kuitenkin", "lisäksi",
    "sitten", "vielä", "jo", "aina", "ainoa", "mukaan",
    # Pronouns
    "on", "ei", "ole", "se", "hän", "he", "me", "te",
    "sen", "sitä", "tämä", "tässä", "tähän", "hänen", "tätä",
    "niiden", "niitä", "joita", "joilla", "jolla", "jolle",
    "jonka", "jossa", "josta", "jota", "jolta", "johon", "kaikki", "koko",
    "siitä",
    # Verb forms
    "olla", "ollut", "oli", "ovat", "olisi",
    "sai", "saa", "saada", "saan", "saakka", "saatu", "saatua",
    "tuli", "tulee", "tulla", "tuleva", "tulevat",
    "voivat", "voisi", "voi", "voida",
    "on", "ovat", "olisi", "oli",
    "sillä",  # "because" / instrumental pronoun
    "kuten",  # "such as"
    "sekä",
    # Nouns too generic to be meaningful
    "uusi", "uuden", "muun", "muut", "muu",
    "suuri", "suuren",
    "päivä", "vuosi", "vuotta",
    "asia", "asiaa", "asiat",
    "suomessa", "suomen", "suomi", "helsinki",
    # English stopwords (some articles still slip through)
    "the", "and", "for", "that", "with", "this", "has", "are", "was",
    "from", "not", "but", "have", "been", "its", "more",
}


# ── Data loaders ─────────────────────────────────────────────────────────────

PUBLISH_CYCLE_SCHEMA = "uutistenlukija.staged_publish_cycle.v1"


def _metric_timestamp(record: dict) -> datetime | None:
    try:
        timestamp = datetime.fromisoformat(str(record.get("ts") or ""))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def load_metrics(
    hours: int = 24,
    actions_cycle_path: Path | None = None,
) -> list[dict]:
    """Load local history plus one Actions-native clean-runner cycle."""
    path = SCRIPT_DIR / "logs" / "publish-metrics.json"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    runs: list[dict] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = _metric_timestamp(record) if isinstance(record, dict) else None
            if timestamp and timestamp >= cutoff:
                runs.append(record)

    if actions_cycle_path and actions_cycle_path.is_file():
        try:
            actions_record = json.loads(actions_cycle_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            actions_record = None
        if (
            isinstance(actions_record, dict)
            and actions_record.get("schema") == PUBLISH_CYCLE_SCHEMA
            and (timestamp := _metric_timestamp(actions_record)) is not None
            and timestamp >= cutoff
        ):
            runs.append(actions_record)

    # A host log may already contain the same Actions cycle. Prefer the final
    # Actions-native record without counting the admitted run twice.
    deduplicated: dict[str, tuple[datetime, dict]] = {}
    anonymous: list[tuple[datetime, dict]] = []
    for record in runs:
        timestamp = _metric_timestamp(record)
        if timestamp is None:
            continue
        cycle_id = str(record.get("cycle_id") or "").strip()
        if cycle_id:
            deduplicated[cycle_id] = (timestamp, record)
        else:
            anonymous.append((timestamp, record))
    combined = [*anonymous, *deduplicated.values()]
    combined.sort(key=lambda item: item[0])
    return [record for _, record in combined]


def load_rejects(hours: int = 24) -> list[dict]:
    """Load quality_gate_rejects.log TSV for the last N hours."""
    path = SCRIPT_DIR / "logs" / "quality_gate_rejects.log"
    if not path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rejects = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        try:
            ts = datetime.fromisoformat(parts[0].strip())
            if ts >= cutoff:
                rejects.append({
                    "ts": ts,
                    "words": parts[1].strip(),
                    "slug": parts[2].strip(),
                    "reason": parts[3].strip(),
                    "title": parts[4].strip() if len(parts) > 4 else "",
                })
        except (ValueError, IndexError):
            pass
    return rejects


def load_feed_health() -> dict:
    """Load feed-health.json."""
    path = SCRIPT_DIR / "logs" / "feed-health.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def recent_post_dates(hours: int = 24) -> list[datetime]:
    """Return publication datetimes for posts in the last N hours."""
    posts_dir = REPO_ROOT / "content" / "posts"
    if not posts_dir.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    dates: list[datetime] = []

    for md in sorted(posts_dir.glob("*.md"), reverse=True)[:300]:
        text = md.read_text(errors="replace")
        date_m = re.search(r"^date:\s*(.+)$", text, re.MULTILINE)
        if not date_m:
            continue
        try:
            pub_date = datetime.fromisoformat(date_m.group(1).strip().strip('"\''))
            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=timezone.utc)
            if pub_date < cutoff:
                continue
            dates.append(pub_date)
        except ValueError:
            continue
    return sorted(dates)


def trending_keywords(hours: int = 24, top_n: int = 5) -> list[tuple[str, int]]:
    """Extract top N keywords from articles published in the last N hours."""
    posts_dir = REPO_ROOT / "content" / "posts"
    if not posts_dir.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    word_counts: Counter = Counter()

    for md in sorted(posts_dir.glob("*.md"), reverse=True)[:200]:  # limit scan
        text = md.read_text(errors="replace")
        # Parse date from frontmatter
        date_m = re.search(r"^date:\s*(.+)$", text, re.MULTILINE)
        if not date_m:
            continue
        try:
            pub_date = datetime.fromisoformat(date_m.group(1).strip().strip('"\''))
            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=timezone.utc)
            if pub_date < cutoff:
                continue
        except ValueError:
            continue

        # Strip frontmatter, extract body
        if text.startswith("---"):
            end = text.find("---", 3)
            body = text[end + 3:].strip() if end != -1 else text
        else:
            body = text
        body = re.sub(r"!\[.*?\]\(.*?\)", "", body)
        body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
        body = re.sub(r"<[^>]+>", "", body)
        body = re.sub(r"[^a-zA-ZäöåÄÖÅ\s-]", " ", body)

        for word in body.lower().split():
            word = word.strip("-")
            if len(word) >= 5 and word not in STOPWORDS:
                word_counts[word] += 1

    return word_counts.most_common(top_n)


# ── Formatting helpers ────────────────────────────────────────────────────────

def _bar(value: int, max_value: int, width: int = 20, char: str = "█") -> str:
    if max_value == 0:
        return " " * width
    filled = int(round(value / max_value * width))
    return char * filled + "░" * (width - filled)


def _pct(a: int, b: int) -> str:
    return f"{a/b*100:.0f}%" if b else "—"


# ── Main dashboard ────────────────────────────────────────────────────────────

STALE_THRESHOLD_MINUTES = 90   # daytime publishing gap threshold
ACTIVE_HOURS_UTC = (6, 22)     # 06:00–22:00 UTC — hours when staleness matters


def build_dashboard(
    hours: int = 24,
    actions_cycle_path: Path | None = None,
) -> dict:
    runs    = load_metrics(hours, actions_cycle_path)
    rejects = load_rejects(hours)
    health  = load_feed_health()
    trends  = trending_keywords(hours)
    recent_posts = recent_post_dates(hours)

    # ── Run stats
    total_runs   = len(runs)
    ok_runs      = sum(1 for r in runs if r.get("outcome") == "ok")
    skip_runs    = sum(1 for r in runs if r.get("outcome") == "skip")
    error_runs   = sum(1 for r in runs if r.get("outcome") == "error")
    attempted    = sum(r.get("attempted", 0) for r in runs)
    published    = sum(r.get("published", 0) for r in runs)
    staged_cycles = [
        record for record in runs
        if record.get("schema") == PUBLISH_CYCLE_SCHEMA
    ]
    admitted_cycles = sum(1 for record in staged_cycles if record.get("admitted") is True)
    cycle_action_counts: Counter = Counter()
    for record in staged_cycles:
        supply = record.get("supply") if isinstance(record.get("supply"), dict) else {}
        actions = supply.get("action_counts") if isinstance(supply.get("action_counts"), dict) else {}
        for action in ("publish", "monica_review", "reject"):
            try:
                cycle_action_counts[action] += max(0, int(actions.get(action) or 0))
            except (TypeError, ValueError):
                continue
    latest_cycle = None
    if staged_cycles:
        record = staged_cycles[-1]
        supply = record.get("supply") if isinstance(record.get("supply"), dict) else {}
        actions = supply.get("action_counts") if isinstance(supply.get("action_counts"), dict) else {}
        latest_cycle = {
            "cycleId": record.get("cycle_id"),
            "ts": record.get("ts"),
            "admitted": record.get("admitted") is True,
            "outcome": record.get("outcome"),
            "result": record.get("result"),
            "rawOutbox": supply.get("raw_outbox", 0),
            "publishEligible": actions.get("publish", 0),
            "monicaReview": actions.get("monica_review", 0),
            "reject": actions.get("reject", 0),
            "published": record.get("published", 0),
        }

    # ── Reject reasons
    reason_counts: Counter = Counter()
    for r in rejects:
        # Split compound reasons: "too_short | lead paragraph too short"
        for part in r["reason"].split("|"):
            part = part.strip()
            # Normalize to short label
            if "too_short" in part:
                reason_counts["too_short"] += 1
            elif "keyword stuffing" in part:
                reason_counts["keyword_stuffing"] += 1
            elif "lead paragraph" in part:
                reason_counts["lead_too_short"] += 1
            elif "few_paragraphs" in part:
                reason_counts["few_paragraphs"] += 1
            elif part:
                reason_counts[part[:30]] += 1

    # ── Feed health
    feed_total    = len(health)
    feed_disabled = sum(1 for e in health.values() if e.get("auto_disabled"))
    feed_stale    = sum(1 for e in health.values() if e.get("stale") and not e.get("auto_disabled"))
    feed_healthy  = feed_total - feed_disabled - feed_stale

    # Find most-recently published article
    last_pub_ts = None
    for r in reversed(runs):
        if r.get("published", 0) > 0:
            try:
                last_pub_ts = datetime.fromisoformat(r["ts"])
            except ValueError:
                pass
            break

    if recent_posts:
        if published == 0:
            published = len(recent_posts)
        if last_pub_ts is None or recent_posts[-1] > last_pub_ts:
            last_pub_ts = recent_posts[-1]

    # ── Staleness check
    now = datetime.now(timezone.utc)
    current_hour = now.hour
    in_active_hours = ACTIVE_HOURS_UTC[0] <= current_hour < ACTIVE_HOURS_UTC[1]
    is_stale = False
    if last_pub_ts is not None and in_active_hours:
        age_minutes = (now - last_pub_ts).total_seconds() / 60
        if age_minutes > STALE_THRESHOLD_MINUTES:
            is_stale = True
    pipeline_status = "degraded" if is_stale else "ok"

    return {
        "hours": hours,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": pipeline_status,
        "is_stale": is_stale,
        "stale_threshold_minutes": STALE_THRESHOLD_MINUTES,
        "runs": {
            "total": total_runs,
            "ok": ok_runs,
            "skip": skip_runs,
            "error": error_runs,
            "admitted": admitted_cycles,
        },
        "stagedPublishCycles": {
            "total": len(staged_cycles),
            "admitted": admitted_cycles,
            "publishEligible": cycle_action_counts["publish"],
            "monicaReview": cycle_action_counts["monica_review"],
            "reject": cycle_action_counts["reject"],
            "published": sum(record.get("published", 0) for record in staged_cycles),
            "latest": latest_cycle,
        },
        "articles": {
            "attempted": attempted,
            "published": published,
            "rejected": len(rejects),
            "publish_rate": round(published / attempted * 100, 1) if attempted else 0,
            "last_published_ts": last_pub_ts.isoformat() if last_pub_ts else None,
        },
        "reject_reasons": dict(reason_counts.most_common(8)),
        "feeds": {
            "total": feed_total,
            "healthy": feed_healthy,
            "disabled": feed_disabled,
            "stale": feed_stale,
            "stale_names": [n for n, e in health.items() if e.get("stale") and not e.get("auto_disabled")],
            "disabled_names": [n for n, e in health.items() if e.get("auto_disabled")],
        },
        "trending": trends,
    }


def print_dashboard(d: dict) -> None:
    hours = d["hours"]
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    runs  = d["runs"]
    arts  = d["articles"]
    feeds = d["feeds"]

    W = 60
    print()
    print("╔" + "═" * (W-2) + "╗")
    print(f"║{'Uutistenlukija — Pipeline Dashboard':^{W-2}}║")
    print(f"║{f'Last {hours}h  ·  {now_str}':^{W-2}}║")
    print("╠" + "═" * (W-2) + "╣")

    # ── Pipeline runs
    total = runs["total"]
    print(f"║  {'PIPELINE RUNS':30s}  {total:>4} runs in {hours}h   ║")
    if total:
        ok_bar = _bar(runs["ok"],    total, 14)
        sk_bar = _bar(runs["skip"],  total, 14)
        er_bar = _bar(runs["error"], total, 14)
        print(f"║    ✅ OK   {ok_bar}  {runs['ok']:>4} ({_pct(runs['ok'],   total):>4})  ║")
        print(f"║    ⏭ skip  {sk_bar}  {runs['skip']:>4} ({_pct(runs['skip'],  total):>4})  ║")
        err_icon = "❌" if runs["error"] else "  "
        print(f"║    {err_icon} error {er_bar}  {runs['error']:>4} ({_pct(runs['error'], total):>4})  ║")

    print("╠" + "─" * (W-2) + "╣")

    # ── Articles
    print(f"║  {'ARTICLES':30s}                       ║")
    print(f"║    Attempted  (scanned→rewriter)  {arts['attempted']:>6}               ║")
    print(f"║    Published  ✅                  {arts['published']:>6}  ({_pct(arts['published'],arts['attempted']):>4} rate)  ║")
    print(f"║    Rejected   (quality gate)      {arts['rejected']:>6}               ║")

    # Last published
    lp = arts.get("last_published_ts")
    if lp:
        try:
            lp_dt = datetime.fromisoformat(lp)
            age = datetime.now(timezone.utc) - lp_dt
            h, m = divmod(int(age.total_seconds()), 3600)
            m = m // 60
            age_str = f"{h}h {m:02d}m ago" if h else f"{m}m ago"
        except ValueError:
            age_str = lp[:16]
        print(f"║    Last publish: {age_str:<40} ║")
    else:
        print(f"║    Last publish: no data{'':<32} ║")

    # Reject breakdown
    if d["reject_reasons"]:
        print("╠" + "─" * (W-2) + "╣")
        print(f"║  {'QUALITY GATE REJECTS':30s}                       ║")
        max_r = max(d["reject_reasons"].values()) if d["reject_reasons"] else 1
        for reason, count in d["reject_reasons"].items():
            bar = _bar(count, max_r, 10)
            print(f"║    {reason:<26} {bar}  {count:>3}              ║")

    print("╠" + "─" * (W-2) + "╣")

    # ── Feed health
    print(f"║  {'FEED HEALTH':30s}                       ║")
    h_icon = "✅" if feeds["disabled"] == 0 and feeds["stale"] == 0 else "⚠️"
    print(f"║    {h_icon} {feeds['healthy']}/{feeds['total']} healthy"
          f"   🚫 {feeds['disabled']} disabled"
          f"   ⚠️ {feeds['stale']} stale          ║")
    for name in feeds.get("stale_names", []):
        print(f"║    ⚠️  Stale: {name:<42} ║")
    for name in feeds.get("disabled_names", []):
        print(f"║    🚫 Disabled: {name:<40} ║")

    # ── Trending
    if d["trending"]:
        print("╠" + "─" * (W-2) + "╣")
        print(f"║  {'TRENDING KEYWORDS (last ' + str(hours) + 'h)':30s}                       ║")
        max_kw = d["trending"][0][1] if d["trending"] else 1
        for i, (word, count) in enumerate(d["trending"], 1):
            bar = _bar(count, max_kw, 12)
            print(f"║    {i}. {word:<22} {bar}  {count:>3}              ║")

    print("╚" + "═" * (W-2) + "╝")
    print()


def main():
    parser = argparse.ArgumentParser(description="Uutistenlukija pipeline dashboard")
    parser.add_argument("--hours", type=int, default=24, help="Time window in hours (default 24)")
    parser.add_argument("--json",  action="store_true", help="Output JSON instead of formatted table")
    args = parser.parse_args()

    d = build_dashboard(hours=args.hours)

    if args.json:
        print(json.dumps(d, indent=2, ensure_ascii=False, default=str))
    else:
        print_dashboard(d)


if __name__ == "__main__":
    main()
