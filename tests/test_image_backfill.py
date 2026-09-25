"""Bounded reviewed image coverage for already admitted stories."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from news_mvp.controller import backfill_missing_images
from news_mvp.editorial import digest
from news_mvp.store import database
import test_generated_integrity as generated


IMAGE = {
    "url": "https://example.invalid/image.jpg",
    "source_url": "https://example.invalid/source",
    "license_url": "https://example.invalid/license",
    "license": "Test permission",
    "alt": "Arkistokuva aiheesta esimerkki",
    "credit": "Test photographer",
}


class Reviewer:
    name = "backfill-test-reviewer"

    def __init__(self):
        self.calls = []

    def call(self, role, packet, draft=None):
        self.calls.append(role)
        if role == 'image_classifier':
            return {'subject': draft['title'], 'depictable_scene': 'public library building',
                    'must_show': ['library building'], 'must_avoid': ['people'],
                    'search_queries': ['public library building', 'library building exterior', 'library interior shelves'],
                    'category': draft['category']}
        return {"approved": True, "draft_sha256": digest(draft),
                "reasons": ["Reviewed image coverage fixture"]}


class MemoryStore:
    def __init__(self, jobs):
        self.jobs = jobs

    def articles(self):
        return list(self.jobs)

    def save_reviewed_image(self, job_id, packet, draft, review, *_hashes):
        job = next(job for job in self.jobs if job["id"] == job_id)
        job.update(packet=json.dumps(packet), draft=json.dumps(draft),
                   review=json.dumps(review), status="approved")

    def get(self, job_id):
        return next(job for job in self.jobs if job["id"] == job_id)


def memory_job(index, template):
    packet = copy.deepcopy(template["packet"])
    draft = copy.deepcopy(template["draft"])
    packet["story_key"] += f"-backfill-{index}"
    packet["sources"][0]["url"] += f"-backfill-{index}"
    identifier = hashlib.sha256(packet["story_key"].encode()).hexdigest()
    return {"id": identifier, "packet": json.dumps(packet), "draft": json.dumps(draft),
            "review": json.dumps({"approved": True, "draft_sha256": digest(draft),
                                  "reasons": ["text-only fixture"]}),
            "status": "rendered"}


class ImageBackfill(unittest.TestCase):
    def test_limit_and_missing_image_filter(self):
        template = {"packet": {"story_key": "url:https://example.invalid/story",
                                "sources": [{"url": "https://example.invalid/source",
                                             "id": "A"}], "image": None},
                    "draft": {"title": "Esimerkkijuttu", "summary": "Yhteenveto.",
                              "category": "Kotimaa", "paragraphs": [
                                  {"text": "Ensimmäinen kappale.", "source_ids": ["A"]},
                                  {"text": "Toinen kappale.", "source_ids": ["A"]}], "image": None}}
        # validate_draft is intentionally not part of this small rate-limit double; the real
        # store/release test below exercises the complete reviewed record contract.
        jobs = [memory_job(index, template) for index in range(5)]
        reviewer = Reviewer()
        with patch("news_mvp.imagery.build_image", return_value=IMAGE) as build:
            attached = backfill_missing_images(MemoryStore(jobs), tempfile.mkdtemp(), reviewer,
                                               limit=99)
        self.assertEqual(len(attached), 3)
        self.assertEqual(build.call_count, 3)
        self.assertEqual(reviewer.calls, ["image_classifier", "reviewer"] * 3)
        self.assertEqual(sum(json.loads(job["packet"]).get("image") is not None for job in jobs), 3)

    def test_failed_chain_keeps_story_text_only(self):
        template = {"packet": {"story_key": "url:https://example.invalid/story",
                                "sources": [{"url": "https://example.invalid/source",
                                             "id": "A"}], "image": None},
                    "draft": {"title": "Esimerkkijuttu", "summary": "Yhteenveto.",
                              "category": "Kotimaa", "paragraphs": [
                                  {"text": "Ensimmäinen kappale.", "source_ids": ["A"]},
                                  {"text": "Toinen kappale.", "source_ids": ["A"]}], "image": None}}
        job = memory_job(0, template)
        reviewer = Reviewer()
        with patch("news_mvp.imagery.build_image", return_value=None):
            self.assertEqual(backfill_missing_images(MemoryStore([job]), tempfile.mkdtemp(), reviewer), [])
        self.assertIsNone(json.loads(job["packet"]).get("image"))
        self.assertEqual(reviewer.calls, ["image_classifier"])

    def test_deployed_text_only_story_is_reset_only_for_a_reviewed_image(self):
        case = generated.GeneratedIntegrity("test_generated_binding_keeps_text_provenance_and_not_applicable_marker")
        case.setUp()
        self.addCleanup(case.doCleanups)
        image_packet, _image_draft = case.generated()
        job = case.ready(case.packet, case.draft)
        old_packet = json.loads(job["packet"])
        old_draft = json.loads(job["draft"])
        with database(case.state) as store:
            store.db.execute(
                "INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) "
                "VALUES(?,?,?,?,?,'deployed')",
                (job["id"], digest(old_packet), digest(old_draft), None, "a" * 40),
            )
            store.db.commit()
        reviewer = Reviewer()
        with patch("news_mvp.imagery.build_image", return_value=image_packet["image"]):
            with database(case.state) as store:
                attached = backfill_missing_images(store, case.state, reviewer)
                self.assertEqual(len(attached), 1)
                updated = store.get(job["id"])
                publication = store.db.execute(
                    "SELECT * FROM publications WHERE job_id=?", (job["id"],)
                ).fetchone()
        self.assertEqual(json.loads(updated["draft"])["image"], image_packet["image"])
        self.assertEqual(publication["status"], "preparing")
        self.assertEqual(publication["packet_sha"], digest(json.loads(updated["packet"])))
        self.assertEqual(publication["draft_sha"], digest(json.loads(updated["draft"])))
        self.assertEqual(publication["image_sha"], image_packet["image"]["sha256"])


if __name__ == "__main__":
    unittest.main()
