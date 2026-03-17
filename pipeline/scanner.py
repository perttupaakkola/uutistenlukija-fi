"""
RSS Scanner — fetches and deduplicates Finnish news from public RSS feeds.
Uses only stdlib (no feedparser dependency).
"""

import hashlib
import re
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import List, Dict, Optional
from email.utils import parsedate_to_datetime

RSS_FEEDS = [
    # Finnish main sources
    {
        "name": "Yle Uutiset",
        "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET",
        "language": "fi",
    },
    {
        "name": "Iltalehti",
        "url": "https://www.iltalehti.fi/rss/uutiset.xml",
        "language": "fi",
    },
    {
        "name": "Kauppalehti",
        "url": "https://feeds.kauppalehti.fi/rss/main",
        "language": "fi",
    },
    {
        "name": "Taloussanomat",
        "url": "https://www.is.fi/rss/taloussanomat.xml",
        "language": "fi",
    },
    # Finnish specialized
    {
        "name": "Yle Urheilu",
        "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_URHEILU",
        "language": "fi",
        "category_hint": "Urheilu",
    },
    {
        "name": "IS Urheilu",
        "url": "https://www.is.fi/rss/urheilu.xml",
        "language": "fi",
        "category_hint": "Urheilu",
    },
    {
        "name": "Tekniikka & Talous",
        "url": "https://www.tekniikkatalous.fi/feed",
        "language": "fi",
        "category_hint": "Teknologia",
    },
    # International sources
    {
        "name": "Reuters World",
        "url": "https://www.reutersagency.com/feed/?best-topics=world&post_type=best",
        "language": "en",
    },
    {
        "name": "BBC World",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "language": "en",
    },
    {
        "name": "BBC Technology",
        "url": "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "language": "en",
    },
    {
        "name": "BBC Science",
        "url": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        "language": "en",
    },
    {
        "name": "AP News",
        "url": "https://rsshub.app/apnews/topics/world-news",
        "language": "en",
    },
    {
        "name": "The Guardian World",
        "url": "https://www.theguardian.com/world/rss",
        "language": "en",
    },
    {
        "name": "TechCrunch",
        "url": "https://techcrunch.com/feed/",
        "language": "en",
    },
    {
        "name": "Ars Technica",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "language": "en",
    },
    {
        "name": "Hacker News Best",
        "url": "https://hnrss.org/best",
        "language": "en",
    },
    {
        "name": "Der Spiegel International",
        "url": "https://www.spiegel.de/international/index.rss",
        "language": "en",
    },
]

HEADERS = {
    "User-Agent": "Uutistenlukija/1.0 (news aggregator; +https://uutistenlukija.fi)"
}


def _clean_html(text: str) -> str:
    """Strip HTML tags from text."""
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_rss_date(date_str: str) -> Optional[datetime]:
    """Parse RSS date string."""
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    # Try ISO format
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        pass
    return None


def _fingerprint(title: str) -> str:
    """Create a simple fingerprint for dedup."""
    normalized = re.sub(r"[^a-zäöå0-9 ]", "", title.lower().strip())
    words = sorted(set(normalized.split()))
    return hashlib.md5(" ".join(words).encode()).hexdigest()


