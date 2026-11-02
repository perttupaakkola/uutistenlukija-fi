import copy
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from news_mvp import earnings, weekly_economy
from news_mvp.authorization import proposed_policy_v2


ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures" / "weekly"
EARNINGS_FIXTURES = ROOT / "fixtures" / "earnings"
NOW = datetime(2026, 11, 2, 16, tzinfo=timezone.utc)


def fixture(name, binary=False):
    path = FIXTURES / name
    return path.read_bytes() if binary else path.read_text(encoding="utf-8")


def earnings_result(company, title, source, baseline, url, published_at):
    text = (EARNINGS_FIXTURES / source).read_text(encoding="utf-8")
    report = earnings.extract_report(text, company, title, published_at)
    article_text = (f"{company} julkaisi tuloksensa. Liikevaihdon ja liiketuloksen "
                    "suunta perustuu yhtiön pörssitiedotteen vertailulukuihin. " + text[:500])
    return weekly_economy.result_summary(report, baseline, title, url,
                                         article_text, published_at)


def four_results():
    return [
        earnings_result("YIT", "YIT:n osavuosikatsaus tammi-syyskuu 2026",
                        "yit-q3-2026.txt", {"available": True,
                         "operating_profit": {"expected": "24.8", "deviation_percent": "20.8"},
                         "comparison": "yläpuolella"},
                        "https://uutistenlukija.fi/uutiset/yit-tulos-a1b2c3d4e5f6/",
                        "2026-10-30T06:30:00+00:00"),
        earnings_result("Stora Enso", "Stora Enson osavuosikatsaus tammi–syyskuulta 2026",
                        "stora-enso-q3-2026.txt", {"available": True,
                         "operating_profit": {"expected": "142.4", "deviation_percent": "13.1"},
                         "comparison": "yläpuolella"},
                        "https://uutistenlukija.fi/uutiset/stora-enso-tulos-b1b2c3d4e5f6/",
                        "2026-10-30T06:00:00+00:00"),
        earnings_result("Aktia", "Aktia Pankki Oyj:n osavuosikatsaus 1.1.–30.9.2026",
                        "aktia-q3-2026.txt", {"available": False},
                        "https://uutistenlukija.fi/uutiset/aktia-tulos-c1b2c3d4e5f6/",
                        "2026-10-29T06:00:00+00:00"),
        earnings_result("Huhtamäki", "Huhtamäki Oyj:n puolivuosikatsaus 1.1.–30.6.2026",
                        "huhtamaki-q2-2026.txt", {"available": True,
                         "operating_profit": {"expected": "100.3", "deviation_percent": "3.4"},
                         "comparison": "yläpuolella"},
                        "https://uutistenlukija.fi/uutiset/huhtamaki-tulos-d1b2c3d4e5f6/",
                        "2026-10-26T06:00:00+00:00"),
    ]


