#!/usr/bin/env python3
from __future__ import annotations

import unittest
import json
from pathlib import Path

try:
    from .story_packet import build_story_packet, selected_source_provenance_error
except ImportError:  # pragma: no cover
    from story_packet import build_story_packet, selected_source_provenance_error


class StoryPacketTests(unittest.TestCase):
    def test_retained_packet_rejects_seed_url_for_different_selected_source(self) -> None:
        fixture = Path(__file__).resolve().parent / "queues/staged/published/20260712T185125Z_dd3d7edcb5.json"
        retained = json.loads(fixture.read_text(encoding="utf-8"))

        self.assertEqual(retained["packet"]["source_names"], ["Stara", "Stara", "Stara"])
        self.assertIn("tivi.fi", retained["packet"]["source_urls"][0])
        self.assertIn("seed provenance cannot substitute", selected_source_provenance_error(retained["packet"]))

    def test_selected_blocks_publish_one_consistent_source_tuple(self) -> None:
        url = "https://www.stara.fi/uutinen"
        article = {
            "title": "Sähkön futuurihinnat nousivat loppuvuodelle",
            "description": "Futuurihintojen vertailu osoittaa sähkömarkkinan odotusten nousseen.",
            "source": "Tivi",
            "link": "https://www.tivi.fi/eri-uutinen",
            "category_hint": "Talous",
            "research": f"[Lähde: Stara | URL: {url}]\n" + ("Sähkön futuurihinta nousi markkinoilla loppuvuodelle. " * 30),
        }

        packet = build_story_packet(article)

        self.assertEqual(packet["source_selection_outcome"], "usable_source_packet")
        self.assertEqual(packet["selected_source"], {"name": "Stara", "url": url, "domain": "stara.fi"})
        self.assertEqual(packet["source_urls"], [url])

    def test_same_bbc_article_aliases_collapse_before_source_accounting(self) -> None:
        rss_url = (
            "https://www.bbc.co.uk/news/articles/c70gkg62w0ro"
            "?at_medium=RSS&at_campaign=rss"
        )
        canonical_url = "https://www.bbc.com/news/articles/c70gkg62w0ro"
        article = {
            "title": "D4vdin oikeudenkäynti etenee Los Angelesissa",
            "description": (
                "Tuomari katsoi D4vdin tapauksen näytön riittävän "
                "oikeudenkäyntiin."
            ),
            "source": "BBC World",
            "link": rss_url,
            "category_hint": "Ulkomaat",
            "research": (
                f"[Lähde: BBC World | URL: {rss_url}]\n"
                + (
                    "D4vdin oikeudenkäynti etenee Los Angelesissa tuomarin "
                    "näyttöratkaisun jälkeen. "
                )
                * 20
                + "\n\n---\n\n"
                + f"[Lähde: BBC | URL: {canonical_url}]\n"
                + (
                    "Los Angelesin tuomari määräsi D4vdin tapauksen "
                    "etenemään oikeudenkäyntiin. "
                )
                * 20
            ),
        }

        packet = build_story_packet(article)

        self.assertEqual(len(packet["clean_source_blocks"]), 1)
        self.assertEqual(packet["source_urls"], [rss_url])
        self.assertEqual(
            {
                block["source_url"]
                for block in packet["clean_source_blocks"]
                if "bbc." in block.get("source_url", "")
            },
            {rss_url},
        )
        identities = {
            block["source_identity"]
            for block in packet["clean_source_blocks"]
            if "bbc." in block.get("source_url", "")
        }
        self.assertEqual(len(identities), 1)
        self.assertEqual(packet["selected_source_provenance_error"], "")

    def test_missing_selected_source_url_is_provenance_invalid(self) -> None:
        article = {
            "title": "Sähkön futuurihinnat nousivat loppuvuodelle",
            "description": "Futuurihintojen vertailu osoittaa sähkömarkkinan odotusten nousseen.",
            "source": "Tivi",
            "link": "https://www.tivi.fi/eri-uutinen",
            "category_hint": "Talous",
            "research": "[Lähde: Stara]\n" + ("Sähkön futuurihinta nousi markkinoilla loppuvuodelle. " * 30),
        }

        packet = build_story_packet(article)

        self.assertEqual(packet["source_selection_outcome"], "provenance_invalid")
        self.assertIn("missing name/url/domain", packet["selected_source_provenance_error"])

    def test_selected_source_url_domain_mismatch_is_rejected(self) -> None:
        packet = {
            "clean_source_blocks": [
                {
                    "source": "Stara",
                    "source_url": "https://www.stara.fi/uutinen",
                    "source_domain": "tivi.fi",
                    "text": "Valittu lähdekatkelma.",
                    "word_count": 3,
                }
            ]
        }

        self.assertEqual(selected_source_provenance_error(packet), "selected source URL/domain mismatch")
    def test_oululainen_restaurant_business_story_is_not_ai_or_iran_substring_match(self) -> None:
        article = {
            "title": "Oululainen ravintoloitsija haukkuu päättäjät ja haluaa sanoa asiakkaille kaksi asiaa",
            "description": "Ravintoloilla menee huonommin kuin koskaan aiemmin tilastohistorian aikana. Pitkän linjan yrittäjä kertoo, mitä sille pitäisi tehdä.",
            "source": "Yle Uutiset",
            "link": "https://yle.fi/a/74-20235833?origin=rss",
            "_guessed_category": "Teknologia",
            "research": "[Lähde: Yle Uutiset]\nMajoitus- ja ravintola-alalla tuli vireille konkursseja enemmän kuin koskaan. Yrittäjä arvioi alan kannattavuutta.",
        }

        packet = build_story_packet(article)

        self.assertEqual(packet["category_hint"], "Talous")

    def test_neste_results_override_mixed_technology_feed_hint(self) -> None:
        article = {
            "title": "Nesteen tuloksen odotetaan pomppaavan 227 prosenttia – Analyytikko arvioi kasvun väliaikaiseksi",
            "description": "Polttoaineyhtiö Nesteen luvuissa näkyy valtava kasvu ja uusiutuvien polttoaineiden myyntimarginaali.",
            "source": "Tekniikka & Talous",
            "link": "https://www.tekniikkatalous.fi/uutiset/example",
            "category_hint": "Teknologia",
            "_guessed_category": "Teknologia",
            "research": "[Lähde: Yle]\nNeste kasvatti vertailukelpoista käyttökatettaan. Analyytikon mukaan yhtiön tulos ylitti markkinaennusteet.",
        }

        packet = build_story_packet(article)

        self.assertEqual(packet["category_hint"], "Talous")

    def test_irrelevant_research_block_is_dropped_in_favor_of_fallback(self) -> None:
        article = {
            "title": 'Kash Patel kiistää väitteet alkoholinkäytöstä',
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

    def test_guessed_foreign_category_survives_without_feed_hint(self) -> None:
        article = {
            "title": "Ben Carroll nousi Victorian uudeksi pääministeriksi",
            "description": "Työväenpuolue valitsi Carrollin johtajakseen osavaltion vallanvaihdoksessa.",
            "source": "The Conversation",
            "link": "https://example.com/victoria-premier",
            "_guessed_category": "Ulkomaat",
            "research": (
                "[Lähde: The Conversation | URL: https://example.com/victoria-premier]\n"
                + "Victorian työväenpuolue valitsi Ben Carrollin uudeksi johtajakseen. " * 20
            ),
        }

        packet = build_story_packet(article)

        self.assertEqual(packet["category_hint"], "Ulkomaat")



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

    def test_school_police_incident_does_not_keep_tiede_hint(self) -> None:
        article = {
            "title": "Poliisi otti kiinni Samkin tiloissa liikkuneen aseistautuneen henkilön",
            "description": "Poliisi kertoo ottaneensa kiinni Satakunnan ammattikorkeakoulun kampuksella maastopuvussa liikkuneen henkilön.",
            "source": "Etelä-Suomen Sanomat",
            "link": "https://www.ess.fi/example",
            "category_hint": "Tiede",
            "research": "[Lähde: ESS]\nPoliisi on ottanut kiinni Porissa Satakunnan ammattikorkeakoulussa henkilön, jonka epäillään liikkuneen tiloissa aseistautuneena.",
        }

        packet = build_story_packet(article)

        self.assertEqual(packet["category_hint"], "Kotimaa")

    def test_school_crime_stats_do_not_keep_tiede_hint_from_tutkimuslaitos(self) -> None:
        article = {
            "title": "Opettaja kertoo levottomuuden lisääntyneen koulussa – oppilaitoksista tehtiin yli 6 500 rikosilmoitusta vuodessa",
            "description": "Poliisihallituksen tilastojen mukaan oppi- ja tutkimuslaitoksista tehtiin viime vuonna yli 6 500 rikosilmoitusta.",
            "source": "MTV Uutiset",
            "link": "https://www.mtvuutiset.fi/example",
            "category_hint": "Tiede",
            "research": "[Lähde: MTV]\nPoliisihallituksen tilastoissa oppi- ja tutkimuslaitokset kattavat päiväkoteja, kouluja ja yliopistoja. Yleisin tutkittu rikosnimike oli pahoinpitely.",
        }

        packet = build_story_packet(article)

        self.assertEqual(packet["category_hint"], "Kotimaa")

    def test_riihimaki_explosive_police_story_does_not_keep_tiede_hint(self) -> None:
        article = {
            "title": "Poliisi sai Riihimäen räjähteestä ilmoituksen jo huhtikuussa",
            "description": "Hämeen poliisin mukaan pellolta löytynyt räjähde oli todennäköisesti sama, josta poliisille ilmoitettiin jo aiemmin.",
            "source": "MTV Uutiset",
            "link": "https://www.mtvuutiset.fi/example",
            "category_hint": "Tiede",
            "research": "[Lähde: MTV]\nPoliisi selvittää Riihimäen jäähallin läheltä löytyneen räjähteen tapahtumaketjua. Löydöstä on tehty ilmoitus valtakunnan syyttäjän toimistoon.",
        }

        packet = build_story_packet(article)

        self.assertEqual(packet["category_hint"], "Kotimaa")

    def test_research_story_can_keep_tiede_hint_with_school_terms(self) -> None:
        article = {
            "title": "Yliopiston tutkimus selvitti koulujen sisäilman vaikutuksia",
            "description": "Tutkijat analysoivat laajan aineiston ja julkaisivat tulokset tieteellisessä lehdessä.",
            "source": "Yle Tiede",
            "link": "https://yle.fi/example",
            "category_hint": "Tiede",
            "research": "[Lähde: Yle Tiede]\nTutkimuksessa selvitettiin koulujen sisäilman vaikutuksia oppilaiden hyvinvointiin usean vuoden aineistolla.",
        }

        packet = build_story_packet(article)

        self.assertEqual(packet["category_hint"], "Tiede")

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

    def test_specific_drone_trial_claim_drops_adjacent_old_drone_blocks(self) -> None:
        article = {
            "title": "Drooneja havainnoidaan uudella tavalla Kaakkois-Suomessa – Rajavartiolaitos ja yritykset sopivat havainnointijärjestelmän koekäytöstä",
            "description": "",
            "source": "Yle",
            "link": "https://yle.fi/a/example",
            "category_hint": "Kotimaa",
            "research": "\n\n".join([
                "[Lähde: Yle]\nSuomen ilmavoimien hävittäjät ovat jyrisseet sunnuntaiaamuna Kaakkois-Suomen taivaalla. Lennot liittyvät drooneihin, mutta drooneja ei ole tullut Suomen puolelle.",
                "[Lähde: ksml.fi]\nMikko Hyppönen arvioi ukrainalaisten AN196-droonien kantamaa ja aiempia harhautumisia Suomenlahden alueella.",
            ]),
        }

        packet = build_story_packet(article)

        self.assertEqual(packet["clean_source_blocks"], [])
        self.assertEqual(packet["story_confidence"], 0.15)

    def test_euribor_weekday_mismatch_drops_tuesday_blocks_for_thursday_claim(self) -> None:
        article = {
            "title": "12 kuukauden euribor laski torstaina",
            "description": "Euribor-korot peilaavat epävarmuutta markkinoilla.",
            "source": "ksml.fi",
            "link": "https://www.ksml.fi/example",
            "category_hint": "Talous",
            "research": "[Lähde: ksml.fi]\nMonien suomalaisten asuntolainoissa viitekorkona käytetty 12 kuukauden euribor laski tiistaina roimasti. Vuoden euribor tippui tiistaina 3,51 prosenttiin.",
        }

        packet = build_story_packet(article)

        self.assertEqual(packet["clean_source_blocks"], [])
        self.assertEqual(packet["story_confidence"], 0.25)

    def test_strict_unsupported_claim_does_not_fall_back_to_headline_echo_description(self) -> None:
        article = {
            "title": "Rajavartiolaitos ja Elisa kokeilevat droonien havainnointijärjestelmää Kaakkois-Suomessa",
            "description": "Rajavartiolaitos ja Elisa kokeilevat droonien havainnointijärjestelmää Kaakkois-Suomessa.",
            "source": "Yle",
            "link": "https://yle.fi/a/example",
            "category_hint": "Kotimaa",
            "research": "[Lähde: Yle]\nSuomen ilmavoimien hävittäjät lensivät sunnuntaina Kaakkois-Suomen yllä aiempien droonihavaintojen vuoksi. Puolustusvoimat ei kertonut uusista yritysyhteistyöhankkeista tai järjestelmäkokeiluista.",
        }

        packet = build_story_packet(article)

        self.assertEqual(packet["clean_source_blocks"], [])

    def test_supported_specific_claim_keeps_matching_source_blocks(self) -> None:
        article = {
            "title": "Rajavartiolaitos ja Elisa kokeilevat droonien havainnointijärjestelmää Kaakkois-Suomessa",
            "description": "Sensofusion on mukana järjestelmän kokeilussa.",
            "source": "Yle",
            "link": "https://yle.fi/a/example",
            "category_hint": "Kotimaa",
            "research": "[Lähde: Yle]\nRajavartiolaitos, Elisa ja Sensofusion kokeilevat Kaakkois-Suomessa droonien havainnointijärjestelmää. Koekäyttö koskee rajaseudun valvontaa ja uusia havaintomenetelmiä.",
        }

        packet = build_story_packet(article)

        self.assertGreaterEqual(len(packet["clean_source_blocks"]), 1)
        self.assertIn("Rajavartiolaitos", packet["source_text"])
        self.assertIn("Sensofusion", packet["source_text"])

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

    def test_backfills_research_block_when_selected_packet_is_rss_thin(self) -> None:
        research_words = " ".join(["Tokmannin perustaja kritisoi markkinatilannetta"] * 46)
        article = {
            "title": "Perustaja kritisoi Tokmannia",
            "description": "Lyhyt RSS kuvaus ilman riittävää lähdepohjaa.",
            "source": "Taloussanomat",
            "link": "https://www.is.fi/taloussanomat/example",
            "category_hint": "Talous",
            "research": f"[Lähde: ksml.fi | URL: https://www.ksml.fi/uutinen]\n{research_words}",
        }

        packet = build_story_packet(article)

        self.assertGreaterEqual(packet["source_diagnostics"]["selected_source_words"], 80)
        self.assertEqual(packet["source_selection_outcome"], "usable_source_packet")
        self.assertIn("ksml.fi", packet["source_diagnostics"]["selected_sources"])

    def test_talous_packet_drops_unrelated_rich_business_context_block(self) -> None:
        finanssiala = " ".join(
            [
                "Finanssiala arvioi eläkejärjestelmän kestävyyttä ja työeläkemaksujen kehitystä.",
                "Järjestön mukaan sijoitustuotot, väestön ikääntyminen ja työllisyys vaikuttavat eläkkeiden rahoitukseen.",
                "Eläketurvan pitkän aikavälin tasapaino vaatii vakaata maksupohjaa ja selkeitä päätöksiä.",
            ]
            * 8
        )
        unrelated = " ".join(
            [
                "Yle kertoo Hormuzinsalmen kiristyneestä turvallisuustilanteesta ja presidentti Stubbin ulkopoliittisista arvioista.",
                "Öljykuljetusten häiriöt voivat vaikuttaa kansainvälisiin energiamarkkinoihin ja sotilaalliseen varautumiseen.",
            ]
            * 10
        )
        article = {
            "title": "Finanssiala arvioi eläkejärjestelmän kestävyyttä",
            "description": "Työeläkemaksut ja sijoitustuotot vaikuttavat eläkkeiden pitkän aikavälin rahoitukseen.",
            "source": "Finanssiala",
            "link": "https://www.finanssiala.fi/example",
            "category_hint": "Talous",
            "research": "\n\n---\n\n".join(
                [
                    f"[Lähde: Finanssiala]\n{finanssiala}",
                    f"[Lähde: Yle]\n{unrelated}",
                ]
            ),
        }

        packet = build_story_packet(article)

        self.assertIn("Finanssiala", packet["source_diagnostics"]["selected_sources"])
        self.assertNotIn("Yle", packet["source_diagnostics"]["selected_sources"])
        self.assertNotIn("Hormuzinsalmen", packet["source_text"])

    def test_description_tokens_can_support_source_selection(self) -> None:
        article = {
            "title": "I-P: Vaasalaispäiväkodin lasten mustelmat herättivät kysymyksiä",
            "description": "Vaasan kaupunki tarkasti yksityiseen päiväkotiin kuuluvan ryhmän toimintaa, kun lasten mustelmista ja kuhmuista kerrottiin vanhemmille.",
            "source": "Iltalehti",
            "link": "https://www.iltalehti.fi/kotimaa/example",
            "category_hint": "Kotimaa",
            "research": "[Lähde: Ilkka-Pohjalainen]\nVaasan kaupunki teki tarkastuksen yksityisen päiväkodin Nappulakedon ryhmään. Lasten mustelmat ja kuhmut herättivät vanhemmissa kysymyksiä, ja päiväkodin toiminnassa todettiin epäkohtia.",
        }

        packet = build_story_packet(article)

        self.assertGreaterEqual(packet["source_diagnostics"]["selected_source_words"], 20)
        self.assertIn("Ilkka-Pohjalainen", packet["source_diagnostics"]["selected_sources"])

    def test_marks_zero_source_packet_for_diagnostics(self) -> None:
        packet = build_story_packet({"title": "Otsikko", "description": "", "category_hint": "Talous"})

        self.assertEqual(packet["source_selection_outcome"], "zero_source_packet")
        self.assertTrue(packet["source_diagnostics"]["zero_source_packet"])


if __name__ == "__main__":
    unittest.main()
