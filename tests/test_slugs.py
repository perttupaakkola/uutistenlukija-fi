"""Invariant tests for readable article URLs.

The migration from hash URLs is only safe if two properties hold: a slug is stable and
unique for a given article, and the old hash URL always has a redirect. Both are pinned
here.
"""
import unittest

from news_mvp.slugs import article_slug, is_legacy_hash_path, redirect_line, slugify

HASH = "8552d795654a7633d49c73a880c6c6e59d70a0cfdeba3766bb9c042c950f8a60"


class Slugify(unittest.TestCase):
    def test_finnish_characters_become_ascii(self):
        self.assertEqual(slugify("Äänekoski öljystä"), "aanekoski-oljysta")

    def test_hyphenates_and_lowercases(self):
        self.assertEqual(slugify("Inflaatio nousi elokuussa"), "inflaatio-nousi-elokuussa")

    def test_strips_punctuation_and_dashes(self):
        self.assertEqual(slugify("Helsinki – uusi alue!"), "helsinki-uusi-alue")

    def test_collapses_whitespace(self):
        self.assertEqual(slugify("  monta    sanaa  "), "monta-sanaa")

    def test_empty_and_symbol_only_input(self):
        self.assertEqual(slugify(""), "")
        self.assertEqual(slugify("!!! ???"), "")
        self.assertEqual(slugify(None), "")

    def test_respects_character_budget(self):
        slug = slugify("sana " * 50)
        self.assertLessEqual(len(slug), 60)

    def test_never_ends_with_hyphen(self):
        for text in ("Loppu -", "Alku - loppu", "a-b-c-"):
            self.assertFalse(slugify(text).endswith("-"), text)

    def test_stopwords_dropped_only_when_substance_remains(self):
        # "ja"/"on" carry no search value here, so they go.
        self.assertNotIn("-ja-", slugify("Kunta ja kaupunki rakentavat"))
        # But a slug must never be emptied by stopword removal.
        self.assertTrue(slugify("ja tai on"))


class ArticleSlug(unittest.TestCase):
    def test_ends_with_id_prefix_for_uniqueness(self):
        slug = article_slug(HASH, "Inflaatio nousi elokuussa")
        self.assertTrue(slug.endswith("-" + HASH[:12]))

    def test_is_deterministic(self):
        first = article_slug(HASH, "Sama otsikko")
        second = article_slug(HASH, "Sama otsikko")
        self.assertEqual(first, second)

    def test_same_title_different_ids_do_not_collide(self):
        a = article_slug("a" * 64, "Sama otsikko")
        b = article_slug("b" * 64, "Sama otsikko")
        self.assertNotEqual(a, b)

    def test_missing_title_falls_back_to_id(self):
        self.assertEqual(article_slug(HASH, ""), HASH[:12])
        self.assertEqual(article_slug(HASH, None), HASH[:12])

    def test_no_double_hyphen_from_empty_base(self):
        slug = article_slug(HASH, "!!!")
        self.assertNotIn("--", slug)
        self.assertEqual(slug, HASH[:12])


class LegacyDetection(unittest.TestCase):
    def test_recognises_bare_hash(self):
        self.assertTrue(is_legacy_hash_path(HASH))

    def test_recognises_hash_with_slashes(self):
        self.assertTrue(is_legacy_hash_path("/" + HASH + "/"))

    def test_rejects_slug_paths(self):
        self.assertFalse(is_legacy_hash_path("inflaatio-nousi-8552d795654a"))
        self.assertFalse(is_legacy_hash_path("/uutiset/" + HASH + "/"))

    def test_rejects_short_or_non_hex(self):
        self.assertFalse(is_legacy_hash_path("abc"))
        self.assertFalse(is_legacy_hash_path("z" * 64))


class RedirectLine(unittest.TestCase):
    def test_emits_301_with_leading_slash(self):
        line = redirect_line("uutiset/" + HASH, "uutiset/slug-abc/")
        self.assertEqual(line, f"/uutiset/{HASH}/ /uutiset/slug-abc/ 301")

    def test_tolerates_existing_slashes(self):
        self.assertEqual(redirect_line("/a/", "/b/"), "/a/ /b/ 301")


if __name__ == "__main__":
    unittest.main()
