import unittest
from news_mvp import seo

class SymppisSearchSnippet(unittest.TestCase):
    title = 'Helsinki: Itiksen Symppis siirtyy Turunlinnantielle'
    summary = 'Helsingin kaupungin mukaan matalan kynnyksen päiväkeskus aloittaa uusissa tiloissa 2. lokakuuta 2026 ja palvelee arkisin kello 10–15.30.'
    address = 'Itiksen Symppiksen uusi osoite on Turunlinnantie 12. Helsingin kaupungin mukaan toiminta alkaa peruskorjatuissa tiloissa rakennuksen ensimmäisessä kerroksessa, ja sisäänkäynti on Turunlinnantien puolelta.'
    expected = 'Itiksen Symppiksen uusi osoite on Turunlinnantie 12 Helsingissä. Kaupungin ilmoittama aukioloaika: arkisin klo 10–15.30.'

    def test_reviewed_address_and_hours_in_search_and_social_metadata(self):
        description = seo.article_description(self.title, self.summary, [self.address])
        self.assertEqual(description, self.expected)
        self.assertLessEqual(len(description), seo.DESCRIPTION_MAX)
        head = seo.article_head(self.title, description, "/uutiset/example/", published="2026-09-28T13:07:24.546808+00:00")
        self.assertEqual(head.count(self.expected), 3)
        self.assertIn("2026-09-28T13:07:24.546808+00:00", head)

    def test_changed_reviewed_facts_fall_back(self):
        for title, summary, paragraphs in [("Other story", self.summary, [self.address]), (self.title, self.summary, []), (self.title, self.summary, [self.address.replace("12.", "14.")]), (self.title, self.summary.replace("10–15.30", "9–15.30"), [self.address])]:
            with self.subTest(title=title, summary=summary, paragraphs=paragraphs):
                self.assertEqual(seo.article_description(title, summary, paragraphs), seo.meta_description(summary, paragraphs))
