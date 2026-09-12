"""Escaped static HTML from reviewed SQLite records. Private preview only."""
import html
import hashlib
import json
import re
from pathlib import Path

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
    return "uutiset/" + job["id"] + "/"


def page(title, body, canonical_path=None):
    public = canonical_path is not None
    head = (f'<link rel="canonical" href="https://uutistenlukija.fi{esc(canonical_path)}">' if public else '<meta name="robots" content="noindex,nofollow">')
    assets = "mvp-assets" if public else "assets"
    banner = "" if public else '<div class="preview">Yksityinen esikatselu · ei julkaistu</div>'
    consent = ((ROOT / "static/consent.html").read_text() if public else "")
    return f'''<!doctype html>
<html lang="fi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
{head}<title>{esc(title)} · Uutistenlukija</title>
<link rel="stylesheet" href="/{assets}/style.css"></head><body>
<a class="skip" href="#sisalto">Siirry sisältöön</a>
{banner}
<header><a class="brand" href="/">Uutistenlukija<span>Uutiset selkeästi.</span></a>
<nav aria-label="Päänavigaatio"><a href="/">Uusimmat</a><a href="/#lahteet">Lähteet ja toimitus</a></nav></header>
<main id="sisalto">{body}</main>
<footer>Uutistenlukija · selkeä suomenkielinen uutispalvelu<br>{"Suomenkielinen uutispalvelu." if public else "Tämä paikallinen versio on tarkastelua varten."}</footer>{consent}
</body></html>'''


def render_site(store, output_dir, state_dir=None, public=False, include_ids=None):
    jobs = [j for j in store.articles() if include_ids is None or j["id"] in include_ids]
    assets = "mvp-assets" if public else "assets"
    # Re-check stored decisions before writing any page; source-derived HTML is always escaped.
    articles = []
    for job in jobs:
        packet, draft, review = (json.loads(job[k]) for k in ("packet", "draft", "review"))
        validate_draft(draft, packet)
        if public and (packet.get("fixture") is not False or not draft.get("image", {}).get("local_path")):
            raise ValueError("Public release requires a real article and reviewed local image")
        validate_review(review, draft)
        if not review["approved"]:
            raise ValueError("Unapproved record cannot be rendered")
        articles.append((job, packet, draft, review))
    cards = []
    output_dir = Path(output_dir)
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
        image = draft.get("image")
        figure = ""
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
            figure = f'<figure><img src="{esc(image_url)}" alt="{esc(image["alt"])}" referrerpolicy="no-referrer"><figcaption>{esc(image.get("caption", ""))} {esc(image["credit"])} · <a href="{esc(image["license_url"])}">{esc(image["license"])}</a> · <a href="{esc(image["source_url"])}">Kuvan lähde</a></figcaption></figure>'
        body = f'''<article class="story"><a class="back" href="/">← Kaikki uutiset</a>{fixture}
<p class="eyebrow">{esc(draft["category"])} · {"" if public else "Luonnos "}{date}</p><h1>{esc(draft["title"])}</h1>
<p class="lead">{esc(draft["summary"])}</p>{figure}<div class="story-body">{paragraphs}</div>
<section class="sources"><h2>Lähteet</h2><ol>{source_list}</ol>
<p>Teksti on laadittu yllä mainittujen lähdekatkelmien perusteella. Lähteiden tiedot ja kuvan käyttöoikeus on tarkastettu.</p></section></article>'''
        atomic_write(output_dir / article_path(job) / "index.html", page(draft["title"], body, link if public else None))
        cards.append(f'<article class="card"><p class="eyebrow">{esc(draft["category"])} · {date}</p><h2><a href="{link}">{esc(draft["title"])}</a></h2><p>{esc(draft["summary"])}</p>{fixture}<a class="read" href="{link}">Lue uutinen <span aria-hidden="true">→</span></a></article>')
    content = "".join(cards) or '<p class="empty">Ei vielä tarkastettuja uutisluonnoksia.</p>'
    body = f'''<section class="intro"><p class="eyebrow">Kotimaa ja maailma</p><h1>Ajankohtaista,<br>ymmärrettävästi.</h1><p>Uutiset, niiden tausta ja alkuperäiset lähteet samassa paikassa.</p></section>
<section aria-label="Uusimmat uutiset" class="grid">{content}</section>
<section id="lahteet" class="principles"><h2>Lähteet näkyviin.</h2><p>Selkeä suomi, perustellut väitteet ja avoimet lähdeviitteet. Epävarma tieto jätetään julkaisematta. {"Julkaisemme vain tarkastetut uutiset." if public else "Sivuston tämä versio sisältää vain yksityisiä luonnoksia."}</p></section>'''
    atomic_write(output_dir / "index.html", page("Uusimmat uutiset", body, "/" if public else None))
    atomic_write(output_dir / assets / "style.css", (ROOT / "static/style.css").read_text())
    if public:
        atomic_write(output_dir / assets / "analytics.js", (ROOT / "cutover/analytics.js").read_text())
        atomic_write(output_dir / assets / "consent.js", (ROOT / "static/consent.js").read_text())
    store.mark_rendered([j["id"] for j, _, _, _ in articles])
    return len(articles)
