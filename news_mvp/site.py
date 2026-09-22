"""Escaped static HTML from reviewed SQLite records. Private preview only."""
import html
import hashlib
import json
import re
from datetime import timezone
from email.utils import format_datetime
from pathlib import Path

from . import indexing, seo, slugs
from .editorial import ROOT, digest, timestamp, validate_draft, validate_review


SITE_NAME = "Uutistenlukija"
SITE_URL = "https://uutistenlukija.fi/"
HOME_DESCRIPTION = "Uutiset, niiden tausta ja alkuperäiset lähteet samassa paikassa."
GENERATED_IMAGE_FALLBACK = (1536, 1024)
# Hard cap on stories per listing. Page 1 promotes its newest story to a lead, and
# that lead counts as one of the 30; later pages need no promoted lead.
PAGE_SIZE = 30
# Exact licence URLs whose short name is CC BY 4.0. Trailing-slash variants are
# the same canonical document, so they are normalised before matching.
CC_BY_40_URLS = frozenset({
    "https://creativecommons.org/licenses/by/4.0",
    "https://creativecommons.org/licenses/by/4.0/deed.fi",
})


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


def image_size_attributes(image):
    """`width`/`height` (when known) and `decoding` attributes for an <img>."""
    dimensions = image_dimensions(image)
    size = f' width="{dimensions[0]}" height="{dimensions[1]}"' if dimensions else ""
    return size + ' decoding="async"'


def homepage_image_figure(image, image_url, lazy):
    """Homepage <figure> for a reviewed image, sized like the article page.

    Only images below the fold are lazy-loaded, so the lead never delays its own
    paint. There are no srcset variants: exactly one reviewed asset is served.
    """
    loading = ' loading="lazy"' if lazy else ""
    credit = str(image.get("credit") or "").strip()
    if image.get("generated") is True:
        # "Kuvituskuva" is required: an illustration must never read as a photo.
        caption = "Kuvituskuva" + (f" · {esc(credit)}" if credit else "")
    else:
        text = " · ".join(part for part in (str(image.get("caption") or "").strip(), credit) if part)
        caption = esc(text)
    caption_html = f"<figcaption>{caption}</figcaption>" if caption else ""
    return (f'<figure class="card-image"><img src="{esc(image_url)}" alt="{esc(image["alt"])}" '
            f'{image_size_attributes(image)}{loading} referrerpolicy="no-referrer">'
            f'{caption_html}</figure>')


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
    metas = (
        f'<meta name="description" content="{esc(HOME_DESCRIPTION)}">'
        f'<meta property="og:site_name" content="{esc(SITE_NAME)}">'
        f'<meta property="og:type" content="website">'
        f'<meta property="og:title" content="{esc(title)}">'
        f'<meta property="og:url" content="{esc(url)}">'
        f'<meta property="og:description" content="{esc(HOME_DESCRIPTION)}">'
        f'<meta name="twitter:card" content="summary">'
        f'<meta name="twitter:title" content="{esc(title)}">'
        f'<meta name="twitter:description" content="{esc(HOME_DESCRIPTION)}">'
    )
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


