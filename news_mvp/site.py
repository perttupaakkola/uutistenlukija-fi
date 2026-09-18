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


def esc(value):
    return html.escape(str(value), quote=True)


def atomic_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if isinstance(value, bytes):
        temporary.write_bytes(value)
    else:
        temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


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
    return f'''<!doctype html>
<html lang="fi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
{head}<title>{esc(title)} · Uutistenlukija</title>
<link rel="stylesheet" href="/{assets}/style.css">{extra_assets}</head><body>
<a class="skip" href="#sisalto">Siirry sisältöön</a>
{banner}
<header><a class="brand" href="/">Uutistenlukija<span>Uutiset selkeästi.</span></a>
<nav aria-label="Päänavigaatio"><a href="/">Uusimmat</a><a href="/#lahteet">Lähteet ja toimitus</a></nav></header>
<main id="sisalto">{body}</main>
<footer>Uutistenlukija · selkeä suomenkielinen uutispalvelu<br>{"Suomenkielinen uutispalvelu." if public else "Tämä paikallinen versio on tarkastelua varten."}</footer>{consent}
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
    cards = []
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
                source_list += f'<li>Lähde: {esc(source["publisher"])} · <a href="{esc(reuse["url"])}">{esc(reuse["license"])}</a>. {esc(reuse["changes"])}</li>'
                if reuse.get('license_url'):
                    source_list += f'<li><a href="{esc(reuse["license_url"])}">CC BY 4.0</a></li>'
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
            if image.get("generated") is True:
                figure = (f'<figure><img src="{esc(image_url)}" alt="{esc(image["alt"])}" '
                          f'referrerpolicy="no-referrer"><figcaption>{esc(image.get("caption", ""))} '
                          f'{esc(image["credit"])} · <a href="{esc(image["license_url"])}">'
                          f'Kuvituskuvien käyttöehdot</a></figcaption></figure>')
            else:
                figure = f'<figure><img src="{esc(image_url)}" alt="{esc(image["alt"])}" referrerpolicy="no-referrer"><figcaption>{esc(image.get("caption", ""))} {esc(image["credit"])} · <a href="{esc(image["license_url"])}">{esc(image["license"])}</a> · <a href="{esc(image["source_url"])}">Kuvan lähde</a></figcaption></figure>'
        picks = related_for[job["id"]]
        related_html = ""
        if picks:
            related_items = "".join(f'<li><a href="/{article_path(j)}">{esc(d["title"])}</a></li>' for j, d in picks)
            related_html = f'<section class="related"><h2>Lue myös</h2><ul>{related_items}</ul></section>'
        body = f'''<article class="story"><a class="back" href="/">← Kaikki uutiset</a>{fixture}
<p class="eyebrow" data-category="{esc(draft["category"])}">{esc(draft["category"])} · {"" if public else "Luonnos "}{date}</p><h1>{esc(draft["title"])}</h1>
<p class="lead">{esc(draft["summary"])}</p>{figure}<div class="story-body">{paragraphs}</div>
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
        cards.append(f'<article class="card"><p class="eyebrow" data-category="{esc(draft["category"])}">{esc(draft["category"])} · {date}</p><h2><a href="{link}">{esc(draft["title"])}</a></h2><p>{esc(draft["summary"])}</p>{fixture}<a class="read" href="{link}">Lue uutinen <span aria-hidden="true">→</span></a></article>')
    content = "".join(cards) or '<p class="empty">Ei vielä tarkastettuja uutisluonnoksia.</p>'
    body = f'''<section class="intro"><p class="eyebrow">Kotimaa ja maailma</p><h1>Ajankohtaista,<br>ymmärrettävästi.</h1><p>Uutiset, niiden tausta ja alkuperäiset lähteet samassa paikassa.</p></section>
<section aria-label="Uusimmat uutiset" class="grid">{content}</section>
<section id="lahteet" class="principles"><h2>Lähteet näkyviin.</h2><p>Selkeä suomi, perustellut väitteet ja avoimet lähdeviitteet. Epävarma tieto jätetään julkaisematta. {"Julkaisemme vain tarkastetut uutiset." if public else "Sivuston tämä versio sisältää vain yksityisiä luonnoksia."}</p></section>'''
    atomic_write(output_dir / "index.html", page("Uusimmat uutiset", body, "/" if public else None))
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
