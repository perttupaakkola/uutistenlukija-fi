#!/usr/bin/env python3
"""
validate_articles.py — Content quality validation for uutistenlukija.fi

Checks all published markdown articles and flags:
  - Missing/empty description
  - Missing image (no hero image)
  - Thin content (< 200 words)
  - Duplicate titles
  - Missing categories
  - Missing tags (informational — not currently used in pipeline)
  - Broken image references (HEAD check for external URLs)

Usage:
    python3 validate_articles.py                   # full scan, report to #operations
    python3 validate_articles.py --dry-run         # print, don't post to Discord
    python3 validate_articles.py --fix-descriptions # auto-fill missing descriptions
    python3 validate_articles.py --check-images    # also HEAD-check external image URLs
    python3 validate_articles.py --limit 50        # scan only first N articles

Output: pipeline/logs/validation.json
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
CONTENT_DIR = Path(__file__).parent.parent / "content" / "posts"
STATIC_DIR = Path(__file__).parent.parent / "static"
LOGS_DIR = Path(__file__).parent / "logs"
VALIDATION_LOG = LOGS_DIR / "validation.json"

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_WEBHOOK_OPS = os.getenv("DISCORD_WEBHOOK_OPS", "")
OPERATIONS_CHANNEL_ID = "1482082645553713366"

MIN_WORDS = 50  # Finnish news briefs are short by design; flag only near-empty articles
MAX_DESC_LEN = 155
REQUEST_TIMEOUT = 8
USER_AGENT = "uutistenlukija-bot/1.0 (content-validator)"

# Checks
CHECK_DESCRIPTION = "no_description"
CHECK_IMAGE = "no_image"
CHECK_THIN = "thin_content"
CHECK_DUPLICATE_TITLE = "duplicate_title"
CHECK_CATEGORIES = "no_categories"
CHECK_TAGS = "no_tags"
CHECK_BROKEN_IMAGE = "broken_image"


# ── Front matter parser ───────────────────────────────────────────────────────

def parse_front_matter(text: str) -> tuple[dict, str]:
    """Parse YAML front matter and return (meta, body)."""
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    fm_block = text[3:end].strip()
    body = text[end + 4:].strip()
    meta: dict = {}

    # Simple line-by-line YAML parser (handles string, list, bool, draft)
    current_list_key = None
    for line in fm_block.splitlines():
        # List item
        if re.match(r"^\s{2,}- ", line):
            if current_list_key:
                item = re.sub(r"^\s+-\s+", "", line).strip().strip('"\'')
                meta.setdefault(current_list_key, []).append(item)
            continue
        # Key: value
        m = re.match(r'^(\w[\w_-]*):\s*(.*)', line)
        if m:
            current_list_key = None
            key, val = m.group(1), m.group(2).strip().strip('"\'')
            if val == "":
                # Could be start of list
                current_list_key = key
                meta[key] = []
            elif val.lower() == "true":
                meta[key] = True
            elif val.lower() == "false":
                meta[key] = False
            else:
                meta[key] = val

    return meta, body


def count_words(text: str) -> int:
    """Count words in markdown body (strip markdown syntax)."""
    # Remove code blocks
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`[^`]*`', '', text)
    # Remove links
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Remove markdown headers/bold/italic
    text = re.sub(r'[#*_~>|]', ' ', text)
    return len(text.split())


def extract_description_from_body(body: str, max_len: int = MAX_DESC_LEN) -> str:
    """First meaningful sentence(s) from body, stripped of markdown, max_len chars."""
    # Remove headers
    text = re.sub(r'^#+\s+.*$', '', body, flags=re.MULTILINE)
    # Remove markdown formatting
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'[*_`#>]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()

    if len(text) <= max_len:
        return text

    # Truncate at sentence boundary
    truncated = text[:max_len]
    for sep in ('. ', '! ', '? ', ', '):
        pos = truncated.rfind(sep)
        if pos > max_len // 2:
            return truncated[:pos + 1].strip()

    return truncated.rsplit(' ', 1)[0].strip()


# ── Image URL checker ─────────────────────────────────────────────────────────

def is_local_image(url: str) -> bool:
    return url.startswith("/") or not url.startswith("http")


def check_image_url(url: str) -> tuple[bool, int]:
    """HEAD request to check image URL. Returns (is_ok, status_code)."""
    if is_local_image(url):
        # Check local file
        path = STATIC_DIR / url.lstrip("/")
        return path.exists(), 200 if path.exists() else 404

    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.status < 400, resp.status
    except urllib.error.HTTPError as e:
        return False, e.code
    except Exception:
        return False, 0


# ── Main validator ────────────────────────────────────────────────────────────

def validate_articles(
    check_images: bool = False,
    fix_descriptions: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict:
    files = sorted(CONTENT_DIR.glob("*.md"))
    if limit:
        files = files[:limit]

    total = len(files)
    issues: dict[str, list[dict]] = defaultdict(list)
    title_counts: dict[str, list[str]] = defaultdict(list)
    fixed_count = 0
    checked_image_urls: dict[str, tuple[bool, int]] = {}  # cache

    print(f"Validating {total} articles...", flush=True)

    for i, fpath in enumerate(files):
        if i % 100 == 0 and i > 0:
            print(f"  {i}/{total} ...", flush=True)

        text = fpath.read_text(encoding="utf-8")
        meta, body = parse_front_matter(text)

        slug = fpath.stem
        title = meta.get("title", "")
        draft = meta.get("draft", False)

        # Skip drafts
        if draft is True:
            continue

        article_ref = {"slug": slug, "title": title, "file": fpath.name}

        # 1. Missing description
        desc = meta.get("description", "")
        if not desc or not desc.strip():
            if fix_descriptions:
                new_desc = extract_description_from_body(body)
                if new_desc:
                    if dry_run:
                        fixed_count += 1
                        continue
                    # Write back
                    safe_desc = new_desc.replace('"', '\\"')
                    new_fm_line = f'description: "{safe_desc}"\n'
                    if 'description:' in text:
                        # Replace existing empty line
                        new_text = re.sub(
                            r'^description:\s*["\']?["\']?\s*$',
                            new_fm_line.rstrip(),
                            text,
                            flags=re.MULTILINE,
                        )
                    else:
                        # Insert after title line
                        new_text = re.sub(
                            r'^(title:.*)',
                            r'\1\n' + new_fm_line.rstrip(),
                            text,
                            count=1,
                            flags=re.MULTILINE,
                        )
                    if new_text != text:
                        fpath.write_text(new_text, encoding="utf-8")
                        fixed_count += 1
                        meta["description"] = new_desc
                    continue  # don't flag as issue after fix
            issues[CHECK_DESCRIPTION].append({**article_ref, "detail": "description missing"})
        elif len(desc) > MAX_DESC_LEN:
            issues[CHECK_DESCRIPTION].append({**article_ref, "detail": f"description too long ({len(desc)} chars)"})

        # 2. Missing image
        image = meta.get("image", "")
        if not image or not image.strip():
            issues[CHECK_IMAGE].append(article_ref)
        elif check_images:
            # Check external/local image URL
            if image not in checked_image_urls:
                ok, status = check_image_url(image)
                checked_image_urls[image] = (ok, status)
                time.sleep(0.05)  # be polite
            ok, status = checked_image_urls[image]
            if not ok:
                issues[CHECK_BROKEN_IMAGE].append({**article_ref, "url": image, "status": status})

        # 3. Thin content
        word_count = count_words(body)
        if word_count < MIN_WORDS:
            issues[CHECK_THIN].append({**article_ref, "words": word_count})

        # 4. Duplicate title tracking
        if title:
            title_counts[title.lower().strip()].append(slug)

        # 5. Missing categories
        cats = meta.get("categories", [])
        if not cats or (isinstance(cats, list) and len(cats) == 0):
            issues[CHECK_CATEGORIES].append(article_ref)

        # 6. Missing tags (informational)
        tags = meta.get("tags", [])
        if not tags or (isinstance(tags, list) and len(tags) == 0):
            issues[CHECK_TAGS].append(article_ref)

    # Post-process: duplicate titles
    for title_lower, slugs in title_counts.items():
        if len(slugs) > 1:
            issues[CHECK_DUPLICATE_TITLE].append({
                "title": title_lower,
                "files": slugs,
                "count": len(slugs),
            })

    # Health score: % of articles free of penalized issues (tags excluded — informational only)
    # We collect unique slugs with any penalized issue, then score = 1 - (bad / total)
    penalized_checks = [CHECK_DESCRIPTION, CHECK_IMAGE, CHECK_THIN, CHECK_CATEGORIES, CHECK_BROKEN_IMAGE]
    bad_slugs: set[str] = set()
    for check_key in penalized_checks:
        for item in issues.get(check_key, []):
            slug = item.get("slug")
            if slug:
                bad_slugs.add(slug)
    # Duplicate titles: count each involved article
    for dup in issues.get(CHECK_DUPLICATE_TITLE, []):
        for slug in dup.get("files", []):
            bad_slugs.add(slug)

    total_non_draft = total  # approximation (drafts skipped before counting)
    score = max(0, round((1 - len(bad_slugs) / max(total_non_draft, 1)) * 100))

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_articles": total,
        "health_score": score,
        "fixed_descriptions": fixed_count,
        "issues": {k: v for k, v in issues.items()},
        "counts": {k: len(v) for k, v in issues.items()},
    }


# ── Discord reporter ──────────────────────────────────────────────────────────

def format_discord_message(result: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = result["total_articles"]
    score = result["health_score"]
    counts = result["counts"]
    issues = result["issues"]
    fixed = result.get("fixed_descriptions", 0)

    score_emoji = "✅" if score >= 80 else ("⚠️" if score >= 60 else "🔴")

    lines = [
        f"## 📋 Artikkelien laaduntarkistus — {now}",
        f"{score_emoji} **Sisältöpisteet: {score}/100** — {total} artikkelia tarkistettu",
    ]

    if fixed:
        lines.append(f"🔧 Automaattisesti korjattu: **{fixed}** puuttuvaa kuvausta")

    lines.append("")

    # Summary table
    check_labels = [
        (CHECK_DESCRIPTION, "Puuttuva/liian pitkä kuvaus"),
        (CHECK_IMAGE, "Ei kuvausta (hero image)"),
        (CHECK_THIN, f"Lyhyt sisältö (alle {MIN_WORDS} sanaa)"),
        (CHECK_DUPLICATE_TITLE, "Kaksoisotsikot"),
        (CHECK_CATEGORIES, "Ei kategoriaa"),
        (CHECK_TAGS, "Ei tunnisteita"),
        (CHECK_BROKEN_IMAGE, "Rikkinäinen kuvaosoite"),
    ]
    for key, label in check_labels:
        n = counts.get(key, 0)
        if n > 0:
            emoji = "⚠️" if key == CHECK_TAGS else "🔴"
            lines.append(f"{emoji} **{label}:** {n} kpl")
        else:
            lines.append(f"✅ {label}: OK")

    # Top 10 worst offenders (by most issues per article)
    # Flatten to per-article issue counts
    article_issues: dict[str, list[str]] = defaultdict(list)
    for check_key, items in issues.items():
        if check_key == CHECK_DUPLICATE_TITLE:
            continue
        for item in items:
            slug = item.get("slug", item.get("files", ["?"])[0] if isinstance(item.get("files"), list) else "?")
            article_issues[slug].append(check_key)

    multi_issue = [(slug, checks) for slug, checks in article_issues.items() if len(checks) >= 2]
    multi_issue.sort(key=lambda x: -len(x[1]))

    if multi_issue:
        lines.append("")
        lines.append(f"**Top {min(10, len(multi_issue))} ongelmallisinta artikkelia:**")
        for slug, checks in multi_issue[:10]:
            issue_list = ", ".join(checks)
            lines.append(f"- `{slug[:60]}` ({len(checks)} ongelmaa: {issue_list})")

    if issues.get(CHECK_DUPLICATE_TITLE):
        lines.append("")
        lines.append(f"**Kaksoisotsikot ({len(issues[CHECK_DUPLICATE_TITLE])} ryhmää):**")
        for dup in issues[CHECK_DUPLICATE_TITLE][:5]:
            lines.append(f'- "{dup["title"][:50]}" — {dup["count"]} versiota')

    return "\n".join(lines)


def post_to_discord(message: str) -> bool:
    if DISCORD_WEBHOOK_OPS:
        payload = json.dumps({"content": message}).encode()
        req = urllib.request.Request(
            DISCORD_WEBHOOK_OPS,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 204)
        except urllib.error.HTTPError as e:
            print(f"Webhook error: {e.code}", file=sys.stderr)

    if DISCORD_BOT_TOKEN:
        url = f"https://discord.com/api/v10/channels/{OPERATIONS_CHANNEL_ID}/messages"
        payload = json.dumps({"content": message}).encode()
        req = urllib.request.Request(
            url, data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 201)
        except urllib.error.HTTPError as e:
            print(f"Bot token error: {e.code}", file=sys.stderr)

    return False


def save_log(result: dict) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    history = []
    if VALIDATION_LOG.exists():
        try:
            history = json.loads(VALIDATION_LOG.read_text())
        except json.JSONDecodeError:
            pass

    # Trim per-issue lists for storage (keep counts + top 50 offenders)
    stored = dict(result)
    stored["issues"] = {
        k: v[:50] for k, v in result["issues"].items()
    }
    history.append(stored)
    history = history[-30:]  # keep 30 runs
    VALIDATION_LOG.write_text(json.dumps(history, indent=2))


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    fix_descriptions = "--fix-descriptions" in args
    check_images = "--check-images" in args
    limit = None

    if "--limit" in args:
        idx = args.index("--limit")
        if idx + 1 < len(args):
            limit = int(args[idx + 1])

    print(f"🔍 Article validator — fix={fix_descriptions}, images={check_images}, limit={limit}")

    result = validate_articles(
        check_images=check_images,
        fix_descriptions=fix_descriptions,
        dry_run=dry_run,
        limit=limit,
    )

    counts = result["counts"]
    print(f"\n✓ Done. Score: {result['health_score']}/100")
    for k, n in counts.items():
        print(f"  {k}: {n}")
    if result.get("fixed_descriptions"):
        print(f"  Fixed descriptions: {result['fixed_descriptions']}")

    message = format_discord_message(result)
    print(f"\n--- Discord message ---\n{message}\n---")

    if not dry_run:
        save_log(result)
        ok = post_to_discord(message)
        if ok:
            print("✅ Posted to #operations")
        else:
            print("⚠️  Discord post failed (no webhook/token configured)")
    else:
        print("(dry-run: not posting or saving)")


if __name__ == "__main__":
    main()
