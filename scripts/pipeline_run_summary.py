#!/usr/bin/env python3
"""pipeline_run_summary.py
Posts compact summary to #operations after each pipeline run.
Silent on 0 articles. Called by auto_publish.sh.
Usage: python3 scripts/pipeline_run_summary.py --articles N --elapsed SECONDS
"""
import argparse, json, os, sys, urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_FILES   = [
    PROJECT_DIR / ".env",
    PROJECT_DIR / "pipeline" / ".env",
    Path("/workspace/.env"),
    Path("/home/pertt/.openclaw/.env"),
]
CONTENT_DIR = PROJECT_DIR / "content" / "posts"
SITE_BASE   = "https://uutistenlukija.fi"
WEBHOOK_ENV = "DISCORD_PIPELINE_WEBHOOK"
CHANNEL_ENV = "DISCORD_PIPELINE_ALERT_CHANNEL_ID"
DEFAULT_CHANNEL_ID = "1482082645553713366"
DISCORD_HTTP_USER_AGENT = "Mozilla/5.0"


def load_env(paths):
    env = {}
    for path in paths:
        if not path.exists():
            continue
        for line in path.open():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def recent_articles(minutes=20):
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    arts = []
    for p in CONTENT_DIR.glob("*.md"):
        txt = p.read_text(encoding="utf-8", errors="replace")
        parts = txt.split("---", 2)
        if len(parts) < 3:
            continue
        fm = parts[1]
        title = cat = ds = ""
        for line in fm.splitlines():
            if line.startswith("title:"):
                title = line[6:].strip().strip('"')
            elif line.startswith("date:"):
                ds = line[5:].strip().strip('"')
            elif line.startswith("  - ") and not cat:
                cat = line[4:].strip().strip('"')
        if not ds:
            continue
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if dt >= cutoff:
            arts.append({"title": title, "cat": cat, "dt": dt, "slug": p.stem})
    return sorted(arts, key=lambda a: a["dt"], reverse=True)


def build_msg(n, arts, elapsed):
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    cats = Counter(a["cat"] for a in arts if a["cat"])
    cat_str = (", ".join(f"{c}: {v}" for c, v in cats.most_common())) or "—"
    link = ""
    if arts:
        t = arts[0]["title"][:60] + ("…" if len(arts[0]["title"]) > 60 else "")
        link = f"\n🔗 Tuorein: {t}\n   {SITE_BASE}/posts/{arts[0]['slug']}/"
    dur = f"{elapsed // 60}m {elapsed % 60}s" if elapsed >= 60 else f"{elapsed}s"
    return (
        f"✅ **Pipeline-ajo valmis** — {now}\n"
        f"📰 Julkaistu: **{n}** artikkelia\n"
        f"📂 Kategoriat: {cat_str}{link}\n"
        f"⏱️  Kesto: {dur}"
    )


def _read_env_key_from_files(key_name: str) -> str:
    candidates = ENV_FILES
    for path in candidates:
        try:
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith(f"{key_name}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            continue
    return ""


def post_discord(url, msg):
    data = json.dumps({"content": msg}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": DISCORD_HTTP_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status in (200, 204)
    except Exception as e:
        print(f"[run_summary] webhook error: {e}", file=sys.stderr)
        return False


def post_via_discord_bot(channel_id: str, msg: str) -> bool:
    token = os.environ.get("OPENCLAW_DISCORD_BOT_TOKEN") or _read_env_key_from_files("OPENCLAW_DISCORD_BOT_TOKEN")
    if not token or not channel_id:
        return False
    data = json.dumps({"content": msg[:1900]}).encode()
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bot {token}",
            "User-Agent": DISCORD_HTTP_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status in (200, 201, 204)
    except Exception as e:
        print(f"[run_summary] bot error: {e}", file=sys.stderr)
        return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--articles", type=int, default=0)
    p.add_argument("--elapsed",  type=int, default=0)
    p.add_argument("--dry-run",  action="store_true")
    a = p.parse_args()

    if a.articles == 0:
        print("[run_summary] 0 articles — skipping")
        return 0

    env  = load_env(ENV_FILES)
    hook = os.environ.get(WEBHOOK_ENV) or env.get(WEBHOOK_ENV, "")
    channel_id = os.environ.get(CHANNEL_ENV) or env.get(CHANNEL_ENV, DEFAULT_CHANNEL_ID)
    arts = recent_articles()
    msg  = build_msg(a.articles, arts, a.elapsed)
    print(msg)

    if a.dry_run:
        return 0

    if hook and post_discord(hook, msg):
        print("[run_summary] Posted to #operations via webhook ✓")
        return 0

    if post_via_discord_bot(channel_id, msg):
        print("[run_summary] Posted to #operations via bot ✓")
        return 0

    if not hook:
        print(f"[run_summary] {WEBHOOK_ENV} not set and bot fallback failed", file=sys.stderr)
    else:
        print("[run_summary] Discord post failed via webhook and bot", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
