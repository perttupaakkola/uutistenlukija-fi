"""Feed and internal-linking contracts.

The feed must expose exactly the rendered articles with absolute links; related links
must connect rendered articles to each other and never to themselves.
"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from news_mvp.controller import ingest, load_config
from news_mvp.editorial import ROOT, FixtureModel, digest
from news_mvp.site import article_path, page, render_site
from news_mvp.store import database


class FeedAndRelated(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".test-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps({"enabled": True, "backend": "fixture",
                                                "state_dir": "state", "output_dir": "site"}))
        self.config = load_config(self.config_path)
        self.now = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)

    def _two_articles(self):
        ids = []
        for suffix, title in (("a", "Ensimmäinen aihe"), ("b", "Toinen aihe")):
            packet = json.loads((ROOT / "fixtures/source-packet.json").read_text())
            packet["story_key"] += "-" + suffix
            packet["sources"][0]["url"] += "-" + suffix
            job_id = ingest(self.config, packet, self.now)["id"]
            with database(self.config["state_dir"]) as store:
                draft = FixtureModel().call("writer", packet)
                draft["title"] = title
                store.save_draft(job_id, draft, "fixture")
                store.finish_review(job_id, {"approved": True, "draft_sha256": digest(draft),
                                             "reasons": ["fixture"]})
            ids.append(job_id)
        return ids

    def test_feed_lists_rendered_articles_with_absolute_links(self):
        self._two_articles()
        with database(self.config["state_dir"]) as store:
            count = render_site(store, self.config["output_dir"], self.config["state_dir"])
        self.assertEqual(count, 2)
        feed = (self.config["output_dir"] / "rss.xml").read_text()
        self.assertIn('<rss version="2.0">', feed)
        self.assertEqual(feed.count("<item>"), 2)
        self.assertIn("https://uutistenlukija.fi/uutiset/", feed)
        self.assertIn("<pubDate>", feed)

    def test_related_links_connect_articles_but_never_self(self):
        ids = self._two_articles()
        with database(self.config["state_dir"]) as store:
            render_site(store, self.config["output_dir"], self.config["state_dir"])
            path_a, path_b = (article_path(store.get(i)) for i in ids)
            pages = {i: (self.config["output_dir"] / article_path(store.get(i)) / "index.html").read_text()
                     for i in ids}
        first, second = ids
        self.assertIn("Lue myös", pages[first])
        self.assertIn(f'href="/{path_b}"', pages[first])
        self.assertNotIn(f'href="/{path_a}"', pages[first])
        self.assertIn(f'href="/{path_a}"', pages[second])


class HeadLink(unittest.TestCase):
    def test_public_pages_advertise_the_feed(self):
        self.assertIn("rss.xml", page("T", "<p>x</p>", "/"))

    def test_private_pages_do_not(self):
        self.assertNotIn("rss.xml", page("T", "<p>x</p>"))


if __name__ == "__main__":
    unittest.main()
