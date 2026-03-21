#!/usr/bin/env python3
"""
backfill_tags.py — Keyword-based tag backfill for existing articles.

Reads all content/posts/*.md, skips articles that already have tags:
in front matter. For the rest, extracts 2–5 tags via TF-IDF-style
frequency analysis on Finnish text, filtering stopwords.

Usage:
    python3 backfill_tags.py [--dry-run] [--limit N] [--posts-dir PATH]
"""

import argparse
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Finnish stopwords (~300 common words)
# ---------------------------------------------------------------------------
FI_STOPWORDS = {
    # Pronouns
    "minä", "sinä", "hän", "me", "te", "he", "se", "ne",
    "minun", "sinun", "hänen", "meidän", "teidän", "heidän",
    "minulle", "sinulle", "hänelle", "meille", "teille", "heille",
    "minut", "sinut", "hänet", "meidät", "teidät", "heidät",
    "minulla", "sinulla", "hänellä", "meillä", "teillä", "heillä",
    "minusta", "sinusta", "hänestä", "meistä", "teistä", "heistä",
    "itse", "itsen", "itsensä", "itselleni",

    # Demonstratives
    "tämä", "tuo", "se", "nämä", "nuo", "ne", "tämän", "tuon",
    "tässä", "tuossa", "siinä", "täällä", "tuolla", "siellä",
    "tähän", "tuohon", "siihen", "tältä", "tuolta", "siltä",
    "täksi", "tuoksi", "siksi",

    # Question words
    "kuka", "mikä", "missä", "mistä", "mihin", "millä", "miltä",
    "miksi", "miten", "kuinka", "milloin", "kuka", "kenen", "ketä",
    "ken", "joka", "jotka", "joka", "jonka", "jolta", "jolle",
    "josta", "johon", "jolla", "jolle",

    # Common verbs (stem forms used in text)
    "on", "oli", "olla", "ole", "olisi", "ollut", "olleet",
    "ei", "eivät", "en", "et", "emme", "ette", "ovat",
    "on", "olen", "olet", "olemme", "olette",
    "on", "oli", "olivat", "olimme", "olitte",
    "tulee", "tuli", "tulla", "tulisi", "tullut",
    "menee", "meni", "mennä", "menisi", "mennyt",
    "tekee", "teki", "tehdä", "tekisi", "tehnyt", "tehty",
    "saa", "sai", "saada", "saisi", "saanut",
    "voi", "voi", "voida", "voisi", "voinut",
    "pitää", "piti", "täytyy", "täytyi",
    "haluaa", "halusi", "haluta",
    "sanoo", "sanoi", "sanoa",
    "kertoo", "kertoi", "kertoa",
    "käy", "kävi", "käydä",
    "antaa", "antoi", "antaa",
    "ottaa", "otti", "ottaa",
    "näkee", "näki", "nähdä",
    "ajattelee", "ajatteli",

    # Conjunctions & particles
    "ja", "tai", "vai", "mutta", "vaan", "sekä", "ettei",
    "että", "jotta", "koska", "kun", "jos", "vaikka", "kuin",
    "niin", "siis", "myös", "myöskään", "sekään",
    "myös", "vielä", "jo", "enää", "kyllä", "ehkä",
    "kai", "kenties", "aina", "usein", "harvoin",
    "nyt", "sitten", "juuri", "heti", "kohta",
    "jo", "vasta", "vain", "vain", "ainoastaan",
    "paljon", "vähän", "hyvin", "erittäin",

    # Prepositions / postpositions
    "yli", "alle", "läpi", "kautta", "kohti", "lähellä",
    "kaukana", "välillä", "välillä", "mukaan", "jälkeen",
    "ennen", "jälkeen", "aikana", "lisäksi", "sijaan",
    "puolesta", "vastaan", "takia", "vuoksi", "avulla",

    # Common adjectives (generic)
    "uusi", "vanha", "suuri", "pieni", "hyvä", "huono",
    "pitkä", "lyhyt", "korkea", "matala", "iso", "pienin",
    "suurin", "parempi", "paras", "huonoin", "ensimmäinen",
    "toinen", "kolmas", "viimeinen", "eri", "sama", "sellainen",
    "tällainen", "molemmat", "kaikki", "moni", "jokainen",
    "mikään", "kukaan", "eräs", "muutama", "useita",

    # Numbers (written)
    "yksi", "kaksi", "kolme", "neljä", "viisi", "kuusi",
    "seitsemän", "kahdeksan", "yhdeksän", "kymmenen",
    "sata", "tuhat", "miljoona",
    "ensimmäinen", "toinen", "kolmas",

    # Time expressions
    "tänään", "eilen", "huomenna", "tällä", "viikolla",
    "kuukausi", "vuosi", "päivä", "tunti", "minuutti",
    "vuonna", "viikko", "kuun", "päivänä",

    # Common nouns (too generic for tags)
    "asia", "asiat", "asia", "tilanne", "tilanteen",
    "tapa", "tavalla", "puoli", "puolen",
    "osa", "osia", "osuus", "osuuden",
    "tulos", "tulokset", "tulosten",
    "syy", "syitä", "syyn",
    "kohde", "kohdetta",
    "henkilö", "henkilöt",
    "paikka", "paikkaan",
    "aika", "aikaan", "ajan",
    "teko", "tekoa",
    "kysymys", "kysymykseen",
    "käyttö", "käyttöä",
    "muutos", "muutosta",
    "yhteisö", "yhteisön",
    "tapahtuma", "tapahtumaa",
    "toiminta", "toimintaa",

    # Articles / misc Finnish function words
    "sen", "sen", "niiden", "niitä", "sitä", "tätä", "niistä",
    "sille", "hänelle", "niille", "näille",
    "kaikki", "kaikki", "kaikkien", "kaikkia",
    "jokin", "jonkin", "joitain",
    "sekä", "sekä",

    # Common abbreviations / words in headlines
    "uutiset", "artikkeli", "lue", "lisää",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
WORD_RE = re.compile(r"[a-zäöåA-ZÄÖÅ][a-zäöå]{3,}", re.UNICODE)

# Suffixes that produce fragment artifacts when titles/URLs are split on hyphens
_SUFFIX_ARTIFACTS = re.compile(
    r"^(ssa|ssä|sta|stä|lle|lta|ltä|lla|llä|han|hän|hin|hun|hyn|"
    r"ksi|nsa|nsä|nta|ntä|nen|tta|ttä|ssa|kin|kaan|kään|mme|nne|"
    r"kin|pää|ensi|siis|joten|siten|koska)$"
)


def parse_front_matter(text: str) -> Tuple[Optional[str], str]:
    """Return (front_matter_block, body) or (None, text) if not found."""
    m = FRONT_MATTER_RE.match(text)
    if m:
        return m.group(1), text[m.end():]
    return None, text


def has_tags(front_matter: str) -> bool:
    return bool(re.search(r"^tags\s*:", front_matter, re.MULTILINE))


def tokenize(text: str) -> List[str]:
    """Extract lowercase word tokens, filter stopwords and suffix artifacts."""
    words = []
    for w in WORD_RE.findall(text):
        w = w.lower()
        if w in FI_STOPWORDS:
            continue
        if _SUFFIX_ARTIFACTS.match(w):
            continue
        words.append(w)
    return words


def extract_tags(body: str, title: str, top_n: int = 5) -> List[str]:
    """
    TF-IDF-style extraction:
    - Tokenize body + title (title weighted 3x)
    - Count term frequency
    - Apply inverse document frequency using a small corpus proxy
      (article length as a normalizer)
    - Return top_n unique candidates
    """
    title_tokens = tokenize(title)
    body_tokens = tokenize(body)

    # Weight title tokens 3x — they're the most signal-dense part
    all_tokens = title_tokens * 3 + body_tokens

    if not all_tokens:
        return []

    tf = Counter(all_tokens)
    total = len(all_tokens)

    # Score: TF * log(1 + freq_in_title_bonus)
    # Simple heuristic: title words get a 2x IDF boost (act as rare signal)
    title_set = set(title_tokens)
    scores: Dict[str, float] = {}
    for term, count in tf.items():
        tf_score = count / total
        # Mild penalty for very common terms even if not in stoplist
        idf_boost = 2.0 if term in title_set else 1.0
        scores[term] = tf_score * idf_boost

    # Sort by score desc, take top candidates
    ranked = sorted(scores.items(), key=lambda x: -x[1])

    # Post-filter: skip anything that looks like a number or too generic
    tags = []
    seen = set()
    for term, _score in ranked:
        if term in seen:
            continue
        # Skip pure numbers
        if term.isdigit():
            continue
        # Skip very high-frequency filler even if not in stopwords list
        # (more than 8% of tokens suggests it's a structural word)
        if tf[term] / total > 0.08 and term not in title_set:
            continue
        tags.append(term)
        seen.add(term)
        if len(tags) >= top_n:
            break

    return tags


def inject_tags(front_matter: str, tags: List[str]) -> str:
    """Append tags block to front matter (before closing)."""
    tags_yaml = "tags:\n" + "\n".join(f"  - {t}" for t in tags)
    return front_matter.rstrip() + "\n" + tags_yaml


def process_file(
    path: Path, dry_run: bool = False
) -> Optional[Tuple[str, List[str]]]:
    """
    Process a single file. Returns (slug, tags) if processed, None if skipped.
    """
    text = path.read_text(encoding="utf-8")
    fm, body = parse_front_matter(text)

    if fm is None:
        return None  # No front matter — skip

    if has_tags(fm):
        return None  # Already tagged

    # Extract title from front matter
    title_match = re.search(r'^title:\s*["\']?(.*?)["\']?\s*$', fm, re.MULTILINE)
    title = title_match.group(1) if title_match else ""

    tags = extract_tags(body, title, top_n=5)

    # Ensure minimum 2 tags
    if len(tags) < 2:
        return None  # Too little signal — skip rather than write garbage

    if not dry_run:
        new_fm = inject_tags(fm, tags)
        new_text = f"---\n{new_fm}\n---\n{body}"
        path.write_text(new_text, encoding="utf-8")

    return path.stem, tags


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill tags for existing articles.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be written without modifying files.")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Process at most N articles.")
    parser.add_argument("--posts-dir", default=None,
                        help="Path to content/posts directory (auto-detected if omitted).")
    args = parser.parse_args()

    # Auto-detect posts dir relative to this script
    if args.posts_dir:
        posts_dir = Path(args.posts_dir)
    else:
        script_dir = Path(__file__).resolve().parent
        posts_dir = script_dir.parent / "content" / "posts"

    if not posts_dir.is_dir():
        print(f"ERROR: posts directory not found: {posts_dir}", file=sys.stderr)
        sys.exit(1)

    files = sorted(posts_dir.glob("*.md"))
    total = len(files)
    print(f"Found {total} article(s) in {posts_dir}")

    if args.limit:
        files = files[: args.limit]
        print(f"Limiting to {args.limit} article(s)")

    if args.dry_run:
        print("DRY RUN — no files will be modified\n")

    processed = 0
    skipped_tagged = 0
    skipped_signal = 0

    for path in files:
        text = path.read_text(encoding="utf-8")
        fm, body = parse_front_matter(text)

        if fm is None:
            skipped_signal += 1
            continue

        if has_tags(fm):
            skipped_tagged += 1
            continue

        title_match = re.search(r'^title:\s*["\']?(.*?)["\']?\s*$', fm, re.MULTILINE)
        title = title_match.group(1) if title_match else ""
        tags = extract_tags(body, title, top_n=5)

        if len(tags) < 2:
            print(f"  SKIP (low signal)  {path.name}")
            skipped_signal += 1
            continue

        action = "WOULD TAG" if args.dry_run else "TAGGED"
        print(f"  {action:10s}  {path.stem[:55]:<55}  {tags}")

        if not args.dry_run:
            new_fm = inject_tags(fm, tags)
            new_text = f"---\n{new_fm}\n---\n{body}"
            path.write_text(new_text, encoding="utf-8")

        processed += 1

    print(f"\nDone. Processed: {processed} | Already tagged: {skipped_tagged} | Low signal: {skipped_signal}")
    if args.dry_run:
        print("(No files modified — dry run)")


if __name__ == "__main__":
    main()
