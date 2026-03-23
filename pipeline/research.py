"""
Research module — multi-source web research for article writing.

Pipeline: article headline → news search → fetch top sources → extract text → combine.

Multi-source approach:
1. Fetch the original RSS source URL
2. Search Bing News RSS for the same topic → discover additional articles
3. Extract body text from each source (with paywall/thin-content detection)
4. Combine all usable material into article["research"] for the rewriter

All failures are graceful — if search or any fetch fails, the article proceeds
with whatever material was collected (even if empty).

Uses only stdlib (no external dependencies).
"""

import html as html_module
import re
import time
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import List

# ── Configuration ──────────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fi-FI,fi;q=0.9,en;q=0.8",
}

FETCH_TIMEOUT = 12          # seconds per fetch
MAX_RESEARCH_CHARS = 6000   # total research text cap (increased for multi-source)
MAX_PER_SOURCE_CHARS = 2500 # cap per individual source
MIN_PARAGRAPH_LEN = 40      # ignore short nav/footer fragments
MAX_ADDITIONAL_SOURCES = 4   # extra sources beyond the original
SEARCH_TIMEOUT = 8          # seconds for news search
INTER_FETCH_DELAY = 0.8     # seconds between fetches (politeness)
MIN_USEFUL_WORDS = 80       # sources with less are discarded as paywall/thin

# Domains known to hard-paywall — always skip (never get useful text)
_BLOCKED_DOMAINS = {
    "hs.fi",                # Helsingin Sanomat
    "kauppalehti.fi",
    "tekniikkatalous.fi",
    "talouselama.fi",
    "tivi.fi",
    "aamulehti.fi",
    "ts.fi",                # Turun Sanomat
    "savonsanomat.fi",
    "ess.fi",
    "kaleva.fi",
    "keskisuomalainen.fi",
    "karjalainen.fi",
    "hameensanomat.fi",
    "lapin-kansa.fi",
    "is.fi",                # Next.js, content JS-rendered
    "iltalehti.fi",         # same
}

# Domains known to be high quality and open
_PREFERRED_DOMAINS = {
    "yle.fi",
    "mtvuutiset.fi",
    "mtv.fi",
    "helsinginuutiset.fi",
    "maaseuduntulevaisuus.fi",
    "verkkouutiset.fi",
    "suomenmaa.fi",
    "taloussanomat.fi",
    "bbc.com", "bbc.co.uk",
    "reuters.com",
    "theguardian.com",
    "arstechnica.com",
    "apnews.com",
    "techcrunch.com",
}

# Phrases that signal paywall/login walls (in extracted text)
_PAYWALL_SIGNALS = [
    "tilaa lehti", "tilaa nyt", "lue lisää tilaajana", "jatka lukemista",
    "kirjaudu sisään", "rekisteröidy lukemaan",
    "tämä sisältö on tilaajille",
    "artikkeli on maksumuurin takana",
    "subscribe to continue", "subscribe to read",
    "sign in to read", "sign in to continue",
    "this article is for subscribers",
    "already a subscriber",
    "log in to continue reading",
    "premium content", "become a subscriber",
]


# ── HTML Text Extraction ──────────────────────────────────────────────────────

class _ArticleExtractor(HTMLParser):
    """Extract visible text from article-like HTML elements."""

    _ARTICLE_P_CLASSES = {
        "yle__article__paragraph",
        "article__paragraph",
        "story__paragraph",
        "body__paragraph",
    }

    def __init__(self):
        super().__init__()
        self._in_article = 0
        self._in_article_div = 0
        self._in_p = False
        self._skip_tags = {"script", "style", "nav", "header", "footer",
                           "aside", "form", "button", "noscript", "svg"}
        self._skip_depth = 0
        self._hit_paywall = False
        self.article_paragraphs: list = []
        self.all_paragraphs: list = []
        self._buf: list = []

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        cls = attr_dict.get("class", "") or ""
        tag_id = attr_dict.get("id", "") or ""

        if tag in self._skip_tags:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        if tag == "article":
            self._in_article += 1
            return
        if tag in ("div", "section", "main"):
            combined = (cls + " " + tag_id).lower()
            if any(k in combined for k in (
                "paywall", "subscription-wall", "premium-wall",
                "register-wall", "login-wall", "metered-wall",
            )):
                self._hit_paywall = True
                return
            if any(k in combined for k in (
                "article-body", "article-content", "article-text",
                "story-body", "story-content", "entry-content",
                "post-content", "body-text", "main-content",
                "article__body", "article__content",
            )):
                self._in_article_div += 1
            return
        if tag == "p":
            if not self._hit_paywall:
                self._in_p = True
                self._buf = []
                cls_tokens = set(cls.lower().split())
                if cls_tokens & self._ARTICLE_P_CLASSES:
                    self._in_article_div += 1

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "article":
            self._in_article = max(0, self._in_article - 1)
            return
        if tag in ("div", "section", "main"):
            if self._in_article_div > 0:
                self._in_article_div -= 1
            return
        if tag == "p" and self._in_p:
            text = "".join(self._buf).strip()
            self._in_p = False
            self._buf = []
            if len(text) < MIN_PARAGRAPH_LEN:
                return
            text_lower = text.lower()
            if any(signal in text_lower for signal in _PAYWALL_SIGNALS):
                self._hit_paywall = True
                return
            self.all_paragraphs.append(text)
            if self._in_article > 0 or self._in_article_div > 0:
                self.article_paragraphs.append(text)

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_p:
            self._buf.append(data)

    def get_text(self) -> str:
        paragraphs = self.article_paragraphs or self.all_paragraphs
        return "\n\n".join(paragraphs)


