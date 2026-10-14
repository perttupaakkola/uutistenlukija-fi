"""Bounded topic detection and source collection for reader-first explainers.

RSS and search-result headlines are signals only.  They never enter the source packet as
evidence.  An explainer is admitted only after the collector has fetched one official
primary document and at least two independently published, readable reports.
"""
import hashlib
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .editorial import digest, timestamp, validate_packet, web_url
from .related import (BLOCKED_DOMAINS, MAX_RELATED_CHARS, USER_AGENT,
                      build_query, extract_article_text, extract_published)
from .slugs import slugify

KIND = "explainer"
POLICY = "explainer-sources-v2"
SECTION_LABELS = (
    "Mitä tapahtui",
    "Tausta",
    "Mitä se tarkoittaa sinulle",
    "Luvut",
    "Mitä seuraavaksi",
)
RSS_FEEDS = (
    "https://feeds.yle.fi/uutiset/v1/majorHeadlines/YLE_UUTISET.rss",
    "https://www.mtvuutiset.fi/rss/uutiset.rss",
    "https://www.is.fi/rss/tuoreimmat.xml",
)
MAX_TOPIC_SEARCHES = 6
MAX_FETCH_CALLS = 20
HELSINKI = ZoneInfo("Europe/Helsinki")
POLICY_FILE = Path(__file__).resolve().parents[1] / "sources/explainer-sources.json"

# Yle is explicitly headline-only for this feature.  The two named paywalled outlets and
# known mirrors/aggregators likewise never become evidence, even when search returns them.
TEXT_BLOCKED_DOMAINS = BLOCKED_DOMAINS + (
    "yle.fi", "hs.fi", "kauppalehti.fi",
    "ampparit.com", "high.fi", "stuudio.ee", "murkut.org", "positv.fi",
    "nordenbladet.fi", "rikosuutiset.fi",
)
# Discussion and social pages may echo a headline, but they are not independent news
# outlets and must not make a topic appear larger than it is.  Yle remains allowed here
# because its RSS/search headline is an explicit detection-only signal.
TOPIC_BLOCKED_DOMAINS = BLOCKED_DOMAINS + (
    "bsky.app", "threads.net", "vauva.fi", "murha.info", "suomi24.fi",
    "ampparit.com", "high.fi", "stuudio.ee", "murkut.org", "positv.fi",
    "nordenbladet.fi", "rikosuutiset.fi",
)
OFFICIAL_DOMAINS = (
    "valtioneuvosto.fi", "eduskunta.fi", "kela.fi", "vero.fi", "thl.fi",
    "traficom.fi", "finlex.fi", "suomi.fi", "stat.fi", "ec.europa.eu",
    "europa.eu", "hel.fi", "espoo.fi", "vantaa.fi", "tampere.fi",
    "turku.fi", "ouka.fi", "kuopio.fi", "hyvinvointialue.fi", "poliisi.fi",
    "ilmatieteenlaitos.fi", "fintraffic.fi", "oph.fi", "ruokavirasto.fi",
    "kkv.fi", "avi.fi",
)
IMPACT_THEMES = {
    "money": ("raha", "palk", "eläk", "toimeentulo", "velka", "korko"),
    "prices": ("hint", "maks", "lask", "sähkö", "polttoain"),
    "taxes": ("vero",),
    "benefits": ("tuki", "etuus", "kela", "asumistuk", "työttömyystur"),
    "public_services": ("palvel", "hyvinvointial", "terveysasem", "kirjasto", "päiväho"),
    "health": ("tervey", "sair", "lääk", "rokot", "epidem", "potila"),
    "housing": ("asumi", "asunto", "vuokr", "kiinteist", "laina"),
    "traffic": ("liikenne", "juna", "bussi", "raiti", "tie", "autoil", "matkust"),
    "weather": ("sää", "myrsky", "helle", "pakkan", "tulva", "ukkos", "lumis"),
    "schools": ("koulu", "oppila", "opisk", "päiväko"),
}
LAW_WORDS = ("laki", "lakimuut", "asetus")
LAW_IN_FORCE_WORDS = ("voimaan", "astuu", "hyväksy", "muuttuu", "muutos")
READER_WORDS = (
    "kuluttaj", "asiakka", "kotital", "asukka", "työntekij", "oppila", "opisk",
    "potila", "matkust", "autoil", "vuokrala", "eläkelä", "perhe",
)
CORPORATE_WORDS = (
    "yritys", "yhtiö", "konserni", "osake", "investoin", "datakesku", "google",
    "microsoft", "amazon", "meta", "kilpailuvir", "regulaatt", "markkinaoike",
)
NARROW_EVENT_WORDS = ("eurojackpot", "lotto", "rahapeli", "voittorivi", "jättipotti")
TOPIC_STOP_WORDS = frozenset(
    "mitä miten miksi näin tarkoittaa vaikuttaa kertoo uutinen uutiset uusi tämä tuo "
    "suomen suomessa hallitus hallituksen päätös päätöksen asia työ työt hanke "
    "hankkeen mukaan nyt taas olisi pitäisi voidaan sekä joka kun mutta".split()
)
CRIME_AGAINST_PERSON = re.compile(
    r"\b(murh|tapp|henkirikos|raisk|seksuaalirikos|pahoinpit|puukot|ampu|kouluisku|"
    r"kurist|surma|siepp|ihmiskaupp)\w*", re.I
)
STT_COPY = re.compile(r"\b(?:STT|Suomen Tietotoimisto)\b", re.I)
NON_REPORTING_HEADLINE = re.compile(r"\b(?:pääkirjoitus|kommentti|kolumni|analyysi)\b", re.I)


