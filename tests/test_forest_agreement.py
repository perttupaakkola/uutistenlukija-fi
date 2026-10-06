import unittest
from news_mvp.imagery import _depicts_people

SAFE = ['Nuori havupuutaimikko, jossa kasvamaan jätettyjen taimien välissä näkyy matalia raivauskantoja ja maahan kaadettuja ohuita lehtipuun runkoja. Kuvassa ei ole ihmisiä.', 'Raivaussaha lepää sammaloituneella maalla tiheässä nuoressa metsässä. Taustalla näkyy ohuita puunrunkoja, eikä paikalla ole ihmisiä.', 'Suomalaisen havupuutaimikon maanpinnan tasolta kuvattu näkymä, jossa kasvavien taimien väleissä näkyy raivattuja pieniä lehtipuun runkoja ja matalia tuoreita kantoja. Kuvassa ei ole ihmisiä.', 'Nuoren metsän tiheässä puustossa raivaussaha lepää sammalpohjalla pienten katkaistujen runkojen vieressä. Taustalla näkyy ohuita kasvavia puunrunkoja, eikä paikalla ole ihmisiä.', 'Nuoren metsän hoitotyö.', 'Nuorta metsää kuvataan ilman ihmisiä.', 'Nuoressa havupuutaimikossa näkyy raivauskantoja.', 'Nuoresta taimikosta näkyy yksityiskohta.', 'Nuoreen havumetsikköön johtava polku.']
UNSAFE = ['Nuorella metsässä.', 'Nuorukainen metsässä.', 'Nuorisoryhmä nuoressa metsässä.', 'Nuoren metsänhoitajan työ.', 'Nuori havupuutaimikonhoitaja.', 'Nuoren metsän keskellä seisoo nuori.', 'Nuoren metsän vieressä näkyy käsi.', 'Nuoren metsän keskellä ihmisiä.', 'Nuoren metsänhoitajat.', 'Nuoren metsän ja nuorukaisen kuva.', 'Nuori metsän puu.', 'Nuoren metsä.', 'Nuori havupuutaimikkolapsi.']

class ForestAgreement(unittest.TestCase):
    def test_nonhuman_agreement(self):
        for scene in SAFE:
            with self.subTest(scene=scene): self.assertFalse(_depicts_people(scene))
    def test_human_and_ambiguous_stay_blocked(self):
        for scene in UNSAFE:
            with self.subTest(scene=scene): self.assertTrue(_depicts_people(scene))
