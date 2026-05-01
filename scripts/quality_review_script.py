#!/usr/bin/env python3
"""Script-first uutistenlukija quality review.

Collects operational facts locally/cheaply and performs deterministic Finnish
quality heuristics on recent posts. It intentionally avoids waking a full
OpenClaw/Felix agent. Optional Discord posting uses an env/webhook if present.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
CONTENT = PROJECT / "content" / "posts"
LOG_DIR = PROJECT / "pipeline" / "logs"
SITE = "https://uutistenlukija.fi/"

BAD_PATTERNS = [
    ("source_leak", re.compile(r"\b(?:Source|Lähde|Continue reading|Read more)\b", re.I)),
    ("ai_meta", re.compile(r"\b(?:aineiston perusteella|paketin mukaan|tämä artikkeli|tässä artikkelissa)\b", re.I)),
    ("english_leak", re.compile(r"\b(?:according to|officials said|breaking news|the company said)\b", re.I)),
]


def fetch_status(url: str, timeout: int = 12) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "uutistenlukija-quality-script/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(200_000)
            return {"ok": 200 <= resp.status < 400, "status": resp.status, "bytes": len(body)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm = text[3:end]
    out = {}
    for line in fm.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip().strip('"')
    return out


def recent_posts(limit: int = 20) -> list[Path]:
    if not CONTENT.exists():
        return []
    return sorted(CONTENT.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def post_date(path: Path, text: str) -> str:
    fm = parse_frontmatter(text)
    raw = fm.get("date") or ""
    m = re.search(r"(20\d\d-\d\d-\d\d)", raw) or re.search(r"(20\d\d-\d\d-\d\d)", path.name)
    return m.group(1) if m else "unknown"


def body_text(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4 :]
    return text.strip()


def grade_finnish(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    fm = parse_frontmatter(text)
    body = body_text(text)
    words = re.findall(r"\b[\wåäöÅÄÖ-]+\b", body)
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    issues: list[str] = []
    if len(words) < 180:
        issues.append(f"short_body:{len(words)}w")
    if len(paras) < 3:
        issues.append(f"few_paragraphs:{len(paras)}")
    if paras and len(paras[0].split()) < 25:
        issues.append(f"short_lead:{len(paras[0].split())}w")
    for label, rx in BAD_PATTERNS:
        if rx.search(body) or rx.search(fm.get("title", "")):
            issues.append(label)
    # simple deterministic grade: 5 minus issue penalties, floor 1
    grade = max(1.0, 5.0 - min(4.0, len(issues) * 0.75))
    return {
        "file": path.name,
        "title": fm.get("title") or path.stem,
        "date": post_date(path, text),
        "words": len(words),
        "paragraphs": len(paras),
        "grade": round(grade, 1),
        "issues": issues,
    }


def load_pipeline_metrics() -> dict:
    p = LOG_DIR / "metrics.json"
    if not p.exists():
        return {"available": False}
    try:
        data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, list) or not data:
            return {"available": False}
        recent = data[-20:]
        return {
            "available": True,
            "last_success": data[-1].get("success"),
            "last_duration_sec": data[-1].get("total_duration_sec"),
            "recent_runs": len(recent),
            "recent_published": sum(int(x.get("article_count") or 0) for x in recent),
            "recent_successes": sum(1 for x in recent if x.get("success")),
        }
    except Exception as e:
        return {"available": False, "error": str(e)[:120]}


def maybe_post_discord(text: str) -> None:
    webhook = os.environ.get("DISCORD_PIPELINE_WEBHOOK") or os.environ.get("DISCORD_METRICS_WEBHOOK")
    if not webhook:
        return
    payload = json.dumps({"content": text[:1900]}).encode("utf-8")
    req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        print(f"[quality-review] Discord post failed: {e}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", action="store_true", help="post compact review to configured Discord webhook")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    homepage = fetch_status(SITE)
    posts = recent_posts(30)
    today = now.date().isoformat()
    today_count = 0
    graded = []
    for p in posts:
        txt = p.read_text(encoding="utf-8", errors="replace")
        if post_date(p, txt) == today:
            today_count += 1
    for p in posts[:2]:
        graded.append(grade_finnish(p))
    avg = round(sum(g["grade"] for g in graded) / len(graded), 1) if graded else None
    metrics = load_pipeline_metrics()
    result = {
        "timestamp": now.isoformat(),
        "homepage": homepage,
        "today_post_count_recent_window": today_count,
        "recent_post_files_checked": len(posts),
        "quality_samples": graded,
        "average_grade": avg,
        "pipeline_metrics": metrics,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    lines = [
        f"🧪 uutistenlukija quality check {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Site: {'OK' if homepage.get('ok') else 'FAIL'} ({homepage.get('status', homepage.get('error'))})",
        f"Recent-window posts dated today: {today_count}",
    ]
    if avg is not None:
        lines.append(f"Finnish heuristic sample avg: {avg}/5")
        for g in graded:
            issue_text = ', '.join(g['issues']) if g['issues'] else 'no major heuristic issues'
            lines.append(f"- {g['title'][:80]}: {g['grade']}/5, {g['words']}w, {issue_text}")
    if metrics.get("available"):
        lines.append(f"Pipeline recent: {metrics['recent_successes']}/{metrics['recent_runs']} successful, {metrics['recent_published']} articles")
    summary = "\n".join(lines)
    print(summary)
    if args.post:
        maybe_post_discord(summary)
    return 0 if homepage.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
