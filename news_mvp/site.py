"""Escaped static HTML from reviewed SQLite records. Private preview only."""
import html
import hashlib
import json
import re
from datetime import timezone
from email.utils import format_datetime
from pathlib import Path

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
HOMEPAGE_CENTER_ROWS = 8
HOMEPAGE_TOPIC_LIMIT = 7
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
        if provider == "unsplash":
            return (f'Photo by <a href="{esc(provenance["photographer_url"])}">{photographer}</a> '
                    f'on <a href="{photo_url}">Unsplash</a>')
        provider_label = {
            "pexels": "Pexels",
            "wikimedia": "Wikimedia Commons",
            "google": "Google Custom Search",
        }.get(provider, provider.title())
        return f'Photo by {photographer} on <a href="{photo_url}">{provider_label}</a>'
    return esc(image.get("credit", ""))


def image_size_attributes(image):
    """`width`/`height` (when known) and `decoding` attributes for an <img>."""
    dimensions = image_dimensions(image)
    size = f' width="{dimensions[0]}" height="{dimensions[1]}"' if dimensions else ""
    return size + ' decoding="async"'


def image_overlay_html(image, include_credit=True):
    """Reader-visible archive-photo labels and reviewed stock credit for a portal slot.

    Generated-image disclosure belongs below the image on the article page, never on
    homepage or listing thumbnails.
    """
    stock = bool(image.get("stock_provenance"))
    label_html = '<span class="portal-lead__image-label">Arkistokuva</span>' if stock else ""
    credit_html = ""
    if include_credit and stock:
        credit_html = f'<span class="portal-lead__credit">{image_credit_html(image)}</span>'
    return label_html + credit_html


def homepage_image_figure(image, image_url, lazy):
    """Homepage image wrapper for a reviewed image, sized like the article page.

    Only images below the fold are lazy-loaded, so the lead never delays its own
    paint. There are no srcset variants: exactly one reviewed asset is served.
    Generated illustrations carry no listing overlay or caption. Their disclosure is
    rendered beneath the hero on the article page. Stock photographs retain the reviewed
    linked credit and an ``Arkistokuva`` overlay.
    """
    loading = ' loading="lazy"' if lazy else ""
    return (f'<div class="portal-lead__image">'
            f'<img src="{esc(image_url)}" alt="{esc(image["alt"])}" '
            f'{image_size_attributes(image)}{loading} referrerpolicy="no-referrer">'
            f'{image_overlay_html(image)}</div>')


def listing_image_slot(image, image_url, slot, lazy=True):
    """Render one of the theme's existing thumbnail slots for a reviewed image."""
    loading = ' loading="lazy"' if lazy else ""
    return (f'<div class="{slot}">'
            f'<img src="{esc(image_url)}" alt="{esc(image["alt"])}" '
            f'{image_size_attributes(image)}{loading} referrerpolicy="no-referrer">'
            f'{image_overlay_html(image)}</div>')


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


