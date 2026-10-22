import unittest

from news_mvp import index_policy, seo


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

    def test_new_short_article_auto_noindex(self):
        short = {"paragraphs": [{"text": "sana " * 60}]}
        full = {"paragraphs": [{"text": "sana " * 200}]}
        self.assertFalse(index_policy.indexable("uutiset/uusi-1/", short))
        self.assertTrue(index_policy.indexable("uutiset/uusi-1/", full))
        self.assertTrue(index_policy.indexable("uutiset/selittaja-x-1/", short))
        self.assertTrue(index_policy.indexable("uutiset/uusi-1/", "not json"))

    def test_head_robots(self):
        self.assertIn('content="noindex,follow"', seo.article_head("O", "K", "/uutiset/x/", index=False))
        self.assertIn('index,follow,max-image-preview:large', seo.article_head("O", "K", "/uutiset/x/"))


if __name__ == "__main__":
    unittest.main()
