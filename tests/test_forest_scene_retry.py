"""Exact fresh 2026-10-06 forestry retry and bounded person controls."""
import unittest
from news_mvp.imagery import _depicts_people

SCENES = ['Nuori havupuutaimikko, jossa kasvamaan jätettyjen taimien välissä näkyy matalia raivauskantoja ja maahan kaadettuja ohuita lehtipuun runkoja. Kuvassa ei ole ihmisiä.', 'Raivaussaha lepää sammaloituneella maalla tiheässä nuoressa metsässä. Taustalla näkyy ohuita puunrunkoja, eikä paikalla ole ihmisiä.']
UNSAFE = ['Nuorukainen havupuutaimikon vieressä.', 'Nuorisoryhmä nuoressa metsässä.', 'Nuori havupuutaimikonhoitaja metsässä.', 'Nuori havupuutaimikko ja käsi raivaussahan kahvalla.', 'Raivaussaha nuoressa metsässä; paikalla on ihmisiä.', 'Eikä paikalla ole vain ihmisiä vaan myös käsiä.', 'Eikä paikalla ole ihmisiä, käsi näkyy puun vieressä.']

class ForestRetry(unittest.TestCase):
    def test_fresh_tree_scene_is_nonhuman(self):
        self.assertFalse(_depicts_people(SCENES[0]))
    def test_nearby_people_stay_blocked(self):
        for scene in UNSAFE:
            with self.subTest(scene=scene):
                self.assertTrue(_depicts_people(scene))

    def test_fresh_brushcutter_scene_is_nonhuman(self):
        self.assertFalse(_depicts_people(SCENES[1]))