def _domain(url):
    try:
        return (urlsplit(url).hostname or "").lower().removeprefix("www.")
    except (TypeError, ValueError):
        return ""


def _domain_matches(domain, suffixes):
    return any(domain == suffix or domain.endswith("." + suffix) for suffix in suffixes)


def _outlet_domain(url):
    """Collapse subdomains so one publisher cannot count as several outlets."""
    domain = _domain(url)
    parts = domain.split(".")
    if len(parts) <= 2:
        return domain
    if parts[-2:] in (["co", "uk"], ["com", "au"], ["com", "br"]):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def story_key(title):
    """Stable, human-auditable dedupe identity for an explainer topic."""
    slug = slugify(title, max_words=10, max_chars=100)
    return "explainer:" + slug if slug else ""


def crime_against_person(title):
    return bool(isinstance(title, str) and CRIME_AGAINST_PERSON.search(title))


def _parse_date(value):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def parse_rss_headlines(raw, feed_url, now=None):
    """Read only feed titles, links and dates; never feed descriptions or article text."""
    now = now or datetime.now(timezone.utc)
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, TypeError):
        return []
    rows = []
    for item in root.findall(".//item")[:30]:
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip()
        published = _parse_date(item.findtext("pubDate") or item.findtext("date"))
        if not title or not link or published is None:
            continue
        age = now - published
        if age < timedelta(minutes=-5) or age > timedelta(hours=48):
            continue
        try:
            link = web_url(link)
        except ValueError:
            continue
        rows.append({"title": title, "url": link, "published_at": published.isoformat(),
                     "headline_only": True, "feed": feed_url})
    return rows


def _fetch(url, limit=2_000_000):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=25) as response:
        final = web_url(response.geturl())
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Explainer source exceeds bounded download size")
        return raw, (response.headers.get("Content-Type") or "").lower(), final


def collect_headlines(store, now=None, fetcher=None, feeds=RSS_FEEDS):
    """Combine recent rendered headlines with public headline-only RSS signals."""
    now = now or datetime.now(timezone.utc)
    fetcher = fetcher or _fetch
    rows = []
    if store is not None:
        for job in store.articles():
            try:
                created = timestamp(job["created_at"])
                if now - created > timedelta(hours=48) or created > now + timedelta(minutes=5):
                    continue
                draft = json.loads(job["draft"]) if isinstance(job["draft"], str) else job["draft"]
                packet = json.loads(job["packet"]) if isinstance(job["packet"], str) else job["packet"]
                rows.append({"title": draft["title"], "url": packet["sources"][0]["url"],
                             "published_at": created.isoformat(), "headline_only": True,
                             "feed": "own-rendered"})
            except (KeyError, TypeError, ValueError):
                continue
    for feed in feeds:
        try:
            fetched = fetcher(feed)
            raw = fetched[0] if isinstance(fetched, tuple) else fetched
            rows.extend(parse_rss_headlines(raw, feed, now))
        except (OSError, ValueError, urllib.error.URLError, TimeoutError):
            continue
    return rows


