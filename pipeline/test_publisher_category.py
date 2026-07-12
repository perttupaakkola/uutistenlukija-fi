#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from publisher import _apply_keyword_category_override


class PublisherCategoryTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
