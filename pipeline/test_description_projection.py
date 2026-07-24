#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

try:
    from . import publish_preflight, publisher
    from .description_projection import (
        PUBLIC_DESCRIPTION_LIMIT,
        WEAK_DESCRIPTION_ENDINGS,
        project_public_description,
    )
except ImportError:  # pragma: no cover - direct execution from pipeline cwd
    import publish_preflight
    import publisher
    from description_projection import (
        PUBLIC_DESCRIPTION_LIMIT,
        WEAK_DESCRIPTION_ENDINGS,
        project_public_description,
    )


FIXTURE_DIR = Path(__file__).resolve().parent / "queues" / "staged" / "published"
MONICA_FIXTURES = {
    "20260721T144122Z_4ae648f533.json": (
        "Varusmiesliitto pitää tärkeänä Vekaranjärvellä kuolleen varusmiehen "
        "tapauksen perusteellista selvittämistä."
    ),
    "20260721T133121Z_46c6c1b50a.json": (
        "Turun kaupungin mukaan lapsilla tulee olla Seikkailupuiston "
        "vesileikkialueella vähintään alushousut."
    ),
    "20260721T113126Z_38482fb74e.json": (
        "Hallihankkeen taustayhtiö uskoo yhä voivansa saada valtiolta tukea "
        "myöhemmin."
    ),
    "20260721T120143Z_c2d8af1a17.json": (
        "Korkeakoulujen lisähauissa on tarjolla entistä enemmän aloituspaikkoja."
    ),
    "20260721T110134Z_31d16025de.json": (
        "Libanonin armeija on aloittanut joukkojensa sijoittamisen "
        "Etelä-Libanonin kokeilualueelle."
    ),
}


def _published_description(description: str) -> str:
    markdown = publisher._article_to_markdown(
        {
            "title": "Kuvausrajan testi",
            "category": "Kotimaa",
            "content": "Testisisältö.",
            "description": description,
        },
        "2026-07-24T00:00:00+00:00",
    )
    match = re.search(r'^description: "(.*)"$', markdown, flags=re.MULTILINE)
    if match is None:
        raise AssertionError("Publisher omitted description front matter")
    return match.group(1)


class DescriptionProjectionTests(unittest.TestCase):
    def test_exact_varusmiesliitto_and_monica_terminal_fixtures(self) -> None:
        for filename, expected in MONICA_FIXTURES.items():
            with self.subTest(filename=filename):
                record = json.loads((FIXTURE_DIR / filename).read_text(encoding="utf-8"))
                source = record["article"]["description"]

                projected = project_public_description(source)

                self.assertEqual(projected, expected)
                self.assertLessEqual(len(projected), PUBLIC_DESCRIPTION_LIMIT)
                self.assertFalse(projected.endswith("…"))

    def test_word_boundary_fallback_reserves_one_character_for_ellipsis(self) -> None:
        prefix = ("Taustatieto " * 11) + "olennainen"
        source = prefix + " " + ("katkeamaton" * 20)

        projected = project_public_description(source)

        self.assertEqual(projected, prefix + "…")
        self.assertEqual(projected.count("…"), 1)
        self.assertLessEqual(len(projected), PUBLIC_DESCRIPTION_LIMIT)

    def test_fallback_strips_each_frozen_weak_ending_as_a_whole_token(self) -> None:
        for weak_ending in sorted(WEAK_DESCRIPTION_ENDINGS):
            with self.subTest(weak_ending=weak_ending):
                source = (
                    ("Taustatieto " * 11)
                    + weak_ending
                    + " "
                    + ("katkeamaton" * 20)
                )

                projected = project_public_description(source)

                self.assertEqual(projected, ("Taustatieto " * 11).rstrip() + "…")

    def test_fallback_rechecks_chained_weak_endings_and_drops_punctuation(self) -> None:
        for punctuation in (",", ";", ":", "-", "–", "—"):
            with self.subTest(punctuation=punctuation):
                source = (
                    ("Taustatieto " * 10)
                    + f"lisätieto{punctuation} mutta että "
                    + ("katkeamaton" * 20)
                )

                projected = project_public_description(source)

                self.assertEqual(
                    projected,
                    (("Taustatieto " * 10) + "lisätieto").rstrip() + "…",
                )
                self.assertNotRegex(projected, r"[.,;:!?–—-]\s*…$")

    def test_sentence_projection_preserves_terminal_punctuation_and_quote(self) -> None:
        for closing_quote in ('"', "”", "’", "»"):
            with self.subTest(closing_quote=closing_quote):
                sentence = (
                    "Ensimmäinen virke sisältää riittävästi olennaista tietoa "
                    f"lukijan päätöksen tueksi.{closing_quote}"
                )
                source = sentence + " " + ("Seuraava virke jatkuu rajan yli " * 8)

                projected = project_public_description(source)

                self.assertEqual(projected, sentence)
                self.assertTrue(projected.endswith(f".{closing_quote}"))
                self.assertNotIn("…", projected)

    def test_sentence_below_usefulness_floor_does_not_win(self) -> None:
        source = "Liian lyhyt virke. " + ("Taustatieto " * 20)

        projected = project_public_description(source)

        self.assertTrue(projected.endswith("…"))
        self.assertGreaterEqual(len(projected), 40)
        self.assertNotEqual(projected, "Liian lyhyt virke.")

    def test_short_description_is_only_whitespace_normalized(self) -> None:
        source = "  Lyhyt   kuvaus\n säilyy kokonaisena.  "

        self.assertEqual(
            project_public_description(source),
            "Lyhyt kuvaus säilyy kokonaisena.",
        )

    def test_finnish_unicode_words_remain_complete(self) -> None:
        prefix = ("Yööljyä " * 16) + "käytetään"
        source = prefix + " " + ("äärimmäisenpitkä" * 20)

        projected = project_public_description(source)

        self.assertEqual(projected, prefix + "…")
        self.assertLessEqual(len(projected), PUBLIC_DESCRIPTION_LIMIT)
        self.assertNotIn("äärimmäisenpit", projected)

    def test_publisher_and_preflight_use_the_same_projection(self) -> None:
        self.assertIs(
            publisher.project_public_description,
            publish_preflight.project_public_description,
        )
        record = json.loads(
            (FIXTURE_DIR / "20260721T144122Z_4ae648f533.json").read_text(
                encoding="utf-8"
            )
        )
        description = record["article"]["description"]

        self.assertEqual(
            _published_description(description),
            project_public_description(description),
        )

    def test_preflight_only_counts_urls_preserved_by_public_projection(self) -> None:
        visible_url = "https://visible.test/story"
        hidden_url = "https://hidden.test/report"
        first_sentence = (
            f"Ensimmäinen lähde {visible_url} näkyy julkisessa kuvauksessa."
        )
        description = (
            first_sentence
            + " "
            + ("Toinen virke jatkuu tarkoituksella rajan yli " * 5)
            + hidden_url
        )

        public_urls = publish_preflight._public_source_urls(
            {"description": description}
        )

        self.assertEqual(project_public_description(description), first_sentence)
        self.assertIn(visible_url, public_urls)
        self.assertNotIn(hidden_url, public_urls)


if __name__ == "__main__":
    unittest.main()
