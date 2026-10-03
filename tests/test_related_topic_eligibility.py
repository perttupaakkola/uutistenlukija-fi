"""Captured real-link negatives and substantive-topic positive controls."""
import unittest
from news_mvp import site

class RelatedTopicEligibility(unittest.TestCase):
    def packet(self):
        return {"sources": [{"publisher": "Tilastokeskus", "url": "https://stat.fi/fixture"}]}
    def score(self,left,right):
        return site.related_story_score(self.packet(), {"title":left,"category":"talous"},
                                        self.packet(), {"title":right,"category":"talous"})
    def test_six_captured_production_false_links(self):
        cases=[
          ("Energiatuonnin arvo kasvoi ennakkotietojen mukaan 50 %", "Kaupan liikevaihto kasvoi elokuussa 7,9 prosenttia"),
          ("Energiatuonnin arvo kasvoi ennakkotietojen mukaan 50 %", "Tilastokeskus: tuotanto kasvoi elokuussa 2,3 prosenttia"),
          ("Energiatuonnin arvo kasvoi ennakkotietojen mukaan 50 %", "Tilastokeskus: Kuorma-autojen tavaramäärä kasvoi 15 %"),
          ("Pihlajasaaren kehittäminen käynnistyy vuonna 2027", "Heteniitynkentän peruskorjaus valmistuu syksyllä 2027"),
          ("Pihlajasaaren kehittäminen käynnistyy vuonna 2027", "Helsingin liikunnan avustukset uudistuvat vuonna 2027"),
          ("Pihlajasaaren kehittäminen käynnistyy vuonna 2027", "Vantaa mittaa toimitilojensa radonia talvella 2026–2027"),
        ]
        for left,right in cases:
            with self.subTest(candidate=right): self.assertEqual(self.score(left,right),0)
    def test_generic_trend_variants_never_qualify_alone(self):
        for verb in ("kasvaa","kasvoi","kasvanut","kasvavat","kasvua","kasvu","laskee","laski","laskenut","laskivat","pienenee","pieneni"):
            with self.subTest(verb=verb):
                self.assertEqual(self.score("Energiatuonnin "+verb,"Konkurssien "+verb),0)
    def test_numeric_year_amount_and_range_never_qualify_alone(self):
        for number in ("2027","2026–2027","12345"):
            with self.subTest(number=number):
                self.assertEqual(self.score("Pihlajasaaren kehittäminen "+number,"Radonin mittaus "+number),0)
    def test_substantive_topic_survives_numeric_and_trend_filter(self):
        for left,right in (
          ("Pihlajasaaren kehittäminen käynnistyy vuonna 2027","Pihlajasaaren laituri uudistuu"),
          ("Energiatuonnin arvo kasvoi 50 prosenttia","Energiatuonnin arvo laski syyskuussa"),
          ("Konkurssien määrä kasvoi vuonna 2027","Konkurssien määrä pieneni vuonna 2026"),
          ("5G-verkko laajenee", "5G-verkko saa taajuuksia"),
        ):
            with self.subTest(left=left): self.assertGreaterEqual(self.score(left,right),4)
    def test_no_self_or_publisher_category_only_link(self):
        self.assertEqual(self.score("Pihlajasaari","Pihlajasaari"),0)
        self.assertEqual(self.score("Tilastokeskus: Energiatuonti", "Tilastokeskus: Konkurssit"),0)
