#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from monica_writer import _extract_json_object, rewrite_articles


SAMPLE_ARTICLE = {
    "title": "Hallitus valmistelee uusia säästöjä",
    "description": "Hallitus valmistelee uusia sosiaalihuollon säästöjä ja esittää niiden tulevan voimaan ensi vuonna.",
    "link": "https://example.com/story",
    "category_hint": "Kotimaa",
    "research": "[Lähde: Yle]\nHallitus valmistelee uusia sosiaalihuollon säästöjä. Päätöksiä valmistellaan ensi vuodelle ja vaikutukset kohdistuvat useisiin palveluihin.\n\n---\n\n[Lähde: BBC]\nThe government is preparing new savings measures for social care. Ministers say the final package is still under preparation.",
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

    def test_extract_json_object_skips_noisy_braces_before_payload(self):
        raw = 'openclaw: dispatch {agent=monica}\nnot json {oops}\n' + _good_payload() + '\n[done]'

        payload = _extract_json_object(raw)

        self.assertEqual(payload["category"], "Kotimaa")
        self.assertIn("Hallitus valmistelee", payload["title"])

    def test_extract_json_object_accepts_fenced_payload_with_commentary(self):
        raw = "Valmis:\n```JSON\n" + _good_payload() + "\n```\nTarkistettu."

        payload = _extract_json_object(raw)

        self.assertEqual(payload["content_type"], "article")

    @patch("subprocess.run")
    def test_rewrite_articles_valid_output(self, run_mock):
        run_mock.return_value = self._result(_good_payload())

        rewritten = rewrite_articles([dict(SAMPLE_ARTICLE)])
        self.assertEqual(len(rewritten), 1)
        article = rewritten[0]
        self.assertEqual(article["writer_backend"], "monica")
        self.assertEqual(article["category"], "Kotimaa")
        self.assertGreaterEqual(len(article["key_points"]), 2)
        self.assertIn("Hallitus valmistelee", article["content"])

    @patch("subprocess.run")
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

    @patch("subprocess.run")
    def test_rewrite_articles_quarantines_insufficient_confidence(self, run_mock):
        run_mock.return_value = self._result(json.dumps({"packet_id": "abc", "status": "INSUFFICIENT_CONFIDENCE", "reason": "source too thin"}))

        rewritten = rewrite_articles([dict(SAMPLE_ARTICLE)])
        self.assertEqual(rewritten, [])
        quarantine_dir = os.path.join(self.tmpdir.name, "quarantine")
        self.assertTrue(os.path.isdir(quarantine_dir))
        self.assertTrue(any(name.endswith(".json") for name in os.listdir(quarantine_dir)))

    @patch("subprocess.run")
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

    @patch("subprocess.run")
    def test_rewrite_articles_resets_local_session_on_context_overflow(self, run_mock):
        run_mock.side_effect = [
            self._result("Context overflow: prompt too large for the model. Try /reset (or /new) to start a fresh session."),
            self._result("reset ok"),
            self._result(_good_payload()),
        ]

        rewritten = rewrite_articles([dict(SAMPLE_ARTICLE)])

        self.assertEqual(len(rewritten), 1)
        self.assertEqual(run_mock.call_count, 3)
        reset_cmd = run_mock.call_args_list[1].args[0]
        self.assertIn("/reset", reset_cmd)

    @patch("subprocess.run")
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
