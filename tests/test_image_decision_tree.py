"""Offline coverage for the subject-driven image tree and denser homepage."""

import hashlib
import io
import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from news_mvp import imagery, site
from news_mvp.editorial import ROOT, digest
from news_mvp.release_contract import stock_binding


DECISION = json.loads((ROOT / "fixtures/image-classifier-output.json").read_text())
DECISION = {
    **DECISION,
    "subject": "Nordic municipal cooperation meeting",
    "depictable_scene": "Municipal leaders meeting in a Nordic civic room",
    "must_show": ["municipal leaders meeting", "Nordic cooperation"],
    "must_avoid": ["trash truck", "legible text", "logos"],
    "search_queries": [
        "Nordic municipal cooperation meeting",
        "kuntajohtajat kokous",
        "Nordic municipal leaders conference",
    ],
    "category": "Kotimaa",
}
DRAFT = {
    "title": "Ikonen: kuntien ohjaus esillä pohjoismaisessa kokouksessa",
    "summary": "Kuntien ohjausta käsitellään pohjoismaisessa kokouksessa.",
    "category": "Kotimaa",
    "paragraphs": [
        {"text": "Kuntien ohjaus on esillä pohjoismaisessa kokouksessa.", "source_ids": ["A"]},
        {"text": "Kokous kokoaa kuntien edustajia keskustelemaan yhteistyöstä.", "source_ids": ["A"]},
    ],
}


