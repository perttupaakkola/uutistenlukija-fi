"""Search-engine metadata for rendered pages.

Measured baseline (2026-09-16): the live site earned 8,443 GSC impressions but only
148 clicks (~1.75% CTR). The published article carried a `<title>` and a canonical
link and nothing else — no meta description, no Open Graph, no structured data — so
Google had to invent every snippet. These helpers supply the metadata the SERP and
social previews actually consume.

Everything here is derived from the reviewed draft, never from raw source HTML.
"""

import html
import json
import re

SITE = "https://uutistenlukija.fi"
PUBLISHER = "Uutistenlukija"
DESCRIPTION_MAX = 158
TITLE_MAX = 60


def _plain(value):
    """Collapse whitespace; titles and summaries are already plain reviewed text."""
    return " ".join(str(value).split())


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÅ])")
_ORDINAL_DATE = re.compile(r"\b\d{1,2}\.$")


def meta_description(summary, paragraphs=(), limit=DESCRIPTION_MAX):
    """A bounded, sentence-aware description for the SERP snippet.

    Sentence splitting must not treat a Finnish ordinal date as a sentence end:
    "ensimmäinen vaihe alkaa 14. syyskuuta 2026" would otherwise truncate to
    "...alkaa 14.", which reads as a broken snippet in the SERP.
    """
    text = _plain(summary)
    if len(text) < 60 and paragraphs:
        text = _plain(f"{text} {' '.join(paragraphs)}").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # Candidate sentence boundaries inside the budget, ignoring ordinal dates.
    best = -1
    for match in _SENTENCE_END.finditer(cut):
        if _ORDINAL_DATE.search(cut[: match.start()].rstrip()):
            continue
        best = match.start()
    if best >= limit // 2:
        return cut[: best + 1].strip()
    index = cut.rfind(" ")
    return (cut[:index] if index >= limit // 2 else cut).rstrip() + "…"


def meta_title(title, limit=TITLE_MAX):
    """Title for og/twitter where the brand suffix is appended by the consumer."""
    text = _plain(title)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    index = cut.rfind(" ")
    return (cut[:index] if index > 0 else cut).rstrip() + "…"


def _tag(name, content, attribute="name"):
    if not content:
        return ""
    return f'<meta {attribute}="{html.escape(name, quote=True)}" content="{html.escape(content, quote=True)}">'


def article_head(title, description, canonical_path, image_url=None, published=None, modified=None):
    """Meta block for one public article page."""
    url = SITE + canonical_path
    parts = [
        _tag("description", description),
        _tag("robots", "index,follow,max-image-preview:large"),
        _tag("author", PUBLISHER),
        _tag("og:site_name", PUBLISHER, "property"),
        _tag("og:locale", "fi_FI", "property"),
        _tag("og:type", "article", "property"),
        _tag("og:title", title, "property"),
        _tag("og:description", description, "property"),
        _tag("og:url", url, "property"),
        _tag("twitter:card", "summary_large_image" if image_url else "summary"),
        _tag("twitter:title", title),
        _tag("twitter:description", description),
    ]
    if image_url:
        absolute = image_url if image_url.startswith("http") else SITE + image_url
        parts.append(_tag("og:image", absolute, "property"))
        parts.append(_tag("twitter:image", absolute))
    if published:
        parts.append(_tag("article:published_time", published, "property"))
    if modified:
        parts.append(_tag("article:modified_time", modified, "property"))
    return "".join(p for p in parts if p)


def news_article_jsonld(title, description, canonical_path, published, modified,
                        category=None, image_url=None, sources=()):
    """schema.org NewsArticle so Google can read the entity, not guess it."""
    url = SITE + canonical_path
    data = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "headline": meta_title(title, 110),
        "description": description,
        "inLanguage": "fi",
        "datePublished": published,
        "dateModified": modified or published,
        "url": url,
        "publisher": {
            "@type": "Organization",
            "name": PUBLISHER,
            "url": SITE,
        },
        "isAccessibleForFree": True,
    }
    if category:
        data["articleSection"] = category
    if image_url:
        data["image"] = [image_url if image_url.startswith("http") else SITE + image_url]
    if sources:
        data["citation"] = [
            {"@type": "CreativeWork", "name": s.get("title", ""), "url": s.get("url", "")}
            for s in sources if s.get("url")
        ]
    # json.dumps with ensure_ascii=False keeps Finnish characters readable while the
    # `<` escape prevents a source title from closing the script tag early.
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return f'<script type="application/ld+json">{payload}</script>'
