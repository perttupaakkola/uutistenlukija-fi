import json
import tempfile
import unittest
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from unittest.mock import patch

from news_mvp import earnings, site
from news_mvp.authorization import proposed_policy_v2


ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures" / "earnings"
NOW = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def report(company, title, name):
    return earnings.extract_report(fixture(name), company, title,
                                   "2026-10-30T06:30:00+00:00")


class EarningsExtractionTests(unittest.TestCase):
    def test_yit_exact_quarter_figures_and_outlook(self):
        value = report("YIT", "YIT:n osavuosikatsaus tammi-syyskuu 2026",
                       "yit-q3-2026.txt")
        self.assertEqual(value["figures"]["revenue"]["value"], "530")
        self.assertEqual(value["figures"]["revenue"]["comparison"], "466")
        self.assertEqual(value["figures"]["revenue"]["change_percent"], "14")
        self.assertEqual(value["figures"]["operating_profit"]["value"], "30")
        self.assertEqual(value["figures"]["operating_profit"]["comparison"], "24")
        self.assertEqual(value["figures"]["operating_profit"]["change_percent"], "26")
        self.assertEqual((value["figures"]["reported_operating_profit"]["value"],
                          value["figures"]["reported_operating_profit"]["comparison"]),
                         ("9", "25"))
        self.assertEqual(value["operating_profit_divergence"]["difference_percent"],
                         "70.0")
        self.assertIn("Tripla Mall Ky:n -19 miljoonan euron käyvän arvon muutos",
                      value["operating_profit_divergence"]["reason"])
        self.assertEqual(value["figures"]["eps"]["value"], "-0.03")
        self.assertEqual(value["figures"]["eps"]["comparison"], "0.00")
        self.assertTrue(value["outlook"]["changed"])
        self.assertEqual(value["ytd_operating_profit"], "60")
        self.assertEqual(earnings.guidance_check(value)["available"], False)

    def test_stora_enso_exact_quarter_figures(self):
        value = report("Stora Enso",
                       "Stora Enson osavuosikatsaus tammi–syyskuulta 2026",
                       "stora-enso-q3-2026.txt")
        figures = value["figures"]
        self.assertEqual((figures["revenue"]["value"],
                          figures["revenue"]["comparison"],
                          figures["revenue"]["change_percent"]),
                         ("2240", "2283", "-2"))
        self.assertEqual((figures["operating_profit"]["value"],
                          figures["operating_profit"]["comparison"],
                          figures["operating_profit"]["change_percent"]),
                         ("161", "126", "28"))
        self.assertEqual((figures["reported_operating_profit"]["value"],
                          figures["reported_operating_profit"]["comparison"]),
                         ("47", "231"))
        self.assertIn("arvonalentumisiin, uudelleenjärjestelyihin ja luovutuksiin",
                      value["operating_profit_divergence"]["reason"])
        self.assertIn("biologisten hyödykkeiden käyvän arvon muutoksiin",
                      value["operating_profit_divergence"]["reason"])
        self.assertEqual((figures["eps"]["value"], figures["eps"]["comparison"],
                          figures["eps"]["change_percent"]),
                         ("0.01", "0.25", "-95.1"))

    def test_financial_company_metrics_and_optional_outlook(self):
        aktia = report("Aktia", "Aktia Pankki Oyj:n osavuosikatsaus 1.1.–30.9.2026",
                       "aktia-q3-2026.txt")
        self.assertEqual(aktia["figures"]["revenue"]["label"],
                         "liiketoiminnan tuotot yhteensä")
        self.assertEqual((aktia["figures"]["revenue"]["value"],
                          aktia["figures"]["operating_profit"]["value"]),
                         ("70.4", "22.5"))
        self.assertEqual((aktia["figures"]["reported_operating_profit"]["value"],
                          aktia["figures"]["reported_operating_profit"]["comparison"]),
                         ("18.0", "25.3"))
        gofore = report(
            "Gofore",
            "Goforen tammi-syyskuun 2026 osavuosikatsaus: Liikevaihto kasvoi 19,7 % Q3:lla",
            "gofore-q3-2026.txt")
        self.assertIsNone(gofore["outlook"])

    def test_bank_and_insurer_lead_metrics_have_finnish_labels(self):
        cases = [
            ("Nordea", "Nordean tulos – puolivuosikatsaus 2026",
             "nordea-q2-2026.txt", "tuotot yhteensä", "liikevoitto", "3032", "1608"),
            ("Mandatum", "Mandatum Oyj:n puolivuosikatsaus 1.1.–30.6.2026",
             "mandatum-q2-2026.txt", "palkkiotulos",
             "pääomakevyen liiketoiminnan tulos ennen veroja", "22.4", "27.1"),
            ("Sampo", "Sampo Group Interim Statement for January–September 2025",
             "sampo-q3-2025.txt", "vakuutusliikevaihto", "vakuutustulos", "2303", "392"),
        ]
        for company, title, name, top_label, profit_label, top, profit in cases:
            with self.subTest(company=company):
                value = report(company, title, name)
                self.assertEqual((value["figures"]["revenue"]["label"],
                                  value["figures"]["operating_profit"]["label"]),
                                 (top_label, profit_label))
                self.assertEqual((value["figures"]["revenue"]["value"],
                                  value["figures"]["operating_profit"]["value"]),
                                 (top, profit))

    def test_eps_is_optional_for_history_and_article(self):
        text = fixture("nordea-q2-2026.txt").replace(
            "Laimennettu osakekohtainen tulos, euroa\n0,36\n0,35\n", "")
        value = earnings.extract_report(text, "Nordea",
                                        "Nordean tulos – puolivuosikatsaus 2026",
                                        "2026-07-16T05:00:00+00:00")
        self.assertNotIn("eps", value["figures"])

    def test_gofore_page_figures_are_exact_even_though_outlook_gate_skips_it(self):
        figures = earnings.extract_figures(fixture("gofore-q3-2026.txt"))
        self.assertEqual((figures["revenue"]["value"],
                          figures["revenue"]["comparison"]), ("49.3", "41.2"))
        self.assertEqual((figures["operating_profit"]["value"],
                          figures["operating_profit"]["comparison"]), ("4.4", "3.6"))
        self.assertEqual((figures["eps"]["value"], figures["eps"]["comparison"]),
                         ("0.24", "0.10"))

    def test_conflicting_core_rows_are_ambiguous(self):
        text = fixture("yit-q3-2026.txt").replace(
            "Oikaistu liikevoitto nousi 30 miljoonaan euroon (24).",
            "Oikaistu liikevoitto nousi 30 miljoonaan euroon (24).\n"
            "Oikaistu liikevoitto nousi 31 miljoonaan euroon (24).", 1)
        with self.assertRaisesRegex(ValueError, "Ambiguous core figure"):
            earnings.extract_report(text, "YIT",
                                    "YIT:n osavuosikatsaus tammi-syyskuu 2026",
                                    "2026-10-30T06:30:00+00:00")

    def test_sharp_gap_without_company_stated_reason_is_rejected(self):
        text = fixture("yit-q3-2026.txt").replace(
            " Liikevoittoon vaikutti pääosin Tripla Mall Ky:n -19 miljoonan "
            "euron käyvän arvon muutos.", "")
        with self.assertRaisesRegex(ValueError, "company-stated reason"):
            earnings.extract_report(text, "YIT",
                                    "YIT:n osavuosikatsaus tammi-syyskuu 2026",
                                    "2026-10-30T06:30:00+00:00")

    def test_reported_result_is_extracted_but_small_gap_needs_no_reason(self):
        value = report("Huhtamäki",
                       "Huhtamäki Oyj:n puolivuosikatsaus 1.1.–30.6.2026",
                       "huhtamaki-q2-2026.txt")
        self.assertEqual((value["figures"]["operating_profit"]["value"],
                          value["figures"]["reported_operating_profit"]["value"],
                          value["figures"]["reported_operating_profit"]["comparison"]),
                         ("103.7", "74.2", "46.2"))
        self.assertNotIn("operating_profit_divergence", value)


class EarningsDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.feeds = {
            "sttinfo": (ROOT.parent / "tests" / "fixtures" / "earnings" / "stt_ann.xml").read_bytes(),
            "cision": (ROOT.parent / "tests" / "fixtures" / "earnings" / "cision.xml").read_bytes(),
        }
        cls.decisions = earnings.feed_decisions(cls.feeds, NOW)

    def decision(self, prefix):
        return next(row for row in self.decisions if row["title"].startswith(prefix))

    def test_actual_reports_kept_and_rankable(self):
        self.assertTrue(self.decision("YIT:n osavuosikatsaus")["kept"])
        self.assertTrue(self.decision("Stora Enson osavuosikatsaus")["kept"])

    def test_invitation_correction_insider_and_old_corrected_item_rejected(self):
        self.assertIn("invitation", self.decision("Teleste: Osavuosikatsaus")["reason"])
        self.assertEqual(self.decision("Korjaus Aktia")["reason"], "correction")
        self.assertIn("correction exists", self.decision("Aktia Pankki Oyj:n osavuosikatsaus")["reason"])
        self.assertIn("insider", self.decision("Sisäpiiritieto: Raute")["reason"])
        self.assertIn("insider", self.decision("UPM-Kymmene Oyj: Johtohenkilöiden")["reason"])

    def test_discovery_fetches_both_feeds_and_ranks_eligible_reports(self):
        feeds = earnings.policy()["feeds"]

        def fetched(url, _hosts):
            provider = next(name for name, row in feeds.items() if row["url"] == url)
            return self.feeds[provider], "application/rss+xml", url

        with patch("news_mvp.earnings.fetch", side_effect=fetched):
            recipes = earnings.discover({}, NOW)
        self.assertEqual([row["company"] for row in recipes], ["Stora Enso", "YIT"])
        self.assertTrue(all(row["family"] == "earnings" for row in recipes))


