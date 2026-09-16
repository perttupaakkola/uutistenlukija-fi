"""Related-coverage search: extend a single-source packet into a multi-source one.

The pipeline discovers one official source and hardcodes it as source "A". The packet
validator, the writer prompt and the reviewer all already support 1-8 sources with
per-paragraph citations - the capability was designed in from the start and simply never
populated. This module populates it.

Design constraints, in priority order:

1. Every source in the packet must be a real, fetchable HTTPS page. The writer may only cite
   source IDs that exist in the packet, and a search snippet is not a page, so each hit is
   fetched and its own text extracted. No snippet is ever passed off as an excerpt.
2. Related sources are corroboration, never new claims. The originating official source stays
   "A"; related coverage is B..N. If a related page adds a fact, that fact is attributable to
   B, not silently merged into A's voice.
3. A search that fails, returns nothing useful, or returns off-topic pages must leave the
   packet exactly as it was (single source). Degrading to today's behaviour is always safe;
   inventing corroboration is not.
"""

import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .editorial import web_url

# Keep the prompt inside a sane budget: the writer gets 1-8 sources, so cap the related set.
MAX_RELATED = 3
MIN_RELATED_CHARS = 400
MAX_RELATED_CHARS = 6000
FETCH_TIMEOUT = 25
# Mirrors validate_packet's max_age_hours so a stale related pick is dropped here instead of
# failing the whole packet at validation time.
MAX_RELATED_AGE_HOURS = 48
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) UutistenlukijaBot/1.0"

# Domains that are never usable corroboration: social/aggregator noise, and the originating
# publisher itself (the same publisher counts as one source, per the writer contract).
BLOCKED_DOMAINS = (
    "facebook.com", "twitter.com", "x.com", "instagram.com", "tiktok.com",
    "youtube.com", "pinterest.com", "linkedin.com", "reddit.com",
    "wikipedia.org",  # not a news source; often mirrors the same press release
)

# Finnish stopwords for building a search query out of a headline.
_STOP = {
    "ja", "on", "ei", "se", "että", "kun", "joka", "oli", "ovat", "myös", "sekä", "tai",
    "mutta", "vain", "jo", "niin", "kuin", "sen", "tämä", "nämä", "hän", "he", "ne",
    "voi", "pitää", "tulee", "mukaan", "kanssa", "josta", "joka", "uusi", "uuden",
    "vuonna", "vuoden", "nyt", "aikaan", "aikana", "kertoo", "mukaan",
}


def _domain(url):
    from urllib.parse import urlsplit
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _registers(domain):
    """Strip a leading www. so kuopio.fi and www.kuopio.fi compare equal."""
    return domain[4:] if domain.startswith("www.") else domain


def build_query(title, limit_words=9):
    """Turn a headline into a keyword query. Headlines are not search strings."""
    if not isinstance(title, str) or not title.strip():
        return ""
    words = re.findall(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9-]+", title)
    kept = [w for w in words if w.lower() not in _STOP and len(w) > 2]
    return " ".join(kept[:limit_words])


def _fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
        final = response.geturl()
        if not final.startswith("https://"):
            raise ValueError("Related source redirected off HTTPS")
        ctype = (response.headers.get("Content-Type") or "").lower()
        if "html" not in ctype:
            raise ValueError("Related source is not HTML")
        raw = response.read(2_000_000)
    return raw, final


