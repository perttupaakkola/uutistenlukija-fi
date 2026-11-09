import unittest
from datetime import datetime, timezone

from news_mvp.editorial import text, validate_packet

# Real STT Info release dropped on 9 Nov 2026 with "ValueError: Invalid story_key".
REAL_URL = ("https://www.sttinfo.fi/tiedote/72483172/kaitera-talks-pureutuu-kulttuurin-"
            "teknologian-ja-tieteen-polttopisteeseen-puhujasarjan-vieraina-rosa-liksom-"
            "matti-latva-aho-aarno-palotie-ja-timo-muotka?lang=fi")


class LongStoryKeyTest(unittest.TestCase):
    def test_real_long_press_release_url_is_a_valid_story_key(self):
        key = "url:" + REAL_URL
        self.assertGreater(len(key), 200)
        now = datetime(2026, 11, 9, 4, 0, tzinfo=timezone.utc)
        packet = {"story_key": key, "fixture": False, "sources": [{
            "id": "A", "url": REAL_URL, "publisher": "STT Info", "title": "Kaitera Talks",
            "published_at": "2026-11-08T10:00:00+00:00", "text": "Lähdeteksti. " * 40}]}
        try:
            validate_packet(packet, now)
        except ValueError as error:
            self.assertNotIn("story_key", str(error))

    def test_story_key_cap_covers_longest_accepted_url(self):
        # web_url() accepts 2000-char URLs; "url:" + such a URL must stay valid.
        text("url:https://example.fi/" + "a" * 1977, "story_key", 2100)


if __name__ == "__main__":
    unittest.main()
