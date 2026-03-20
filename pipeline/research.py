"""
Research module — fetches and extracts full article text from source URLs.

Enriches article dicts with article["research"] containing the extracted
body text. Used between dedup and rewrite steps to give the rewriter
actual source material instead of just an RSS title + 1-sentence description.

Failure modes are all handled gracefully: paywall, 403, timeout, parse error
— article just proceeds with empty research, pipeline never blocks.
"""

import re
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser
from typing import Optional
import urllib.parse

# Browser-like UA to reduce 403s from news sites
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fi-FI,fi;q=0.9,en;q=0.8",
}

FETCH_TIMEOUT = 10  # seconds
MAX_RESEARCH_CHARS = 3000  # cap to stay within rewriter context window
MIN_PARAGRAPH_LEN = 40  # ignore short nav/footer fragments


# Domains known to 403/paywall — skip immediately, don't waste time
_BLOCKED_DOMAINS = {
    "hs.fi",
    "kauppalehti.fi",
    "tekniikkatalous.fi",
    "talouselama.fi",
    "tivi.fi",
}


class _ArticleExtractor(HTMLParser):
    """
    Minimal HTML parser that extracts visible text from article-like elements.

    Priority order:
    1. <article> tag content
    2. <div class="...article-body|article-content|story-body..."> pattern
    3. Fallback: all <p> tags with meaningful content

    Paywall handling: most Finnish news sites show 2-4 paragraphs before the
    subscription wall. We capture all paragraphs we can see — even 80 words
    from the lead is better than zero for the rewriter.
    """

    # Paywall signal phrases — when we see these in a paragraph, stop collecting
    # (the paragraphs after are usually "subscribe to read more" UI text, not news)
    _PAYWALL_SIGNALS = [
        "tilaa lehti", "tilaa nyt", "lue lisää tilaajana", "jatka lukemista",
        "artikkeli jatkuu", "kirjaudu sisään", "rekisteröidy lukemaan",
        "subscribe to read", "sign in to read", "this article is for subscribers",
        "premium content", "become a subscriber",
    ]

    def __init__(self):
        super().__init__()
        self._in_article = 0
        self._in_article_div = 0
        self._in_p = False
        self._skip_tags = {"script", "style", "nav", "header", "footer",
                           "aside", "form", "button", "noscript", "svg"}
        self._skip_depth = 0
        self._hit_paywall = False
        self.article_paragraphs: list[str] = []
        self.all_paragraphs: list[str] = []
        self._buf = []

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
            # Paywall container: stop collecting once we enter these
            if any(k in combined for k in (
                "paywall", "subscription-wall", "premium-wall",
                "register-wall", "login-wall", "metered-wall",
            )):
                self._hit_paywall = True
                return
            # Article body containers
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
            # Check for paywall signal in paragraph text
            text_lower = text.lower()
            if any(signal in text_lower for signal in self._PAYWALL_SIGNALS):
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
    # Collapse excessive whitespace
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def _is_blocked_domain(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
        return any(host == d or host.endswith("." + d) for d in _BLOCKED_DOMAINS)
    except Exception:
        return False


def fetch_article_text(url: str) -> str:
    """
    Fetch and extract article body text from URL.
    Returns empty string on any failure (paywall, 403, timeout, parse error).
    """
    if not url or not url.startswith("http"):
        return ""

    if _is_blocked_domain(url):
        return ""  # known paywall, skip silently

    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            # Only process HTML responses
            ct = resp.headers.get("Content-Type", "")
            if "html" not in ct.lower():
                return ""
            html = resp.read(500_000)  # cap at 500KB, don't download infinite pages
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404, 410, 451):
            return ""  # paywall/gone — expected, silent
        return ""
    except Exception:
        return ""  # timeout, DNS failure, etc — silent

    text = _extract_text(html)
    return text[:MAX_RESEARCH_CHARS]


def enrich_with_research(articles: list) -> list:
    """
    Fetch source text for each article and store in article["research"].

    Fallback chain per article:
    1. Web fetch of article URL → extract visible paragraphs (paywall-aware)
    2. RSS content:encoded (already in article["description"] if longer than plain desc)
    3. RSS description (plain text summary)

    article["research"] is always set (may be empty string if all fail).
    article["research_source"] records which chain step succeeded: "web", "rss", "none".

    Includes a small inter-fetch delay to be polite.
    """
    total = len(articles)
    web_ok = 0
    rss_fallback = 0
    empty = 0

    # Minimum words to consider RSS description useful as research material
    RSS_MIN_WORDS = 30

    for i, article in enumerate(articles):
        url = article.get("link", "")
        source_name = article.get("source", "?")
        print(f"[research] ({i+1}/{total}) {source_name} — ", end="", flush=True)

        # Step 1: web fetch
        text = fetch_article_text(url)

        if text:
            word_count = len(text.split())
            print(f"web: {word_count}w")
            article["research"] = text
            article["research_source"] = "web"
            web_ok += 1
        else:
            # Step 2: fall back to RSS description (may be content:encoded if longer)
            rss_text = article.get("description", "").strip()
            rss_words = len(rss_text.split())
            if rss_words >= RSS_MIN_WORDS:
                print(f"rss-fallback: {rss_words}w")
                article["research"] = rss_text
                article["research_source"] = "rss"
                rss_fallback += 1
            else:
                print(f"empty (rss only {rss_words}w)")
                article["research"] = rss_text  # keep even if short — better than nothing
                article["research_source"] = "none" if rss_words == 0 else "rss-short"
                empty += 1

        # Politeness: small delay between fetches (different domains)
        if i < total - 1:
            time.sleep(0.5)

    print(f"[research] Done: {web_ok} web, {rss_fallback} rss-fallback, {empty} thin/empty (of {total} total)")
    return articles