def pagination_nav(page_number, page_count):
    """Prev/next anchors for one listing page, or "" when there is only one page.

    The links are real paths and the Finnish labels name the page they lead to. The
    first page has no previous link and the last page has no next link, so no anchor
    ever points at a page that does not exist.
    """
    if page_count <= 1:
        return ""
    links = []
    if page_number > 1:
        links.append(f'<a class="page-prev" rel="prev" href="{listing_page_path(page_number - 1)}" '
                     f'aria-label="Edellinen sivu: sivu {page_number - 1}">'
                     f'<span aria-hidden="true">←</span> Edellinen sivu</a>')
    links.append(f'<span class="page-current" aria-current="page">Sivu {page_number} / {page_count}</span>')
    if page_number < page_count:
        links.append(f'<a class="page-next" rel="next" href="{listing_page_path(page_number + 1)}" '
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


def homepage_head_meta(articles, path="/", page_title="Uusimmat uutiset", start_position=1):
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
        f'<meta name="description" content="{esc(HOME_DESCRIPTION)}">'
        f'<meta property="og:site_name" content="{esc(SITE_NAME)}">'
        f'<meta property="og:type" content="website">'
        f'<meta property="og:title" content="{esc(title)}">'
        f'<meta property="og:url" content="{esc(url)}">'
        f'<meta property="og:description" content="{esc(HOME_DESCRIPTION)}">'
        f'<meta name="twitter:card" content="{twitter_card}">'
        f'<meta name="twitter:title" content="{esc(title)}">'
        f'<meta name="twitter:description" content="{esc(HOME_DESCRIPTION)}">'
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
    sivu_dir = Path(output_dir) / "sivu"
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


def article_hero_figure(image, image_url):
    """Article hero with intrinsic dimensions and honest, quiet image disclosure."""
    caption = (f'<figcaption class="article-hero-caption">{esc(image["caption"])}</figcaption>'
               if image.get("generated") is True else "")
    return (f'<figure class="article-hero"><img src="{esc(image_url)}" alt="{esc(image["alt"])}" '
            f'{image_size_attributes(image)} referrerpolicy="no-referrer">'
            f'{image_overlay_html(image, include_credit=bool(image.get("stock_provenance")))}'
            f'{caption}</figure>')


def image_rights_html(image):
    """Image credit/caption/licence/source section, rendered next to the sources.

    A generated illustration shows the normalized reader credit "AI-kuvitus" and links
    its illustration terms; the stored record (including the model name) is untouched
    and stays internal. Stock photographs keep their stored credit, licence and source.
    """
    if not image:
        return ""
    caption = esc(image.get("caption", ""))
    if image.get("generated") is True:
        body = (f'{caption} AI-kuvitus · <a href="{esc(image["license_url"])}">'
                f'Kuvituskuvien käyttöehdot</a>')
    else:
        body = (f'{caption} {image_credit_html(image)} · '
                f'<a href="{esc(image["license_url"])}">{esc(image["license"])}</a> · '
                f'<a href="{esc(image["source_url"])}">Kuvan lähde</a>')
    return f'<section class="image-rights"><h2>Kuvan käyttöoikeudet</h2><p>{body}</p></section>'


def listing_feed_html(items, empty_text):
    """Text rows for a category/latest page in the native portal feed markup."""
    rows = []
    for job, draft, link, date, fixture, image, image_url in items:
        published = esc(timestamp(job["created_at"]).isoformat())
        modifier = "" if image else " portal-feed-item--no-image"
        thumb = listing_image_slot(image, image_url, "portal-feed-item__thumb") if image else ""
        rows.append(f'<article class="portal-feed-item{modifier}">'
                    f'<time class="portal-feed-item__time" datetime="{published}">{date}</time>'
                    f'<div class="portal-feed-item__body">'
                    f'<h3><a href="{link}">{esc(draft["title"])}</a></h3>'
                    f'<p>{esc(draft["summary"])}</p></div>{thumb}{fixture}</article>')
    if not rows:
        return f'<div class="portal-list-feed"><p class="empty">{esc(empty_text)}</p></div>'
    return f'<div class="portal-list-feed">{"".join(rows)}</div>'


def category_page_body(title, note, items, empty_text):
    """Native portal-list page: header plus a feed of text rows, never a card grid."""
    return (f'<div class="portal-list-page">'
            f'<header class="portal-list-header"><h1>{esc(title)}</h1><p>{esc(note)}</p></header>'
            f'{listing_feed_html(items, empty_text)}</div>')


def sources_page_body():
    """The real editorial-method page linked from the shell footer."""
    return ('<div class="portal-list-page">'
            '<header class="portal-list-header"><h1>Lähteet ja toimitus</h1>'
            '<p>Uutisten lähteet, tarkistus ja kuvitusten käyttöoikeudet.</p></header>'
            '<div class="portal-list-feed">'
            '<section class="portal-feed-item"><div class="portal-feed-item__body">'
            '<h2>Alkuperäiset lähteet</h2>'
            '<p>Jokaisen uutisen lähteet ja niihin liittyvät käyttöehdot näkyvät jutun yhteydessä. '
            'Teksti perustuu tarkastettuihin lähdekatkelmiin.</p></div></section>'
            '<section class="portal-feed-item"><div class="portal-feed-item__body">'
            '<h2>Kuvat</h2>'
            '<p>Valokuvien tekijä, lähde ja käyttöoikeus ilmoitetaan kuvan yhteydessä. '
            'Tekoälyllä tehdyt kuvitukset merkitään kuvituskuviksi.</p></div></section>'
            '<section class="portal-feed-item"><div class="portal-feed-item__body">'
            '<h2>Toimitus</h2>'
            '<p>Uutiset laaditaan tekoälyn avulla ja tarkastetaan erillisessä lähdetarkistuksessa. '
            'Epävarmaa tietoa ei julkaista.</p></div></section>'
            '</div></div>')


def homepage_topic_strip(items):
    """Render one native topic card per category from the already loaded archive.

    This deliberately consumes ``listing_items`` rather than fetching or inventing content. The
    first item in each taxonomy bucket is newest because the store is already newest-first. A
    fixed seven-card cap keeps the homepage render fast even when the archive grows.
    """
    latest = {}
    for item in items:
        draft = item[1]
        slug = category_page_slug(draft.get("category"))
        if slug and slug not in latest:
            latest[slug] = item
    cards = []
    for slug, display in CATEGORY_PAGES[:HOMEPAGE_TOPIC_LIMIT]:
        item = latest.get(slug)
        if item is None:
            continue
        job, draft, link, date = item[:4]
        published = esc(timestamp(job["created_at"]).isoformat())
        cards.append(
            f'<div class="portal-topic-card portal-topic-card--{esc(slug)}">'
            f'<a class="portal-topic-card__label" href="/categories/{esc(slug)}/">{esc(display)}</a>'
            f'<h3><a href="{link}">{esc(draft["title"])}</a></h3>'
            f'<time class="portal-topic-card__time" datetime="{published}">{esc(date)}</time>'
            f'</div>')
    if not cards:
        return ""
    return (f'<section class="portal-topic-strip" aria-labelledby="front-topics-title">'
            f'<div class="portal-module-head"><h2 id="front-topics-title">Aiheet</h2>'
            f'<a href="{LATEST_PATH}">Kaikki uutiset</a></div>'
            f'<div class="portal-topic-strip__grid">{"".join(cards)}</div></section>')


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
        published = esc(timestamp(job["created_at"]).isoformat())
        modifier = "" if image else " portal-teaser--no-image"
        thumb = listing_image_slot(image, image_url, "portal-teaser__thumb") if image else ""
        return (f'<article class="portal-teaser{modifier}">{thumb}<div>'
                f'<div class="portal-teaser__meta">'
                f'<span class="portal-kicker portal-teaser__category portal-teaser__category--{slug}">{category}</span>'
                f'<span>Julkaistu <time datetime="{published}">{date}</time></span></div>'
                f'<h3><a href="{link}">{esc(draft["title"])}</a></h3></div>'
                f'{fixture}</article>')

    def river_row(item):
        """River row: use its native thumbnail slot when a reviewed image exists."""
        job, draft, link, date, fixture, image, image_url = item[:7]
        category, slug = row_category(draft)
        published = esc(timestamp(job["created_at"]).isoformat())
        modifier = "" if image else " portal-row-card--no-image"
        thumb = listing_image_slot(image, image_url, "portal-row-card__thumb") if image else ""
        return (f'<article class="portal-row-card{modifier}">{thumb}<div>'
                f'<div class="portal-row-card__meta">'
                f'<span class="portal-kicker portal-row-card__category portal-row-card__category--{slug}">{category}</span>'
                f'<span class="portal-row-card__time">Julkaistu <time datetime="{published}">{date}</time></span></div>'
                f'<h3><a href="{link}">{esc(draft["title"])}</a></h3></div>'
                f'{fixture}</article>')

    lead_html = ""
    rows = []
    river_rows = []
    if is_homepage:
        job, draft, link, date, fixture, image, image_url = page_items[0]
        category, _slug = row_category(draft)
        published = esc(timestamp(job["created_at"]).isoformat())
        figure_html = homepage_image_figure(image, image_url, lazy=False) if image else ""
        lead_classes = "portal-lead lead-story" + ("" if image else " lead-story--text-only")
        minutes = reading_time_minutes(draft)
        lead_html = (f'<article class="{lead_classes}">{figure_html}'
                     f'<div class="portal-lead__body">'
                     f'<span class="portal-kicker">{category}</span>'
                     f'<a class="portal-lead__time" href="{link}">Uusin juttu · julkaistu '
                     f'<time datetime="{published}">{date}</time></a>'
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
              f'<div class="portal-mobile-section-head"><span>Etusivu</span>'
              f'<h2 id="front-top-stories-title">Uusimmat otsikot</h2></div>'
              f'{"".join(rows)}</div>') if rows else ""
    rail = ('<aside class="portal-right-rail" aria-label="Sivupalkki">'
            '<section class="portal-newsletter"><h2>Seuraa uutisia</h2>'
            '<p>Lue uusimmat jutut verkkosivulla tai seuraa RSS-syötettä.</p>'
            '<a href="/rss.xml">RSS-syöte</a></section>'
            + frontpage.markets(snapshot) + '</aside>')
    grid_label = ' aria-labelledby="front-lead-title"' if lead_html else ""
    grid_class = "portal-front-grid"
    if is_homepage and page_items[0][5] is None:
        grid_class += " portal-front-grid--image-free-lead"
    grid = f'<section class="{grid_class}"{grid_label}>{lead_html}{center}{rail}</section>'
    river = ""
    if river_rows:
        river = (f'<section class="portal-river" aria-labelledby="front-latest-title">'
                 f'<div class="portal-module-head"><h2 id="front-latest-title">Tuoreimmat</h2></div>'
                 f'<div class="portal-river__grid">{"".join(river_rows)}</div></section>')
    topics = homepage_topic_strip(archive_items if archive_items is not None else page_items)
    return grid + river + topics


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


def page(title, body, canonical_path=None, head_meta="", readability_present=True, canonical=True, snapshot=None):
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
        footer_tagline = ('Suomenkielinen uutispalvelu.<br><a href="/tietosuoja/">Tietosuoja</a> · '
                          '<a href="/lahteet/">Lähteet ja toimitus</a> · <a href="/rss.xml">RSS-syöte</a>')
        footer_columns = ('<div class="site-footer-col"><h3>Toimitus</h3><ul class="site-footer-links">'
                          '<li><a href="/lahteet/">Lähteet ja toimitus</a></li>'
                          '<li><a href="/">Uusimmat uutiset</a></li></ul></div>'
                          '<div class="site-footer-col"><h3>Tietoa</h3><ul class="site-footer-links">'
                          '<li><a href="/tietosuoja/">Tietosuoja</a></li>'
                          '<li><a href="/rss.xml">RSS-syöte</a></li></ul></div>')
    else:
        footer_tagline = "Tämä paikallinen versio on tarkastelua varten."
        footer_columns = ('<div class="site-footer-col"><h3>Toimitus</h3>'
                          '<p>Lähteet ja toimitus julkaistaan sivuston mukana.</p></div>'
                          '<div class="site-footer-col"><h3>Tietoa</h3>'
                          '<p>Tietosuoja ja RSS-syöte julkaistaan sivuston mukana.</p></div>')
    # The public brand links home; the private preview must not advertise a published
    # destination it does not have, so there the brand is plain text.
    footer_brand = ('<a class="site-footer-brand" href="/" aria-label="Uutistenlukija etusivulle">'
                    '<h2>Uutistenlukija</h2></a>' if public else
                    '<div class="site-footer-brand"><h2>Uutistenlukija</h2></div>')
    nav_items = (("/", "Etusivu"),) + tuple(
        (f"/categories/{slug}/", display) for slug, display in CATEGORY_PAGES
    ) + ((OPPAAT_PATH, "Oppaat"), (LATEST_PATH, "Tuoreimmat"))
    nav_link_items = []
    for href, label in nav_items:
        aria_current = " aria-current='page'" if canonical_path == href else ""
        nav_link_items.append(f'<li><a href="{href}"{aria_current}>{esc(label)}</a></li>')
    nav_links = "".join(nav_link_items)
    theme_icons = ('<svg class="theme-icon theme-icon--dark" xmlns="http://www.w3.org/2000/svg" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/></svg>'
                   '<svg class="theme-icon theme-icon--light" xmlns="http://www.w3.org/2000/svg" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>')
    theme_button = (f'<button id="theme-toggle" data-theme-toggle="header" class="portal-icon-button theme-toggle-btn" type="button" aria-label="Vaihda teema" aria-pressed="false">{theme_icons}</button>')
    menu_theme_button = (f'<button id="theme-toggle-menu" data-theme-toggle="menu" class="theme-toggle-btn" type="button" aria-label="Vaihda teema" aria-pressed="false">{theme_icons}<span>Vaihda teema</span></button>')
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
<label class="site-search__label" for="header-search-input">Hae uutisia Googlesta. Haku on rajattu sivustoon {esc(SEARCH_SITE)}.</label>
<input id="header-search-input" class="site-search__input" type="search" name="q" placeholder="Hae uutisia, aiheita tai yhtiöitä" autocomplete="off">
<input type="hidden" name="sitesearch" value="{esc(SEARCH_SITE)}">
<button class="site-search__submit" type="submit" aria-label="Hae Googlesta"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-4.2-4.2"/></svg></button>
</form>
<p id="header-search-note" class="search-note visually-hidden">Haku avautuu Googlen omalla sivulla.</p>
</div>
<div class="portal-actions" aria-label="Pikatoiminnot">
{frontpage.weather(snapshot)}
<a class="portal-action portal-action--desktop" href="{SOURCES_PATH}">Lähteet</a>
{theme_button}
<button id="hamburger" class="portal-icon-button hamburger-btn" type="button" aria-label="Avaa valikko" aria-expanded="false" aria-controls="main-nav-menu"><svg class="portal-menu-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg><span class="portal-mobile-label">Valikko</span></button>
</div>
</div>
<nav class="main-nav" id="main-nav-menu" aria-label="Päävalikko"><ul>{nav_links}<li class="theme-menu-item">{menu_theme_button}</li></ul></nav>
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


def render_site(store, output_dir, state_dir=None, public=False, include_ids=None, verify_policy_ids=None, snapshot=None):
    jobs = [j for j in store.articles() if include_ids is None or j["id"] in include_ids]
    assets = "mvp-assets" if public else "assets"
    # Re-check stored decisions before writing any page; source-derived HTML is always escaped.
    articles = []
    for job in jobs:
        packet, draft, review = (json.loads(job[k]) for k in ("packet", "draft", "review"))
        validate_draft(draft, packet)
        if public:
            if not display_image(draft.get('image')):
                raise ValueError('Published article requires a reviewed relevant image')
            # The policy gate is a PUBLISH-time check: it binds a packet to the policy in force
            # when it is released, via an exact policy digest. Re-running it for articles that
            # were already released against an earlier policy would fail every historical page,
            # so adding a source would brick the whole archive and block all future publishing.
            # verify_policy_ids names the articles being published now; those get the full gate.
            # Everything else is already bound to its captured bytes by verify_intake at release
            # time, and is re-checked structurally by validate_draft above.
            from .release_contract import media
            if verify_policy_ids is None or job["id"] in verify_policy_ids:
                media(packet, draft)
            else:
                media(packet, draft, policy_gate=False)
        validate_review(review, draft)
        if not review["approved"]:
            raise ValueError("Unapproved record cannot be rendered")
        articles.append((job, packet, draft, review))
    # Listing cards are collected while the article pages are written, then split into
    # pages of at most PAGE_SIZE stories. Page 1 promotes its newest story to a lead
    # (the lead counts toward that page's 30); later pages need no promoted lead.
    listing_items = []
    output_dir = Path(output_dir)
    # "Lue myös": newest-first links between rendered articles (same category preferred).
    # Gives readers somewhere to go next and gives crawlers a real internal link graph.
    related_for = {}
    for job, _, draft, _ in articles:
        others = [(j, d) for j, _, d, _ in articles if j["id"] != job["id"]]
        same = [x for x in others if x[1].get("category") == draft.get("category")]
        picks = same[:3]
        if len(picks) < 3:
            picks += [x for x in others if x not in same][:3 - len(picks)]
        related_for[job["id"]] = picks
    for job, packet, draft, review in articles:
        link = "/" + article_path(job)
        date = timestamp(job["created_at"]).strftime("%d.%m.%Y")
        fixture = '<p class="fixture">Testiaineisto: keksitty uutinen, ei oikea julkaisu.</p>' if packet.get("fixture") else ""
        source_numbers = {s["id"]: i + 1 for i, s in enumerate(packet["sources"])}
        paragraphs = "".join('<p>' + esc(p["text"]) + ' <span class="citations">' +
                             " ".join(f'<a href="#lahde-{source_numbers[s]}">[{source_numbers[s]}]</a>' for s in p["source_ids"]) +
                             '</span></p>' for p in draft["paragraphs"])
        source_list = "".join(f'<li id="lahde-{i}"><a href="{esc(s["url"])}" rel="noopener noreferrer">{esc(s["publisher"])}: {esc(s["title"])}</a><br><small>Lähteen päiväys: {esc(s["published_at"])}</small></li>'
                              for i, s in enumerate(packet["sources"], 1))
        for source in packet["sources"]:
            reuse = source.get("reuse")
            if reuse:
                # The stored license string is the only authority for the label on both the
                # source link and its terms link; a link alone never implies a named licence.
                license_label = str(reuse.get("license") or "").strip() or "Käyttöehdot: lähdekohtaiset"
                source_list += f'<li>Lähde: {esc(source["publisher"])} · <a href="{esc(reuse["url"])}">{esc(license_label)}</a>. {esc(reuse["changes"])}</li>'
                if reuse.get('license_url'):
                    # Only the second (terms) link may show the standard short name, and
                    # only when the URL is the known CC BY 4.0 document itself.
                    terms_label = short_license_label(reuse["license_url"]) or license_label
                    source_list += f'<li><a href="{esc(reuse["license_url"])}">{esc(terms_label)}</a></li>'
                if reuse.get('notice'):
                    source_list += f'<li>{esc(reuse["notice"])}</li>'
        image = display_image(draft.get("image"))
        image_url = None
        # A missing image is allowed only in the private draft preview.
        figure = ""
        image_note = "" if image else '<p class="image-note">Ei kuvaa: tekstiversion yksityinen esikatselu.</p>'
        if image:
            image_url = image["url"]
            if image.get("local_path"):
                sha = image.get("sha256", "")
                if state_dir is None or not re.fullmatch(r"[0-9a-f]{64}", sha) or image["local_path"] != f"media/{sha}.jpg":
                    raise ValueError("Invalid local image identity")
                data = (Path(state_dir) / image["local_path"]).read_bytes()
                if hashlib.sha256(data).hexdigest() != sha:
                    raise ValueError("Local image does not match reviewed rights record")
                image_url = f"/{assets}/{sha}.jpg"
                atomic_write(output_dir / image_url.lstrip("/"), data)
            # Hero picture only: credit and licence terms render in the image-rights
            # section after the prose, next to the source list.
            figure = article_hero_figure(image, image_url)
        image_rights = image_rights_html(image)
        picks = related_for[job["id"]]
        related_html = ""
        if picks:
            related_items = "".join(f'<li><a href="/{article_path(j)}">{esc(d["title"])}</a></li>' for j, d in picks)
            related_html = f'<section class="related"><h2>Lue myös</h2><ul>{related_items}</ul></section>'
        # Method disclosure: states plainly how the text was made and names the source
        # publishers it was checked against, without inventing an editor or any metrics.
        publishers = []
        for source in packet["sources"]:
            name = str(source.get("publisher") or "").strip()
            if name and name not in publishers:
                publishers.append(name)
        publisher_list = ", ".join(esc(name) for name in publishers)
        method_line = ('<p>Teksti on tuotettu tekoälyn avulla ja tarkastettu erillisessä '
                       'lähdetarkistuksessa.' + (f' Lähdetietojen julkaisijat: {publisher_list}.' if publisher_list else "") + '</p>')
        badge = (f'<a class="category-label category-label--badge" '
                 f'href="{esc(category_route(draft["category"]))}">{esc(category_display(draft["category"]))}</a>')
        body = f'''<article class="story single-article"><a class="back" href="/">← Kaikki uutiset</a>{fixture}
{badge}<p class="eyebrow article-date" data-category="{esc(draft["category"])}">{"" if public else "Luonnos "}{date}</p><h1>{esc(draft["title"])}</h1>
{figure}<p class="lead">{esc(draft["summary"])}</p>{image_note}<div class="content">{paragraphs}</div>
{method_line}
<section class="sources"><h2>Lähteet</h2><ol>{source_list}</ol>
<p>Teksti on laadittu yllä mainittujen lähdekatkelmien perusteella. {"Kuvan käyttöoikeustiedot on esitetty alla." if image else "Uutisteksti esitetään ilman kuvaa."}</p></section>{image_rights}{related_html}</article>'''
        # --- SEO metadata ---------------------------------------------------
        # Built only for the public build; the private preview stays noindex.
        head_meta = ""
        if public:
            paragraph_text = [p["text"] for p in draft["paragraphs"]]
            description = seo.meta_description(draft["summary"], paragraph_text)
            image_for_meta = image_url or None
            published_iso = timestamp(job["created_at"]).astimezone(timezone.utc).isoformat()
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
                modified=published_iso,
                category=draft.get("category"),
                image_url=image_for_meta,
                sources=packet["sources"],
            )
        atomic_write(output_dir / article_path(job) / "index.html", page(draft["title"], body, link if public else None, head_meta=head_meta, snapshot=snapshot))
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
        intro_class = "intro homepage-intro visually-hidden" if page_number == 1 else "intro"
        body = f'''<section class="{intro_class}"><h1>{esc(page_title)}</h1></section>
{listing}'''
        # JSON-LD/OG describe this page's own slice and URL; the private preview keeps none.
        head_meta = homepage_head_meta(page_items, path=path, page_title=page_title,
                                       start_position=(page_number - 1) * PAGE_SIZE + 1) if public else ""
        listing_path = "index.html" if page_number == 1 else f"sivu/{page_number}/index.html"
        atomic_write(output_dir / listing_path, page(page_title, body, path if public else None, head_meta=head_meta, snapshot=snapshot))
    # Category, latest and guides pages share the reviewed listing items: no story is
    # re-fetched, and an empty category says so honestly instead of hiding itself.
    for slug, display in CATEGORY_PAGES:
        items = [item for item in listing_items
                 if category_page_slug(item[1].get("category")) == slug]
        path = f"/categories/{slug}/"
        title = f"{display} – uutiset"
        body = category_page_body(display, f"Uusimmat {display.lower()}-aiheet.", items,
                                 "Ei vielä tarkastettuja uutisia tässä kategoriassa.")
        head_meta = homepage_head_meta(items, path=path, page_title=title) if public else ""
        atomic_write(output_dir / f"categories/{slug}/index.html",
                     page(title, body, path if public else None, head_meta=head_meta, snapshot=snapshot))
    latest_path = LATEST_PATH
    latest_title = "Tuoreimmat uutiset"
    latest_body = category_page_body("Tuoreimmat", "Kaikki tarkastetut uutiset uusimmasta vanhimpaan.",
                                     listing_items, "Ei vielä tarkastettuja uutisia.")
    latest_meta = homepage_head_meta(listing_items, path=latest_path, page_title=latest_title) if public else ""
    atomic_write(output_dir / "tuoreimmat/index.html",
                 page(latest_title, latest_body, latest_path if public else None, head_meta=latest_meta, snapshot=snapshot))
    guides_title = "Oppaat"
    guides_body = category_page_body("Oppaat", "Toimitukselliset oppaat ja taustat.",
                                     [], "Oppaita ei ole vielä julkaistu.")
    guides_meta = homepage_head_meta([], path=OPPAAT_PATH, page_title=guides_title) if public else ""
    atomic_write(output_dir / "oppaat/index.html",
                 page(guides_title, guides_body, OPPAAT_PATH if public else None, head_meta=guides_meta, snapshot=snapshot))
    sources_title = "Lähteet ja toimitus"
    atomic_write(output_dir / "lahteet/index.html",
                 page(sources_title, sources_page_body(), SOURCES_PATH if public else None, snapshot=snapshot))

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
    for job, _, draft, _ in articles:
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
