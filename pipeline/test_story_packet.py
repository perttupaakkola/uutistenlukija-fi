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



    def test_labeled_research_keeps_coherent_multi_paragraph_source_chunks(self) -> None:
        paragraph = " ".join(
            [
                "Suomen Yrittäjät arvioi, että lomakauden siirto voisi pidentää matkailusesonkia ja lisätä palvelualojen kysyntää.",
                "Järjestön mukaan muutos vaikuttaisi yritysten työvoiman tarpeeseen, investointien kannattavuuteen ja nuorten kesätyömahdollisuuksiin.",
                "Ehdotusta perustellaan sillä, että viileämmät pohjoiset matkakohteet kiinnostavat eurooppalaisia matkailijoita yhä enemmän.",
            ]
            * 10
        )
        research = "[Lähde: Suomen Yrittäjät]\n" + "\n\n".join([paragraph] * 8)
        article = {
            "title": "Yrittäjät esittää kesälomien siirtoa talouden kasvutoimena",
            "description": "Järjestön mukaan pidempi matkailusesonki voisi vahvistaa yritysten kasvua ja työllisyyttä.",
            "source": "Suomen Yrittäjät",
            "link": "https://www.yrittajat.fi/example",
            "category_hint": "Talous",
            "research": research,
        }

        packet = build_story_packet(article)

        self.assertEqual(packet["category_hint"], "Talous")
        self.assertGreaterEqual(len(packet["clean_source_blocks"]), 2)
        self.assertGreaterEqual(sum(block["word_count"] for block in packet["clean_source_blocks"]), 300)
        self.assertTrue(all(block["source"] == "Suomen Yrittäjät" for block in packet["clean_source_blocks"]))

    def test_talous_packet_keeps_long_business_context_block_with_generic_terms(self) -> None:
        business_text = " ".join(
            [
                "Yhtiö kertoi liikevaihdon kasvaneen alkuvuonna ja tuloksen parantuneen markkinoiden elpyessä.",
                "Johto arvioi kysynnän vahvistuvan vientimarkkinoilla, mutta kustannusten nousu painaa edelleen kannattavuutta.",
                "Yritys kertoo investoivansa tuotantoon ja hakevansa kasvua uusista asiakkuuksista loppuvuoden aikana.",
            ]
            * 10
        )
        research = "\n\n".join(f"[Lähde: Kauppalehti {idx}]\n{business_text}" for idx in range(4))
        article = {
            "title": "Talouskasvu hidastui alkuvuonna",
            "description": "Yritysten markkinat elpyvät hitaasti ja investoinnit jatkuvat.",
            "source": "Kauppalehti",
            "link": "https://www.kauppalehti.fi/uutiset/example",
            "category_hint": "Talous",
            "research": research,
        }

        packet = build_story_packet(article)

        self.assertEqual(packet["category_hint"], "Talous")
        self.assertEqual(len(packet["clean_source_blocks"]), 1)
        self.assertGreaterEqual(sum(block["word_count"] for block in packet["clean_source_blocks"]), 300)
        self.assertIn("liikevaihdon", packet["source_text"])

    def test_talous_hint_survives_foreign_market_tokens(self) -> None:
        article = {
            "title": "Pörssijuhla jatkuu Wall Streetillä – Nousuhuuma ei tarttunut Nokiaan",
            "description": "Markkinat odottavat Iranin konfliktin päättyvän pian.",
            "source": "Kauppalehti",
            "link": "https://www.kauppalehti.fi/uutiset/example",
            "category_hint": "Talous",
            "research": "[Lähde: Kauppalehti]\nOsakekurssit nousivat Wall Streetillä ja öljyn hinta laski.",
        }

        packet = build_story_packet(article)

        self.assertEqual(packet["category_hint"], "Talous")

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
