"""Readership measurement and the ranked-hypothesis feedback loop.

The pipeline published articles but never read a single number back: `ga4_id` existed
only as a string written into the publish receipt. Nothing connected what was published
to what was read, so nothing could learn.

This module closes that loop:

  measure()   -> pull GA4 + GSC through the read-only analytics CLI
  attribute() -> join per-article performance back to published article metadata
  diagnose()  -> turn the joined evidence into ranked, checkable hypotheses
  ledger()    -> persist every experiment and its verdict so learning survives sessions

Every number originates from `news_analytics.py`; nothing here fabricates or estimates a
metric. When a window carries too little traffic to support a claim, the honest output is
`no_evidence`, and that is what the code returns.
"""

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ANALYTICS = "/home/pertt/.local/share/lean-support/bin/news_analytics.py"

# A hypothesis is only meaningful with enough signal behind it. Below this many GSC
# impressions on the affected pages, a CTR claim is noise, so the verdict is no_evidence.
MIN_IMPRESSIONS_FOR_CTR = 100
MIN_CLICKS_FOR_CTR = 5
TARGET_VIEWS = 10000
TARGET_USERS = 1000
STATE_DIR = Path("/home/pertt/.local/share/uutistenlukija")
LEARNING_DIR = STATE_DIR / "learning"


def _now():
    return datetime.now(timezone.utc)


def measure(timeout=180):
    """Read-only GA4 + GSC totals. Returns {'ok': bool, 'data'|'error': ...}."""
    try:
        proc = subprocess.run(
            [ANALYTICS],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}
    if proc.returncode != 0:
        return {"ok": False, "error": f"analytics exit {proc.returncode}: {proc.stderr[-300:]}"}
    try:
        return {"ok": True, "data": json.loads(proc.stdout)}
    except ValueError as error:
        return {"ok": False, "error": f"analytics returned invalid JSON: {error}"}