def structured_png():
    image = Image.new("RGB", (900, 600), (120, 140, 160))
    draw = ImageDraw.Draw(image)
    for top in range(0, 600, 100):
        for left in range(0, 900, 100):
            draw.rectangle((left, top, left + 99, top + 99),
                           fill=(40, 90, 200) if (left // 100 + top // 100) % 2 else (230, 210, 120))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class ClassifierContract(unittest.TestCase):
    def test_fixture_has_exact_six_field_contract(self):
        result = imagery.validate_image_decision(DECISION, DRAFT)
        self.assertEqual(set(result), imagery.IMAGE_DECISION_KEYS)
        self.assertEqual(len(result["search_queries"]), 3)
        self.assertIn("kuntajohtajat kokous", result["search_queries"])

    def test_ambiguous_or_extra_classifier_output_is_rejected(self):
        for mutation in (
            {**DECISION, "extra": True},
            {**DECISION, "search_queries": ["municipality"]},
            {**DECISION, "must_show": []},
            {**DECISION, "search_queries": [
                "trash truck collection", "garbage vehicle depot", "waste truck parking",
            ]},
        ):
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    imagery.validate_image_decision(mutation, DRAFT)

    def test_existing_model_call_path_is_used(self):
        calls = []

        class Model:
            def call(self, role, packet, draft):
                calls.append((role, packet, draft))
                return DECISION

        result = imagery.classify_draft(DRAFT, model=Model(), packet={"story_key": "x"})
        self.assertEqual(result, DECISION)
        self.assertEqual(calls[0][0], "image_classifier")

    def test_explicitly_absent_must_avoid_content_is_not_rejected(self):
        result = imagery.relevance_check(
            "Nordic cooperation municipal leaders meeting; no legible text, logos or trash truck.",
            DECISION,
            "vision")
        self.assertTrue(result["accepted"])


class ProviderTree(unittest.TestCase):
    def test_order_and_attribution_recording(self):
        calls = []
        candidate = {
            "photo_id": "wikimedia-123456",
            "photo_page": "https://commons.wikimedia.org/wiki/File:Meeting.jpg",
            "profile": "https://commons.wikimedia.org/wiki/User:Author",
            "name": "Author Example",
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/a/a1/Meeting.jpg",
            "description": "municipal leaders meeting",
            "license": "CC BY-SA 4.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        }
        with tempfile.TemporaryDirectory() as state, \
                mock.patch.object(imagery, "fetch_pexels",
                                  side_effect=lambda *args, **kwargs: calls.append("pexels") or None), \
                mock.patch.object(imagery, "fetch_unsplash",
                                  side_effect=lambda *args, **kwargs: calls.append("unsplash") or None), \
                mock.patch.object(imagery, "fetch_wikimedia",
                                  side_effect=lambda *args, **kwargs: calls.append("wikimedia") or {
                                      "generated": False, "provider": "wikimedia"}), \
                mock.patch.object(imagery, "fetch_google",
                                  side_effect=lambda *args, **kwargs: calls.append("google") or None), \
                mock.patch.object(imagery, "generate", side_effect=AssertionError("fallback")):
            result = imagery.build_image(DRAFT, state, decision=DECISION)
        self.assertEqual(calls, ["pexels", "unsplash", "wikimedia"])
        self.assertEqual(result["classifier_output"], DECISION)
        self.assertTrue(result["relevance_check"]["accepted"])

        raw = structured_png()
        with tempfile.TemporaryDirectory() as state:
            sha, local_path, pixels = imagery._persist_verified_image(raw, state)
            relevance = imagery.relevance_check("Nordic cooperation municipal leaders meeting", DECISION)
            record = imagery._open_source_record(
                "wikimedia", candidate, DECISION["search_queries"][0], state, pixels,
                sha, local_path, "municipal leaders meeting", DECISION, relevance,
                "2026-09-23T00:00:00Z")
            bound = stock_binding(record)
        self.assertEqual(bound["stock_provenance"]["license"], "CC BY-SA 4.0")
        self.assertEqual(bound["stock_provenance"]["photographer"], "Author Example")
        self.assertEqual(bound["source_url"], candidate["photo_page"])

    def test_candidate_that_misses_must_show_is_skipped(self):
        def pexels(photo_id, alt):
            return {
                "id": photo_id,
                "url": f"https://www.pexels.com/photo/municipal-meeting-{photo_id}/",
                "photographer": "Fixture Author",
                "photographer_url": "https://www.pexels.com/@fixture-author",
                "alt": alt,
                "src": {"large": f"https://images.pexels.com/photos/{photo_id}/fixture.jpg"},
            }

        # The misleading result has the stronger keyword score, so the vision gate must reject
        # it before the weaker but actually relevant candidate is considered.
        bad = pexels(123456, "Nordic cooperation municipal leaders meeting beside a trash truck")
        good = pexels(123457, "municipal meeting in a civic room")
        with tempfile.TemporaryDirectory() as state, \
                mock.patch.object(imagery, "provider_key", return_value="fixture-key"), \
                mock.patch.object(imagery, "_reserve_pexels_request", return_value=True), \
                mock.patch.object(imagery, "_pexels_search", return_value={"photos": [bad, good]}), \
                mock.patch.object(imagery, "_get_bytes", return_value=structured_png()), \
                mock.patch.object(imagery, "describe", side_effect=[
                    "a trash truck at a municipal depot",
                    "Nordic cooperation municipal leaders meeting in a civic room",
                ]):
            result = imagery.fetch_pexels(DRAFT, state, decision=DECISION)
        self.assertIsNotNone(result)
        self.assertEqual(result["stock_provenance"]["photo_id"], "123457")
        self.assertEqual(result["relevance_check"]["method"], "vision")
        self.assertTrue(result["relevance_check"]["accepted"])


class GenerationFallback(unittest.TestCase):
    def test_generation_uses_decision_and_hides_model_from_credit(self):
        with tempfile.TemporaryDirectory() as state, \
                mock.patch.object(imagery, "fetch_pexels", return_value=None), \
                mock.patch.object(imagery, "fetch_unsplash", return_value=None), \
                mock.patch.object(imagery, "fetch_wikimedia", return_value=None), \
                mock.patch.object(imagery, "fetch_google", return_value=None), \
                mock.patch.object(imagery, "generate",
                                  return_value=(structured_png(), "decision prompt", "deepseek-test")), \
                mock.patch.object(imagery, "describe", return_value=None):
            result = imagery.build_image(DRAFT, state, decision=DECISION)
        self.assertTrue(result["generated"])
        self.assertEqual(result["credit"], "AI-kuvitus")
        self.assertNotIn("deepseek", result["credit"])
        self.assertEqual(result["classifier_output"], DECISION)
        self.assertEqual(result["relevance_check"]["method"], "generation")
        prompt = imagery._prompt_for(
            DECISION["subject"], DECISION["category"], DECISION["depictable_scene"],
            DECISION["must_show"], DECISION["must_avoid"])
        self.assertIn("municipal leaders meeting", prompt)
        self.assertIn("Depictable scene", prompt)


class HomepageModules(unittest.TestCase):
    class Store:
        def __init__(self, jobs):
            self.jobs = jobs

        def articles(self):
            return list(self.jobs)

        def mark_rendered(self, ids):
            pass

    def test_additional_headline_rows_and_archive_topic_modules_render(self):
        # Reuse the already reviewed, text-only release fixture; no network or image provider is
        # involved in this homepage test.
        from test_release_v2 import ReleaseV2

        case = ReleaseV2("source_fetch")
        case.setUp()
        self.addCleanup(case.doCleanups)
        template = case.ready()
        jobs = []
        categories = ["Kotimaa", "Maailma", "Talous", "Tiede", "Kulttuuri", "Urheilu"]
        for index in range(12):
            job = dict(template)
            draft = json.loads(job["draft"])
            draft["category"] = categories[index % len(categories)]
            job["draft"] = json.dumps(draft, ensure_ascii=False)
            review = json.loads(job["review"])
            review["draft_sha256"] = digest(draft)
            job["review"] = json.dumps(review, ensure_ascii=False)
            job["id"] = hashlib.sha256(f"homepage-decision:{index}".encode()).hexdigest()
            job["created_at"] = (datetime(2026, 9, 23, tzinfo=timezone.utc) -
                                  timedelta(minutes=index)).isoformat()
            jobs.append(job)
        output = Path(tempfile.mkdtemp(dir=case.root))
        self.addCleanup(lambda: __import__("shutil").rmtree(output, ignore_errors=True))
        self.assertEqual(site.render_site(self.Store(jobs), output, case.state, public=True), 12)
        html = (output / "index.html").read_text()
        entries = re.findall(r'<article class="([^"]+)"', html)
        self.assertEqual(sum("portal-teaser" in entry for entry in entries), site.HOMEPAGE_CENTER_ROWS)
        self.assertIn('class="portal-topic-strip"', html)
        self.assertEqual(html.count('class="portal-topic-card portal-topic-card--'), 6)
        self.assertIn("Kulttuuri", html)
        self.assertIn("Urheilu", html)


if __name__ == "__main__":
    unittest.main()
