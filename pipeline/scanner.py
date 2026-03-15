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
    # Finnish sources
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
        "name": "MTV Uutiset",
        "url": "https://www.mtvuutiset.fi/api/feed/rss/uutiset",
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

    # Return top 20
    selected = unique[:20]
    print(f"[scanner] Total: {len(all_articles)} → Unique: {len(unique)} → Selected: {len(selected)}")
    return selected


if __name__ == "__main__":
    import json
    articles = scan_all_feeds()
    print(json.dumps(articles, indent=2, ensure_ascii=False))
