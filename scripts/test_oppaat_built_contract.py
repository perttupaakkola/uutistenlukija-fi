#!/usr/bin/env python3
"""Assert the rendered OPE-377 guide, discovery, schema, and archive contract."""

from __future__ import annotations

import argparse
import html
import json
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


HUB_PATH = "/oppaat/"
GUIDE_PATH = "/oppaat/kauppojen-aukioloajat/"
HUB_URL = f"https://uutistenlukija.fi{HUB_PATH}"
GUIDE_URL = f"https://uutistenlukija.fi{GUIDE_PATH}"
LEGACY_PATHS = (
    "/paasiaisopas/kaupat-auki/",
    "/vappuopas/kaupat-auki/",
)
SEASONAL_HUBS = ("/paasiaisopas/", "/vappuopas/")

HUB_TITLE = "Oppaat – käytännön tietoa arkeen | Uutistenlukija"
HUB_H1 = "Oppaat arjen käytännön tilanteisiin"
HUB_DESCRIPTION = (
    "Selkeät, lähteisiin perustuvat oppaat palvelujen, poikkeusaikojen "
    "ja arjen käytännön tietojen tarkistamiseen."
)
GUIDE_TITLE = "Kaupat auki pyhinä – tarkista oma kauppa | Uutistenlukija"
GUIDE_H1 = "Kauppojen aukioloajat pyhinä – näin tarkistat oman kaupan"
GUIDE_DESCRIPTION = (
    "Tarkista kauppojen poikkeavat aukioloajat luotettavasti virallisista "
    "myymälähauista. Opas kertoo, mistä oman kaupan ajantasainen tieto löytyy."
)


def page_path(public: Path, route: str) -> Path:
    return public / route.strip("/") / "index.html"


def read_page(public: Path, route: str) -> str:
    path = page_path(public, route)
    if not path.is_file():
        raise AssertionError(f"missing built page: {path}")
    return path.read_text(encoding="utf-8")


