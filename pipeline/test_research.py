import unittest
from unittest.mock import patch

try:
    from . import research
except ImportError:  # pragma: no cover - direct execution from pipeline cwd
    import research


class ResearchFallbackTests(unittest.TestCase):
    def test_talous_rss_fallback_promotes_labeled_source(self):
        article = {
            "title": "Wall Street avautui alamäkeen inflaatiolukujen jälkeen",
            "category_hint": "Talous",
            "source": "Taloussanomat",
            "description": "Wall Street avautui tiistaina laskuun inflaatiolukujen jälkeen. Sijoittajat arvioivat korko-odotuksia ja suurten yhtiöiden tulosnäkymiä markkinoilla. Pörssin pääindeksit painuivat, kun uudet luvut muuttivat odotuksia keskuspankin seuraavista ratkaisuista ja yritysten rahoituskustannuksista. Analyytikot seuraavat erityisesti kuluttajahintoja, korkoeroja, teknologiayhtiöiden tulosennusteita ja pankkien luotonantoa, koska ne vaikuttavat sekä riskinottoon että yritysten investointeihin.",
            "link": "https://example.com/talous",
        }
        self.assertTrue(research._usable_talous_rss_fallback(article, article["description"]))

    def test_promotional_talous_rss_fallback_is_not_promoted(self):
        article = {"title": "Kurkista finanssialan arkeen", "category_hint": "Talous", "source": "Finanssiala"}
        text = "Ota Finanssialalle-Instagram seurantaan ja vinkkaa kaverille. Liity mukaan seuraamaan kohokohtia ja uratarinoita."
        self.assertFalse(research._usable_talous_rss_fallback(article, text))


    def test_talous_thin_original_fallback_is_bounded_and_labeled(self):
        article = {
            "title": "Yrittäjä arvioi tilansa talousnäkymiä",
            "category_hint": "Talous",
            "source": "Suomen Yrittäjät",
            "link": "https://www.yrittajat.fi/uutiset/esimerkki",
            "description": "",
        }
        thin_body = (
            "Maatilayrittäjä kertoo investointien lykkääntyneen kustannuspaineen vuoksi. "
            "Tilalla arvioidaan rehukustannusten, lainanhoitokulujen ja kysynnän muutosten "
            "vaikuttavan loppuvuoden tulokseen. Yritys jatkaa toimintaa varovaisella kassasuunnittelulla. "
            "Omistaja sanoo, että konehankintoja lykätään ja tuotannon kannattavuutta seurataan kuukausittain. "
            "Pankin kanssa sovittu rahoitusvara antaa aikaa, mutta markkinahinta ratkaisee syksyn investoinnit."
        )
        self.assertGreaterEqual(len(thin_body.split()), research.TALOUS_ORIGINAL_THIN_MIN_WORDS)

        self.assertTrue(research._usable_talous_original_fallback(article, thin_body))

    def test_talous_thin_original_fallback_rejects_opinion_and_promo(self):
        article = {"title": "Vieraskynä: talouspolitiikka on pielessä", "category_hint": "Talous", "source": "Talous"}
        opinion = "Vieraskynä kertoo, miksi talouspolitiikka on kirjoittajan mielestä väärässä. Teksti sisältää arvion ja mielipiteen ilman neutraalia uutislähdettä."
        promo = "Yrittäjä kertoo yrityksestään ja pyytää lukijoita seuraamaan Instagramissa. Liity jäseneksi ja tule mukaan paikallisyhdistyksen toimintaan."

        self.assertFalse(research._usable_talous_original_fallback(article, opinion))
        self.assertFalse(research._usable_talous_original_fallback(article, promo))

    def test_talous_rss_supplement_adds_safe_context_to_one_source_result(self):
        article = {
            "title": "Pk-yritysten maksuajat pitenevät",
            "category_hint": "Talous",
            "source": "Suomen Yrittäjät",
            "link": "https://www.yrittajat.fi/uutiset/maksuajat",
            "description": (
                "Pk-yritysten maksuajat ovat pidentyneet alkuvuonna useilla toimialoilla. "
                "Yrittäjäjärjestön mukaan viiveet kiristävät kassaa, vaikeuttavat investointeja "
                "ja lisäävät tarvetta lyhytaikaiselle rahoitukselle. Yritykset seuraavat "
                "asiakaskohtaisia maksuehtoja aiempaa tarkemmin ja pyrkivät varmistamaan "
                "sopimusten ehdot ennen toimituksia. Tilanne koskee erityisesti pieniä "
                "alihankkijoita, joiden kulut erääntyvät ennen asiakkaiden maksuja "
                "ja varaston täydentämistä."
            ),
        }
        fetched_source = (
            "Avoin lähde kertoo, että pienyritysten maksuviiveet ovat kasvaneet. "
            * 20
        )

        with patch.object(research, "fetch_article_text", side_effect=["", fetched_source]), \
             patch.object(research, "_search_news", return_value=[{"url": "https://example.com/maksuajat", "source": "Example"}]), \
             patch.object(research.time, "sleep", return_value=None):
            text = research._research_article(article)

        self.assertIn("[Lähde: Example | URL: https://example.com/maksuajat]", text)
        self.assertIn("[Lähde: Suomen Yrittäjät | URL: https://www.yrittajat.fi/uutiset/maksuajat]", text)
        self.assertIn("Pk-yritysten maksuajat ovat pidentyneet", text)

    def test_talous_rss_supplement_rejects_promotional_context(self):
        article = {
            "title": "Kurkista finanssialan arkeen",
            "category_hint": "Talous",
            "source": "Finanssiala",
            "link": "https://www.finanssiala.fi/uutiset/kesatyo",
            "description": (
                "Ota Finanssialalle-Instagram seurantaan ja vinkkaa kaverille. "
                "Liity mukaan seuraamaan kohokohtia ja uratarinoita."
            ),
        }
        existing = [("Example", "Avoin lähde kertoo kesätyöstä ja yritysten henkilöstötarpeista. " * 12)]

        self.assertIsNone(research._talous_rss_supplement(article, existing))

    def test_talous_rss_supplement_does_not_duplicate_existing_text(self):
        article = {
            "title": "Osakemarkkina avautui laskuun",
            "category_hint": "Talous",
            "source": "Arvopaperi",
            "link": "https://www.arvopaperi.fi/uutiset/markkina",
            "description": (
                "Osakemarkkina avautui laskuun korko-odotusten muuttuessa. "
                "Sijoittajat seuraavat keskuspankin viestejä ja yhtiöiden tulosnäkymiä. "
                "Pankkisektorin kurssit laskivat, mutta teknologiayhtiöt pitivät indeksit lähellä eilistä tasoa."
            ),
        }
        existing = [("Example", article["description"] + " Lisää taustaa markkinoista.")]

        self.assertIsNone(research._talous_rss_supplement(article, existing))


if __name__ == "__main__":
    unittest.main()
