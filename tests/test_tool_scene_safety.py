import unittest
from news_mvp.imagery import _depicts_people,validate_image_decision

class ToolSceneTests(unittest.TestCase):
 def test_exact_nonhuman_forms(self):
  for s in ('Työpöydällä on käsityökaluja.','Pöydällä siististi asetellut käsityökalut.','KÄSITYÖKALUT ovat pöydällä.'):
   with self.subTest(scene=s):self.assertFalse(_depicts_people(s))
 def test_human_and_compound_controls(self):
  for s in ('Työpöydällä näkyy käsi.','Käsityöläinen työskentelee työpajassa.','Käsityökalujen käyttäjä työskentelee.','Käsityökalut ja käsi näkyvät.','Käsityökaluja pitelevä henkilö.','Käsityökalut kädessään opettaja.','Käsityökalutkäsi','käsityökalukäyttäjä','käsityökalujen','nuorukainen','henkilöautonkuljettaja','lapsi','lasten kädet'):
   with self.subTest(scene=s):self.assertTrue(_depicts_people(s))
 def test_other_safe_controls(self):
  for s in ('Työpenkissä on ruuvipenkki.','Lastausvarret satamassa.','Nuori metsä.'):
   with self.subTest(scene=s):self.assertFalse(_depicts_people(s))
if __name__=='__main__':unittest.main()