def tag_text(source: str, tag: str) -> list[str]:
    matches = re.findall(
        rf"<{tag}\b[^>]*>(.*?)</{tag}>",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return [
        re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", value))).strip()
        for value in matches
    ]


def attr_values(source: str, tag: str, attr: str) -> list[str]:
    values: list[str] = []
    for attrs in re.findall(rf"<{tag}\b([^>]*)>", source, flags=re.IGNORECASE):
        match = re.search(
            rf"\b{attr}=(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
            attrs,
            flags=re.IGNORECASE,
        )
        if match:
            values.append(html.unescape(next(value for value in match.groups() if value is not None)))
    return values


def meta_content(source: str, name: str) -> list[str]:
    values: list[str] = []
    for attrs in re.findall(r"<meta\b([^>]*)>", source, flags=re.IGNORECASE):
        name_match = re.search(
            r"\bname=(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
            attrs,
            flags=re.IGNORECASE,
        )
        if not name_match:
            continue
        actual_name = next(value for value in name_match.groups() if value is not None)
        if actual_name.lower() != name.lower():
            continue
        content_match = re.search(
            r"\bcontent=(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
            attrs,
            flags=re.IGNORECASE,
        )
        if content_match:
            values.append(
                html.unescape(
                    next(value for value in content_match.groups() if value is not None)
                )
            )
    return values


def canonical_values(source: str) -> list[str]:
    values: list[str] = []
    for attrs in re.findall(r"<link\b([^>]*)>", source, flags=re.IGNORECASE):
        if not re.search(r"\brel=(?:\"canonical\"|'canonical'|canonical)(?:\s|$)", attrs):
            continue
        href = re.search(
            r"\bhref=(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
            attrs,
        )
        if href:
            values.append(next(value for value in href.groups() if value is not None))
    return values


def schemas(source: str) -> list[dict]:
    blocks = re.findall(
        r"<script\b[^>]*type=(?:\"application/ld\+json\"|'application/ld\+json'|application/ld\+json)[^>]*>(.*?)</script>",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return [json.loads(html.unescape(block)) for block in blocks]


def schema_types(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        schema_type = value.get("@type")
        if isinstance(schema_type, str):
            found.append(schema_type)
        elif isinstance(schema_type, list):
            found.extend(str(item) for item in schema_type)
        for child in value.values():
            found.extend(schema_types(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(schema_types(child))
    return found


def sitemap_locations(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    return [
        element.text or ""
        for element in root.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url/"
                                    "{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
    ]


class BuiltOppaatContractTest(unittest.TestCase):
    public: Path

    def test_exact_titles_descriptions_canonicals_and_h1s(self) -> None:
        fixtures = (
            (HUB_PATH, HUB_TITLE, HUB_DESCRIPTION, HUB_URL, HUB_H1),
            (GUIDE_PATH, GUIDE_TITLE, GUIDE_DESCRIPTION, GUIDE_URL, GUIDE_H1),
        )
        for route, title, description, canonical, h1 in fixtures:
            with self.subTest(route=route):
                source = read_page(self.public, route)
                self.assertEqual(tag_text(source, "title"), [title])
                self.assertEqual(meta_content(source, "description"), [description])
                self.assertEqual(canonical_values(source), [canonical])
                self.assertEqual(tag_text(source, "h1"), [h1])
                self.assertEqual(meta_content(source, "robots"), [])

    def test_navigation_footer_and_breadcrumbs_use_canonical_oppaat(self) -> None:
        source = read_page(self.public, GUIDE_PATH)
        nav = re.search(
            r'<nav\b[^>]*id=(?:"main-nav-menu"|\'main-nav-menu\'|main-nav-menu)[^>]*>(.*?)</nav>',
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(nav)
        labels = tag_text(nav.group(1), "a")
        self.assertLess(labels.index("Tiede"), labels.index("Oppaat"))
        self.assertLess(labels.index("Oppaat"), labels.index("Tuoreimmat"))
        self.assertIn('href=/oppaat/', source)

        breadcrumb = re.search(
            r'<nav\b[^>]*aria-label=(?:"Murupolku"|\'Murupolku\'|Murupolku)[^>]*>(.*?)</nav>',
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(breadcrumb)
        breadcrumb_text = re.sub(
            r"\s+",
            " ",
            html.unescape(re.sub(r"<[^>]+>", " ", breadcrumb.group(1))),
        ).strip()
        self.assertIn("Etusivu", breadcrumb_text)
        self.assertIn("Oppaat", breadcrumb_text)
        self.assertIn(GUIDE_H1, breadcrumb_text)

    def test_guide_article_schema_is_narrow_and_exact(self) -> None:
        guide_schemas = schemas(read_page(self.public, GUIDE_PATH))
        articles = [item for item in guide_schemas if item.get("@type") == "Article"]
        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article["headline"], GUIDE_H1)
        self.assertEqual(article["description"], GUIDE_DESCRIPTION)
        self.assertEqual(article["mainEntityOfPage"]["@id"], GUIDE_URL)
        self.assertEqual(article["author"]["@type"], "Organization")
        self.assertEqual(
            article["author"]["url"],
            "https://uutistenlukija.fi/tietoja/#toimitustapa",
        )
        self.assertEqual(article["inLanguage"], "fi")
        self.assertIs(article["isAccessibleForFree"], True)
        self.assertIn("datePublished", article)
        self.assertIn("dateModified", article)
        for forbidden in ("image", "reviewedBy"):
            self.assertNotIn(forbidden, article)
        types = schema_types(guide_schemas)
        for forbidden_type in ("NewsArticle", "FAQPage", "HowTo"):
            self.assertNotIn(forbidden_type, types)

        breadcrumbs = [
            item for item in guide_schemas if item.get("@type") == "BreadcrumbList"
        ]
        self.assertEqual(len(breadcrumbs), 1)
        self.assertEqual(
            [item["name"] for item in breadcrumbs[0]["itemListElement"]],
            ["Etusivu", "Oppaat", GUIDE_H1],
        )

    def test_hub_has_one_collection_page_and_one_current_item(self) -> None:
        hub_schemas = schemas(read_page(self.public, HUB_PATH))
        collections = [
            item for item in hub_schemas if item.get("@type") == "CollectionPage"
        ]
        self.assertEqual(len(collections), 1)
        collection = collections[0]
        self.assertEqual(collection["name"], HUB_H1)
        self.assertEqual(collection["url"], HUB_URL)
        self.assertEqual(collection["mainEntity"]["@type"], "ItemList")
        items = collection["mainEntity"]["itemListElement"]
        self.assertEqual(
            [(item["position"], item["url"], item["name"]) for item in items],
            [(1, GUIDE_URL, GUIDE_H1)],
        )
        hub = read_page(self.public, HUB_PATH)
        self.assertEqual(hub.count('class=guide-card>'), 1)
        main = re.search(r"<main\b[^>]*>(.*?)</main>", hub, flags=re.DOTALL)
        self.assertIsNotNone(main)
        self.assertNotIn("newsletter", main.group(1).lower())

    def test_lifecycle_labels_sources_and_correction_are_visible(self) -> None:
        source = read_page(self.public, GUIDE_PATH)
        visible = re.sub(
            r"\s+",
            " ",
            html.unescape(re.sub(r"<[^>]+>", " ", source)),
        )
        for label in (
            "Lähteet tarkistettu",
            "Seuraava tarkistus viimeistään",
            "Voimassa",
            "Ilmoita korjauksesta",
        ):
            self.assertIn(label, visible)
        self.assertNotIn(">Päivitetty<", source)
        self.assertIn("K-ryhmä: kauppojen aukioloajat", visible)
        self.assertIn("S-kaupat: myymälät", visible)
        self.assertIn("Lidl: myymälät Suomessa", visible)

    def test_sitemap_and_feeds_have_only_the_accepted_discovery(self) -> None:
        locations = sitemap_locations(self.public / "sitemap.xml")
        self.assertEqual(locations.count(HUB_URL), 1)
        self.assertEqual(locations.count(GUIDE_URL), 1)
        for seasonal in SEASONAL_HUBS:
            self.assertEqual(
                locations.count(f"https://uutistenlukija.fi{seasonal}"),
                1,
            )
        for legacy in LEGACY_PATHS:
            self.assertEqual(
                locations.count(f"https://uutistenlukija.fi{legacy}"),
                0,
            )

        for feed_name in ("index.xml", "news-sitemap.xml"):
            feed = (self.public / feed_name).read_text(encoding="utf-8")
            self.assertNotIn("/oppaat/", feed, feed_name)
            for legacy in LEGACY_PATHS:
                self.assertNotIn(legacy, feed, feed_name)
        self.assertFalse((self.public / "oppaat/index.xml").exists())

    def test_legacy_children_are_absent_and_seasonal_hubs_are_archived(self) -> None:
        for legacy in LEGACY_PATHS:
            self.assertFalse(page_path(self.public, legacy).exists(), legacy)
        for seasonal in SEASONAL_HUBS:
            source = read_page(self.public, seasonal)
            self.assertIn("Arkistoitu", source)
            self.assertEqual(
                canonical_values(source),
                [f"https://uutistenlukija.fi{seasonal}"],
            )

    def test_built_search_has_hub_and_canonical_once_without_legacy(self) -> None:
        records = json.loads(
            (self.public / "search-index.json").read_text(encoding="utf-8")
        )
        urls = [record["url"] for record in records]
        self.assertEqual(urls.count(HUB_PATH), 1)
        self.assertEqual(urls.count(GUIDE_PATH), 1)
        guide = next(record for record in records if record["url"] == GUIDE_PATH)
        self.assertEqual(guide["category"], "Oppaat")
        self.assertEqual(
            guide["search_terms"],
            ["oppaat", "kaupat auki", "aukioloajat", "pyhäpäivä"],
        )
        for legacy in LEGACY_PATHS:
            self.assertNotIn(legacy, urls)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("public", type=Path)
    args = parser.parse_args()
    if not args.public.is_dir():
        raise SystemExit(f"not a build directory: {args.public}")
    BuiltOppaatContractTest.public = args.public.resolve()
    unittest.main(argv=["test_oppaat_built_contract.py"])


if __name__ == "__main__":
    main()
