import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ServiceWorkerTests(unittest.TestCase):
    def read_sw(self) -> str:
        return (ROOT / "static/sw.js").read_text(encoding="utf-8")

    def test_scripts_and_styles_are_network_first_not_cache_first(self) -> None:
        sw = self.read_sw()

        self.assertIn("function networkFirst", sw)
        self.assertRegex(sw, re.compile(r"else if \(isFrontendAsset\(event\.request\)\) \{\s*event\.respondWith\(networkFirst\(event\.request\)\)", re.S))
        self.assertNotRegex(sw, re.compile(r"caches\.match\(event\.request\)\.then\(\s*cached\s*=>\s*cached\s*\|\|\s*fetch", re.S))

    def test_frontend_assets_are_not_precached_under_fixed_cache_name(self) -> None:
        sw = self.read_sw()
        precache_match = re.search(r"const PRECACHE = \[(.*?)\];", sw, re.S)
        self.assertIsNotNone(precache_match)
        precache = precache_match.group(1)

        self.assertNotIn("/js/frontpage-live.js", precache)
        self.assertNotIn("/js/search.js", precache)
        self.assertNotIn("/css/style.css", precache)


if __name__ == "__main__":
    unittest.main()
