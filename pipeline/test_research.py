import unittest

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


if __name__ == "__main__":
    unittest.main()
