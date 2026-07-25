#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    from .monica_writer import MIN_CONTENT_WORDS, OPENCLAW_CANDIDATES, SOURCE_BACKED_NEAR_MISS_MIN_WORDS, _build_prompt, _build_repair_prompt, _extract_json_object, _is_source_backed_near_miss, _is_source_backed_repair_candidate, _is_source_backed_talous_micro_near_miss, _merge_article, _near_miss_repair_metadata, _openclaw_command, _packet_source_blocks, _packet_source_words, _packet_story_confidence, _run_openclaw_command, rewrite_articles
    PATCH_TARGET = "pipeline.monica_writer.subprocess.run"
    RESOLVE_PATCH_TARGET = "pipeline.monica_writer._resolve_openclaw_base_cmd"
    TIMING_LOG_PATCH_TARGET = "pipeline.monica_writer.MONICA_DISPATCH_TIMING_LOG"
except ImportError:  # pragma: no cover - direct execution from pipeline cwd
    from monica_writer import MIN_CONTENT_WORDS, OPENCLAW_CANDIDATES, SOURCE_BACKED_NEAR_MISS_MIN_WORDS, _build_prompt, _build_repair_prompt, _extract_json_object, _is_source_backed_near_miss, _is_source_backed_repair_candidate, _is_source_backed_talous_micro_near_miss, _merge_article, _near_miss_repair_metadata, _openclaw_command, _packet_source_blocks, _packet_source_words, _packet_story_confidence, _run_openclaw_command, rewrite_articles
    PATCH_TARGET = "monica_writer.subprocess.run"
    RESOLVE_PATCH_TARGET = "monica_writer._resolve_openclaw_base_cmd"
    TIMING_LOG_PATCH_TARGET = "monica_writer.MONICA_DISPATCH_TIMING_LOG"


SAMPLE_ARTICLE = {
    "title": "Hallitus valmistelee uusia säästöjä",
    "description": "Hallitus valmistelee uusia sosiaalihuollon säästöjä ja esittää niiden tulevan voimaan ensi vuonna.",
    "link": "https://example.com/story",
    "category_hint": "Kotimaa",
    "research": "[Lähde: Yle | URL: https://yle.fi/a/testi]\nHallitus valmistelee uusia sosiaalihuollon säästöjä. Päätöksiä valmistellaan ensi vuodelle ja vaikutukset kohdistuvat useisiin palveluihin.\n\n---\n\n[Lähde: BBC | URL: https://bbc.com/news/test]\nThe government is preparing new savings measures for social care. Ministers say the final package is still under preparation.",
}


