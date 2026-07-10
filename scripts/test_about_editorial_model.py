#!/usr/bin/env python3
"""Source contracts for the canonical About and editorial identity surfaces."""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = Path(os.environ["OPE347_PUBLIC_DIR"]) if os.environ.get("OPE347_PUBLIC_DIR") else None

EXPECTED_ABOUT = '''---
title: "Tietoja Uutistenlukijasta"
description: "Uutistenlukija.fi on tekoälyavusteinen uutispalvelu. Näin artikkelit syntyvät, lähteet ilmoitetaan ja virheistä voi ilmoittaa."
url: "/tietoja/"
layout: "page"
noindex: false
---

**Uutistenlukija.fi julkaisee tekoälyavusteisesti laadittuja suomenkielisiä uutisartikkeleita. Tavoitteena on auttaa lukijaa hahmottamaan ajankohtaisia tapahtumia selkeästi ja ohjata alkuperäisen journalismin äärelle.**

<h2 id="toimitustapa">Näin artikkelit syntyvät</h2>

Automaattinen järjestelmä seuraa valittujen kotimaisten ja kansainvälisten uutismedioiden julkisia syötteitä, tunnistaa päällekkäisiä aiheita ja kokoaa valitusta uutisesta lähdeaineiston. Aineistoa voidaan täydentää muilla julkisilla lähteillä.

Tekoäly laatii lähdeaineiston perusteella suomenkielisen artikkelin. Ennen julkaisua automaattiset tarkistukset arvioivat muun muassa lähdeaineiston riittävyyttä, tekstin rakennetta ja suomen kieltä sekä sitä, onko aihe jo julkaistu. Liian niukka, ristiriitainen tai tarkistuksia läpäisemätön aineisto voidaan hylätä. Tarkistukset vähentävät virheiden riskiä, mutta eivät poista sitä.

Artikkeleita ei lähtökohtaisesti tarkista ihminen yksitellen ennen automaattista julkaisua. Ihmisen vastuulla ovat palvelun omistus ja toimituksellisten linjausten hyväksyminen sekä mahdollisuus puuttua sisältöön. Sivuston ylläpito seuraa järjestelmän toimintaa, arvioi julkaisuja pistokokein ja voi korjata tai poistaa sisältöä.

Artikkeleissa käytetty yleisbyline ”Toimitus” tarkoittaa Uutistenlukijan automatisoitua toimitusprosessia. Se ei tarkoita, että nimetty ihmistoimittaja olisi kirjoittanut tai tarkistanut yksittäisen jutun.

## Lähteet

Uusissa artikkeleissa ilmoitamme pääasiallisen lähteen ja linkin alkuperäiseen julkaisuun. Lähdemerkintä ei välttämättä kata kaikkia taustoituksessa käytettyjä lähteitä. Kaikkien vanhempien artikkeleiden lähdetiedot eivät ole yhtä täydellisiä.

Uutistenlukijan artikkelit eivät korvaa alkuperäislähdettä. Erityisesti nopeasti muuttuvissa, terveydellisissä, oikeudellisissa tai taloudellisissa asioissa ajantasainen tieto kannattaa tarkistaa myös alkuperäisestä julkaisusta tai toimivaltaiselta viranomaiselta.

## Korjaukset ja yhteydenotto

Huomasitko virheen? Lähetä artikkelin linkki, virheellinen kohta ja mahdollinen korjaava lähde osoitteeseen **info@uutistenlukija.fi**. Tarkistamme ilmoituksen ja korjaamme olennaiset virheet. Samasta osoitteesta voi lähettää myös yleistä palautetta.

## Toimituksellinen riippumattomuus

Mainostajat, sponsorit tai muut kaupalliset kumppanit eivät vaikuta uutisaiheiden valintaan, käytettyihin lähteisiin, käsittelytapaan, juttujen järjestykseen, otsikoihin tai julkaisupäätöksiin.

Jos sivustolla julkaistaan mainontaa tai kaupallista yhteistyötä, se merkitään selvästi ja erotetaan uutisartikkeleista. Kaupallinen yhteistyö ei muuta uutisartikkeleiden lähde-, kirjoitus-, tarkistus- tai julkaisukriteerejä.
'''


