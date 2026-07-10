#!/usr/bin/env python3
"""Regression checks for the passive advertiser trust surface."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AdvertiserTrustSurfaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.frontmatter = (ROOT / "content/mainosta/_index.md").read_text(encoding="utf-8")
        self.mainosta = (ROOT / "layouts/_default/mainosta.html").read_text(encoding="utf-8")
        self.cta = (ROOT / "layouts/partials/advertiser-cta.html").read_text(encoding="utf-8")
        self.tracking = (ROOT / "layouts/partials/event-tracking.html").read_text(encoding="utf-8")
        self.critical_css = (ROOT / "layouts/partials/critical-css.html").read_text(encoding="utf-8")
        self.style_css = (ROOT / "themes/uutistenlukija/static/css/style.css").read_text(
            encoding="utf-8"
        )

    def test_public_copy_has_no_unsupported_or_internal_claims(self) -> None:
        public_copy = self.frontmatter + self.mainosta + self.cta
        forbidden = (
            "10 000+",
            "25 000+",
            "3 min+",
            "25–55",
            "Kaupunkilaiset, koulutetut",
            "käy sivustolla päivittäin",
            "Merkittävä mobiiliyleisö",
            "monetization_signal",
            "Sponsoroitu sisältö",
            "journalistiseen muotoon",
            "pilottikampanja",
            "49 €",
        )
        for claim in forbidden:
            with self.subTest(claim=claim):
                self.assertNotIn(claim, public_copy)

        self.assertIn("Näkyvyyttä, klikkauksia tai myyntiä ei taata", public_copy)
        self.assertIn("mainostaja ei osallistu", public_copy)

    def test_existing_passive_lead_telemetry_is_preserved(self) -> None:
        for template in (self.mainosta, self.cta):
            self.assertIn('data-track="advertise_cta_click"', template)
            self.assertIn('data-monetization-signal="advertise_email_click"', template)

        self.assertIn('data-monetization-signal="advertise_page_click"', self.cta)
        self.assertIn("_gtag('event', 'monetization_signal'", self.tracking)
        self.assertIn("[data-monetization-signal]", self.tracking)

    def test_article_bottom_cta_uses_full_width_copy_row(self) -> None:
        selector = ".advertiser-cta--article-bottom .advertiser-cta__inner"
        for stylesheet in (self.critical_css, self.style_css):
            with self.subTest(stylesheet=stylesheet[:24]):
                start = stylesheet.find(selector)
                self.assertNotEqual(-1, start)
                rule = stylesheet[start : start + 180]
                self.assertIn("grid-template-columns", rule)
                self.assertIn("minmax(0, 1fr)", rule)


if __name__ == "__main__":
    unittest.main()