def _coverage_for(headline, search):
    hits = search(headline["title"], 12) or []
    coverage = [{"url": headline["url"], "title": headline["title"]}]
    seen = {_outlet_domain(headline["url"])}
    for hit in hits:
        try:
            url = web_url((hit or {}).get("url") or (hit or {}).get("href"))
        except (TypeError, ValueError):
            continue
        domain = _domain(url)
        outlet = _outlet_domain(url)
        if (not domain or outlet in seen or
                _domain_matches(domain, TOPIC_BLOCKED_DOMAINS) or
                _domain_matches(domain, OFFICIAL_DOMAINS)):
            continue
        hit_title = " ".join(str(hit.get("title") or "").split())
        if not deterministic_relevance(
                headline["title"], {"title": hit_title, "text": ""})["passed"]:
            continue
        seen.add(outlet)
        coverage.append({"url": url, "title": hit_title})
    return coverage


def _words(value):
    return re.findall(r"[a-zäöå]+", str(value or "").casefold())


def _contains_stem(words, stems):
    return any((word == stem[1:] if stem.startswith("=") else
                word == stem if len(stem) <= 3 else word.startswith(stem))
               for word in words for stem in stems)


def reader_impact(title, coverage=()):
    """Return an auditable reader-impact score and its matched themes.

    Outlet count measures how large a story is; this score separately measures whether it
    changes ordinary readers' money, rights, services, health, home, travel or schooling.
    Corporate/regulatory news without one of those explicit effects is not an explainer
    candidate, regardless of how many outlets repeat it.
    """
    text = " ".join([str(title or "")] + [str(item.get("title") or "")
                                           for item in coverage if isinstance(item, dict)])
    words = _words(text)
    reasons = [name for name, stems in IMPACT_THEMES.items()
               if _contains_stem(words, stems)]
    if (_contains_stem(words, LAW_WORDS) and
            _contains_stem(words, LAW_IN_FORCE_WORDS)):
        reasons.append("law_in_force")
    score = len(set(reasons)) * 4
    if _contains_stem(words, READER_WORDS):
        score += 3
        reasons.append("named_reader_group")
    if _contains_stem(words, ("tarkista", "hae", "ilmoita", "määräaika", "alkaen")):
        score += 2
        reasons.append("reader_action_or_deadline")
    corporate = _contains_stem(words, CORPORATE_WORDS)
    narrow_event = _contains_stem(words, NARROW_EVENT_WORDS)
    return {"score": score, "reasons": sorted(set(reasons)), "corporate": corporate,
            "direct_reader_effect": score > 0, "narrow_event": narrow_event}


def _topic_term(word):
    """Conservative Finnish-ish comparison stem for names, decisions and places."""
    word = word.casefold()
    for family in ("huija", "diesel", "bussi"):
        if word.startswith(family):
            return family
    for ending in ("ineen", "ssa", "ssä", "sta", "stä", "lla", "llä", "lta", "ltä",
                   "lle", "ksi", "tta", "ttä"):
        if len(word) - len(ending) >= 4 and word.endswith(ending):
            word = word[:-len(ending)]
            break
    if len(word) > 5 and word.endswith("n"):
        word = word[:-1]
    return word[:8]


def _topic_terms(title):
    terms = []
    for word in _words(title):
        if len(word) < 4 or word in TOPIC_STOP_WORDS:
            continue
        term = _topic_term(word)
        if len(term) >= 4 and term not in terms:
            terms.append(term)
    return sorted(terms)


def deterministic_relevance(topic_title, source):
    """Require source A to name at least one distinctive topic actor/decision/place."""
    terms = _topic_terms(topic_title)
    source_terms = {_topic_term(word) for word in
                    _words((source or {}).get("title", "") + " " +
                           (source or {}).get("text", "")) if len(word) >= 4}
    matched = sorted(set(terms) & source_terms)
    return {"topic_terms": terms, "matched_terms": matched, "passed": bool(matched)}


