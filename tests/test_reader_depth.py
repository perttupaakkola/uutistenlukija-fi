"""Focused contracts for the three-surface reader-depth redesign."""

import hashlib
import unittest
from datetime import datetime, timedelta, timezone

from news_mvp import site


def story(index, category="Kotimaa"):
    identifier = hashlib.sha256(f"reader-depth:{index}".encode()).hexdigest()
    created = (datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
               - timedelta(minutes=index)).isoformat()
    draft = {
        "title": f"Ajankohtainen uutinen numero {index}",
        "summary": f"Varmennettu tiivistelmä uutisesta {index}.",
        "category": category,
        "paragraphs": [{"text": "Ensimmäinen kappale."}, {"text": "Toinen kappale."}],
    }
    job = {"id": identifier, "created_at": created, "draft": draft}
    link = f"/uutiset/uutinen-{index}-{identifier[:12]}/"
    return job, draft, link, created, "", None, None


class ReaderDepthContracts(unittest.TestCase):
    def test_home_has_one_edition_and_keeps_every_story_in_a_clear_role(self):
        items = [story(index, "Talous" if index % 2 else "Kotimaa") for index in range(12)]
        text = site.homepage_edition_html(items) + site.listing_page_html(items, 1, 1, items)
        self.assertEqual(text.count('<h1 id="front-edition-title">'), 1)
        self.assertEqual(text.count('<article class="portal-lead'), 1)
        self.assertEqual(text.count('<article class="portal-teaser'), site.HOMEPAGE_CENTER_ROWS)
        self.assertEqual(text.count('<article class="portal-row-card'),
                         len(items) - 1 - site.HOMEPAGE_CENTER_ROWS)
        self.assertIn("Uusimmasta vanhimpaan", text)
        for item in items:
            self.assertIn(item[2], text)

    def test_category_features_only_the_newest_then_labels_the_archive(self):
        items = [story(index, "Kulttuuri") for index in range(4)]
        text = site.category_page_body(
            "Kulttuuri", "Kulttuurin ajankohtaiset uutiset.", items,
            "Ei uutisia", total_count=4, featured=True,
        )
        self.assertEqual(text.count("portal-feed-item--featured"), 1)
        self.assertEqual(text.count('<article class="portal-feed-item'), 4)
        self.assertEqual(text.count("Osaston uusin"), 1)
        self.assertIn("Uutisarkisto", text)
        self.assertIn("4 juttua", text)

    def test_article_continuation_is_truthful_and_excludes_related_items(self):
        current = story(0, "Talous")
        related = story(1, "Talous")
        remaining = [story(index, "Talous" if index < 5 else "Kotimaa")
                     for index in range(2, 9)]
        candidates = [(item[0], {}, item[1], {})
                      for item in [current, related, *remaining]]
        text = site.article_context_html(
            current[0], current[1], candidates, related_ids={related[0]["id"]},
        )
        self.assertIn("Samasta osastosta", text)
        self.assertIn("Uusimmat", text)
        self.assertNotIn(related[1]["title"], text)
        self.assertNotIn(current[1]["title"], text)
        self.assertEqual(text.count('<li><a href="/uutiset/'), 7)

    def test_public_shell_and_article_expose_local_saved_story_controls(self):
        shell = site.page("Etusivu", "<p>Uutiset</p>", "/")
        private_shell = site.page("Esikatselu", "<p>Uutiset</p>")
        actions = site.article_actions_html(
            "/uutiset/esimerkki/", "Tiede", True, "Esimerkkiuutinen",
        )
        self.assertEqual(shell.count("data-saved-toggle"), 2)
        self.assertIn('id="saved-stories-dialog"', shell)
        self.assertIn("vain tämän selaimen omassa muistissa", shell)
        self.assertNotIn("data-saved-toggle", private_shell)
        self.assertNotIn("saved-stories-dialog", private_shell)
        self.assertIn('data-save-title="Esimerkkiuutinen"', actions)
        self.assertIn('data-save-category="Tiede"', actions)
        self.assertIn('aria-pressed="false"', actions)
        self.assertIn("Osaston uutiset: Tiede", actions)

    def test_phone_continuation_dom_precedes_sources_without_duplication(self):
        reading = '<div class="article-reading-main"><div class="content">Body</div></div>'
        context = '<aside class="article-context"><span class="article-context__title">Next</span></aside>'
        afterword = '<div class="article-afterword"><section class="sources"><h2>Lähteet</h2></section></div>'
        text = f'<div class="article-reading-grid">{reading}{context}{afterword}</div>'
        self.assertLess(text.index('article-context__title'), text.index('<h2>Lähteet</h2>'))
        self.assertEqual(text.count('article-context__title'), 1)

    def test_saved_story_script_is_local_only_and_bounded(self):
        source = (site.ROOT / "static/portal.js").read_text()
        self.assertIn('uutistenlukija-saved-stories', source)
        self.assertIn("window.localStorage.setItem", source)
        self.assertIn("slice(0, 40)", source)
        self.assertNotIn("fetch(", source)
        self.assertNotIn("XMLHttpRequest", source)


if __name__ == "__main__":
    unittest.main()
