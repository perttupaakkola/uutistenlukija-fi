"""
Firehose Poller — supplementary article discovery via Firehose SSE stream.

Runs alongside RSS scanner. Every 10 minutes, fetches articles from the past 20
minutes via Server-Sent Events. Dedups by normalized URL hash before feeding into
the rewriter pipeline.

Rules active in Firehose (5 rules, synced 2026-03-19):
  - fi-news-clean:      language:fi AND page_category:"/News" AND recent:24h (excl. games/reviews/tutorials/FAQ)
  - fi-trusted-domains: Finnish news domains + language:fi + /Article + recent:24h
  - tiede:              language:fi AND page_category:"/Science" AND recent:48h
  - talous-fallback:    kauppalehti/hs/is/yle domains + language:fi + recent:24h
  - urheilu-fallback:   yle/is/iltalehti/mtv domains + language:fi + recent:24h

Field note: response payload uses page_category[] (singular, array) and page_types[] (plural, array).

Usage:
  python3 firehose.py              # Poll once, print results
  python3 firehose.py --rules      # Print current rules from API
  python3 firehose.py --register   # Register/sync rules to API
  python3 firehose.py --delete-all # Delete all rules from API (use with care)
"""

import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import List, Dict, Optional
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

FIREHOSE_BASE = "https://api.firehose.com/v1"
FIREHOSE_TOKEN = os.environ.get("FIREHOSE_TOKEN", "").strip()

# Rules to register with Firehose (idempotent — tag is unique key)
# Synced with live API state 2026-03-19. quality:true on all rules.
FIREHOSE_RULES = [
    {
        "tag": "fi-news-clean",
        "value": (
            'language:fi AND page_category:"/News" AND recent:24h'
            ' AND NOT page_category:"/Games"'
            ' AND NOT page_type:"/Article/Product_or_Brand_Review"'
            ' AND NOT page_type:"/Article/Tutorial_or_Guide"'
            ' AND NOT page_type:"/Article/FAQ"'
            # Exclude known low-quality / non-news domains (2026-03-26)
            ' AND NOT domain:scoop.it'
            ' AND NOT domain:7sun.fi'
            ' AND NOT domain:listamaailma.fi'
            ' AND NOT domain:listafriikki.com'
            ' AND NOT domain:uutiskaista.com'
            ' AND NOT domain:bandilanews.com'
            ' AND NOT domain:itbranschen.com'
            ' AND NOT domain:etappi.com'
            ' AND NOT domain:destia.fi'
        ),
        "quality": True,
    },
    {
        "tag": "fi-trusted-domains",
        "value": (
            "(domain:yle.fi OR domain:hs.fi OR domain:is.fi OR domain:iltalehti.fi"
            " OR domain:mtv.fi OR domain:kauppalehti.fi OR domain:verkkouutiset.fi)"
            ' AND language:fi AND page_type:"/Article" AND recent:24h'
            ' AND NOT page_type:"/Article/Product_or_Brand_Review"'
            ' AND NOT page_type:"/Article/FAQ"'
        ),
        "quality": True,
    },
    {
        "tag": "tiede",
        "value": (
            'language:fi AND page_category:"/Science" AND recent:48h'
            ' AND NOT page_type:"/Article/Product_or_Brand_Review"'
            ' AND NOT page_type:"/Article/FAQ"'
        ),
        "quality": True,
    },
    {
        "tag": "talous-fallback",
        "value": (
            "(domain:kauppalehti.fi OR domain:hs.fi OR domain:is.fi OR domain:yle.fi)"
            ' AND language:fi AND page_type:"/Article" AND recent:24h'
            ' AND NOT page_type:"/Article/Product_or_Brand_Review"'
            ' AND NOT page_type:"/Article/FAQ"'
        ),
        "quality": True,
    },
    {
        "tag": "urheilu-fallback",
        "value": (
            "(domain:yle.fi OR domain:is.fi OR domain:iltalehti.fi OR domain:mtv.fi)"
            ' AND language:fi AND page_type:"/Article" AND recent:24h'
            ' AND NOT page_type:"/Article/Product_or_Brand_Review"'
            ' AND NOT page_type:"/Article/FAQ"'
        ),
        "quality": True,
    },
]

# State file: stores Last-Event-ID for exact-offset resume
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
_STATE_FILE = os.path.join(_CACHE_DIR, "firehose_state.json")