def extract_article_text(raw, page_url=None):
    """Pull the readable body out of a normal news page.

    Deliberately conservative: prefer <article>, then common content containers, and accept
    a container only if it yields substantive prose. A page we cannot read confidently is
    dropped rather than summarised from navigation chrome.
    """
    from .official import Page
    html = raw.decode("utf-8", errors="replace")

    def clean(value):
        value = (value or "").replace("\u00ad", "")
        value = re.sub(r"\s+", " ", value).strip()
        return value

    candidates = []
    for selector in (
        lambda t, a: t == "article",
        lambda t, a: "article-body" in a.get("class", "").split(),
        lambda t, a: "article__body" in a.get("class", "").split(),
        lambda t, a: "entry-content" in a.get("class", "").split(),
        lambda t, a: "field--body" in a.get("class", "").split(),
        lambda t, a: "journal-content-article" in a.get("class", "").split(),
        lambda t, a: t == "main",
    ):
        page = Page(selector)
        page.feed(html)
        value = clean(page.text())
        if len(value) >= MIN_RELATED_CHARS:
            candidates.append(value)

    if not candidates:
        return ""
    body = max(candidates, key=len)[:MAX_RELATED_CHARS]
    body = strip_navigation(body)
    return body if len(body) >= MIN_RELATED_CHARS else ""


def strip_navigation(body):
    """Remove site-menu/boilerplate runs that are not article prose.

    Ministry and municipal templates emit a long list of sibling organisations before the
    story ("Valtioneuvosto Valtioneuvoston kanslia Puolustusministeriö ..."). Passed through,
    the writer treats that as source text. Drop leading runs of short capitalised tokens that
    look like navigation rather than sentences.
    """
    # Soft hyphens (U+00AD) are invisible word-break hints some CMS templates embed inside
    # words ("viestintä\xadministteriö"). Left in, they corrupt both the prose and any
    # word-boundary logic below, so normalise them away first.
    body = body.replace("\u00ad", "")
    words = body.split()
    if not words:
        return body

    # Detect an organisational menu run directly. Ministry/municipal templates list sibling
    # bodies as bare capitalised names ("Valtioneuvosto Puolustusministeriö Ulkoministeriö
    # Valtiovarainministeriö ..."). Counting sentence stops does not work here because dates
    # like 16.9.2026 supply periods, so match the menu's own vocabulary instead.
    #
    # Compound names are split across tokens ("Työ-" + "ja" + "elinkeinoministeriö"), so a run
    # is any span where nearly every token is an organisation name, a conjunction, or a
    # hyphen fragment. Walk to the end of such a span and cut everything before it.
    org = re.compile(
        r"(ministeriö|ministeriön|kanslia|valtioneuvosto|virasto|keskus|liitto|yhdistys|"
        r"laitos|instituutti|neuvosto)$", re.I)
    fragment = re.compile(r"^[A-ZÄÖÅ][a-zäöå]+-$")

    def is_menu_token(word):
        stripped = word.strip(",.")
        return bool(org.search(stripped) or fragment.match(word) or word == "ja")

    best_end = 0
    start = None
    for i, word in enumerate(words[:80]):
        if is_menu_token(word):
            if start is None:
                start = i
            continue
        if start is not None:
            # A span of >= 5 consecutive menu tokens is a navigation block, not prose.
            if i - start >= 5 and i > best_end:
                best_end = i
            start = None
    # Only strip a leading menu: the first real prose word must come after it.
    if best_end:
        body = " ".join(words[best_end:]).strip()
    return body.strip()


def is_hub_page(url):
    """A section/index page aggregates many items; it is not corroboration for one story."""
    path = url.split("//", 1)[-1]
    path = path[path.find("/"):] if "/" in path else ""
    path = path.rstrip("/")
    if not path or path == "":
        return True
    # Article URLs carry a slug or an id; indexes are short collection paths.
    segments = [s for s in path.split("/") if s]
    if not segments:
        return True
    last = segments[-1]
    # A real article slug is long or id-like; "tiedotteet"/"uutiset" style ends are indexes.
    index_words = (
        "tiedotteet", "uutiset", "ajankohtaista", "news", "press", "press-releases",
        "articles", "blogi", "tapahtumat", "julkaisut", "index", "sitemap",
    )
    if last.lower() in index_words:
        return True
    if len(last) < 12 and not re.search(r"\d{4,}", last):
        return True
    return False