def _source_packet(source_words: int, blocks: int = 2) -> dict:
    block_text = " ".join(["sana"] * max(1, source_words // max(1, blocks)))
    return {
        "packet_id": "talous-test",
        "category_hint": "Talous",
        "source_text": "\n\n".join(f"[Lähde: Testi {idx}]\n{block_text}" for idx in range(blocks)),
        "clean_source_blocks": [
            {"source": f"Testi {idx}", "source_url": f"https://testi.example/{idx}", "source_domain": "testi.example", "text": block_text, "word_count": len(block_text.split())}
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
        self.timing_log_patch = patch(TIMING_LOG_PATCH_TARGET, Path(self.tmpdir.name) / "dispatch.jsonl")
        self.timing_log_patch.start()

    def tearDown(self):
        self.timing_log_patch.stop()
        self.tmpdir.cleanup()
        for key in ("MONICA_QUEUE_DIR", "MONICA_OPENCLAW_CMD", "MONICA_OPENCLAW_LOCAL"):
            os.environ.pop(key, None)

    def _result(self, stdout: str):
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    @patch(RESOLVE_PATCH_TARGET, return_value=["openclaw"])
    def test_local_command_keeps_packet_in_unique_explicit_session(self, _resolve_mock):
        cmd = _openclaw_command("prompt", force_local=True, session_id="packet-session")

        self.assertIn("--local", cmd)
        self.assertIn("--session-id", cmd)
        self.assertEqual(cmd[cmd.index("--session-id") + 1], "packet-session")

    @patch(RESOLVE_PATCH_TARGET, return_value=["openclaw"])
    def test_gateway_command_keeps_packet_in_unique_explicit_session(self, _resolve_mock):
        cmd = _openclaw_command("prompt", force_local=False, session_id="packet-session")

        self.assertNotIn("--local", cmd)
        self.assertIn("--session-id", cmd)
        self.assertEqual(cmd[cmd.index("--session-id") + 1], "packet-session")

    @patch(RESOLVE_PATCH_TARGET, return_value=["openclaw"])
    def test_default_command_uses_isolated_local_mode(self, _resolve_mock):
        with patch.dict(os.environ, {"MONICA_OPENCLAW_CMD": "openclaw"}, clear=True):
            cmd = _openclaw_command("prompt", session_id="packet-session")

        self.assertIn("--local", cmd)
        self.assertIn("--session-id", cmd)
        self.assertEqual(cmd[cmd.index("--session-id") + 1], "packet-session")

    @patch(RESOLVE_PATCH_TARGET, return_value=["openclaw"])
    def test_legacy_fixed_session_environment_cannot_disable_isolation(self, _resolve_mock):
        with patch.dict(os.environ, {"MONICA_OPENCLAW_SESSION_ID": "legacy-fixed-session"}, clear=False):
            first = _openclaw_command("first")
            second = _openclaw_command("second")

        first_session = first[first.index("--session-id") + 1]
        second_session = second[second.index("--session-id") + 1]
        self.assertNotEqual(first_session, "legacy-fixed-session")
        self.assertNotEqual(second_session, "legacy-fixed-session")
        self.assertNotEqual(first_session, second_session)

    def test_openclaw_candidates_include_user_bin_wrapper_first(self):
        self.assertEqual(OPENCLAW_CANDIDATES[0], "/home/pertt/.openclaw/bin/openclaw")

    @patch(PATCH_TARGET)
    def test_rewrite_fails_closed_before_dispatch_on_provenance_mismatch(self, run_mock):
        packet = _source_packet(120, blocks=1)
        packet["clean_source_blocks"][0]["source_domain"] = "wrong.example"

        with patch(f"{rewrite_articles.__module__}.build_story_packet", return_value=packet), \
             patch(f"{rewrite_articles.__module__}.save_writer_quarantine") as quarantine_mock:
            rewritten = rewrite_articles([dict(SAMPLE_ARTICLE)])

        self.assertEqual(rewritten, [])
        run_mock.assert_not_called()
        self.assertEqual(quarantine_mock.call_args.args[1], "selected_source_provenance_invalid")
        self.assertEqual(
            quarantine_mock.call_args.kwargs["extra"]["reason_code"],
            "selected_source_provenance_invalid",
        )

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

    def test_merge_article_recovers_retained_macroeconomy_candidate(self):
        original = {
            **SAMPLE_ARTICLE,
            "title": "One Nation capitalises on economic pessimism",
            "description": "Inflation, high housing costs and interest rate hikes weigh on households.",
            "category_hint": "Ulkomaat",
            "_guessed_category": "Ulkomaat",
        }
        packet = _source_packet(360, blocks=2)
        packet["category"] = "Kotimaa"
        packet["category_hint"] = "Kotimaa"
        payload = json.loads(_good_payload())
        payload["category"] = "Kotimaa"
        payload["title"] = "Talouspessimismi kasvattaa One Nationin kannatusta"
        payload["summary"] = "Inflaatio ja korkeat asumiskustannukset painavat kotitalouksia."
        payload["content"] += " Elinkustannukset ja korkojen nousu lisäävät epävarmuutta."

        article = _merge_article(original, packet, payload)

        self.assertEqual(article["category"], "Talous")

    def test_merge_article_recovers_retained_household_finance_candidate(self):
        fixture_path = (
            Path(__file__).resolve().parent
            / "queues/staged/published/20260713T061121Z_40f48c408f.json"
        )
        retained = json.loads(fixture_path.read_text(encoding="utf-8"))

        article = _merge_article(
            retained["original_article"], retained["packet"], retained["payload"]
        )

        self.assertEqual(retained["packet"]["category"], "Kotimaa")
        self.assertEqual(retained["payload"]["category"], "Kotimaa")
        self.assertEqual(article["category"], "Talous")

    def test_merge_article_preserves_retained_iphone_technology_category(self):
        fixture_path = (
            Path(__file__).resolve().parent
            / "queues/staged/published/20260719T170121Z_452931fc1d.json"
        )
        retained = json.loads(fixture_path.read_text(encoding="utf-8"))

        article = _merge_article(
            retained["original_article"], retained["packet"], retained["payload"]
        )

        self.assertEqual(retained["packet"]["category"], "Teknologia")
        self.assertEqual(retained["payload"]["category"], "Teknologia")
        self.assertEqual(retained["article"]["category"], "Talous")
        self.assertEqual(article["category"], "Teknologia")

    def test_merge_article_preserves_retained_immigration_packet_category(self):
        fixture_path = (
            Path(__file__).resolve().parent
            / "queues/staged/published/20260712T191123Z_48bdfbec17.json"
        )
        retained = json.loads(fixture_path.read_text(encoding="utf-8"))

        article = _merge_article(
            retained["original_article"], retained["packet"], retained["payload"]
        )

        self.assertEqual(retained["payload"]["category"], "Ulkomaat")
        self.assertEqual(article["category"], "Ulkomaat")

    def test_merge_article_demotes_tiede_school_police_incident_to_kotimaa(self):
        original = {
            **SAMPLE_ARTICLE,
            "title": "Poliisi otti kiinni Samkin tiloissa liikkuneen aseistautuneen henkilön",
            "description": "Poliisi kertoo tilanteesta Satakunnan ammattikorkeakoulun kampuksella.",
            "category_hint": "Tiede",
        }
        packet = _source_packet(360, blocks=2)
        packet["category"] = "Tiede"
        packet["category_hint"] = "Tiede"
        payload = json.loads(_good_payload())
        payload["category"] = "Tiede"
        payload["title"] = original["title"]
        payload["summary"] = original["description"]
        payload["content"] = (
            "Poliisi on ottanut kiinni Porissa Satakunnan ammattikorkeakoulussa "
            "henkilön, jonka epäillään liikkuneen tiloissa aseistautuneena."
        )

        article = _merge_article(original, packet, payload)

        self.assertEqual(article["category"], "Kotimaa")

    def test_merge_article_demotes_tiede_school_crime_stats_to_kotimaa(self):
        original = {
            **SAMPLE_ARTICLE,
            "title": "Opettaja kertoo levottomuuden lisääntyneen koulussa – oppilaitoksista tehtiin yli 6 500 rikosilmoitusta vuodessa",
            "description": "Poliisihallituksen tilastojen mukaan oppi- ja tutkimuslaitoksista tehtiin viime vuonna yli 6 500 rikosilmoitusta.",
            "category_hint": "Tiede",
        }
        packet = _source_packet(360, blocks=2)
        packet["category"] = "Tiede"
        packet["category_hint"] = "Tiede"
        payload = json.loads(_good_payload())
        payload["category"] = "Tiede"
        payload["title"] = original["title"]
        payload["summary"] = original["description"]
        payload["content"] = (
            "Pitkään opettajana työskennellyt Sirpa kertoo selvittelevänsä "
            "koulussa tapahtuneita oppilaiden välisiä tilanteita. "
            "Poliisihallituksen tilastoissa oppi- ja tutkimuslaitoksista "
            "tehtiin viime vuonna yli 6 500 rikosilmoitusta."
        )

        article = _merge_article(original, packet, payload)

        self.assertEqual(article["category"], "Kotimaa")

    def test_merge_article_demotes_tiede_riihimaki_explosive_to_kotimaa(self):
        original = {
            **SAMPLE_ARTICLE,
            "title": "Poliisi sai Riihimäen räjähteestä ilmoituksen jo huhtikuussa",
            "description": "Hämeen poliisi selvittää pellolta löytyneen räjähteen tapahtumaketjua.",
            "category_hint": "Tiede",
        }
        packet = _source_packet(360, blocks=2)
        packet["category"] = "Tiede"
        packet["category_hint"] = "Tiede"
        payload = json.loads(_good_payload())
        payload["category"] = "Tiede"
        payload["title"] = original["title"]
        payload["summary"] = original["description"]
        payload["content"] = (
            "Hämeen poliisi selvittää Riihimäen jäähallin läheltä löytyneen "
            "räjähteen tapahtumaketjua. Poliisi sai asiasta ilmoituksen jo "
            "huhtikuussa ja löytö on raivattu."
        )

        article = _merge_article(original, packet, payload)

        self.assertEqual(article["category"], "Kotimaa")

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
    def test_run_openclaw_command_accepts_complete_json_from_timeout_stdout(self, run_mock):
        run_mock.side_effect = subprocess.TimeoutExpired(["openclaw"], 360, output="progress\n" + _good_payload())

        raw = _run_openclaw_command(["openclaw"])

        self.assertIn("Hallitus valmistelee", raw)
        self.assertEqual(_extract_json_object(raw)["category"], "Kotimaa")

    @patch(PATCH_TARGET)
    def test_run_openclaw_command_uses_360_default_timeout_when_env_absent(self, run_mock):
        run_mock.return_value = self._result(_good_payload())

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MONICA_WRITER_TIMEOUT_SEC", None)
            _run_openclaw_command(["openclaw"])

        self.assertEqual(run_mock.call_args.kwargs["timeout"], 360)

    @patch(PATCH_TARGET)
    def test_run_openclaw_command_rejects_incomplete_timeout_stdout(self, run_mock):
        run_mock.side_effect = subprocess.TimeoutExpired(["openclaw"], 360, output="progress\n" + _good_payload()[:-20])

        with self.assertRaises(RuntimeError):
            _run_openclaw_command(["openclaw"])

    @patch(PATCH_TARGET)
    def test_run_openclaw_command_writes_redacted_dispatch_timing(self, run_mock):
        timing_log = os.path.join(self.tmpdir.name, "dispatch.jsonl")
        run_mock.return_value = self._result(_good_payload())

        with patch(TIMING_LOG_PATCH_TARGET, Path(timing_log)):
            _run_openclaw_command(["openclaw", "agent", "--agent", "monica", "--session-id", "secret-session", "--message", "prompt text"])

        row = json.loads(Path(timing_log).read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(row["schema"], "uutistenlukija.monica_dispatch_timing.v1")
        self.assertEqual(row["outcome"], "success")
        self.assertEqual(row["mode"], "gateway")
        self.assertIn("session_id_hash", row)
        self.assertNotIn("secret-session", json.dumps(row))
        self.assertNotIn("prompt text", json.dumps(row))

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
        self.assertIn("--local", first_cmd)
        self.assertIn("--local", retry_cmd)
        self.assertIn("--session-id", first_cmd)
        self.assertIn("--session-id", retry_cmd)
        self.assertNotEqual(first_cmd[first_cmd.index("--session-id") + 1], retry_cmd[retry_cmd.index("--session-id") + 1])

    @patch(PATCH_TARGET)
    def test_rewrite_articles_resets_gateway_session_on_context_overflow(self, run_mock):
        run_mock.side_effect = [
            self._result("Context overflow: prompt too large for the model. Try /reset (or /new) to start a fresh session."),
            self._result(_good_payload()),
        ]

        with patch.dict(os.environ, {"MONICA_OPENCLAW_LOCAL": "0"}, clear=False):
            rewritten = rewrite_articles([dict(SAMPLE_ARTICLE)])

        self.assertEqual(len(rewritten), 1)
        self.assertEqual(run_mock.call_count, 2)
        first_cmd = run_mock.call_args_list[0].args[0]
        retry_cmd = run_mock.call_args_list[1].args[0]
        self.assertNotIn("--local", first_cmd)
        self.assertNotIn("--local", retry_cmd)
        self.assertIn("--session-id", first_cmd)
        self.assertIn("--session-id", retry_cmd)
        self.assertNotEqual(first_cmd[first_cmd.index("--session-id") + 1], retry_cmd[retry_cmd.index("--session-id") + 1])

    def test_source_backed_repair_candidate_requires_words_blocks_and_length_issue(self):
        issues = ["content too short: 207 words", "lead paragraph too short: 22 words"]

        self.assertTrue(_is_source_backed_repair_candidate(_source_packet(360, blocks=3), issues))
        near_floor = _source_packet(252, blocks=3)
        near_floor["story_confidence"] = 0.85
        self.assertTrue(_is_source_backed_repair_candidate(near_floor, issues))
        low_confidence = _source_packet(260, blocks=3)
        low_confidence["story_confidence"] = 0.84
        self.assertFalse(_is_source_backed_repair_candidate(low_confidence, issues))
        self.assertFalse(_is_source_backed_repair_candidate(_source_packet(320, blocks=1), issues))
        self.assertFalse(_is_source_backed_repair_candidate(_source_packet(320, blocks=2), issues))
        self.assertFalse(_is_source_backed_repair_candidate(_source_packet(320, blocks=2), ["not enough tags"]))

    def test_packet_source_words_prefers_clean_selected_blocks_over_full_source_text(self):
        packet = _source_packet(120, blocks=2)
        packet["source_text"] = " ".join(["sana"] * 600)

        self.assertEqual(_packet_source_words(packet), 120)
        self.assertEqual(_packet_source_blocks(packet), 2)
        packet["story_confidence"] = 0.84
        self.assertFalse(_is_source_backed_repair_candidate(packet, ["content too short: 220 words"]))

    def test_repair_prompt_strengthens_source_backed_short_draft_without_lowering_gate(self):
        packet = _source_packet(360, blocks=3)
        broken_payload = json.loads(_good_payload())
        broken_payload["content"] = " ".join(["Sana"] * 207)

        prompt = _build_repair_prompt(packet, broken_payload, ["content too short: 207 words"])

        self.assertIn("Source-backed repair mode", prompt)
        self.assertIn("short draft is a repair target", prompt)
        self.assertIn("source_words: 360", prompt)
        self.assertIn("MUST be at least 250 Finnish words", prompt)
        self.assertIn("first paragraph MUST be at least 30 words", prompt)
        self.assertIn("source_backed_writer_shortfall_unrepairable", prompt)
        self.assertIn(f"Do not stop at {SOURCE_BACKED_NEAR_MISS_MIN_WORDS}–249 words", prompt)
        self.assertIn("return INSUFFICIENT_CONFIDENCE", prompt)
        self.assertIn("Do not pad", prompt)

    def test_source_backed_near_short_hint_requires_250_words_and_three_blocks(self):
        rich_packet = _source_packet(252, blocks=3)
        rich_packet["story_confidence"] = 0.9
        too_few_words = _source_packet(249, blocks=3)
        too_few_words["story_confidence"] = 0.9
        too_few_blocks = _source_packet(320, blocks=2)
        too_few_blocks["story_confidence"] = 0.9

        self.assertIn("Source-backed near-short rule", _build_prompt(rich_packet))
        self.assertIn("compact 250-320 word article", _build_prompt(rich_packet))
        self.assertNotIn("Source-backed near-short rule", _build_prompt(too_few_words))
        self.assertNotIn("Source-backed near-short rule", _build_prompt(too_few_blocks))

    def test_near_short_repair_prompt_uses_source_backed_rules_for_200_word_marker(self):
        packet = _source_packet(252, blocks=3)
        packet["story_confidence"] = 0.98
        broken_payload = json.loads(_good_payload())
        broken_payload["content"] = " ".join(["Sana"] * 248)

        prompt = _build_repair_prompt(packet, broken_payload, [
            "content too short: 248 words",
            "source_backed_writer_shortfall: final expansion required",
        ])

        self.assertIn("Source-backed repair mode", prompt)
        self.assertIn("source_words: 252", prompt)
        self.assertIn("source_blocks: 3", prompt)
        self.assertIn("MUST be at least 250 Finnish words", prompt)
        self.assertIn(f"Do not stop at {SOURCE_BACKED_NEAR_MISS_MIN_WORDS}–249 words", prompt)

    def test_source_backed_near_miss_requires_source_confidence_and_200_249_words(self):
        packet = _source_packet(252, blocks=3)
        packet["story_confidence"] = 0.85
        payload = json.loads(_good_payload())
        payload["content"] = " ".join(["Sana"] * 211)

        self.assertTrue(_is_source_backed_near_miss(packet, payload, ["content too short: 211 words"]))
        payload["content"] = " ".join(["Sana"] * 209)
        self.assertTrue(_is_source_backed_near_miss(packet, payload, ["content too short: 209 words"]))
        payload["content"] = " ".join(["Sana"] * 199)
        self.assertFalse(_is_source_backed_near_miss(packet, payload, ["content too short: 199 words"]))
        payload["content"] = " ".join(["Sana"] * 250)
        self.assertFalse(_is_source_backed_near_miss(packet, payload, []))
        payload["content"] = " ".join(["Sana"] * 29) + "\n\n" + " ".join(["Sana"] * 221)
        self.assertTrue(_is_source_backed_near_miss(packet, payload, ["lead paragraph too short: 29 words"]))
        payload["content"] = " ".join(["Sana"] * 29) + "\n\n" + " ".join(["Sana"] * (MIN_CONTENT_WORDS - 80))
        self.assertFalse(_is_source_backed_near_miss(packet, payload, ["lead paragraph too short: 29 words"]))
        payload["content"] = " ".join(["Sana"] * 247)
        reduced_floor_packet = _source_packet(252, blocks=3)
        reduced_floor_packet["story_confidence"] = 0.85
        self.assertTrue(_is_source_backed_near_miss(reduced_floor_packet, payload, ["content too short: 247 words"]))
        below_floor_packet = _source_packet(249, blocks=3)
        below_floor_packet["story_confidence"] = 0.85
        self.assertFalse(_is_source_backed_near_miss(below_floor_packet, payload, ["content too short: 247 words"]))
        self.assertFalse(_is_source_backed_near_miss(_source_packet(260, blocks=2), payload, ["content too short: 247 words"]))
        low_confidence = _source_packet(360, blocks=3)
        low_confidence["story_confidence"] = 0.84
        self.assertFalse(_is_source_backed_near_miss(low_confidence, payload, ["content too short: 247 words"]))

        for category in ("Teknologia", "Kotimaa", "Ulkomaat"):
            packet = _source_packet(252, blocks=3)
            packet["category"] = category
            packet["story_confidence"] = 0.9
            self.assertTrue(_is_source_backed_near_miss(packet, payload, ["content too short: 247 words"]))

    def test_source_word_count_uses_text_when_declared_block_word_count_is_low(self):
        packet = {
            "clean_source_blocks": [
                {"text": " ".join(["sana"] * 90), "word_count": 50},
                {"text": " ".join(["sana"] * 80), "word_count": 40},
            ],
            "source_text": " ".join(["sana"] * 500),
        }

        self.assertEqual(_packet_source_words(packet), 170)

    def test_talous_micro_near_miss_uses_three_blocks_and_high_confidence(self):
        packet = _source_packet(252, blocks=3)
        packet["category"] = "Talous"
        packet["story_confidence"] = 0.98
        payload = json.loads(_good_payload())
        payload["content"] = " ".join(["Sana"] * 209)

        self.assertTrue(_is_source_backed_talous_micro_near_miss(packet, payload, ["content too short: 209 words"]))
        self.assertTrue(_is_source_backed_near_miss(packet, payload, ["content too short: 209 words"]))
        self.assertTrue(_is_source_backed_repair_candidate(packet, ["content too short: 209 words"]))

        not_talous = dict(packet, category="Kotimaa")
        self.assertFalse(_is_source_backed_talous_micro_near_miss(not_talous, payload, ["content too short: 209 words"]))
        two_blocks = _source_packet(252, blocks=2)
        two_blocks["category"] = "Talous"
        two_blocks["story_confidence"] = 0.98
        self.assertFalse(_is_source_backed_talous_micro_near_miss(two_blocks, payload, ["content too short: 209 words"]))
        low_confidence = _source_packet(252, blocks=3)
        low_confidence["category"] = "Talous"
        low_confidence["story_confidence"] = 0.84
        self.assertFalse(_is_source_backed_talous_micro_near_miss(low_confidence, payload, ["content too short: 209 words"]))

    def test_talous_micro_near_short_repair_prompt_uses_source_backed_rules(self):
        packet = _source_packet(252, blocks=3)
        packet["category"] = "Talous"
        packet["story_confidence"] = 0.98
        broken_payload = json.loads(_good_payload())
        broken_payload["content"] = " ".join(["Sana"] * 225)

        prompt = _build_repair_prompt(packet, broken_payload, ["source_backed_writer_shortfall: final expansion required"])

        self.assertIn("Source-backed repair mode", prompt)
        self.assertIn("Talous only", prompt)
        self.assertIn("source_words: 252", prompt)


    def test_packet_story_confidence_prefers_story_confidence_over_payload_confidence(self):
        packet = {"story_confidence": 0.91, "confidence": 0.2}
        self.assertEqual(_packet_story_confidence(packet), 0.91)
        self.assertEqual(_packet_story_confidence({"confidence": 0.86}), 0.86)


    def test_near_miss_repair_metadata_records_recovered_runtime_proof(self):
        packet = _source_packet(252, blocks=3)
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
        self.assertGreaterEqual(metadata["selected_source_words_at_repair"], 250)
        self.assertGreaterEqual(metadata["selected_source_blocks_at_repair"], 3)
        self.assertGreaterEqual(metadata["source_words"], 250)
        self.assertGreaterEqual(metadata["source_blocks"], 3)
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
            {"text": " ".join(["Hallitus valmistelee säästöjä sosiaalihuoltoon ensi vuodelle"] * 20), "word_count": 120, "source": "Testi", "source_url": "https://testi.example/1", "source_domain": "testi.example"},
            {"text": " ".join(["Hallitus valmistelee säästöjä sosiaalihuoltoon ensi vuodelle"] * 15), "word_count": 90, "source": "Testi 2", "source_url": "https://testi.example/2", "source_domain": "testi.example"},
            {"text": " ".join(["Hallitus valmistelee säästöjä sosiaalihuoltoon ensi vuodelle"] * 12), "word_count": 72, "source": "Testi 3", "source_url": "https://testi.example/3", "source_domain": "testi.example"},
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
        packet = _source_packet(252, blocks=3)
        packet["story_confidence"] = 0.9

        run_mock.side_effect = [
            self._result(json.dumps(near_miss_payload, ensure_ascii=False)),
            self._result(json.dumps(near_miss_payload, ensure_ascii=False)),
            self._result(json.dumps(near_miss_payload, ensure_ascii=False)),
            self._result(json.dumps(near_miss_payload, ensure_ascii=False)),
        ]

        with patch(f"{rewrite_articles.__module__}.build_story_packet", return_value=packet), \
             patch(f"{rewrite_articles.__module__}.save_writer_quarantine") as quarantine_mock:
            rewritten = rewrite_articles([dict(SAMPLE_ARTICLE)])

        self.assertEqual(rewritten, [])
        self.assertEqual(run_mock.call_count, 4)
        self.assertTrue(quarantine_mock.called)
        self.assertEqual(quarantine_mock.call_args.args[1], "source_backed_writer_shortfall_unrepairable")
        extra = quarantine_mock.call_args.kwargs["extra"]
        self.assertEqual(extra["reason_code"], "source_backed_writer_shortfall_unrepairable")
        self.assertEqual(extra["final_word_count"], 247)
        self.assertEqual(extra["final_lead_word_count"], 247)
        self.assertGreaterEqual(extra["source_words"], 250)
        self.assertGreaterEqual(extra["source_blocks"], 3)

    @patch(PATCH_TARGET)
    def test_rewrite_articles_quarantines_still_short_after_near_floor_repair(self, run_mock):
        initial_payload = json.loads(_good_payload())
        initial_payload["content"] = " ".join(["Sana"] * 244)
        still_short_payload = json.loads(_good_payload())
        still_short_payload["content"] = " ".join(["Sana"] * 231)
        packet = _source_packet(252, blocks=3)
        packet["story_confidence"] = 0.98
        packet["category"] = "Talous"

        run_mock.side_effect = [
            self._result(json.dumps(initial_payload, ensure_ascii=False)),
            self._result(json.dumps(still_short_payload, ensure_ascii=False)),
            self._result(json.dumps(still_short_payload, ensure_ascii=False)),
            self._result(json.dumps(still_short_payload, ensure_ascii=False)),
        ]

        with patch(f"{rewrite_articles.__module__}.build_story_packet", return_value=packet), \
             patch(f"{rewrite_articles.__module__}.save_writer_quarantine") as quarantine_mock:
            rewritten = rewrite_articles([dict(SAMPLE_ARTICLE)])

        self.assertEqual(rewritten, [])
        self.assertEqual(run_mock.call_count, 4)
        self.assertTrue(quarantine_mock.called)
        self.assertEqual(quarantine_mock.call_args.args[1], "source_backed_writer_shortfall_unrepairable")
        extra = quarantine_mock.call_args.kwargs["extra"]
        self.assertEqual(extra["reason_code"], "source_backed_writer_shortfall_unrepairable")
        self.assertEqual(extra["source_words"], 252)
        self.assertEqual(extra["source_blocks"], 3)
        self.assertEqual(extra["final_word_count"], 231)
        self.assertEqual(extra["repair_result"], "still_short")

    @patch(PATCH_TARGET)
    def test_rewrite_articles_retries_talous_zero_word_near_miss_repair(self, run_mock):
        near_miss_payload = json.loads(_good_payload())
        near_miss_payload["category"] = "Talous"
        near_miss_payload["content"] = " ".join(["Sana"] * 244)
        repaired_payload = json.loads(_good_payload())
        repaired_payload["category"] = "Talous"
        repaired_payload["content"] = _long_content()
        packet = _source_packet(252, blocks=3)
        packet["story_confidence"] = 0.98
        packet["category"] = "Talous"

        run_mock.side_effect = [
            self._result(json.dumps(near_miss_payload, ensure_ascii=False)),
            self._result(json.dumps(near_miss_payload, ensure_ascii=False)),
            self._result(json.dumps(near_miss_payload, ensure_ascii=False)),
            self._result(json.dumps(repaired_payload, ensure_ascii=False)),
        ]

        with patch(f"{rewrite_articles.__module__}.build_story_packet", return_value=packet):
            rewritten = rewrite_articles([dict(SAMPLE_ARTICLE, category_hint="Talous")])

        self.assertEqual(len(rewritten), 1)
        self.assertEqual(run_mock.call_count, 4)
        retry_prompt = run_mock.call_args_list[3].args[0][-1]
        self.assertIn("source_backed_talous_zero_word_retry", retry_prompt)
        self.assertEqual(rewritten[0]["category"], "Talous")
        self.assertEqual(rewritten[0]["monica_repair"]["repair_retry"], "talous_zero_word_short_retry")
        self.assertEqual(rewritten[0]["monica_repair"]["pre_repair_word_count"], 244)
        self.assertGreaterEqual(rewritten[0]["monica_repair"]["post_repair_word_count"], MIN_CONTENT_WORDS)
        self.assertEqual(rewritten[0]["monica_repair"]["repair_result"], "published")

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
