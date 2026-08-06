#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest
from pathlib import Path

from quality_gate import score_article
from source_confidence_guard import source_confidence_issues


FIXTURE_DIR = Path("/home/pertt/.openclaw/workspace/projects/uutistenlukija/pipeline/queues/staged/published")
VANCE_IRAN_PACKET = FIXTURE_DIR / "20260622T144147Z_3c4e5fd7ac.json"
COLOMBIA_ELECTION_PACKET = FIXTURE_DIR / "20260623T104125Z_8d62270f9b.json"


FRESH_IRAN_DENIAL_TEXT = """
Iran's foreign ministry denied that Tehran had made new commitments on nuclear
inspectors after JD Vance said Iran had agreed to allow inspectors back into
the country. A spokesperson said any contact with the IAEA would proceed under
existing procedures, not as a new commitment.
"""


class SourceConfidenceGuardTests(unittest.TestCase):
    def _article_from_fixture(self, path: Path) -> dict:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        article = dict(data["article"])
        packet = data["packet"]
        article["source_text"] = packet.get("source_text", article.get("source_text", ""))
        return article

    def test_vance_iran_fixture_holds_when_fresh_source_denial_is_missing_from_public_copy(self):
        article = self._article_from_fixture(VANCE_IRAN_PACKET)
        article["fresh_source_text"] = FRESH_IRAN_DENIAL_TEXT

        result = score_article(article)

        self.assertFalse(result.passes)
        self.assertIn("source_confidence_denial_context_missing", result.hard_fails)

    def test_vance_iran_fixture_passes_source_confidence_when_denial_and_attribution_survive(self):
        article = self._article_from_fixture(VANCE_IRAN_PACKET)
        article["fresh_source_text"] = FRESH_IRAN_DENIAL_TEXT
        article["title"] = "BBC: Iran kiistää uudet ydintarkastussitoumukset Vancen lausunnon jälkeen"
        article["summary"] = (
            "BBC:n mukaan Iran kiistää JD Vancen väitteen uusista ydintarkastussitoumuksista "
            "ja sanoo mahdollisen IAEA-yhteydenpidon etenevän nykyisten menettelyjen mukaan."
        )
        article["summary_bullets"] = [
            "BBC:n mukaan Iran kiistää Vancen väitteen uusista ydintarkastussitoumuksista.",
            "Iranin mukaan mahdollinen yhteydenpito IAEA:n kanssa etenisi nykyisten menettelyjen mukaan.",
        ]
        article["key_points"] = list(article["summary_bullets"])
        article["content"] = (
            "BBC:n mukaan Iran kiistää Yhdysvaltain varapresidentti JD Vancen väitteen siitä, "
            "että Teheran olisi tehnyt uusia sitoumuksia ydintarkastajien päästämisestä maahan. "
            "Iranin ulkoministeriön mukaan mahdollinen yhteydenpito IAEA:n kanssa etenisi nykyisten "
            "menettelyjen mukaan, eikä kyse olisi uudesta lupauksesta.\n\n"
            + article["content"].split("\n\n", 1)[1]
        )

        result = score_article(article)

        self.assertNotIn("source_confidence_denial_context_missing", result.hard_fails)

    def test_colombia_election_fixture_preserves_preliminary_not_conceded_context(self):
        article = self._article_from_fixture(COLOMBIA_ELECTION_PACKET)

        result = score_article(article)

        self.assertNotIn("source_confidence_election_uncertainty_missing", result.hard_fails)

    def test_talous_ydintehtava_is_not_misclassified_as_nuclear_geopolitics(self):
        article = {
            "category": "Talous",
            "title": "Julkisen talouden tehtävät",
            "summary": "Haastateltava arvioi julkisen sektorin tehtäviä.",
            "content": "Haastateltavan mukaan maanpuolustus on julkisen talouden ydintehtävä.",
            "source_text": (
                "Jokainen ymmärtää, että maanpuolustus on julkisen talouden ydintehtävä, "
                "haastateltava sanoi. Julkisen terveydenhuollon tarvetta en kiistä."
            ),
        }

        self.assertEqual(source_confidence_issues(article), [])

    def test_viranomainen_and_non_denial_ristiriita_do_not_activate_iran_guard(self):
        article = {
            "category": "Kotimaa",
            "title": "Ruokaviraston viestintää arvioitiin Kaakkois-Suomessa",
            "summary": "Yle tarkasteli viranomaisviestinnän resursointia.",
            "content": "Ylen analyysi käsitteli sikaruttotiedotuksen järjestämistä.",
            "source_text": (
                "Ylen analyysin mukaan viranomainen sanoi, että viesteissä saattoi "
                "olla ristiriita. Ristiriita koski viestinnän ajoitusta."
            ),
        }

        self.assertEqual(source_confidence_issues(article), [])


if __name__ == "__main__":
    unittest.main()
