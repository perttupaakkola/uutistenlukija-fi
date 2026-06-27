#!/usr/bin/env python3
from __future__ import annotations

import unittest

try:
    from . import pexels, unsplash
except ImportError:  # pragma: no cover
    import pexels
    import unsplash


DEGREE_ROI_FIXTURE = {
    "title": "Kannattaako korkeakoulututkinto? Uusi laskuri arvioi koulutuksen tuoton",
    "category": "Talous",
    "summary": (
        "Artikkeli kertoo korkeakoulututkinnon sijoitetun pääoman tuotosta, "
        "palkkaerosta, opintolainasta ja tutkinnon takaisinmaksuajasta."
    ),
    "content": (
        "Korkeakoulututkinnon kannattavuutta arvioidaan vertaamalla lukukausimaksuja, "
        "opintolainaa, menetettyjä työvuosia ja valmistumisen jälkeistä palkkatasoa. "
        "Degree ROI kertoo, milloin koulutus maksaa itsensä takaisin."
    ),
}


class ImageQueryTokenTests(unittest.TestCase):
    def test_degree_roi_fallback_query_uses_english_visual_tokens(self) -> None:
        expected = "university degree education return investment"

        self.assertEqual(pexels.build_search_query(**DEGREE_ROI_FIXTURE), expected)
        self.assertEqual(unsplash.build_search_query(**DEGREE_ROI_FIXTURE), expected)


if __name__ == "__main__":
    unittest.main()
