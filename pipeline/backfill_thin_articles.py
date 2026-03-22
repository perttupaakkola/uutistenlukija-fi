"""
backfill_thin_articles.py — Expands thin articles that are too short for SEO.

Reads published content/posts/*.md files, identifies those under --max-words,
rewrites them via the LLM to meet the 300-400w target, and overwrites the
original file in place.

Usage:
    python3 backfill_thin_articles.py --max-words 50 --batch 10
    python3 backfill_thin_articles.py --max-words 100 --batch 5 --dry-run
    python3 backfill_thin_articles.py --status

Output JSON (for cron wrapper to parse):
    {"expanded": N, "skipped": N, "failed": N,
     "avg_before": X.X, "avg_after": Y.Y,
     "articles": [{"file": ..., "before": N, "after": N}, ...]}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────────

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR  = os.path.dirname(_PIPELINE_DIR)
CONTENT_DIR   = os.path.join(_PROJECT_DIR, "content", "posts")

# ── Frontmatter parsing ───────────────────────────────────────────────────────

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

def _parse_article(path: str) -> tuple[dict, str] | None:
    """Return (frontmatter_dict, body_text) or None on parse error."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()

    m = _FM_RE.match(raw)
    if not m:
        return None

    fm_text = m.group(1)
    body = raw[m.end():]

    # Parse YAML frontmatter manually (avoid yaml dep)
    fm: dict = {}
    current_list_key = None
    for line in fm_text.splitlines():
        if line.startswith("  - ") and current_list_key:
            fm.setdefault(current_list_key, []).append(line[4:].strip().strip('"'))
            continue
        current_list_key = None
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"')
        if val == "":
            current_list_key = key  # next lines may be list items
        elif val.lower() == "true":
            fm[key] = True
        elif val.lower() == "false":
            fm[key] = False
        else:
            fm[key] = val

    return fm, body.strip()


def _word_count(text: str) -> int:
    return len(text.split())


def _rebuild_file(path: str, fm: dict, new_body: str) -> None:
    """Write back the article file with updated body but original frontmatter."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()

    m = _FM_RE.match(raw)
    if not m:
        raise ValueError(f"No frontmatter in {path}")

    fm_block = raw[: m.end()]
    with open(path, "w", encoding="utf-8") as f:
        f.write(fm_block)
        f.write(new_body)
        f.write("\n")


# ── LLM expansion ─────────────────────────────────────────────────────────────

EXPAND_SYSTEM = """Olet kokenut suomalainen uutistoimittaja. Tehtäväsi on laajentaa lyhyt uutisartikkeli täysimittaiseksi artikkeliksi.

