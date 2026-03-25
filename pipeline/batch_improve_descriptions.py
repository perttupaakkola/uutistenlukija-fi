#!/usr/bin/env python3
"""
batch_improve_descriptions.py — AI-powered description improvement for auto-truncated articles.

Targets articles where the meta description is just the first sentence of the body
(auto-truncated heuristic), NOT articles that already have properly written descriptions.

Usage:
  python3 pipeline/batch_improve_descriptions.py --limit 5 --dry-run   # preview 5
  python3 pipeline/batch_improve_descriptions.py --limit 50 --offset 0  # batch 1
  python3 pipeline/batch_improve_descriptions.py --limit 50 --offset 50 # batch 2

Requirements: OPENAI_API_KEY in environment
"""

import os, re, sys, time, json, argparse
from pathlib import Path
from datetime import datetime
from openai import OpenAI

CONTENT_DIR = Path(__file__).parent.parent / "content" / "posts"
LOG_DIR = Path(__file__).parent / "logs"
MODEL = "gpt-4o-mini"
MIN_CHARS = 115
MAX_CHARS = 145
RATE_LIMIT_DELAY = 0.3

SYSTEM_PROMPT = (
    "You are writing a meta description for a Finnish news article for Google search results.\n\n"
    "RULES:\n"
    "- Language: Finnish (match the article language exactly)\n"
    "- Length: 120-145 characters (including spaces) — max 145, never exceed\n"
    "- End at a sentence boundary — never cut mid-sentence or mid-word\n"
    "- Do NOT start with the site name or 'Lue lisää'\n"
    "- Do NOT use clickbait ('Hämmästyttävää!', 'Et usko...')\n"
    "- Lead with the most newsworthy fact — WHO did WHAT\n"
    "- Must be meaningfully different from the article's first sentence\n"
    "- Present tense preferred for ongoing situations, past tense for completed events\n"
    "- Avoid passive voice when active is natural\n\n"
    "Return ONLY the meta description text. No quotes, no labels, no explanation."
)

_client = None

def get_client():
    global _client
    if _client is None:
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
            sys.exit(1)
        _client = OpenAI(api_key=key)
    return _client

def is_auto_truncated(desc, body):
    if not desc or not body:
        return False
    body_start = body[:200].replace("\n", " ").strip()
    desc_clean = desc[:100].strip()
    return desc_clean in body_start

def parse_frontmatter(text):
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_raw = text[3:end].strip()
    body = text[end + 4:].strip()
    fm = {}
    for line in fm_raw.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"')
    return fm, body

def generate_description(headline, body):
    lead = body[:500].strip()
    r = get_client().chat.completions.create(
        model=MODEL, max_tokens=200,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Article headline: {headline}\nArticle body (first 500 chars): {lead}"},
        ],
    )
    return r.choices[0].message.content.strip()

def update_description(file_path, new_desc, dry_run=False):
    text = file_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end == -1:
        return False
    fm_block = text[3:end]
    rest = text[end:]
    safe_desc = new_desc.replace('"', '\\"')
    if re.search(r'^description:', fm_block, re.MULTILINE):
        new_fm = re.sub(r'^description:.*$', f'description: "{safe_desc}"', fm_block, flags=re.MULTILINE)
    else:
        new_fm = fm_block + f'\ndescription: "{safe_desc}"'
    if not dry_run:
        file_path.write_text("---" + new_fm + rest, encoding="utf-8")
    return True

def find_auto_truncated():
    result = []
    for f in sorted(CONTENT_DIR.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        if end == -1:
            continue
        fm_block = text[3:end]
        body = text[end + 4:].strip()
        desc = ""
        for line in fm_block.splitlines():
            if line.startswith("description:"):
                _, _, v = line.partition(":")
                desc = v.strip().strip('"')
                break
        if desc and is_auto_truncated(desc, body):
            result.append(f)
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    get_client()
    print("Scanning for auto-truncated descriptions...")
    candidates = find_auto_truncated()
    print(f"Found {len(candidates)} auto-truncated articles")

    batch = candidates[args.offset:args.offset + args.limit]
    print(f"Processing {len(batch)} (offset={args.offset}, limit={args.limit})")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}\n")

    results = []
    ok = flagged = errors = 0

    for i, f in enumerate(batch):
        text = f.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(text)
        headline = fm.get("title", "")
        old_desc = fm.get("description", "")

        print(f"[{i+1}/{len(batch)}] {f.name[:60]}")
        print(f"  OLD ({len(old_desc)}): {old_desc[:80]}")

        if not headline or not body:
            print(f"  SKIP: missing title or body")
            errors += 1
            continue

        try:
            new_desc = generate_description(headline, body)
        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1
            results.append({"file": f.name, "status": "error", "error": str(e)})
            time.sleep(RATE_LIMIT_DELAY)
            continue

        char_count = len(new_desc)
        ends_clean = new_desc[-1] in ".!?»" if new_desc else False
        print(f"  NEW ({char_count}): {new_desc}")

        if char_count < MIN_CHARS or char_count > MAX_CHARS or not ends_clean:
            status = "flagged"; flagged += 1
            print(f"  ⚠️  FLAGGED: {char_count} chars")
        else:
            status = "ok"; ok += 1
            print(f"  ✅ OK")

        results.append({"file": f.name, "status": status, "old_desc": old_desc,
                        "new_desc": new_desc, "char_count": char_count})

        if not args.dry_run:
            update_description(f, new_desc)

        time.sleep(RATE_LIMIT_DELAY)

    print(f"\n{'='*60}")
    print(f"Summary: {ok} OK, {flagged} flagged, {errors} errors / {len(batch)} processed")

    if not args.dry_run and results:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        log_file = LOG_DIR / f"batch_improve_descriptions_{ts}.json"
        log_file.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"Log: {log_file}")

if __name__ == "__main__":
    main()