class EarningsBaselineAndDraftTests(unittest.TestCase):
    def history_report(self, year, quarter, revenue, profit):
        month, day = ((3, 31), (6, 30), (9, 30), (12, 31))[quarter - 1]
        return {"company": "Example", "year": year, "quarter": quarter,
                "period": f"Q{quarter}/{year}",
                "period_end": f"{year}-{month:02d}-{day:02d}",
                "figures": {"revenue": {"value": str(revenue)},
                            "operating_profit": {"value": str(profit)},
                            "eps": {"value": "1"}}, "outlook": {"text": "ennallaan", "changed": False}}

    def test_trend_math_requires_four_quarters_and_labels_deviation(self):
        with tempfile.TemporaryDirectory() as directory:
            current = self.history_report(2026, 1, "121", "12.1")
            self.assertFalse(earnings.trend_baseline(directory, current)["available"])
            for quarter, revenue, profit in [(1, "100", "10"), (2, "110", "11"),
                                             (3, "121", "12.1"), (4, "133.1", "13.31")]:
                prior = self.history_report(2025, quarter, revenue, profit)
                earnings.store_report(directory, prior, f"https://example.com/{quarter}")
            baseline = earnings.trend_baseline(directory, current)
            self.assertTrue(baseline["available"])
            self.assertEqual(baseline["operating_profit"]["expected"], "11.0")
            self.assertEqual(baseline["operating_profit"]["deviation_percent"], "10.0")
            self.assertEqual(baseline["comparison"], "yläpuolella")
            self.assertIn("Uutistenlukijan laskeman", earnings.baseline_sentence(baseline))

    def test_trend_never_mixes_adjusted_and_reported_profit_series(self):
        with tempfile.TemporaryDirectory() as directory:
            current = self.history_report(2026, 1, "121", "12")
            current["figures"]["revenue"]["series"] = "liikevaihto"
            current["figures"]["operating_profit"]["series"] = "oikaistu liikevoitto"
            for quarter in range(1, 5):
                prior = self.history_report(2025, quarter, "100", "10")
                prior["figures"]["revenue"]["series"] = "liikevaihto"
                prior["figures"]["operating_profit"]["series"] = (
                    "liikevoitto" if quarter == 3 else "oikaistu liikevoitto")
                earnings.store_report(directory, prior,
                                      f"https://example.com/series/{quarter}")
            baseline = earnings.trend_baseline(directory, current)
            self.assertFalse(baseline["available"])
            self.assertIn("not mixed", baseline["reason"])

    def test_guidance_uses_q4_seasonality_instead_of_plain_annualising(self):
        with tempfile.TemporaryDirectory() as directory:
            for year in (2024, 2025):
                for quarter, profit in [(1, "10"), (2, "10"), (3, "10"), (4, "30")]:
                    earnings.store_report(directory,
                        self.history_report(year, quarter, "100", profit),
                        f"https://example.com/{year}/{quarter}")
            current = self.history_report(2026, 3, "400", "20")
            current["ytd_operating_profit"] = "45"
            current["outlook"]["text"] = (
                "Ohjeistus: oikaistun liikevoiton odotetaan olevan 85–95 miljoonaa euroa.")
            check = earnings.guidance_check(current, directory)
            self.assertEqual(check, {"available": True, "low": "85", "high": "95",
                "seasonally_estimated_full_year": "90.0", "q4_share": "50.0",
                "seasonal_years": [2025, 2024], "on_track": True,
                "position": "ohjeistushaarukassa"})
            self.assertNotEqual(check["seasonally_estimated_full_year"], "60.0")

    def test_guidance_omits_claim_without_full_year_or_with_unstable_share(self):
        current = self.history_report(2026, 3, "400", "20")
        current["ytd_operating_profit"] = "45"
        current["outlook"]["text"] = "Liikevoiton odotetaan olevan 85–95 miljoonaa euroa."
        with tempfile.TemporaryDirectory() as directory:
            self.assertIn("two complete", earnings.guidance_check(current, directory)["reason"])
            for year, values in [(2024, (10, 10, 10, 3)), (2025, (10, 10, 10, 30))]:
                for quarter, profit in enumerate(values, 1):
                    earnings.store_report(directory,
                        self.history_report(year, quarter, "100", str(profit)),
                        f"https://example.com/{year}/{quarter}")
            check = earnings.guidance_check(current, directory)
            self.assertFalse(check["available"])
            self.assertIn("unstable", check["reason"])

    def test_committed_seed_covers_allowlist_and_preserves_shortfall_reasons(self):
        seed = earnings.history_seed()
        allowed = {row["name"] for row in earnings.policy()["companies"]}
        self.assertEqual(set(seed["coverage"]), allowed)
        self.assertGreaterEqual(len(seed["reports"]), 40)
        self.assertGreaterEqual(sum(row["stored_quarters"] >= 4
                                    for row in seed["coverage"].values()), 18)
        for company, row in seed["coverage"].items():
            if row["stored_quarters"] < 4:
                self.assertTrue(row["short_reason"], company)
        self.assertGreaterEqual(seed["coverage"]["YIT"]["stored_quarters"], 6)
        self.assertGreaterEqual(seed["coverage"]["Stora Enso"]["stored_quarters"], 6)
        self.assertGreaterEqual(seed["coverage"]["Orion"]["stored_quarters"], 4)
        self.assertIn("PDF", seed["coverage"]["Sampo"]["short_reason"])

    def packet_and_draft(self):
        extracted = report("YIT", "YIT:n osavuosikatsaus tammi-syyskuu 2026",
                           "yit-q3-2026.txt")
        packet = {"kind": "earnings", "earnings": extracted,
                  "earnings_baseline": {"available": False},
                  "guidance_check": earnings.guidance_check(extracted),
                  "sources": [{"text": fixture("yit-q3-2026.txt")}]}
        draft = {"title": "YIT:n liikevaihto nousi 14 %", "summary": "Liikevaihto oli 530 miljoonaa euroa.",
                 "category": "Talous", "paragraphs": [
                     {"text": "Oikaistu liikevoitto oli 30 miljoonaa euroa.", "source_ids": ["A"]},
                     {"text": "Raportoitu liikevoitto laski 9 miljoonaan euroon 25 miljoonasta eurosta. Yhtiön mukaan tulosta heikensi pääosin Tripla Mall Ky:n -19 miljoonan euron käyvän arvon muutos.", "source_ids": ["A"]},
                     {"text": "Osakekohtainen tulos oli -0,03 euroa.", "source_ids": ["A"]}]}
        return packet, draft

    def test_figure_check_rejects_wrong_number_and_fake_consensus(self):
        packet, draft = self.packet_and_draft()
        self.assertTrue(earnings.figure_check(draft, packet))
        wrong = json.loads(json.dumps(draft))
        wrong["paragraphs"][0]["text"] = "Oikaistu liikevoitto oli 999 miljoonaa euroa."
        with self.assertRaisesRegex(ValueError, "absent"):
            earnings.figure_check(wrong, packet)
        consensus = {**draft, "summary": "Analyytikot odottivat 530 miljoonaa euroa."}
        with self.assertRaisesRegex(ValueError, "consensus"):
            earnings.figure_check(consensus, packet)
        typographic_minus = json.loads(json.dumps(draft))
        typographic_minus["paragraphs"][2]["text"] = "Osakekohtainen tulos oli –0,03 euroa."
        self.assertTrue(earnings.figure_check(typographic_minus, packet))
        missing_reported = json.loads(json.dumps(draft))
        missing_reported["paragraphs"].pop(1)
        with self.assertRaisesRegex(ValueError, "must report current and comparison"):
            earnings.figure_check(missing_reported, packet)
        missing_reason = json.loads(json.dumps(draft))
        missing_reason["paragraphs"][1]["text"] = (
            "Raportoitu liikevoitto laski 9 miljoonaan euroon 25 miljoonasta eurosta.")
        with self.assertRaisesRegex(ValueError, "company-stated reason"):
            earnings.figure_check(missing_reason, packet)

    def test_unavailable_calculation_meta_sentence_is_rejected(self):
        packet, draft = self.packet_and_draft()
        draft["paragraphs"].append({
            "text": "Kausivaihteluun perustuvaa ohjeistusvertailua ei näytetä, "
                    "koska kahta täyttä vertailuvuotta ei ole.",
            "source_ids": ["A"]})
        with self.assertRaisesRegex(ValueError, "must be omitted"):
            earnings.figure_check(draft, packet)

    def test_small_percentage_title_uses_prosentilla(self):
        extracted = report("Huhtamäki",
                           "Huhtamäki Oyj:n puolivuosikatsaus 1.1.–30.6.2026",
                           "huhtamaki-q2-2026.txt")
        packet = {"kind": "earnings", "earnings": extracted,
                  "earnings_baseline": {"available": False},
                  "guidance_check": {"available": False},
                  "sources": [{"text": fixture("huhtamaki-q2-2026.txt")}]}
        draft = {"title": "Huhtamäen oikaistu liikevoitto nousi 1 prosentilla",
                 "summary": "Liikevoitto kasvoi hieman.", "category": "Talous",
                 "paragraphs": [{"text": (
                     "Oikaistu liikevoitto oli 103,7 miljoonaa euroa, kun se oli "
                     "103,1 miljoonaa euroa. Raportoitu liikevoitto oli 74,2 miljoonaa "
                     "euroa, kun se oli 46,2 miljoonaa euroa."), "source_ids": ["A"]}]}
        self.assertTrue(earnings.figure_check(draft, packet))
        draft["title"] = "Huhtamäen oikaistu liikevoitto nousi 1 prosentin"
        with self.assertRaisesRegex(ValueError, "prosentilla"):
            earnings.figure_check(draft, packet)

    def test_all_four_committed_examples_pass_figure_check(self):
        cases = [
            ("yit.md", "YIT", "YIT:n osavuosikatsaus tammi-syyskuu 2026",
             "yit-q3-2026.txt", {"available": True,
                 "operating_profit": {"expected": "24.8", "deviation_percent": "20.8"},
                 "comparison": "yläpuolella"}),
            ("storaenso.md", "Stora Enso",
             "Stora Enson osavuosikatsaus tammi–syyskuulta 2026",
             "stora-enso-q3-2026.txt", {"available": True,
                 "operating_profit": {"expected": "142.4", "deviation_percent": "13.1"},
                 "comparison": "yläpuolella"}),
            ("aktia.md", "Aktia",
             "Aktia Pankki Oyj:n osavuosikatsaus 1.1.–30.9.2026",
             "aktia-q3-2026.txt", {"available": False}),
            ("huhtamaki.md", "Huhtamäki",
             "Huhtamäki Oyj:n puolivuosikatsaus 1.1.–30.6.2026",
             "huhtamaki-q2-2026.txt", {"available": True,
                 "operating_profit": {"expected": "100.3", "deviation_percent": "3.4"},
                 "comparison": "yläpuolella"}),
        ]
        for example, company, title, source, baseline in cases:
            with self.subTest(example=example):
                markdown = (ROOT.parent / "examples" / example).read_text(encoding="utf-8")
                heading, _, body = markdown.partition("\n")
                extracted = report(company, title, source)
                packet = {"kind": "earnings", "earnings": extracted,
                          "earnings_baseline": baseline,
                          "guidance_check": {"available": False},
                          "sources": [{"text": fixture(source)}]}
                draft = {"title": heading.removeprefix("# "), "summary": "",
                         "category": "Talous",
                         "paragraphs": [{"text": body, "source_ids": ["A"]}]}
                self.assertTrue(earnings.figure_check(draft, packet))

    def test_policy_and_method_page_are_explicit(self):
        authorization = proposed_policy_v2()
        self.assertIn("earnings", authorization["source_families"])
        self.assertEqual(authorization["earnings_policy_sha256"], earnings.policy_digest())
        self.assertEqual(authorization["max_earnings_per_helsinki_day"], 6)
        method = site.earnings_method_page_body()
        self.assertIn("neljää peräkkäistä", method)
        self.assertIn("ei ole analyytikkoennuste", method)
        calculation = site.earnings_baseline_html({
            "earnings_baseline": {"available": False},
            "guidance_check": {"available": True, "low": "80", "high": "90",
                               "seasonally_estimated_full_year": "80.0",
                               "q4_share": "25.0", "seasonal_years": [2025, 2024],
                               "on_track": True, "position": "ohjeistushaarukassa"}})
        self.assertIn("yhtiö itse odottaa 80–90 milj. euroa", calculation)
        self.assertIn("vuosien 2025 ja 2024", calculation)
        self.assertIn("Q4:n osuus on 25,0 %", calculation)
        self.assertIn('/talous/menetelma/', calculation)

    def test_collected_packet_passes_release_and_capture_contracts(self):
        from news_mvp.release_contract import media, verify_intake
        title = "YIT:n osavuosikatsaus tammi-syyskuu 2026"
        body = "".join(f"<p>{escape(line)}</p>" for line in
                       fixture("yit-q3-2026.txt").splitlines())
        raw = (f"<html><body><article><h1>{escape(title)}</h1>{body}</article>"
               "</body></html>").encode()
        recipe = {"family": "earnings", "provider": "cision",
                  "url": "https://news.cision.com/fi/yit-oyj/r/yit-n-osavuosikatsaus-tammi-syyskuu-2026,c4417506",
                  "title": title, "company": "YIT", "quarter": 3,
                  "period_end": "2026-09-30", "published_at": "2026-10-30T06:30:00+00:00"}
        with tempfile.TemporaryDirectory() as directory, patch(
                "news_mvp.earnings.fetch", return_value=(raw, "text/html", recipe["url"])):
            packet, _receipt = earnings.collect(recipe, directory, NOW)
            draft = {"title": "YIT:n liikevaihto nousi 14 %",
                     "summary": "Liikevaihto oli 530 miljoonaa euroa.",
                     "category": "Talous", "image": None, "paragraphs": [
                         {"text": "Oikaistu liikevoitto oli 30 miljoonaa euroa.",
                          "source_ids": ["A"]},
                         {"text": "Raportoitu liikevoitto laski 9 miljoonaan euroon 25 miljoonasta eurosta. Yhtiön mukaan tulosta heikensi pääosin Tripla Mall Ky:n -19 miljoonan euron käyvän arvon muutos.",
                          "source_ids": ["A"]},
                         {"text": "Osakekohtainen tulos oli -0,03 euroa.",
                          "source_ids": ["A"]}]}
            binding = media(packet, draft)
            self.assertEqual(binding["text_only"]["policy"], "earnings-text-v1")
            verify_intake(packet, directory)


if __name__ == "__main__":
    unittest.main()