# URL params to strip (tracking noise)
_STRIP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source",
}

# Category hint mapping from Firehose page_category → pipeline category
_CATEGORY_MAP = {
    "/Science": "Tiede",
    "/Finance": "Talous",
    "/Business": "Talous",
    "/Sports": "Urheilu",
    "/Computers_and_Electronics": "Teknologia",
    "/Technology": "Teknologia",
    "/News": None,  # Resolved by pipeline
    "/Article": None,
}

_TAG_CATEGORY_MAP = {
    # New tag names (2026-03-19 API sync)
    "tiede": "Tiede",
    "talous-fallback": "Talous",
    "urheilu-fallback": "Urheilu",
    "teknologia": "Teknologia",
    # Legacy tag names (kept for backward compat with old state files)
    "finnish-tiede": "Tiede",
    "finnish-talous": "Talous",
    "finnish-urheilu": "Urheilu",
    "finnish-teknologia": "Teknologia",
}

BASE_HEADERS = {
    "User-Agent": "Uutistenlukija/1.0 (+https://uutistenlukija.fi)",
    "Accept": "text/event-stream",
}

FIREHOSE_STREAM_WAIT_SEC = int(os.environ.get("FIREHOSE_STREAM_WAIT_SEC", "5"))
FIREHOSE_HTTP_TIMEOUT_SEC = int(os.environ.get("FIREHOSE_HTTP_TIMEOUT_SEC", "12"))


def _redact_firehose_token(value: object) -> str:
    """Render an error without exposing the configured Firehose credential."""
    text = str(value)
    if FIREHOSE_TOKEN:
        text = text.replace(FIREHOSE_TOKEN, "[REDACTED]")
    return text


# ─── URL normalization & dedup ────────────────────────────────────────────────

def _normalize_url(url: str) -> str:
    """Strip tracking params, normalize case, drop trailing slash."""
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        # Filter query params
        query_pairs = []
        for k, vs in parse_qs(parsed.query, keep_blank_values=True).items():
            if k not in _STRIP_PARAMS:
                for v in vs:
                    query_pairs.append(f"{k}={v}")
        query = "&".join(sorted(query_pairs))
        return urlunparse((parsed.scheme, host, path, parsed.params, query, ""))
    except Exception:
        return url.lower().strip()


def _url_hash(url: str) -> str:
    return hashlib.sha256(_normalize_url(url).encode()).hexdigest()


def _title_hash(title: str) -> str:
    normalized = re.sub(r"[^a-zäöå0-9 ]", "", title.lower().strip())
    return hashlib.sha256(normalized.encode()).hexdigest()


# ─── State persistence ────────────────────────────────────────────────────────

def _load_state() -> Dict:
    try:
        with open(_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: Dict) -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ─── SSE parsing ─────────────────────────────────────────────────────────────

def _parse_sse_events(raw: bytes) -> List[Dict]:
    """Parse SSE text/event-stream into list of {event, data, id} dicts."""
    events = []
    current: Dict = {}
    data_lines = []

    text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
        if line.startswith("event:"):
            current["event"] = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
        elif line.startswith("id:"):
            current["id"] = line[3:].strip()
        elif line == "":
            # Dispatch event
            if data_lines:
                current["data"] = "\n".join(data_lines)
                events.append(current)
            current = {}
            data_lines = []

    return events


# ─── Rule management ─────────────────────────────────────────────────────────