def _publisher(domain):
    """A readable publisher name from a host, for the packet's publisher field."""
    host = _registers(domain)
    base = host.split(":")[0]
    return base[:160] or "unknown"


def extract_published(raw):
    """Return the page's own publication time, or None.

    Never substitutes the current time: freshness must come from the page, or the candidate is
    dropped. Checks the standard machine-readable signals in order of reliability, and
    requires an explicit timezone, since a naive timestamp cannot be placed in the window.
    """
    from .official import Page

    html = raw.decode("utf-8", errors="replace")
    patterns = (
        r'<meta[^>]+property="article:published_time"[^>]+content="([^"]+)"',
        r'<meta[^>]+content="([^"]+)"[^>]+property="article:published_time"',
        r'<meta[^>]+name="date"[^>]+content="([^"]+)"',
        r'<meta[^>]+property="og:published_time"[^>]+content="([^"]+)"',
    )
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if not match:
            continue
        value = match.group(1).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            continue
        return parsed.isoformat()

    # Fall back to a <time datetime="..."> carrying an explicit offset.
    page = Page(lambda t, a: t == "time")
    page.feed(html)
    for value in sorted({v for v in page.times if "T" in v or "-" in v}):
        candidate = value.replace(" ", "T").replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            continue
        return parsed.isoformat()
    return None


def find_related(title, source_url, search, exclude_titles=(), max_results=MAX_RELATED):
    """Return related sources as packet entries B, C, D...

    `search` is a callable (query, limit) -> [{'url','title'}] so this stays testable and the
    caller controls which backend is used. Any failure yields [] - the caller then keeps the
    single-source packet, which is the current behaviour and always safe.
    """
    query = build_query(title)
    if not query:
        return []

    try:
        hits = search(query, max_results * 4) or []
    except Exception:
        return []

    origin = _registers(_domain(source_url))
    seen_urls = {source_url}
    seen_fingerprints = set()
    related = []

    for hit in hits:
        if len(related) >= max_results:
            break
        url = (hit or {}).get("url") or ""
        if not url:
            continue
        try:
            url = web_url(url)
        except ValueError:
            continue
        if url in seen_urls:
            continue
        domain = _registers(_domain(url))
        if not domain or domain == origin:
            continue
        if any(blocked in domain for blocked in BLOCKED_DOMAINS):
            continue
        # A section/index page aggregates many stories and is not corroboration for one.
        if is_hub_page(url):
            continue

        try:
            raw, final = _fetch(url)
        except (urllib.error.URLError, ValueError, OSError, TimeoutError):
            continue
        if final in seen_urls:
            continue
        body = extract_article_text(raw)
        if not body:
            continue
        # Guards against the same wire copy appearing on several domains.
        fingerprint = re.sub(r"[^a-z0-9äöå]", "", body[:600].lower())
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        seen_urls.add(final)

        hit_title = (hit.get("title") or "").strip() or domain
        if hit_title in exclude_titles:
            continue

        # The packet contract requires a publisher name and a real publication time within
        # the freshness window. A news page's own date is not reliably machine-readable across
        # arbitrary sites, and asserting "now" would fabricate freshness, so use the page date
        # when it is present and unambiguous and otherwise skip the candidate.
        published = extract_published(raw)
        if published is None:
            continue
        # Enforce the packet's own freshness window here rather than letting a stale source
        # reach validate_packet and fail the whole article. validate_packet allows at most
        # max_age_hours old; mirror that so a bad related pick degrades to a smaller packet
        # instead of losing the story.
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(published)).total_seconds()
        except ValueError:
            continue
        if age < -300 or age > MAX_RELATED_AGE_HOURS * 3600:
            continue

        related.append({
            "id": chr(ord("A") + len(related) + 1),
            "url": final,
            "publisher": _publisher(domain),
            "title": hit_title[:240],
            "published_at": published,
            "text": body,
            "related": True,
        })

    return related
