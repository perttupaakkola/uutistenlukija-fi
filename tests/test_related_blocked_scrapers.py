import unittest
from news_mvp import related


class BlockedScrapers(unittest.TestCase):
    def test_mirror_sites_are_not_corroboration(self):
        for d in ("europesays.com", "msn.com", "headtopics.com"):
            self.assertIn(d, related.BLOCKED_DOMAINS)


if __name__ == "__main__":
    unittest.main()
