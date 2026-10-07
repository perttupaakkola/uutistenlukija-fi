"""Escaped static HTML from reviewed SQLite records. Private preview only."""
import html
import hashlib
import json
import re
from copy import deepcopy
from datetime import timezone
from difflib import SequenceMatcher
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from . import frontpage, indexing, seo, slugs
from .editorial import ROOT, digest, timestamp, validate_draft, validate_review


SITE_NAME = "Uutistenlukija"
SITE_URL = "https://uutistenlukija.fi/"
HOME_DESCRIPTION = "Uutiset, niiden tausta ja alkuperäiset lähteet samassa paikassa."
GENERATED_IMAGE_FALLBACK = (1536, 1024)
# Hard cap on stories per listing. Page 1 promotes its newest story to a lead, and
# that lead counts as one of the 30; later pages need no promoted lead.
PAGE_SIZE = 30
# The imported portal theme has room for a denser headline column than the old four-row slice.
# Lower topic cards are separately capped by the fixed taxonomy below.
HOMEPAGE_CENTER_ROWS = 4
HOMEPAGE_TOPIC_LIMIT = 7
HELSINKI = ZoneInfo("Europe/Helsinki")
ABOUT_PATH = "/tietoja/"
PRIVACY_PATH = "/tietosuoja/"
# These are the established populated desks. Empty routes remain available in the
# grouped full directory and are promoted here only after an explicit content review.
PRIMARY_CATEGORY_SLUGS = ("kotimaa", "ulkomaat", "talous", "kulttuuri", "tiede")
# Exact licence URLs whose short name is CC BY 4.0; trailing slashes are normalised.
CC_BY_40_URLS = frozenset({
    "https://creativecommons.org/licenses/by/4.0",
    "https://creativecommons.org/licenses/by/4.0/deed.fi",
})
# Visually audited 2026-09-24: a South African waste truck does not illustrate
# the Nordic municipal-governance meeting. Retain the source record for audit.
EXCLUDED_IMAGES = {'e30285f7354046d1034767b63a4ef9089678b245442ac406c133694a311c4958'}
IMAGE_ALT_CORRECTIONS = {
    '264c57353d9b25dc92b699b12ef724269a820b833bb5b8778d85e8ae5d2e7aec': 'Arkistokuva: matkustajakoneen siipi pilvien yllä.',
    'c4411f82b0001b9f6099f01b680fa02e29becf51c18a88a785ce489ec5111e0e': 'Arkistokuva: tuulivoimaloita ilta-auringossa.',
}
_PROGRAMME_LINK_ARTICLE = "/uutiset/kuopion-vanhustenviikko-tuo-kulttuuria-kohtaamisia-5cd5fcd61b42/"
_PROGRAMME_LINK_SOURCE = (
    "https://www.kuopio.fi/2026/10/05/"
    "kuopion-vanhustenviikolla-kohtaamisia-kulttuuria-ja-yhteisia-elamyksia/"
)
_PROGRAMME_LINK_LABEL = "www.kuopio.fi/vanhustenviikko2026"
_PROGRAMME_LINK_DESTINATION = "https://www.kuopio.fi/vanhustenviikko2026"
_PROGRAMME_LINK_PARAGRAPH = (
    "Vanhustyön keskusliiton avoimia verkkoluentoja voi kaupungin mukaan seurata myös "
    "yhteisissä etäkatsomoissa: maanantaina Nilsiässä, keskiviikkona Juankoskella ja "
    "perjantaina Maaningalla. Katsomoissa on lisäksi kevyttä tuolijumppaa. Koko "
    "tapahtumaohjelma on osoitteessa www.kuopio.fi/vanhustenviikko2026."
)


def display_image(image):
    if not image or image.get('sha256') in EXCLUDED_IMAGES:
        return None
    alt = IMAGE_ALT_CORRECTIONS.get(image.get('sha256'))
    return {**image, 'alt': alt} if alt else image


def short_license_label(license_url):
    """Standard short name for a licence URL, or "" when the URL is not that licence.

    This never invents terms: the stored licence text stays the label unless the
    record points at the exact known CC BY 4.0 document.
    """
    normalized = str(license_url or "").strip().rstrip("/")
    return "CC BY 4.0" if normalized in CC_BY_40_URLS else ""


def esc(value):
    return html.escape(str(value), quote=True)


def _paragraph_text_html(article_route, paragraph, sources):
    """Escape prose, adding only explicitly reviewed, article-bound programme links."""
    text = paragraph["text"]
    plain = esc(text)
    reviewed_links = (
        (_PROGRAMME_LINK_ARTICLE, _PROGRAMME_LINK_PARAGRAPH,
         _PROGRAMME_LINK_SOURCE, _PROGRAMME_LINK_LABEL, _PROGRAMME_LINK_DESTINATION),
        ('/uutiset/vantaan-syyslomassa-taidepajoja-kartanon-kekri-f1f023667c0f/',
         'Kaupunki ohjaa tarkistamaan syysloman koko ohjelman ja tapahtumien yksityiskohdat osoitteesta tapahtumat.vantaa.fi/syysloma. Kirjastojen tapahtumien tarkemmat tiedot löytyvät niiden omilta Helmet-sivuilta.',
         'https://www.vantaa.fi/fi/ajankohtaista/uutinen/syyslomalla-vantaalla-taiteillaan-temppuillaan-ja-nautitaan-kulttuurista',
         'tapahtumat.vantaa.fi/syysloma', 'https://tapahtumat.vantaa.fi/syysloma'),
        ('/uutiset/helsingin-rokotukset-alkoivat-75-vuotta-tayttaneille-a733ecffde70/', 'Alle 65-vuotiaiden ajanvaraus avautuu 7. lokakuuta, ja heidän rokotuksensa alkavat terveysasemilla 19. lokakuuta. Kaupunki ohjeistaa tarkistamaan ennen ajan varaamista, kuuluuko rokotusten kohderyhmään. Kohderyhmät ja ajanvarausohjeet löytyvät osoitteesta hel.fi/rokotukset.', 'https://www.hel.fi/fi/uutiset/75-vuotta-tayttaneiden-influenssa-ja-koronarokotukset-alkavat', 'hel.fi/rokotukset', 'https://www.hel.fi/fi/sosiaali-ja-terveyspalvelut/terveydenhoito/terveysasemat/rokotukset'),
    )
    for route, reviewed_text, source_url, label, destination in reviewed_links:
        if article_route != route or text != reviewed_text:
            continue
        if not any(source["id"] in paragraph["source_ids"] and source["url"] == source_url
                   for source in sources):
            continue
        if text.count(label) != 1:
            continue
        before, after = text.split(label)
        return (esc(before)
                + f'<a href="{esc(destination)}">{esc(label)}</a>'
                + esc(after))
    return plain


def semantic_datetime(value):
    """Return one UTC machine value and one Europe/Helsinki reader value.

    Stored timestamps stay authoritative. The UTC value belongs in ``datetime``;
    only the visible rendering is localized, including daylight-saving transitions.
    """
    utc = timestamp(value).astimezone(timezone.utc)
    local = utc.astimezone(HELSINKI)
    machine = utc.isoformat(timespec="seconds").replace("+00:00", "Z")
    visible = f"{local.day}.{local.month}.{local.year} klo {local.hour:02d}.{local.minute:02d}"
    return machine, visible


def time_html(value, css_class=""):
    machine, visible = semantic_datetime(value)
    class_attr = f' class="{esc(css_class)}"' if css_class else ""
    return f'<time{class_attr} datetime="{esc(machine)}">{esc(visible)}</time>'


def story_title_key(draft):
    """Conservative normalized key used only to compare already reviewed records."""
    title = str((draft or {}).get("title") or "").casefold()
    return " ".join(re.findall(r"[0-9a-zåäö]+", title))


def _primary_source(packet):
    sources = packet.get("sources") if isinstance(packet, dict) else None
    return sources[0] if isinstance(sources, list) and sources else {}


def same_story_record(left_packet, left_draft, right_packet, right_draft):
    """Recognize the audited duplicate without merging ordinary same-topic news.

    Production admission already makes exact source URLs unique. The confirmed pair
    has the same normalized title, publisher and source time, plus near-identical but
    not equal URL paths (a one-character spelling variation). Synthetic pagination
    fixtures intentionally reuse one exact URL, so equal URLs are not collapsed here.
    """
    if not story_title_key(left_draft) or story_title_key(left_draft) != story_title_key(right_draft):
        return False
    left, right = _primary_source(left_packet), _primary_source(right_packet)
    left_url, right_url = str(left.get("url") or ""), str(right.get("url") or "")
    if not left_url or not right_url or left_url == right_url:
        return False
    if (str(left.get("publisher") or "").casefold() != str(right.get("publisher") or "").casefold()
            or str(left.get("published_at") or "") != str(right.get("published_at") or "")):
        return False
    left_path = urlsplit(left_url).path.rstrip("/").casefold()
    right_path = urlsplit(right_url).path.rstrip("/").casefold()
    return bool(left_path and right_path and SequenceMatcher(None, left_path, right_path).ratio() >= 0.96)


def duplicate_story_ids(articles):
    """Later IDs in conservative duplicate groups; records/pages remain untouched."""
    kept = []
    duplicates = set()
    for job, packet, draft, review in articles:
        if any(same_story_record(packet, draft, old_packet, old_draft)
               for _old_job, old_packet, old_draft, _old_review in kept):
            duplicates.add(job["id"])
        else:
            kept.append((job, packet, draft, review))
    return duplicates


_RELATED_GENERIC_WORDS = frozenset({
    "alue", "alueellinen", "alkaa", "aloittaa", "avaa", "avataan", "ennen", "ensi",
    "esillä", "että", "hanke", "jatkaa", "jatkuu", "joka", "jälkeen", "kaupunki",
    "kasvaa", "kasvoi", "kasvanut", "kasvavat", "kasvua", "kasvu",
    "laskee", "laski", "laskenut", "laskivat", "pienenee", "pieneni",
    "kertoo", "koskeva", "kunta", "kunnallinen", "kanssa", "liittyvä", "mukaan",
    "muuttuu", "myös", "ovat", "palvelu", "päättyy", "päätös", "saa", "saavat",
    "sanoo", "sekä", "suunnitelma", "sulkee", "suljetaan", "suomen", "suomessa",
    "tiedote", "toiminta", "tulossa", "tänä", "uuden", "uudistaa", "uudistuu", "uusi",
    "uusia", "uutta", "valmistuu", "vuoden", "vuoksi", "vuonna", "vuotta",
})
# A shared place names the coverage area, not the subject. Publisher-derived words
# below catch other municipal names; this compact set also covers common cross-source
# locality wording in the current Finnish inventory.
_RELATED_LOCALITY_WORDS = frozenset({
    "espoo", "helsinki", "hämeenlinna", "jyväskylä", "kauniainen", "kotka", "kuopio",
    "lahti", "mikkeli", "oulu", "pori", "rovaniemi", "savonlinna", "tampere", "turku",
    "vaasa", "vantaa",
})


def _topic_stem(word):
    """Small Finnish title normalisation for nominative/genitive topic matches."""
    word = str(word or "").casefold()
    return word[:-1] if len(word) >= 5 and word.endswith("n") else word


_RELATED_GENERIC_STEMS = frozenset(_topic_stem(word) for word in _RELATED_GENERIC_WORDS)
_RELATED_LOCALITY_STEMS = frozenset(_topic_stem(word) for word in _RELATED_LOCALITY_WORDS)


def _publisher_words(packet):
    return {
        _topic_stem(word)
        for source in (packet or {}).get("sources", [])
        for word in re.findall(r"[0-9a-zåäö]+", str(source.get("publisher") or "").casefold())
        if len(word) >= 4
    }


