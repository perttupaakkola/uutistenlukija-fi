"""Offline captured-scene regression and adversarial safety examples."""
import unittest
from news_mvp.imagery import _depicts_people

class GrowthImageBlocker(unittest.TestCase):
    def test_exact_captured_safe_scene(self):
        scene = "Nimeämätön suuri öljytankkeri kiinnitettynä öljysataman laituriin. Aluksen pitkä kansi putkistoineen ja laiturin lastausvarret näkyvät sivuviistosta veden yli kuvattuina, eikä kuvassa ole ihmisiä."
        self.assertFalse(_depicts_people(scene))
    def test_cargo_is_not_children(self):
        for s in ("Lastausvarret öljysatamassa", "Lastauksen putkisto", "Lastausalue vedestä kuvattuna"):
            with self.subTest(s=s):self.assertFalse(_depicts_people(s))
    def test_negative_existence(self):
        for s in ("Öljysäiliöt, eikä kuvassa ole ihmisiä.", "Säiliöt. Ei kuvassa näy henkilöitä.", "Laituri ilman ihmisiä.", "Oil tanks without people."):
            with self.subTest(s=s):self.assertFalse(_depicts_people(s))
    def test_people_and_body_parts_still_refused(self):
        for s in ("Lapsia laiturilla", "Lasten ryhmä", "Aikuinen satamassa", "Henkilö säiliön vieressä", "Käsi venttiilillä", "People beside an oil tanker", "Faces near loading arms"):
            with self.subTest(s=s):self.assertTrue(_depicts_people(s))
    def test_captured_location_before_negation(self):
        self.assertFalse(_depicts_people("Nimeämätön öljytankkeri kiinnitettynä öljysataman laituriin. Aluksen kannella näkyy putkistoa ja laiturilla lastausvarsi; kuvassa ei ole ihmisiä eikä tunnistettavaa todellista satamaa."))
        self.assertFalse(_depicts_people("Säiliöt; ei ole ihmisiä."))
        self.assertTrue(_depicts_people("Kuvassa ei ole vain ihmisiä vaan myös putkia."))
    def test_positive_clause_not_hidden_by_negation(self):
        for s in ("Ei kuvassa ole vain ihmisiä, vaan myös säiliöitä", "Ei kuvassa ole ihmisiä mutta käsi näkyy", "Laituri ilman ihmisiä ja lapset taustalla", "Eikä kuvassa ole ihmisiä, mutta henkilö näkyy laiturilla"):
            with self.subTest(s=s):self.assertTrue(_depicts_people(s))

if __name__ == '__main__':unittest.main()
