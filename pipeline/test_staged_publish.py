#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

try:
    from . import staged_publish
except ImportError:  # pragma: no cover - direct execution from pipeline cwd
    import staged_publish


def _record(title: str, source_words: int, blocks: int = 1) -> dict:
    research = "\n\n".join(f"[Lähde: Testi]\n{'sana ' * max(1, source_words // max(1, blocks))}" for _ in range(blocks))
    return {
        "schema": "uutistenlukija.staged_packet.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "digest": title[:10],
        "packet": {
            "packet_id": title,
            "headline_seed": title,
            "source_text": research,
            "category_hint": "Kotimaa",
        },
        "original_article": {
            "title": title,
            "description": "kuvaus",
            "research": research,
            "category_hint": "Kotimaa",
        },
    }


class StagedPublishMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for box in ["ready", "writing", "outbox", "published", "failed"]:
            (self.root / box).mkdir(parents=True, exist_ok=True)
        self.patch = patch.object(staged_publish, "STAGED_ROOT", self.root)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def _write(self, box: str, name: str, data: dict, age_hours: float = 0) -> Path:
        path = self.root / box / f"{name}.json"
        created = datetime.now(timezone.utc) - timedelta(hours=age_hours)
        data = {**data, "created_at": created.isoformat()}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        ts = created.timestamp()
        path.touch()
        import os
        os.utime(path, (ts, ts))
        return path

    def test_failure_reason_normalization(self) -> None:
        self.assertEqual(staged_publish.normalize_failure_reason("content too short: 233 words"), "content_too_short")
        self.assertEqual(staged_publish.normalize_failure_reason("Lähdeaineisto on liian niukka"), "insufficient_confidence")
        self.assertEqual(staged_publish.normalize_failure_reason("Context overflow from Monica"), "writer_runtime")
        self.assertEqual(staged_publish.normalize_failure_reason("quality gate unsourced_numbers"), "quality_gate")
        self.assertEqual(staged_publish.normalize_failure_reason("duplicate article"), "duplicate")
        self.assertEqual(staged_publish.normalize_failure_reason("stale_low_confidence_expired age_h=120.0"), "stale_low_confidence_expired")
        self.assertEqual(staged_publish.normalize_failure_reason("stale_ready_expired age_h=10.1 max_age_h=10.0"), "stale_ready_expired")

    def test_verbose_status_contains_age_source_and_failure_buckets(self) -> None:
        self._write("ready", "old-rich", _record("old-rich", source_words=360, blocks=2), age_hours=12)
        self._write("ready", "new-thin", _record("new-thin", source_words=40, blocks=1), age_hours=1)
        self._write("failed", "short", {**_record("short", 100), "failure": "content too short: 220 words"}, age_hours=2)
        self._write("failed", "runtime", {**_record("runtime", 200), "failure": "timed out"}, age_hours=3)

        now = datetime.now(timezone.utc)
        ready_status = staged_publish.queue_box_status("ready", list((self.root / "ready").glob("*.json")), now)
        failed_status = staged_publish.queue_box_status("failed", list((self.root / "failed").glob("*.json")), now)

        self.assertEqual(ready_status["count"], 2)
        self.assertGreaterEqual(ready_status["oldest_age_hours"], 11.9)
        self.assertIn("source_words_median", ready_status)
        self.assertEqual(failed_status["failure_reason_buckets"]["content_too_short"], 1)
        self.assertEqual(failed_status["failure_reason_buckets"]["writer_runtime"], 1)
        self.assertEqual(failed_status["alert_summary"]["runtime_failure_total"], 2)
        self.assertEqual(failed_status["failure_alert_buckets"]["quality"], 1)
        self.assertEqual(failed_status["failure_alert_buckets"]["writer_runtime"], 1)

    def test_failed_writer_feedback_classifies_near_miss_short_repair(self) -> None:
        record = _record("near-miss", source_words=360, blocks=3)
        record["packet"]["packet_id"] = "pkt-near-miss"
        payload = {
            "packet_id": "pkt-near-miss",
            "title": "Lähes valmis artikkeli",
            "content": " ".join(["sana"] * 248),
            "category": "Talous",
        }

        feedback = staged_publish.failed_writer_feedback(record, payload, ["content too short: 248 words"])

        self.assertEqual(feedback["packet_id"], "pkt-near-miss")
        self.assertEqual(feedback["selected_source_words"], 366)
        self.assertEqual(feedback["selected_source_blocks"], 3)
        self.assertEqual(feedback["final_word_count"], 248)
        self.assertTrue(feedback["near_miss_short"])
        self.assertEqual(feedback["retry_classification"], "repair_near_miss_short")
        self.assertTrue(feedback["fail_closed"])


    def test_failed_writer_feedback_classifies_high_confidence_209_word_talous_shortfall(self) -> None:
        record = _record("talous-209", source_words=199, blocks=3)
        record["packet"]["packet_id"] = "pkt-talous-209"
        record["packet"]["category_hint"] = "Talous"
        record["packet"]["story_confidence"] = 0.98
        payload = {
            "packet_id": "pkt-talous-209",
            "title": "Talousartikkeli jäi liian lyhyeksi",
            "content": " ".join(["sana"] * 209),
            "category": "Talous",
        }

        feedback = staged_publish.failed_writer_feedback(record, payload, ["content too short: 209 words"])

        self.assertGreaterEqual(feedback["selected_source_words"], 199)
        self.assertEqual(feedback["selected_source_blocks"], 3)
        self.assertEqual(feedback["final_word_count"], 209)
        self.assertTrue(feedback["source_backed"])
        self.assertTrue(feedback["near_miss_short"])
        self.assertEqual(feedback["retry_classification"], "repair_near_miss_short")

    def test_talous_ready_guardrail_fails_promotional_instagram_org_packet(self) -> None:
        record = _record("finanssiala-promo", source_words=145, blocks=2)
        record["packet"]["category_hint"] = "Talous"
        record["packet"]["story_confidence"] = 0.79
        record["original_article"].update({
            "category_hint": "Talous",
            "source": "Finanssiala",
            "description": "Kesätyöntekijät ottavat Finanssialalle-Instagram-tilin haltuun. Ota tili seurantaan ja vinkkaa kaverille.",
            "research": "[Lähde: Finanssiala]\nKesätyöntekijät ottavat Finanssialalle-Instagram-tilin haltuun. Ota Finanssialalle-Instagram seurantaan ja vinkkaa kaverille.",
        })

        guard = staged_publish.talous_packet_quality_guardrail(record)

        self.assertEqual(guard["action"], "fail")
        self.assertEqual(guard["reason"], "weak_talous_ready_promotional")

    def test_talous_ready_guardrail_fails_borderline_political_entrepreneur_packet(self) -> None:
        record = _record("yrittaja-eduskuntaan", source_words=169, blocks=2)
        record["packet"]["category_hint"] = "Talous"
        record["packet"]["headline_seed"] = "Yksi yrittäjä lisää eduskuntaan – Konkari palaa Arkadianmäelle"
        record["packet"]["story_confidence"] = 0.83
        record["original_article"].update({
            "category_hint": "Talous",
            "source": "Suomen Yrittäjät",
            "title": "Yksi yrittäjä lisää eduskuntaan – Konkari palaa Arkadianmäelle",
            "research": "[Lähde: Suomen Yrittäjät]\nPertti Hemmilä nousee eduskuntaan. YRITTÄJÄ, tule mukaan omiesi pariin! Liity Yrittäjiin.",
        })

        guard = staged_publish.talous_packet_quality_guardrail(record)

        self.assertEqual(guard["action"], "fail")
        self.assertEqual(guard["reason"], "weak_talous_ready_category_borderline")

    def test_talous_ready_guardrail_keeps_publishable_market_packet(self) -> None:
        record = _record("kamux", source_words=214, blocks=3)
        record["packet"]["category_hint"] = "Talous"
        record["packet"]["story_confidence"] = 0.98
        record["original_article"].update({
            "category_hint": "Talous",
            "source": "Arvopaperi",
            "description": "Kamuxin liikevaihto laski 12 prosenttia 205 miljoonaan euroon ja bruttokate parani.",
            "research": "[Lähde: Arvopaperi]\nKamuxin liikevaihto laski alkuvuonna 12 prosenttia 205 miljoonaan euroon. Oikaistu liiketulos oli tappiolla. Bruttokate parani.",
        })

        guard = staged_publish.talous_packet_quality_guardrail(record)

        self.assertEqual(guard["action"], "keep")
        self.assertEqual(guard["reason"], "source_quality_ok")


    def test_talous_cooldown_requeues_when_recent_recoverable_failure_exists(self) -> None:
        article = {"title": "talous-recoverable", "link": "https://example.com/talous-recoverable", "category_hint": "Talous"}
        digest = staged_publish.stable_digest(article)
        failed = _record("talous-recoverable", source_words=220, blocks=3)
        failed["digest"] = digest
        failed["packet"]["category_hint"] = "Talous"
        failed["packet"]["story_confidence"] = 0.98
        failed["failure"] = "content too short: 225 words"
        failed["writer_failure_feedback"] = {"retry_classification": "repair_near_miss_short"}
        self._write("failed", "old-talous", failed, age_hours=1)

        self.assertFalse(staged_publish.should_skip_staged_cooldown(article, hours=48))

    def test_talous_cooldown_still_skips_when_digest_already_ready(self) -> None:
        article = {"title": "talous-ready", "link": "https://example.com/talous-ready", "category_hint": "Talous"}
        digest = staged_publish.stable_digest(article)
        failed = _record("talous-ready", source_words=220, blocks=3)
        failed["digest"] = digest
        failed["packet"]["category_hint"] = "Talous"
        failed["writer_failure_feedback"] = {"retry_classification": "repair_near_miss_short"}
        ready = _record("talous-ready", source_words=220, blocks=3)
        ready["digest"] = digest
        ready["packet"]["category_hint"] = "Talous"
        self._write("failed", "failed-talous-ready", failed, age_hours=1)
        self._write("ready", "ready-talous-ready", ready, age_hours=0.1)

        self.assertTrue(staged_publish.should_skip_staged_cooldown(article, hours=48))

    def test_talous_cooldown_does_not_requeue_quality_gate_failure(self) -> None:
        article = {"title": "talous-quality", "link": "https://example.com/talous-quality", "category_hint": "Talous"}
        digest = staged_publish.stable_digest(article)
        failed = _record("talous-quality", source_words=360, blocks=3)
        failed["digest"] = digest
        failed["packet"]["category_hint"] = "Talous"
        failed["failure"] = "quality_gate_rejected: unsourced numbers"
        failed["quality_gate_feedback"] = {"retry_classification": "fail_closed_quality_gate"}
        self._write("failed", "failed-talous-quality", failed, age_hours=1)

        self.assertTrue(staged_publish.should_skip_staged_cooldown(article, hours=48))


    def test_failed_writer_feedback_classifies_invalid_json(self) -> None:
        record = _record("bad-json", source_words=111, blocks=4)
        record["packet"]["packet_id"] = "pkt-bad-json"

        feedback = staged_publish.failed_writer_feedback(record, None, [], raw_response="not valid json")

        self.assertEqual(feedback["packet_id"], "pkt-bad-json")
        self.assertEqual(feedback["retry_classification"], "writer_invalid_json")
        self.assertEqual(feedback["final_word_count"], 0)
        self.assertTrue(feedback["fail_closed"])

    def test_quality_gate_reject_quarantine_records_fail_closed_feedback(self) -> None:
        record = _record("rich-quality-reject", source_words=360, blocks=3)
        record["packet"]["packet_id"] = "pkt-rich-quality"
        record["packet"]["category_hint"] = "Talous"
        record["packet"]["story_confidence"] = 0.98
        article = {
            "title": "Trump asetti EU:lle määräajan tullikiistan ratkaisemiseksi",
            "description": "Trump uhkaa EU:ta uusilla tulleilla, ellei sopua synny.",
            "content": (
                "Yhdysvaltain presidentti Donald Trump vaatii EU:lta ratkaisua 4. heinäkuuta mennessä ja uhkaa "
                "10, 15, 30 ja 50 prosentin tulleilla. Neuvottelut jatkuvat Brysselissä, mutta päätöksiä ei vielä ole.\n\n"
                "## Neuvottelut jatkuvat\n\n"
                "EU:n edustajat arvioivat tilannetta ja korostavat, että sopimuksen toimeenpano vaatii jäsenmaiden hyväksyntää."
            ),
            "category": "Talous",
            "source_text": "Trump ja EU neuvottelevat tulleista ilman näitä tarkkoja lukuja.",
            "source_url": "https://example.com/story",
        }
        data = {**record, "article": article, "payload": {"packet_id": "pkt-rich-quality"}}
        path = self._write("outbox", "pkt-rich-quality", data)

        moved = staged_publish.quarantine_rejected_outbox([(path, data)], [article])

        self.assertEqual(moved, 1)
        failed = json.loads((self.root / "failed" / "pkt-rich-quality.json").read_text(encoding="utf-8"))
        feedback = failed["quality_gate_feedback"]
        self.assertEqual(feedback["packet_id"], "pkt-rich-quality")
        self.assertEqual(feedback["category"], "Talous")
        self.assertGreaterEqual(feedback["selected_source_words"], 360)
        self.assertEqual(feedback["selected_source_blocks"], 3)
        self.assertFalse(feedback["repair_eligible"])
        self.assertEqual(feedback["retry_classification"], "fail_closed_quality_gate")
        self.assertTrue(any("central unsourced number" in reason for reason in feedback["quality_reasons"]))
        self.assertIn("quality_gate_rejected", failed["failure"])

    def test_quality_gate_accepts_source_date_rephrased_as_finnish_ordinal(self) -> None:
        article = {
            "title": "Laura Welling nimitettiin Finanssiala ry:n johtajaksi",
            "description": "Laura Welling aloittaa tehtävässä syyskuussa 2026.",
            "content": (
                "Laura Welling aloittaa Finanssiala ry:n johtajana 1. syyskuuta 2026. "
                "Hän tulee tehtävään Taina Ahvenjärven tilalle ja liittyy samalla FA:n johtoryhmään.\n\n"
                "## Tausta\n\n"
                "Lähde kertoo aloituspäivän muodossa 1.9.2026, jonka toimituksellinen teksti "
                "voi kirjoittaa suomenkielisenä päivämääränä ilman, että päivä muuttuu uudeksi luvuksi. "
                "Tarkistus ei saa koventaa tällaista lähteistettyä päivämäärää keskiseksi luvuksi."
            ),
            "category": "Talous",
            "image": "https://example.com/img.jpg",
            "source_text": "Laura Welling aloittaa tehtävässään 1.9.2026 ja on osa FA:n johtoryhmää.",
            "source_url": "https://example.com/story",
        }

        breakdown = staged_publish.score_article(article)

        self.assertFalse(any("central unsourced number" in reason for reason in breakdown.hard_fails))
        self.assertFalse(any("unsourced_numbers: 1" in reason for reason in breakdown.soft_warnings))

    def test_enrich_images_uses_unsplash_for_missing_article_images(self) -> None:
        articles = [{"title": "Kuvaton artikkeli", "category": "Talous", "content": "sisältö"}]

        def fake_unsplash(batch, delay=0):
            batch[0]["image"] = "https://images.unsplash.com/photo-test"
            batch[0]["image_alt"] = "Kuvaton artikkeli"
            batch[0]["image_category_fallback"] = False
            return batch

        with patch.dict(staged_publish.os.environ, {"UNSPLASH_ACCESS_KEY": "key"}, clear=False), \
             patch.object(staged_publish, "should_skip", return_value=(False, None)), \
             patch.object(staged_publish, "unsplash_fetch_images", side_effect=fake_unsplash), \
             patch.object(staged_publish, "record_success") as success:
            summary = staged_publish.enrich_images_for_articles(articles, unsplash_delay=0, pexels_delay=0)

        self.assertEqual(summary["images"], 1)
        self.assertEqual(summary["unsplash"], 1)
        self.assertEqual(summary["missing"], 0)
        self.assertEqual(articles[0]["image"], "https://images.unsplash.com/photo-test")
        success.assert_called_with("unsplash")

    def test_enrich_images_clears_category_fallback_before_pexels_rescue(self) -> None:
        articles = [{"title": "Fallback artikkeli", "category": "Kotimaa", "image": "/images/categories/kotimaa.jpg", "image_category_fallback": True}]

        def fake_pexels(batch, delay=0):
            self.assertNotIn("image", batch[0])
            batch[0]["image"] = "/images/articles/fallback-hero.jpg"
            batch[0]["image_category_fallback"] = False
            return batch

        with patch.dict(staged_publish.os.environ, {"PEXELS_API_KEY": "key", "UNSPLASH_ACCESS_KEY": ""}, clear=False), \
             patch.object(staged_publish, "should_skip", return_value=(False, None)), \
             patch.object(staged_publish, "pexels_fetch_images", side_effect=fake_pexels):
            summary = staged_publish.enrich_images_for_articles(articles, unsplash_delay=0, pexels_delay=0)

        self.assertEqual(summary["images"], 1)
        self.assertEqual(summary["pexels"], 1)
        self.assertEqual(articles[0]["image"], "/images/articles/fallback-hero.jpg")
        self.assertFalse(articles[0]["image_category_fallback"])


    def test_enrich_images_loads_project_env_for_staged_publish(self) -> None:
        project_env = staged_publish.PROJECT_DIR / ".env"
        old_text = project_env.read_text(encoding="utf-8") if project_env.exists() else None
        old_pexels = staged_publish.os.environ.pop("PEXELS_API_KEY", None)
        old_unsplash = staged_publish.os.environ.pop("UNSPLASH_ACCESS_KEY", None)
        try:
            project_env.write_text("PEXELS_API_KEY=project-key\n", encoding="utf-8")
            articles = [{"title": "Env artikkeli", "category": "Kotimaa"}]

            def fake_pexels(batch, delay=0):
                batch[0]["image"] = "/images/articles/env-hero.jpg"
                batch[0]["image_category_fallback"] = False
                return batch

            with patch.object(staged_publish, "should_skip", return_value=(False, None)), \
                 patch.object(staged_publish, "pexels_fetch_images", side_effect=fake_pexels), \
                 patch.object(staged_publish, "unsplash_fetch_images", side_effect=lambda batch, delay=0: batch):
                summary = staged_publish.enrich_images_for_articles(articles, unsplash_delay=0, pexels_delay=0)

            self.assertEqual(summary["pexels"], 1)
            self.assertEqual(articles[0]["image"], "/images/articles/env-hero.jpg")
        finally:
            if old_text is None:
                project_env.unlink(missing_ok=True)
            else:
                project_env.write_text(old_text, encoding="utf-8")
            if old_pexels is not None:
                staged_publish.os.environ["PEXELS_API_KEY"] = old_pexels
            else:
                staged_publish.os.environ.pop("PEXELS_API_KEY", None)
            if old_unsplash is not None:
                staged_publish.os.environ["UNSPLASH_ACCESS_KEY"] = old_unsplash
            else:
                staged_publish.os.environ.pop("UNSPLASH_ACCESS_KEY", None)

    def test_publish_persists_enriched_image_metadata_to_published_queue(self) -> None:
        article = {"title": "Kuvallinen julkaisu", "content": "sana " * 260, "category": "Kotimaa", "image": "/images/articles/pub.jpg", "image_category_fallback": False, "monica_packet_id": "pkt-image"}
        data = {"article": article, "packet": {"packet_id": "pkt-image"}}
        path = self._write("outbox", "pkt-image", data, age_hours=1)

        with patch.object(staged_publish, "load_outbox", return_value=[(path, data)]), \
             patch.object(staged_publish, "run_quality_gate", return_value=type("Gate", (), {"passed": [article], "rejected": []})()), \
             patch.object(staged_publish, "check_published_duplicates", side_effect=lambda articles, window_hours=48: articles), \
             patch.object(staged_publish, "dedup_within_batch", side_effect=lambda articles: articles), \
             patch.object(staged_publish, "enrich_images_for_articles", return_value={"total": 1, "images": 1, "unsplash": 0, "pexels": 1, "missing": 0}), \
             patch.object(staged_publish, "publish_articles", return_value=["content/posts/test.md"]), \
             patch.object(staged_publish, "mark_published"), \
             patch.object(staged_publish, "build_site", return_value=(True, "")), \
             patch.object(staged_publish, "atomic_write_json", side_effect=lambda target, payload: target.write_text(json.dumps(payload), encoding="utf-8")):
            rc = staged_publish.cmd_publish(type("Args", (), {"max_articles": 1, "dedup_window": 48, "dry_run": False, "git_push": False})())

        self.assertEqual(rc, 0)
        published = json.loads((self.root / "published" / "pkt-image.json").read_text(encoding="utf-8"))
        self.assertEqual(published["article"]["image"], "/images/articles/pub.jpg")
        self.assertEqual(published["image_enrichment"]["image"], "/images/articles/pub.jpg")

    def test_quality_gate_feedback_marks_source_backed_length_only_as_repairable(self) -> None:
        record = _record("length-only", source_words=360, blocks=3)
        record["packet"]["packet_id"] = "pkt-length-only"
        article = {
            "title": "Hallitus valmistelee säästöjä",
            "description": "Hallitus valmistelee säästöjä sosiaalihuoltoon ensi vuodelle.",
            "content": "Hallitus valmistelee säästöjä ensi vuodelle. Valmistelu jatkuu ministeriöissä.\n\n## Tausta\n\nPäätöksiä arvioidaan myöhemmin.",
            "category": "Kotimaa",
            "image": "https://example.com/img.jpg",
            "source_text": " ".join(["Hallitus valmistelee säästöjä sosiaalihuoltoon ensi vuodelle."] * 70),
            "source_url": "https://example.com/story",
        }

        feedback = staged_publish.quality_gate_retry_classification(record, article)

        self.assertTrue(feedback["source_backed"])
        self.assertTrue(feedback["repair_eligible"])
        self.assertEqual(feedback["retry_classification"], "repairable_length_only")

    def test_priority_prefers_promising_packet_over_old_thin_fifo(self) -> None:
        thin_old = self._write("ready", "thin-old", _record("thin-old", source_words=45, blocks=1), age_hours=30)
        rich_newer = self._write("ready", "rich-newer", _record("rich-newer", source_words=420, blocks=3), age_hours=10)

        ordered = staged_publish.prioritized_ready_packets()

        self.assertEqual(ordered[0], rich_newer)
        self.assertIn(thin_old, ordered)

    def test_priority_applies_talous_mix_bonus_without_beating_much_stronger_packet(self) -> None:
        talous = _record("talous", source_words=260, blocks=2)
        talous["packet"]["category_hint"] = "Talous"
        talous_path = self._write("ready", "talous", talous, age_hours=1)
        kotimaa_path = self._write("ready", "kotimaa", _record("kotimaa", source_words=260, blocks=2), age_hours=1)
        rich_path = self._write("ready", "rich", _record("rich", source_words=700, blocks=4), age_hours=1)

        self.assertGreater(staged_publish.priority_score(talous_path)[0], staged_publish.priority_score(kotimaa_path)[0])
        self.assertEqual(staged_publish.ready_sample(talous_path)["category_priority_bonus"], 4.0)
        self.assertEqual(staged_publish.prioritized_ready_packets()[0], rich_path)

    def test_priority_uses_original_talous_hint_when_saved_packet_still_says_ulkomaat(self) -> None:
        stale_saved = _record("stale-saved", source_words=260, blocks=2)
        stale_saved["packet"]["category_hint"] = "Ulkomaat"
        stale_saved["packet"]["category"] = "Ulkomaat"
        stale_saved["original_article"]["category_hint"] = "Talous"
        stale_saved["original_article"]["_guessed_category"] = "Talous"
        stale_path = self._write("ready", "stale-saved", stale_saved, age_hours=1)
        kotimaa_path = self._write("ready", "kotimaa", _record("kotimaa", source_words=260, blocks=2), age_hours=1)

        self.assertGreater(staged_publish.priority_score(stale_path)[0], staged_publish.priority_score(kotimaa_path)[0])
        self.assertEqual(staged_publish.ready_sample(stale_path)["category"], "Talous")
        self.assertEqual(staged_publish.ready_sample(stale_path)["category_priority_bonus"], 4.0)



    def test_talous_rss_source_backed_counts_as_enriched_and_passes_priority_floor(self) -> None:
        article = {
            "title": "Pörssi laski inflaatiolukujen jälkeen",
            "category_hint": "Talous",
            "source": "Taloussanomat",
            "research_source": "rss_talous_source_backed",
            "research": "[Lähde: Taloussanomat]\n" + " ".join(["sana"] * 125),
            "description": "Lyhyt kuvaus",
        }

        self.assertEqual(staged_publish.article_research_bucket(article), "research_enriched")
        self.assertTrue(staged_publish.passes_priority_source_floor(article))
        self.assertGreater(staged_publish.category_enqueue_bonus(article), 0)


    def test_research_candidate_cap_keeps_talous_after_cooldown(self) -> None:
        kotimaa = {"title": "kotimaa uutinen", "category_hint": "Kotimaa", "description": "kuvaus " * 6}
        ulkomaat = {"title": "ulkomaat uutinen", "category_hint": "Ulkomaat", "description": "kuvaus " * 5}
        talous = {"title": "talous uutinen", "category_hint": "Talous", "description": "kuvaus " * 4}

        selected = staged_publish.select_research_candidates([kotimaa, ulkomaat, talous], max_candidates=2)

        self.assertEqual(len(selected), 2)
        self.assertIn("Talous", {staged_publish.article_category(article) for article in selected})
        self.assertNotIn(ulkomaat, selected)

    def test_talous_failed_staged_digest_can_reenter_scan_cooldown(self) -> None:
        failed = _record("talous-failed", source_words=0, blocks=0)
        failed["packet"]["category_hint"] = "Talous"
        failed["original_article"]["category_hint"] = "Talous"
        self._write("failed", "talous-failed", failed, age_hours=1)

        article = {"title": "Talous failed", "url": "https://example.com/talous", "category_hint": "Talous"}
        with patch.object(staged_publish, "stable_digest", return_value="abc123def0"):
            self.assertFalse(staged_publish.should_skip_staged_cooldown(article, hours=24))

    def test_talous_duplicate_failed_digest_obeys_terminal_cooldown(self) -> None:
        article = {"title": "Talous duplicate", "url": "https://example.com/talous-duplicate", "category_hint": "Talous"}
        digest = staged_publish.stable_digest(article)
        failed = _record("talous-duplicate", source_words=360, blocks=3)
        failed["digest"] = digest
        failed["packet"]["category_hint"] = "Talous"
        failed["original_article"]["category_hint"] = "Talous"
        failed["duplicate_rejected"] = True
        self._write("failed", "talous-duplicate", failed, age_hours=1)

        with patch.object(staged_publish, "stable_digest", return_value=digest):
            self.assertTrue(staged_publish.should_skip_staged_cooldown(article, hours=24))

    def test_talous_fail_closed_quality_gate_obeys_terminal_cooldown(self) -> None:
        failed = _record("talous-quality", source_words=360, blocks=3)
        failed["digest"] = "abc123def3"
        failed["packet"]["category_hint"] = "Talous"
        failed["original_article"]["category_hint"] = "Talous"
        failed["quality_gate_feedback"] = {"retry_classification": "fail_closed_quality_gate"}
        self._write("failed", "talous-quality", failed, age_hours=1)

        article = {"title": "Talous quality", "url": "https://example.com/talous-quality", "category_hint": "Talous"}
        with patch.object(staged_publish, "stable_digest", return_value="abc123def3"):
            self.assertTrue(staged_publish.should_skip_staged_cooldown(article, hours=24))

    def test_talous_newer_ready_digest_obeys_cooldown(self) -> None:
        ready = _record("talous-ready", source_words=360, blocks=3)
        ready["digest"] = "abc123def4"
        ready["packet"]["category_hint"] = "Talous"
        ready["original_article"]["category_hint"] = "Talous"
        failed = _record("talous-terminal", source_words=360, blocks=3)
        failed["digest"] = "abc123def4"
        failed["packet"]["category_hint"] = "Talous"
        failed["original_article"]["category_hint"] = "Talous"
        failed["duplicate_rejected"] = True
        self._write("ready", "talous-ready", ready, age_hours=0.5)
        self._write("failed", "talous-terminal", failed, age_hours=1)

        article = {"title": "Talous ready", "url": "https://example.com/talous-ready", "category_hint": "Talous"}
        with patch.object(staged_publish, "stable_digest", return_value="abc123def4"):
            self.assertTrue(staged_publish.should_skip_staged_cooldown(article, hours=24))

    def test_non_talous_failed_staged_digest_still_obeys_cooldown(self) -> None:
        failed = _record("kotimaa-failed", source_words=0, blocks=0)
        failed["digest"] = "abc123def1"
        failed["packet"]["category_hint"] = "Kotimaa"
        failed["original_article"]["category_hint"] = "Kotimaa"
        self._write("failed", "kotimaa-failed", failed, age_hours=1)

        article = {"title": "Kotimaa failed", "url": "https://example.com/kotimaa", "category_hint": "Kotimaa"}
        with patch.object(staged_publish, "stable_digest", return_value="abc123def1"):
            self.assertTrue(staged_publish.should_skip_staged_cooldown(article, hours=24))

    def test_scan_enqueue_keeps_under_target_talous_when_source_strength_ties(self) -> None:
        kotimaa = {"title": "kotimaa", "category_hint": "Kotimaa", "research": "[Lähde: Testi]\n" + "sana " * 220, "description": "kuvaus"}
        talous = {"title": "talous", "category_hint": "Talous", "research": "[Lähde: A]\n" + "sana " * 110 + "\n\n[Lähde: B]\n" + "sana " * 110, "description": "kuvaus"}

        selected = staged_publish.select_scan_enqueue_candidates([kotimaa, talous], max_packets=1)

        self.assertEqual(len(selected), 1)
        self.assertEqual(staged_publish.article_category(selected[0]), "Talous")


    def test_scan_enqueue_does_not_promote_thin_talous_fallback(self) -> None:
        thin_kotimaa = {"title": "kotimaa", "category_hint": "Kotimaa", "research": "sana " * 90, "description": "kuvaus"}
        fallback_talous = {"title": "talous", "category_hint": "Talous", "research": "sana " * 120, "description": "kuvaus"}

        selected = staged_publish.select_scan_enqueue_candidates([thin_kotimaa, fallback_talous], max_packets=1)

        self.assertEqual(len(selected), 1)
        self.assertEqual(staged_publish.article_category(selected[0]), "Kotimaa")

    def test_scan_enqueue_promotes_talous_after_source_floor_over_thin_backlog(self) -> None:
        thin_kotimaa = {"title": "kotimaa", "category_hint": "Kotimaa", "research": "sana " * 90, "description": "kuvaus"}
        sourced_talous = {"title": "talous", "category_hint": "Talous", "research": "[Lähde: A]\n" + "sana " * 95 + "\n\n[Lähde: B]\n" + "sana " * 95, "description": "kuvaus"}

        selected = staged_publish.select_scan_enqueue_candidates([thin_kotimaa, sourced_talous], max_packets=1)

        self.assertEqual(len(selected), 1)
        self.assertEqual(staged_publish.article_category(selected[0]), "Talous")


    def test_scan_enqueue_keeps_source_qualified_talous_when_cap_drops_it(self) -> None:
        rich_kotimaa = {"title": "kotimaa", "category_hint": "Kotimaa", "research": "sana " * 260, "description": "kuvaus"}
        moderate_ulkomaat = {"title": "ulkomaat", "category_hint": "Ulkomaat", "research": "sana " * 170, "description": "kuvaus"}
        sourced_talous = {"title": "talous", "category_hint": "Talous", "research": "[Lähde: A]\n" + "sana " * 95 + "\n\n[Lähde: B]\n" + "sana " * 95, "description": "kuvaus"}

        selected = staged_publish.select_scan_enqueue_candidates([rich_kotimaa, moderate_ulkomaat, sourced_talous], max_packets=2)

        self.assertEqual(len(selected), 2)
        self.assertIn("Talous", {staged_publish.article_category(article) for article in selected})
        self.assertNotIn(moderate_ulkomaat, selected)


    def test_scan_enqueue_reserves_source_backed_talous_when_cap_would_drop_it(self) -> None:
        teknologia = {"title": "teknologia", "category_hint": "Teknologia", "research": "[Lähde: Testi]\n" + "sana " * 310, "description": "kuvaus"}
        uutiset = {"title": "uutiset", "category_hint": "Uutiset", "research": "[Lähde: Testi]\n" + "sana " * 260, "description": "kuvaus"}
        talous = {"title": "talous", "category_hint": "Talous", "research": "[Lähde: A]\n" + "sana " * 95 + "\n\n[Lähde: B]\n" + "sana " * 95, "description": "kuvaus", "story_confidence": 0.90}

        selected = staged_publish.select_scan_enqueue_candidates([teknologia, uutiset, talous], max_packets=1)

        self.assertEqual(len(selected), 1)
        self.assertEqual(staged_publish.article_category(selected[0]), "Talous")

    def test_scan_enqueue_reserve_rejects_weak_one_block_talous_packet(self) -> None:
        teknologia = {"title": "teknologia", "category_hint": "Teknologia", "research": "[Lähde: Testi]\n" + "sana " * 220, "description": "kuvaus"}
        tokmanni = {
            "title": "Tokmanni aloittaa omien osakkeiden hankinnan",
            "category_hint": "Talous",
            "source": "Arvopaperi",
            "research": "[Lähde: Arvopaperi]\n" + "sana " * 102,
            "description": "Tokmanni aloittaa omien osakkeiden hankinnan.",
            "story_confidence": 0.62,
            "research_source": "multi",
        }

        self.assertFalse(staged_publish.passes_priority_source_floor(tokmanni))
        self.assertFalse(staged_publish.scan_candidate_passes_talous_reserve(tokmanni))
        selected = staged_publish.select_scan_enqueue_candidates([teknologia, tokmanni], max_packets=1)

        self.assertEqual(staged_publish.article_category(selected[0]), "Teknologia")


    def test_scan_enqueue_reserve_preserves_promotional_talous_rejection(self) -> None:
        teknologia = {"title": "teknologia", "category_hint": "Teknologia", "research": "[Lähde: Testi]\n" + "sana " * 260, "description": "kuvaus"}
        promo = {
            "title": "Finanssiala uudisti verkkosivunsa",
            "category_hint": "Talous",
            "source": "Finanssiala",
            "description": "Tavoitteemme-osio kertoo sivuston uudesta ulkoasusta.",
            "research": "[Lähde: Finanssiala]\n" + "sana " * 300 + " uudisti verkkosivunsa tavoitteemme-osio",
            "story_confidence": 0.98,
        }

        self.assertFalse(staged_publish.scan_candidate_passes_talous_reserve(promo))
        selected = staged_publish.select_scan_enqueue_candidates([teknologia, promo], max_packets=1)

        self.assertEqual(staged_publish.article_category(selected[0]), "Teknologia")


    def test_scan_enqueue_uses_total_source_floor_for_talous_candidate(self) -> None:
        rich_kotimaa = {"title": "kotimaa", "category_hint": "Kotimaa", "research": "sana " * 410, "description": "kuvaus"}
        moderate_ulkomaat = {"title": "ulkomaat", "category_hint": "Ulkomaat", "research": "sana " * 204, "description": "kuvaus " * 16}
        sourced_talous = {"title": "talous", "category_hint": "Talous", "research": "[Lähde: A]\n" + "sana " * 100 + "\n\n[Lähde: B]\n" + "sana " * 100, "description": "kuvaus " * 16}
        rich_urheilu = {"title": "urheilu", "category_hint": "Urheilu", "research": "sana " * 608, "description": "kuvaus"}

        selected = staged_publish.select_scan_enqueue_candidates([rich_urheilu, rich_kotimaa, moderate_ulkomaat, sourced_talous], max_packets=3)

        self.assertIn("Talous", {staged_publish.article_category(article) for article in selected})
        self.assertNotIn(moderate_ulkomaat, selected)

    def test_scan_enqueue_does_not_let_talous_beat_much_stronger_source(self) -> None:
        rich_kotimaa = {"title": "kotimaa", "category_hint": "Kotimaa", "research": "sana " * 700, "description": "kuvaus"}
        thin_talous = {"title": "talous", "category_hint": "Talous", "research": "sana " * 120, "description": "kuvaus"}

        selected = staged_publish.select_scan_enqueue_candidates([rich_kotimaa, thin_talous], max_packets=1)

        self.assertEqual(len(selected), 1)
        self.assertEqual(staged_publish.article_category(selected[0]), "Kotimaa")

    def test_org_source_talous_guardrail_downranks_self_promotional_org_news(self) -> None:
        article = {
            "title": "Finanssiala uudisti verkkosivunsa ja nosti edunvalvontatavoitteet näkyviin",
            "description": "Järjestön Tavoitteemme-osio kertoo sivuston uudesta ulkoasusta.",
            "source": "Finanssiala",
            "category_hint": "Talous",
            "research": "[Lähde: Finanssiala]\n" + "sana " * 360,
        }

        guardrail = staged_publish.org_source_talous_guardrail(article)

        self.assertEqual(guardrail["classification"], "down_rank_promotional_org_source")
        self.assertGreater(staged_publish.org_source_talous_penalty(article), staged_publish.category_enqueue_bonus(article))

    def test_org_source_talous_guardrail_keeps_attributed_policy_claim(self) -> None:
        article = {
            "title": "Finanssiala varoittaa osakesäästötilin rahastolaajennuksesta",
            "description": "Finanssialan mukaan muutos voisi heikentää järjestelmän selkeyttä.",
            "source": "Finanssiala",
            "category_hint": "Talous",
            "research": "[Lähde: Finanssiala]\n" + "sana " * 360,
        }

        guardrail = staged_publish.org_source_talous_guardrail(article)

        self.assertEqual(guardrail["classification"], "ok_attributed_policy_claim")
        self.assertEqual(staged_publish.org_source_talous_penalty(article), 0)

    def test_org_source_talous_guardrail_allows_concrete_yrittajat_profile(self) -> None:
        article = {
            "title": "Yrittäjä Agim Sopjan löytää shakkilaudalta vastapainoa rakennusalan arkeen",
            "description": "Yritysprofiili kertoo yrittäjän arjesta ja harrastuksesta ilman jäsen-CTA:ta.",
            "source": "Suomen Yrittäjät",
            "category_hint": "Talous",
            "research": "[Lähde: Suomen Yrittäjät]\n" + "sana " * 360,
        }

        guardrail = staged_publish.org_source_talous_guardrail(article)

        self.assertEqual(guardrail["classification"], "ok_company_profile")
        self.assertEqual(staged_publish.org_source_talous_penalty(article), 0)

    def test_scan_enqueue_downranks_promotional_org_source_talous_below_comparable_packet(self) -> None:
        promotional = {
            "title": "Finanssiala uudisti verkkosivunsa ja nosti edunvalvontatavoitteet näkyviin",
            "description": "Tavoitteemme-osio ja sivuston ulkoasu esitellään järjestön omassa uutisessa.",
            "source": "Finanssiala",
            "category_hint": "Talous",
            "research": "[Lähde: Finanssiala]\n" + "sana " * 360,
        }
        neutral = {"title": "kotimaa", "category_hint": "Kotimaa", "research": "sana " * 260, "description": "kuvaus"}

        selected = staged_publish.select_scan_enqueue_candidates([promotional, neutral], max_packets=1)

        self.assertEqual(selected, [neutral])

    def test_talous_worker_bonus_requires_source_floor(self) -> None:
        kotimaa_record = _record("kotimaa", source_words=320, blocks=1)
        talous_record = _record("talous", source_words=320, blocks=1)
        talous_record["packet"]["category_hint"] = "Talous"
        talous_record["original_article"]["category_hint"] = "Talous"
        thin_talous_record = _record("thin-talous", source_words=120, blocks=1)
        thin_talous_record["packet"]["category_hint"] = "Talous"
        thin_talous_record["original_article"]["category_hint"] = "Talous"

        kotimaa = self._write("ready", "kotimaa", kotimaa_record, age_hours=1)
        talous = self._write("ready", "talous", talous_record, age_hours=1)
        thin_talous = self._write("ready", "thin-talous", thin_talous_record, age_hours=1)

        self.assertGreater(staged_publish.priority_score(talous)[0], staged_publish.priority_score(kotimaa)[0])
        self.assertLess(staged_publish.priority_score(thin_talous)[0], staged_publish.priority_score(talous)[0])
        self.assertEqual(staged_publish.ready_sample(talous)["category_worker_priority_bonus"], 3.0)
        self.assertEqual(staged_publish.ready_sample(thin_talous)["category_worker_priority_bonus"], 0.0)

    def test_ready_sample_is_dry_run_metadata_only(self) -> None:
        path = self._write("ready", "sample", _record("sample", source_words=250, blocks=2), age_hours=5)

        sample = staged_publish.ready_sample(path)

        self.assertEqual(sample["file"], "sample.json")
        self.assertEqual(sample["packet_id"], "sample")
        self.assertGreater(sample["priority_score"], 0)
        self.assertTrue(path.exists())

    def test_status_source_metrics_match_monica_selected_packet_metrics(self) -> None:
        record = _record("selected-metrics", source_words=120, blocks=2)
        record["packet"]["source_text"] = " ".join(["sana"] * 600)
        record["packet"]["clean_source_blocks"] = [
            {"source": "Testi 0", "text": " ".join(["sana"] * 60), "word_count": 60},
            {"source": "Testi 1", "text": " ".join(["sana"] * 60), "word_count": 60},
        ]
        path = self._write("ready", "selected-metrics", record, age_hours=1)

        data = staged_publish.read_queue_record(path)

        self.assertEqual(staged_publish.packet_source_words(data), 120)
        self.assertEqual(staged_publish.packet_source_blocks(data), 2)
        sample = staged_publish.ready_sample(path)
        self.assertEqual(sample["source_words"], 120)
        self.assertEqual(sample["source_blocks"], 2)


    @patch.object(staged_publish, "_run_monica")
    def test_monica_worker_records_near_short_repair_markers_in_outbox(self, run_mock) -> None:
        record = _record("worker-near-short", source_words=240, blocks=2)
        record["packet"]["packet_id"] = "pkt-worker-near-short"
        record["packet"]["story_confidence"] = 0.9
        record["packet"]["clean_source_blocks"] = [
            {"source": "Testi 1", "text": " ".join(["sana"] * 120), "word_count": 120},
            {"source": "Testi 2", "text": " ".join(["sana"] * 120), "word_count": 120},
        ]
        path = self._write("ready", "worker-near-short", record, age_hours=1)
        near_payload = {
            "packet_id": "pkt-worker-near-short",
            "title": "Lähes valmis artikkeli",
            "summary": "Lähes valmis yhteenveto.",
            "content": "Aloituskappale sisältää riittävästi sanoja ja kuvaa asian taustan, vaikutukset sekä jatkon lukijalle selkeästi, ja mukana on vielä lisää varmistavia sanoja lukijalle nyt, jotta pituusraja täyttyy varmasti tässä testissä nyt selvästi.\n\n## Tausta\n\n" + " ".join(["sana"] * 215),
            "category": "Talous",
            "tags": ["talous", "testi", "korjaus"],
            "summary_bullets": ["Yksi asia", "Toinen asia", "Kolmas asia"],
            "content_type": "article",
            "editorial_reviewed": True,
            "confidence": 0.9,
            "journalist_note": " ",
        }
        repaired_payload = {**near_payload, "content": "Aloituskappale sisältää riittävästi sanoja ja kuvaa asian taustan, vaikutukset sekä jatkon lukijalle selkeästi, ja mukana on vielä lisää varmistavia sanoja lukijalle nyt, jotta pituusraja täyttyy varmasti tässä testissä nyt selvästi.\n\n## Tausta\n\n" + " ".join(["sana"] * 266)}
        run_mock.side_effect = [json.dumps(near_payload), json.dumps(near_payload), json.dumps(repaired_payload)]

        status, _ = staged_publish.process_one_packet(path, type("Args", (), {})())

        self.assertEqual(status, "ok")
        outbox = json.loads((self.root / "outbox" / "worker-near-short.json").read_text(encoding="utf-8"))
        repair = outbox["repair"]
        self.assertEqual(repair["repair_attempt"], "source_backed_near_short")
        self.assertEqual(repair["pre_repair_word_count"], 247)
        self.assertGreaterEqual(repair["post_repair_word_count"], 250)
        self.assertEqual(repair["repair_result"], "published")
        self.assertTrue(repair["source_block_ids_used_for_repair"])
        self.assertEqual(outbox["article"]["monica_repair"]["repair_attempt"], "source_backed_near_short")

    def test_failed_status_extracts_nested_failure_reason_and_cleanup_bucket(self) -> None:
        self._write("failed", "expired", {**_record("expired", 100), "failure": {"reason": "stale_ready_expired age_h=10.1 max_age_h=10.0"}}, age_hours=12)

        failed_status = staged_publish.queue_box_status("failed", list((self.root / "failed").glob("*.json")), datetime.now(timezone.utc))

        self.assertEqual(failed_status["failure_reason_buckets"]["stale_ready_expired"], 1)
        self.assertEqual(failed_status["failure_alert_buckets"]["expected_cleanup"], 1)

    def test_cleanup_failed_queue_dry_run_matches_old_stale_ready_only(self) -> None:
        self._write("failed", "old-expired", {**_record("old-expired", 100), "failure": "stale_ready_expired age_h=40.0 max_age_h=10.0"}, age_hours=200)
        self._write("failed", "new-expired", {**_record("new-expired", 100), "failure": "stale_ready_expired age_h=10.0 max_age_h=10.0"}, age_hours=2)
        self._write("failed", "runtime", {**_record("runtime", 100), "failure": "timed out"}, age_hours=200)

        summary = staged_publish.cleanup_failed_queue(max_age_hours=168, dry_run=True)

        self.assertEqual(summary["matched"], 1)
        self.assertTrue((self.root / "failed" / "old-expired.json").exists())
        self.assertTrue((self.root / "failed" / "runtime.json").exists())

    def test_cleanup_failed_queue_deletes_old_stale_ready_only(self) -> None:
        self._write("failed", "old-expired", {**_record("old-expired", 100), "failure": "stale_ready_expired age_h=40.0 max_age_h=10.0"}, age_hours=200)
        self._write("failed", "runtime", {**_record("runtime", 100), "failure": "timed out"}, age_hours=200)

        summary = staged_publish.cleanup_failed_queue(max_age_hours=168, dry_run=False)

        self.assertEqual(summary["deleted"], 1)
        self.assertFalse((self.root / "failed" / "old-expired.json").exists())
        self.assertTrue((self.root / "failed" / "runtime.json").exists())


class StagedPublishBacklogAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for box in ["ready", "writing", "outbox", "published", "failed"]:
            (self.root / box).mkdir(parents=True, exist_ok=True)
        self.patch = patch.object(staged_publish, "STAGED_ROOT", self.root)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def _write(self, box: str, name: str, data: dict, age_hours: float = 0) -> Path:
        path = self.root / box / f"{name}.json"
        created = datetime.now(timezone.utc) - timedelta(hours=age_hours)
        data = {**data, "created_at": created.isoformat()}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        import os
        os.utime(path, (created.timestamp(), created.timestamp()))
        return path

    def test_audit_ready_dry_run_identifies_stale_low_confidence_without_moving(self) -> None:
        self._write("ready", "stale-thin", _record("stale-thin", source_words=55, blocks=1), age_hours=60)
        self._write("ready", "fresh-rich", _record("fresh-rich", source_words=420, blocks=2), age_hours=4)

        summary = staged_publish.audit_ready_backlog(dry_run=True, demote_after_hours=48, expire_after_hours=96)

        self.assertEqual(summary["scanned"], 2)
        self.assertEqual(summary["demoted"], 1)
        self.assertEqual(summary["expired"], 0)
        self.assertTrue((self.root / "ready" / "stale-thin.json").exists())
        self.assertFalse((self.root / "failed" / "stale-thin.json").exists())

    def test_audit_ready_moves_expired_packet_to_failed_with_reason(self) -> None:
        self._write("ready", "expired-thin", _record("expired-thin", source_words=55, blocks=1), age_hours=120)

        summary = staged_publish.audit_ready_backlog(dry_run=False, demote_after_hours=48, expire_after_hours=96)

        self.assertEqual(summary["expired"], 1)
        self.assertFalse((self.root / "ready" / "expired-thin.json").exists())
        failed = json.loads((self.root / "failed" / "expired-thin.json").read_text(encoding="utf-8"))
        self.assertEqual(failed["backlog_audit_action"], "expire")
        self.assertIn("stale_low_confidence_expired", failed["failure"])

    def test_status_reports_ready_audit_candidates(self) -> None:
        self._write("ready", "stale-thin", _record("stale-thin", source_words=55, blocks=1), age_hours=60)
        self._write("ready", "fresh-rich", _record("fresh-rich", source_words=420, blocks=2), age_hours=4)

        status = staged_publish.queue_box_status("ready", list((self.root / "ready").glob("*.json")), datetime.now(timezone.utc))

        self.assertEqual(status["audit"]["stale_low_confidence"], 1)
        self.assertEqual(status["audit"]["demote_candidates_48h"], 1)
        self.assertEqual(status["audit"]["expire_candidates_96h"], 0)


class StagedPublishFailedHygieneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for box in ["ready", "writing", "outbox", "published", "failed"]:
            (self.root / box).mkdir(parents=True, exist_ok=True)
        self.patch = patch.object(staged_publish, "STAGED_ROOT", self.root)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def _write_failed(self, name: str, failure: str, age_hours: float) -> Path:
        path = self.root / "failed" / f"{name}.json"
        created = datetime.now(timezone.utc) - timedelta(hours=age_hours)
        data = {**_record(name, 100), "failed_at": created.isoformat(), "failure": failure}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        import os
        os.utime(path, (created.timestamp(), created.timestamp()))
        return path

    def test_failed_alert_summary_separates_intentional_cleanup_from_runtime(self) -> None:
        summary = staged_publish.failed_runtime_alert_summary({
            "stale_ready_expired": 10,
            "content_too_short": 2,
            "writer_runtime": 1,
        })

        self.assertEqual(summary["intentional_cleanup_total"], 10)
        self.assertEqual(summary["runtime_failure_total"], 3)
        self.assertEqual(summary["runtime_failure_buckets"], {"content_too_short": 2, "writer_runtime": 1})

    def test_prune_failed_dry_run_keeps_recent_bucket_and_reports_old_excess(self) -> None:
        self._write_failed("old-a", "stale_ready_expired age_h=240 max_age_h=10", age_hours=240)
        self._write_failed("old-b", "stale_ready_expired age_h=230 max_age_h=10", age_hours=230)
        self._write_failed("runtime", "timed out", age_hours=240)

        summary = staged_publish.prune_failed_backlog(dry_run=True, keep_days=7, keep_recent=1)

        self.assertEqual(summary["pruned"], 1)
        self.assertEqual(summary["kept"], 2)
        self.assertTrue((self.root / "failed" / "old-a.json").exists())
        self.assertTrue((self.root / "failed" / "old-b.json").exists())
        self.assertTrue((self.root / "failed" / "runtime.json").exists())

    def test_prune_failed_non_dry_removes_only_old_excess_bucket(self) -> None:
        self._write_failed("old-a", "stale_ready_expired age_h=240 max_age_h=10", age_hours=240)
        self._write_failed("old-b", "stale_ready_expired age_h=230 max_age_h=10", age_hours=230)
        self._write_failed("runtime", "timed out", age_hours=240)

        summary = staged_publish.prune_failed_backlog(dry_run=False, keep_days=7, keep_recent=1)

        self.assertEqual(summary["pruned"], 1)
        self.assertEqual(len(list((self.root / "failed").glob("*.json"))), 2)
        self.assertTrue((self.root / "failed" / "runtime.json").exists())


if __name__ == "__main__":
    unittest.main()


class RssSourcePolicyTests(unittest.TestCase):
    def test_scanner_policy_skips_dead_and_unreachable_feeds(self) -> None:
        from pipeline import scanner
        policy = {"AP News": {"policy": "disable_or_replace", "reason": "http_403_or_known_block"}}
        allowed, reason = scanner._scanner_policy_allows_feed({"name": "AP News"}, policy)
        self.assertFalse(allowed)
        self.assertEqual(reason, "http_403_or_known_block")

    def test_scanner_policy_marks_stale_articles_not_fresh_quota_eligible(self) -> None:
        from pipeline import scanner
        article = {"source": "Yle Tiede"}
        scanner._apply_source_policy_metadata(article, {"Yle Tiede": {"policy": "stale_source", "fresh_quota_eligible": False}})
        self.assertEqual(article["source_policy"], "stale_source")
        self.assertFalse(article["fresh_source_quota_eligible"])
        self.assertTrue(article["stale_source"])
