#!/usr/bin/env python3
from __future__ import annotations

import unittest

from quality_gate import check_numbers_sourced, score_article


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

    def test_unsourced_numbers_in_body_remain_warning_only(self):
        article = _article(False)
        article["content"] = article["content"] + "\n\nLisäksi valmistelussa arvioidaan 42 miljoonan euron vaikutusta."
        breakdown = score_article(article)
        self.assertTrue(any(w.startswith("unsourced_numbers") for w in breakdown.soft_warnings))
        self.assertFalse(any("central unsourced number" in fail for fail in breakdown.hard_fails))

    def test_unsourced_numbers_in_title_or_lead_are_hard_fail(self):
        article = _article(False)
        article["title"] = "Hallitus valmistelee 42 miljoonan euron säästöjä"
        article["content"] = (
            "Hallitus valmistelee 42 miljoonan euron säästöjä sosiaalihuoltoon ensi vuodelle. "
            "Valmistelu jatkuu ministeriöissä ja vaikutuksia arvioidaan hyvinvointialueilla. "
            "Ratkaisujen tavoitteena on hillitä menojen kasvua ilman, että palveluiden saatavuus heikkenee liikaa.\n\n"
            + article["content"]
        )
        breakdown = score_article(article)
        self.assertFalse(breakdown.passes)
        self.assertTrue(any("central unsourced number" in fail for fail in breakdown.hard_fails))

    def test_date_equivalence_works_in_both_directions(self):
        self.assertEqual(
            check_numbers_sourced(
                "Tehtävä alkaa 1.9.2026.",
                "Tehtävä alkaa 1. syyskuuta 2026.",
            ),
            [],
        )
        self.assertEqual(
            check_numbers_sourced(
                "Tehtävä alkaa 1. syyskuuta 2026.",
                "Tehtävä alkaa 1.9.2026.",
            ),
            [],
        )

    def test_source_date_without_year_does_not_authorize_invented_year(self):
        self.assertEqual(
            check_numbers_sourced(
                "Tehtävä alkaa 1. syyskuuta.",
                "Tehtävä alkaa 1. syyskuuta 2037.",
            ),
            ["1.9.2037"],
        )
        self.assertEqual(
            check_numbers_sourced(
                "Tehtävä alkaa 1. syyskuuta.",
                "Tehtävä alkaa 1.9.",
            ),
            [],
        )

    def test_equivalent_finnish_number_units_are_canonicalized(self):
        self.assertEqual(
            check_numbers_sourced(
                "Vaikutus on 42 miljoonaa euroa eli 7 prosenttia.",
                "Vaikutus on 42 miljoonan euron suuruinen eli 7 %.",
            ),
            [],
        )

    def test_million_and_billion_are_not_conflated(self):
        self.assertEqual(
            check_numbers_sourced(
                "Vaikutus on 42 miljardia euroa.",
                "Vaikutus on 42 miljoonaa euroa.",
            ),
            ["42miljoona"],
        )


if __name__ == "__main__":
    unittest.main()