def list_rules() -> List[Dict]:
    """Fetch current rules from Firehose API."""
    if not FIREHOSE_TOKEN:
        print("[firehose] FIREHOSE_TOKEN missing; cannot list rules")
        return []
    req = urllib.request.Request(
        f"{FIREHOSE_BASE}/rules",
        headers={
            "Authorization": f"Bearer {FIREHOSE_TOKEN}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"[firehose] Failed to list rules: HTTP {e.code}")
        return []
    except Exception as e:
        print(f"[firehose] Failed to list rules: {_redact_firehose_token(e)}")
        return []


def register_rules(dry_run: bool = False) -> None:
    """Register all configured rules with Firehose (idempotent by tag)."""
    if not FIREHOSE_TOKEN and not dry_run:
        print("[firehose] FIREHOSE_TOKEN missing; cannot register rules")
        return
    existing = list_rules()
    # existing may be a list of rule dicts, or empty/error
    if not isinstance(existing, list):
        existing = []
    existing_tags = {r.get("tag") for r in existing if isinstance(r, dict)}

    for rule in FIREHOSE_RULES:
        tag = rule["tag"]
        if tag in existing_tags:
            print(f"[firehose] Rule already exists: {tag}")
            continue

        if dry_run:
            print(f"[firehose] Would register: {tag}")
            print(f"  curl -X POST {FIREHOSE_BASE}/rules \\")
            print("    -H 'Authorization: Bearer $FIREHOSE_TOKEN' \\")
            print(f"    -H 'Content-Type: application/json' \\")
            print(f"    -d '{json.dumps(rule)}'")
            continue

        payload = json.dumps(rule).encode()
        req = urllib.request.Request(
            f"{FIREHOSE_BASE}/rules",
            data=payload,
            headers={
                "Authorization": f"Bearer {FIREHOSE_TOKEN}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
                print(f"[firehose] Registered rule: {tag} → id={result.get('id', '?')}")
        except urllib.error.HTTPError as e:
            print(f"[firehose] Failed to register {tag}: HTTP {e.code}")
        except Exception as e:
            print(
                f"[firehose] Failed to register {tag}: "
                f"{_redact_firehose_token(e)}"
            )
        time.sleep(0.5)  # polite — don't hammer the API


# ─── Core poller ─────────────────────────────────────────────────────────────

def poll_firehose(since: str = "20m") -> List[Dict]:
    """
    Poll Firehose stream for the past `since` window.

    Returns list of article dicts compatible with the RSS scanner output format,
    ready for dedup → rewrite → publish.

    Uses Last-Event-ID for exact-offset resume when available.
    """
    if not FIREHOSE_TOKEN:
        print("[firehose] FIREHOSE_TOKEN missing; skipping supplementary source")
        return []

    state = _load_state()
    last_event_id = state.get("last_event_id")

    # Firehose is a supplementary discovery lane. The main auto-publish path
    # must never spend minutes waiting on an empty SSE stream while RSS already
    # has a healthy batch, so keep both server-side and client-side waits short.
    params = {"timeout": str(FIREHOSE_STREAM_WAIT_SEC), "since": since}
    url = f"{FIREHOSE_BASE}/stream?" + urlencode(params)

    req_headers = {
        **BASE_HEADERS,
        "Authorization": f"Bearer {FIREHOSE_TOKEN}",
    }
    if last_event_id:
        req_headers["Last-Event-ID"] = last_event_id

    articles = []
    last_seen_id = last_event_id

    print(f"[firehose] Polling stream (since={since}, last_id={last_event_id or 'none'})...")
    try:
        req = urllib.request.Request(url, headers=req_headers)
        with urllib.request.urlopen(req, timeout=FIREHOSE_HTTP_TIMEOUT_SEC) as resp:
            raw = resp.read()

        events = _parse_sse_events(raw)
        print(f"[firehose] Received {len(events)} SSE events")

        for event in events:
            if event.get("id"):
                last_seen_id = event["id"]

            event_type = event.get("event", "update")
            if event_type not in ("update", "create", ""):
                continue

            raw_data = event.get("data", "")
            if not raw_data or raw_data in ("[]", "{}"):
                continue

            try:
                doc = json.loads(raw_data)
            except json.JSONDecodeError:
                continue

            # Unwrap list payloads (e.g. [{...}])
            if isinstance(doc, list):
                doc = doc[0] if doc else None
            if not isinstance(doc, dict):
                continue

            # Handle both wrapped {"document": {...}} and bare {...}
            inner = doc.get("document")
            if isinstance(inner, dict):
                doc = inner

            article = _parse_firehose_doc(doc, event)
            if article:
                articles.append(article)

    except urllib.error.HTTPError as e:
        print(f"[firehose] HTTP {e.code}")
    except Exception as e:
        print(f"[firehose] Poll error: {_redact_firehose_token(e)}")

    # Persist last event ID for next run
    if last_seen_id and last_seen_id != last_event_id:
        state["last_event_id"] = last_seen_id
        state["last_poll"] = datetime.now(timezone.utc).isoformat()
        _save_state(state)

    # Dedup within this batch by URL hash
    seen_hashes = set()
    unique = []
    for a in articles:
        h = a.get("_url_hash", "")
        if h and h not in seen_hashes:
            seen_hashes.add(h)
            unique.append(a)

    print(f"[firehose] {len(articles)} events → {len(unique)} unique articles")
    return unique


def _parse_firehose_doc(doc: Dict, event: Dict) -> Optional[Dict]:
    """Extract article fields from a Firehose document object."""
    url = doc.get("url") or doc.get("link") or ""
    title = doc.get("title") or ""
    if not url or not title:
        return None

    # Language guard — only Finnish content
    lang = doc.get("language") or doc.get("lang") or ""
    if lang and lang.lower() not in ("fi", "fin", ""):
        return None

    description = doc.get("description") or doc.get("summary") or ""
    # Firehose may provide full markdown text — use as description if short enough
    markdown = doc.get("markdown") or doc.get("content") or ""
    if not description and markdown:
        description = markdown[:500]
    elif markdown and len(markdown) > len(description):
        description = markdown[:500]

    pub_date = doc.get("published_at") or doc.get("published") or doc.get("created_at") or ""
    if not pub_date:
        pub_date = datetime.now(timezone.utc).isoformat()

    # Determine category hint from Firehose metadata.
    # Field name quirk: response uses page_category[] (singular key, array value)
    # and page_types[] (plural key, array value). Both must be handled.
    _raw_cats = doc.get("page_category") or doc.get("page_categories") or []
    if not isinstance(_raw_cats, list):
        _raw_cats = [_raw_cats] if _raw_cats else []
    page_category = _raw_cats[0] if _raw_cats else ""

    _raw_types = doc.get("page_types") or doc.get("page_type") or []
    if not isinstance(_raw_types, list):
        _raw_types = [_raw_types] if _raw_types else []
    # page_types used for filtering only — not mapped to categories currently

    matched_tag = doc.get("matched_rule_tag") or doc.get("tag") or event.get("event") or ""

    category_hint = (
        _TAG_CATEGORY_MAP.get(matched_tag)
        or _CATEGORY_MAP.get(page_category)
    )

    normalized_url = _normalize_url(url)
    url_h = _url_hash(url)

    # Derive a human-readable source name and domain from the URL
    _parsed_url = urlparse(url)
    _source_domain = _parsed_url.netloc.removeprefix("www.") if url else ""
    _source_name = _source_domain or "Firehose"

    return {
        "title": title.strip(),
        "description": str(description)[:500],
        "link": url,
        "published": pub_date,
        "source": _source_name,
        "source_domain": _source_domain,
        "language": "fi",
        "fingerprint": _title_hash(title),
        "_url_hash": url_h,
        "_normalized_url": normalized_url,
        "_source_type": "firehose",
        "_matched_rule": matched_tag,
        "_page_category": page_category,
        **({"category_hint": category_hint} if category_hint else {}),
    }


# ─── Entry point ─────────────────────────────────────────────────────────────

def delete_rule(rule_id: str) -> bool:
    """Delete a rule by ID. Returns True on success."""
    if not FIREHOSE_TOKEN:
        print("[firehose] FIREHOSE_TOKEN missing; cannot delete rules")
        return False
    req = urllib.request.Request(
        f"{FIREHOSE_BASE}/rules/{rule_id}",
        headers={
            "Authorization": f"Bearer {FIREHOSE_TOKEN}",
            "Accept": "application/json",
        },
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[firehose] Deleted rule {rule_id}: HTTP {resp.status}")
            return True
    except urllib.error.HTTPError as e:
        print(f"[firehose] Failed to delete {rule_id}: HTTP {e.code}")
        return False
    except Exception as e:
        print(
            f"[firehose] Failed to delete {rule_id}: "
            f"{_redact_firehose_token(e)}"
        )
        return False


if __name__ == "__main__":
    if "--rules" in sys.argv:
        print("=== Current Firehose rules (from API) ===")
        rules = list_rules()
        print(json.dumps(rules, indent=2))
        sys.exit(0)

    if "--register" in sys.argv:
        print("=== Registering Firehose rules ===")
        register_rules(dry_run=False)
        sys.exit(0)

    if "--delete-all" in sys.argv:
        print("=== Deleting all Firehose rules ===")
        rules = list_rules()
        rule_list = rules.get("data", rules) if isinstance(rules, dict) else rules
        for r in rule_list:
            if isinstance(r, dict) and r.get("id"):
                delete_rule(r["id"])
                time.sleep(0.3)
        sys.exit(0)

    articles = poll_firehose()
    print(json.dumps(articles[:5], indent=2, ensure_ascii=False))
    print(f"\nTotal: {len(articles)} articles")
