#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from .monica_writer import OPENCLAW_CANDIDATES, _build_repair_prompt, _extract_json_object, _is_source_backed_near_miss, _is_source_backed_repair_candidate, _merge_article, _near_miss_repair_metadata, _packet_source_blocks, _packet_source_words, _packet_story_confidence, rewrite_articles
    PATCH_TARGET = "pipeline.monica_writer.subprocess.run"
    RESOLVE_PATCH_TARGET = "pipeline.monica_writer._resolve_openclaw_base_cmd"
except ImportError:  # pragma: no cover - direct execution from pipeline cwd
    from monica_writer import OPENCLAW_CANDIDATES, _build_repair_prompt, _extract_json_object, _is_source_backed_near_miss, _is_source_backed_repair_candidate, _merge_article, _near_miss_repair_metadata, _packet_source_blocks, _packet_source_words, _packet_story_confidence, rewrite_articles
    PATCH_TARGET = "monica_writer.subprocess.run"
    RESOLVE_PATCH_TARGET = "monica_writer._resolve_openclaw_base_cmd"


SAMPLE_ARTICLE = {
    "title": "Hallitus valmistelee uusia säästöjä",
    "description": "Hallitus valmistelee uusia sosiaalihuollon säästöjä ja esittää niiden tulevan voimaan ensi vuonna.",
    "link": "https://example.com/story",
    "category_hint": "Kotimaa",
    "research": "[Lähde: Yle]\nHallitus valmistelee uusia sosiaalihuollon säästöjä. Päätöksiä valmistellaan ensi vuodelle ja vaikutukset kohdistuvat useisiin palveluihin.\n\n---\n\n[Lähde: BBC]\nThe government is preparing new savings measures for social care. Ministers say the final package is still under preparation.",
}


