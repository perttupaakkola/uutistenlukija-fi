#!/usr/bin/env python3
from __future__ import annotations

import unittest

from story_packet import build_story_packet


class StoryPacketTests(unittest.TestCase):
    def test_irrelevant_research_block_is_dropped_in_favor_of_fallback(self) -> None:
        article = {
            "title": 'Vakavia syytöksiä FBI:n johtajan ryyppäämisestä – Kash Patel kiistää: "Nähdään oikeudessa"',
            "description": "FBI:n johtaja Kash Patel on kiistänyt häntä koskevat väitteet runsaasta alkoholinkäytöstä, jotka nousivat esiin oikeusasiakirjoissa.",
            "source": "MTV Uutiset",
            "link": "https://www.mtvuutiset.fi/artikkeli/vakavia-syytoksia-fbi-n-johtajan-ryyppaamisesta-kash-patel-kiistaa-nahdaan-oikeudessa/9326240",
            "category_hint": "Kotimaa",
            "research": "[Lähde: Yle]\nAinakin neljä ihmistä on kuollut Washingtonin ampumisessa, kertoo poliisi.",
        }

        packet = build_story_packet(article)

        self.assertEqual(packet["category_hint"], "Ulkomaat")
        self.assertEqual(packet["source_names"], ["MTV Uutiset"])
        self.assertIn("Kash Patel", packet["source_text"])
        self.assertNotIn("Washingtonin ampumisessa", packet["source_text"])

    def test_relevant_research_block_is_preserved(self) -> None:
        article = {
            "title": "Suomen vienti kasvaa nopeasti Saksaan",
            "description": "Viennin kasvu on ollut alkuvuonna odotettua nopeampaa.",
            "source": "Yle",
            "link": "https://yle.fi/a/74-00000001",
            "category_hint": "Talous",
            "research": "[Lähde: Yle]\nSuomen vienti Saksaan on kasvanut alkuvuonna nopeasti, ja yritykset odottavat trendin jatkuvan kesällä.",
        }

        packet = build_story_packet(article)

        self.assertEqual(packet["category_hint"], "Talous")
        self.assertIn("Suomen vienti Saksaan", packet["source_text"])
        self.assertIn("Yle", packet["source_names"]) 


if __name__ == "__main__":
    unittest.main()
