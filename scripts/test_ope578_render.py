#!/usr/bin/env python3
"""Exact built-output regression for the OPE-578 treatment."""

from html.parser import HTMLParser
import json
import os
from pathlib import Path
import unittest


SLUG = "2026-05-08-isanmaan-toivot-sarjan-toni-wahlstrom-on-jatkanut-uraansa-te"
TITLE = "Toni Wahlström – Isänmaan toivot ja teatterityö | Uutistenlukija"
DESCRIPTION = (
    "Toni Wahlström näytteli Anttia Isänmaan toivot -sarjassa. Lue hänen "
    "ruututöistään sekä vuosien 2016 ja 2022 teatterityöstä lähteineen."
)
HEADLINE = (
    "Toni Wahlström näytteli Anttia Isänmaan toivoissa – teatterityöstä tietoa "
    "vuosilta 2016 ja 2022"
)
SOURCES = [
    ("Ruutu", "https://www.ruutu.fi/ohjelmat/isanmaan-toivot"),
    ("KAVI/Elonet", "https://elonet.finna.fi/Search/Results?filter%5B%5D=author2_id_str_mv%3Akavi.elonet_henkilo_718596&sort=main_date_str+desc&limit=50"),
    ("Ilta-Sanomat", "https://www.is.fi/viihde/art-2000001167471.html"),
    ("Rauhalahti Teatteri", "https://www.rauhalahtiteatteri.fi/tuotanto/rockn-rollators-musikaali-2022/"),
    ("Tiketti", "https://www.tiketti.fi/kaunis-ja-koskettava-rockmusikaalikomedia-rock-n-rollators-news/12617"),
]
BODY = [
    "Toni Wahlström näytteli Anttia Isänmaan toivot -sarjassa. KAVI/Elonet kokoaa hänen ruututöitään, ja vuosilta 2016 ja 2022 on lähteitä hänen teatteriohjauksistaan. Tämän jutun tiedot koskevat lähteissä nimettyjä vuosia, eivät Wahlströmin nykyistä työtilannetta.",
    "Antti Isänmaan toivot -sarjassa",
    "Ruutu-palvelun ohjelmasivun mukaan Toni Wahlström näytteli Isänmaan toivot -sarjassa Anttia.",
    "Ruututyöt KAVI/Elonetin tiedoissa",
    "Kansallisen audiovisuaalisen instituutin Elonet-hakutulos kokoaa Wahlströmin elokuva- ja televisiotöitä. Kaappari on luettelossa vuoden 2012 teoksena.",
    "Teatteriohjauksia koskeva haastattelu vuodelta 2016",
    "Ilta-Sanomien vuonna 2016 julkaisemassa haastattelussa Wahlström kertoi tehneensä teatteriohjauksia haastattelua edeltäneiden kymmenen vuoden aikana. Tieto kuvaa hänen uraansa haastattelun ajankohtana eikä kerro hänen nykyisestä työtilanteestaan.",
    "Rock'n Rollators vuonna 2022",
    "Rauhalahti Teatterin tuotantosivun mukaan Toni Wahlström ja Ismo Apell kirjoittivat vuoden 2022 Rock'n Rollators -musikaalin. Tiketin tiedotteen mukaan Wahlström myös ohjasi teoksen, jonka ensi-ilta oli 30. kesäkuuta 2022.",
]


class ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.capture: str | None = None
        self.text: dict[str, list[str]] = {"title": [], "h1": [], "body": []}
        self.meta: dict[tuple[str, str], str] = {}
        self.sources: list[tuple[str, str, str, str]] = []
        self.schemas: list[dict] = []
        self._schema_parts: list[str] | None = None
        self._source: tuple[str, str, str] | None = None
        self._body_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if tag == "meta":
            for key in ("name", "property"):
                if values.get(key):
                    self.meta[(key, values[key] or "")] = values.get("content") or ""
        if tag == "title":
            self.capture = "title"
        elif tag == "h1":
            self.capture = "h1"
        if "content" in classes:
            self._body_depth = 1
        elif self._body_depth:
            self._body_depth += 1
        if tag == "script" and values.get("type") == "application/ld+json":
            self._schema_parts = []
        if tag == "a" and "source-attribution__link" in classes:
            self._source = (
                values.get("href") or "",
                values.get("target") or "",
                values.get("rel") or "",
            )

    def handle_endtag(self, tag: str) -> None:
        if tag in {"title", "h1"}:
            self.capture = None
        if self._body_depth:
            self._body_depth -= 1
        if tag == "script" and self._schema_parts is not None:
            self.schemas.append(json.loads("".join(self._schema_parts)))
            self._schema_parts = None
        if tag == "a" and self._source:
            self._source = None

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if self._schema_parts is not None:
            self._schema_parts.append(data)
        elif value:
            if self.capture:
                self.text[self.capture].append(value)
            if self._body_depth:
                self.text["body"].append(value)
            if self._source:
                self.sources.append((value, *self._source))


@unittest.skipUnless(os.environ.get("HUGO_OUTPUT_DIR"), "requires a Hugo build")
class Ope578RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        page = Path(os.environ["HUGO_OUTPUT_DIR"]) / "posts" / SLUG / "index.html"
        cls.html = page.read_text(encoding="utf-8")
        cls.parser = ArticleParser()
        cls.parser.feed(cls.html)

    def test_exact_metadata_and_body(self) -> None:
        self.assertEqual(" ".join(self.parser.text["title"]), TITLE)
        self.assertEqual(" ".join(self.parser.text["h1"]), HEADLINE)
        self.assertEqual(self.parser.meta[("name", "description")], DESCRIPTION)
        self.assertEqual(self.parser.meta[("property", "og:title")], TITLE)
        self.assertEqual(self.parser.meta[("property", "og:description")], DESCRIPTION)
        body = self.parser.text["body"]
        self.assertEqual(body, BODY)
        self.assertEqual(" ".join(body).count("Rock'n Rollators"), 2)
        self.assertNotIn("Rock’n Rollators", " ".join(body))

    def test_five_visible_and_schema_sources_are_ordered(self) -> None:
        self.assertEqual(
            self.parser.sources,
            [(name, url, "_blank", "noopener noreferrer") for name, url in SOURCES],
        )
        news = next(schema for schema in self.parser.schemas if schema.get("@type") == "NewsArticle")
        self.assertEqual(news["headline"], HEADLINE)
        self.assertEqual(news["description"], DESCRIPTION)
        self.assertEqual(
            news["isBasedOn"],
            [{"@type": "WebPage", "url": url} for _, url in SOURCES],
        )

    def test_rejected_claims_and_schema_are_absent(self) -> None:
        for rejected in (
            "Maaseudun Tulevaisuus",
            "maaseuduntulevaisuus.fi",
            "Seiska",
            "Vivi Wahlström",
            "25. tammikuuta",
            "Kaappari 2013",
            "Rock’n Rollators",
        ):
            self.assertNotIn(rejected, self.html)
        self.assertFalse(any(schema.get("@type") == "FAQPage" for schema in self.parser.schemas))

    def test_legacy_single_source_schema_remains_an_object(self) -> None:
        legacy_page = (
            Path(os.environ["HUGO_OUTPUT_DIR"])
            / "posts"
            / "2026-03-20-jyvaskylassa-lahihoitajalle-tuomio-tietosuojarikoksista"
            / "index.html"
        )
        parser = ArticleParser()
        parser.feed(legacy_page.read_text(encoding="utf-8"))
        news = next(schema for schema in parser.schemas if schema.get("@type") == "NewsArticle")
        self.assertEqual(
            news["isBasedOn"],
            {"@type": "WebPage", "url": "https://yle.fi/a/74-20216112"},
        )


if __name__ == "__main__":
    unittest.main()
