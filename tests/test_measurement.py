import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from news_mvp.measurement import classify_path, normalize_url

SITE = "https://uutistenlukija.fi"


class NormalizeUrlTest(unittest.TestCase):
    def test_site_urls_and_paths(self):
        self.assertEqual(normalize_url(SITE + "/uutiset/2024/01/foo/"), "/uutiset/2024/01/foo/")
        self.assertEqual(normalize_url("/uutiset/2024/01/foo/"), "/uutiset/2024/01/foo/")
        self.assertEqual(normalize_url("/sivu/2/", "uutistenlukija.fi"), "/sivu/2/")
        self.assertEqual(normalize_url(SITE), "/")
        self.assertEqual(normalize_url(SITE + "?x=1"), "/")

    def test_query_and_fragment_removed(self):
        self.assertEqual(normalize_url("/uutiset/x?utm=1&b=2"), "/uutiset/x")
        self.assertEqual(normalize_url(SITE + "/sivu/2/?page=3#top"), "/sivu/2/")

    def test_path_case_and_trailing_slash_preserved(self):
        self.assertEqual(normalize_url("/Uutiset/X/"), "/Uutiset/X/")
        self.assertNotEqual(normalize_url("/uutiset/x"), normalize_url("/uutiset/x/"))

    def test_foreign_and_host_mismatch(self):
        for value in (
            "https://example.com/uutiset/x",
            "https://www.uutistenlukija.fi/uutiset/x",
            "https://sub.uutistenlukija.fi/",
            "https://uutistenlukija.fi.evil.com/uutiset/x",
            "http://uutistenlukija.fi/uutiset/x",
            "https://uutistenlukija.fi:8443/uutiset/x",
            "https://user:pass@uutistenlukija.fi/uutiset/x",
            "https:/uutistenlukija.fi/uutiset/x",
        ):
            self.assertIsNone(normalize_url(value), value)
        self.assertIsNone(normalize_url("/uutiset/x", "example.com"))
        self.assertIsNone(normalize_url("/uutiset/x", "www.uutistenlukija.fi"))

    def test_malformed_traversal_and_control(self):
        for value in (
            "//uutistenlukija.fi/uutiset/x",
            "//evil.com/uutiset/x",
            "uutiset/x",
            "/uutiset/%zz",
            "/uutiset/%2",
            "/uutiset/%2e%2e/secret",
            "/uutiset/%2E%2E/",
            "/uutiset/%2e/",
            "/a/../uutiset/",
            "/uutiset/%2fetc/passwd",
            "/uutiset/%5c",
            "/uutiset\\x",
            "https://uutistenlukija.fi\\@evil.com/uutiset/",
            "/uutiset/ x",
            "/uutiset/a%20b/",
            "/uutiset/\tx",
            "/uutiset/x\n",
            "/uutiset/\x00x",
        ):
            self.assertIsNone(normalize_url(value), value)

    def test_empty_unknown_and_no_implicit_root(self):
        for value in ("", "(not set)", "(NOT SET)", "(none)", "unknown", None, 42, "?q=1", "#f"):
            self.assertIsNone(normalize_url(value), value)
        self.assertEqual(normalize_url("/"), "/")

    def test_host_argument_absent_or_matching(self):
        self.assertEqual(normalize_url("/uutiset/x"), "/uutiset/x")
        self.assertEqual(normalize_url("/uutiset/x", "uutistenlukija.fi"), "/uutiset/x")
        self.assertEqual(normalize_url("/uutiset/x", "UUTISTENLUKIJA.FI"), "/uutiset/x")

    def test_explicit_host_requires_exact_site_host(self):
        for host in ("", "(not set)", "(NOT SET)", "unknown", "none", "-", " uutistenlukija.fi",
                     "uutistenlukija.fi ", "uutistenlukija.fi.", "www.uutistenlukija.fi",
                     "uutistenlukija.fi:443", "sub.uutistenlukija.fi", "example.com", 42):
            self.assertIsNone(normalize_url("/uutiset/x", host), host)
            self.assertEqual(classify_path("/uutiset/x", host), "excluded", host)
        self.assertEqual(classify_path("/uutiset/x", "uutistenlukija.fi"), "reboot")

    def test_malformed_url_returns_none(self):
        for value in ("https://[broken/", "https://[broken/uutiset/x", "https://uutistenlukija.fi[/x"):
            self.assertIsNone(normalize_url(value), value)
            self.assertEqual(classify_path(value), "excluded", value)

    def test_userinfo_and_explicit_port_rejected(self):
        for value in (
            "https://@uutistenlukija.fi/uutiset/a/",
            "https://:pass@uutistenlukija.fi/uutiset/a/",
            "https://user@uutistenlukija.fi/uutiset/a/",
            "https://uutistenlukija.fi:/uutiset/a/",
            "https://uutistenlukija.fi:443/uutiset/a/",
            "https://uutistenlukija.fi:8443/uutiset/a/",
        ):
            self.assertIsNone(normalize_url(value), value)
            self.assertEqual(classify_path(value), "excluded", value)

    def test_ambiguous_decoding_rejected(self):
        for value in (
            "/uutiset/a%3Fb/",
            "/uutiset/a%23b/",
            "/uutiset/a%252fb/",
            "/uutiset/a%2525b/",
            SITE + "/uutiset/a%3Fb/",
        ):
            self.assertIsNone(normalize_url(value), value)
            self.assertEqual(classify_path(value), "excluded", value)

    def test_safe_utf8_and_idempotent_normalization(self):
        fixtures = (
            "/uutiset/x",
            "/uutiset/x/",
            "/uutiset/%C3%A4/",
            "/uutiset/caf%C3%A9/",
            "/uutiset/%E2%82%AC/",
            "/uutiset/2024/01/foo/?utm=1#top",
            SITE,
            SITE + "/sivu/2/",
        )
        for value in fixtures:
            once = normalize_url(value)
            self.assertIsNotNone(once, value)
            self.assertEqual(normalize_url(once), once, value)
            self.assertEqual(classify_path(once), classify_path(value), value)


class ClassifyPathTest(unittest.TestCase):
    def test_reboot(self):
        for value in ("/", SITE + "/", "/uutiset/", "/uutiset/2024/01/foo/",
                      SITE + "/uutiset/2024/01/foo/", "/sivu/", "/sivu/2/",
                      "/uutiset/x?utm=1"):
            self.assertEqual(classify_path(value), "reboot", value)

    def test_legacy_and_prefix_boundary(self):
        for value in ("/uutiset", "/sivu", "/uutisetfake/", "/uutisetfake", "/sivut/",
                      "/sivu2/", "/blog/post/", "/oppaat/", "/posts/1", "/muu", "/Uutiset/x/"):
            self.assertEqual(classify_path(value), "legacy", value)

    def test_excluded(self):
        for value in ("", "(not set)", None, "https://example.com/uutiset/x",
                      "https://uutistenlukija.fi/uutiset/%2e%2e/x", "//evil.com/uutiset/x",
                      "/a/../uutiset/", "/uutiset/ x"):
            self.assertEqual(classify_path(value), "excluded", value)
        self.assertEqual(classify_path("/uutiset/x", "example.com"), "excluded")
        self.assertEqual(classify_path("/uutiset/x", "uutistenlukija.fi"), "reboot")


if __name__ == "__main__":
    unittest.main()
