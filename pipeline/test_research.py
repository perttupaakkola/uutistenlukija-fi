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



if __name__ == "__main__":
    unittest.main()
