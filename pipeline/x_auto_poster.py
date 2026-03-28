#!/usr/bin/env python3
"""
x_auto_poster.py — Auto-post recent articles to @Uutistenlukija_ on X/Twitter.

Run 3-4 times/day: 07:30, 11:30, 17:00, 20:00 UTC.
Free tier: 500 posts/month (~16/day max). We target 3-4/day.

Selection priority:
1. Articles published in last 90 min, source_tier=1
2. Articles published in last 3h, any tier
3. Most recent article not yet posted

Skips:
- Already-posted URLs (tracked in logs/x-posted.json)
- Casino/gambling articles (spam filter)
- Articles <100 words in description
"""

import argparse
import glob
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

# ── Config ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
CONTENT_DIR   = os.path.join(SCRIPT_DIR, "..", "content", "posts")
LOG_DIR       = os.path.join(SCRIPT_DIR, "logs")
POSTED_FILE   = os.path.join(LOG_DIR, "x-posted.json")
X_TOKENS_FILE = "/workspace/.secrets/x-tokens.json"
SITE_BASE_URL = "https://uutistenlukija.fi"
MAX_POSTED_LOG = 2000   # keep last N URLs in posted log

CATEGORY_HASHTAGS = {
    "kotimaa":   "#suomi #kotimaa",
    "ulkomaat":  "#ulkomaat #maailma",
    "talous":    "#talous",
    "urheilu":   "#urheilu",
    "teknologia": "#teknologia",
    "tiede":     "#tiede",
    "kulttuuri": "#kulttuuri",
    "ulkomailla": "#ulkomaat",
    "ulkomaisia": "#ulkomaat",
    "ulkomainen": "#ulkomaat",
    "tekoala":   "#tekoäly #teknologia",
}

SPAM_KEYWORDS = {"kasino", "casino", "vedonlyönti", "nettikasin", "pelaaminen", "skrill"}

# ── Frontmatter parser ─────────────────────────────────────────────────────────