def _get_text(element, tag: str) -> str:
    """Safely get text from an XML element."""
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def fetch_feed(feed_info: dict) -> List[Dict]:
    """Fetch and parse a single RSS feed."""
    articles = []
    try:
        req = urllib.request.Request(feed_info["url"], headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read()
        
        root = ET.fromstring(content)
        
        # Handle both RSS 2.0 and Atom feeds
        items = root.findall(".//item")
        if not items:
            # Try Atom format
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//atom:entry", ns)
        
        for item in items[:30]:
            title = _clean_html(_get_text(item, "title"))
            if not title:
                continue
            
            description = _clean_html(
                _get_text(item, "description") or _get_text(item, "summary")
            )
            
            link = _get_text(item, "link")
            if not link:
                link_el = item.find("link")
                if link_el is not None:
                    link = link_el.get("href", "")
            
            date_str = (
                _get_text(item, "pubDate") or 
                _get_text(item, "published") or
                _get_text(item, "updated")
            )
            pub_date = _parse_rss_date(date_str) or datetime.now(timezone.utc)
            
            articles.append({
                "title": title,
                "description": description[:500],
                "link": link,
                "published": pub_date.isoformat(),
                "source": feed_info["name"],
                "language": feed_info.get("language", "fi"),
                "category_hint": feed_info.get("category_hint"),
                "fingerprint": _fingerprint(title),
            })
    except Exception as e:
        print(f"[scanner] Error fetching {feed_info['name']}: {e}")

    return articles


def scan_all_feeds() -> List[Dict]:
    """Scan all configured RSS feeds, deduplicate, return top articles."""
    all_articles = []
    for feed in RSS_FEEDS:
        print(f"[scanner] Fetching {feed['name']}...")
        articles = fetch_feed(feed)
        print(f"[scanner]   → {len(articles)} articles")
        all_articles.extend(articles)

    # Deduplicate by fingerprint
    seen = set()
    unique = []
    for article in all_articles:
        fp = article["fingerprint"]
        if fp not in seen:
            seen.add(fp)
            unique.append(article)

    # Detect trending: articles with similar fingerprints from multiple sources
    fp_sources = {}
    for article in all_articles:
        fp = article["fingerprint"]
        source = article["source"]
        if fp not in fp_sources:
            fp_sources[fp] = set()
        fp_sources[fp].add(source)

    # Mark articles as trending if covered by 2+ sources
    trending_fps = {fp for fp, sources in fp_sources.items() if len(sources) >= 2}
    for article in unique:
        article["trending"] = article["fingerprint"] in trending_fps

    trending_count = sum(1 for a in unique if a.get("trending"))
    print(f"[scanner] Trending stories: {trending_count}")

    # Sort by date (newest first)
    unique.sort(key=lambda a: a["published"], reverse=True)

    # Category-aware selection: ensure all 7 categories get representation
    CATEGORIES = ["Kotimaa", "Ulkomaat", "Talous", "Teknologia", "Urheilu", "Kulttuuri", "Tiede"]
    CATEGORY_PATTERNS = {
        "Urheilu": [
            r"\burheilu\b", r"\bsport\b", r"\bliiga\b", r"\bolymp", r"\bjalkapallo\b",
            r"\bjääkiekko\b", r"\bnhl\b", r"\bf1\b", r"\bformula\b", r"\btennis\b",
            r"\bgolf\b", r"\bkoripallo\b", r"\bsalibandy\b", r"\bhiihto\b",
        ],
        "Tiede": [
            r"\btiede\w*", r"\btutkimus\w*", r"\bscience\b", r"\bresearch\b",
            r"\bilmasto\w*", r"\bavaruus\w*", r"\bterveys\w*", r"\bhealth\b",
            r"\blääketied", r"\byliopisto\w*", r"\btutkija\w*",
        ],
        "Kulttuuri": [
            r"\bkulttuuri\w*", r"\btaide\w*", r"\bmusiik\w*", r"\belokuva\w*",
            r"\bteatteri\w*", r"\bkirja\w*", r"\bculture\b", r"\bart\b", r"\bmusic\b",
            r"\bartisti\w*", r"\bkonsertti\w*",
        ],
        "Teknologia": [
            r"\bteknologia\w*", r"\btech\b", r"\btekoäly\b", r"\bai\b", r"\bohjelmisto\w*",
            r"\bcyber\b", r"\bdigital\w*", r"\bapple\b", r"\bgoogle\b", r"\bmicrosoft\b",
            r"\bnvidia\b", r"\bopenai\b", r"\bstartup\b", r"\bsiru\w*", r"\bpuhelin\w*",
            r"\bsovellus\w*", r"\balgoritmi\w*",
        ],
        "Talous": [
            r"\btalous\w*", r"\bekonom\w*", r"\bosake\w*", r"\bpörssi\w*", r"\bbusiness\b",
            r"\beconomy\b", r"\bmarket\w*", r"\bfinance\b", r"\bkauppa\w*", r"\binflaatio\w*",
            r"\bkorko\w*", r"\btyöllisyys\w*", r"\byritys\w*",
        ],
        "Ulkomaat": [
            r"\bulkomaa\w*", r"\bworld\b", r"\binternational\b", r"\busa\b", r"\beurooppa\w*",
            r"\bkiina\w*", r"\bvenäjä\w*", r"\bnato\b", r"\bukraina\w*", r"\bgaza\w*",
            r"\blähi-itä\b", r"\btrump\b", r"\bxi\b",
        ],
        "Kotimaa": [
            r"\bsuomi\b", r"\bhelsinki\w*", r"\btampere\w*", r"\bturku\w*", r"\beduskunta\w*",
            r"\bhallitus\w*", r"\bpoliisi\w*", r"\bkäräjäoikeus\w*", r"\bhyvinvointialue\w*",
            r"\bpäiväkoti\w*", r"\bkoulu\w*", r"\bkunnan\b",
        ],
    }
    SOURCE_CATEGORY_HINTS = {
        "Yle Urheilu": "Urheilu",
        "IS Urheilu": "Urheilu",
        "Tekniikka & Talous": "Teknologia",
        "BBC Technology": "Teknologia",
        "TechCrunch": "Teknologia",
        "Ars Technica": "Teknologia",
        "Hacker News Best": "Teknologia",
        "BBC Science": "Tiede",
        "Reuters World": "Ulkomaat",
        "BBC World": "Ulkomaat",
        "AP News": "Ulkomaat",
        "The Guardian World": "Ulkomaat",
        "Der Spiegel International": "Ulkomaat",
        "Kauppalehti": "Talous",
        "Taloussanomat": "Talous",
    }

    def _score_category(text: str, category: str) -> int:
        score = 0
        for pattern in CATEGORY_PATTERNS.get(category, []):
            if re.search(pattern, text):
                score += 1
        return score

    def _guess_category(article):
        """Guess category from source hint, source defaults, and boundary-aware keyword scoring."""
        hint = article.get("category_hint", "")
        if hint in CATEGORIES:
            return hint

        source = article.get("source", "")
        source_default = SOURCE_CATEGORY_HINTS.get(source)
        text = (article.get("title", "") + " " + article.get("description", "")).lower()
        scores = {cat: _score_category(text, cat) for cat in CATEGORIES}

        if source_default:
            scores[source_default] += 3

        if article.get("language") == "en" and not source_default:
            scores["Ulkomaat"] += 2

        best_category = max(scores, key=scores.get)
        if scores[best_category] > 0:
            return best_category

        if article.get("language") == "en":
            return "Ulkomaat"
        return source_default or "Kotimaa"

    # First pass: pick at least 1 article per category
    selected = []
    selected_fps = set()
    for cat in CATEGORIES:
        for article in unique:
            if article["fingerprint"] not in selected_fps and _guess_category(article) == cat:
                article["_guessed_category"] = cat
                selected.append(article)
                selected_fps.add(article["fingerprint"])
                break

    # Second pass: fill remaining slots with newest articles, balanced by category
    # Track how many we've selected per category
    cat_counts = {c: sum(1 for a in selected if a.get("_guessed_category") == c) for c in CATEGORIES}
    target = 25
    
    for article in unique:
        if len(selected) >= target:
            break
        if article["fingerprint"] not in selected_fps:
            cat = _guess_category(article)
            # Prefer underrepresented categories
            article["_guessed_category"] = cat
            selected.append(article)
            selected_fps.add(article["fingerprint"])
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

    print(f"[scanner] Category distribution: {cat_counts}")
    print(f"[scanner] Total: {len(all_articles)} → Unique: {len(unique)} → Selected: {len(selected)}")
    return selected


if __name__ == "__main__":
    import json
    articles = scan_all_feeds()
    print(json.dumps(articles, indent=2, ensure_ascii=False))