def listing_page_html(page_items, page_number, page_count):
    """Rendered listing for one page: lead (page 1 only), grid cards and pager.

    Image rules keep the original intent: the lead paints immediately, the top few
    grid cards lazy-load, and verified dimensions keep every box reserved.
    """
    if not page_items:
        return '<p class="empty">Ei vielä tarkastettuja uutisluonnoksia.</p>'
    lead_html = ""
    cards = []
    for index, (job, draft, link, date, fixture, image, image_url) in enumerate(page_items):
        if page_number == 1 and index == 0:
            lead_figure = homepage_image_figure(image, image_url, lazy=False) if image else ""
            lead_class = "lead-story" if image else "lead-story lead-story--text-only"
            lead_html = (f'<article class="{lead_class}"><div class="lead-text">'
                         f'<p class="eyebrow" data-category="{esc(draft["category"])}">Uusin uutinen · {esc(draft["category"])} · {date}</p>'
                         f'<h2 class="lead-headline"><a href="{link}">{esc(draft["title"])}</a></h2>'
                         f'<p class="lead-summary">{esc(draft["summary"])}</p>{fixture}'
                         f'<a class="read" href="{link}">Lue uutinen <span aria-hidden="true">→</span></a></div>{lead_figure}</article>')
            continue
        card_figure = homepage_image_figure(image, image_url, lazy=True) if image and index <= 3 else ""
        cards.append(f'<article class="card"><p class="eyebrow" data-category="{esc(draft["category"])}">{esc(draft["category"])} · {date}</p><h2><a href="{link}">{esc(draft["title"])}</a></h2><p>{esc(draft["summary"])}</p>{fixture}{card_figure}<a class="read" href="{link}">Lue uutinen <span aria-hidden="true">→</span></a></article>')
    listing = lead_html
    if cards:
        section = f'<section aria-label="Muut uutiset" class="grid">{"".join(cards)}</section>'
        listing += section
    return listing + pagination_nav(page_number, page_count)


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


def page(title, body, canonical_path=None, head_meta="", readability_present=True):
    public = canonical_path is not None
    head = (f'<link rel="canonical" href="https://uutistenlukija.fi{esc(canonical_path)}">' if public else '<meta name="robots" content="noindex,nofollow">')
    # Public pages advertise the RSS feed so readers and aggregators can find it.
    if public:
        head += '<link rel="alternate" type="application/rss+xml" title="Uutistenlukija" href="/rss.xml">'
    # `head_meta` carries the description/OG/JSON-LD block for public pages; private
    # previews stay noindex and get none of it.
    head += head_meta if public else ""
    assets = "mvp-assets" if public else "assets"
    # Extra stylesheet links (readability layer), injected after the base sheet.
    extra_assets = f'<link rel="stylesheet" href="/{assets}/style-readability.css">' if readability_present else ""
    banner = "" if public else '<div class="preview">Yksityinen esikatselu · ei julkaistu</div>'
    consent = ((ROOT / "static/consent.html").read_text() if public else "")
    # Public pages link their privacy notice and RSS feed; the private preview has
    # neither, so it must not advertise pages that were never published.
    if public:
        footer_tagline = ('Suomenkielinen uutispalvelu.<br><a href="/tietosuoja/">Tietosuoja</a> · '
                          '<a href="/#lahteet">Lähteet ja toimitus</a> · <a href="/rss.xml">RSS-syöte</a>')
    else:
        footer_tagline = "Tämä paikallinen versio on tarkastelua varten."
    return f'''<!doctype html>
<html lang="fi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
{head}<title>{esc(title)} · Uutistenlukija</title>
<link rel="stylesheet" href="/{assets}/style.css">{extra_assets}</head><body>
<a class="skip" href="#sisalto">Siirry sisältöön</a>
{banner}
<header><a class="brand" href="/">Uutistenlukija<span>Uutiset selkeästi.</span></a>
<nav aria-label="Päänavigaatio"><a href="/">Uusimmat</a><a href="/#lahteet">Lähteet ja toimitus</a></nav></header>
<main id="sisalto">{body}</main>
<footer>Uutistenlukija · selkeä suomenkielinen uutispalvelu<br>{footer_tagline}</footer>{consent}
</body></html>'''