def read_published(state_dir=STATE_DIR):
    """Published articles with the metadata needed for attribution."""
    import sqlite3
    db = Path(state_dir) / "jobs.sqlite"
    if not db.exists():
        return []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT j.id, j.created_at, j.draft, p.status AS pub_status
                 FROM jobs j
                 LEFT JOIN publications p ON p.job_id = j.id
                WHERE p.status = 'deployed'"""
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        try:
            draft = json.loads(row["draft"])
        except (ValueError, TypeError):
            continue
        out.append({
            "id": row["id"],
            "created_at": row["created_at"],
            "title": draft.get("title", ""),
            "summary": draft.get("summary", ""),
            "category": draft.get("category", ""),
            "title_length": len(draft.get("title", "")),
            "summary_length": len(draft.get("summary", "")),
            "has_image": bool(draft.get("image")),
        })
    return out


def goal_status(data):
    """Distance to the standing goal, from measured values only."""
    ga4 = data.get("ga4", {}) if data else {}
    views = ga4.get("views")
    users = ga4.get("active_users")
    return {
        "views": views,
        "users": users,
        "views_target": TARGET_VIEWS,
        "users_target": TARGET_USERS,
        "views_pct": round(100.0 * views / TARGET_VIEWS, 3) if isinstance(views, (int, float)) else None,
        "users_pct": round(100.0 * users / TARGET_USERS, 3) if isinstance(users, (int, float)) else None,
    }


def diagnose(data, articles):
    """Ranked, checkable hypotheses from measured evidence.

    Each hypothesis names the evidence it rests on and the metric that would confirm or
    refute it, so a later run can close it out rather than re-asserting it.
    """
    hypotheses = []
    if not data:
        return hypotheses

    goal = goal_status(data)
    gsc = data.get("gsc", {}) or {}
    impressions = gsc.get("impressions")
    clicks = gsc.get("clicks")
    ctr = None
    if isinstance(impressions, int) and isinstance(clicks, int) and impressions > 0:
        ctr = 100.0 * clicks / impressions

    # --- SEO: the dominant signal -------------------------------------------------
    if ctr is not None:
        evidence = f"{clicks} clicks / {impressions} impressions = {ctr:.2f}% CTR"
        enough = impressions >= MIN_IMPRESSIONS_FOR_CTR and clicks >= MIN_CLICKS_FOR_CTR
        if enough and ctr < 2.0:
            hypotheses.append({
                "lane": "seo",
                "priority": 1,
                "hypothesis": "Search snippets win impressions but not clicks; titles and "
                              "meta descriptions do not match query intent.",
                "evidence": evidence,
                "metric": "GSC CTR on the same query/URL set",
                "target": "CTR >= 3% at equal or higher impressions",
                "action": "Ship description/OG/JSON-LD, then rewrite titles toward the "
                          "queries that already produce impressions.",
                "confidence": "high" if impressions >= 1000 else "medium",
            })
        elif not enough:
            hypotheses.append({
                "lane": "seo",
                "priority": 3,
                "hypothesis": "Too little search exposure to judge snippet quality.",
                "evidence": evidence,
                "metric": "GSC impressions",
                "target": f">= {MIN_IMPRESSIONS_FOR_CTR} impressions",
                "action": "Grow breadth/freshness first; hold SEO verdicts.",
                "confidence": "no_evidence",
            })

    # --- Volume: the goal is far away, so throughput matters -----------------------
    views = goal.get("views")
    if isinstance(views, int):
        hypotheses.append({
            "lane": "volume",
            "priority": 2 if views < 500 else 4,
            "hypothesis": "Publishing volume is the binding constraint on reaching the "
                          "10,000 views / 1,000 users goal.",
            "evidence": f"{views} views in the measured 30-day window vs {TARGET_VIEWS} target "
                        f"({goal['views_pct']}%)",
            "metric": "GA4 views per rolling 30 days",
            "target": "sustained week-over-week growth",
            "action": "Fix idle ticks (source collection) and raise the per-tick publication "
                      "ceiling so fresh material actually ships.",
            "confidence": "high",
        })

    # --- Coverage: are categories and images balanced? ----------------------------
    if articles:
        without_image = [a for a in articles if not a["has_image"]]
        if len(without_image) > len(articles) // 2:
            hypotheses.append({
                "lane": "publishing_quality",
                "priority": 3,
                "hypothesis": "Most articles ship without an image, weakening both click "
                              "appeal in listings and social/snippet previews.",
                "evidence": f"{len(without_image)} of {len(articles)} published articles have no image",
                "metric": "share of published articles with a verified image",
                "target": ">= 50% with a rights-verified image",
                "action": "Repair the NASA image lane and add image-capable sources.",
                "confidence": "medium",
            })
        categories = {}
        for a in articles:
            categories[a["category"]] = categories.get(a["category"], 0) + 1
        if categories and max(categories.values()) > 0.6 * len(articles):
            top = max(categories, key=categories.get)
            hypotheses.append({
                "lane": "coverage",
                "priority": 3,
                "hypothesis": "Coverage is concentrated in one category, limiting the set of "
                              "queries the site can rank for.",
                "evidence": f"{categories[top]} of {len(articles)} articles in '{top}'",
                "metric": "distinct categories with >= 3 published articles",
                "target": ">= 3 categories represented",
                "action": "Rebalance discovery across providers/categories.",
                "confidence": "medium",
            })

    # --- Titles: length is a cheap, checkable property ---------------------------
    if articles:
        long_titles = [a for a in articles if a["title_length"] > 60]
        if long_titles:
            longest = max(a["title_length"] for a in articles)
            hypotheses.append({
                "lane": "seo",
                "priority": 2,
                "hypothesis": "Titles exceed the width a SERP/social card displays, so the "
                              "distinctive words may be cut off.",
                "evidence": f"{len(long_titles)} of {len(articles)} titles exceed 60 characters "
                            f"(max {longest})",
                "metric": "GSC CTR for the affected URLs",
                "target": "titles <= 60 chars without losing the key noun",
                "action": "Tighten headline generation to front-load the distinctive term.",
                "confidence": "medium",
            })

    hypotheses.sort(key=lambda h: (h["priority"], {"high": 0, "medium": 1, "no_evidence": 2}[h["confidence"]]))
    return hypotheses


def ledger_path(learning_dir=LEARNING_DIR):
    return Path(learning_dir) / "experiments.jsonl"


def record(entry, learning_dir=LEARNING_DIR):
    """Append one experiment/observation row. Never rewrites history."""
    path = ledger_path(learning_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"recorded_at": _now().isoformat(), **entry}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return row


def history(learning_dir=LEARNING_DIR, limit=200):
    path = ledger_path(learning_dir)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows[-limit:]


def review(state_dir=STATE_DIR, learning_dir=LEARNING_DIR):
    """One full loop iteration: measure, attribute, diagnose, persist, report."""
    measured = measure()
    articles = read_published(state_dir)
    if not measured["ok"]:
        record({"kind": "review_failed", "error": measured["error"]}, learning_dir)
        return {"ok": False, "error": measured["error"]}

    data = measured["data"]
    goal = goal_status(data)
    hypotheses = diagnose(data, articles)
    record({
        "kind": "review",
        "goal": goal,
        "articles_published": len(articles),
        "hypotheses": [{"lane": h["lane"], "confidence": h["confidence"], "hypothesis": h["hypothesis"]}
                       for h in hypotheses],
    }, learning_dir)
    return {"ok": True, "goal": goal, "articles": len(articles),
            "hypotheses": hypotheses, "generated_at": _now().isoformat()}


def format_report(result):
    """Compact Telegram-friendly report."""
    if not result.get("ok"):
        return f"Learning review failed: {result.get('error')}"
    goal = result["goal"]
    lines = [
        "Uutistenlukija learning review",
        f"Goal: {goal['views']} / {goal['views_target']} views ({goal['views_pct']}%), "
        f"{goal['users']} / {goal['users_target']} users ({goal['users_pct']}%)",
        f"Published articles: {result['articles']}",
    ]
    if result["hypotheses"]:
        lines.append("")
        lines.append("Ranked hypotheses:")
        for i, h in enumerate(result["hypotheses"], 1):
            lines.append(f"{i}. [{h['lane']}/{h['confidence']}] {h['hypothesis']}")
            lines.append(f"   evidence: {h['evidence']}")
            lines.append(f"   test: {h['metric']} -> {h['target']}")
    else:
        lines.append("No hypotheses: insufficient measured evidence.")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    outcome = review()
    print(format_report(outcome))
    raise SystemExit(0 if outcome.get("ok") else 1)
