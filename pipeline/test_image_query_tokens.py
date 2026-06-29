#!/usr/bin/env python3
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from . import pexels, unsplash
    from . import image_query
except ImportError:  # pragma: no cover
    import pexels
    import unsplash
    import image_query


DEGREE_ROI_FIXTURE = {
    "title": "Kannattaako korkeakoulututkinto? Uusi laskuri arvioi koulutuksen tuoton",
    "category": "Talous",
    "summary": (
        "Artikkeli kertoo korkeakoulututkinnon sijoitetun pääoman tuotosta, "
        "palkkaerosta, opintolainasta ja tutkinnon takaisinmaksuajasta."
    ),
    "content": (
        "Korkeakoulututkinnon kannattavuutta arvioidaan vertaamalla lukukausimaksuja, "
        "opintolainaa, menetettyjä työvuosia ja valmistumisen jälkeistä palkkatasoa. "
        "Degree ROI kertoo, milloin koulutus maksaa itsensä takaisin."
    ),
}


class ImageQueryTokenTests(unittest.TestCase):
    def test_degree_roi_fallback_query_uses_english_visual_tokens(self) -> None:
        expected = "university degree education return investment"

        self.assertEqual(pexels.build_search_query(**DEGREE_ROI_FIXTURE), expected)
        self.assertEqual(unsplash.build_search_query(**DEGREE_ROI_FIXTURE), expected)

    def test_entertainment_articles_block_broad_category_fallback(self) -> None:
        fixture = {
            "title": "Netflixin viikko tuo Enola Holmesin, scifiä ja uusia sarjakausia",
            "summary": "Suoratoistopalvelun uudet elokuvat ja sarjat julkaistaan tällä viikolla.",
            "key_points": ["Netflix", "Enola Holmes", "elokuvat"],
            "content": "",
        }

        self.assertTrue(pexels.blocks_broad_category_fallback(**fixture))
        self.assertTrue(unsplash.blocks_broad_category_fallback(**fixture))

    def test_non_entertainment_articles_allow_category_fallback(self) -> None:
        fixture = {
            "title": "Uusi laskuri arvioi korkeakoulutuksen tuoton",
            "summary": "Artikkeli vertailee koulutuksen kustannuksia ja palkkatasoa.",
            "key_points": ["koulutus", "opintolaina"],
            "content": "",
        }

        self.assertFalse(pexels.blocks_broad_category_fallback(**fixture))
        self.assertFalse(unsplash.blocks_broad_category_fallback(**fixture))

    def test_entertainment_fetch_does_not_search_broad_category_fallback(self) -> None:
        title = "Atomfall-pelistä tehdään televisiosarja"

        with patch.object(image_query, "generate_image_query", return_value="Atomfall television series"), \
             patch.object(pexels, "_search_pexels", return_value=[]) as pexels_search, \
             patch.object(pexels, "time") as pexels_time:
            self.assertIsNone(pexels.fetch_image_for_article(title, "Kulttuuri", inter_request_delay=0))
            pexels_time.sleep.assert_not_called()

        with patch.object(image_query, "generate_image_query", return_value="Atomfall television series"), \
             patch.object(unsplash, "_search", return_value=[]) as unsplash_search, \
             patch.object(unsplash, "time") as unsplash_time:
            self.assertIsNone(unsplash.fetch_image_for_article(title, "Kulttuuri", inter_request_delay=0))
            unsplash_time.sleep.assert_not_called()

        self.assertEqual(pexels_search.call_count, 1)
        self.assertEqual(unsplash_search.call_count, 1)


if __name__ == "__main__":
    unittest.main()