def render_site(store, output_dir, state_dir=None, public=False, include_ids=None, verify_policy_ids=None):
    jobs = [j for j in store.articles() if include_ids is None or j["id"] in include_ids]
    assets = "mvp-assets" if public else "assets"
    # Re-check stored decisions before writing any page; source-derived HTML is always escaped.
    articles = []
    for job in jobs:
        packet, draft, review = (json.loads(job[k]) for k in ("packet", "draft", "review"))
        validate_draft(draft, packet)
        if public:
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
        image = draft.get("image")
        image_url = None
        figure = "" if image else '<p class="image-note">Tämä uutinen julkaistaan ilman kuvaa.</p>' if public else '<p class="image-note">Ei kuvaa: tekstiversion yksityinen esikatselu.</p>'
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
            # A generated illustration must not claim a "source" - there is no source work. It
            # links to the illustration terms instead, and never presents itself as a photograph.
            img_attrs = image_size_attributes(image)
            if image.get("generated") is True:
                figure = (f'<figure><img src="{esc(image_url)}" alt="{esc(image["alt"])}" '
                          f'{img_attrs} referrerpolicy="no-referrer"><figcaption>{esc(image.get("caption", ""))} '
                          f'{esc(image["credit"])} · <a href="{esc(image["license_url"])}">'
                          f'Kuvituskuvien käyttöehdot</a></figcaption></figure>')
            else:
                figure = (f'<figure><img src="{esc(image_url)}" alt="{esc(image["alt"])}" '
                          f'{img_attrs} referrerpolicy="no-referrer"><figcaption>{esc(image.get("caption", ""))} '
                          f'{esc(image["credit"])} · <a href="{esc(image["license_url"])}">{esc(image["license"])}</a> '
                          f'· <a href="{esc(image["source_url"])}">Kuvan lähde</a></figcaption></figure>')
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
        body = f'''<article class="story"><a class="back" href="/">← Kaikki uutiset</a>{fixture}
<p class="eyebrow" data-category="{esc(draft["category"])}">{esc(draft["category"])} · {"" if public else "Luonnos "}{date}</p><h1>{esc(draft["title"])}</h1>
<p class="lead">{esc(draft["summary"])}</p>{figure}<div class="story-body">{paragraphs}</div>
{method_line}
<section class="sources"><h2>Lähteet</h2><ol>{source_list}</ol>
<p>Teksti on laadittu yllä mainittujen lähdekatkelmien perusteella. {"Kuvan käyttöoikeustiedot ovat kuvan yhteydessä." if image else "Uutisteksti esitetään ilman kuvaa."}</p></section>{related_html}</article>'''
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
        atomic_write(output_dir / article_path(job) / "index.html", page(draft["title"], body, link if public else None, head_meta=head_meta))
        listing_items.append((job, draft, link, date, fixture, image, image_url))
    pages = [listing_items[offset:offset + PAGE_SIZE] for offset in range(0, len(listing_items), PAGE_SIZE)] or [[]]
    page_count = len(pages)
    # A render with fewer stories must not leave its retired archive pages behind.
    prune_stale_listing_pages(output_dir, page_count)
    for page_number, page_items in enumerate(pages, 1):
        path = listing_page_path(page_number)
        page_title = "Uusimmat uutiset" if page_number == 1 else f"Uusimmat uutiset – sivu {page_number}"
        listing = listing_page_html(page_items, page_number, page_count)
        body = f'''<section class="intro"><h1>{esc(page_title)}</h1></section>
{listing}
<section id="lahteet" class="principles"><h2>Lähteet näkyviin.</h2><p>Selkeä suomi, perustellut väitteet ja avoimet lähdeviitteet. Epävarma tieto jätetään julkaisematta. {"Julkaisemme vain tarkastetut uutiset." if public else "Sivuston tämä versio sisältää vain yksityisiä luonnoksia."}</p></section>'''
        # JSON-LD/OG describe this page's own slice and URL; the private preview keeps none.
        head_meta = homepage_head_meta(page_items, path=path, page_title=page_title,
                                       start_position=(page_number - 1) * PAGE_SIZE + 1) if public else ""
        listing_path = "index.html" if page_number == 1 else f"sivu/{page_number}/index.html"
        atomic_write(output_dir / listing_path, page(page_title, body, path if public else None, head_meta=head_meta))
    atomic_write(output_dir / assets / "style.css", (ROOT / "static/style.css").read_text())
    # Reading-quality layer, kept separate so the base design stays untouched.
    readability = ROOT / "static/style-readability.css"
    if readability.exists():
        atomic_write(output_dir / assets / "style-readability.css", readability.read_text())
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
