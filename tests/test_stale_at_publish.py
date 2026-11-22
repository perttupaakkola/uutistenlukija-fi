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

    def test_waiting_story_that_aged_out_is_retired_at_claim_not_retried(self):
        """22 Nov 2026: ePressi story admitted at 46.9 h waited for an image, passed 48 h and
        the tick recorded 'Source is stale or future-dated' as a retryable failure (status
        ready), so later ticks kept claiming a story that can never become fresh."""
        from news_mvp.controller import tick
        packet = _shift_sources(json.loads(json.dumps(self.case.packet)), 30)
        packet["story_key"] = "url:https://www.epressi.com/tiedotteet/aged-while-waiting"
        cfg = load_config(self.case.cfg)
        job_id = ingest(cfg, packet, self.case.now)["id"]
        later = self.case.now + timedelta(hours=19)
        result = tick(self.case.cfg, now=later, target_job_id=job_id)
        with database(self.case.state) as store:
            row = store.get(job_id)
        self.assertEqual(result, {"status": "stale_retired", "id": job_id})
        self.assertEqual(row["status"], "failed")
        self.assertIn("aged out", row["error"])


if __name__ == "__main__":
    unittest.main()