def _extract_text(html: bytes) -> str:
    """Extract article body text from raw HTML bytes."""
    parser = _ArticleExtractor()
    try:
        parser.feed(html.decode("utf-8", errors="replace"))
    except Exception:
        return ""
    raw = parser.get_text()
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


# ── URL & Domain Utilities ─────────────────────────────────────────────────────

def _get_domain(url: str) -> str:
    """Extract base domain (strip www.)."""
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _is_blocked_domain(url: str) -> bool:
    host = _get_domain(url)
    return any(host == d or host.endswith("." + d) for d in _BLOCKED_DOMAINS)


def _is_same_article(url1: str, url2: str) -> bool:
    """Check if two URLs point to the same article (same domain + path)."""
    if not url1 or not url2:
        return False
    try:
        p1 = urllib.parse.urlparse(url1)
        p2 = urllib.parse.urlparse(url2)
        d1 = p1.netloc.lower().replace("www.", "")
        d2 = p2.netloc.lower().replace("www.", "")
        return d1 == d2 and p1.path.rstrip("/") == p2.path.rstrip("/")
    except Exception:
        return False


def _is_paywall_text(text: str) -> bool:
    """Detect if extracted text looks like a paywall snippet rather than an article."""
    lower = text.lower()
    signals_found = sum(1 for s in _PAYWALL_SIGNALS if s in lower)
    if signals_found >= 2:
        return True
    if len(text.split()) < 100 and signals_found >= 1:
        return True
    return False


# ── Fetching ───────────────────────────────────────────────────────────────────

def fetch_article_text(url: str, timeout: int = FETCH_TIMEOUT) -> str:
    """Fetch and extract article body text. Returns "" on any failure or paywall."""
    if not url or not url.startswith("http"):
        return ""
    if _is_blocked_domain(url):
        return ""

    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ct = resp.headers.get("Content-Type", "")
            if "html" not in ct.lower():
                return ""
            html = resp.read(500_000)
    except urllib.error.HTTPError:
        return ""
    except Exception:
        return ""

    text = _extract_text(html)

    if _is_paywall_text(text):
        return ""

    return text[:MAX_PER_SOURCE_CHARS]


# ── Bing News Search (returns real URLs, no API key needed) ───────────────────

def _search_bing_news(query: str, language: str = "fi", max_results: int = 10) -> List[dict]:
    """Search Bing News via RSS. Returns [{title, url, source}]."""
    results = []
    encoded = urllib.parse.quote_plus(query)
    mkt = "fi-FI" if language == "fi" else "en-US"
    rss_url = f"https://www.bing.com/news/search?q={encoded}&format=rss&mkt={mkt}"

    try:
        req = urllib.request.Request(rss_url, headers={
            "User-Agent": _HEADERS["User-Agent"],
            "Accept": "application/xml, text/xml, */*",
        })
        with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT) as resp:
            xml_data = resp.read(200_000)

        # Bing sometimes returns empty body when rate-limiting or on long queries.
        # Retry once with a shorter (first 6 words) version of the query.
        if not xml_data.strip():
            short_query = " ".join(query.split()[:6])
            if short_query != query:
                short_encoded = urllib.parse.quote_plus(short_query)
                retry_url = f"https://www.bing.com/news/search?q={short_encoded}&format=rss&mkt={mkt}"
                req2 = urllib.request.Request(retry_url, headers={
                    "User-Agent": _HEADERS["User-Agent"],
                    "Accept": "application/xml, text/xml, */*",
                })
                try:
                    with urllib.request.urlopen(req2, timeout=SEARCH_TIMEOUT) as resp2:
                        xml_data = resp2.read(200_000)
                except Exception:
                    pass  # fall through to empty parse
            if not xml_data.strip():
                print(f"[research]   Bing returned empty response (rate limited?)")
                return results

        root = ET.fromstring(xml_data)
        for item in root.findall(".//item"):
            if len(results) >= max_results:
                break

            title_el = item.find("title")
            link_el = item.find("link")

            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            raw_link = link_el.text.strip() if link_el is not None and link_el.text else ""

            # Extract actual URL from Bing redirect wrapper
            url_match = re.search(r"url=([^&]+)", raw_link)
            if url_match:
                actual_url = urllib.parse.unquote(url_match.group(1))
            else:
                actual_url = raw_link

            if not actual_url or not actual_url.startswith("http"):
                continue

            source_name = _get_domain(actual_url)
            for child in item:
                if "Source" in child.tag and child.text:
                    source_name = child.text

            results.append({
                "title": title,
                "url": actual_url,
                "source": source_name,
            })

    except Exception as e:
        print(f"[research]   Bing News search failed: {e}")

    return results