class AboutEditorialModelTests(unittest.TestCase):
    def test_about_copy_matches_the_approved_contract_exactly(self) -> None:
        actual = (ROOT / "content/tietoja.md").read_text(encoding="utf-8")
        self.assertEqual(actual, EXPECTED_ABOUT)

    def test_duplicate_about_and_fictional_staff_sources_are_retired(self) -> None:
        retired_paths = (
            "content/tietoja/_index.md",
            "content/toimitus/_index.md",
            "data/writers.json",
            "layouts/_default/toimitus.html",
            "themes/uutistenlukija/layouts/_default/toimitus.html",
        )
        for relative in retired_paths:
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists())
        self.assertFalse((ROOT / "static/images/writers").exists())

    def test_regular_articles_use_the_shared_source_attribution(self) -> None:
        adapter = (ROOT / "layouts/partials/source-article-link.html").read_text(encoding="utf-8")
        shared = (ROOT / "layouts/partials/article-source-attribution.html").read_text(
            encoding="utf-8"
        )
        self.assertEqual(adapter.strip(), '{{ partial "article-source-attribution.html" . }}')
        self.assertIn("if and $sourceName $sourceUrl", shared)
        self.assertIn('href="{{ $sourceUrl }}"', shared)
        self.assertIn("{{ $sourceName }}", shared)
        self.assertNotIn("source_domain", shared)

    def test_structured_default_author_points_to_the_truthful_disclosure(self) -> None:
        json_ld = (ROOT / "layouts/partials/json-ld.html").read_text(encoding="utf-8")
        nav = (ROOT / "layouts/partials/site-nav-schema.html").read_text(encoding="utf-8")
        self.assertIn('tietoja/#toimitustapa', json_ld)
        self.assertNotIn('toimitus/', json_ld)
        self.assertIn('printf "%stietoja/"', nav)
        self.assertNotIn('printf "%stoimitus/"', nav)

    def test_worker_redirect_precedes_asset_fallback(self) -> None:
        worker = (ROOT / "static/_worker.js").read_text(encoding="utf-8")
        redirect_at = worker.index("const editorialSurfaceRedirect")
        assets_at = worker.index("return env.ASSETS.fetch(request)")
        self.assertLess(redirect_at, assets_at)
        self.assertIn("url.pathname = '/tietoja/'", worker)
        self.assertIn("url.hash = 'toimitustapa'", worker)

    def test_dark_source_link_uses_readable_text_token_and_underline(self) -> None:
        css = (ROOT / "themes/uutistenlukija/static/css/article.css").read_text(
            encoding="utf-8"
        )
        selector = '[data-theme="dark"] .source-attribution__link'
        block = css[css.index(selector) : css.index("/* ── end source attribution", css.index(selector))]
        self.assertNotIn(".single-article .source-attribution a {", css)
        self.assertIn("color: var(--text);", block)
        self.assertIn("text-decoration: underline;", block)
        self.assertIn("text-underline-offset: 2px;", block)


@unittest.skipUnless(PUBLIC_DIR, "set OPE347_PUBLIC_DIR to test rendered Hugo output")
class RenderedEditorialModelTests(unittest.TestCase):
    def read_public(self, relative: str) -> str:
        assert PUBLIC_DIR is not None
        return (PUBLIC_DIR / relative).read_text(encoding="utf-8", errors="replace")

    def test_about_is_one_clean_canonical_page(self) -> None:
        html = self.read_public("tietoja/index.html")
        required = (
            "Tietoja Uutistenlukijasta",
            "Artikkeleita ei lähtökohtaisesti tarkista ihminen yksitellen",
            "Kaikkien vanhempien artikkeleiden lähdetiedot eivät ole yhtä täydellisiä",
            "Korjaukset ja yhteydenotto",
            "Toimituksellinen riippumattomuus",
        )
        for needle in required:
            self.assertIn(needle, html)
        self.assertRegex(html, r'id="?toimitustapa"?')
        self.assertRegex(
            html,
            r'rel=canonical href="?https://uutistenlukija\.fi/tietoja/"?',
        )
        self.assertNotIn("Tässä kategoriassa ei ole vielä artikkeleita", html)
        for token in (
            "article-meta",
            "source-attribution",
            "article-end-note",
            "advertiser-cta",
            "related-articles",
            "author-box",
        ):
            self.assertNotRegex(
                html,
                rf'<[^>]+class=(?:"[^"]*\b{re.escape(token)}\b|[^\s>]*\b{re.escape(token)}\b)',
            )

    def test_fictional_surface_is_not_generated_or_indexed(self) -> None:
        assert PUBLIC_DIR is not None
        self.assertFalse((PUBLIC_DIR / "toimitus/index.html").exists())
        sitemap = self.read_public("sitemap.xml")
        self.assertIn("https://uutistenlukija.fi/tietoja/", sitemap)
        self.assertNotIn("https://uutistenlukija.fi/toimitus/", sitemap)
        worker = self.read_public("_worker.js")
        self.assertIn("url.hash = 'toimitustapa'", worker)

    def test_current_articles_render_source_only_with_complete_metadata(self) -> None:
        assert PUBLIC_DIR is not None
        sourced = None
        incomplete = None
        for path in sorted((ROOT / "content/posts").glob("*.md"), reverse=True):
            source = path.read_text(encoding="utf-8", errors="replace")
            source_name = re.search(r'^source_name:\s*["\']?(.+?)["\']?\s*$', source, re.M)
            source_url = re.search(r'^source_url:\s*["\']?(.+?)["\']?\s*$', source, re.M)
            rendered = PUBLIC_DIR / "posts" / path.stem / "index.html"
            if not rendered.exists():
                continue
            if source_name and source_url and sourced is None:
                sourced = (rendered, source_name.group(1).strip(), source_url.group(1).strip())
            if (not source_name or not source_url) and incomplete is None:
                incomplete = rendered
            if sourced and incomplete:
                break

        self.assertIsNotNone(sourced, "no rendered article with complete source metadata")
        self.assertIsNotNone(incomplete, "no rendered article with incomplete source metadata")
        rendered, source_name, source_url = sourced
        html = rendered.read_text(encoding="utf-8", errors="replace")
        self.assertIn("source-attribution", html)
        self.assertIn(source_name, html)
        self.assertIn(source_url, html)
        self.assertNotIn(
            "source-attribution",
            incomplete.read_text(encoding="utf-8", errors="replace"),
        )


if __name__ == "__main__":
    unittest.main()
