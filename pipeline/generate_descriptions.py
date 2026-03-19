#!/usr/bin/env python3
"""
Batch-generate meta descriptions for all articles that lack one.
Also integrates into pipeline for new articles.

Usage:
  # Batch mode — process all existing articles
  python3 pipeline/generate_descriptions.py --batch

  # Single article (pipe from publisher)
  python3 pipeline/generate_descriptions.py --article path/to/article.md

  # Dry run (show what would be written, don't modify files)
  python3 pipeline/generate_descriptions.py --batch --dry-run

Requirements: ANTHROPIC_API_KEY in environment
"""

import os
import sys
import json
import re
import time
import argparse
import urllib.request
import urllib.error
from pathlib import Path

CONTENT_DIR = Path(__file__).parent.parent / "content" / "posts"
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5"
MIN_CHARS = 120
MAX_CHARS = 158

SYSTEM_PROMPT = (
    "You are writing a meta description for a Finnish news article for Google search results.\n\n"
    "RULES:\n"
    "- Language: Finnish (match the article language exactly)\n"
    "- Length: 140–155 characters (including spaces)\n"
    "- End at a sentence boundary — never cut mid-sentence or mid-word\n"
    "- Do NOT start with the site name or \"Lue lisää\"\n"
    "- Do NOT use clickbait (\"Hämmästyttävää!\", \"Et usko...\")\n"
    "- Lead with the most newsworthy fact — WHO did WHAT\n"
    "- Present tense preferred when describing ongoing situations\n"
    "- Past tense for completed events\n"
    "- Avoid passive voice when active is natural\n\n"
    "Return ONLY the meta description text. No quotes, no labels, no explanation."
)


def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    return key


def call_claude(headline: str, lead_text: str, api_key: str) -> str:
    """Call Claude API via urllib (no SDK dependency)."""
    user_msg = f"Article headline: {headline}\nArticle body (first 500 chars): {lead_text}"

    payload = {
        "model": MODEL,
        "max_tokens": 200,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_msg}],
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result["content"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API error {e.code}: {body}")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML front matter from markdown. Returns (frontmatter_dict, body)."""
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    fm_raw = text[3:end].strip()
    body = text[end + 4:].strip()

    # Simple key: "value" parser (handles our front matter format)
    fm = {}
    for line in fm_raw.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            v = v.strip().strip('"')
            if v:
                fm[k.strip()] = v
            else:
                fm[k.strip()] = ""
    return fm, body


def inject_description(file_path: Path, description: str, dry_run: bool = False) -> bool:
    """Inject description into front matter. Returns True if file was modified."""
    text = file_path.read_text(encoding="utf-8")

    if not text.startswith("---"):
        print(f"  SKIP (no front matter): {file_path.name}")
        return False

    end = text.find("\n---", 3)
    if end == -1:
        print(f"  SKIP (malformed front matter): {file_path.name}")
        return False

    fm_block = text[3:end]
    rest = text[end:]

    # Check if description already exists
    if re.search(r'^description:', fm_block, re.MULTILINE):
        print(f"  SKIP (already has description): {file_path.name}")
        return False

    # Escape quotes in description
    safe_desc = description.replace('"', '\\"')
    new_fm = fm_block + f'\ndescription: "{safe_desc}"'
    new_text = "---" + new_fm + rest

    if dry_run:
        print(f"  DRY-RUN would write: {description[:80]}...")
        return True

    file_path.write_text(new_text, encoding="utf-8")
    return True


def process_file(file_path: Path, api_key: str, dry_run: bool = False) -> bool:
    """Generate and inject description for a single file. Returns True on success."""
    text = file_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)

    # Skip if already has description
    if "description" in fm and fm["description"]:
        print(f"  SKIP: {file_path.name} (has description)")
        return False

    headline = fm.get("title", "")
    if not headline:
        print(f"  SKIP: {file_path.name} (no title)")
        return False

    # First 500 chars of body
    lead_text = body[:500].strip()
    if not lead_text:
        print(f"  SKIP: {file_path.name} (empty body)")
        return False

    # Generate
    try:
        description = call_claude(headline, lead_text, api_key)
    except Exception as e:
        print(f"  ERROR: {file_path.name}: {e}")
        return False

    # Validate length
    char_count = len(description)
    if char_count < MIN_CHARS or char_count > MAX_CHARS:
        print(f"  FLAG: {file_path.name}: {char_count} chars (outside {MIN_CHARS}-{MAX_CHARS}): {description[:60]}")
        # Still inject but flag it
        if not dry_run:
            inject_description(file_path, description, dry_run=False)
        return False  # Caller can decide to review

    inject_description(file_path, description, dry_run=dry_run)
    print(f"  OK [{char_count}]: {file_path.name}")
    return True


def generate_for_article_dict(article: dict, api_key: str) -> str | None:
    """
    Pipeline integration: generate description for an article dict.
    Called from publisher.py before writing front matter.
    Returns description string or None on failure.
    """
    headline = article.get("title", "")
    body = article.get("body", article.get("content", ""))
    lead_text = body[:500].strip() if body else ""

    if not headline or not lead_text:
        return None

    try:
        desc = call_claude(headline, lead_text, api_key)
        if MIN_CHARS <= len(desc) <= MAX_CHARS:
            return desc
        # Outside range — try to trim at sentence boundary
        if len(desc) > MAX_CHARS:
            # Find last sentence end before MAX_CHARS
            truncated = desc[:MAX_CHARS]
            last_dot = max(truncated.rfind(". "), truncated.rfind("! "), truncated.rfind("? "))
            if last_dot > MIN_CHARS:
                return truncated[:last_dot + 1]
        return desc  # Use as-is rather than skip
    except Exception:
        return None


def batch_mode(dry_run: bool = False):
    api_key = get_api_key()
    files = sorted(CONTENT_DIR.glob("*.md"))
    total = len(files)
    processed = 0
    skipped = 0
    flagged = 0
    errors = 0

    print(f"Processing {total} articles...")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}\n")

    for i, f in enumerate(files):
        print(f"[{i+1}/{total}] {f.name}")
        result = process_file(f, api_key, dry_run=dry_run)
        if result:
            processed += 1
        elif "SKIP" in str(result):
            skipped += 1

        # Rate limit: ~3 req/sec to be safe
        time.sleep(0.35)

    print(f"\nDone: {processed} written, {skipped} skipped, {flagged} flagged, {errors} errors")


def single_article_mode(article_path: str, dry_run: bool = False):
    api_key = get_api_key()
    f = Path(article_path)
    if not f.exists():
        print(f"ERROR: {article_path} not found", file=sys.stderr)
        sys.exit(1)
    process_file(f, api_key, dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate meta descriptions for articles")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--batch", action="store_true", help="Process all articles in content/posts/")
    group.add_argument("--article", metavar="PATH", help="Process a single article file")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be written without modifying files")
    args = parser.parse_args()

    if args.batch:
        batch_mode(dry_run=args.dry_run)
    elif args.article:
        single_article_mode(args.article, dry_run=args.dry_run)