SÄÄNNÖT:
- Kirjoita VÄHINTÄÄN 320 sanaa (tavoite 350–420 sanaa). Lyhyempi teksti ei kelpaa.
- Säilytä alkuperäinen otsikko ja ydintieto täysin ennallaan.
- Lisää kontekstia, taustaa, seurauksia ja laajempaa merkitystä.
- Kirjoita AINA suomeksi.
- Käytä 5–7 kappaletta ja 1–2 H2-väliotsikkoa (## Otsikko).
- Älä keksi faktoja — laajenna käyttäen yleistä kontekstitietoa aiheesta.
- Palauta VAIN artikkelin teksti. Ei otsikkoa, ei JSON-muotoilua."""

def _expand_article(title: str, body: str) -> Optional[str]:
    """Call LLM to expand a thin article. Returns new body text or None on failure."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        prompt = f"""Laajenna tämä lyhyt uutisartikkeli 300–400 sanan artikkeliksi.

Otsikko: {title}

Nykyinen teksti:
{body}

Kirjoita laajennettu versio (VAIN teksti, ei otsikkoa):"""

        for attempt in range(2):
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": EXPAND_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7 + attempt * 0.1,
                max_tokens=1200,
            )
            result = resp.choices[0].message.content.strip()
            if len(result.split()) >= 280:
                return result
            # Too short — retry with explicit nudge
            prompt += f"\n\nMUISTA: tekstin on oltava vähintään 320 sanaa. Edellinen yritys tuotti vain {len(result.split())} sanaa."
        return result  # Return best attempt even if short
    except Exception as e:
        print(f"[backfill] LLM error: {e}", file=sys.stderr)
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def find_thin_articles(max_words: int) -> list[tuple[int, str]]:
    """Return list of (word_count, filepath) for articles under max_words."""
    thin = []
    for fn in sorted(os.listdir(CONTENT_DIR)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(CONTENT_DIR, fn)
        parsed = _parse_article(path)
        if not parsed:
            continue
        _, body = parsed
        wc = _word_count(body)
        if wc < max_words:
            thin.append((wc, path))
    thin.sort()  # shortest first
    return thin


def backfill(max_words: int = 50, batch: int = 10, dry_run: bool = False) -> dict:
    """
    Find and expand thin articles.

    Returns result dict with stats (same format written to stdout for cron wrapper).
    """
    thin = find_thin_articles(max_words)
    batch_articles = thin[:batch]

    print(f"[backfill] Found {len(thin)} articles under {max_words}w. Processing {len(batch_articles)}.")

    results = []
    expanded = skipped = failed = 0
    before_words = []
    after_words = []

    for wc_before, path in batch_articles:
        fname = os.path.basename(path)
        parsed = _parse_article(path)
        if not parsed:
            print(f"[backfill] SKIP {fname} — parse error")
            skipped += 1
            continue

        fm, body = parsed
        title = fm.get("title", fname)

        print(f"[backfill] {'[DRY] ' if dry_run else ''}Expanding '{title[:60]}' ({wc_before}w)...")

        if dry_run:
            print(f"[backfill]   Would expand {fname} ({wc_before}w)")
            skipped += 1
            continue

        new_body = _expand_article(title, body)
        if not new_body:
            print(f"[backfill] FAILED {fname}")
            failed += 1
            continue

        wc_after = _word_count(new_body)

        # Sanity check — don't accept if LLM returned something shorter
        if wc_after <= wc_before:
            print(f"[backfill] SKIP {fname} — expansion not longer ({wc_before}→{wc_after}w)")
            skipped += 1
            continue

        _rebuild_file(path, fm, new_body)
        expanded += 1
        before_words.append(wc_before)
        after_words.append(wc_after)
        results.append({"file": fname, "before": wc_before, "after": wc_after})
        print(f"[backfill] OK {fname}: {wc_before}→{wc_after}w")

        # Polite rate limiting
        time.sleep(0.5)

    avg_before = round(sum(before_words) / len(before_words), 1) if before_words else 0
    avg_after  = round(sum(after_words)  / len(after_words),  1) if after_words  else 0
    remaining  = max(0, len(thin) - batch)

    output = {
        "expanded":   expanded,
        "skipped":    skipped,
        "failed":     failed,
        "avg_before": avg_before,
        "avg_after":  avg_after,
        "total_thin": len(thin),
        "remaining":  remaining,
        "max_words":  max_words,
        "articles":   results,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }

    print(f"[backfill] Done: {expanded} expanded, {skipped} skipped, {failed} failed. "
          f"Avg {avg_before}→{avg_after}w. {remaining} still remaining at <{max_words}w.")

    return output


def status(max_words_tiers: list[int] = (50, 100, 150, 200)) -> None:
    """Print tier breakdown of thin articles."""
    all_articles = []
    for fn in sorted(os.listdir(CONTENT_DIR)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(CONTENT_DIR, fn)
        parsed = _parse_article(path)
        if parsed:
            _, body = parsed
            all_articles.append(_word_count(body))

    print(f"Total articles: {len(all_articles)}")
    for threshold in max_words_tiers:
        count = sum(1 for w in all_articles if w < threshold)
        print(f"  <{threshold:4d}w: {count:4d} articles")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill thin articles via LLM expansion")
    parser.add_argument("--max-words", type=int, default=50,
                        help="Target articles under this word count (default: 50)")
    parser.add_argument("--batch", "--limit", type=int, default=10, dest="batch",
                        help="Max articles to process per run (default: 10)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be expanded without modifying files")
    parser.add_argument("--status", action="store_true",
                        help="Show word count tier breakdown and exit")
    parser.add_argument("--json", action="store_true",
                        help="Output result as JSON (for cron wrapper)")
    args = parser.parse_args()

    if args.status:
        status()
        sys.exit(0)

    result = backfill(max_words=args.max_words, batch=args.batch, dry_run=args.dry_run)

    if args.json:
        print("\n__RESULT_JSON__")
        print(json.dumps(result))