def _topic_words(packet, draft):
    """Substantive title terms; generic framing, places and publisher identity do not qualify."""
    publisher_words = _publisher_words(packet)
    words = re.findall(r"[0-9a-zåäö]+", str((draft or {}).get("title") or "").casefold())
    # Years and amounts are context, never standalone evidence of a shared topic.
    # Preserve named alphanumeric topics; exclude only wholly numeric tokens.
    stems = {_topic_stem(word) for word in words if len(word) >= 4 and not word.isdecimal()}
    return stems - _RELATED_GENERIC_STEMS - _RELATED_LOCALITY_STEMS - publisher_words


"""Individually reviewed directed-edge removals; no ranking changes or refill."""
# Review of complete articles: scooter use does not continue in floodworks or
# diplomacy. Municipal appeal rights do not continue in education/archipelago law.
# The sports-partnership origin also has three independently reviewed non-sports
# selections. Apply every edge AFTER the ordinary top-three selection. Never refill.
_REVIEWED_RELATED_EXCLUSIONS = frozenset({
    ('81f29c83f79538d5fd9b01f974a798f551b47e58a0dff7cbce29db5efbb8bc7c', 'c8d9df28ef8ce7fe87450dd4498c914257cb037e3bc627f0e9cbad83925278bd'),
    ('81f29c83f79538d5fd9b01f974a798f551b47e58a0dff7cbce29db5efbb8bc7c', '61f60677da98a8254ef83ba6702da6b22a68af50845c8a32a1d95fce0e852a30'),
    ('81f29c83f79538d5fd9b01f974a798f551b47e58a0dff7cbce29db5efbb8bc7c', 'c1124443e5729a96eed55f2422fec75a1aeaf45a6040452b8a2103551b937c30'),
    ('fe92f910b26aac13d8b676d93310d1f190e2382d7084b1dd2f7afeaa6e319148', 'b2545a6894798b253700c72456987a124b4060a0820afeda4eec13e48028fd9d'),
    ('fe92f910b26aac13d8b676d93310d1f190e2382d7084b1dd2f7afeaa6e319148', '2a902aa7df9e34ae63e77bb635eadbc1dd101069705453301a65c5650c023598'),
    ('ecf85fae35c2030e53ecf87a2489e7876027137199936bebe0c85989dce60440', 'f9615094ff1726f6b3f50457d7dbc12c15dd70b8d6982689b5c08a756fef9517'),
    ('ecf85fae35c2030e53ecf87a2489e7876027137199936bebe0c85989dce60440', '45d3e3c1610bb940a2ba807ea2824966867423a0821f5e1ef237c5d992abc56a'),
    ('ecf85fae35c2030e53ecf87a2489e7876027137199936bebe0c85989dce60440', 'ccde11681bc6ee07fc9d97ebb6d6c5747a3d3adb2ca13105cfeec63613733648'),
})

# SHA-256 of title, summary and every paragraph joined by a literal newline.
# These pins bind the round-1 exclusions to the exact complete texts reviewed by
# Hermes; a changed stored text must be reviewed again rather than inheriting them.
_ROUND1_RELATED_TEXT_SHA256 = {
    'ecf85fae35c2030e53ecf87a2489e7876027137199936bebe0c85989dce60440': '15847e11aba83ea49e8c361bafb401f1b72eb563d7dba89ba370cee15d463f33',
    'f9615094ff1726f6b3f50457d7dbc12c15dd70b8d6982689b5c08a756fef9517': 'c53b05480f1a4b99a81133f6848e42611d0eaa8fca0e5fd6a5de780135768012',
    '45d3e3c1610bb940a2ba807ea2824966867423a0821f5e1ef237c5d992abc56a': '53e006443dc404c4544b4934c03d1604e0465918cc2b0dfe37baf643033157b9',
    'ccde11681bc6ee07fc9d97ebb6d6c5747a3d3adb2ca13105cfeec63613733648': '6820a5d4a9744cde5d8f49a1edc2b526c0b32e562c777c44b7cde476b1c8a0eb',
}


def _reviewed_text_sha256(draft):
    values = [draft.get('title', ''), draft.get('summary', '')]
    values.extend(paragraph.get('text', '') for paragraph in draft.get('paragraphs', []))
    return hashlib.sha256('\n'.join(values).encode()).hexdigest()


def validate_round1_related_text_pins(articles):
    """Fail closed if any present round-1 reviewed article text has changed."""
    for job, _packet, draft, _review in articles:
        expected = _ROUND1_RELATED_TEXT_SHA256.get(job['id'])
        if expected and _reviewed_text_sha256(draft) != expected:
            raise ValueError(f"Round-1 related text pin changed: {job['id']}")


def reviewed_related_picks(job, picks):
    """Remove only reviewed directed edges, retaining order and never refilling."""
    return [(candidate_job, candidate_draft)
            for candidate_job, candidate_draft in picks
            if (job['id'], candidate_job['id']) not in _REVIEWED_RELATED_EXCLUSIONS]


def related_story_score(packet, draft, candidate_packet, candidate_draft):
    """Small evidence-based relevance score; zero means the candidate is filler."""
    if story_title_key(draft) == story_title_key(candidate_draft):
        return 0
    overlap = _topic_words(packet, draft) & _topic_words(candidate_packet, candidate_draft)
    # Category, publisher and host only rank stories that already share a real
    # subject term. They can never turn same-municipality miscellany into a link.
    if not overlap:
        return 0
    score = 4 * len(overlap)
    if draft.get("category") == candidate_draft.get("category"):
        score += 2
    publishers = {str(source.get("publisher") or "").casefold()
                  for source in packet.get("sources", []) if source.get("publisher")}
    candidate_publishers = {str(source.get("publisher") or "").casefold()
                            for source in candidate_packet.get("sources", []) if source.get("publisher")}
    if publishers & candidate_publishers:
        score += 2
    hosts = {urlsplit(str(source.get("url") or "")).hostname
             for source in packet.get("sources", []) if source.get("url")}
    candidate_hosts = {urlsplit(str(source.get("url") or "")).hostname
                       for source in candidate_packet.get("sources", []) if source.get("url")}
    if (hosts - {None}) & (candidate_hosts - {None}):
        score += 1
    return score


def paginated_listing_path(base_path, page_number):
    """Stable first page plus /sivu/N/ descendants for one real archive."""
    if (not isinstance(base_path, str) or not base_path.startswith("/")
            or not base_path.endswith("/") or "//" in base_path):
        raise ValueError("Invalid listing base path")
    if isinstance(page_number, bool) or not isinstance(page_number, int) or page_number < 1:
        raise ValueError("Invalid listing page number")
    if base_path == "/":
        return listing_page_path(page_number)
    return base_path if page_number == 1 else f"{base_path}sivu/{page_number}/"


def _positive_int(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def image_dimensions(image):
    """Intrinsic (width, height) for an <img>, or None when the record has none.

    Generated illustrations predate recorded pixel metadata in legacy records, so
    they fall back to the generator's known output size. Source photographs without
    recorded dimensions must not claim a size they never had.
    """
    pixels = image.get("pixels")
    if isinstance(pixels, dict):
        width, height = _positive_int(pixels.get("width")), _positive_int(pixels.get("height"))
        if width and height:
            return width, height
    width, height = _positive_int(image.get("width")), _positive_int(image.get("height"))
    if width and height:
        return width, height
    if image.get("generated") is True:
        return GENERATED_IMAGE_FALLBACK
    return None


def image_credit_html(image):
    """Escaped reader-facing credit, with reviewed stock links where applicable."""
    if image.get("stock_provenance"):
        provenance = image["stock_provenance"]
        photographer = esc(provenance["photographer"])
        photo_url = esc(provenance["photo_url"])
        provider = provenance["provider"]
        if provider == 'statfi':
            return f'Lähde: <a href="{photo_url}">Tilastokeskus</a>'
        if provider == 'helsinki':
            return (f'Kuva: <a href="{photo_url}">Helsingin kaupunki</a> / '
                    f'<a href="{esc(provenance["photographer_url"])}">{photographer}</a>')
        if provider == "unsplash":
            return (f'Photo by <a href="{esc(provenance["photographer_url"])}">{photographer}</a> '
                    f'on <a href="{photo_url}">Unsplash</a>')
        provider_label = {
            "pexels": "Pexels",
            "wikimedia": "Wikimedia Commons",
            "google": "Google Custom Search",
        }.get(provider, provider.title())
        return (f'Photo by <a href="{esc(provenance["photographer_url"])}">{photographer}</a> '
                f'on <a href="{photo_url}">{provider_label}</a>')
    return esc(image.get("credit", ""))


def image_size_attributes(image):
    """`width`/`height` (when known) and `decoding` attributes for an <img>."""
    dimensions = image_dimensions(image)
    size = f' width="{dimensions[0]}" height="{dimensions[1]}"' if dimensions else ""
    return size + ' decoding="async"'


def homepage_image_figure(image, image_url, lazy):
    """Homepage image wrapper for a reviewed image, sized like the article page.

    Only images below the fold are lazy-loaded, so the lead never delays its own
    paint. There are no srcset variants: exactly one reviewed asset is served.
    The image has no listing credit; full real-image rights live inside its article.
    """
    loading = ' loading="lazy"' if lazy else ""
    return (f'<div class="portal-lead__image">'
            f'<img src="{esc(image_url)}" alt="{esc(image["alt"])}" '
            f'{image_size_attributes(image)}{loading} data-image-fallback="lead" '
            f'referrerpolicy="no-referrer"></div>')


def listing_image_slot(image, image_url, slot, story_url, story_title, lazy=True):
    """Link a reviewed thumbnail to its story; rights remain in the article."""
    loading = ' loading="lazy"' if lazy else ""
    return (f'<div class="{slot}">'
            f'<a class="portal-thumb__story" href="{esc(story_url)}" '
            f'aria-label="Lue juttu: {esc(story_title)}">'
            f'<img src="{esc(image_url)}" alt="{esc(image["alt"])}" '
            f'{image_size_attributes(image)}{loading} data-image-fallback="thumbnail" '
            f'referrerpolicy="no-referrer"></a></div>')


def jsonld_script(payload):
    """JSON-LD script tag; `<` is escaped so record text cannot close the tag."""
    data = json.dumps(payload, ensure_ascii=False)
    for char, replacement in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026")):
        data = data.replace(char, replacement)
    return f'<script type="application/ld+json">{data}</script>'


def website_jsonld():
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": SITE_NAME,
        "url": SITE_URL,
        "description": HOME_DESCRIPTION,
        "inLanguage": "fi",
    }


def listing_page_path(page_number):
    """Public path of one listing page: page 1 is the homepage, page N is /sivu/N/."""
    return "/" if page_number == 1 else f"/sivu/{page_number}/"


def pagination_nav(page_number, page_count, base_path="/"):
    """Prev/next anchors for one listing page, or "" when there is only one page.

    The links are real paths and the Finnish labels name the page they lead to. The
    first page has no previous link and the last page has no next link, so no anchor
    ever points at a page that does not exist.
    """
    if page_count <= 1:
        return ""
    links = []
    if page_number > 1:
        previous = paginated_listing_path(base_path, page_number - 1)
        links.append(f'<a class="page-prev" rel="prev" href="{esc(previous)}" '
                     f'aria-label="Edellinen sivu: sivu {page_number - 1}">'
                     f'<span aria-hidden="true">←</span> Edellinen sivu</a>')
    links.append(f'<span class="page-current" aria-current="page">Sivu {page_number} / {page_count}</span>')
    if page_number < page_count:
        following = paginated_listing_path(base_path, page_number + 1)
        links.append(f'<a class="page-next" rel="next" href="{esc(following)}" '
                     f'aria-label="Seuraava sivu: sivu {page_number + 1}">'
                     f'Seuraava sivu <span aria-hidden="true">→</span></a>')
    return f'<nav class="pager" aria-label="Sivujen selaus">{"".join(links)}</nav>'


