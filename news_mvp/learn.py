"""Readership measurement and the ranked-hypothesis feedback loop.

The pipeline published articles but never read a single number back: `ga4_id` existed
only as a string written into the publish receipt. Nothing connected what was published
to what was read, so nothing could learn.

This module closes that loop:

  measure()   -> pull GA4 + GSC through the read-only analytics CLI
  attribute() -> join per-article performance back to published article metadata
  diagnose()  -> turn the joined evidence into ranked, checkable hypotheses
  ledger()    -> persist every experiment and its verdict so learning survives sessions
  record_action() -> log concrete changes so a later review can attribute movement

Only verified, joined evidence can produce a readership diagnosis. `diagnose` requires a
complete measurement (`measurement_status == "ok"`, `truncated is False`) whose per-article
GSC rows are deployed articles on this site's canonical URL prefix. A deployed article with
no GSC row is unknown coverage: it is excluded from every measured sum rather than read as
zero. Anything less - a domain-level total, an unverified article list, an invalid or
malformed observed row, a truncated pull - yields a single `insufficient_evidence` verdict
instead of a guess. Nothing here fabricates or estimates a metric, and no diagnosis is
extrapolated from article shape alone.
"""

import json
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .measurement import normalize_url

ANALYTICS = "/home/pertt/.local/share/lean-support/bin/news_analytics.py"

# A hypothesis is only meaningful with enough signal behind it. The threshold applies to the
# summed GSC impressions of the joined deployed articles, never to domain-level totals.
MIN_IMPRESSIONS_FOR_CTR = 100
# An exposed cohort below this CTR is worth a tentative, explicitly non-causal look.
LOW_CTR_THRESHOLD = 2.0
# Impression-weighted average position at or below this points at title/query intent, above it
# at ranking/visibility. Neither is a snippet failure.
LOW_POSITION_MAX = 10.0
# "medium" confidence needs both volume and breadth of exposed articles; "high" is never claimed.
COHORT_MEDIUM_MIN_IMPRESSIONS = 1000
COHORT_MEDIUM_MIN_URLS = 3
MAX_EVIDENCE_URLS = 6
CANONICAL_ORIGIN = "https://uutistenlukija.fi"
CANONICAL_PATH_PREFIX = "/uutiset/"
CANONICAL_ARTICLE_PREFIX = CANONICAL_ORIGIN + CANONICAL_PATH_PREFIX
METADATA_COMPONENTS = ("description", "og", "jsonld")
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