def _model_relevance(relevance_checker, topic_title, source, deterministic):
    if relevance_checker is None or not deterministic.get("passed"):
        return None
    request = {
        "fixture": False,
        "kind": "explainer_source_relevance",
        "topic_title": topic_title,
        "candidate": {key: source[key] for key in
                      ("url", "publisher", "title", "published_at", "text")},
        "deterministic_overlap": deterministic,
    }
    try:
        decision = relevance_checker(request)
    except Exception:
        return None
    if (not isinstance(decision, dict) or set(decision) != {"relevant", "reason"} or
            type(decision.get("relevant")) is not bool or
            not isinstance(decision.get("reason"), str) or
            not decision["reason"].strip() or len(decision["reason"]) > 1000):
        return None
    return {"deterministic": deterministic, "model": {
        "relevant": decision["relevant"], "reason": decision["reason"].strip()}}


def validate_primary_relevance(topic_title, source, record):
    expected = deterministic_relevance(topic_title, source)
    deterministic = record.get("deterministic") if isinstance(record, dict) else None
    model = record.get("model") if isinstance(record, dict) else None
    if (deterministic != expected or expected.get("passed") is not True or
            not isinstance(model, dict) or model.get("relevant") is not True or
            not isinstance(model.get("reason"), str) or not model["reason"].strip() or
            len(model["reason"]) > 1000):
        raise ValueError("Explainer source A is not directly relevant to its topic")
    return record


def pick_topics(headlines, search, covered_story_keys=(), *, max_topics=3,
                min_outlets=3, max_searches=MAX_TOPIC_SEARCHES):
    """Rank current subjects by independent outlet count and ordinary-reader impact."""
    covered = set(covered_story_keys)
    candidates, seen_keys = [], set()
    # Search calls are the scarce resource. Rank the raw headline signals first so a feed's
    # ordering cannot spend the whole budget on celebrity or corporate stories before a
    # benefit, price, service or health story is even measured for outlet coverage.
    eligible = []
    for position, headline in enumerate(headlines):
        title = (headline or {}).get("title", "")
        key = story_key(title)
        impact = reader_impact(title)
        if (not key or key in covered or impact["score"] <= 0 or
                crime_against_person(title) or
                NON_REPORTING_HEADLINE.search(title) or
                impact["narrow_event"] or
                (impact["corporate"] and not impact["direct_reader_effect"])):
            continue
        eligible.append((position, headline, impact))
    ranked = sorted(eligible, key=lambda row: (-row[2]["score"], row[0]))
    for _position, headline, preliminary_impact in ranked[:max_searches]:
        title = (headline or {}).get("title", "")
        key = story_key(title)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        try:
            coverage = _coverage_for(headline, search)
        except Exception:
            continue
        if len({_outlet_domain(item["url"]) for item in coverage}) < min_outlets:
            continue
        # Coverage results prove scale, but do not get to manufacture reader impact: search
        # engines can return adjacent stories containing words such as price or customer.
        impact = preliminary_impact
        candidates.append({"title": title, "story_key": key, "coverage": coverage,
                           "outlet_count": len(coverage), "impact_score": impact["score"],
                           "impact_reasons": impact["reasons"],
                           "corporate_topic": impact["corporate"],
                           "published_at": headline.get("published_at")})
    candidates.sort(key=lambda row: (-row["impact_score"], -row["outlet_count"],
                                     row["story_key"]))
    return candidates[:max_topics]


def previous_story_keys(store):
    result = set()
    if store is None:
        return result
    for row in store.db.execute("SELECT story_key FROM jobs WHERE story_key LIKE 'explainer:%'"):
        result.add(row[0])
    return result


def daily_count(store, now=None):
    """Count admissions in the current Helsinki calendar day, regardless of outcome."""
    now = now or datetime.now(timezone.utc)
    local_day = now.astimezone(HELSINKI).date()
    count = 0
    for row in store.db.execute("SELECT packet,created_at FROM jobs"):
        try:
            packet = json.loads(row[0])
            if (packet.get("kind") == KIND and
                    timestamp(row[1]).astimezone(HELSINKI).date() == local_day):
                count += 1
        except (ValueError, TypeError, KeyError):
            continue
    return count


