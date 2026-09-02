#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    from . import audit_image_flow, image_candidate_guard, image_state
except ImportError:  # pragma: no cover
    import audit_image_flow
    import image_candidate_guard
    import image_state


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FINANCE_ARTICLE = (
    PROJECT_ROOT
    / "content/posts/2026-09-02-finanssiala-vaatii-sisapiirirekisterivelvoitteen-poistamista.md"
)
FINANCE_PACKET = (
    PROJECT_ROOT
    / "pipeline/queues/staged/published/20260902T181239Z_b91614fbff.json"
)


SNOW_CANDIDATE = {
    "id": "rxLGSOM0e3U",
    "alt": "brown wooden fence filled with snow during winter",
    "url_regular": (
        "https://images.unsplash.com/photo-1511803471753-da23b1a92d4b"
        "?crop=entropy&fm=jpg&w=1080"
    ),
    "photo_page": (
        "https://unsplash.com/photos/"
        "brown-wooden-fence-filled-with-snow-during-winter-rxLGSOM0e3U"
    ),
}


class ArticleGroundedImagePipelineTests(unittest.TestCase):
    def test_finance_article_rejects_injected_winter_intent_and_snow_candidate(self) -> None:
        title = "Finanssiala vaatii sisäpiirirekisterivelvoitteen poistamista rahastoyhtiöiltä"
        summary = "Hallitus valmistelee kansallisen rekisterivelvoitteen poistamista."
        content = (
            "EU-sääntely on kansallista sääntelyä kattavampaa. Velvoite on jäänyt "
            "päällekkäiseksi, ja muutos vähentäisi rahastoyhtiöiden hallinnollista työtä."
        )
        grounded = image_candidate_guard.build_image_intent(
            title, "Talous", summary=summary, content=content
        )
        injected = replace(
            grounded,
            season_time="winter",
            must_have=["weather", "winter conditions"],
        )

        decision = image_candidate_guard.score_image_candidate(
            SNOW_CANDIDATE,
            intent=injected,
            query="winter weather",
            title=title,
            summary=summary,
            content=content,
            provider="unsplash",
        )

        self.assertNotIn("weather", grounded.must_have)
        self.assertEqual(grounded.season_time, "neutral")
        self.assertFalse(decision.accepted)
        self.assertIn("unsupported", "; ".join(decision.reasons))

    def test_finnish_regulation_and_verb_jaa_do_not_create_weather_truth(self) -> None:
        intent = image_candidate_guard.build_image_intent(
            "EU-sääntely jää kansallisen velvoitteen rinnalle",
            "Talous",
            summary="Rahastoyhtiöiden hallinnollista taakkaa halutaan keventää.",
            content="Sääntelyä yhdenmukaistetaan eikä talvesta tai säästä kerrota.",
        )

        self.assertEqual(intent.season_time, "neutral")
        self.assertFalse(any("weather" in cue for cue in intent.must_have))
        self.assertFalse(any("winter" in cue for cue in intent.must_have))

    def test_incidental_name_and_negated_winter_do_not_create_winter_intent(self) -> None:
        fixtures = (
            {
                "title": "Larppi-sarjassa Lumi etsii rohkeutta olla oma itsensä",
                "summary": "Lumi osallistuu ensimmäistä kertaa roolipelitapahtumaan.",
                "content": "Sarja käsittelee identiteettiä ja ihmissuhteita.",
            },
            {
                "title": "Rahastoyhtiöiden rekisterivelvoitetta muutetaan",
                "summary": "Muutos koskee finanssisääntelyä ja hallinnollista työtä.",
                "content": "Talvi ei liity päätökseen eikä jutussa käsitellä säätä.",
            },
            {
                "title": "Kunnan budjettipäätös etenee valtuustoon",
                "summary": "Päätös koskee ensi vuoden investointeja.",
                "content": "Tausta-aineistossa mainitaan sana talvi vain esimerkkinä.",
            },
        )

        for fixture in fixtures:
            with self.subTest(title=fixture["title"]):
                intent = image_candidate_guard.build_image_intent(
                    fixture["title"],
                    "Kulttuuri" if "Larppi" in fixture["title"] else "Talous",
                    summary=fixture["summary"],
                    content=fixture["content"],
                )
                brief = image_candidate_guard.build_visual_brief(
                    fixture["title"],
                    "Kulttuuri" if "Larppi" in fixture["title"] else "Talous",
                    summary=fixture["summary"],
                    content=fixture["content"],
                )

                self.assertEqual(intent.season_time, "neutral")
                self.assertNotIn("winter conditions", intent.must_have)
                self.assertNotIn("winter weather", brief.acceptable_concepts)

    def test_concrete_winter_weather_remains_grounded(self) -> None:
        intent = image_candidate_guard.build_image_intent(
            "Talvi saapuu Tampereelle",
            "Kotimaa",
            summary="Sää kylmenee ja lumi peittää kadut.",
        )

        self.assertEqual(intent.season_time, "winter")
        self.assertIn("winter conditions", intent.must_have)

    def test_railway_and_peat_stories_reject_winter_weather_stock(self) -> None:
        fixtures = (
            (
                "Karjalan radalle esitetään 149 miljoonan euron valtuutta",
                "Hallitus esittää rautatien parantamiseen rahoitusta.",
                "Rakennustyöt ja rataverkon kohtaamispaikat kuuluvat hankkeeseen, "
                "mutta useita ratkaisuja jää seuraavalle hallitukselle.",
            ),
            (
                "Hallitus kaavailee tukea turvealueiden metsitykseen",
                "Entisiä turpeennostoalueita voidaan metsittää tai vettää.",
                "Ratkaisu vaikuttaa soihin, kosteikkoihin, ilmastoon ja luonnon "
                "monimuotoisuuteen; keskeiseksi kysymykseksi jää tuen kohdentuminen.",
            ),
        )
        for title, summary, content in fixtures:
            with self.subTest(title=title):
                intent = image_candidate_guard.build_image_intent(
                    title, "Kotimaa", summary=summary, content=content
                )
                decision = image_candidate_guard.score_image_candidate(
                    SNOW_CANDIDATE,
                    intent=intent,
                    query="winter weather",
                    title=title,
                    summary=summary,
                    content=content,
                    provider="unsplash",
                )
                self.assertFalse(decision.accepted)
                self.assertIn("article-grounded", "; ".join(decision.reasons))

    def test_sensitive_military_conflict_rejects_tv_books_intent_and_candidate(self) -> None:
        title = "Yhdysvallat iski Larakin saarelle – Iran ilmoitti ohjusiskuista Jordaniaan"
        summary = "Osapuolet kertoivat sotilasiskuista ja ballistisista ohjuksista."
        content = (
            "Iranin valtiollisen television mukaan iskuissa kuoli ihmisiä. "
            "Tietoja ei ole vahvistettu riippumattomasti."
        )
        grounded = image_candidate_guard.build_image_intent(
            title, "Ulkomaat", summary=summary, content=content
        )
        injected = replace(
            grounded,
            must_have=["book, television, or screen production"],
        )
        candidate = {
            "id": "ORT8CtIFriE",
            "alt": "a television sitting on top of a shelf filled with books",
            "photo_page": (
                "https://unsplash.com/photos/"
                "a-television-sitting-on-top-of-a-shelf-filled-with-books-ORT8CtIFriE"
            ),
        }

        decision = image_candidate_guard.score_image_candidate(
            candidate,
            intent=injected,
            query="book and television production",
            title=title,
            summary=summary,
            content=content,
            provider="unsplash",
        )

        self.assertTrue(grounded.sensitive_story)
        self.assertFalse(grounded.stock_ok)
        self.assertFalse(decision.accepted)
        self.assertIn("sensitive", "; ".join(decision.reasons))

    def test_finnish_incidents_and_compounds_disable_stock_and_generation(self) -> None:
        fixtures = (
            ("Junaonnettomuus pysäytti Karjalan radan liikenteen", "Useita loukkaantui törmäyksessä."),
            ("Väkivalta lisääntyi viikonlopun aikana", "Poliisi tutkii tapahtumia."),
            ("Pahoinpitely johti esitutkintaan", "Tapausta selvitetään."),
            ("Räjähdys vaurioitti rakennusta", "Pelastuslaitos eristi alueen."),
            ("Tulipalo sulki keskustan kadun", "Sammutustyöt jatkuivat aamulla."),
            ("Loukkaantuminen keskeytti kilpailun", "Osallistuja vietiin hoitoon."),
        )

        for title, summary in fixtures:
            with self.subTest(title=title):
                intent = image_candidate_guard.build_image_intent(
                    title, "Kotimaa", summary=summary
                )
                queries = image_candidate_guard.build_stock_queries(
                    title, "Kotimaa", summary=summary
                )

                self.assertTrue(intent.sensitive_story)
                self.assertFalse(intent.stock_ok)
                self.assertFalse(intent.generated_ok)
                self.assertEqual(queries, [])

    def test_common_finnish_diabetes_and_cancer_variants_are_sensitive(self) -> None:
        titles = (
            "Diabetes yleistyy nuorten keskuudessa",
            "Diabeteksen hoitoa uudistetaan",
            "Diabeetikkojen palvelut muuttuvat",
            "Syöpä havaitaan aiempaa aikaisemmin",
            "Syövän hoitotulokset paranevat",
        )

        for title in titles:
            with self.subTest(title=title):
                intent = image_candidate_guard.build_image_intent(title, "Tiede")

                self.assertTrue(intent.sensitive_story)
                self.assertFalse(intent.stock_ok)
                self.assertFalse(intent.generated_ok)
                self.assertEqual(
                    image_candidate_guard.build_stock_queries(title, "Tiede"),
                    [],
                )

    def test_violent_and_financial_crime_inflections_override_stock_concepts(self) -> None:
        titles = (
            "Hotellissa tapahtuneen puukotuksen tutkinta jatkuu",
            "Hotellin joukkoraiskauksen esitutkinta valmistui",
            "Pankkiryöstö johti hotellin sulkemiseen",
            "Hotelliyhtiön kavallusepäily eteni oikeuteen",
        )
        summary = "Tapahtumapaikkana ollut hotelli tarjoaa majoitusta keskustassa."

        for title in titles:
            with self.subTest(title=title):
                intent = image_candidate_guard.build_image_intent(
                    title, "Kotimaa", summary=summary
                )

                self.assertIn("hotel or hospitality", intent.must_have)
                self.assertTrue(intent.sensitive_story)
                self.assertFalse(intent.stock_ok)
                self.assertFalse(intent.generated_ok)
                self.assertEqual(
                    image_candidate_guard.build_stock_queries(
                        title, "Kotimaa", summary=summary
                    ),
                    [],
                )

    def test_generation_requires_a_grounded_non_sensitive_visual_concept(self) -> None:
        unmatched = image_candidate_guard.build_image_intent(
            "Kunnan päätös etenee ensi viikolla",
            "Kotimaa",
            summary="Valmistelu jatkuu tavalliseen tapaan.",
        )
        grounded = image_candidate_guard.build_image_intent(
            "Karjalan rautatiehanke etenee",
            "Kotimaa",
            summary="Rautatien ja rataverkon rakennustyöt alkavat ensi vuonna.",
        )

        self.assertFalse(unmatched.generated_ok)
        self.assertTrue(grounded.generated_ok)

    def test_single_name_action_headline_blocks_generic_person_in_both_gates(self) -> None:
        title = "Trump kommentoi uutta mielipidekyselyä"
        summary = "Kysely mittaa äänestäjien mielipidettä hallinnosta."
        brief = image_candidate_guard.build_visual_brief(
            title, "Ulkomaat", summary=summary
        )
        candidate = {
            "id": "generic-businessman",
            "alt": "businessman reviewing a public opinion survey and ballot questionnaire",
            "photo_page": "https://example.com/photos/businessman-public-opinion-survey",
        }
        decision = image_candidate_guard.score_image_candidate(
            candidate,
            intent=brief.intent,
            query="public opinion survey ballot",
            title=title,
            summary=summary,
            category="Ulkomaat",
        )
        judge = image_candidate_guard.judge_visual_candidate(candidate, brief=brief)

        self.assertTrue(brief.intent.named_person)
        self.assertEqual(brief.intent.safety_mode, "illustration_only")
        self.assertFalse(decision.accepted)
        self.assertIn("lookalike", "; ".join(decision.reasons))
        self.assertTrue(judge.hard_fail)
        self.assertFalse(judge.accepted)
        self.assertIn("lookalike", "; ".join(judge.reasons))

    def test_named_person_story_is_unconditionally_stock_ineligible(self) -> None:
        title = "Donald Trump kommentoi uutta mielipidekyselyä"
        summary = "Kysely mittaa äänestäjien mielipidettä hallinnosta."
        brief = image_candidate_guard.build_visual_brief(
            title, "Ulkomaat", summary=summary
        )
        candidates = (
            {
                "id": "named-subject-at-podium",
                "alt": "Donald Trump holding public opinion survey ballot at podium",
                "photo_page": "https://example.com/photos/donald-trump-survey-ballot-podium",
            },
            {
                "id": "generic-speaker-at-podium",
                "alt": "speaker holding public opinion survey ballot at podium",
                "photo_page": "https://example.com/photos/speaker-survey-ballot-podium",
            },
        )

        self.assertTrue(brief.intent.named_person)
        self.assertFalse(brief.intent.stock_ok)
        self.assertTrue(brief.intent.generated_ok)
        self.assertEqual(
            image_candidate_guard.build_stock_queries(
                title, "Ulkomaat", summary=summary
            ),
            [],
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate["id"]):
                decision = image_candidate_guard.score_image_candidate(
                    candidate,
                    intent=brief.intent,
                    query="public opinion survey ballot",
                    title=title,
                    summary=summary,
                    category="Ulkomaat",
                    provider="unsplash",
                )
                judge = image_candidate_guard.judge_visual_candidate(
                    candidate, brief=brief, provider="unsplash"
                )

                self.assertFalse(decision.accepted)
                self.assertIn("named-person", "; ".join(decision.reasons))
                self.assertTrue(judge.hard_fail)
                self.assertFalse(judge.accepted)
                self.assertIn("named-person", "; ".join(judge.reasons))

        generated_symbolic = image_candidate_guard.judge_visual_candidate(
            {
                "id": "symbolic-ballot",
                "alt": "public opinion survey questionnaire and ballot box",
                "photo_page": "https://example.com/photos/survey-questionnaire-ballot-box",
            },
            brief=brief,
            provider="generated",
        )
        self.assertTrue(generated_symbolic.accepted)

    def test_railway_concept_requires_railway_anchor(self) -> None:
        title = "Karjalan radan rahoitusta lisätään"
        summary = "Rautatien parantamiseen esitetään uutta rahoitusta."
        content = "Rataverkon rakennustyöt voivat alkaa ensi vuonna."
        query, concept, brief = image_candidate_guard.build_stock_queries(
            title, "Kotimaa", summary=summary, content=content
        )[0]
        airport = {
            "id": "airport-construction",
            "alt": "airport infrastructure construction beside a terminal building",
            "photo_page": "https://example.com/photos/airport-infrastructure-construction",
        }
        railway = {
            "id": "railway-construction",
            "alt": "railway tracks and rail infrastructure construction work",
            "photo_page": "https://example.com/photos/railway-tracks-construction",
        }

        accepted, decisions = image_candidate_guard.filter_image_candidates(
            [airport, railway],
            query=query,
            title=title,
            summary=summary,
            content=content,
            category="Kotimaa",
            provider="unsplash",
            brief=brief,
            concept=concept,
            return_decisions=True,
        )
        airport_judge = image_candidate_guard.judge_visual_candidate(airport, brief=brief)

        self.assertEqual([candidate["id"] for candidate in accepted], ["railway-construction"])
        self.assertFalse(decisions[0].accepted)
        self.assertIn("concept-specific anchor", "; ".join(decisions[0].reasons))
        self.assertTrue(decisions[1].accepted)
        self.assertTrue(airport_judge.hard_fail)
        self.assertIn("concept-specific anchor", "; ".join(airport_judge.reasons))

    def test_tampere_railway_rejects_foreign_city_country_mismatches(self) -> None:
        title = "Tampereella rakennetaan uutta rautatieyhteyttä"
        summary = "Tampereen rataverkon rakennustyöt alkavat ensi vuonna."
        query, concept, brief = image_candidate_guard.build_stock_queries(
            title, "Kotimaa", summary=summary
        )[0]
        foreign_candidates = [
            {
                "id": "paris-railway",
                "alt": "railway tracks and rail infrastructure construction in Paris France",
                "photo_page": "https://example.com/photos/paris-france-railway-construction",
            },
            {
                "id": "rome-railway",
                "alt": "railway tracks and rail infrastructure construction in Rome Italy",
                "photo_page": "https://example.com/photos/rome-italy-railway-construction",
            },
            {
                "id": "london-railway",
                "alt": "railway tracks and rail infrastructure construction in London England",
                "photo_page": "https://example.com/photos/london-england-railway-construction",
            },
            {
                "id": "new-york-railway",
                "alt": "railway tracks and rail infrastructure in New York United States",
                "photo_page": "https://example.com/photos/new-york-united-states-railway",
            },
            {
                "id": "unlisted-foreign-railway",
                "alt": "railway tracks and rail infrastructure construction in Madrid Spain",
                "photo_page": "https://example.com/photos/madrid-spain-railway-construction",
            },
        ]
        local = {
            "id": "tampere-railway",
            "alt": "railway tracks and rail infrastructure construction in Tampere Finland",
            "photo_page": "https://example.com/photos/tampere-finland-railway-construction",
        }

        accepted, decisions = image_candidate_guard.filter_image_candidates(
            [*foreign_candidates, local],
            query=query,
            title=title,
            summary=summary,
            category="Kotimaa",
            provider="unsplash",
            brief=brief,
            concept=concept,
            return_decisions=True,
        )
        foreign_judges = [
            image_candidate_guard.judge_visual_candidate(candidate, brief=brief)
            for candidate in foreign_candidates
        ]

        self.assertIn("tampere", brief.intent.locations)
        self.assertEqual([candidate["id"] for candidate in accepted], ["tampere-railway"])
        for decision in decisions[:-1]:
            self.assertFalse(decision.accepted)
            self.assertIn("location lacks article support", "; ".join(decision.reasons))
        self.assertTrue(decisions[-1].accepted)
        for judge in foreign_judges:
            self.assertTrue(judge.hard_fail)
            self.assertIn("location lacks article support", "; ".join(judge.reasons))

    def test_lowercase_alt_and_provider_slug_reject_unsupported_city_country(self) -> None:
        title = "Tampereella rakennetaan uutta rautatieyhteyttä"
        summary = "Tampereen rataverkon rakennustyöt alkavat ensi vuonna."
        query, _, brief = image_candidate_guard.build_stock_queries(
            title,
            "Kotimaa",
            summary=summary,
        )[0]
        foreign_candidates = []
        for city, country in (
            ("madrid", "spain"),
            ("bratislava", "slovakia"),
            ("osaka", "japan"),
            ("porvoo", "finland"),
        ):
            foreign_candidates.extend(
                [
                    {
                        "id": f"lowercase-{city}",
                        "alt": f"railway tracks in {city} {country}",
                        "photo_page": (
                            "https://unsplash.com/photos/"
                            f"railway-tracks-in-{city}-{country}-lowercaseLocation"
                        ),
                    },
                    {
                        "id": f"url-only-{city}",
                        "alt": "",
                        "photo_page": (
                            "https://unsplash.com/photos/"
                            f"railway-tracks-in-{city}-{country}-urlOnlyLocation"
                        ),
                    },
                ]
            )
        for index, (preposition, country) in enumerate(
            (
                ("in", "slovakia"),
                ("at", "japan"),
                ("near", "united arab emirates"),
                ("from", "canada"),
            )
        ):
            slug_country = country.replace(" ", "-")
            slug = f"railway-tracks-{preposition}-{slug_country}-countryLocation"
            foreign_candidates.append(
                {
                    "id": f"country-{preposition}-{country}",
                    "alt": (
                        f"railway tracks {preposition} {country}"
                        if index % 2 == 0
                        else ""
                    ),
                    "photo_page": f"https://unsplash.com/photos/{slug}",
                }
            )
        foreign_candidates.extend(
            [
                {
                    "id": "bare-country-lowercase-slovakia",
                    "alt": "railway tracks slovakia",
                    "photo_page": "https://unsplash.com/photos/railway-track-bareCountryAlt",
                },
                {
                    "id": "bare-country-url-only-slovakia",
                    "alt": "",
                    "photo_page": (
                        "https://unsplash.com/photos/"
                        "railway-tracks-slovakia-bareCountryUrl"
                    ),
                },
            ]
        )
        supported_candidates = [
            {
                "id": "lowercase-tampere",
                "alt": (
                    "railway tracks and rail infrastructure construction "
                    "in tampere finland"
                ),
                "photo_page": (
                    "https://unsplash.com/photos/"
                    "railway-tracks-in-tampere-finland-localTampere"
                ),
            },
            {
                "id": "generic-rural-finland",
                "alt": (
                    "railway tracks and rail infrastructure construction "
                    "in rural finland"
                ),
                "photo_page": (
                    "https://unsplash.com/photos/"
                    "railway-infrastructure-in-rural-finland-ruralRail"
                ),
            },
            {
                "id": "url-only-northern-finland",
                "alt": "",
                "photo_page": (
                    "https://unsplash.com/photos/railway-tracks-and-rail-"
                    "infrastructure-construction-in-northern-finland-northRail"
                ),
            },
            {
                "id": "generic-scenic-finland",
                "alt": (
                    "railway tracks and rail infrastructure construction "
                    "in scenic finland"
                ),
                "photo_page": (
                    "https://unsplash.com/photos/"
                    "scenic-railway-infrastructure-finland-scenicRail"
                ),
            },
        ]

        for candidate in foreign_candidates:
            with self.subTest(candidate=candidate["id"]):
                decision = image_candidate_guard.score_image_candidate(
                    candidate,
                    intent=brief.intent,
                    query=query,
                    title=title,
                    summary=summary,
                    category="Kotimaa",
                    provider="unsplash",
                )
                judge = image_candidate_guard.judge_visual_candidate(
                    candidate,
                    brief=brief,
                    provider="unsplash",
                )

                self.assertFalse(decision.accepted)
                self.assertEqual(decision.score, image_candidate_guard.MISMATCH_SCORE)
                self.assertIn("location lacks article support", "; ".join(decision.reasons))
                self.assertFalse(judge.accepted)
                self.assertTrue(judge.hard_fail)
                self.assertIn("location lacks article support", "; ".join(judge.reasons))

        for candidate in supported_candidates:
            with self.subTest(candidate=candidate["id"]):
                supported_decision = image_candidate_guard.score_image_candidate(
                    candidate,
                    intent=brief.intent,
                    query=query,
                    title=title,
                    summary=summary,
                    category="Kotimaa",
                    provider="unsplash",
                )
                supported_judge = image_candidate_guard.judge_visual_candidate(
                    candidate,
                    brief=brief,
                    provider="unsplash",
                )
                self.assertTrue(supported_decision.accepted)
                self.assertTrue(supported_judge.accepted)
                self.assertFalse(supported_judge.hard_fail)

    def test_country_location_truth_from_summary_supports_matching_candidate(self) -> None:
        title = "Uutta rautatieyhteyttä suunnitellaan"
        summary = "Railway construction will begin in Osaka Japan next year."
        query, _, brief = image_candidate_guard.build_stock_queries(
            title,
            "Ulkomaat",
            summary=summary,
        )[0]
        candidate = {
            "id": "supported-osaka",
            "alt": "railway tracks and rail infrastructure in osaka japan",
            "photo_page": (
                "https://unsplash.com/photos/"
                "railway-infrastructure-in-osaka-japan-supportedLocation"
            ),
        }

        decision = image_candidate_guard.score_image_candidate(
            candidate,
            intent=brief.intent,
            query=query,
            title=title,
            summary=summary,
            category="Ulkomaat",
            provider="unsplash",
        )
        judge = image_candidate_guard.judge_visual_candidate(
            candidate,
            brief=brief,
            provider="unsplash",
        )

        self.assertIn("japan", brief.intent.locations)
        self.assertIn("osaka", brief.intent.locations)
        self.assertIn(("osaka", "japan"), brief.intent.location_pairs)
        self.assertTrue(decision.accepted)
        self.assertTrue(judge.accepted)

    def test_location_parser_ignores_styles_names_and_generic_title_case(self) -> None:
        title = "Tampereella rakennetaan uutta rautatieyhteyttä"
        summary = "Tampereen rataverkon rakennustyöt alkavat ensi vuonna."
        query, _, brief = image_candidate_guard.build_stock_queries(
            title,
            "Kotimaa",
            summary=summary,
        )[0]
        semantic_nonplaces = [
            "railway tracks and rail infrastructure in japanese style",
            "railway tracks beside an Air Jordan advertisement",
            "railway construction beside a roasted turkey mural",
            "railway tracks and rail infrastructure in Modern Office interior",
        ]

        for index, alt in enumerate(semantic_nonplaces):
            with self.subTest(alt=alt):
                candidate = {
                    "id": f"semantic-nonplace-{index}",
                    "alt": alt,
                    "photo_page": "https://unsplash.com/photos/railway-track-genericSafe",
                }
                decision = image_candidate_guard.score_image_candidate(
                    candidate,
                    intent=brief.intent,
                    query=query,
                    title=title,
                    summary=summary,
                    category="Kotimaa",
                    provider="unsplash",
                )
                judge = image_candidate_guard.judge_visual_candidate(
                    candidate,
                    brief=brief,
                    provider="unsplash",
                )
                self.assertTrue(decision.accepted)
                self.assertTrue(judge.accepted)
                self.assertFalse(judge.hard_fail)

    def test_location_parser_keeps_city_country_pairing_through_modifiers(self) -> None:
        title = "Railway construction expands in france and the united states"
        summary = "The plans concern rail infrastructure in paris france."
        query, _, brief = image_candidate_guard.build_stock_queries(
            title,
            "Ulkomaat",
            summary=summary,
        )[0]
        mismatches = [
            "railway tracks in paris united states",
            "railway tracks in lyon northern france",
        ]
        controls = [
            "railway tracks and rail infrastructure in rural france",
            "railway tracks and rail infrastructure in northern france",
        ]

        for index, alt in enumerate(mismatches):
            with self.subTest(mismatch=alt):
                candidate = {
                    "id": f"paired-mismatch-{index}",
                    "alt": alt,
                    "photo_page": "https://unsplash.com/photos/railway-track-pairMismatch",
                }
                decision = image_candidate_guard.score_image_candidate(
                    candidate,
                    intent=brief.intent,
                    query=query,
                    title=title,
                    summary=summary,
                    category="Ulkomaat",
                    provider="unsplash",
                )
                judge = image_candidate_guard.judge_visual_candidate(
                    candidate,
                    brief=brief,
                    provider="unsplash",
                )
                self.assertFalse(decision.accepted)
                self.assertIn("location lacks article support", "; ".join(decision.reasons))
                self.assertFalse(judge.accepted)
                self.assertTrue(judge.hard_fail)

        for index, alt in enumerate(controls):
            with self.subTest(control=alt):
                candidate = {
                    "id": f"paired-control-{index}",
                    "alt": alt,
                    "photo_page": "https://unsplash.com/photos/railway-track-pairControl",
                }
                decision = image_candidate_guard.score_image_candidate(
                    candidate,
                    intent=brief.intent,
                    query=query,
                    title=title,
                    summary=summary,
                    category="Ulkomaat",
                    provider="unsplash",
                )
                judge = image_candidate_guard.judge_visual_candidate(
                    candidate,
                    brief=brief,
                    provider="unsplash",
                )
                self.assertTrue(decision.accepted)
                self.assertTrue(judge.accepted)
                self.assertFalse(judge.hard_fail)

    def test_prompt_version_marks_grounded_v3_policy(self) -> None:
        self.assertEqual(
            image_candidate_guard.PROMPT_VERSION,
            "image-flow-v3-grounded-2026-09-02",
        )

    def test_generated_query_cannot_supply_article_truth_or_candidate_metadata(self) -> None:
        title = "Rahastoyhtiöiden sisäpiirirekisterivelvoitetta halutaan keventää"
        summary = "Ala vaatii hallinnollisen velvoitteen poistamista."
        content = "Muutos koskisi kansallista finanssisääntelyä."

        queries = image_candidate_guard.build_stock_queries(
            title,
            "Talous",
            summary=summary,
            content=content,
            primary_query="winter weather",
        )
        self.assertNotIn("winter weather", [query for query, _, _ in queries])

        intent = image_candidate_guard.build_image_intent(
            title, "Talous", summary=summary, content=content
        )
        decision = image_candidate_guard.score_image_candidate(
            {"id": "metadata-missing"},
            intent=intent,
            query="financial regulation documents",
            title=title,
            summary=summary,
            content=content,
            provider="unsplash",
        )
        self.assertFalse(decision.accepted)
        self.assertIn("no semantic metadata", "; ".join(decision.reasons))

    def test_transformed_provider_urls_have_one_canonical_asset_identity(self) -> None:
        unsplash_a = {
            "url": (
                "https://images.unsplash.com/photo-1511803471753-da23b1a92d4b"
                "?crop=entropy&fm=jpg&w=1080"
            )
        }
        unsplash_b = {
            "url_thumb": (
                "https://images.unsplash.com/photo-1511803471753-da23b1a92d4b"
                "?fit=crop&fm=webp&q=70&w=400"
            )
        }
        pexels_a = {
            "url": "https://images.pexels.com/photos/1234567/pexels-photo-1234567.jpeg?w=1920"
        }
        pexels_b = {
            "thumb_url": "https://images.pexels.com/photos/1234567/pexels-photo-1234567.jpeg?h=350"
        }

        self.assertEqual(
            image_state.canonical_image_identity("unsplash", unsplash_a),
            image_state.canonical_image_identity("unsplash", unsplash_b),
        )
        self.assertEqual(
            image_state.canonical_image_identity("pexels", pexels_a),
            image_state.canonical_image_identity("pexels", pexels_b),
        )

    def test_real_finance_packet_audit_flags_unsupported_intent_and_candidate(self) -> None:
        row = audit_image_flow.audit_packet(FINANCE_PACKET, FINANCE_ARTICLE)

        self.assertEqual(row["status"], "flag")
        reason = str(row["reason"])
        self.assertIn("unsupported stored intent", reason)
        self.assertIn("winter", reason)
        self.assertIn("unrelated", reason)

    def test_collection_audit_flags_transformed_duplicate_on_unrelated_headlines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            first = posts / "2026-09-02-finance.md"
            second = posts / "2026-09-02-rail.md"
            first.write_text(
                "---\n"
                'title: "Rahastoyhtiöiden sääntelyä muutetaan"\n'
                "date: 2026-09-02T12:00:00+00:00\n"
                "categories:\n  - Talous\n"
                'description: "Finanssisääntelyä ja rekisterivelvoitetta muutetaan."\n'
                'image: "https://images.unsplash.com/photo-1511803471753-da23b1a92d4b?w=1080"\n'
                'image_source_url: "https://unsplash.com/photos/rxLGSOM0e3U?utm_source=test"\n'
                'image_source: "unsplash"\n'
                'image_candidate_id: "rxLGSOM0e3U"\n'
                "---\n\nRahastoyhtiöiden hallinnollinen velvoite muuttuu.\n",
                encoding="utf-8",
            )
            second.write_text(
                "---\n"
                'title: "Karjalan radan rahoitusta lisätään"\n'
                "date: 2026-09-02T13:00:00+00:00\n"
                "categories:\n  - Kotimaa\n"
                'description: "Rautatien parantamiseen esitetään rahoitusta."\n'
                'image: "https://images.unsplash.com/photo-1511803471753-da23b1a92d4b?fm=webp&w=400"\n'
                'image_source_url: "https://unsplash.com/photos/snowy-fence-rxLGSOM0e3U"\n'
                'image_source: "unsplash"\n'
                'image_candidate_id: "rxLGSOM0e3U"\n'
                "---\n\nRataverkon rakennustyöt voivat alkaa ensi vuonna.\n",
                encoding="utf-8",
            )

            with patch.object(audit_image_flow, "POSTS_DIR", posts):
                rows = audit_image_flow.audit_recent(2)

        reasons = "\n".join(str(row["reason"]) for row in rows)
        self.assertIn("duplicate canonical image", reasons)


if __name__ == "__main__":
    unittest.main()
