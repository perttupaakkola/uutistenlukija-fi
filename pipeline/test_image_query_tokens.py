#!/usr/bin/env python3
from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

try:
    from . import pexels, unsplash
    from . import image_query
    from . import image_candidate_guard
    from . import audit_image_flow
    from .image_provider_result import search_photos
except ImportError:  # pragma: no cover
    import pexels
    import unsplash
    import image_query
    import image_candidate_guard
    import audit_image_flow
    from image_provider_result import search_photos


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

        pexels_empty = search_photos([], provider="pexels", attempted=True, succeeded=True,
                                     outcome="search_succeeded", reason="response_received")
        unsplash_empty = search_photos([], provider="unsplash", attempted=True, succeeded=True,
                                       outcome="search_succeeded", reason="response_received")
        with patch("image_query.generate_image_query", return_value="Atomfall television series"), \
             patch.object(pexels, "PEXELS_API_KEY", "key"), \
             patch.object(pexels, "_search_pexels", return_value=pexels_empty) as pexels_search, \
             patch.object(pexels, "time") as pexels_time:
            self.assertIsNone(pexels.fetch_image_for_article(title, "Kulttuuri", inter_request_delay=0))
            pexels_time.sleep.assert_not_called()

        with patch("image_query.generate_image_query", return_value="Atomfall television series"), \
             patch.object(unsplash, "UNSPLASH_ACCESS_KEY", "key"), \
             patch.object(unsplash, "_search", return_value=unsplash_empty) as unsplash_search, \
             patch.object(unsplash, "time") as unsplash_time:
            self.assertIsNone(unsplash.fetch_image_for_article(title, "Kulttuuri", inter_request_delay=0))
            unsplash_time.sleep.assert_not_called()

        pexels_queries = [call.args[0] for call in pexels_search.call_args_list]
        unsplash_queries = [call.args[0] for call in unsplash_search.call_args_list]
        self.assertIn("Atomfall television series", pexels_queries)
        self.assertIn("Atomfall television series", unsplash_queries)
        self.assertNotIn(pexels.CATEGORY_QUERIES["Kulttuuri"], pexels_queries)
        self.assertNotIn(unsplash.CATEGORY_QUERIES["Kulttuuri"], unsplash_queries)

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

        pexels_empty = search_photos([], provider="pexels", attempted=True, succeeded=True,
                                     outcome="search_succeeded", reason="response_received")
        unsplash_empty = search_photos([], provider="unsplash", attempted=True, succeeded=True,
                                       outcome="search_succeeded", reason="response_received")
        with patch("image_query.generate_image_query", return_value="Petteri Orpo politician portrait"), \
             patch.object(pexels, "PEXELS_API_KEY", "key"), \
             patch.object(pexels, "_search_pexels", return_value=pexels_empty) as pexels_search:
            self.assertIsNone(pexels.fetch_image_for_article(title, "Kotimaa", content=body, inter_request_delay=0))

        with patch("image_query.generate_image_query", return_value="Petteri Orpo politician portrait"), \
             patch.object(unsplash, "UNSPLASH_ACCESS_KEY", "key"), \
             patch.object(unsplash, "_search", return_value=unsplash_empty) as unsplash_search:
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

    def test_generated_weather_query_cannot_redefine_economy_article_truth(self) -> None:
        title = "Suomen talous elpyy, mutta kasvu näkyy kuluttajien arjessa viiveellä"
        summary = "BKT, vienti, palkat, työllisyys ja kulutus vahvistuvat eri tahdissa."
        content = (
            "Talouden kasvu perustuu vientiin ja kotitalouksien ostovoiman asteittaiseen "
            "elpymiseen. Työllisyys reagoi suhdanteeseen viiveellä."
        )
        query = "sunny Finnish weather"
        candidate = {
            "id": "CcNCC0Zplwc",
            "alt": "white and red boat near city under sunny sky",
            "photo_page": "https://unsplash.com/photos/CcNCC0Zplwc",
        }

        intent = image_candidate_guard.build_image_intent(
            title,
            "Talous",
            summary=summary,
            content=content,
            query=query,
        )
        brief = image_candidate_guard.build_visual_brief(
            title,
            "Talous",
            summary=summary,
            content=content,
            query=query,
        )
        decision = image_candidate_guard.score_image_candidate(
            candidate,
            intent=intent,
            query=query,
            title=title,
            summary=summary,
            content=content,
            provider="unsplash",
        )

        self.assertNotIn("weather", intent.must_have)
        self.assertNotIn("sunny Finnish weather", brief.acceptable_concepts)
        self.assertFalse(decision.accepted)
        self.assertIn("no article-grounded concept overlap", "; ".join(decision.reasons))

    def test_named_person_story_rejects_generic_lookalike_stock_portrait(self) -> None:
        candidate = {
            "id": "generic-politician",
            "alt": "portrait of a politician speaking at a podium",
            "photo_page": "https://example.com/photos/generic-politician-portrait",
        }

        accepted, reason = image_candidate_guard.vet_image_candidate(
            candidate,
            query="politician portrait",
            title="Petteri Orpo kommentoi hallituksen uutta kyselytulosta",
            summary="Artikkeli käsittelee Petteri Orpon hallitusta ja kyselyä.",
        )

        self.assertFalse(accepted)
        self.assertIn("lookalike", reason)

    def test_akseli_boat_repair_rejects_unsplash_skyscraper_candidate(self) -> None:
        title = "16-vuotiaan Akseli Hinkkalan veneenkorjaus lähti kesätyön puutteesta"
        summary = "16-vuotias kunnostaa romukuntoisia veneitä ja perusti 4H-yrityksen."
        content = "Hän korjaa soutuveneitä ja moottoriveneitä vanhempiensa kotipihalla."
        candidate = {
            "id": "photo-1776333089082-e6d06c8b6910",
            "alt": "modern glass skyscrapers against a clear sky",
            "url": "https://images.unsplash.com/photo-1776333089082-e6d06c8b6910",
            "photo_page": "https://unsplash.com/photos/modern-glass-skyscrapers-against-a-clear-sky",
        }

        accepted, reason = image_candidate_guard.vet_image_candidate(
            candidate,
            query="business entrepreneur",
            title=title,
            summary=summary,
            content=content,
        )

        self.assertFalse(accepted)
        self.assertIn("boat-repair", reason)

    def test_visual_brief_lists_concepts_and_forbidden_implications(self) -> None:
        brief = image_candidate_guard.build_visual_brief(
            "16-vuotiaan Akseli Hinkkalan veneenkorjaus lähti kesätyön puutteesta",
            "Talous",
            summary="16-vuotias kunnostaa romukuntoisia veneitä ja perusti 4H-yrityksen.",
            content="Hän korjaa soutuveneitä ja moottoriveneitä vanhempiensa kotipihalla.",
        )

        self.assertIn("boat repair workshop", brief.acceptable_concepts)
        self.assertTrue(any("skyscrapers" in item for item in brief.hard_forbidden_implications))
        self.assertEqual(brief.prompt_version, image_candidate_guard.PROMPT_VERSION)

    def test_visual_judge_hard_fail_overrides_keyword_score(self) -> None:
        brief = image_candidate_guard.build_visual_brief(
            "16-vuotiaan Akseli Hinkkalan veneenkorjaus lähti kesätyön puutteesta",
            "Talous",
            summary="16-vuotias kunnostaa romukuntoisia veneitä ja perusti 4H-yrityksen.",
            content="Hän korjaa soutuveneitä ja moottoriveneitä vanhempiensa kotipihalla.",
        )

        judge = image_candidate_guard.judge_visual_candidate(
            {
                "id": "photo-1776333089082-e6d06c8b6910",
                "alt": "modern glass skyscrapers against a clear sky",
                "url": "https://images.unsplash.com/photo-1776333089082-e6d06c8b6910",
            },
            brief=brief,
        )

        self.assertTrue(judge.hard_fail)
        self.assertFalse(judge.accepted)
        self.assertEqual(judge.score, 0)

    def test_logistics_payment_terms_use_article_grounded_stock_concepts(self) -> None:
        title = (
            "Kuljetusyrittäjälle esitettiin jopa 90 päivän maksuehtoa – "
            "60 päivääkin olisi vaatinut pankkilainaa"
        )
        summary = "Kuljetusyrityksen laskujen maksuaikaa haluttiin pidentää rajusti."
        content = (
            "Kuljetusyrittäjä ajaa kuorma-autoa ja kertoo pitkän maksuehdon "
            "vaikeuttavan kuljetusliikkeen kassaa ja logistiikan rahoitusta."
        )

        queries = image_candidate_guard.build_stock_queries(
            title,
            "Talous",
            summary=summary,
            content=content,
            primary_query="asiakkaan maksuehto olisi pidentynyt päivästä",
        )

        self.assertIn("freight truck logistics", [query for query, _, _ in queries])
        self.assertNotEqual(queries[0][1], "primary_query")
        query, concept, brief = queries[0]
        accepted, _ = image_candidate_guard.filter_image_candidates(
            [{
                "id": "freight-truck",
                "alt": "commercial freight truck on road for logistics transport",
                "photo_page": "https://example.com/freight-truck",
            }],
            query=query,
            title=title,
            summary=summary,
            content=content,
            provider="unsplash",
            brief=brief,
            concept=concept,
            return_decisions=True,
        )

        self.assertEqual(len(accepted), 1)
        self.assertTrue(
            any(
                isinstance(row, dict) and row.get("id") == "freight-truck"
                for row in accepted
            )
        )

    def test_named_carpenter_story_accepts_non_person_workshop_image(self) -> None:
        title = "Puuseppäyrittäjä Jukka Korpi haastaa halvan Ikea-keittiön mielikuvan"
        summary = "Kalannin Kaluste valmistaa erikoismittaisia keittiökalusteita."
        content = (
            "Puuseppä valmistaa puusta keittiökaappeja ja muita kalusteita "
            "verstaassa asiakkaan mittojen mukaan."
        )
        queries = image_candidate_guard.build_stock_queries(
            title,
            "Talous",
            summary=summary,
            content=content,
            primary_query="kalannin kaluste valmistaa erikoismittaiset kalusteet",
        )

        self.assertIn("carpentry workshop", [query for query, _, _ in queries])
        query, concept, brief = queries[0]
        self.assertEqual(brief.intent.safety_mode, "illustration_only")
        accepted, _ = image_candidate_guard.filter_image_candidates(
            [{
                "id": "carpentry-workshop",
                "alt": "carpentry workshop with wooden kitchen cabinets and woodworking tools",
                "photo_page": "https://example.com/carpentry-workshop",
            }],
            query=query,
            title=title,
            summary=summary,
            content=content,
            provider="pexels",
            brief=brief,
            concept=concept,
            return_decisions=True,
        )

        self.assertEqual(len(accepted), 1)
        self.assertFalse(
            any(
                isinstance(row, dict) and "person" in str(row.get("alt", ""))
                for row in accepted
            )
        )

    def test_ambiguous_terms_do_not_activate_unrelated_visual_concepts(self) -> None:
        intent = image_candidate_guard.build_image_intent(
            "Gordon Bennett kommentoi hallituksen cabinet-keskustelua",
            "Ulkomaat",
            content="Poliittinen rally keräsi yleisöä ja transport-kysymykset olivat esillä.",
        )

        self.assertEqual(intent.must_have, [])

    def test_multi_concept_stock_rejection_records_all_candidate_failures(self) -> None:
        brief = image_candidate_guard.build_visual_brief(
            "16-vuotiaan Akseli Hinkkalan veneenkorjaus lähti kesätyön puutteesta",
            "Talous",
            summary="16-vuotias kunnostaa romukuntoisia veneitä ja perusti 4H-yrityksen.",
            content="Hän korjaa soutuveneitä ja moottoriveneitä vanhempiensa kotipihalla.",
        )
        accepted, decisions = image_candidate_guard.filter_image_candidates(
            [
                {
                    "id": "photo-1776333089082-e6d06c8b6910",
                    "alt": "modern glass skyscrapers against a clear sky",
                    "photo_page": "https://unsplash.com/photos/modern-glass-skyscrapers-against-a-clear-sky",
                },
                {
                    "id": "generic-finance",
                    "alt": "business district office towers and city skyline",
                    "photo_page": "https://example.com/finance",
                },
            ],
            query="business entrepreneur",
            title="16-vuotiaan Akseli Hinkkalan veneenkorjaus lähti kesätyön puutteesta",
            summary="16-vuotias kunnostaa romukuntoisia veneitä ja perusti 4H-yrityksen.",
            content="Hän korjaa soutuveneitä ja moottoriveneitä vanhempiensa kotipihalla.",
            provider="unsplash",
            brief=brief,
            concept="boat repair workshop",
            return_decisions=True,
        )

        self.assertEqual(accepted, [])
        self.assertEqual(len(decisions), 2)
        self.assertTrue(all(not decision.accepted for decision in decisions))

    def test_audit_flags_boat_repair_article_with_skyscraper_stock_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            post_dir = Path(tmp)
            post = post_dir / "2026-07-02-akseli.md"
            post.write_text(
                "---\n"
                'title: "16-vuotiaan Akseli Hinkkalan veneenkorjaus lähti kesätyön puutteesta"\n'
                "date: 2026-07-02T09:38:06+00:00\n"
                "categories:\n"
                "  - Talous\n"
                'description: "16-vuotias kunnostaa romukuntoisia veneitä ja perusti 4H-yrityksen."\n'
                'image: "https://images.unsplash.com/photo-1776333089082-e6d06c8b6910"\n'
                'image_source_url: "https://unsplash.com/photos/modern-glass-skyscrapers-against-a-clear-sky"\n'
                'image_source: "unsplash"\n'
                'image_query: "business entrepreneur"\n'
                "---\n\n"
                "Hän korjaa soutuveneitä ja moottoriveneitä vanhempiensa kotipihalla.\n",
                encoding="utf-8",
            )
            with patch.object(audit_image_flow, "POSTS_DIR", post_dir):
                rows = audit_image_flow.audit_recent(1)

        self.assertEqual(rows[0]["status"], "flag")
        self.assertIn("boat-repair", rows[0]["reason"])

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

        photos = search_photos(
            [snowy, sunny], provider="unsplash", attempted=True, succeeded=True,
            outcome="search_succeeded", reason="response_received",
        )
        with patch("image_query.generate_image_query", return_value="sunny weather Finland"), \
             patch.object(unsplash, "UNSPLASH_ACCESS_KEY", "key"), \
             patch.object(unsplash, "_search", return_value=photos), \
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

        photos = search_photos(
            [snowy, sunny], provider="pexels", attempted=True, succeeded=True,
            outcome="search_succeeded", reason="response_received",
        )
        with patch("image_query.generate_image_query", return_value="sunny weather Finland"), \
             patch.object(pexels, "PEXELS_API_KEY", "key"), \
             patch.object(pexels, "_search_pexels", return_value=photos), \
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