class WeeklyEconomyTests(unittest.TestCase):
    def decision(self):
        url = ("https://www.ecb.europa.eu/press/pr/date/2026/html/"
               "ecb.mp261029~9a493adf17.fi.html")
        raw = fixture("ecb-decision-2026-10-29.html", binary=True)
        return {"data": weekly_economy.parse_ecb_decision(raw, "2026-10-29", url),
                "url": url, "published_at": "2026-10-29T12:15:00+00:00",
                "text": weekly_economy.visible_text(raw)}

    def fed_decision(self):
        url = ("https://www.federalreserve.gov/newsevents/pressreleases/"
               "monetary20261028a.htm")
        raw = fixture("fed-decision-2026-10-28.html", binary=True)
        return {"data": weekly_economy.parse_central_bank_decision(
                    raw, "Yhdysvaltain keskuspankki", "2026-10-28", url),
                "url": url, "title": "Federal Reserve issues FOMC statement",
                "published_at": "2026-10-28T18:00:00+00:00",
                "text": weekly_economy.visible_text(raw)}

    def packet(self):
        return weekly_economy.build_packet(
            "2026-10-30", fixture("ecb-fx-2026-10.xml", binary=True),
            decisions=[self.decision(), self.fed_decision()],
            statistics_raw=fixture("stat-publications-2026-10.json"),
            results=four_results(),
            company_feeds={"cision": (ROOT.parent / "tests" / "fixtures" / "earnings" / "cision.xml").read_bytes()},
            statistics_calendar_raw=fixture("stat-calendar-2026-11.json"), now=NOW)

    def test_results_from_outside_the_week_are_dropped(self):
        old = four_results()
        old[3]["published_at"] = "2026-07-24T06:00:00+00:00"
        packet = weekly_economy.build_packet(
            "2026-10-30", fixture("ecb-fx-2026-10.xml", binary=True),
            decisions=[self.decision()], statistics_raw=fixture("stat-publications-2026-10.json"),
            results=old, now=NOW)
        text = str(packet)
        self.assertNotIn("huhtamaki-tulos", text)
        self.assertIn("yit-tulos", text)

    def test_fx_friday_math_from_real_ecb_rates(self):
        rows = weekly_economy.parse_fx(
            fixture("ecb-fx-2026-10.xml", binary=True), "2026-10-30")
        self.assertEqual([(row["currency"], row["change_percent"], row["direction"])
                          for row in rows],
                         [("USD", "-0.2", "heikkeni"), ("SEK", "-1.4", "heikkeni"),
                          ("GBP", "-0.4", "heikkeni"), ("NOK", "-1.5", "heikkeni")])

    def test_real_ecb_decision_and_statistics_are_parsed(self):
        decision = self.decision()["data"]
        self.assertEqual(decision["new_rate"], "2.50")
        self.assertEqual(decision["rates"]["maksuvalmiusluoton korko"], "2.90")
        self.assertIn("Energian hinnat", decision["reason"])
        rows = weekly_economy.parse_statistics_finland(
            fixture("stat-publications-2026-10.json"), date(2026, 10, 26), date(2026, 10, 30))
        self.assertEqual([row["date"] for row in rows], ["2026-10-27", "2026-10-30"])
        self.assertIn("-9,7", rows[0]["headline"])

    def test_real_federal_reserve_decision_and_official_feed_are_parsed(self):
        source = weekly_economy.policy()["central_bank_decisions"][
            "Yhdysvaltain keskuspankki"]
        links = weekly_economy.central_bank_decision_links(
            fixture("fed-monetary-2026.xml", binary=True),
            date(2026, 10, 26), date(2026, 10, 30), source)
        self.assertEqual(links, [("2026-10-28",
            "https://www.federalreserve.gov/newsevents/pressreleases/"
            "monetary20261028a.htm")])
        decision = self.fed_decision()["data"]
        self.assertEqual(decision["new_rate"], "3.75–4.00")
        self.assertIn("Economic activity", decision["reason"])

    def test_company_and_statistics_calendars(self):
        rows = weekly_economy.parse_company_calendar(
            {"cision": (ROOT.parent / "tests" / "fixtures" / "earnings" / "cision.xml").read_bytes()},
            date(2026, 11, 2), date(2026, 11, 8), ["Teleste"])
        self.assertEqual([(row["date"], row["title"]) for row in rows],
                         [("2026-11-06", "Teleste tulosjulkistus")])
        stats = weekly_economy.parse_statistics_calendar(
            fixture("stat-calendar-2026-11.json"), date(2026, 11, 2), date(2026, 11, 8))
        self.assertEqual([row["date"] for row in stats], ["2026-11-04"])

    def test_friday_discovery_and_cap_identity(self):
        before = datetime(2026, 10, 30, 13, 59, tzinfo=timezone.utc)  # 15.59 Helsinki
        due = datetime(2026, 10, 30, 14, 0, tzinfo=timezone.utc)
        self.assertEqual(weekly_economy.discover({}, before), [])
        rows = weekly_economy.discover({}, due)
        self.assertEqual(rows[0]["story_key"], "weekly-economy:2026-10-30")
        self.assertEqual(weekly_economy.discover({}, due, {rows[0]["story_key"]}), [])

    def test_skip_rule_requires_three_real_sections(self):
        with self.assertRaisesRegex(ValueError, "fewer than three"):
            weekly_economy.build_packet(
                "2026-10-30", fixture("ecb-fx-2026-10.xml", binary=True), now=NOW)

    def test_figure_check_rejects_wrong_number_and_missing_meta_sentence(self):
        packet = self.packet()
        draft = {"title": "Talous tällä viikolla: euro heikkeni ja korot pysyivät",
                 "summary": "Euro heikkeni dollariin nähden 0,2 %.", "category": "Talous",
                 "paragraphs": [
                     {"text": "EKP piti talletuskoron 2,50 prosentissa.", "source_ids": ["B"]},
                     {"text": "Kuluttajien luottamusindikaattori oli -9,7.", "source_ids": ["D"]}]}
        self.assertTrue(weekly_economy.figure_check(draft, packet))
        wrong = copy.deepcopy(draft)
        wrong["paragraphs"][0]["text"] = "EKP piti talletuskoron 9,99 prosentissa."
        with self.assertRaisesRegex(ValueError, "absent"):
            weekly_economy.figure_check(wrong, packet)
        meta = copy.deepcopy(draft)
        meta["paragraphs"].append({"text": "Trendiodotusta ei näytetä, koska tietoja puuttuu.",
                                   "source_ids": ["D"]})
        with self.assertRaisesRegex(ValueError, "must be omitted"):
            weekly_economy.figure_check(meta, packet)

    def test_packet_has_real_sections_and_registered_policy(self):
        packet = self.packet()
        weekly = packet["weekly_economy"]
        self.assertEqual(len(weekly["results"]), 4)
        self.assertEqual([row["bank"] for row in weekly["central_banks"]],
                         ["Euroopan keskuspankki", "Yhdysvaltain keskuspankki"])
        self.assertGreaterEqual(sum(bool(weekly[key]) for key in
                                    ("fx", "central_banks", "statistics_finland",
                                     "results", "next_week")), 3)
        authorization = proposed_policy_v2()
        self.assertIn("weekly-economy", authorization["source_families"])
        self.assertEqual(authorization["weekly_economy_policy_sha256"],
                         weekly_economy.policy_digest())
        self.assertEqual(authorization["max_weekly_economy_per_week"], 1)

    def test_release_contract_runs_weekly_figure_gate(self):
        from news_mvp.release_contract import media
        packet = self.packet()
        # A public packet always has captured upstream bytes. The fixture builder
        # receives a small representative capture to exercise that binding here.
        packet["publication_basis"]["capture_sha256"] = {
            "fixture": "a" * 64}
        draft = {"title": "Talous tällä viikolla: euro heikkeni",
                 "summary": "Euro heikkeni dollariin nähden 0,2 %.",
                 "category": "Talous", "image": None,
                 "paragraphs": [
                     {"text": "EKP piti talletuskoron 2,50 prosentissa.",
                      "source_ids": ["B"]},
                     {"text": "Kuluttajien luottamusindikaattori oli -9,7.",
                      "source_ids": ["D"]}]}
        binding = media(packet, draft)
        self.assertEqual(binding["text_only"]["policy"], "weekly-economy-text-v1")

    def test_own_results_url_is_rendered_as_a_real_link(self):
        from news_mvp.site import _paragraph_text_html
        url = "https://uutistenlukija.fi/uutiset/yit-tulos-a1b2c3d4e5f6/"
        paragraph = {"text": "YIT:n tulosjuttu: " + url, "source_ids": ["D"]}
        rendered = _paragraph_text_html("/uutiset/weekly/", paragraph, [
            {"id": "D", "publisher": "Uutistenlukija", "url": url}])
        self.assertEqual(rendered.count('<a href="' + url + '">'), 1)


if __name__ == "__main__":
    unittest.main()