def _search_google_news(query: str, language: str = "fi", max_results: int = 8) -> List[dict]:
    """Search Google News via RSS. Returns [{title, source, source_domain}].
    
    Note: Google News RSS returns unresolvable redirect URLs, so we only
    use this for discovering source names / titles for fallback Bing searches.
    """
    results = []
    encoded = urllib.parse.quote_plus(query)

    if language == "fi":
        rss_url = f"https://news.google.com/rss/search?q={encoded}&hl=fi&gl=FI&ceid=FI:fi"
    else:
        rss_url = f"https://news.google.com/rss/search?q={encoded}&hl=en&gl=US&ceid=US:en"

    try:
        req = urllib.request.Request(rss_url, headers={
            "User-Agent": _HEADERS["User-Agent"],
            "Accept": "application/xml, text/xml, application/rss+xml",
        })
        with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT) as resp:
            xml_data = resp.read(200_000)

        root = ET.fromstring(xml_data)
        channel = root.find("channel")
        if channel is None:
            return results

        for item in channel.findall("item"):
            if len(results) >= max_results:
                break

            title_el = item.find("title")
            source_el = item.find("source")

            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            source_name = source_el.text.strip() if source_el is not None and source_el.text else ""

            if not title:
                continue

            results.append({
                "title": title,
                "url": "",
                "source": source_name,
            })

    except Exception as e:
        print(f"[research]   Google News search failed: {e}")

    return results


# ── Search Orchestration ──────────────────────────────────────────────────────

def _build_search_query(title: str, description: str = "") -> str:
    """Build a search query from article title."""
    query = title.strip()
    query = re.sub(r'["\[\](){}]', '', query)

    words = query.split()
    if len(words) < 4 and description:
        desc_words = re.sub(r'["\[\](){}]', '', description).split()[:6]
        query = query + " " + " ".join(desc_words)

    words = query.split()
    if len(words) > 12:
        words = words[:12]
    return " ".join(words)


def _search_news(query: str, language: str = "fi") -> List[dict]:
    """Search multiple news sources and merge results.
    
    Primary: Bing News RSS (returns real URLs)
    Fallback: Google News RSS titles → re-search via Bing
    """
    bing_results = _search_bing_news(query, language=language)

    if not bing_results:
        google_results = _search_google_news(query, language=language)
        if google_results:
            for gr in google_results[:3]:
                fallback = _search_bing_news(gr["title"][:60], language=language, max_results=2)
                bing_results.extend(fallback)

    return bing_results


def _rank_and_filter(results: List[dict], original_url: str) -> List[dict]:
    """Rank search results for quality/diversity. Skip duplicates, paywalls, same-origin."""
    original_domain = _get_domain(original_url)
    seen_domains = {original_domain} if original_domain else set()
    ranked = []

    for result in results:
        url = result.get("url", "")
        if not url:
            continue
        if _is_same_article(url, original_url):
            continue
        if _is_blocked_domain(url):
            continue

        domain = _get_domain(url)
        if domain in seen_domains:
            continue

        score = 10 if any(domain == d or domain.endswith("." + d) for d in _PREFERRED_DOMAINS) else 5
        ranked.append((score, result))
        seen_domains.add(domain)

    ranked.sort(key=lambda x: -x[0])
    return [r for _, r in ranked]


# ── Main Research Function ─────────────────────────────────────────────────────