def can_admit(store, now=None, limit=2):
    if type(limit) is not int or not 1 <= limit <= 2:
        raise ValueError("Explainer daily limit must be 1 or 2")
    return daily_count(store, now) < limit


def _usable_hit(hit, official=False, now=None, fetcher=None):
    """Turn a search hit into captured source evidence, or return None."""
    now = now or datetime.now(timezone.utc)
    fetcher = fetcher or _fetch
    try:
        url = web_url(hit.get("url") or hit.get("href"))
    except (AttributeError, ValueError):
        return None
    domain = _domain(url)
    if not domain or _domain_matches(domain, TEXT_BLOCKED_DOMAINS):
        return None
    if official != _domain_matches(domain, OFFICIAL_DOMAINS):
        return None
    title = " ".join(str(hit.get("title") or domain).split())
    supplied_text = hit.get("text")
    supplied_date = hit.get("published_at")
    raw = None
    if supplied_text is None:
        try:
            raw, mime, final = fetcher(url)
        except (OSError, ValueError, urllib.error.URLError, TimeoutError):
            return None
        if "html" not in mime:
            return None
        url, domain = final, _domain(final)
        if _domain_matches(domain, TEXT_BLOCKED_DOMAINS):
            return None
        body = extract_article_text(raw, final)
        published = extract_published(raw)
    else:
        body = " ".join(str(supplied_text).split())[:MAX_RELATED_CHARS]
        published = supplied_date
        raw = body.encode()
    if len(body) < 200 or STT_COPY.search(title) or STT_COPY.search(body[:500]):
        return None
    try:
        published_dt = timestamp(published)
    except (TypeError, ValueError):
        return None
    if published_dt > now + timedelta(minutes=5):
        return None
    return {"url": url, "publisher": domain, "title": title[:240],
            "published_at": published_dt.isoformat(), "text": body,
            "capture_sha256": hashlib.sha256(body.encode()).hexdigest()}


def build_packet(topic, search, *, now=None, fetcher=None, relevance_checker=None):
    """Build a packet only with a directly relevant A and two other usable reports."""
    now = now or datetime.now(timezone.utc)
    fetcher = fetcher or _fetch
    query = topic.get("title", "")
    search_query = build_query(query) or query
    try:
        official_hits = search(search_query + " viranomainen", 10) or []
        report_hits = (list(topic.get("coverage") or []) +
                       list(search(search_query, 12) or []))
    except Exception:
        return None
    primary = None
    primary_relevance = None
    for hit in official_hits[:4]:
        source = _usable_hit(hit, True, now, fetcher)
        if source is None:
            continue
        deterministic = deterministic_relevance(query, source)
        relevance = _model_relevance(relevance_checker, query, source, deterministic)
        if relevance is not None and relevance["model"]["relevant"] is True:
            primary = {**source, "primary_type": "official_document"}
            primary_relevance = relevance
            break

    reports = []
    seen_domains = set()
    seen_urls = set()
    for hit in report_hits:
        if len(reports) >= 6:
            break
        source = _usable_hit(hit, False, now, fetcher)
        if source is None:
            continue
        if not deterministic_relevance(query, source)["passed"]:
            continue
        domain = _domain(source["url"])
        if domain in seen_domains or source["url"] in seen_urls:
            continue
        seen_domains.add(domain)
        seen_urls.add(source["url"])
        reports.append(source)

    # A directly relevant official document is preferred. If none exists, the first
    # directly relevant open report becomes A; a tangential official text is never used to
    # decorate the packet.
    if primary is None:
        for index, source in enumerate(reports):
            deterministic = deterministic_relevance(query, source)
            relevance = _model_relevance(relevance_checker, query, source, deterministic)
            if relevance is not None and relevance["model"]["relevant"] is True:
                primary = {**source, "primary_type": "original_reporting"}
                primary_relevance = relevance
                reports.pop(index)
                break
    if primary is None:
        return None

    sources = [{**primary, "id": "A", "primary": True}]
    for source in reports[:5]:
        source.update(id=chr(ord("A") + len(sources)), related=True)
        sources.append(source)
    if len(sources) < 3:
        return None
    fresh = [source for source in sources
             if timedelta(minutes=-5) <= now - timestamp(source["published_at"])
             <= timedelta(hours=48)]
    if not fresh:
        return None
    freshest = max(fresh, key=lambda source: timestamp(source["published_at"]))
    freshest["news_hook"] = True
    captures = {source["id"]: source.pop("capture_sha256") for source in sources}
    packet = {
        "kind": KIND,
        "story_key": topic.get("story_key") or story_key(query),
        "fixture": False,
        "publication_basis": {
            "policy": POLICY,
            "policy_sha256": policy_digest(),
            "source_sha256": captures,
            "topic_title": query,
            "primary_relevance": primary_relevance,
            "topic_outlets": int(topic.get("outlet_count") or len(topic.get("coverage") or [])),
            "reader_impact_score": int(topic.get("impact_score") or 0),
            "reader_impact_reasons": list(topic.get("impact_reasons") or []),
        },
        "sources": sources,
        "image": None,
        "image_note": "Lähdekuvia ei käytetä; kuvitus valitaan erillisessä kuvaprosessissa.",
    }
    validate_packet(packet, now, 48)
    return packet


