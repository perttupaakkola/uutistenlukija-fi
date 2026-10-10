import unittest
from news_mvp import seo


class LocalSearchSnippet(unittest.TestCase):
    title = "Oulu valmistelee Ravander-korttelin kaavamuutosta"
    summary = "Oulun kaupungin mukaan Vanhatullin Ravander-korttelin kaavamuutoksella tavoitellaan rakennuskannan uudistamista sekä asuin-, liike- ja toimistorakentamista."
    deadline = "Kaavaluonnos on kaupungin ilmoituksen mukaan nähtävillä 18. syyskuuta–19. lokakuuta 2026."

    def test_exact_reviewed_facts_make_bounded_search_snippet(self):
        text = seo.article_description(self.title, self.summary, [self.deadline])
        self.assertIn("Oulun Vanhatullin Ravander-kortteliin", text)
        self.assertIn("18.9.–19.10.2026", text)
        self.assertLessEqual(len(text), seo.DESCRIPTION_MAX)
        self.assertNotIn("päivitetty", text)
        head = seo.article_head(self.title, text, "/uutiset/example/")
        self.assertEqual(head.count(text), 3)

    def test_missing_or_changed_fact_falls_back(self):
        for summary, paragraphs in [(self.summary, []), (self.summary, [self.deadline.replace("19. lokakuuta", "20. lokakuuta")]), ("Other summary", [self.deadline])]:
            with self.subTest(summary=summary, paragraphs=paragraphs):
                self.assertEqual(seo.article_description(self.title, summary, paragraphs), seo.meta_description(summary, paragraphs))

    def test_other_articles_stay_unchanged(self):
        self.assertEqual(seo.article_description("Other story", self.summary, [self.deadline]), seo.meta_description(self.summary, [self.deadline]))
