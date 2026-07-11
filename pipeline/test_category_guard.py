#!/usr/bin/env python3
from __future__ import annotations

import unittest

try:
    from .category_guard import contains_token, protect_business_category
except ImportError:  # pragma: no cover
    from category_guard import contains_token, protect_business_category


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


if __name__ == "__main__":
    unittest.main()
