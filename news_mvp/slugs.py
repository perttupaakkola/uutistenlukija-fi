"""Readable article URLs derived from the reviewed headline.

Measured problem: every article lived at `/uutiset/<64-char sha256>/`. The hash carries
no keywords, is unreadable in a share, and gives a search engine nothing to match on —
part of why 8,443 impressions converted at only 1.75% CTR.

A slug is derived deterministically from the published title and the job id, so:

  - the same article always produces the same slug (no churn across rebuilds),
  - the job id stays the stable identity and remains the suffix, keeping every slug
    unique even when two articles share a headline,
  - the old hash URL keeps working via a redirect, so nothing already indexed breaks.

Finnish characters are transliterated (ä->a, ö->o, å->a) because non-ASCII in a path is
percent-encoded in the SERP, which reads worse than the plain ASCII form.
"""

import re
import unicodedata

MAX_SLUG_WORDS = 8
MAX_SLUG_CHARS = 60
ID_SUFFIX = 12

# Finnish and common Nordic letters map to plain ASCII rather than being dropped.
_TRANSLITERATE = str.maketrans({
    "ä": "a", "ö": "o", "å": "a", "Ä": "A", "Ö": "O", "Å": "A",
    "š": "s", "ž": "z", "ü": "u", "é": "e", "è": "e", "á": "a",
})

# Words that carry no search value in a URL and only consume slug width.
_STOPWORDS = {
    "ja", "tai", "on", "ei", "se", "että", "kun", "myös", "sekä", "mutta",
    "eli", "joka", "joka", "tämä", "näin", "varten", "kanssa", "mukaan",
}


def slugify(text, max_words=MAX_SLUG_WORDS, max_chars=MAX_SLUG_CHARS):
    """ASCII, lowercase, hyphenated slug from a headline."""
    if not text:
        return ""
    value = unicodedata.normalize("NFKC", str(text)).translate(_TRANSLITERATE)
    # Decompose any remaining accents, then strip what is left.
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    if not value:
        return ""
    words = [w for w in value.split("-") if w]
    # Drop stopwords only if enough substance remains; never empty the slug.
    trimmed = [w for w in words if w not in _STOPWORDS]
    if len(trimmed) >= 2:
        words = trimmed
    words = words[:max_words]
    slug = "-".join(words)
    if len(slug) > max_chars:
        slug = slug[:max_chars].rsplit("-", 1)[0]
    return slug.strip("-")


def article_slug(job_id, title):
    """`<readable-slug>-<id-prefix>`, or a bare id prefix when no slug is possible.

    The id suffix guarantees uniqueness and stays stable even if the title is later
    edited, so a slug is never silently reassigned to a different article.
    """
    identifier = str(job_id)
    suffix = identifier[:ID_SUFFIX]
    base = slugify(title)
    return f"{base}-{suffix}" if base else suffix


def is_legacy_hash_path(path):
    """True when `path` is a bare 64-char hex article id (the pre-slug form)."""
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(path).strip("/")))


def redirect_line(old_path, new_path, status=301):
    """One Cloudflare Pages `_redirects` entry. 301 keeps accumulated ranking signal."""
    return f"/{str(old_path).strip('/')}/ /{str(new_path).strip('/')}/ {status}"
