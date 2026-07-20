#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from publisher import _apply_keyword_category_override, _article_to_markdown, effective_category


class PublisherCategoryTests(unittest.TestCase):
    def test_retained_teknologia_packet_reaches_frontmatter_unchanged(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parent
            / "queues/staged/published/20260718T083134Z_96358acb15.json"
        )
        retained = json.loads(fixture_path.read_text(encoding="utf-8"))

        self.assertEqual(retained["packet"]["category"], "Teknologia")
        self.assertEqual(retained["payload"]["category"], "Teknologia")
        markdown = _article_to_markdown(
            retained["article"],
            "2026-07-18T08:31:34+00:00",
        )
        self.assertIn("\ncategories:\n  - Teknologia\n", markdown)

    def test_retained_kotimaa_packet_reaches_frontmatter_unchanged(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parent
            / "queues/staged/published/20260718T085119Z_00a3748bb8.json"
        )
        retained = json.loads(fixture_path.read_text(encoding="utf-8"))

        self.assertEqual(retained["packet"]["category"], "Kotimaa")
        self.assertEqual(retained["payload"]["category"], "Kotimaa")
        markdown = _article_to_markdown(
            retained["article"],
            "2026-07-18T08:51:19+00:00",
        )
        self.assertIn("\ncategories:\n  - Kotimaa\n", markdown)

    def test_retained_iphone_article_reaches_frontmatter_as_teknologia(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parent
            / "queues/staged/published/20260719T170121Z_452931fc1d.json"
        )
        retained = json.loads(fixture_path.read_text(encoding="utf-8"))
        corrected = {**retained["article"], "category": "Teknologia"}

        self.assertEqual(retained["article"]["category"], "Talous")
        self.assertEqual(effective_category(corrected), "Teknologia")
        markdown = _article_to_markdown(corrected, "2026-07-19T17:01:21+00:00")
        self.assertIn("\ncategories:\n  - Teknologia\n", markdown)
        self.assertNotIn("\ncategories:\n  - Talous\n", markdown)

    def test_retained_immigration_packet_stays_ulkomaat(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parent
            / "queues/staged/published/20260712T191123Z_48bdfbec17.json"
        )
        retained = json.loads(fixture_path.read_text(encoding="utf-8"))

        self.assertEqual(
            _apply_keyword_category_override(retained["payload"], "Ulkomaat"),
            "Ulkomaat",
        )

    def test_retained_macroeconomy_candidate_cannot_drift_to_tiede(self) -> None:
        article = {
            "title": "Talouspessimismi kasvattaa One Nationin kannatusta Australiassa",
            "summary": "Inflaatio, korkeat asumiskustannukset ja korkojen nousu painavat kotitalouksia.",
            "content": "Tutkija arvioi elinkustannusten ja asuntolainojen vaikutusta talouteen.",
            "category": "Kotimaa",
        }

        self.assertEqual(_apply_keyword_category_override(article, "Kotimaa"), "Talous")

    def test_retained_household_finance_candidate_cannot_drift_to_tiede(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parent
            / "queues/staged/published/20260713T061121Z_40f48c408f.json"
        )
        retained = json.loads(fixture_path.read_text(encoding="utf-8"))

        self.assertEqual(retained["article"]["category"], "Kotimaa")
        self.assertEqual(
            _apply_keyword_category_override(retained["article"], "Kotimaa"),
            "Talous",
        )

    def test_genuine_science_and_non_business_categories_remain_protected(self) -> None:
        science = {
            "title": "Tutkijat löysivät uuden solumekanismin",
            "summary": "Tutkimus julkaistiin tiedelehdessä.",
            "content": "Genomin analyysi auttaa ymmärtämään solujen toimintaa.",
            "category": "Kotimaa",
        }
        local = {
            "title": "Poliisi saapui ravintolaan",
            "summary": "Ravintolapäällikkö kertoi poliisin olevan tulossa paikalle.",
            "content": "Tilanne rauhoittui nopeasti.",
            "category": "Kotimaa",
        }

        self.assertEqual(_apply_keyword_category_override(science, "Kotimaa"), "Tiede")
        self.assertEqual(_apply_keyword_category_override(local, "Kotimaa"), "Kotimaa")

    def test_genuine_weather_terms_still_override_to_kotimaa(self) -> None:
        weather = {
            "title": "Sääennuste varoittaa ukkosmyrskystä",
            "summary": "Lämpötila laskee nopeasti illalla.",
            "content": "Ilmatieteen laitos seuraa sadealuetta.",
            "category": "Tiede",
        }

        self.assertEqual(_apply_keyword_category_override(weather, "Tiede"), "Kotimaa")

    def test_genuine_technology_terms_still_override_to_teknologia(self) -> None:
        technology = {
            "title": "Uusi tekoäly nopeuttaa ohjelmiston kehitystä",
            "summary": "Sovellus auttaa ohjelmoijia työssään.",
            "content": "Teknologia on saatavilla pilvipalvelun kautta.",
            "category": "Kotimaa",
        }

        self.assertEqual(
            _apply_keyword_category_override(technology, "Kotimaa"),
            "Teknologia",
        )


if __name__ == "__main__":
    unittest.main()