def _is_number(value):
    """Finite real number, explicitly not a bool (True would pass isinstance(int))."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _has_id(value):
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, int)


def _insufficient(reason):
    """The single honest verdict whenever the evidence gate cannot be satisfied."""
    return [{
        "lane": "measurement",
        "priority": 1,
        "verdict": "insufficient_evidence",
        "hypothesis": "No readership diagnosis is supported: verified joined article evidence "
                      "is missing or untrustworthy.",
        "evidence": f"Evidence gate failed: {reason}.",
        "metric": "GSC clicks/impressions/position joined to deployed article URLs",
        "target": f">= {MIN_IMPRESSIONS_FOR_CTR} verified impressions across a valid, "
                  f"unambiguous deployed-article cohort",
        "action": "Hold every readership hypothesis until a complete measurement + join pass "
                  "exists for this window.",
        "confidence": "no_evidence",
    }]


def _metadata_gaps(cohort):
    """Explicitly missing vs merely unrecorded metadata components, per affected URL."""
    missing, unknown = {}, {}
    for component in METADATA_COMPONENTS:
        for row in cohort:
            value = row["metadata"].get(component)
            if value is False:
                missing.setdefault(component, []).append(row["url"])
            elif value is not True:
                unknown.setdefault(component, []).append(row["url"])
    return missing, unknown


def _name_urls(urls):
    shown = ", ".join(urls[:MAX_EVIDENCE_URLS])
    if len(urls) > MAX_EVIDENCE_URLS:
        shown += f", +{len(urls) - MAX_EVIDENCE_URLS} more"
    return shown


def diagnose(data, articles=None):
    """Ranked, checkable hypotheses from verified joined evidence, or nothing.

    Every readership verdict must pass an explicit evidence gate: the measurement must be
    complete and untruncated, and every row must be an exactly deployed article carrying a
    valid, non-duplicate URL on this site. A single invalid or malformed observed row fails
    the whole diagnosis closed. A deployed article with no GSC row is unknown coverage: it is
    excluded from every measured sum and never read as zero. `articles` (structural facts
    about published drafts) is kept for API compatibility and deliberately ignored: article
    shape is not readership evidence.
    """
    if not isinstance(data, dict):
        return _insufficient("no measurement payload was provided")
    if data.get("measurement_status") != "ok":
        return _insufficient("measurement_status is not 'ok'")
    if data.get("truncated") is not False:
        return _insufficient("the measurement is truncated or its completeness is unverified")

    rows = data.get("article_performance")
    if not isinstance(rows, list) or not rows:
        return _insufficient("no joined deployed-article rows were provided")

    cohort, unknown, seen_urls = [], [], set()
    for row in rows:
        if not isinstance(row, dict):
            return _insufficient("a joined article row is not a mapping")
        url = row.get("canonical_url")
        path = normalize_url(url)
        if (path is None or not path.startswith(CANONICAL_PATH_PREFIX)
                or len(path) <= len(CANONICAL_PATH_PREFIX)
                or url != CANONICAL_ORIGIN + path):
            return _insufficient("a row does not carry this site's canonical article URL")
        if url in seen_urls:
            return _insufficient(f"duplicate canonical rows make the cohort ambiguous ({url})")
        seen_urls.add(url)
        if row.get("deployed") is not True:
            return _insufficient("a row is not an exactly deployed article")
        if not _has_id(row.get("id")):
            return _insufficient("a row does not carry an article id")
        gsc = row.get("gsc")
        if gsc is None:
            unknown.append(url)
            continue
        if not isinstance(gsc, dict):
            return _insufficient("a row's GSC payload is not a mapping")
        status = gsc.get("status")
        if status == "missing":
            # The analytics pull has no GSC row for this deployed article: that is unknown
            # coverage, and its placeholder metrics must never be summed as zero.
            unknown.append(url)
            continue
        if status is None:
            if any(key in gsc for key in ("clicks", "impressions", "position")):
                return _insufficient("a row's observed GSC metrics carry no 'ok' status")
            unknown.append(url)
            continue
        if status != "ok":
            return _insufficient("a row's GSC status is not 'ok'")
        clicks, impressions, position = (gsc.get("clicks"), gsc.get("impressions"),
                                        gsc.get("position"))
        if not all(_is_number(value) for value in (clicks, impressions)):
            return _insufficient("a row carries a non-finite or non-numeric GSC value")
        if clicks < 0 or impressions < 0:
            return _insufficient("a row carries a negative GSC value")
        if clicks > impressions:
            return _insufficient("a row reports more clicks than impressions")
        if impressions > 0:
            # Any row that carries impressions must carry a finite position >= 1.
            if not _is_number(position) or position < 1:
                return _insufficient("a row with impressions carries no finite position >= 1")
        elif position is not None and (not _is_number(position) or position < 1):
            return _insufficient("a row carries a position below 1")
        # Zero impressions with no position is a valid unexposed row: nothing is imputed, and
        # the row is excluded from position-weighted evidence, breadth and metadata advice.
        metadata = row.get("metadata")
        cohort.append({
            "url": url,
            "clicks": clicks,
            "impressions": impressions,
            "position": position,
            "metadata": metadata if isinstance(metadata, dict) else {},
        })

    unknown_coverage = len(unknown)
    measured_urls = len(cohort)
    total_clicks = sum(row["clicks"] for row in cohort)
    total_impressions = sum(row["impressions"] for row in cohort)
    if total_impressions < MIN_IMPRESSIONS_FOR_CTR:
        return _insufficient(
            f"joined deployed articles carry only {total_impressions} measured GSC impressions "
            f"across {measured_urls} measured URL(s) with {unknown_coverage} missing GSC "
            f"row(s), below the {MIN_IMPRESSIONS_FOR_CTR} needed for a CTR read")

    # Exposure, breadth and metadata advice are defined only on positive-impression URLs; rows
    # with zero impressions are valid unexposed rows, but they add no signal of their own.
    exposed = [row for row in cohort if row["impressions"] > 0]
    exposure = (f"coverage: {total_impressions} measured impressions across {len(exposed)} "
                f"exposed URL(s) of {measured_urls} measured row(s), {unknown_coverage} deployed "
                f"article(s) with a missing GSC row (excluded, never counted as zero)")
    ctr = 100.0 * total_clicks / total_impressions
    if ctr >= LOW_CTR_THRESHOLD:
        return []

    weighted_position = (sum(row["impressions"] * row["position"] for row in exposed)
                         / total_impressions)
    if weighted_position <= LOW_POSITION_MAX:
        position_note = ("Average position is on page one, so investigate title/meta intent "
                         "alignment before assuming a snippet failure.")
        action = ("Investigate query/title intent for the affected URLs: impressions arrive "
                  "and the titles/descriptions may not match that intent.")
    else:
        position_note = ("Average position is beyond page one, so investigate "
                         "ranking/visibility drivers before assuming a snippet failure.")
        action = ("Investigate ranking/visibility for the affected URLs (indexing, freshness, "
                  "internal links) rather than treating this as a snippet failure.")
    missing, unknown_metadata = _metadata_gaps(exposed)
    if missing:
        action += (" Audit/fill the explicitly missing metadata component(s): "
                   + "; ".join(f"{component} on {_name_urls(urls)}"
                               for component, urls in missing.items()) + ".")
    if unknown_metadata:
        action += (" Verify first where not recorded: "
                   + "; ".join(f"{component} on {_name_urls(urls)}"
                               for component, urls in unknown_metadata.items())
                   + "; do not assume it is present or missing.")

    ranked = sorted(exposed, key=lambda row: row["impressions"], reverse=True)
    shown = ranked[:MAX_EVIDENCE_URLS]
    details = "; ".join(
        f"{row['url']} ({row['clicks']} clicks/{row['impressions']} impressions/"
        f"position {row['position']:g})" for row in shown
    )
    if len(ranked) > len(shown):
        details += f"; +{len(ranked) - len(shown)} more URL(s)"

    # "medium" needs both exposure and breadth; "high" is never claimed unconditionally.
    confidence = "medium" if (total_impressions >= COHORT_MEDIUM_MIN_IMPRESSIONS
                              and len(exposed) >= COHORT_MEDIUM_MIN_URLS) else "low"
    hypotheses = [{
        "lane": "seo",
        "priority": 1,
        "verdict": "tentative",
        "hypothesis": f"Tentative association, not causal proof: {total_clicks} clicks from "
                      f"{total_impressions} impressions ({ctr:.2f}% CTR) on this deployed "
                      f"cohort ({len(exposed)} exposed URL(s), {measured_urls} measured row(s), "
                      f"{unknown_coverage} missing). {position_note}",
        "evidence": f"{total_clicks} clicks / {total_impressions} impressions = {ctr:.2f}% CTR; "
                    f"impression-weighted position {weighted_position:.1f}; {exposure}; "
                    f"URL set: {details}",
        "metric": "GSC CTR and impression-weighted position on this exact URL set",
        "target": "CTR >= 3% at equal or higher verified impressions on the same URLs",
        "action": action,
        "confidence": confidence,
    }]
    hypotheses.sort(key=lambda h: (h["priority"],
                                   {"high": 0, "medium": 1, "low": 2, "no_evidence": 3}[h["confidence"]]))
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


def record_action(description, lane=None, learning_dir=LEARNING_DIR):
    """Append one concrete change made since the last review.

    Without this the weekly loop re-ranks the same hypotheses forever; with it, a later
    review can attribute metric movement to what was actually tried.
    """
    entry = {"kind": "action", "description": str(description)[:400]}
    if lane:
        entry["lane"] = lane
    return record(entry, learning_dir)


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
    # What changed since the previous review, and what did it move. Without this the loop
    # re-ranks the same hypotheses instead of closing them out.
    prior = [row for row in history(learning_dir) if row.get("kind") == "review"]
    previous = prior[-1] if prior else None
    actions = []
    delta = None
    if previous:
        actions = [row for row in history(learning_dir)
                   if row.get("kind") == "action"
                   and row.get("recorded_at", "") > previous.get("recorded_at", "")]
        previous_goal = previous.get("goal") or {}
        delta = {}
        for key in ("views", "users"):
            old, new = previous_goal.get(key), goal.get(key)
            delta[key] = (new - old) if isinstance(old, (int, float)) and isinstance(new, (int, float)) else None
        old_articles = previous.get("articles_published")
        delta["articles"] = (len(articles) - old_articles) if isinstance(old_articles, int) else None
    record({
        "kind": "review",
        "goal": goal,
        "articles_published": len(articles),
        "actions_since_last_review": [{"description": row.get("description"), "lane": row.get("lane")}
                                      for row in actions[-10:]],
        "delta": delta,
        "hypotheses": [{"lane": h["lane"], "confidence": h["confidence"], "hypothesis": h["hypothesis"]}
                       for h in hypotheses],
    }, learning_dir)
    return {"ok": True, "goal": goal, "articles": len(articles),
            "hypotheses": hypotheses, "actions": actions[-10:], "delta": delta,
            "generated_at": _now().isoformat()}


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
    if result.get("delta"):
        delta = result["delta"]

        def motion(value):
            return "n/a" if value is None else f"{value:+d}"

        lines.append(f"Since last review: views {motion(delta.get('views'))}, "
                     f"users {motion(delta.get('users'))}, articles {motion(delta.get('articles'))}")
    if result.get("actions"):
        lines.append("")
        lines.append("Changes recorded since last review:")
        for action in result["actions"]:
            lines.append(f"- {str(action.get('description') or '')[:140]}")
    if result["hypotheses"]:
        lines.append("")
        lines.append("Ranked hypotheses:")
        for i, h in enumerate(result["hypotheses"], 1):
            lines.append(f"{i}. [{h['lane']}/{h['confidence']}] {h['hypothesis']}")
            lines.append(f"   evidence: {h['evidence']}")
            lines.append(f"   test: {h['metric']} -> {h['target']}")
    else:
        lines.append("No hypotheses raised for this window.")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "action":
        row = record_action(" ".join(sys.argv[2:]).strip())
        print(json.dumps(row, ensure_ascii=False))
        raise SystemExit(0)
    outcome = review()
    print(format_report(outcome))
    raise SystemExit(0 if outcome.get("ok") else 1)