def home_item_list_jsonld(articles, start_position=1):
    """ItemList naming exactly the stories on one listing page, in rendered order.

    Callers pass one page's slice of listing items, never the whole archive, so
    positions stay honest for that page. `start_position` continues the count across
    pages (page 2 starts at 31), so no position claims a rank the story does not hold
    in the listing. Each item is (job, draft, link, ...); the link is the same URL the
    page itself rendered.
    """
    return {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": position,
                "url": SITE_URL.rstrip("/") + item[2],
                "name": item[1]["title"],
            }
            for position, item in enumerate(articles, start_position)
        ],
    }


def homepage_head_meta(articles, path="/", page_title="Uusimmat uutiset", start_position=1,
                       description=HOME_DESCRIPTION):
    """Description/OG/Twitter/JSON-LD block for one public listing page.

    `path` is that page's own URL and `articles` is exactly the slice rendered on it,
    so the OG URL and the ItemList describe this page rather than the whole archive.
    The WebSite JSON-LD stays site-level and keeps naming the site root.
    """
    title = f"{page_title} · {SITE_NAME}"
    url = SITE_URL.rstrip("/") + path
    lead_image = articles[0][6] if articles and len(articles[0]) > 6 else None
    image_meta = ""
    if lead_image:
        absolute_image = (lead_image if str(lead_image).startswith("http")
                          else SITE_URL.rstrip("/") + str(lead_image))
        image_meta = (f'<meta property="og:image" content="{esc(absolute_image)}">'
                      f'<meta name="twitter:image" content="{esc(absolute_image)}">')
    twitter_card = "summary_large_image" if lead_image else "summary"
    metas = (
        f'<meta name="description" content="{esc(description)}">'
        f'<meta property="og:site_name" content="{esc(SITE_NAME)}">'
        f'<meta property="og:type" content="website">'
        f'<meta property="og:title" content="{esc(title)}">'
        f'<meta property="og:url" content="{esc(url)}">'
        f'<meta property="og:description" content="{esc(description)}">'
        f'<meta name="twitter:card" content="{twitter_card}">'
        f'<meta name="twitter:title" content="{esc(title)}">'
        f'<meta name="twitter:description" content="{esc(description)}">'
    ) + image_meta
    return metas + jsonld_script(website_jsonld()) + jsonld_script(home_item_list_jsonld(articles, start_position))


def atomic_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if isinstance(value, bytes):
        temporary.write_bytes(value)
    else:
        temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def prune_stale_listing_pages(output_dir, page_count):
    """Delete generated /sivu/N/index.html pages this render did not produce.

    Page 1 is the homepage and later pages run 2..page_count, so any other numeric
    archive directory is a leftover from a longer earlier render (or from a renderer
    that also wrote a /sivu/1/ duplicate) and must not survive. Only exact numeric
    names are touched, and only real directories inside `output_dir`: a symlinked
    `sivu` root or numeric child is skipped before it is traversed, so a link can
    never take the prune outside the output tree. A numeric regular file is skipped
    entirely, and only a directory our own removal left empty is cleaned up.
    """
    prune_stale_paginated_children(Path(output_dir) / "sivu", page_count)


def prune_stale_paginated_children(sivu_dir, page_count):
    """Remove only stale generated numeric child pages under one archive root."""
    sivu_dir = Path(sivu_dir)
    if sivu_dir.is_symlink() or not sivu_dir.is_dir():
        return
    for child in sivu_dir.iterdir():
        if not re.fullmatch(r"[1-9][0-9]*", child.name):
            continue
        if 2 <= int(child.name) <= page_count:
            continue
        # Skip links and plain files: following a numeric symlink would delete a
        # generated-looking page outside the output tree, and rmdir on a regular
        # file is not something a stale-page cleanup should attempt at all.
        if child.is_symlink() or not child.is_dir():
            continue
        page_file = child / "index.html"
        if page_file.is_file() and not page_file.is_symlink():
            page_file.unlink()
        try:
            child.rmdir()
        except OSError:
            # Keep any directory that still holds something we did not generate.
            pass