def _research_article(article: dict) -> str:
    """Perform multi-source research for a single article.
    
    1. Fetch original source URL
    2. Search Bing/Google News for the topic
    3. Fetch top additional sources (skip paywalls, thin content)
    4. Combine all text with source labels
    
    Returns combined research text, or "" if nothing useful found.
    """
    title = article.get("title", "")
    description = article.get("description", "")
    original_url = article.get("link", "")
    language = article.get("language", "fi")

    sources_collected = []  # [(label, text)]

    # ── 1. Fetch original source ──────────────────────────────────────────
    if original_url:
        original_text = fetch_article_text(original_url)
        if original_text and len(original_text.split()) >= MIN_USEFUL_WORDS:
            label = article.get("source", _get_domain(original_url) or "Alkuperäinen lähde")
            sources_collected.append((label, original_text))
            print(f"[research]   Original: {len(original_text.split())}w from {_get_domain(original_url)}")
        elif original_text:
            print(f"[research]   Original: only {len(original_text.split())}w (too thin, discarded)")
        else:
            print(f"[research]   Original: empty/blocked")

    # ── 2. Search for additional sources ──────────────────────────────────
    query = _build_search_query(title, description)
    print(f"[research]   Searching: \"{query[:60]}\"")

    search_results = _search_news(query, language=language)
    print(f"[research]   Found {len(search_results)} search results")

    if language != "fi" and len(search_results) < 3:
        en_results = _search_news(query, language="en")
        search_results.extend(en_results)

    ranked = _rank_and_filter(search_results, original_url)

    # ── 3. Fetch additional sources ───────────────────────────────────────
    fetched = 0
    for result in ranked:
        if fetched >= MAX_ADDITIONAL_SOURCES:
            break

        url = result.get("url", "")
        source_name = result.get("source", _get_domain(url))
        domain = _get_domain(url)

        time.sleep(INTER_FETCH_DELAY)

        text = fetch_article_text(url)
        word_count = len(text.split()) if text else 0

        if text and word_count >= MIN_USEFUL_WORDS:
            sources_collected.append((source_name, text))
            fetched += 1
            print(f"[research]   + {domain}: {word_count}w ✓")
        elif text:
            print(f"[research]   - {domain}: {word_count}w (too thin, skipped)")
        else:
            print(f"[research]   - {domain}: empty/blocked")

    # ── 4. Combine ────────────────────────────────────────────────────────
    if not sources_collected:
        return ""

    parts = []
    total_chars = 0

    for label, text in sources_collected:
        if total_chars + len(text) > MAX_RESEARCH_CHARS:
            remaining = MAX_RESEARCH_CHARS - total_chars
            if remaining < 200:
                break
            text = text[:remaining] + "..."

        parts.append(f"[Lähde: {label}]\n{text}")
        total_chars += len(text)

    return "\n\n---\n\n".join(parts)


# ── Pipeline Entry Point ──────────────────────────────────────────────────────

def enrich_with_research(articles: list) -> list:
    """Multi-source research enrichment for article list.
    
    For each article:
    1. Fetches the original source URL
    2. Searches Bing + Google News for the same topic
    3. Fetches up to 4 additional sources (skipping paywalls/thin content)
    4. Combines all text into article["research"]
    
    Articles where all fetches fail get research="" with RSS description fallback.
    Pipeline never blocks on research failures.
    """
    total = len(articles)
    enriched = 0
    skipped = 0

    RSS_MIN_WORDS = 30

    for i, article in enumerate(articles):
        title = article.get("title", "?")[:60]
        print(f"\n[research] ({i+1}/{total}) {title}", flush=True)

        try:
            research_text = _research_article(article)

            if research_text:
                word_count = len(research_text.split())
                source_count = research_text.count("[Lähde:")
                print(f"[research]   → {word_count} words from {source_count} source(s)")
                article["research"] = research_text
                article["research_source"] = "multi"
                enriched += 1
            else:
                # Fallback: use RSS description
                rss_raw = article.get("description", "").strip()
                rss_text = re.sub(r"<[^>]+>", " ", html_module.unescape(rss_raw)).strip()
                rss_text = re.sub(r"\s{2,}", " ", rss_text)
                rss_words = len(rss_text.split())

                if rss_words >= RSS_MIN_WORDS:
                    print(f"[research]   → RSS fallback: {rss_words}w")
                    article["research"] = rss_text
                    article["research_source"] = "rss"
                else:
                    print(f"[research]   → No usable sources")
                    article["research"] = rss_text
                    article["research_source"] = "none"
                skipped += 1

        except Exception as e:
            print(f"[research]   → Failed: {e}")
            article["research"] = ""
            article["research_source"] = "error"
            skipped += 1

        if i < total - 1:
            time.sleep(0.3)

    print(f"\n[research] Done: {enriched}/{total} multi-source, {skipped} fallback/empty")
    return articles
