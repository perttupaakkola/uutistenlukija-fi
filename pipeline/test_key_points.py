#!/usr/bin/env python3
"""Reproducible key-points verification harness.

Builds 5 representative article fixtures, normalizes key_points the same way as the
pipeline, renders Hugo markdown front matter, and validates that:
- exactly 3 key points are stored
- combined key-point length stays <= 300 chars
- publisher writes key_points into front matter
"""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path


# Allow importing pipeline.rewriter without the real OpenAI package during tests.
if "openai" not in sys.modules:
    fake_openai = types.ModuleType("openai")

    class OpenAI:  # pragma: no cover - test shim only
        def __init__(self, *args, **kwargs):
            pass

    fake_openai.OpenAI = OpenAI
    sys.modules["openai"] = fake_openai

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "pipeline"))

from publisher import _article_to_markdown  # noqa: E402
from rewriter import _normalize_key_points  # noqa: E402

FIXTURES = [
    {
        "title": "Hallitus kiristää budjettikuria keväällä",
        "summary": "Hallitus valmistelee uusia säästöjä ja veroratkaisuja kevään kehysriiheen.",
        "description": "Valtiovarainministeriö arvioi, että päätöksillä haetaan useiden satojen miljoonien eurojen vaikutusta.",
        "content": """Hallitus valmistelee kevään kehysriiheen uusia toimia, joilla julkista taloutta pyritään vahvistamaan nopeasti. Ministeriöt käyvät läpi menoeriä, verotusta ja investointeja samaan aikaan, kun kasvuennusteet ovat jääneet vaisuiksi.

Oppositio on arvostellut valmistelua siitä, että säästöjen vaikutukset kuntiin ja hyvinvointialueille voivat kasautua samaan aikaan. Hallituksen mukaan vaihtoehtona olisi velkaantumisen jatkuminen nykyisellä uralla.

Ekonomistien mukaan ratkaisevaa on, kohdistuvatko päätökset kertaluonteisiin säästöihin vai pysyviin rakenteellisiin muutoksiin. Markkinoilla seurataan erityisesti sitä, miten päätökset vaikuttavat työllisyyteen ja kotimaiseen kysyntään.""",
        "key_points": [
            "Hallitus valmistelee kevään kehysriiheen uusia säästöjä ja veropäätöksiä.",
            "Tavoitteena on vahvistaa julkista taloutta useilla sadoilla miljoonilla euroilla.",
            "Ratkaisujen vaikutuksia kuntiin, työllisyyteen ja kysyntään seurataan tarkasti.",
        ],
    },
    {
        "title": "Merituulivoimahanke etenee länsirannikolla",
        "summary": "Suunniteltu merituulipuisto siirtyy lupavaiheesta tarkempaan tekniseen valmisteluun.",
        "description": "Hankkeen arvioidaan tuottavan sähköä kymmenille tuhansille kotitalouksille, jos investointipäätös syntyy ensi vuonna.",
        "content": """Energiayhtiö kertoo, että merituulivoimahanke on siirtymässä seuraavaan valmisteluvaiheeseen länsirannikolla. Yhtiö arvioi, että suunnittelun tarkentuminen auttaa määrittämään lopullisen voimalamäärän, kaapeloinnin sekä satamien roolin rakentamisessa.

Kalastajat ja mökkiläiset ovat vaatineet lisäselvityksiä vaikutuksista maisemaan, veneilyyn ja luontoon. Yhtiön mukaan ympäristövaikutusten arviointi jatkuu rinnakkain teknisen suunnittelun kanssa.

Sähkömarkkinoilla hankkeen etenemistä seurataan siksi, että uusi tuotanto voisi lisätä tarjontaa tilanteessa, jossa kulutus kasvaa teollisissa investoinneissa. Samalla rakentamiskustannukset ja korkotaso vaikuttavat edelleen hankkeen kannattavuuteen.""",
        "key_points": "- Hanke etenee lupavaiheesta tarkempaan valmisteluun.\n- Ympäristövaikutuksia arvioidaan edelleen.\n- Investointipäätös riippuu kustannuksista ja markkinasta.",
    },
    {
        "title": "Teknologiayhtiö avaa uuden tutkimuskeskuksen Ouluun",
        "summary": "Uusi tutkimuskeskus keskittyy langattomiin verkkoihin, sulautettuihin järjestelmiin ja tekoälyn käyttöön teollisuudessa.",
        "description": "Yhtiö hakee alkuvaiheessa kymmeniä asiantuntijoita ja tekee yhteistyötä yliopiston kanssa.",
        "content": """Kansainvälinen teknologiayhtiö kertoo avaavansa Ouluun uuden tutkimuskeskuksen, joka keskittyy seuraavan sukupolven verkkoteknologioihin. Päätöstä perustellaan alueen vahvalla osaamispohjalla ja pitkällä elektroniikkateollisuuden historiallaan.

Yhtiö arvioi palkkaavansa ensimmäisessä vaiheessa useita kymmeniä asiantuntijoita ohjelmistokehitykseen, radiotekniikkaan ja data-analytiikkaan. Oulun yliopiston kanssa tarkoitus on käynnistää yhteisiä tutkimushankkeita sekä harjoitteluohjelmia.

Aluekehityksen kannalta hanke on merkittävä, koska se voi houkutella myös alihankkijoita ja muita teknologia-alan investointeja Pohjois-Suomeen. Kilpailu osaajista on silti kovaa, ja rekrytointien onnistuminen ratkaisee keskuksen kasvuvauhdin.""",
        "key_points": [
            "1. Yhtiö avaa Ouluun tutkimuskeskuksen langattomille verkoille.",
            "2. Keskus palkkaa alkuvaiheessa kymmeniä asiantuntijoita.",
            "3. Yhteistyötä tehdään yliopiston ja alueen yritysten kanssa.",
        ],
    },
    {
        "title": "Pitkä listaus testaa lyhennyslogiikkaa",
        "summary": "Tiivistyslogiikan pitää puristaa liian pitkät kohdat kolmeen napakkaan bulletiin ilman että olennaiset asiat katoavat.",
        "description": "Tämä fixture sisältää tahallisen pitkät pointit, jotta enimmäispituuden hallinta tulee oikeasti testatuksi eikä vain nimellisesti kirjattua koodiin.",
        "content": """Testiartikkelin tarkoitus on kuormittaa juuri sitä reittiä, jossa kielimallin palauttamat bulletit ovat liian pitkiä julkaisupintaan. Käytännössä ongelma näkyy silloin, kun jokainen kohta yrittää kertoa koko jutun yhdellä rivillä.

Tässä tapauksessa julkaisujärjestelmän on pakko lyhentää kohtia hallitusti niin, että lukija saa edelleen kolme ymmärrettävää pääasiaa. Samalla vältetään rumat katkeamiset, toisteisuus ja liian pitkät ingressimäiset listat.

Jos lyhennys ei riitä, varmistuslogiikka hakee varakohtia yhteenvedosta ja sisällöstä. Näin artikkeliin saadaan aina siisti, käyttöliittymässä toimiva Tärkeimmät kohdat -osio.""",
        "key_points": [
            "Tämä ensimmäinen kohta on tarkoituksella hyvin pitkä ja yrittää kertoa sekä testin tavoitteen että sen, miksi liiallinen pituus rikkoo käyttökokemusta uutisartikkelin yläosassa.",
            "Toinen kohta venyy myös turhan pitkäksi, koska sen tehtävä on varmistaa, että kokonaispituuden tasaus kohdistuu useaan kohtaan eikä ainoastaan yhteen selvästi ylimittaiseen bulletiin.",
            "Kolmaskin kohta jatkaa samaa linjaa ja pakottaa lyhennyslogiikan tekemään oikeita kompromisseja, jotta lopputulos säilyy ymmärrettävänä ja mahtuu asetettuun kolmensadan merkin rajaan.",
        ],
    },
    {
        "title": "Varafallback rakentaa kohdat sisällöstä",
        "summary": "Ensimmäinen johtopäätös korostaa toimitusvarmuutta. Toinen lause kertoo, että fallback hakee kohdat yhteenvedosta tai tekstistä. Kolmas lause varmistaa, että julkaisuun saadaan aina kolme nostoa.",
        "description": "Jos kielimalli ei tuota key_points-kenttää lainkaan, järjestelmä muodostaa sen muista kentistä.",
        "content": """Tässä testitapauksessa key_points puuttuu täysin. Julkaisuketjun ei silti pidä kaatua, vaan sen kuuluu muodostaa käyttökelpoinen kolmen kohdan lista yhteenvedosta ja sisällöstä.

Tavoite on käytännöllinen: artikkelipohja saa tarvitsemansa datan aina, vaikka upstream-vastaus olisi vajaa. Tämä pienentää käsityön tarvetta ja estää rikkinäisiä julkaisuja.

Koska fallback perustuu jo kirjoitettuun tekstiin, se ei keksi uusia väitteitä vaan tiivistää olemassa olevat pääasiat. Se on turvallisempi ratkaisu kuin jättää osio tyhjäksi tai julkaista satunnaista roskaa.""",
    },
]


