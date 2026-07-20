#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    from .category_guard import category_text, contains_token, protect_business_category
except ImportError:  # pragma: no cover
    from category_guard import category_text, contains_token, protect_business_category


class CategoryGuardTests(unittest.TestCase):
    def test_short_ai_keyword_does_not_match_asiakkaille_or_aiemmin(self) -> None:
        self.assertFalse(contains_token("asiakkaille kaksi asiaa", "ai"))
        self.assertFalse(contains_token("huonommin kuin koskaan aiemmin", "ai"))
        self.assertTrue(contains_token("AI muuttaa ohjelmistoalaa", "ai"))

    def test_foreign_token_does_not_match_inside_tilastohistorian(self) -> None:
        self.assertFalse(contains_token("tilastohistorian aikana", "iran"))
        self.assertTrue(contains_token("Iranin sodan vaikutukset", "iran"))

    def test_business_override_requires_multiple_signal_groups(self) -> None:
        self.assertEqual(
            protect_business_category(
                "Teknologia",
                "Polttoaineyhtiö Nesteen tulos kasvoi ja analyytikko arvioi myyntimarginaalia.",
            ),
            "Talous",
        )
        self.assertEqual(
            protect_business_category("Teknologia", "Yhtiö julkaisi uuden puhelimen."),
            "Teknologia",
        )

    def test_retained_iphone_packet_keeps_explicit_technology_category(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parent
            / "queues/staged/published/20260719T170121Z_452931fc1d.json"
        )
        retained = json.loads(fixture_path.read_text(encoding="utf-8"))
        text = " ".join(
            [
                category_text(retained["original_article"]),
                category_text(retained["packet"]),
                category_text(retained["payload"]),
            ]
        )

        self.assertEqual(retained["packet"]["category"], "Teknologia")
        self.assertEqual(retained["payload"]["category"], "Teknologia")
        self.assertEqual(retained["article"]["category"], "Talous")
        self.assertEqual(protect_business_category("Teknologia", text), "Teknologia")

    def test_generic_company_market_terms_do_not_steal_specialist_categories(self) -> None:
        samples = {
            "Kulttuuri": "Yhtiö tuo uuden dokumenttielokuvan markkinoille syksyllä.",
            "Tiede": "Yhtiö tuo tutkimusryhmän uuden mittalaitteen markkinoille.",
            "Urheilu": "Yhtiö tuo uuden juoksukengän markkinoille ennen kisakautta.",
        }

        for category, text in samples.items():
            with self.subTest(category=category):
                self.assertEqual(protect_business_category(category, text), category)

    def test_tulossa_does_not_count_as_a_business_result_signal(self) -> None:
        self.assertEqual(
            protect_business_category(
                "Kotimaa",
                "Ravintolapäällikkö kertoi poliisin olevan tulossa paikalle.",
            ),
            "Kotimaa",
        )
        self.assertEqual(
            protect_business_category(
                "Teknologia",
                "Yhtiön tulos kasvoi ja investoinnit vauhdittivat myyntiä.",
            ),
            "Talous",
        )

    def test_retained_macroeconomy_candidate_routes_to_talous(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parent
            / "queues/staged/published/20260711T203153Z_b15231a0f0.json"
        )
        retained = json.loads(fixture_path.read_text(encoding="utf-8"))
        original = retained["original_article"]
        text = " ".join(
            [
                str(original.get("title") or ""),
                str(original.get("description") or ""),
                str(original.get("research") or ""),
            ]
        )

        self.assertEqual(retained["packet"]["packet_id"], "20260711T203153Z_b15231a0f0")
        self.assertEqual(protect_business_category("Ulkomaat", text), "Talous")

    def test_retained_household_finance_candidate_routes_to_talous(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parent
            / "queues/staged/published/20260713T061121Z_40f48c408f.json"
        )
        retained = json.loads(fixture_path.read_text(encoding="utf-8"))
        original = retained["original_article"]
        text = " ".join(
            [
                str(original.get("title") or ""),
                str(original.get("description") or ""),
                str(original.get("research") or ""),
            ]
        )

        self.assertEqual(retained["packet"]["packet_id"], "20260713T061121Z_40f48c408f")
        self.assertEqual(protect_business_category("Kotimaa", text), "Talous")

    def test_retained_immigration_packet_is_not_stolen_by_incidental_terms(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parent
            / "queues/staged/published/20260712T191123Z_48bdfbec17.json"
        )
        retained = json.loads(fixture_path.read_text(encoding="utf-8"))
        text = " ".join(
            [
                str(retained["original_article"].get("research") or ""),
                str(retained["payload"].get("content") or ""),
            ]
        )

        self.assertEqual(retained["packet"]["packet_id"], "20260712T191123Z_48bdfbec17")
        self.assertIn("yrityksiin", text)
        self.assertIn("kasvavan", text)
        self.assertEqual(protect_business_category("Ulkomaat", text), "Ulkomaat")

    def test_single_economy_term_does_not_steal_genuine_science_or_non_business(self) -> None:
        self.assertEqual(
            protect_business_category(
                "Tiede",
                "Tutkijat analysoivat inflaation vaikutusta solujen aineenvaihduntaan.",
            ),
            "Tiede",
        )
        self.assertEqual(
            protect_business_category(
                "Kotimaa",
                "Ravintolapäällikkö kertoi poliisin olevan tulossa paikalle.",
            ),
            "Kotimaa",
        )
        self.assertEqual(
            protect_business_category(
                "Tiede",
                "Tutkijat analysoivat finanssivarallisuutta uudella tilastomenetelmällä.",
            ),
            "Tiede",
        )


if __name__ == "__main__":
    unittest.main()