def capture_packet(packet, state_dir, *, now=None):
    """Persist a completed packet without performing another search or fetch."""
    now = now or datetime.now(timezone.utc)
    directory = Path(state_dir) / "intake" / digest(packet)
    directory.mkdir(parents=True, exist_ok=True)
    receipt = {"fixture": False, "kind": KIND, "retrieved_at": now.isoformat(),
               "packet_sha256": digest(packet),
               "source_sha256": packet["publication_basis"]["source_sha256"]}
    (directory / "packet.json").write_text(
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (directory / "receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return packet, receipt


def collect(topic, state_dir, search, *, now=None, fetcher=None, relevance_checker=None):
    """Build and capture one packet for the ordinary controller/publisher path."""
    now = now or datetime.now(timezone.utc)
    packet = build_packet(topic, search, now=now, fetcher=fetcher,
                          relevance_checker=relevance_checker)
    if packet is None:
        raise ValueError("Explainer topic lacks a directly relevant A source and two usable reports")
    return capture_packet(packet, state_dir, now=now)


def policy_document():
    document = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    expected = {
        "mode": POLICY, "max_sources": 6, "min_sources": 3,
        "required_primary_id": "A", "headline_only_domains": ["yle.fi"],
        "blocked_text_domains": sorted(set(TEXT_BLOCKED_DOMAINS)),
        "official_domains": list(OFFICIAL_DOMAINS),
        "allowed_primary_types": ["official_document", "original_reporting"],
        "requires_deterministic_overlap": True,
        "requires_model_relevance": True,
        "max_fetch_calls_per_tick": MAX_FETCH_CALLS,
    }
    if document != expected:
        raise ValueError("Unreviewed explainer source policy")
    return document


def policy_digest():
    return digest(policy_document())


def discover_one(store, search, *, now=None, fetcher=None, feeds=RSS_FEEDS,
                 relevance_checker=None):
    """Return the highest-ranked packet candidate without admitting or publishing it."""
    now = now or datetime.now(timezone.utc)
    fetcher = fetcher or _fetch
    calls = 0
    def spend():
        nonlocal calls
        calls += 1
        if calls > MAX_FETCH_CALLS:
            raise ValueError("Explainer fetch budget exhausted")
    def bounded_fetch(url, *args, **kwargs):
        spend()
        return fetcher(url, *args, **kwargs)
    def bounded_search(query, limit):
        spend()
        return search(query, limit)
    headlines = collect_headlines(store, now, fetcher=bounded_fetch, feeds=feeds)
    topics = pick_topics(headlines, bounded_search, previous_story_keys(store), max_topics=3)
    for topic in topics:
        packet = build_packet(topic, bounded_search, now=now, fetcher=bounded_fetch,
                              relevance_checker=relevance_checker)
        if packet is not None:
            return topic, packet
    return None