def split_frontmatter(markdown: str):
    match = re.match(r"^---\n(.*?)\n---\n\n(.*)$", markdown, re.S)
    if not match:
        raise AssertionError("front matter missing")
    frontmatter_text = match.group(1)
    body = match.group(2)

    meta = {}
    lines = frontmatter_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if re.match(r"^[A-Za-z0-9_]+:$", line.strip()):
            key = line.split(":", 1)[0].strip()
            items = []
            i += 1
            while i < len(lines) and lines[i].startswith("  - "):
                item = lines[i][4:].strip().strip('"')
                items.append(item)
                i += 1
            meta[key] = items
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"')
        i += 1
    return meta, body


for index, fixture in enumerate(FIXTURES, start=1):
    article = dict(fixture)
    article["category"] = "Kotimaa"
    article["tags"] = ["testi", f"fixture-{index}"]
    article["description"] = article.get("description", article.get("summary", ""))
    article["key_points"] = _normalize_key_points(article)

    assert len(article["key_points"]) == 3, f"fixture {index}: expected 3 key points"
    total_len = sum(len(point) for point in article["key_points"])
    assert total_len <= 300, f"fixture {index}: key points too long ({total_len})"
    assert all(point and not point.startswith(("-", "•")) for point in article["key_points"])

    markdown = _article_to_markdown(article, "2026-03-26T10:00:00+00:00")
    meta, body = split_frontmatter(markdown)
    stored_points = meta.get("key_points")

    assert isinstance(stored_points, list), f"fixture {index}: key_points missing from front matter"
    assert len(stored_points) == 3, f"fixture {index}: wrong stored key point count"
    assert sum(len(point) for point in stored_points) <= 300, f"fixture {index}: stored key_points too long"
    assert body.strip(), f"fixture {index}: body missing"

    print(f"fixture {index}: ok ({sum(len(point) for point in stored_points)} chars)")

print(f"verified {len(FIXTURES)} fixtures")
