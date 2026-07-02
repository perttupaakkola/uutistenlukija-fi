#!/usr/bin/env python3
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from . import pexels, unsplash
    from . import image_query
    from . import image_candidate_guard
except ImportError:  # pragma: no cover
    import pexels
    import unsplash
    import image_query
    import image_candidate_guard


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

    def test_political_poll_query_sanitizes_named_person_portrait(self) -> None:
        title = "Kysely: Orpon hallitus saa kansalaisilta hallituskautensa heikoimman arvion"
        body = "Yli puolet vastaajista arvioi Petteri Orpon hallituksen onnistuneen huonosti."

        self.assertEqual(
            image_query.sanitize_generated_query("Petteri Orpo politician portrait", title, body, "Kotimaa"),
            "public opinion survey ballot",
        )

    def test_fetch_uses_sanitized_political_poll_query(self) -> None:
        title = "Kysely: Orpon hallitus saa kansalaisilta hallituskautensa heikoimman arvion"
        body = "Yli puolet vastaajista arvioi Petteri Orpon hallituksen onnistuneen huonosti."

        with patch.object(image_query, "generate_image_query", return_value="Petteri Orpo politician portrait"), \
             patch.object(pexels, "_search_pexels", return_value=[]) as pexels_search:
            self.assertIsNone(pexels.fetch_image_for_article(title, "Kotimaa", content=body, inter_request_delay=0))

        with patch.object(image_query, "generate_image_query", return_value="Petteri Orpo politician portrait"), \
             patch.object(unsplash, "_search", return_value=[]) as unsplash_search:
            self.assertIsNone(unsplash.fetch_image_for_article(title, "Kotimaa", content=body, inter_request_delay=0))

        pexels_search.assert_any_call("public opinion survey ballot")
        unsplash_search.assert_any_call("public opinion survey ballot")

    def test_sunny_weather_finland_rejects_snowy_unsplash_candidate(self) -> None:
        title = "Loppuviikon sää viilenee, mutta aurinkoa riittää monin paikoin"
        summary = "Korkeapaine pitää sään monin paikoin poutaisena ja aurinkoisena."
        candidate = {
            "id": "Ah_hBiz2-ao",
            "alt": "the sun is setting over a snowy forest",
            "photo_page": "https://unsplash.com/photos/the-sun-is-setting-over-a-snowy-forest-Ah_hBiz2-ao",
        }

        accepted, reason = image_candidate_guard.vet_image_candidate(
            candidate,
            query="sunny weather Finland",
            title=title,
            summary=summary,
        )

        self.assertFalse(accepted)
        self.assertIn("winter", reason)

    def test_non_contradictory_sunny_weather_candidate_is_allowed(self) -> None:
        candidate = {
            "id": "sunny-field",
            "alt": "sunny blue sky over green trees",
            "photo_page": "https://example.com/photos/sunny-blue-sky-green-trees",
        }

        accepted, reason = image_candidate_guard.vet_image_candidate(
            candidate,
            query="sunny weather Finland",
            title="Loppuviikon sää viilenee, mutta aurinkoa riittää monin paikoin",
            summary="Sää on monin paikoin poutainen ja aurinkoinen.",
        )

        self.assertTrue(accepted, reason)

    def test_unsplash_fetch_skips_snowy_candidate_and_uses_allowed_result(self) -> None:
        title = "Loppuviikon sää viilenee, mutta aurinkoa riittää monin paikoin"
        snowy = {
            "id": "Ah_hBiz2-ao",
            "url_regular": "https://images.unsplash.com/snowy",
            "url_full": "https://images.unsplash.com/snowy-full",
            "url_small": "https://images.unsplash.com/snowy-small",
            "url_thumb": "https://images.unsplash.com/snowy-thumb",
            "download_location": "https://api.unsplash.com/photos/Ah_hBiz2-ao/download",
            "photographer": "Aiva Apsite",
            "photographer_url": "https://unsplash.com/@aiva",
            "photo_page": "https://unsplash.com/photos/the-sun-is-setting-over-a-snowy-forest-Ah_hBiz2-ao",
            "alt": "the sun is setting over a snowy forest",
        }
        sunny = {
            "id": "sunny-field",
            "url_regular": "https://images.unsplash.com/sunny",
            "url_full": "https://images.unsplash.com/sunny-full",
            "url_small": "https://images.unsplash.com/sunny-small",
            "url_thumb": "https://images.unsplash.com/sunny-thumb",
            "download_location": "https://api.unsplash.com/photos/sunny-field/download",
            "photographer": "Test Photographer",
            "photographer_url": "https://unsplash.com/@test",
            "photo_page": "https://unsplash.com/photos/sunny-blue-sky-green-trees",
            "alt": "sunny blue sky over green trees",
        }

        with patch.object(image_query, "generate_image_query", return_value="sunny weather Finland"), \
             patch.object(unsplash, "_search", return_value=[snowy, sunny]), \
             patch.object(unsplash, "_trigger_download") as trigger_download, \
             patch("image_state.is_image_used", return_value=False), \
             patch("image_state.mark_image_used"), \
             patch.object(unsplash, "time") as unsplash_time:
            result = unsplash.fetch_image_for_article(
                title,
                "Kotimaa",
                summary="Korkeapaine pitää sään monin paikoin poutaisena ja aurinkoisena.",
                inter_request_delay=0,
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["url"], "https://images.unsplash.com/sunny")
        trigger_download.assert_called_once()
        self.assertEqual(trigger_download.call_args.args[0]["id"], "sunny-field")
        unsplash_time.sleep.assert_called_once_with(0)

    def test_pexels_fetch_uses_same_semantic_guard(self) -> None:
        title = "Loppuviikon sää viilenee, mutta aurinkoa riittää monin paikoin"
        snowy = {
            "id": 1,
            "url": "https://images.pexels.com/photos/snowy-forest.jpeg",
            "thumb_url": "https://images.pexels.com/photos/snowy-forest-thumb.jpeg",
            "photographer": "Winter Photo",
            "photographer_url": "https://www.pexels.com/@winter",
            "pexels_url": "https://www.pexels.com/photo/the-sun-is-setting-over-a-snowy-forest-1/",
        }
        sunny = {
            "id": 2,
            "url": "https://images.pexels.com/photos/sunny-sky.jpeg",
            "thumb_url": "https://images.pexels.com/photos/sunny-sky-thumb.jpeg",
            "photographer": "Sunny Photo",
            "photographer_url": "https://www.pexels.com/@sunny",
            "pexels_url": "https://www.pexels.com/photo/sunny-blue-sky-over-green-trees-2/",
        }

        with patch.object(image_query, "generate_image_query", return_value="sunny weather Finland"), \
             patch.object(pexels, "_search_pexels", return_value=[snowy, sunny]), \
             patch("image_state.is_image_used", return_value=False), \
             patch("image_state.mark_image_used"):
            result = pexels.fetch_image_for_article(
                title,
                "Kotimaa",
                summary="Korkeapaine pitää sään monin paikoin poutaisena ja aurinkoisena.",
                download=False,
                inter_request_delay=0,
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["url"], "https://images.pexels.com/photos/sunny-sky.jpeg")


if __name__ == "__main__":
    unittest.main()
