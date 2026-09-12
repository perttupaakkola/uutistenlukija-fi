import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from news_mvp.controller import ingest, load_config, single_tick, tick
from news_mvp.editorial import ROOT, FixtureModel, digest
from news_mvp.site import article_path, render_site
from news_mvp.store import database


class Smoke(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".test-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps({"enabled": True, "backend": "fixture",
                                                "state_dir": "state", "output_dir": "site"}))
        self.config = load_config(self.config_path)
        self.now = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
        self.packet = json.loads((ROOT / "fixtures/source-packet.json").read_text())

    def admit(self):
        return ingest(self.config, self.packet, self.now)["id"]

    def test_intake_draft_review_render_and_duplicate_tick(self):
        first = ingest(self.config, self.packet, self.now)
        again = ingest(self.config, self.packet, self.now)
        alias = copy.deepcopy(self.packet)
        alias["story_key"] = "a-new-key-for-the-same-primary-source"
        self.assertEqual(first["id"], ingest(self.config, alias, self.now)["id"])
        self.assertTrue(first["admitted"])
        self.assertFalse(again["admitted"])
        result = tick(self.config_path, now=self.now)
        self.assertEqual(result["status"], "rendered")
        with database(self.config["state_dir"]) as store:
            job = store.get(first["id"])
            self.assertEqual(len(store.status()), 1)
            self.assertEqual(job["attempts"], 1)
            self.assertEqual(json.loads(job["review"])["draft_sha256"], digest(json.loads(job["draft"])))
            article = self.config["output_dir"] / article_path(job) / "index.html"
        self.assertTrue(article.is_file())
        html = article.read_text()
        self.assertIn('lang="fi"', html)
        self.assertIn('name="viewport"', html)
        self.assertIn("keksitty uutinen", html)
        self.assertIn('id="lahde-1"', html)
        self.assertIn('noindex,nofollow', html)
        self.assertEqual(tick(self.config_path, now=self.now)["status"], "idle")

    def test_real_subprocess_exit_after_saved_draft_resumes_at_review(self):
        job_id = self.admit()
        code = '''
import os, sys
from datetime import datetime
from news_mvp.controller import tick
from news_mvp.editorial import FixtureModel
class Interrupted(FixtureModel):
    def call(self, role, packet, draft=None):
        if role == "reviewer": os._exit(73)
        return super().call(role, packet, draft)
tick(sys.argv[1], model=Interrupted(), now=datetime.fromisoformat(sys.argv[2]))
'''
        child = subprocess.run([sys.executable, "-B", "-c", code, str(self.config_path), self.now.isoformat()],
                               cwd=ROOT, timeout=10, capture_output=True, text=True)
        self.assertEqual(child.returncode, 73, child.stderr)
        with database(self.config["state_dir"]) as store:
            self.assertEqual(store.get(job_id)["status"], "running")
            saved = store.get(job_id)["draft"]
            self.assertIsNotNone(saved)

        class ReviewOnly(FixtureModel):
            def call(self, role, packet, draft=None):
                if role == "writer":
                    raise AssertionError("Persisted draft must not be rewritten")
                return super().call(role, packet, draft)

        self.assertEqual(tick(self.config_path, model=ReviewOnly(), now=self.now)["status"], "rendered")
        with database(self.config["state_dir"]) as store:
            self.assertEqual(store.get(job_id)["draft"], saved)
            self.assertEqual(store.get(job_id)["attempts"], 2)
            self.assertEqual(len(store.articles()), 1)

    def test_rejection_and_writer_withholding_never_render(self):
        self.admit()

        class Reject(FixtureModel):
            def call(self, role, packet, draft=None):
                value = super().call(role, packet, draft)
                if role == "reviewer":
                    value.update(approved=False, reasons=["Fixture source does not establish this claim"])
                return value

        self.assertEqual(tick(self.config_path, model=Reject(), now=self.now)["status"], "rejected")
        self.assertFalse((self.config["output_dir"] / "index.html").exists())
        self.packet["story_key"] += "-held"
        self.packet["sources"][0]["url"] += "-held"
        self.admit()

        class Withhold(FixtureModel):
            def call(self, role, packet, draft=None):
                return {"withhold": True, "reason": "Fixture evidence is insufficient"}

        self.assertEqual(tick(self.config_path, model=Withhold(), now=self.now)["status"], "rejected")

    def test_wrong_review_hash_retries_are_bounded(self):
        job_id = self.admit()

        class WrongHash(FixtureModel):
            def call(self, role, packet, draft=None):
                value = super().call(role, packet, draft)
                if role == "reviewer":
                    value["draft_sha256"] = "0" * 64
                return value

        for minute in (0, 2, 5):
            result = tick(self.config_path, model=WrongHash(), now=self.now + timedelta(minutes=minute))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(tick(self.config_path, now=self.now + timedelta(hours=1))["status"], "idle")
        with database(self.config["state_dir"]) as store:
            self.assertEqual(store.get(job_id)["attempts"], 3)
        self.assertFalse(self.config["output_dir"].exists())

    def test_stale_thin_and_unlabelled_fixture_input_refused(self):
        for change in ("stale", "thin", "unlabelled", "malformed"):
            packet = copy.deepcopy(self.packet)
            if change == "stale":
                packet["sources"][0]["published_at"] = "2020-01-01T12:00:00Z"
            elif change == "thin":
                packet["sources"][0]["text"] = "No useful source evidence."
            elif change == "unlabelled":
                packet["fixture"] = False
            else:
                packet["sources"][0] = []
            with self.assertRaises(ValueError, msg=change):
                ingest(self.config, packet, self.now)
        self.assertFalse(self.config["state_dir"].exists())

    def test_stop_switch_and_single_tick_lock(self):
        self.admit()
        with single_tick(self.config["state_dir"]):
            self.assertEqual(tick(self.config_path, now=self.now)["status"], "busy")
        config = json.loads(self.config_path.read_text())
        config["enabled"] = False
        self.config_path.write_text(json.dumps(config))
        self.assertEqual(tick(self.config_path, now=self.now)["status"], "stopped")
        with database(self.config["state_dir"]) as store:
            self.assertEqual(store.status()[0]["attempts"], 0)

    def test_renderer_escapes_source_and_model_text(self):
        job_id = self.admit()
        draft = FixtureModel().call("writer", self.packet)
        draft["title"] = '<script>alert("not executable")</script>'
        with database(self.config["state_dir"]) as store:
            store.save_draft(job_id, draft, "fixture")
            store.finish_review(job_id, {"approved": True, "draft_sha256": digest(draft), "reasons": ["Escaping fixture"]})
            render_site(store, self.config["output_dir"])
        html = (self.config["output_dir"] / "index.html").read_text()
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_local_image_identity_is_checked_before_rendering(self):
        data = b'\xff\xd8\xfflocal-image-test'
        sha = hashlib.sha256(data).hexdigest()
        self.packet['image'] = {'url':'https://example.invalid/photo.jpg','source_url':'https://example.invalid/source',
                                'license_url':'https://example.invalid/rights','license':'Fixture permission',
                                'alt':'Fixture image','credit':'Fixture author','sha256':sha,'local_path':f'media/{sha}.jpg'}
        job_id = self.admit()
        draft = FixtureModel().call('writer',self.packet)
        draft['image'] = self.packet['image']
        path = self.config['state_dir']/self.packet['image']['local_path']
        path.parent.mkdir();path.write_bytes(data)
        with database(self.config['state_dir']) as store:
            store.save_draft(job_id,draft,'fixture')
            store.finish_review(job_id,{'approved':True,'draft_sha256':digest(draft),'reasons':['Image identity fixture']})
            render_site(store,self.config['output_dir'],self.config['state_dir'])
            self.assertEqual((self.config['output_dir']/f'assets/{sha}.jpg').read_bytes(),data)
            path.write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                render_site(store,self.config['output_dir'],self.config['state_dir'])

    def test_explicit_evidence_amendment_archives_rejection_and_keeps_draft(self):
        from news_mvp.intake import revise_rejected
        job_id = self.admit()
        draft = FixtureModel().call('writer',self.packet)
        with database(self.config['state_dir']) as store:
            store.save_draft(job_id,draft,'fixture')
            store.finish_review(job_id,{'approved':False,'draft_sha256':digest(draft),'reasons':['Need permission evidence']})
        amended = copy.deepcopy(self.packet)
        amended['supporting_documents'] = [{'id':'RIGHTS','text':'Additional fixture permission evidence'}]
        result = revise_rejected(self.config,amended,self.now)
        archived = json.loads(Path(result['previous_record']).read_text())
        self.assertFalse(json.loads(archived['review'])['approved'])
        with database(self.config['state_dir']) as store:
            self.assertEqual(store.get(job_id)['draft'],archived['draft'])
            self.assertEqual(store.get(job_id)['status'],'ready')
            self.assertIsNone(store.get(job_id)['review'])
            self.assertEqual(len(store.status()),1)
        with self.assertRaises(ValueError):
            revise_rejected(self.config,amended,self.now)


if __name__ == "__main__":
    unittest.main()