def reading_time_minutes(draft):
    """Whole minutes to read a draft, from its own paragraph text (min 1)."""
    words = sum(len(str(paragraph.get("text") or "").split())
                for paragraph in draft.get("paragraphs") or [])
    return max(1, (words + 199) // 200)


def category_slug(category):
    """CSS-safe category modifier for theme markup (Finnish letters kept)."""
    slug = "".join(char if char.isalnum() else "-" for char in str(category or "").strip().lower())
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "muu"


# Fixed reader-facing category routes. The stored taxonomy (editorial.CATEGORIES)
# still calls the world desk "Maailma"; readers see "Ulkomaat" for those records and
# the route stays /categories/ulkomaat/. Nothing here rewrites stored drafts.
CATEGORY_PAGES = (
    ("kotimaa", "Kotimaa"),
    ("ulkomaat", "Ulkomaat"),
    ("talous", "Talous"),
    ("teknologia", "Teknologia"),
    ("urheilu", "Urheilu"),
    ("kulttuuri", "Kulttuuri"),
    ("tiede", "Tiede"),
)
CATEGORY_ALIASES = {"maailma": "ulkomaat"}
LATEST_PATH = "/tuoreimmat/"
OPPAAT_PATH = "/oppaat/"
SOURCES_PATH = "/lahteet/"
GUIDES_DESCRIPTION = (
    "Syysloman 2026 tapahtumajutut Helsingistä ja Vantaalta. "
    "Tarkista ajantasaiset ohjelmat jutun lähteistä."
)
GUIDES_JOB_IDS = frozenset({
    "9c818b9e83818ccf047a7fce9a4c2657f551f5abe743370f60b812af3bd5ed56",
    "f1f023667c0fcb8fd1fc1a0b600cb91c32c7d5717e765892463169e1c4aedcfa",
})
GUIDES_SINGLE_DESCRIPTIONS = {
    "9c818b9e83818ccf047a7fce9a4c2657f551f5abe743370f60b812af3bd5ed56":
        "Syysloman 2026 tapahtumajuttu Helsingistä. Tarkista ajantasainen ohjelma jutun lähteestä.",
    "f1f023667c0fcb8fd1fc1a0b600cb91c32c7d5717e765892463169e1c4aedcfa":
        "Syysloman 2026 tapahtumajuttu Vantaalta. Tarkista ajantasainen ohjelma jutun lähteestä.",
}


def category_page_slug(category):
    """Fixed route slug for a stored category, or None when it has no page."""
    key = str(category or "").strip().lower()
    key = CATEGORY_ALIASES.get(key, key)
    for slug, display in CATEGORY_PAGES:
        if key in (slug, display.lower()):
            return slug
    return None


def category_route(category):
    """Public route for an article's category badge; the latest listing as fallback."""
    slug = category_page_slug(category)
    return f"/categories/{slug}/" if slug else LATEST_PATH


def category_display(category):
    """Reader-facing name for a stored category ("Maailma" is shown as "Ulkomaat")."""
    slug = category_page_slug(category)
    for page_slug, display in CATEGORY_PAGES:
        if page_slug == slug:
            return display
    return str(category or "").strip()


def guides_listing_items(listing_items):
    """Select only the reviewed guide stories, preserving archive order and data."""
    return [item for item in listing_items if item[0].get("id") in GUIDES_JOB_IDS]


def guides_description(items):
    """Describe only the guide cities represented by the selected listing items."""
    ids = {item[0].get("id") for item in items}
    if ids == GUIDES_JOB_IDS:
        return GUIDES_DESCRIPTION
    if len(ids) == 1:
        return GUIDES_SINGLE_DESCRIPTIONS[next(iter(ids))]
    return "Toimitukselliset oppaat ja taustat."


def article_hero_figure(image, image_url):
    """Article hero with intrinsic dimensions and honest, quiet image disclosure."""
    caption = (f'<figcaption class="article-hero-caption">{esc(image["caption"])}</figcaption>'
               if image.get("generated") is True else "")
    return (f'<figure class="article-hero"><img src="{esc(image_url)}" alt="{esc(image["alt"])}" '
            f'{image_size_attributes(image)} data-image-fallback="hero" referrerpolicy="no-referrer">'
            f'{caption}</figure>')


def resolved_image_url(image, state_dir, output_dir, assets):
    """Reuse the article's reviewed image bytes and public URL in every placement."""
    image_url = image['url']
    if image.get('local_path'):
        sha = image.get('sha256', '')
        if state_dir is None or not re.fullmatch(r'[0-9a-f]{64}', sha) or image['local_path'] != f'media/{sha}.jpg':
            raise ValueError('Invalid local image identity')
        data = (Path(state_dir) / image['local_path']).read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            raise ValueError('Local image does not match reviewed rights record')
        image_url = f'/{assets}/{sha}.jpg'
        atomic_write(Path(output_dir) / image_url.lstrip('/'), data)
    return image_url


def related_story_html(job, draft, state_dir, output_dir, assets):
    """One quiet image-backed story link; its article contains the image rights."""
    href = '/' + article_path(job)
    image = display_image(draft.get('image'))
    if not image:
        return f'<li class="related-story related-story--text"><a href="{href}">{esc(draft["title"])}</a></li>'
    image_url = resolved_image_url(image, state_dir, output_dir, assets)
    thumbnail = (f'<span class="related-story__thumb"><img src="{esc(image_url)}" '
                 f'alt="{esc(image["alt"])}" {image_size_attributes(image)} '
                 'loading="lazy" data-image-fallback="thumbnail" referrerpolicy="no-referrer"></span>')
    return (f'<li class="related-story"><a class="related-story__link" href="{href}">'
            f'{thumbnail}<span class="related-story__title">{esc(draft["title"])}</span></a></li>')


def article_context_html(job, draft, articles, related_ids=()):
    """Truthful section and recency routes, distinct from evidence-based related news."""
    excluded = {job["id"], *related_ids}

    def visible(candidate):
        candidate_job, candidate_packet, candidate_draft, _review = candidate
        status = candidate_packet.get("article_status")
        return (candidate_job["id"] not in excluded and
                not (isinstance(status, dict) and status.get("kind") == "withdrawn") and
                candidate_draft.get("title"))

    candidates = [candidate for candidate in articles if visible(candidate)]
    desk_slug = category_page_slug(draft.get("category"))
    same_desk = [candidate for candidate in candidates
                 if category_page_slug(candidate[2].get("category")) == desk_slug][:3]
    excluded.update(candidate[0]["id"] for candidate in same_desk)
    newest = [candidate for candidate in candidates if candidate[0]["id"] not in excluded][:4]

    def story_rows(values):
        rows = []
        for candidate_job, _packet, candidate_draft, _review in values:
            href = "/" + article_path(candidate_job)
            rows.append(
                f'<li><a href="{href}"><span class="article-context__title">'
                f'{esc(candidate_draft["title"])}</span>'
                f'<span class="article-context__meta">{esc(category_display(candidate_draft.get("category")))}'
                f'<span aria-hidden="true"> · </span>{time_html(candidate_job["created_at"])}</span></a></li>')
        return "".join(rows)

    blocks = []
    if same_desk:
        blocks.append(
            '<section class="article-context__block">'
            '<div class="article-context__head"><h2>Samasta osastosta</h2>'
            f'<a href="{esc(category_route(draft.get("category")))}">Kaikki {esc(category_display(draft.get("category"))).lower()}-uutiset</a></div>'
            f'<ul>{story_rows(same_desk)}</ul></section>')
    if newest:
        blocks.append(
            '<section class="article-context__block">'
            f'<div class="article-context__head"><h2>Uusimmat</h2><a href="{LATEST_PATH}">Koko uutisvirta</a></div>'
            f'<ul>{story_rows(newest)}</ul></section>')
    if not blocks:
        return ""
    return '<aside class="article-context" aria-label="Jatka lukemista">' + "".join(blocks) + '</aside>'


def image_rights_html(image):
    """Image credit/caption/licence/source section, rendered next to the sources.

    A generated illustration shows the normalized reader credit "AI-kuvitus" and links
    its illustration terms; the stored record (including the model name) is untouched
    and stays internal. Stock photographs keep their stored credit, licence and source.
    """
    if not image:
        return ""
    if image.get("generated") is True:
        body = (f'AI-kuvitus · <a href="{esc(image["license_url"])}">'
                f'AI-kuvien käyttöehdot</a>')
    else:
        body = (f'{esc(image.get("caption", ""))} {image_credit_html(image)} · '
                f'<a href="{esc(image["license_url"])}">{esc(image["license"])}</a> · '
                f'<a href="{esc(image["source_url"])}">Kuvan lähde</a>')
        attribution = image.get('stock_provenance', {}).get('attribution')
        if attribution:
            body += f' · {esc(attribution["title"])}. {esc(attribution["changes"])}'
            if attribution.get('source_credit'):
                body += f' {esc(attribution["source_credit"])}.'
    return f'<section class="image-rights"><h2>Kuvan käyttöoikeudet</h2><p>{body}</p></section>'


def article_status_html(status):
    """Optional genuine update/correction/withdrawal state; absent means no claim."""
    if status is None:
        return ""
    if not isinstance(status, dict) or set(status) - {"kind", "at", "note"}:
        raise ValueError("Invalid article status")
    kind = status.get("kind")
    labels = {
        "updated": ("Päivitetty", "Juttua on päivitetty"),
        "corrected": ("Korjattu", "Juttua on korjattu"),
        "withdrawn": ("Poistettu", "Juttu on poistettu"),
    }
    if kind not in labels:
        raise ValueError("Invalid article status kind")
    note = str(status.get("note") or "").strip()
    if not note or len(note) > 600:
        raise ValueError("Article status needs a bounded explanation")
    machine, visible = semantic_datetime(status.get("at"))
    short, heading = labels[kind]
    return (f'<section class="article-status article-status--{kind}" role="status">'
            f'<h2>{heading}</h2><p><strong>{short} '
            f'<time datetime="{esc(machine)}">{esc(visible)}</time>.</strong> {esc(note)}</p></section>')


def source_list_html(sources):
    """Only actual editorial evidence; reuse/mirror terms are rendered separately."""
    rows = []
    for index, source in enumerate(sources, 1):
        rows.append(
            f'<li id="lahde-{index}"><a href="{esc(source["url"])}" rel="noopener noreferrer">'
            f'{esc(source["publisher"])}: {esc(source["title"])}</a><br>'
            f'<small>Lähteen päiväys: {time_html(source["published_at"])}</small></li>'
        )
    return "".join(rows)


def reuse_rights_html(sources):
    """Distribution/text-reuse records are not additional editorial sources."""
    rows = []
    for source in sources:
        reuse = source.get("reuse")
        if not reuse:
            continue
        license_label = str(reuse.get("license") or "").strip() or "Käyttöehdot: lähdekohtaiset"
        body = (f'<strong>{esc(source["publisher"])}</strong>: '
                f'<a href="{esc(reuse["url"])}">{esc(license_label)}</a>. '
                f'{esc(reuse["changes"])}')
        if reuse.get("license_url"):
            terms_label = short_license_label(reuse["license_url"]) or license_label
            body += f' · <a href="{esc(reuse["license_url"])}">{esc(terms_label)}</a>'
        if reuse.get("notice"):
            body += f' · {esc(reuse["notice"])}'
        rows.append(f'<li>{body}</li>')
    if not rows:
        return ""
    return ('<section class="source-reuse"><h2>Jakelu ja tekstin käyttöehdot</h2>'
            '<p>Nämä tiedot kuvaavat jakelua tai tekstin käyttöä, eivät erillistä vahvistavaa lähdettä.</p>'
            f'<ul>{"".join(rows)}</ul></section>')


def article_actions_html(link, category, public, title=""):
    """Working reader actions with no unverified account or email destination."""
    reader_tools = ""
    if public:
        canonical = SITE_URL.rstrip("/") + link
        reader_tools = (
            f'<button class="article-save" type="button" data-save-url="{esc(canonical)}" '
            f'data-save-title="{esc(title)}" data-save-category="{esc(category_display(category))}" '
            'aria-pressed="false" aria-describedby="save-feedback">'
            '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
            'stroke-width="1.9" aria-hidden="true"><path d="M6 4h12v17l-6-4-6 4z"/></svg>'
            '<span>Tallenna</span></button>'
            f'<button class="article-share" type="button" data-share-url="{esc(canonical)}" '
            'aria-describedby="share-feedback">'
            '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
            'stroke-width="1.9" aria-hidden="true"><circle cx="18" cy="5" r="2.5"/>'
            '<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/>'
            '<path d="m8.2 10.8 7.6-4.5M8.2 13.2l7.6 4.5"/></svg>'
            '<span>Jaa tai kopioi linkki</span></button>'
            '<span id="save-feedback" class="article-action-feedback" aria-live="polite"></span>'
            '<span id="share-feedback" class="article-action-feedback" aria-live="polite"></span>')
    return ('<nav class="article-actions" aria-label="Jutun toiminnot">'
            '<div class="article-actions__primary">'
            f'<a class="article-section-return" href="{esc(category_route(category))}">'
            f'<span aria-hidden="true">←</span> Osaston uutiset: {esc(category_display(category))}</a>'
            f'{reader_tools}</div>'
            '<div class="article-actions__secondary">'
            + (f'<a class="article-latest-return" href="{LATEST_PATH}">Lue seuraavaksi tuoreimmat uutiset</a>' if public else '')
            + f'<a href="{ABOUT_PATH}#korjaukset">Korjauskäytäntö</a></div></nav>')


def listing_feed_html(items, empty_text, recovery_html="", featured=False):
    """Article rows with an optional, truthful newest-story feature treatment."""
    rows = []
    for index, (job, draft, link, date, fixture, image, image_url) in enumerate(items):
        modifier = "" if image else " portal-feed-item--no-image"
        if featured and index == 0:
            modifier += " portal-feed-item--featured"
        thumb = listing_image_slot(image, image_url, "portal-feed-item__thumb", link, draft["title"]) if image else ""
        rows.append(f'<article class="portal-feed-item{modifier}">'
                    f'<div class="portal-feed-item__body">'
                    + ('<span class="portal-feed-item__flag">Osaston uusin</span>'
                       if featured and index == 0 else '')
                    +
                    f'<p class="portal-feed-item__meta"><a href="{esc(category_route(draft.get("category")))}">'
                    f'{esc(category_display(draft.get("category")))}</a><span aria-hidden="true"> · </span>'
                    f'Julkaistu {time_html(job["created_at"], "portal-feed-item__time")}</p>'
                    f'<h2><a href="{link}">{esc(draft["title"])}</a></h2>'
                    f'<p>{esc(draft["summary"])}</p></div>{thumb}{fixture}</article>')
        if featured and index == 0 and len(items) > 1:
            rows.append('<div class="portal-list-feed__divider" role="heading" aria-level="2">'
                        '<span>Uutisarkisto</span><small>Uusimmasta vanhimpaan</small></div>')
    if not rows:
        return (f'<div class="portal-list-feed portal-list-feed--empty">'
                f'<p class="empty">{esc(empty_text)}</p>{recovery_html}</div>')
    modifier = " portal-list-feed--featured" if featured else ""
    return f'<div class="portal-list-feed{modifier}">{"".join(rows)}</div>'


def category_page_body(title, note, items, empty_text, page_number=1, page_count=1,
                       base_path=None, total_count=None, recovery_html="", featured=False):
    """Newspaper desk header and finite archive, with only the newest item featured."""
    slug = category_page_slug(title)
    modifier = f' portal-list-header--{esc(slug)}' if slug else ''
    total = len(items) if total_count is None else total_count
    count_label = "1 juttu" if total == 1 else f"{total} juttua"
    page_label = f" · sivu {page_number}/{page_count}" if page_count > 1 else ""
    pager = pagination_nav(page_number, page_count, base_path) if base_path else ""
    return (f'<div class="portal-list-page">'
            f'<header class="portal-list-header{modifier}"><p class="portal-list-header__eyebrow">Uutisosasto</p>'
            f'<div class="portal-list-header__title"><h1>{esc(title)}</h1>'
            f'<p class="archive-count">{esc(count_label + page_label)}</p></div><p>{esc(note)}</p></header>'
            f'{listing_feed_html(items, empty_text, recovery_html, featured=featured)}{pager}</div>')


def recovery_links_html():
    """Useful exits for a genuinely empty section; every target is always rendered."""
    links = [
        (LATEST_PATH, "Katso tuoreimmat uutiset"),
        ("/categories/kotimaa/", "Kotimaa"),
        ("/categories/ulkomaat/", "Ulkomaat"),
        ("/categories/talous/", "Talous"),
    ]
    return ('<nav class="empty-recovery" aria-label="Jatka muihin uutisiin"><h2>Jatka lukemista</h2><ul>'
            + "".join(f'<li><a href="{href}">{esc(label)}</a></li>' for href, label in links)
            + '</ul></nav>')


def sources_page_body():
    """The real editorial-method page linked from the shell footer."""
    return ('<div class="portal-list-page">'
            '<header class="portal-list-header"><h1>Lähteet ja toimitus</h1>'
            '<p>Uutisten lähteet, tarkistus ja kuvitusten käyttöoikeudet.</p></header>'
            '<div class="portal-list-feed">'
            '<section class="portal-feed-item"><div class="portal-feed-item__body">'
            '<h2>Alkuperäiset lähteet</h2>'
            '<p>Jokaisen uutisen varsinaiset uutislähteet näkyvät jutun yhteydessä suorina linkkeinä. '
            'Jakelupeilit ja tekstin käyttöehdot esitetään erikseen, eikä niitä lasketa riippumattomaksi vahvistukseksi.</p></div></section>'
            '<section class="portal-feed-item"><div class="portal-feed-item__body">'
            '<h2>Kuvat</h2>'
            '<p>Valokuvien tekijä, lähde ja käyttöoikeus ilmoitetaan artikkelin kuvan käyttöoikeudet -osiossa. '
            'Tekoälyllä tehtyjen kuvien alla artikkelissa lukee AI-generoitu kuva.</p></div></section>'
            '<section class="portal-feed-item"><div class="portal-feed-item__body">'
            '<h2>Automaattinen tuotanto</h2>'
            '<p>Uutiset laaditaan tekoälyn avulla ja tarkastetaan erillisessä automatisoidussa lähdetarkistuksessa. '
            'Järjestelmä voi silti tehdä virheitä. Prosessi, rajaukset ja korjauskäytäntö on kuvattu '
            f'<a href="{ABOUT_PATH}">Tietoa Uutistenlukijasta</a> -sivulla.</p></div></section>'
            '</div></div>')


def about_page_body():
    """Truthful service, process and correction policy without an unproved contact."""
    return ('<article class="story about-page">'
            '<h1>Tietoa Uutistenlukijasta</h1>'
            '<p>Uutistenlukija on automaattisesti tuotettu suomenkielinen uutispalvelu. '
            'Palvelun ylläpito vastaa teknisestä tuotannosta ja julkaisuprosessista. '
            'Sivusto ei väitä, että jutut olisivat nimetyn toimittajan kirjoittamia tai ihmisen ennakkotarkastamia.</p>'
            '<h2>Mitä palvelu kattaa</h2>'
            '<p>Palvelu kokoaa rajatun uutisvirran kelpuutetuista virallisista ja avoimista lähteistä. '
            'Se ei ole kattava uutistoimisto eikä lupaa seurata kaikkia aiheita, alueita tai näkökulmia.</p>'
            '<h2 id="prosessi">Miten juttu syntyy</h2>'
            '<ol><li>Lähdeaineisto kerätään kelpuutetusta lähteestä ja sidotaan tallennettuun lähdeosoitteeseen.</li>'
            '<li>Tekoäly laatii suomenkielisen luonnoksen vain tallennettujen lähdekatkelmien perusteella.</li>'
            '<li>Erillinen automatisoitu tarkistus vertaa väitteitä lähteisiin ja vaatii kappalekohtaiset viitteet.</li>'
            '<li>Kuva valitaan ja tarkistetaan erillisillä relevanssi- ja käyttöoikeussäännöillä.</li>'
            '<li>Julkaisu tapahtuu vain, jos lähde-, rakenne-, kuva- ja julkaisuportit hyväksyvät saman tallennetun version.</li></ol>'
            '<p>Automaatio ja lähteet voivat olla puutteellisia. Artikkelin lähteet, tuotantotiedot ja kuvan oikeudet '
            'auttavat arvioimaan yksittäistä juttua.</p>'
            '<h2 id="korjaukset">Korjaukset ja poistot</h2>'
            '<p>Vahvistettu olennainen korjaus merkitään juttuun päivämäärineen. Jos jutun julkaisemista ei voida enää '
            'perustella, sisältö voidaan korvata poistosta kertovalla ilmoituksella samalla osoitteella.</p>'
            '<p>Varmistettua yleisön yhteydenottokanavaa ei julkaista ennen kuin sen toimivuus on osoitettu. '
            'Sivulla ei siksi ole tällä hetkellä sähköpostiosoitetta tai yhteydenottolomaketta.</p>'
            '<h2>Prosessikuvaus</h2>'
            '<p>Versio 1.0 · tarkistettu 30.9.2026. Vanha juttu säilyttää siihen tallennetut lähde- ja '
            'tuotantotiedot, vaikka palvelun myöhempi prosessikuvaus muuttuisi.</p>'
            '</article>')


def homepage_topic_items(items, exclude_ids=None):
    """One newest unseen item per populated category in taxonomy order."""
    excluded = set(exclude_ids or ())
    latest = {}
    for item in items:
        job, draft = item[:2]
        if job.get("id") in excluded:
            continue
        slug = category_page_slug(draft.get("category"))
        if slug and slug not in latest:
            latest[slug] = item
    return [latest[slug] for slug, _display in CATEGORY_PAGES[:HOMEPAGE_TOPIC_LIMIT]
            if slug in latest]


def homepage_topic_strip(items, exclude_ids=None):
    """Render one native topic card per category from the already loaded archive.

    This deliberately consumes ``listing_items`` rather than fetching or inventing content. The
    first item in each taxonomy bucket is newest because the store is already newest-first. A
    fixed seven-card cap keeps the homepage render fast even when the archive grows.
    """
    cards = []
    labels = dict(CATEGORY_PAGES)
    for item in homepage_topic_items(items, exclude_ids):
        job, draft, link, date = item[:4]
        slug = category_page_slug(draft.get("category"))
        display = labels[slug]
        cards.append(
            f'<div class="portal-topic-card portal-topic-card--{esc(slug)}">'
            f'<a class="portal-topic-card__label" href="/categories/{esc(slug)}/">{esc(display)}</a>'
            f'<h3><a href="{link}">{esc(draft["title"])}</a></h3>'
            f'<span class="portal-topic-card__time">Julkaistu {time_html(job["created_at"])}</span>'
            f'</div>')
    if not cards:
        return ""
    return (f'<section class="portal-topic-strip" aria-labelledby="front-topics-title">'
            f'<div class="portal-module-head"><h2 id="front-topics-title">Osastot</h2>'
            f'<a href="{LATEST_PATH}">Kaikki uutiset</a></div>'
            f'<div class="portal-topic-strip__grid">{"".join(cards)}</div></section>')


def homepage_edition_html(page_items):
    """A compact edition identity grounded in the newest stored publication time."""
    latest = (f'<span>Viimeisin julkaisu {time_html(page_items[0][0]["created_at"])}</span>'
              if page_items else '<span>Ei vielä tarkastettuja uutisia</span>')
    return ('<header class="portal-edition" aria-labelledby="front-edition-title">'
            '<div class="portal-edition__title"><p>Uutistenlukija</p>'
            '<h1 id="front-edition-title">Uutiset nyt</h1></div>'
            f'<div class="portal-edition__meta">{latest}'
            '<nav aria-label="Etusivun oikopolut">'
            f'<a href="{LATEST_PATH}">Koko uutisvirta</a>'
            f'<a href="{SOURCES_PATH}">Lähteet</a><a href="/rss.xml">RSS</a></nav></div></header>')


def listing_page_html(page_items, page_number, page_count, archive_items=None, snapshot=None):
    """Rendered listing for one page in the portal theme.

    Page 1 is the homepage: one promoted lead, the first eight remaining stories
    as center teaser rows, the right rail, and every later story as a row in the
    river outside the top grid. Reviewed images use the theme's existing thumbnail
    slots; text-only stories keep the matching no-image variant. The lead paints
    eagerly with verified dimensions so its box is reserved before the bytes arrive.
    The homepage also carries the branch's bounded, archive-backed topic strip.
    """
    if not page_items:
        return '<p class="empty">Ei vielä tarkastettuja uutisluonnoksia.</p>'
    is_homepage = page_number == 1

    def row_category(draft):
        """Visible category label and colour slug, mapped without touching the draft.

        ``Maailma`` is shown to readers as ``Ulkomaat`` and takes the native
        ``ulkomaat`` colour slug. The mapping lives only in rendered markup, so
        reviewed drafts keep the category value they were reviewed with.
        """
        display = str(draft["category"])
        if display.strip() == "Maailma":
            display = "Ulkomaat"
        return esc(display), esc(category_slug(display))

    def teaser_row(item):
        job, draft, link, date, fixture, image, image_url = item[:7]
        category, slug = row_category(draft)
        modifier = "" if image else " portal-teaser--no-image"
        thumb = listing_image_slot(image, image_url, "portal-teaser__thumb", link, draft["title"]) if image else ""
        return (f'<article class="portal-teaser{modifier}">{thumb}<div>'
                f'<div class="portal-teaser__meta">'
                f'<span class="portal-kicker portal-teaser__category portal-teaser__category--{slug}">{category}</span>'
                f'<span>Julkaistu {time_html(job["created_at"])}</span></div>'
                f'<h3><a href="{link}">{esc(draft["title"])}</a></h3></div>'
                f'{fixture}</article>')

    def river_row(item):
        """River row: use its native thumbnail slot when a reviewed image exists."""
        job, draft, link, date, fixture, image, image_url = item[:7]
        category, slug = row_category(draft)
        modifier = "" if image else " portal-row-card--no-image"
        thumb = listing_image_slot(image, image_url, "portal-row-card__thumb", link, draft["title"]) if image else ""
        return (f'<article class="portal-row-card{modifier}">{thumb}<div>'
                f'<div class="portal-row-card__meta">'
                f'<span class="portal-kicker portal-row-card__category portal-row-card__category--{slug}">{category}</span>'
                f'<span class="portal-row-card__time">Julkaistu {time_html(job["created_at"])}</span></div>'
                f'<h3><a href="{link}">{esc(draft["title"])}</a></h3></div>'
                f'{fixture}</article>')

    lead_html = ""
    rows = []
    river_rows = []
    if is_homepage:
        job, draft, link, date, fixture, image, image_url = page_items[0]
        category, slug = row_category(draft)
        figure_html = homepage_image_figure(image, image_url, lazy=False) if image else ""
        lead_classes = "portal-lead lead-story" + ("" if image else " lead-story--text-only")
        minutes = reading_time_minutes(draft)
        lead_html = (f'<article class="{lead_classes}">{figure_html}'
                     f'<div class="portal-lead__body">'
                     f'<span class="portal-kicker portal-lead__category portal-lead__category--{slug}">{category}</span>'
                     f'<a class="portal-lead__time" href="{link}">Uusin juttu · julkaistu '
                     f'{time_html(job["created_at"])}</a>'
                     f'<h2 id="front-lead-title"><a href="{link}">{esc(draft["title"])}</a></h2>'
                     f'<p>{esc(draft["summary"])}</p>{fixture}'
                     f'<div class="portal-meta-row">'
                     f'<a class="portal-save-link" href="{link}" aria-label="Lue juttu: {esc(draft["title"])}">Lue juttu</a>'
                     f'<span>{minutes} min lukuaika</span>'
                     f'</div></div></article>')
        rows = [teaser_row(item) for item in page_items[1:1 + HOMEPAGE_CENTER_ROWS]]
        river_rows = [river_row(item) for item in page_items[1 + HOMEPAGE_CENTER_ROWS:]]
    else:
        rows = [teaser_row(item) for item in page_items]
    if not is_homepage:
        return "".join(rows) + pagination_nav(page_number, page_count)
    center = (f'<div class="portal-center-list" aria-labelledby="front-top-stories-title">'
              f'<div class="portal-mobile-section-head"><span>Juuri nyt</span>'
              f'<h2 id="front-top-stories-title">Pääuutiset</h2></div>'
              f'{"".join(rows)}</div>') if rows else ""
    rail = ('<aside class="portal-right-rail" aria-label="Sivupalkki">'
            '<section class="portal-newsletter"><h2>Seuraa uutisia</h2>'
            '<p>Lisää syötteen osoite omaan RSS-lukijaasi, niin uudet jutut tulevat samaan paikkaan.</p>'
            '<a href="/rss.xml">RSS-syöte</a>'
            '<p class="portal-rss-address">https://uutistenlukija.fi/rss.xml</p>'
            '<button type="button" class="portal-rss-copy" data-rss-copy-url="https://uutistenlukija.fi/rss.xml" '
            'aria-describedby="rss-copy-feedback" hidden>Kopioi syötteen osoite</button>'
            '<p id="rss-copy-feedback" class="portal-rss-feedback" role="status" aria-live="polite"></p></section>'
            + frontpage.markets(snapshot) + '</aside>')
    grid_label = ' aria-labelledby="front-lead-title"' if lead_html else ""
    grid_class = "portal-front-grid"
    if is_homepage and page_items[0][5] is None:
        grid_class += " portal-front-grid--image-free-lead"
    grid = f'<section class="{grid_class}"{grid_label}>{lead_html}{center}{rail}</section>'
    river = ""
    if river_rows:
        river = (f'<section class="portal-river" aria-labelledby="front-latest-title">'
                 f'<div class="portal-module-head"><div><span class="portal-module-head__eyebrow">Uusimmasta vanhimpaan</span>'
                 f'<h2 id="front-latest-title">Lisää uutisia</h2></div>'
                 f'<a href="{LATEST_PATH}">Avaa koko arkisto</a></div>'
                 f'<div class="portal-river__grid">{"".join(river_rows)}</div></section>')
    archive = archive_items if archive_items is not None else page_items
    # A discovery card is additional only when inventory outside this homepage page
    # supports it. This prevents lead/supporting/river repetition without shortening
    # the chronological page itself.
    topics = homepage_topic_strip(archive, {item[0].get("id") for item in page_items})
    return grid + topics + river


def article_path(job):
    """Readable slug URL; the job id remains the stable suffix identity."""
    return "uutiset/" + slugs.article_slug(job["id"], _job_title(job)) + "/"


def _job_title(job):
    """Best-effort headline for slug derivation; never fails the render."""
    try:
        draft = job["draft"]
        if isinstance(draft, (str, bytes)):
            draft = json.loads(draft)
        if not isinstance(draft, dict):
            # Jobs with a NULL/unparsed draft (e.g. intake that failed before the
            # writer ran) still need a slug; fall back to id-only identity.
            return ""
        return draft.get("title", "") or ""
    except (ValueError, TypeError, KeyError, AttributeError):
        return ""


def asset_url(assets, name):
    """Stable content version: returning browsers must not mix release assets."""
    source = ROOT / ('cutover' if name == 'analytics.js' else 'static') / name
    version = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    return f'/{assets}/{name}?v={version}'


def page(title, body, canonical_path=None, head_meta="", readability_present=True, canonical=True,
         snapshot=None, active_section=None):
    """Full public page shell. `canonical_path` alone selects the public build.

    `canonical=False` keeps the public shell (public assets and the consent/privacy
    UI) but drops the canonical link, for a public page that must not claim a URL of
    its own; such a page is served noindex like a private preview, but without the
    private-preview banner and without the private asset paths.
    """
    public = canonical_path is not None
    # Only a page that owns its URL gets a canonical link; public pages that must not
    # claim one (the 404 body) keep the public shell but stay noindex.
    head = (f'<link rel="canonical" href="https://uutistenlukija.fi{esc(canonical_path)}">'
            if public and canonical else '<meta name="robots" content="noindex,nofollow">')
    # Public pages advertise the RSS feed so readers and aggregators can find it.
    if public:
        head += '<link rel="alternate" type="application/rss+xml" title="Uutistenlukija" href="/rss.xml">'
    # `head_meta` carries the description/OG/JSON-LD block for public pages; private
    # previews stay noindex and get none of it.
    head += head_meta if public else ""
    assets = "mvp-assets" if public else "assets"
    # The imported portal theme keeps its original sheet links and order; the assets
    # root then carries the small compatibility layer render_site writes, and the
    # reading-quality layer comes last so it can only add.
    sheet_names = ("css/style.css", "css/homepage-polish.css", "css/article.css",
                   "css/category.css", "css/category-hero.css", "css/empty-state.css",
                   "css/search.css", "css/portal-overhaul.css")
    style_links = "".join(f'<link rel="stylesheet" href="{asset_url(assets, name)}">' for name in sheet_names)
    style_links += f'<link rel="stylesheet" href="{asset_url(assets, "style.css")}">'
    if readability_present:
        style_links += f'<link rel="stylesheet" href="{asset_url(assets, "style-readability.css")}">'
    banner = "" if public else '<div class="preview">Yksityinen esikatselu · ei julkaistu</div>'
    consent = ((ROOT / "static/consent.html").read_text() if public else "")
    if public:
        for name in ('analytics.js', 'consent.js'):
            consent = consent.replace(f'/{assets}/{name}', asset_url(assets, name))
    # Public pages link their privacy notice and RSS feed; the private preview has
    # neither, so it must not advertise pages that were never published.
    if public:
        footer_tagline = 'Uutistenlukija · automaattisesti tuotettu suomenkielinen uutispalvelu.'
        footer_columns = ('<div class="site-footer-col"><h3>Uutiset</h3><ul class="site-footer-links">'
                          f'<li><a href="{LATEST_PATH}">Tuoreimmat uutiset</a></li>'
                          '<li><a href="/categories/kotimaa/">Kotimaa</a></li>'
                          '<li><a href="/categories/ulkomaat/">Ulkomaat</a></li>'
                          '<li><a href="/categories/talous/">Talous</a></li></ul></div>'
                          '<div class="site-footer-col"><h3>Palvelu</h3><ul class="site-footer-links">'
                          f'<li><a href="{ABOUT_PATH}">Tietoa Uutistenlukijasta</a></li>'
                          f'<li><a href="{SOURCES_PATH}">Lähteet ja tuotantotapa</a></li>'
                          '<li><a href="/ai-kuvat/">AI-kuvien käyttöehdot</a></li>'
                          f'<li><a href="{PRIVACY_PATH}">Tietosuoja</a></li>'
                          '<li><a href="/rss.xml">RSS-syöte</a></li></ul>'
                          '<button class="site-footer-consent-button" id="consent-settings" '
                          'data-consent-settings type="button">Evästeasetukset</button></div>')
    else:
        footer_tagline = "Tämä paikallinen versio on tarkastelua varten."
        footer_columns = ('<div class="site-footer-col"><h3>Toimitus</h3>'
                          '<p>Lähteet ja toimitus julkaistaan sivuston mukana.</p></div>'
                          '<div class="site-footer-col"><h3>Tietoa</h3>'
                          '<p>Tietosuoja ja RSS-syöte julkaistaan sivuston mukana.</p></div>')
    # The public brand links home; the private preview must not advertise a published
    # destination it does not have, so there the brand is plain text.
    footer_brand = (f'<a class="site-footer-brand" href="/" aria-label="Uutistenlukija etusivulle">'
                    f'<img src="/{assets}/images/logo.png" alt="Uutistenlukija" '
                    f'class="site-footer-brand__image" loading="lazy" decoding="async" '
                    f'width="977" height="191"></a>' if public else
                    '<div class="site-footer-brand"><h2>Uutistenlukija</h2></div>')
    labels_by_slug = dict(CATEGORY_PAGES)
    nav_items = (("/", "Etusivu"),) + tuple(
        (f"/categories/{slug}/", labels_by_slug[slug]) for slug in PRIMARY_CATEGORY_SLUGS
    ) + ((LATEST_PATH, "Tuoreimmat"),)
    nav_link_items = []
    current_section = active_section or canonical_path
    for href, label in nav_items:
        aria_current = ' aria-current="page"' if current_section == href else ""
        nav_link_items.append(f'<li><a href="{href}"{aria_current}>{esc(label)}</a></li>')
    nav_links = "".join(nav_link_items)
    section_links = []
    for slug, label in CATEGORY_PAGES:
        href = f"/categories/{slug}/"
        aria_current = ' aria-current="page"' if current_section == href else ""
        section_links.append(f'<li><a href="{href}"{aria_current}>{esc(label)}</a></li>')
    theme_icons = ('<svg class="theme-icon theme-icon--dark" xmlns="http://www.w3.org/2000/svg" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/></svg>'
                   '<svg class="theme-icon theme-icon--light" xmlns="http://www.w3.org/2000/svg" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>')
    theme_button = (f'<button id="theme-toggle" data-theme-toggle="header" class="portal-icon-button theme-toggle-btn" type="button" aria-label="Vaihda teema" aria-pressed="false">{theme_icons}</button>')
    menu_theme_button = (f'<button id="theme-toggle-menu" data-theme-toggle="menu" class="theme-toggle-btn" type="button" aria-label="Vaihda teema" aria-pressed="false">{theme_icons}<span>Vaihda teema</span></button>')
    saved_button = ('<button class="portal-action portal-action--desktop portal-saved-toggle" '
                    'data-saved-toggle type="button" aria-haspopup="dialog" '
                    'aria-controls="saved-stories-dialog">Tallennetut '
                    '<span class="saved-count" data-saved-count aria-label="0 tallennettua juttua">0</span></button>'
                    if public else '')
    menu_saved_button = ('<li class="saved-menu-item"><button class="menu-saved-toggle" '
                         'data-saved-toggle type="button" aria-haspopup="dialog" '
                         'aria-controls="saved-stories-dialog">Tallennetut '
                         '<span class="saved-count" data-saved-count aria-label="0 tallennettua juttua">0</span>'
                         '</button></li>' if public else '')
    full_menu = ('<div class="menu-directory" aria-label="Koko valikko">'
                 '<div class="menu-directory__head"><strong>Valikko</strong>'
                 '<button id="menu-close" class="menu-close" type="button">Sulje valikko</button></div>'
                 '<div class="menu-directory__group"><p class="menu-directory__title">Osastot</p><ul>'
                 + "".join(section_links) + f'<li><a href="{OPPAAT_PATH}">Oppaat</a></li></ul></div>'
                 '<div class="menu-directory__group"><p class="menu-directory__title">Palvelu</p><ul>'
                 f'<li><a href="{LATEST_PATH}">Tuoreimmat</a></li>'
                 f'<li><a href="{ABOUT_PATH}">Tietoa Uutistenlukijasta</a></li>'
                 f'<li><a href="{ABOUT_PATH}#korjaukset">Korjauskäytäntö</a></li>'
                 f'<li><a href="{SOURCES_PATH}">Lähteet ja tuotantotapa</a></li>'
                 + ('<li><a href="/rss.xml">RSS-syöte</a></li>' if public else '') + '</ul></div>'
                 '<div class="menu-directory__group"><p class="menu-directory__title">Asetukset</p><ul>'
                 f'<li class="theme-menu-item">{menu_theme_button}</li>'
                 + menu_saved_button
                 + ('<li><button class="menu-consent-settings" data-consent-settings type="button">Evästeasetukset</button></li>' if public else '')
                 + '</ul></div></div>')
    saved_dialog = ('<dialog id="saved-stories-dialog" class="saved-stories" aria-labelledby="saved-stories-title">'
                    '<div class="saved-stories__inner"><div class="saved-stories__head">'
                    '<div><span class="saved-stories__eyebrow">Tällä laitteella</span>'
                    '<h2 id="saved-stories-title">Tallennetut jutut</h2></div>'
                    '<button class="saved-stories__close" data-saved-close type="button" aria-label="Sulje tallennetut jutut">Sulje</button>'
                    '</div><p class="saved-stories__note">Tallennukset säilyvät vain tämän selaimen omassa muistissa.</p>'
                    '<p id="saved-stories-empty" class="saved-stories__empty">Et ole vielä tallentanut juttuja.</p>'
                    '<ul id="saved-stories-list" class="saved-stories__list"></ul></div></dialog>'
                    if public else '')
    return f'''<!doctype html>
<html lang="fi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
{head}<title>{esc(title)} · Uutistenlukija</title>
{style_links}</head><body>
<a class="skip skip-to-content" href="#sisalto">Siirry sisältöön</a>
{banner}
<header class="site-header" role="banner">
<div class="portal-masthead">
<a class="portal-logo" href="/" aria-label="Uutistenlukija etusivulle"><img src="/{assets}/images/logo.png" alt="Uutistenlukija" class="portal-logo__image" loading="eager" decoding="async" width="977" height="191"></a>
<div id="header-search" class="portal-search site-search site-search--collapsed">
<button id="header-search-toggle" class="portal-icon-button search-toggle-btn" type="button" aria-label="Avaa haku" aria-expanded="false" aria-controls="header-search-form"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-4.2-4.2"/></svg><span class="visually-hidden">Haku</span></button>
<form id="header-search-form" class="site-search__form" action="{esc(SEARCH_ACTION)}" method="get" role="search" aria-label="Etsi uutisia" aria-describedby="header-search-note">
<label class="site-search__label" for="header-search-input">Hae sivustolta Googlesta</label>
<input id="header-search-input" class="site-search__input" type="search" name="q" placeholder="Hae sivustolta Googlesta" autocomplete="off">
<input type="hidden" name="sitesearch" value="{esc(SEARCH_SITE)}">
<button class="site-search__submit" type="submit" aria-label="Hae Googlesta"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-4.2-4.2"/></svg></button>
</form>
<p id="header-search-note" class="search-note">Tulokset avautuvat Googlen sivulla. Haku on rajattu sivustoon {esc(SEARCH_SITE)}.</p>
</div>
<div class="portal-actions" aria-label="Pikatoiminnot">
{frontpage.weather(snapshot)}
<a class="portal-action portal-action--desktop" href="{SOURCES_PATH}">Lähteet</a>
{saved_button}
{theme_button}
<button id="hamburger" class="portal-icon-button hamburger-btn" type="button" aria-label="Avaa valikko" aria-expanded="false" aria-controls="main-nav-menu"><svg class="portal-menu-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg><span class="portal-mobile-label">Valikko</span></button>
</div>
</div>
<nav class="main-nav" id="main-nav-menu" aria-label="Päävalikko"><ul class="main-nav__primary">{nav_links}</ul>{full_menu}</nav>
</header>
<main class="container" id="sisalto" tabindex="-1">{body}</main>
<footer class="site-footer" role="contentinfo" aria-label="Sivuston alatunniste">
<div class="container">
<div class="site-footer-grid">
<div class="site-footer-col site-footer-brand-col">{footer_brand}<p class="site-footer-slogan">Selkeä suomenkielinen uutispalvelu.</p></div>
{footer_columns}
</div>
</div>
<div class="site-footer-copyright"><div class="container"><p>{footer_tagline}</p></div></div>
</footer>
{consent}
{saved_dialog}
{frontpage.data_script(snapshot)}
<script src="{asset_url(assets, 'portal.js')}" defer></script>
</body></html>'''


# The one place search is offered: Google, scoped to this site by default. The hidden
# field is a fixed default scope, never caller text, and the visible label says plainly
# which engine opens. No other search endpoint is advertised.
SEARCH_ACTION = "https://www.google.com/search"
SEARCH_SITE = "uutistenlukija.fi"
# Callers may name the archive listing the old link most plausibly belonged to. Only the
# exact paths the renderer itself writes are accepted, so nothing else can be linked.
ARCHIVE_PATH_RE = re.compile(r"/sivu/([0-9]+)/\Z")


def archive_page_path(archive_path="/"):
    """The caller-supplied listing path if it is a real page, else the homepage.

    Only "/" and "/sivu/<n>/" with n >= 2 and no leading zero are archive pages the
    renderer writes; anything else is a bug in the caller and is rejected instead of
    being rendered as a link readers cannot use.
    """
    value = "/" if archive_path is None else archive_path
    if isinstance(value, str) and value == "/":
        return value
    match = ARCHIVE_PATH_RE.fullmatch(value) if isinstance(value, str) else None
    if match and match.group(1)[0] != "0" and int(match.group(1)) >= 2:
        return value
    raise ValueError(f"Invalid archive path: {archive_path!r}")


def search_form_html():
    """Site-scoped Google search form with an explicit Finnish label.

    The query input is user-visible and escaped. The hidden `sitesearch` field only
    sets the default site scope for the search; it does not stop a reader from changing
    that scope. Submitting opens Google's own search results page; nothing on this site
    pretends to search.
    """
    return ('<form id="missing-search-form" class="search" action="' + esc(SEARCH_ACTION) + '" method="get" role="search" aria-label="Etsi uutisia" aria-describedby="missing-search-note">'
            '<label for="missing-search-input">Hae uutisia Googlesta. Haku on rajattu sivustoon uutistenlukija.fi.</label>'
            '<input type="search" id="missing-search-input" name="q" placeholder="Etsi uutisia">'
            '<input type="hidden" name="sitesearch" value="' + esc(SEARCH_SITE) + '">'
            '<button type="submit">Hae Googlesta</button>'
            '<p id="missing-search-note" class="search-note visually-hidden">Haku avautuu Googlen omalla sivulla.</p></form>')


def missing_page(archive_path="/"):
    """Public 404 body for URLs this site no longer serves.

    The copy says plainly that the page is missing and the old link may be stale, then
    points at routes that do exist: the newest listing, the caller-named archive page
    when there is one, and a site-scoped Google search. It renders through the ordinary
    public page shell, so the assets and consent/privacy UI are the same as every other
    public page.
    """
    archive = archive_page_path(archive_path)
    if archive == "/":
        archive_link = ""
        destinations = "uusimmat uutiset ja haku"
    else:
        number = esc(archive.split("/")[2])
        archive_link = f'<li><a href="{esc(archive)}">Arkiston sivu {number}</a></li>'
        destinations = "uusimmat uutiset, arkiston sivu {0} ja haku".format(number)
    body = f'''<section class="intro missing"><h1>Sivua ei löytynyt</h1>
<p>Tätä osoitetta ei löytynyt. Vanha linkki voi viitata sisältöön, jota ei enää julkaista.</p>
<p>Voit jatkaa täältä: {destinations}.</p>
<ul class="missing-links"><li><a href="/">Siirry uusimpiin uutisiin</a></li>{archive_link}</ul>
{search_form_html()}</section>'''
    return page("Sivua ei löytynyt", body, "/404.html", canonical=False)


def render_paginated_archive(output_dir, base_path, items, heading, page_title, note,
                             empty_text, public, snapshot=None, active_section=None,
                             recovery_html="", featured=False):
    """Write one finite category/latest archive and remove only retired page children."""
    # Call the shared path validator before deriving a filesystem location. These
    # values are renderer-owned constants, but keeping the boundary explicit makes
    # it impossible for a future caller to turn a URL into path traversal.
    paginated_listing_path(base_path, 1)
    if not re.fullmatch(r"/(?:[a-z0-9-]+/)+", base_path):
        raise ValueError("Invalid archive base path")
    output_dir = Path(output_dir)
    archive_root = output_dir.joinpath(*base_path.strip("/").split("/"))
    pages = [items[offset:offset + PAGE_SIZE]
             for offset in range(0, len(items), PAGE_SIZE)] or [[]]
    page_count = len(pages)
    prune_stale_paginated_children(archive_root / "sivu", page_count)
    for page_number, page_items in enumerate(pages, 1):
        path = paginated_listing_path(base_path, page_number)
        title = page_title if page_number == 1 else f"{page_title} – sivu {page_number}"
        body = category_page_body(
            heading, note, page_items, empty_text,
            page_number=page_number, page_count=page_count, base_path=base_path,
            total_count=len(items), recovery_html=recovery_html,
            featured=featured and page_number == 1,
        )
        head_meta = (homepage_head_meta(
            page_items, path=path, page_title=title,
            start_position=(page_number - 1) * PAGE_SIZE + 1,
        ) if public else "")
        relative = (archive_root / "index.html" if page_number == 1
                    else archive_root / "sivu" / str(page_number) / "index.html")
        atomic_write(relative, page(
            title, body, path if public else None, head_meta=head_meta,
            snapshot=snapshot, active_section=active_section,
        ))
    return page_count


def render_site(store, output_dir, state_dir=None, public=False, include_ids=None, verify_policy_ids=None, snapshot=None):
    jobs = [j for j in store.articles() if include_ids is None or j["id"] in include_ids]
    assets = "mvp-assets" if public else "assets"
    # Re-check stored decisions before writing any page; source-derived HTML is always escaped.
    articles = []
    amendments = {}
    from .release_contract import AMENDMENT_RELEASE, check_article, media
    for job in jobs:
        packet, draft, review = (json.loads(job[k]) for k in ("packet", "draft", "review"))
        if packet.get("schema") == AMENDMENT_RELEASE:
            # The composite remains the authentication object. Only this local view is
            # shaped like an ordinary packet for established rendering/scoring helpers.
            binding = media(packet, draft, policy_gate=True)
            envelope = packet["final_review_input"]["source_packet"]
            metadata = binding["amendment"]["public_metadata"]
            predecessor = envelope["preparation"]["predecessor"]["job"]
            predecessor_link = "/" + article_path(predecessor)
            current_link = "/" + article_path(job)
            if (job["id"] != binding["amendment"]["job_id"] or
                    job["id"] != predecessor["id"] or
                    job["created_at"] != predecessor["created_at"] or
                    metadata.get("datePublished") != predecessor["created_at"] or
                    metadata.get("canonical") != SITE_URL.rstrip("/") + predecessor_link or
                    current_link != predecessor_link):
                raise ValueError("Amendment predecessor/public identity mismatch")
            notice = metadata.get("notice")
            if (not isinstance(notice, dict) or
                    notice.get("at") != metadata.get("dateModified")):
                raise ValueError("Amendment notice/dateModified mismatch")
            sources = []
            for citation in envelope["preparation"]["citations"]:
                source = deepcopy(citation["capture_source"])
                source["id"] = citation["id"]
                sources.append(source)
            render_packet = {
                "sources": sources,
                "image": deepcopy(envelope["final_image"]),
                "article_status": deepcopy(notice),
            }
            validate_draft(draft, render_packet)
            if review != packet["final_review_result"]["review"]:
                raise ValueError("Amendment row review differs from combined review")
            amendments[job["id"]] = (packet, metadata["canonical"])
            packet = render_packet
        else:
            # Amendment-shaped packets never fall through as ordinary records when
            # their required marker is missing or unsupported.
            if any(key in packet for key in ("preparation_json", "capture_json",
                                             "final_review_input", "final_review_result",
                                             "version")):
                media(packet, draft)
            validate_draft(draft, packet)
            if public:
                # The policy gate is a PUBLISH-time check: it binds a packet to the policy in force
                # when it is released, via an exact policy digest. Re-running it for articles that
                # were already released against an earlier policy would fail every historical page,
                # so adding a source would brick the whole archive and block all future publishing.
                # verify_policy_ids names the articles being published now; those get the full gate.
                # Everything else is already bound to its captured bytes by verify_intake at release
                # time, and is re-checked structurally by validate_draft above.
                if verify_policy_ids is None or job["id"] in verify_policy_ids:
                    media(packet, draft)
                else:
                    media(packet, draft, policy_gate=False)
        if public and not display_image(draft.get('image')):
            raise ValueError('Published article requires a reviewed relevant image')
        validate_review(review, draft)
        if not review["approved"]:
            raise ValueError("Unapproved record cannot be rendered")
        articles.append((job, packet, draft, review))
    validate_round1_related_text_pins(articles)
    # Listing cards are collected while the article pages are written, then split into
    # pages of at most PAGE_SIZE stories. Page 1 promotes its newest story to a lead
    # (the lead counts toward that page's 30); later pages need no promoted lead.
    listing_items = []
    output_dir = Path(output_dir)
    # "Lue myös": evidence-based links only. A quota never creates unrelated filler.
    related_for = {}
    duplicate_ids = duplicate_story_ids(articles)
    for job, packet, draft, _review in articles:
        scored = []
        for position, (candidate_job, candidate_packet, candidate_draft, _candidate_review) in enumerate(articles):
            if candidate_job["id"] == job["id"] or candidate_job["id"] in duplicate_ids:
                continue
            score = related_story_score(packet, draft, candidate_packet, candidate_draft)
            if score >= 4:
                scored.append((score, position, candidate_job, candidate_draft))
        scored.sort(key=lambda item: (-item[0], item[1]))
        related_for[job["id"]] = [(candidate_job, candidate_draft)
                                  for _score, _position, candidate_job, candidate_draft in scored[:3]]
    for job, packet, draft, review in articles:
        link = "/" + article_path(job)
        _machine_date, date = semantic_datetime(job["created_at"])
        fixture = '<p class="fixture">Testiaineisto: keksitty uutinen, ei oikea julkaisu.</p>' if packet.get("fixture") else ""
        source_numbers = {s["id"]: i + 1 for i, s in enumerate(packet["sources"])}
        paragraphs = "".join('<p>' + _paragraph_text_html(link, p, packet["sources"]) +
                             ' <span class="citations">' +
                             " ".join(f'<a href="#lahde-{source_numbers[s]}">[{source_numbers[s]}]</a>' for s in p["source_ids"]) +
                             '</span></p>' for p in draft["paragraphs"])
        source_list = source_list_html(packet["sources"])
        reuse_rights = reuse_rights_html(packet["sources"])
        image = display_image(draft.get("image"))
        image_url = resolved_image_url(image, state_dir, output_dir, assets) if image else None
        # A missing image is allowed only in the private draft preview.
        figure = article_hero_figure(image, image_url) if image else ""
        image_note = "" if image else '<p class="image-note">Ei kuvaa: tekstiversion yksityinen esikatselu.</p>'
        image_rights = image_rights_html(image)
        picks = reviewed_related_picks(job, related_for[job["id"]])
        related_ids = {related_job["id"] for related_job, _related_draft in picks}
        related_html = ""
        if picks:
            related_items = "".join(related_story_html(j, d, state_dir, output_dir, assets) for j, d in picks)
            related_html = f'<section class="related"><h2>Lue myös</h2><ul>{related_items}</ul></section>'
        # Method disclosure: states plainly how the text was made and names the source
        # publishers it was checked against, without inventing an editor or any metrics.
        publishers = []
        for source in packet["sources"]:
            name = str(source.get("publisher") or "").strip()
            if name and name not in publishers:
                publishers.append(name)
        publisher_list = ", ".join(esc(name) for name in publishers)
        method_line = ('<section class="article-production"><h2>Tuotantotiedot</h2>'
                       '<p>Teksti on tuotettu tekoälyn avulla ja tarkastettu erillisessä '
                       'lähdetarkistuksessa. Lähdetarkistus ja julkaisuportit ovat automatisoituja; '
                       'sivusto ei väitä jutun olevan ihmisen ennakkotarkistama.'
                       + (f' Lähdetietojen julkaisijat: {publisher_list}.' if publisher_list else "")
                       + f' <a href="{ABOUT_PATH}#prosessi">Lue tuotantoprosessista</a>.</p></section>')
        breadcrumb = (f'<nav class="article-breadcrumb" aria-label="Murupolku"><ol>'
                      f'<li><a href="/">Etusivu</a></li>'
                      f'<li><a href="{esc(category_route(draft["category"]))}">{esc(category_display(draft["category"]))}</a></li>'
                      f'<li aria-current="page">Juttu</li></ol></nav>')
        status_data = packet.get("article_status")
        status = article_status_html(status_data)
        withdrawn = isinstance(status_data, dict) and status_data.get("kind") == "withdrawn"
        if status_data is not None and timestamp(status_data["at"]) < timestamp(job["created_at"]):
            raise ValueError("Article status cannot predate publication")
        source_count = len(packet["sources"])
        source_label = "1 uutislähde" if source_count == 1 else f"{source_count} uutislähdettä"
        actions = article_actions_html(link, draft["category"], public, draft["title"])
        context = article_context_html(job, draft, articles, related_ids | duplicate_ids)
        reading = f'{figure}{image_note}<div class="content">{paragraphs}</div>'
        afterword = (f'<div class="article-afterword"><div class="article-evidence">'
                     f'<section class="sources"><h2>Lähteet</h2>'
                     f'<p class="source-count">{esc(source_label)}</p><ol>{source_list}</ol></section>'
                     f'{reuse_rights}{method_line}{image_rights}</div>{related_html}</div>')
        story_content = "" if withdrawn else (
            f'{actions}<div class="article-reading-grid"><div class="article-reading-main">'
            f'{reading}</div>{context}{afterword}</div>')
        if withdrawn:
            story_content = f'{actions}'
        deck = "" if withdrawn else f'<p class="lead">{esc(draft["summary"])}</p>'
        reading_time = (f'<span class="article-reading-time">{reading_time_minutes(draft)} min lukuaika</span>'
                        if not withdrawn else "")
        body = f'''<article class="story single-article">{breadcrumb}{fixture}
<h1>{esc(draft["title"])}</h1>
<p class="article-meta" data-category="{esc(draft["category"])}"><span>{"Luonnos · " if not public else ""}Julkaistu {time_html(job["created_at"])}</span>{reading_time}</p>
{status}{deck}{story_content}</article>'''
        # --- SEO metadata ---------------------------------------------------
        # Built only for the public build; the private preview stays noindex.
        head_meta = ""
        if public:
            paragraph_text = [p["text"] for p in draft["paragraphs"]]
            description = seo.meta_description(draft["summary"], paragraph_text)
            image_for_meta = image_url or None
            published_iso = timestamp(job["created_at"]).astimezone(timezone.utc).isoformat()
            modified_iso = published_iso
            if isinstance(status_data, dict) and status_data.get("kind") in ("updated", "corrected"):
                modified_iso = timestamp(status_data["at"]).astimezone(timezone.utc).isoformat()
            head_meta = seo.article_head(
                seo.meta_title(draft["title"]),
                description,
                link,
                image_url=image_for_meta,
                published=published_iso,
            ) + seo.news_article_jsonld(
                draft["title"],
                description,
                link,
                published=published_iso,
                modified=modified_iso,
                category=draft.get("category"),
                image_url=image_for_meta,
                sources=packet["sources"],
            )
        rendered_page = page(draft["title"], body, link if public else None, head_meta=head_meta,
                             snapshot=snapshot, active_section=category_route(draft["category"]))
        amendment = amendments.get(job["id"])
        if public and amendment is not None:
            original_packet, canonical = amendment
            check_article(rendered_page, original_packet, draft, canonical=canonical)
        atomic_write(output_dir / article_path(job) / "index.html", rendered_page)
        if job["id"] not in duplicate_ids and not withdrawn:
            listing_items.append((job, draft, link, date, fixture, image, image_url))
    pages = [listing_items[offset:offset + PAGE_SIZE] for offset in range(0, len(listing_items), PAGE_SIZE)] or [[]]
    page_count = len(pages)
    # A render with fewer stories must not leave its retired archive pages behind.
    prune_stale_listing_pages(output_dir, page_count)
    for page_number, page_items in enumerate(pages, 1):
        path = listing_page_path(page_number)
        page_title = "Uusimmat uutiset" if page_number == 1 else f"Uusimmat uutiset – sivu {page_number}"
        listing = listing_page_html(
            page_items, page_number, page_count,
            archive_items=listing_items if page_number == 1 else None, snapshot=snapshot)
        if page_number == 1:
            body = homepage_edition_html(page_items) + listing
        else:
            body = f'<section class="intro"><h1>{esc(page_title)}</h1></section>{listing}'
        # JSON-LD/OG describe this page's own slice and URL; the private preview keeps none.
        head_meta = homepage_head_meta(page_items, path=path, page_title=page_title,
                                       start_position=(page_number - 1) * PAGE_SIZE + 1) if public else ""
        listing_path = "index.html" if page_number == 1 else f"sivu/{page_number}/index.html"
        atomic_write(output_dir / listing_path, page(
            page_title, body, path if public else None, head_meta=head_meta,
            snapshot=snapshot, active_section="/" if page_number == 1 else LATEST_PATH,
        ))
    # Category, latest and guides pages share the reviewed listing items: no story is
    # re-fetched, and an empty category says so honestly instead of hiding itself.
    for slug, display in CATEGORY_PAGES:
        items = [item for item in listing_items
                 if category_page_slug(item[1].get("category")) == slug]
        path = f"/categories/{slug}/"
        title = f"{display} – uutiset"
        render_paginated_archive(
            output_dir, path, items, display, title,
            f"Uusimmat {display.lower()}-aiheet.",
            "Ei vielä tarkastettuja uutisia tässä kategoriassa.",
            public, snapshot=snapshot, active_section=path,
            recovery_html=recovery_links_html(),
            featured=True,
        )
    latest_path = LATEST_PATH
    latest_title = "Tuoreimmat uutiset"
    render_paginated_archive(
        output_dir, latest_path, listing_items, "Tuoreimmat", latest_title,
        "Kaikki tarkastetut uutiset uusimmasta vanhimpaan.",
        "Ei vielä tarkastettuja uutisia.", public, snapshot=snapshot,
        active_section=LATEST_PATH, recovery_html=recovery_links_html(),
    )
    guides_title = "Oppaat"
    guides_items = guides_listing_items(listing_items)
    guides_note = guides_description(guides_items)
    guides_body = category_page_body("Oppaat", guides_note,
                                     guides_items, "Oppaita ei ole vielä julkaistu.",
                                     recovery_html=recovery_links_html())
    guides_body += (
        '<section class="portal-list-page" aria-labelledby="oppaat-lisaa-title">'
        '<header class="portal-list-header">'
        '<p class="portal-list-header__eyebrow">'
        'Linkki kaupungin palvelusivulle – ei Uutistenlukijan uutisjuttu.</p>'
        '<div class="portal-list-header__title">'
        '<h2 id="oppaat-lisaa-title">Lisää syyslomatekemistä</h2></div>'
        '<p>Oulu: kaupungin Fiilis-sivulle on koottu lasten ja nuorten toimintaa '
        'syyslomalle 19.–23.10.2026. Tarkista tapahtumien ikärajat, hinnat ja '
        'ilmoittautuminen kaupungin sivulta.</p>'
        '<p class="empty-recovery"><a href="https://www.ouka.fi/fiilis" rel="noopener noreferrer">'
        'Oulun kaupungin syyslomatoiminta</a></p>'
        '<p class="portal-list-header__eyebrow">'
        'Linkki kaupungin ohjelmakoosteeseen – ei Uutistenlukijan uutisjuttu.</p>'
        '<p>Turku: kaupungin ohjelmakoosteessa on tekemistä lasten ja nuorten syyslomalle '
        '12.–18.10.2026. Tarkista maksut, ikärajat ja ennakkovaraukset tapahtuman tiedoista.</p>'
        '<p class="empty-recovery"><a href="https://www.turku.fi/ajankohtaista/'
        'turussa-tapahtuu-syyslomalla-joka-paiva" rel="noopener noreferrer">'
        'Turun kaupungin syyslomaohjelma</a></p>'
        '<p class="portal-list-header__eyebrow">'
        'Linkki kaupungin ohjelmakoosteeseen – ei Uutistenlukijan uutisjuttu.</p>'
        '<p>Jyväskylän Lomalokki kokoaa syyslomatekemistä lapsille, nuorille ja perheille. '
        'Tarkista järjestäjän ohjelmasta ikärajat, hinnat ja ilmoittautuminen.</p>'
        '<p class="empty-recovery"><a href="https://www.jyvaskyla.fi/harrastukset/lomalokki" '
        'rel="noopener noreferrer">Jyväskylän kaupungin Lomalokki</a></p>'
        '</header></section>'
    )
    guides_meta = (homepage_head_meta(
        guides_items, path=OPPAAT_PATH, page_title=guides_title,
        description=guides_note,
    ) if public else "")
    atomic_write(output_dir / "oppaat/index.html",
                 page(guides_title, guides_body, OPPAAT_PATH if public else None, head_meta=guides_meta, snapshot=snapshot))
    sources_title = "Lähteet ja toimitus"
    atomic_write(output_dir / "lahteet/index.html",
                 page(sources_title, sources_page_body(), SOURCES_PATH if public else None, snapshot=snapshot))
    about_title = "Tietoa Uutistenlukijasta"
    atomic_write(output_dir / "tietoja/index.html",
                 page(about_title, about_page_body(), ABOUT_PATH if public else None, snapshot=snapshot))

    # Shell assets. The imported theme and everything it loads relatively is copied
    # byte-for-byte into the current assets namespace, so the CSS keeps resolving its
    # own nested images and the built site ships the exact audited bytes.
    static_root = ROOT / "static"
    for sheet in sorted((static_root / "css").glob("*.css")):
        atomic_write(output_dir / assets / "css" / sheet.name, sheet.read_bytes())
    for source_image in sorted((static_root / "images").rglob("*")):
        if source_image.is_file():
            relative = source_image.relative_to(static_root / "images")
            atomic_write(output_dir / assets / "images" / relative, source_image.read_bytes())
    atomic_write(output_dir / assets / "portal.js", (static_root / "portal.js").read_bytes())
    # Root /assets/style.css is the small compatibility layer (consent, skip/focus,
    # 44px controls) that loads after the imported theme sheets.
    atomic_write(output_dir / assets / "style.css", (static_root / "style.css").read_bytes())
    # Reading-quality layer, kept separate so the base design stays untouched.
    readability = static_root / "style-readability.css"
    if readability.exists():
        atomic_write(output_dir / assets / "style-readability.css", readability.read_bytes())
    if public:
        atomic_write(output_dir / assets / "analytics.js", (ROOT / "cutover/analytics.js").read_text())
        atomic_write(output_dir / assets / "consent.js", (ROOT / "static/consent.js").read_text())
        # IndexNow key file: proves site ownership to participating search engines.
        atomic_write(output_dir / indexing.key_name(), indexing.INDEXNOW_KEY)
    # RSS feed: a standard discovery surface for readers and aggregators, built from the
    # same reviewed records as the pages. Newest first (articles order).
    feed_items = []
    for job, draft, _link, _date, _fixture, _image, _image_url in listing_items:
        item_link = "https://uutistenlukija.fi/" + article_path(job)
        feed_items.append(
            '<item><title>' + esc(draft["title"]) + '</title><link>' + esc(item_link) +
            '</link><guid isPermaLink="true">' + esc(item_link) + '</guid><pubDate>' +
            format_datetime(timestamp(job["created_at"])) + '</pubDate><description>' +
            esc(draft["summary"]) + '</description></item>')
    feed = ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
            '<title>Uutistenlukija</title><link>https://uutistenlukija.fi/</link>'
            '<description>Selkeä suomenkielinen uutispalvelu.</description><language>fi</language>'
            + "".join(feed_items) + '</channel></rss>')
    atomic_write(output_dir / "rss.xml", feed)
    store.mark_rendered([j["id"] for j, _, _, _ in articles])
    return len(articles)
