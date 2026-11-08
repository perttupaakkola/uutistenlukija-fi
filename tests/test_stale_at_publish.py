import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from news_mvp.controller import ingest
from news_mvp.controller import load_config
from news_mvp.publish import publish
from news_mvp.store import database
import test_release_v2 as release_v2


def _shift_sources(packet, hours):
    for source in packet["sources"]:
        when = datetime.fromisoformat(source["published_at"].replace("Z", "+00:00"))
        source["published_at"] = (when - timedelta(hours=hours)).isoformat()
    return packet


class StaleAtPublishTests(unittest.TestCase):
    """8 Nov 2026: story admitted at 47 h 50 min, aged past 48 h during the 10 min tick,
    and publish() raised 'Source is stale or future-dated', crashing the publisher."""

    def setUp(self):
        self.case = release_v2.ReleaseV2("test_text_and_image_full_actual_publish_workflow_canonical_next_tick")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_admission_refuses_source_that_would_age_out_mid_tick(self):
        packet = _shift_sources(json.loads(json.dumps(self.case.packet)), 47 + 50 / 60)
        packet["story_key"] = "url:https://www.hel.fi/fi/uutiset/near-limit"
        with self.assertRaisesRegex(ValueError, "too close to the freshness limit"):
            ingest(load_config(self.case.cfg), packet, self.case.now)

    def test_admission_still_accepts_ordinary_fresh_source(self):
        packet = _shift_sources(json.loads(json.dumps(self.case.packet)), 30)
        packet["story_key"] = "url:https://www.hel.fi/fi/uutiset/thirty-hours"
        self.assertTrue(ingest(load_config(self.case.cfg), packet, self.case.now)["admitted"])

    def test_story_that_aged_out_before_publish_is_retired_not_crashing(self):
        job, _sha = self.case.image_job()
        later = datetime.now(timezone.utc) + timedelta(hours=49)

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return later
        with database(self.case.state) as store, patch("news_mvp.publish.guard"), \
                patch("news_mvp.publish.datetime", Clock):
            result = publish(store, job, self.case.state, self.case.cfg)
            row = store.get(job["id"])
            pubs = store.db.execute("SELECT count(*) FROM publications").fetchone()[0]
        self.assertEqual(result, {"status": "stale_at_publish", "job_id": job["id"]})
        self.assertEqual(row["status"], "failed")
        self.assertIn("aged out", row["error"])
        self.assertEqual(pubs, 0)


if __name__ == "__main__":
    unittest.main()