def parse_frontmatter(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        content = f.read()

    if not content.startswith("---"):
        return {}

    end = content.find("\n---", 3)
    if end == -1:
        return {}

    fm_text = content[3:end]
    result = {}
    current_list_key = None
    for line in fm_text.splitlines():
        stripped = line.strip()
        # YAML list item
        if stripped.startswith("- ") and current_list_key:
            item = stripped[2:].strip().strip('"')
            if isinstance(result.get(current_list_key), list):
                result[current_list_key].append(item)
            continue
        # Key: value (scalar)
        m = re.match(r'^(\w+):\s*"?([^"]*)"?$', stripped)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val == "":
                # might be start of a list block
                result[key] = []
                current_list_key = key
            else:
                result[key] = val
                current_list_key = None
        elif stripped == "" or ":" in stripped:
            current_list_key = None

    # Also grab body word count (rough)
    body = content[end + 4:]
    result["_word_count"] = len(body.split())
    result["_path"] = path

    return result


def slug_to_url(path: str) -> str:
    slug = os.path.basename(path).replace(".md", "")
    return f"{SITE_BASE_URL}/posts/{slug}/"


def is_spam(article: dict) -> bool:
    title = (article.get("title", "") + " " + article.get("description", "")).lower()
    return any(kw in title for kw in SPAM_KEYWORDS)


# ── Article loader ─────────────────────────────────────────────────────────────

def load_recent_articles(hours: int = 3) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    articles = []
    for path in glob.glob(os.path.join(CONTENT_DIR, "*.md")):
        fm = parse_frontmatter(path)
        if not fm.get("date"):
            continue
        try:
            pub_date = datetime.fromisoformat(fm["date"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if pub_date < cutoff:
            continue
        fm["_url"] = slug_to_url(path)
        fm["_pub_date"] = pub_date
        articles.append(fm)

    articles.sort(key=lambda a: a["_pub_date"], reverse=True)
    return articles


def load_posted_urls() -> set:
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE) as f:
            data = json.load(f)
        return set(data.get("urls", []))
    return set()


def save_posted_url(url: str):
    os.makedirs(LOG_DIR, exist_ok=True)
    posted = []
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE) as f:
            data = json.load(f)
        posted = data.get("log", [])

    entry = {
        "url": url,
        "posted_at": datetime.now(timezone.utc).isoformat(),
    }
    posted.append(entry)
    posted = posted[-MAX_POSTED_LOG:]  # rotate

    with open(POSTED_FILE, "w") as f:
        json.dump({
            "urls": [e["url"] for e in posted],
            "log": posted,
        }, f, indent=2)


# ── Tweet composer ─────────────────────────────────────────────────────────────

CATEGORY_EMOJIS = {
    "kotimaa": "🇫🇮",
    "ulkomaat": "🌍",
    "talous": "💶",
    "urheilu": "⚽",
    "teknologia": "💻",
    "tiede": "🔬",
    "kulttuuri": "🎭",
    "tekoala": "🤖",
}


def compose_tweet(article: dict) -> str:
    title = article.get("title", "")
    desc  = article.get("description", "")
    url   = article.get("_url", "")

    # categories is a list from frontmatter; fall back to keywords string
    cats = article.get("categories", [])
    if isinstance(cats, list):
        category = cats[0].lower().strip() if cats else ""
    else:
        category = str(cats).lower().split(",")[0].strip()
    if not category:
        raw_kw = article.get("keywords", "")
        category = str(raw_kw).lower().split(",")[0].strip()

    emoji    = CATEGORY_EMOJIS.get(category, "📰")
    hashtags = CATEGORY_HASHTAGS.get(category, "#uutiset")

    # Extra hashtag for AI articles
    if any(k in title.lower() + desc.lower() for k in ["tekoäly", "tekoäl", "ai ", "chatgpt", "openai"]):
        if "#tekoäly" not in hashtags:
            hashtags += " #tekoäly"

    # Teaser line: first key_point if available, else description
    key_points = article.get("key_points", [])
    if isinstance(key_points, list) and key_points:
        teaser = f"▪ {key_points[0].strip()}"
    else:
        teaser = desc

    # Build tweet (no trailing #uutiset — already in hashtags default)
    title_trunc  = title[:180] if len(title) > 180 else title
    teaser_trunc = (teaser[:110] + "…") if len(teaser) > 110 else teaser

    if teaser_trunc:
        tweet = f"{emoji} {title_trunc}\n\n{teaser_trunc}\n\n{url} {hashtags}"
    else:
        tweet = f"{emoji} {title_trunc}\n\n{url} {hashtags}"

    # Twitter hard limit: 280 chars
    if len(tweet) > 280:
        available = 280 - len(f"{emoji} {title_trunc}\n\n…\n\n{url} {hashtags}")
        if available > 20:
            tweet = f"{emoji} {title_trunc}\n\n{teaser[:available]}…\n\n{url} {hashtags}"
        else:
            tweet = f"{emoji} {title_trunc[:220]}\n\n{url} {hashtags}"

    return tweet[:280]


# ── X API poster ──────────────────────────────────────────────────────────────

def get_x_token() -> str:
    with open(X_TOKENS_FILE) as f:
        data = json.load(f)
    return data["access_token"]


def post_tweet(text: str, dry_run: bool = False) -> dict:
    if dry_run:
        print(f"[DRY RUN] Would tweet:\n{text}\n({len(text)} chars)")
        return {"dry_run": True, "text": text}

    token = get_x_token()
    req = urllib.request.Request(
        "https://api.x.com/2/tweets",
        json.dumps({"text": text}).encode(),
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read())
        tweet_id = result.get("data", {}).get("id", "?")
        print(f"[x] Tweeted ✅  id={tweet_id}  '{text[:60]}...'")
        return result
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[x] HTTP {e.code}: {body[:400]}", file=sys.stderr)
        # Check for token expiry (401)
        if e.code == 401:
            print("[x] Token expired — run scripts/refresh-x-token.sh", file=sys.stderr)
        return {"error": e.code, "body": body}


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",   action="store_true")
    parser.add_argument("--hours",     type=int, default=3, help="Look back N hours for articles")
    parser.add_argument("--max-posts", type=int, default=2, help="Max tweets per run")
    args = parser.parse_args()

    os.makedirs(LOG_DIR, exist_ok=True)

    posted_urls = load_posted_urls()
    articles = load_recent_articles(hours=args.hours)

    print(f"[x_poster] Found {len(articles)} articles in last {args.hours}h")
    print(f"[x_poster] Already posted: {len(posted_urls)} URLs")

    # Filter: not posted, not spam, has title
    candidates = [
        a for a in articles
        if a.get("title")
        and a.get("_url") not in posted_urls
        and not is_spam(a)
    ]

    # Sort: tier 1 first, then by date
    candidates.sort(key=lambda a: (
        int(a.get("source_tier", 2)),
        -a["_pub_date"].timestamp()
    ))

    print(f"[x_poster] {len(candidates)} candidates after filtering")

    posted_count = 0
    for article in candidates:
        if posted_count >= args.max_posts:
            break

        tweet = compose_tweet(article)
        url   = article["_url"]
        title = article.get("title", "?")[:60]

        print(f"\n[x_poster] Posting: {title}")
        print(f"  URL: {url}")
        print(f"  Tier: T{article.get('source_tier', '?')}")
        print(f"  Tweet ({len(tweet)}c):\n  {tweet[:120]}...")

        result = post_tweet(tweet, dry_run=args.dry_run)

        if "error" in result:
            print(f"[x_poster] Failed — stopping", file=sys.stderr)
            break

        if not result.get("dry_run"):
            save_posted_url(url)

        posted_count += 1

        if posted_count < args.max_posts and len(candidates) > posted_count:
            time.sleep(5)  # brief pause between tweets

    print(f"\n[x_poster] Done — posted {posted_count} tweets")


if __name__ == "__main__":
    main()
