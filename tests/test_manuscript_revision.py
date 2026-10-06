"""Isolated contract tests for the explicit rejected-manuscript amendment."""
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from news_mvp.controller import ingest, load_config, single_tick, tick
from news_mvp.editorial import digest
from news_mvp.intake import (MANUSCRIPT_REVISION_KIND, revise_manuscript)
from news_mvp.publish import ensure_table
from news_mvp.store import database


NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)


def article_text_sha(draft):
    article = {key: draft[key] for key in ("title", "summary", "category", "paragraphs")}
    return hashlib.sha256(
        json.dumps(article, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


class ManuscriptRevision(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps({
            "enabled": True,
            "backend": "hermes",
            "state_dir": "state",
            "output_dir": "site",
            "max_source_age_hours": 48,
            "illustrations": True,
        }))
        self.config = load_config(self.config_path)
        source_text = (
            "Helsingin kaupunki kertoo influenssa- ja koronarokotusten aikataulusta, "
            "ajanvarauksesta ja rokotuspaikoista. Kaupungin tiedote kuvaa ikäryhmien "
            "ajat sekä neuvoloiden käytännöt. Tämä synteettinen ote on riittävän pitkä "
            "vain rakenteellisen sopimuksen testaamiseen eikä sitä julkaista. "
        )
        self.packet = {
            "story_key": "url:https://www.hel.fi/fi/uutiset/testirokotukset",
            "fixture": False,
            "sources": [
                {"id": "A", "url": "https://www.hel.fi/fi/uutiset/testirokotukset",
                 "publisher": "Helsingin kaupunki", "title": "Rokotukset alkavat",
                 "published_at": (NOW - timedelta(hours=1)).isoformat(),
                 "text": source_text},
                {"id": "B", "url": "https://www.example.com/uutiset/testirokotukset",
                 "publisher": "Esimerkkilehti", "title": "Rokotusaikataulu",
                 "published_at": (NOW - timedelta(minutes=30)).isoformat(),
                 "text": source_text + " Lehti kertoo samasta aikataulusta."},
            ],
            "supporting_documents": [{
                "id": "RIGHTS", "purpose": "text reuse rights",
                "url": "https://www.hel.fi/fi/kayttoehdot", "sha256": "c" * 64,
                "text": "Synthetic retained rights evidence",
            }],
            "publication_basis": {"provider": "helsinki", "policy": "official-text-v1"},
        }
        old_text = {
            "category": "Kotimaa",
            "title": "Helsingin rokotukset alkoivat",
            "summary": "Kaupunki kertoo rokotusten aikataulusta ja ajanvarauksesta.",
            "paragraphs": [
                {"text": "Kaupunki kertoo rokotusten alkaneen. Lehti kertoo samasta aikataulusta.",
                 "source_ids": ["A", "B"]},
                {"text": "Ajanvaraus on avoinna kaupungin palvelussa. Lehti vahvistaa ohjeen.",
                 "source_ids": ["A", "B"]},
            ],
        }
        self.old_image = {
            "url": "https://images.example.com/old.jpg",
            "source_url": "https://images.example.com/old-source",
            "license_url": "https://images.example.com/old-rights",
            "license": "Synthetic image rights",
            "alt": "Rokotustarvikkeita pöydällä.",
            "credit": "Synthetic old image",
            "sha256": "a" * 64,
            "pixel_review": {
                "approved": True,
                "no_people": True,
                "image_sha256": "a" * 64,
                "article_text_sha256": article_text_sha(old_text),
                "description": "Synthetic old pixels",
                "reason": "Synthetic prior review",
            },
        }
        self.packet["image"] = copy.deepcopy(self.old_image)
        self.old_draft = {**old_text, "image": copy.deepcopy(self.old_image)}
        self.candidate = {
            "category": old_text["category"],
            "title": old_text["title"],
            "summary": old_text["summary"],
            "paragraphs": [
                copy.deepcopy(old_text["paragraphs"][0]),
                {"text": "Ajanvaraus on avoinna kaupungin palvelussa.", "source_ids": ["A"]},
            ],
        }
        self.job_id = ingest(self.config, self.packet, NOW)["id"]
        self.rejected_review = {
            "approved": False,
            "draft_sha256": digest(self.old_draft),
            "reasons": ["Secondary citation does not support every claim."],
        }
        with database(self.config["state_dir"]) as store:
            store.save_draft(self.job_id, self.old_draft, "synthetic-writer")
            store.finish_review(self.job_id, self.rejected_review)
            ensure_table(store)
            self.original = store.get(self.job_id)

    def test_missing_publication_table_is_unknown_not_empty(self):
        with database(self.config["state_dir"]) as store:
            with store.db:
                store.db.execute("DROP TABLE publications")
        with self.assertRaisesRegex(ValueError, "Publication state is missing"):
            revise_manuscript(self.config, self.job_id, self.candidate, NOW)
        with database(self.config["state_dir"]) as store:
            self.assertEqual(store.get(self.job_id), self.original)

    def test_archives_complete_rejection_and_installs_only_text_candidate(self):
        result = revise_manuscript(self.config, self.job_id, self.candidate, NOW)
        self.assertEqual(result["candidate_sha256"], digest(self.candidate))
        archive = json.loads(Path(result["previous_record"]).read_text())
        self.assertEqual(archive["revision_kind"], MANUSCRIPT_REVISION_KIND)
        self.assertEqual(archive["candidate_sha256"], digest(self.candidate))
        self.assertIn("fresh image and editorial review", archive["reason"])
        self.assertEqual(archive["previous_job"], self.original)
        with database(self.config["state_dir"]) as store:
            current = store.get(self.job_id)
        self.assertEqual(current["packet"], self.original["packet"])
        self.assertEqual(current["story_key"], self.original["story_key"])
        self.assertEqual(current["source_url"], self.original["source_url"])
        self.assertEqual(current["status"], "ready")
        self.assertIsNone(current["review"])
        self.assertEqual(json.loads(current["draft"]), {**self.candidate, "image": None})
        self.assertEqual((current["attempts"], current["next_attempt"], current["error"]),
                         (0, 0, None))

    def test_exact_whitelists_reject_control_and_nested_fields(self):
        for field in ("image", "review", "approval", "provider", "packet", "config"):
            with self.subTest(field=field):
                bad = {**copy.deepcopy(self.candidate), field: {}}
                with self.assertRaisesRegex(ValueError, "exactly category"):
                    revise_manuscript(self.config, self.job_id, bad, NOW)
        nested = copy.deepcopy(self.candidate)
        nested["paragraphs"][0]["review"] = "old approval"
        with self.assertRaisesRegex(ValueError, "exactly text and source_ids"):
            revise_manuscript(self.config, self.job_id, nested, NOW)

    def test_rejected_saved_review_and_real_pipeline_are_mandatory(self):
        unchanged = {key: copy.deepcopy(self.old_draft[key]) for key in self.candidate}
        with self.assertRaisesRegex(ValueError, "does not amend"):
            revise_manuscript(self.config, self.job_id, unchanged, NOW)
        with database(self.config["state_dir"]) as store:
            with store.db:
                store.db.execute("UPDATE jobs SET status='ready' WHERE id=?", (self.job_id,))
        with self.assertRaisesRegex(ValueError, "rejected saved draft"):
            revise_manuscript(self.config, self.job_id, self.candidate, NOW)
        with database(self.config["state_dir"]) as store:
            with store.db:
                store.db.execute("UPDATE jobs SET status='rejected',review=NULL WHERE id=?",
                                 (self.job_id,))
        with self.assertRaisesRegex(ValueError, "rejected saved draft and review"):
            revise_manuscript(self.config, self.job_id, self.candidate, NOW)
        with self.assertRaisesRegex(ValueError, "does not exist"):
            revise_manuscript(self.config, "f" * 64, self.candidate, NOW)
        disabled = {**self.config, "illustrations": False}
        with self.assertRaisesRegex(ValueError, "illustrations pipeline"):
            revise_manuscript(disabled, self.job_id, self.candidate, NOW)

    def test_malformed_citations_stale_source_and_publication_are_fenced(self):
        bad = copy.deepcopy(self.candidate)
        bad["paragraphs"][1]["source_ids"] = ["UNKNOWN"]
        with self.assertRaisesRegex(ValueError, "known source IDs"):
            revise_manuscript(self.config, self.job_id, bad, NOW)

        stale = copy.deepcopy(self.packet)
        stale["sources"][0]["published_at"] = (NOW - timedelta(days=3)).isoformat()
        with database(self.config["state_dir"]) as store:
            with store.db:
                store.db.execute("UPDATE jobs SET packet=? WHERE id=?",
                                 (json.dumps(stale, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")), self.job_id))
        with self.assertRaisesRegex(ValueError, "stale"):
            revise_manuscript(self.config, self.job_id, self.candidate, NOW)

        with database(self.config["state_dir"]) as store:
            with store.db:
                store.db.execute("UPDATE jobs SET packet=? WHERE id=?",
                                 (self.original["packet"], self.job_id))
            ensure_table(store)
            with store.db:
                store.db.execute(
                    "INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,"
                    "source_commit,status) VALUES(?,?,?,?,?,?)",
                    (self.job_id, "packet", "draft", "image", "source", "unknown"),
                )
        with self.assertRaisesRegex(ValueError, "forbidden after publication preparation"):
            revise_manuscript(self.config, self.job_id, self.candidate, NOW)

    def test_controller_busy_refuses_without_touching_rejection(self):
        with single_tick(self.config["state_dir"]) as locked:
            self.assertTrue(locked)
            with self.assertRaisesRegex(ValueError, "Another tick"):
                revise_manuscript(self.config, self.job_id, self.candidate, NOW)
        with database(self.config["state_dir"]) as store:
            self.assertEqual(store.get(self.job_id), self.original)

    def test_normal_tick_uses_amended_draft_then_fresh_image_and_review(self):
        revise_manuscript(self.config, self.job_id, self.candidate, NOW)
        decision = {
            "version": "article-first-v1",
            "category": "Kotimaa",
            "concepts": [
                {"rank": 1, "safe_to_generate": False,
                 "subject": "Helsingin rokotukset",
                 "depictable_scene": "Rokotustarvikkeita suljetulla hoitopöydällä.",
                 "must_show": ["rokotustarvikkeet"], "must_avoid": ["tunnistettavat ihmiset"],
                 "search_queries": ["Helsinki vaccination supplies", "rokotustarvikkeet Helsinki",
                                    "vaccination equipment Finland"]},
                {"rank": 2, "safe_to_generate": True,
                 "subject": "rokotusten ajanvaraus",
                 "depictable_scene": "Suljettuja rokotustarvikkeita tyhjällä pöydällä.",
                 "must_show": ["suljetut rokotustarvikkeet"], "must_avoid": ["ihmiset"],
                 "search_queries": ["sealed vaccination supplies", "rokotusvälineet tyhjä pöytä",
                                    "medical supplies table"]},
            ],
        }

        class OfflineModel:
            name = "offline-revision-test"

            def __init__(self):
                self.calls = []

            def call(inner, role, packet, draft=None):
                inner.calls.append(role)
                if role == "writer":
                    raise AssertionError("saved amended manuscript must bypass the writer")
                if role == "image_classifier":
                    self.assertNotIn("image", draft)
                    self.assertNotIn("image", packet)
                    return decision
                self.assertEqual(role, "reviewer")
                self.assertEqual({key: draft[key] for key in self.candidate}, self.candidate)
                self.assertEqual(draft["image"]["sha256"], "b" * 64)
                return {"approved": True, "draft_sha256": digest(draft),
                        "reasons": ["Fresh review supports the amended exact draft."]}

        model = OfflineModel()

        def freshly_reviewed_image(draft, _state_dir, **kwargs):
            self.assertEqual(draft["image"], self.old_image)
            self.assertEqual(kwargs["packet"]["image"], self.old_image)
            self.assertEqual(kwargs["decision"], decision)
            return {
                "url": "https://images.example.com/fresh.jpg",
                "source_url": "https://images.example.com/fresh-source",
                "license_url": "https://images.example.com/fresh-rights",
                "license": "Synthetic fresh image rights",
                "alt": "Suljettuja rokotustarvikkeita pöydällä.",
                "credit": "Synthetic fresh image",
                "sha256": "b" * 64,
                "pixel_review": {
                    "approved": True,
                    "no_people": True,
                    "image_sha256": "b" * 64,
                    "article_text_sha256": article_text_sha(draft),
                    "description": "Fresh synthetic pixels",
                    "reason": "Fresh exact-pixel review for amended article text",
                },
            }

        with mock.patch("news_mvp.imagery.build_image", side_effect=freshly_reviewed_image) as build:
            result = tick(self.config_path, model=model, now=NOW, target_job_id=self.job_id)
        self.assertEqual(result["status"], "rendered")
        self.assertEqual(model.calls, ["image_classifier", "reviewer"])
        build.assert_called_once()
        with database(self.config["state_dir"]) as store:
            current = store.get(self.job_id)
        final_draft = json.loads(current["draft"])
        final_review = json.loads(current["review"])
        self.assertEqual(current["status"], "rendered")
        self.assertEqual(final_draft["image"]["sha256"], "b" * 64)
        self.assertNotEqual(final_review, self.rejected_review)
        self.assertEqual(final_review["draft_sha256"], digest(final_draft))

    def test_cli_help_and_real_entrypoint_use_only_synthetic_state(self):
        repository = Path(__file__).resolve().parents[1]
        help_result = subprocess.run(
            [sys.executable, "-m", "news_mvp", "revise-manuscript", "--help"],
            cwd=repository, text=True, capture_output=True, check=False,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--job", help_result.stdout)
        self.assertIn("manuscript", help_result.stdout)

        candidate_path = self.root / "candidate.json"
        candidate_path.write_text(json.dumps(self.candidate, ensure_ascii=False), encoding="utf-8")
        current_packet = copy.deepcopy(self.packet)
        for source in current_packet["sources"]:
            source["published_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        with database(self.config["state_dir"]) as store:
            with store.db:
                store.db.execute(
                    "UPDATE jobs SET packet=? WHERE id=?",
                    (json.dumps(current_packet, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")), self.job_id),
                )
        result = subprocess.run(
            [sys.executable, "-m", "news_mvp", "revise-manuscript",
             "--config", str(self.config_path), "--job", self.job_id, str(candidate_path)],
            cwd=repository, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual((output["id"], output["status"], output["candidate_sha256"]),
                         (self.job_id, "ready", digest(self.candidate)))


if __name__ == "__main__":
    unittest.main()