def _source_packet(source_words: int, blocks: int = 2) -> dict:
    block_text = " ".join(["sana"] * max(1, source_words // max(1, blocks)))
    return {
        "packet_id": "talous-test",
        "category_hint": "Talous",
        "source_text": "\n\n".join(f"[Lähde: Testi {idx}]\n{block_text}" for idx in range(blocks)),
        "clean_source_blocks": [
            {"source": f"Testi {idx}", "text": block_text, "word_count": len(block_text.split())}
            for idx in range(blocks)
        ],
    }


def _long_content() -> str:
    para1 = (
        "Hallitus valmistelee uusia säästöjä sosiaalihuoltoon ensi vuodelle. "
        "Tavoitteena on pienentää menoja useissa palveluissa samalla, kun valmistelu jatkuu ministeriöissä ja vaikutuksia arvioidaan. "
        "Kyse on laajasta kokonaisuudesta, joka vaikuttaa kuntiin, hyvinvointialueisiin ja palveluiden järjestämiseen eri puolilla maata. "
        "Valmistelu on herättänyt keskustelua siitä, miten säästöt voidaan toteuttaa ilman että heikoimmassa asemassa olevien palvelut heikkenevät liikaa."
    )
    para2 = (
        "## Mitä päätöksestä tiedetään\n"
        "Valmistelu on kesken, mutta hallitus kertoo päätösten kohdistuvan useisiin sosiaalihuollon palveluihin. "
        "Arviot tarkentuvat budjettiriihen yhteydessä, ja ministeriöt käyvät läpi vaihtoehtoja, joilla menoja voidaan hillitä ilman että peruspalvelut vaarantuvat. "
        "Samalla selvitetään, millaisia vaikutuksia ratkaisuilla olisi alueiden talouteen ja henkilöstön arkeen. "
        "Virkamiehet käyvät läpi myös sitä, miten säästöjen vaikutuksia voidaan mitata ja millaisia siirtymäaikoja mahdollisiin muutoksiin tarvitaan."
    )
    para3 = (
        "## Mitä seuraavaksi tapahtuu\n"
        "Seuraavaksi esitykset viimeistellään ministeriöissä, niiden vaikutuksia arvioidaan tarkemmin ja poliittiset neuvottelut jatkuvat. "
        "Lopulliset päätökset tehdään myöhemmin, mutta jo nyt on selvää, että säästölinja vaikuttaa useiden palveluiden rahoitukseen. "
        "Julkinen keskustelu jatkuu ennen kuin ratkaisut vahvistetaan ja niiden täsmällinen sisältö julkaistaan. "
        "Hyvinvointialueet seuraavat valmistelua tarkasti, koska muutoksilla voi olla vaikutuksia sekä budjetteihin että palveluverkkoon."
    )
    para4 = (
        "## Mitä tämä merkitsee alueille\n"
        "Jos säästöt toteutuvat suunnitellussa laajuudessa, alueiden on arvioitava uudelleen palveluiden järjestämistä, henkilöstöresursseja ja hankintoja. "
        "Samalla paine kasvaa osoittaa, että muutokset voidaan tehdä hallitusti ja että kriittiset palvelut pysyvät saatavilla. "
        "Päätösten lopullinen vaikutus riippuu siitä, miten säästöt kohdennetaan ja millaisia lieventäviä ratkaisuja niiden rinnalle rakennetaan."
    )
    para5 = (
        "## Miksi asiasta kiistellään\n"
        "Oppositio on arvostellut säästövalmistelua siitä, että vaikutuksia haavoittuviin ryhmiin ei vielä tunneta riittävän tarkasti. "
        "Hallitus puolestaan painottaa, että julkisen talouden tasapainottaminen vaatii vaikeita ratkaisuja ja että lopulliset päätökset tehdään vasta vaikutusarvioiden valmistuttua. "
        "Keskustelu jatkuu todennäköisesti koko budjettivalmistelun ajan, koska säästöjen laajuus ja kohdentuminen vaikuttavat laajasti palvelujärjestelmään."
    )
    return "\n\n".join([para1, para2, para3, para4, para5])


def _good_payload() -> str:
    payload = {
        "packet_id": "abc",
        "title": "Hallitus valmistelee uusia säästöjä sosiaalihuoltoon",
        "summary": "Hallitus valmistelee uusia säästöjä sosiaalihuoltoon ensi vuodelle.",
        "content": _long_content(),
        "category": "Kotimaa",
        "tags": ["hallitus", "säästöt", "sosiaalihuolto"],
        "summary_bullets": [
            "Hallitus valmistelee säästöjä sosiaalihuoltoon.",
            "Päätöksiä valmistellaan ensi vuodelle.",
            "Vaikutukset kohdistuvat useisiin palveluihin.",
        ],
        "content_type": "article",
        "editorial_reviewed": True,
        "confidence": 0.88,
        "journalist_note": " ",
    }
    return json.dumps(payload, ensure_ascii=False)


class MonicaWriterTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["MONICA_QUEUE_DIR"] = self.tmpdir.name
        os.environ["MONICA_OPENCLAW_CMD"] = "openclaw"
        os.environ["MONICA_OPENCLAW_LOCAL"] = "1"

    def tearDown(self):
        self.tmpdir.cleanup()
        for key in ("MONICA_QUEUE_DIR", "MONICA_OPENCLAW_CMD", "MONICA_OPENCLAW_LOCAL"):
            os.environ.pop(key, None)

    def _result(self, stdout: str):
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    def test_openclaw_candidates_include_user_bin_wrapper_first(self):
        self.assertEqual(OPENCLAW_CANDIDATES[0], "/home/pertt/.openclaw/bin/openclaw")

    def test_extract_json_object_skips_noisy_braces_before_payload(self):
        raw = 'openclaw: dispatch {agent=monica}\nnot json {oops}\n' + _good_payload() + '\n[done]'

        payload = _extract_json_object(raw)

        self.assertEqual(payload["category"], "Kotimaa")
        self.assertIn("Hallitus valmistelee", payload["title"])

    def test_extract_json_object_accepts_fenced_payload_with_commentary(self):
        raw = "Valmis:\n```JSON\n" + _good_payload() + "\n```\nTarkistettu."

        payload = _extract_json_object(raw)

        self.assertEqual(payload["content_type"], "article")

    def test_extract_json_object_repairs_single_missing_final_brace_after_warning(self):
        raw = "plugin warning\n" + _good_payload()[:-1]
        payload = _extract_json_object(raw)
        self.assertIn("Hallitus valmistelee", payload["title"])

    def test_extract_json_object_does_not_repair_truncated_string(self):
        raw = "plugin warning\n" + _good_payload()[:-12]
        with self.assertRaises(ValueError):
            _extract_json_object(raw)

    @patch(PATCH_TARGET)
    def test_rewrite_articles_valid_output(self, run_mock):
        run_mock.return_value = self._result(_good_payload())

        rewritten = rewrite_articles([dict(SAMPLE_ARTICLE)])
        self.assertEqual(len(rewritten), 1)
        article = rewritten[0]
        self.assertEqual(article["writer_backend"], "monica")
        self.assertEqual(article["category"], "Kotimaa")
        self.assertGreaterEqual(len(article["key_points"]), 2)
        self.assertIn("Hallitus valmistelee", article["content"])

    def test_merge_article_preserves_packet_category_over_payload_guess(self):
        original = {**SAMPLE_ARTICLE, "category_hint": "Talous"}
        packet = _source_packet(360, blocks=2)
        packet["category"] = "Talous"
        payload = json.loads(_good_payload())
        payload["category"] = "Ulkomaat"

        article = _merge_article(original, packet, payload)

        self.assertEqual(article["category"], "Talous")


    def test_merge_article_preserves_original_guessed_talous_over_packet_ulkomaat(self):
        original = {**SAMPLE_ARTICLE, "category_hint": "", "_guessed_category": "Talous"}
        packet = _source_packet(360, blocks=2)
        packet["category"] = "Ulkomaat"
        packet["category_hint"] = "Ulkomaat"
        payload = json.loads(_good_payload())
        payload["category"] = "Ulkomaat"

        article = _merge_article(original, packet, payload)

        self.assertEqual(article["category"], "Talous")

    @patch(PATCH_TARGET)
    def test_rewrite_articles_repairs_once(self, run_mock):
        broken_payload = {
            "packet_id": "abc",
            "title": "Broken",
            "summary": "Too short",
            "content": "Liian lyhyt teksti.",
            "category": "Kotimaa",
            "tags": ["hallitus"],
            "summary_bullets": [],
            "content_type": "article",
            "editorial_reviewed": True,
            "confidence": 0.70,
            "journalist_note": " ",
        }
        run_mock.side_effect = [self._result(json.dumps(broken_payload, ensure_ascii=False)), self._result(_good_payload())]

        rewritten = rewrite_articles([dict(SAMPLE_ARTICLE)])
        self.assertEqual(len(rewritten), 1)
        self.assertEqual(run_mock.call_count, 2)

    @patch(RESOLVE_PATCH_TARGET, side_effect=FileNotFoundError("openclaw"))
    def test_rewrite_articles_quarantine_cli_missing_has_reason_code(self, _resolve_mock):
        rewritten = rewrite_articles([dict(SAMPLE_ARTICLE)])

        self.assertEqual(rewritten, [])
        quarantine_dir = os.path.join(self.tmpdir.name, "quarantine")
        files = [name for name in os.listdir(quarantine_dir) if name.endswith(".json")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(quarantine_dir, files[0]), encoding="utf-8") as f:
            quarantine = json.load(f)
        self.assertEqual(quarantine["reason"], "dispatch_error")
        self.assertEqual(quarantine["extra"].get("reason_code"), "cli_missing")

    @patch(PATCH_TARGET, side_effect=TimeoutError("timed out"))
    def test_rewrite_articles_quarantine_timeout_has_reason_code(self, _run_mock):
        rewritten = rewrite_articles([dict(SAMPLE_ARTICLE)])

        self.assertEqual(rewritten, [])
        quarantine_dir = os.path.join(self.tmpdir.name, "quarantine")
        files = [name for name in os.listdir(quarantine_dir) if name.endswith(".json")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(quarantine_dir, files[0]), encoding="utf-8") as f:
            quarantine = json.load(f)
        self.assertEqual(quarantine["reason"], "dispatch_error")
        self.assertEqual(quarantine["extra"].get("reason_code"), "timeout")

    @patch(PATCH_TARGET)
    def test_rewrite_articles_quarantine_context_overflow_has_reason_code(self, run_mock):
        run_mock.return_value = self._result("Context overflow: prompt too large for the model")

        rewritten = rewrite_articles([dict(SAMPLE_ARTICLE)])

        self.assertEqual(rewritten, [])
        quarantine_dir = os.path.join(self.tmpdir.name, "quarantine")
        files = [name for name in os.listdir(quarantine_dir) if name.endswith(".json")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(quarantine_dir, files[0]), encoding="utf-8") as f:
            quarantine = json.load(f)
        self.assertEqual(quarantine["reason"], "dispatch_error")
        self.assertEqual(quarantine["extra"].get("reason_code"), "context_overflow")

    @patch(PATCH_TARGET)
    def test_rewrite_articles_quarantines_insufficient_confidence(self, run_mock):
        run_mock.return_value = self._result(json.dumps({"packet_id": "abc", "status": "INSUFFICIENT_CONFIDENCE", "reason": "source too thin"}))

        rewritten = rewrite_articles([dict(SAMPLE_ARTICLE)])
        self.assertEqual(rewritten, [])
        quarantine_dir = os.path.join(self.tmpdir.name, "quarantine")
        self.assertTrue(os.path.isdir(quarantine_dir))
        self.assertTrue(any(name.endswith(".json") for name in os.listdir(quarantine_dir)))

    @patch(PATCH_TARGET)
    def test_rewrite_articles_quarantine_parse_failure_has_reason_code(self, run_mock):
        run_mock.return_value = self._result("openclaw progress {not-json}\nMonica failed to produce JSON")

        rewritten = rewrite_articles([dict(SAMPLE_ARTICLE)])

        self.assertEqual(rewritten, [])
        quarantine_dir = os.path.join(self.tmpdir.name, "quarantine")
        files = [name for name in os.listdir(quarantine_dir) if name.endswith(".json")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(quarantine_dir, files[0]), encoding="utf-8") as f:
            quarantine = json.load(f)
        self.assertEqual(quarantine["reason"], "dispatch_error")
        self.assertEqual(quarantine["extra"].get("reason_code"), "json_parse_failed")
        self.assertEqual(quarantine["extra"].get("stage"), "initial_parse")

    @patch(PATCH_TARGET)
    def test_rewrite_articles_resets_local_session_on_context_overflow(self, run_mock):
        run_mock.side_effect = [
            self._result("Context overflow: prompt too large for the model. Try /reset (or /new) to start a fresh session."),
            self._result(_good_payload()),
        ]

        rewritten = rewrite_articles([dict(SAMPLE_ARTICLE)])

        self.assertEqual(len(rewritten), 1)
        self.assertEqual(run_mock.call_count, 2)
        first_cmd = run_mock.call_args_list[0].args[0]
        retry_cmd = run_mock.call_args_list[1].args[0]
        self.assertNotIn("/reset", retry_cmd)
        self.assertNotEqual(first_cmd, retry_cmd)
        if "--session-id" in first_cmd:
            self.assertIn("--session-id", retry_cmd)
            self.assertNotEqual(first_cmd[first_cmd.index("--session-id") + 1], retry_cmd[retry_cmd.index("--session-id") + 1])
        else:
            self.assertIn("--local", first_cmd)
            self.assertIn("--session-id", retry_cmd)
            self.assertNotIn("--local", retry_cmd)

    def test_source_backed_repair_candidate_requires_words_blocks_and_length_issue(self):
        issues = ["content too short: 207 words", "lead paragraph too short: 22 words"]

        self.assertTrue(_is_source_backed_repair_candidate(_source_packet(320, blocks=2), issues))
        self.assertFalse(_is_source_backed_repair_candidate(_source_packet(260, blocks=2), issues))
        self.assertFalse(_is_source_backed_repair_candidate(_source_packet(320, blocks=1), issues))
        self.assertFalse(_is_source_backed_repair_candidate(_source_packet(320, blocks=2), ["not enough tags"]))

    def test_packet_source_words_prefers_clean_selected_blocks_over_full_source_text(self):
        packet = _source_packet(120, blocks=2)
        packet["source_text"] = " ".join(["sana"] * 600)

        self.assertEqual(_packet_source_words(packet), 120)
        self.assertEqual(_packet_source_blocks(packet), 2)
        self.assertFalse(_is_source_backed_repair_candidate(packet, ["content too short: 220 words"]))

    def test_repair_prompt_strengthens_source_backed_short_draft_without_lowering_gate(self):
        packet = _source_packet(360, blocks=2)
        broken_payload = json.loads(_good_payload())
        broken_payload["content"] = " ".join(["Sana"] * 207)

        prompt = _build_repair_prompt(packet, broken_payload, ["content too short: 207 words"])

        self.assertIn("Source-backed repair mode", prompt)
        self.assertIn("short draft is a repair target", prompt)
        self.assertIn("source_words: 360", prompt)
        self.assertIn("MUST be at least 250 Finnish words", prompt)
        self.assertIn("source_backed_writer_shortfall_unrepairable", prompt)
        self.assertIn("Do not stop at 210–249 words", prompt)
        self.assertIn("return INSUFFICIENT_CONFIDENCE", prompt)
        self.assertIn("Do not pad", prompt)


    def test_near_short_repair_prompt_uses_source_backed_rules_for_200_word_marker(self):
        packet = _source_packet(216, blocks=3)
        packet["story_confidence"] = 0.98
        broken_payload = json.loads(_good_payload())
        broken_payload["content"] = " ".join(["Sana"] * 248)

        prompt = _build_repair_prompt(packet, broken_payload, [
            "content too short: 248 words",
            "source_backed_writer_shortfall: final expansion required",
        ])

        self.assertIn("Source-backed repair mode", prompt)
        self.assertIn("source_words: 216", prompt)
        self.assertIn("source_blocks: 3", prompt)
        self.assertIn("MUST be at least 250 Finnish words", prompt)
        self.assertIn("Do not stop at 210–249 words", prompt)

    def test_source_backed_near_miss_requires_source_confidence_and_210_249_words(self):
        packet = _source_packet(200, blocks=2)
        packet["story_confidence"] = 0.85
        payload = json.loads(_good_payload())
        payload["content"] = " ".join(["Sana"] * 211)

        self.assertTrue(_is_source_backed_near_miss(packet, payload, ["content too short: 211 words"]))
        payload["content"] = " ".join(["Sana"] * 209)
        self.assertFalse(_is_source_backed_near_miss(packet, payload, ["content too short: 209 words"]))
        payload["content"] = " ".join(["Sana"] * 250)
        self.assertFalse(_is_source_backed_near_miss(packet, payload, []))
        payload["content"] = " ".join(["Sana"] * 247)
        reduced_floor_packet = _source_packet(180, blocks=2)
        reduced_floor_packet["story_confidence"] = 0.85
        self.assertTrue(_is_source_backed_near_miss(reduced_floor_packet, payload, ["content too short: 247 words"]))
        below_floor_packet = _source_packet(178, blocks=2)
        below_floor_packet["story_confidence"] = 0.85
        self.assertFalse(_is_source_backed_near_miss(below_floor_packet, payload, ["content too short: 247 words"]))
        self.assertFalse(_is_source_backed_near_miss(_source_packet(220, blocks=1), payload, ["content too short: 247 words"]))
        low_confidence = _source_packet(360, blocks=2)
        low_confidence["story_confidence"] = 0.84
        self.assertFalse(_is_source_backed_near_miss(low_confidence, payload, ["content too short: 247 words"]))

        for category in ("Teknologia", "Kotimaa", "Ulkomaat"):
            packet = _source_packet(180, blocks=2)
            packet["category"] = category
            packet["story_confidence"] = 0.9
            self.assertTrue(_is_source_backed_near_miss(packet, payload, ["content too short: 247 words"]))

    def test_packet_story_confidence_prefers_story_confidence_over_payload_confidence(self):
        packet = {"story_confidence": 0.91, "confidence": 0.2}
        self.assertEqual(_packet_story_confidence(packet), 0.91)
        self.assertEqual(_packet_story_confidence({"confidence": 0.86}), 0.86)


    def test_near_miss_repair_metadata_records_recovered_runtime_proof(self):
        packet = _source_packet(220, blocks=2)
        initial_payload = json.loads(_good_payload())
        initial_payload["content"] = " ".join(["Sana"] * 247)
        final_payload = json.loads(_good_payload())
        final_payload["content"] = " ".join(["Sana"] * 281)

        metadata = _near_miss_repair_metadata(packet, initial_payload, final_payload, [])

        self.assertEqual(metadata["repair_attempt"], "source_backed_near_short")
        self.assertEqual(metadata["pre_repair_word_count"], 247)
        self.assertEqual(metadata["post_repair_word_count"], 281)
        self.assertEqual(metadata["repair_result"], "published")
        self.assertIn("pre_repair_word_count=247", metadata["repair_trigger"])
        self.assertGreaterEqual(metadata["selected_source_words_at_repair"], 200)
        self.assertGreaterEqual(metadata["selected_source_blocks_at_repair"], 2)
        self.assertGreaterEqual(metadata["source_words"], 200)
        self.assertGreaterEqual(metadata["source_blocks"], 2)
        self.assertIn("repair_attempted_at", metadata)
        self.assertTrue(metadata["source_block_ids_used_for_repair"])
        self.assertTrue(metadata["recovered"])

    @patch(PATCH_TARGET)
    def test_rewrite_articles_retries_source_backed_near_miss_once(self, run_mock):
        near_miss_payload = json.loads(_good_payload())
        near_miss_payload["content"] = " ".join(["Sana"] * 247)
        repaired_payload = json.loads(_good_payload())
        repaired_payload["content"] = _long_content()
        source_text = "\n\n".join(["[Lähde: Testi %d]\nHallitus valmistelee säästöjä sosiaalihuoltoon ensi vuodelle. %s" % (i, " ".join(["palvelu"] * 160)) for i in range(3)])
        article = {
            "title": "Hallitus valmistelee uusia säästöjä",
            "description": source_text,
            "link": "https://example.com/story",
            "category_hint": "Kotimaa",
            "research": source_text,
        }

        run_mock.side_effect = [
            self._result(json.dumps(near_miss_payload, ensure_ascii=False)),
            self._result(json.dumps(near_miss_payload, ensure_ascii=False)),
            self._result(json.dumps(repaired_payload, ensure_ascii=False)),
        ]

        from pipeline.story_packet import build_story_packet as original_build_story_packet
        original_packet = original_build_story_packet(article)
        original_packet["source_text"] = " ".join(["Hallitus valmistelee säästöjä sosiaalihuoltoon ensi vuodelle"] * 80)
        original_packet["story_confidence"] = 0.9
        original_packet["clean_source_blocks"] = [
            {"text": " ".join(["Hallitus valmistelee säästöjä sosiaalihuoltoon ensi vuodelle"] * 20), "word_count": 120, "source": "Testi"},
            {"text": " ".join(["Hallitus valmistelee säästöjä sosiaalihuoltoon ensi vuodelle"] * 15), "word_count": 90, "source": "Testi 2"},
        ]
        with patch(f"{rewrite_articles.__module__}.build_story_packet", return_value=original_packet):
            rewritten = rewrite_articles([article])

        self.assertEqual(len(rewritten), 1)
        self.assertGreaterEqual(len(rewritten[0]["content"].split()), 250)
        self.assertEqual(run_mock.call_count, 3)
        self.assertIn("source_backed_writer_shortfall", run_mock.call_args_list[2].args[0][-1])
        self.assertIn("source_words:", run_mock.call_args_list[2].args[0][-1])
        self.assertEqual(rewritten[0]["monica_repair"]["repair_attempt"], "source_backed_near_short")
        self.assertEqual(rewritten[0]["monica_repair"]["pre_repair_word_count"], 247)
        self.assertGreaterEqual(rewritten[0]["monica_repair"]["post_repair_word_count"], 250)
        self.assertEqual(rewritten[0]["monica_repair"]["repair_result"], "published")
        self.assertTrue(rewritten[0]["monica_repair"]["source_block_ids_used_for_repair"])
        self.assertTrue(rewritten[0]["monica_repair"]["recovered"])


    @patch(PATCH_TARGET)
    def test_rewrite_articles_quarantines_source_backed_near_miss_with_explicit_reason(self, run_mock):
        near_miss_payload = json.loads(_good_payload())
        near_miss_payload["content"] = " ".join(["Sana"] * 247)
        packet = _source_packet(220, blocks=2)
        packet["story_confidence"] = 0.9

        run_mock.side_effect = [
            self._result(json.dumps(near_miss_payload, ensure_ascii=False)),
            self._result(json.dumps(near_miss_payload, ensure_ascii=False)),
            self._result(json.dumps(near_miss_payload, ensure_ascii=False)),
        ]

        with patch(f"{rewrite_articles.__module__}.build_story_packet", return_value=packet), \
             patch(f"{rewrite_articles.__module__}.save_writer_quarantine") as quarantine_mock:
            rewritten = rewrite_articles([dict(SAMPLE_ARTICLE)])

        self.assertEqual(rewritten, [])
        self.assertEqual(run_mock.call_count, 3)
        self.assertTrue(quarantine_mock.called)
        self.assertEqual(quarantine_mock.call_args.args[1], "source_backed_writer_shortfall_unrepairable")
        extra = quarantine_mock.call_args.kwargs["extra"]
        self.assertEqual(extra["reason_code"], "source_backed_writer_shortfall_unrepairable")
        self.assertEqual(extra["final_word_count"], 247)
        self.assertGreaterEqual(extra["source_words"], 200)
        self.assertGreaterEqual(extra["source_blocks"], 2)

    @patch(PATCH_TARGET)
    def test_rewrite_articles_rejects_still_short_after_repair(self, run_mock):
        short_content = " ".join(["Sana"] * 180)
        short_payload = json.loads(_good_payload())
        short_payload["content"] = short_content
        run_mock.side_effect = [
            self._result(json.dumps(short_payload, ensure_ascii=False)),
            self._result(json.dumps(short_payload, ensure_ascii=False)),
        ]

        rewritten = rewrite_articles([dict(SAMPLE_ARTICLE)])
        self.assertEqual(rewritten, [])
        self.assertEqual(run_mock.call_count, 2)
        quarantine_dir = os.path.join(self.tmpdir.name, "quarantine")
        self.assertTrue(any(name.endswith(".json") for name in os.listdir(quarantine_dir)))


if __name__ == "__main__":
    unittest.main()
