#!/usr/bin/env python3
from __future__ import annotations

import unittest

from quality_gate import score_article


_BASE = (
    "Hallitus valmistelee uusia säästöjä sosiaalihuoltoon ensi vuodelle. "
    "Valmistelu jatkuu ministeriöissä ja vaikutuksia arvioidaan hyvinvointialueilla. "
    "Ratkaisujen tavoitteena on hillitä menojen kasvua ilman, että palveluiden saatavuus heikkenee liikaa."
)


def _article(degraded_mode: bool) -> dict:
    para1 = " ".join([_BASE] * 2)
    para2 = "## Mitä tiedetään\n" + " ".join([_BASE] * 2)
    para3 = "## Mitä seuraavaksi\n" + " ".join([_BASE] * 2)
    content = "\n\n".join([para1, para2, para3])
    source_text = " ".join([_BASE] * 3)
    return {
        "title": "Hallitus valmistelee uusia säästöjä",
        "description": "Hallitus valmistelee uusia säästöjä sosiaalihuoltoon ensi vuodelle.",
        "content": content,
        "category": "Kotimaa",
        "image": "https://example.com/test.jpg",
        "source_text": source_text,
        "source_url": "https://example.com/story",
        "key_points": [
            "Päätöksiä valmistellaan ensi vuodelle.",
            "Vaikutuksia arvioidaan hyvinvointialueilla.",
        ],
        "degraded_mode": degraded_mode,
    }


class QualityGateDegradedModeTests(unittest.TestCase):
    def test_short_article_fails_without_degraded_mode(self):
        breakdown = score_article(_article(False))
        self.assertFalse(breakdown.passes)
        self.assertTrue(any("too_short" in fail for fail in breakdown.hard_fails))

    def test_short_article_can_pass_with_degraded_mode(self):
        breakdown = score_article(_article(True))
        self.assertTrue(breakdown.passes)
        self.assertEqual(breakdown.hard_fails, [])
        self.assertGreaterEqual(breakdown.total, 30)


    def test_missing_image_does_not_block_pre_image_gate(self):
        article = _article(True)
        article["image"] = ""
        breakdown = score_article(article)
        self.assertTrue(breakdown.passes)
        self.assertEqual(breakdown.image_pts, 10)


if __name__ == "__main__":
    unittest.main()
