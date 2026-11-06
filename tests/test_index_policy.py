import json
import unittest
from pathlib import Path

from news_mvp import index_policy, publish, seo, site


ROOT = Path(__file__).resolve().parents[1]


class IndexPolicyTest(unittest.TestCase):
    def test_listed_short_article_is_noindex(self):
        path = sorted(index_policy.NOINDEX_PATHS)[0]
        self.assertFalse(index_policy.indexable(path.strip("/") + "/"))
        self.assertFalse(index_policy.indexable(path))

    def test_other_articles_indexed(self):
        self.assertTrue(index_policy.indexable("uutiset/jotain-uutta-1/"))

    def test_no_explainer_listed(self):
        self.assertFalse(any("/selittaja-" in p for p in index_policy.NOINDEX_PATHS))
        self.assertGreater(len(index_policy.NOINDEX_PATHS), 100)

    def test_head_robots(self):
        self.assertIn('content="noindex,follow"', seo.article_head("O", "K", "/uutiset/x/", index=False))
        self.assertIn('index,follow,max-image-preview:large', seo.article_head("O", "K", "/uutiset/x/"))

    def test_zero_news_inventory_is_noindex_and_absent_from_sitemap(self):
        audited = json.loads((ROOT / "tests/fixtures/zero_news_20261106.json").read_text(encoding="utf-8"))
        self.assertEqual(len(audited), 50)
        self.assertEqual(len(set(audited)), 50)
        self.assertTrue(set(audited).issubset(index_policy.NOINDEX_PATHS))

        identifiers = set()
        titles = {}
        for path in audited:
            stem = path.removeprefix("/uutiset/").removesuffix("/")
            slug, suffix = stem.rsplit("-", 1)
            identifier = suffix + "0" * 52
            title = slug.replace("-", " ")
            self.assertEqual("/" + site.article_path({"id": identifier, "draft": {"title": title}}), path)
            identifiers.add(identifier)
            titles[identifier] = json.dumps({"title": title})
            self.assertIn('content="noindex,follow"', seo.article_head(
                title, "Kuvaus", path, index=index_policy.indexable(path)))

        entries = publish._article_sitemap_entries(identifiers, titles, {}, {})
        self.assertEqual(entries, [])


if __name__ == "__main__":
    unittest.main()
