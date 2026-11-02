#!/usr/bin/env python3
"""Build the committed earnings seed from public Cision company archives.

This is an explicit maintenance command, never part of the publisher tick.  It
fetches at most six releases per allowlisted company and feeds their text to the
same fail-closed extractor used by live intake.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from news_mvp import earnings  # noqa: E402


NEWSROOMS = {
    "Nordea": "nordea", "Nokia": "nokia", "Kone": "kone-oyj",
    "Sampo": "sampo-group", "UPM": "upm-kymmene-oyj", "Neste": "neste",
    "Wärtsilä": "wartsila-corporation", "Fortum": "fortum",
    "Stora Enso": "stora-enso-oyj", "Kesko": "k-ryhma", "Elisa": "elisa-oyj",
    "Konecranes": "konecranes-oyj", "Metso": "metso-corporation",
    "Orion": "orion-oyj", "Valmet": "valmet-oyj", "Huhtamäki": "huhtamaki-oyj",
    "Outokumpu": "outokumpu-oyj", "Nokian Renkaat": "nokian-tyres",
    "Tietoevry": "tietoevry", "Kemira": "kemira-oyj", "Mandatum": "mandatum-oyj",
    "Kalmar": "kalmar-oyj", "Kojamo": "lumo-homes-plc", "YIT": "yit-oyj",
    "Aktia": "aktia-bank",
}
OFFICIAL_ARCHIVES = {
    "Kalmar": "https://www.kalmar.fi/news--insights/lehdistotiedotteet/",
    "Orion": "https://www.orion.fi/uutishuone/kaikki-uutiset/",
    "Nokia": "https://www.nokia.com/newsroom/stock-exchange-releases/",
    "Sampo": "https://www.sampo.com/investors/results-and-presentations/",
    "Tietoevry": "https://www.tietoevry.com/fi/uutishuone/kaikki-uutiset-ja-tiedotteet/",
}
SEARCH_TERMS = earnings.REPORT_WORDS


def fetch(url):
    request = Request(url, headers={"User-Agent": "Uutistenlukija history backfill/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read()


class ListingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current = None
        self.in_heading = False
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "bodytext" in attrs.get("class", "").split():
            self.current = {"url": attrs.get("href"), "title": []}
        elif self.current is not None and tag == "h2":
            self.in_heading = True

    def handle_data(self, data):
        if self.current is not None and self.in_heading:
            self.current["title"].append(data)

    def handle_endtag(self, tag):
        if tag == "h2":
            self.in_heading = False
        elif tag == "a" and self.current is not None:
            title = " ".join("".join(self.current["title"]).split())
            if title and self.current["url"]:
                self.rows.append({"title": html.unescape(title), "url": self.current["url"]})
            self.current = None
            self.in_heading = False


class OfficialListingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current = None
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.current = {"url": attrs["href"], "text": [],
                            "title": attrs.get("title") or attrs.get("aria-label") or ""}

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            title = self.current["title"] or " ".join("".join(
                self.current["text"]).split())
            if title:
                self.rows.append({"title": html.unescape(title),
                                  "url": self.current["url"]})
            self.current = None


def archive_candidates(newsroom):
    rows = {}
    for term in SEARCH_TERMS:
        query = urlencode({"q": term, "startDate": "2024-01-01",
                           "endDate": "2026-10-29", "pageIx": 1, "pageSize": 100})
        raw = fetch(f"https://news.cision.com/fi/{newsroom}/ListItems?{query}")
        parser = ListingParser()
        parser.feed(raw.decode("utf-8-sig"))
        for row in parser.rows:
            title = earnings._fold(row["title"])
            if (any(word in title for word in earnings.REPORT_WORDS) and
                    not earnings.FORBIDDEN_TITLE.search(title) and
                    not earnings.FORBIDDEN_NOTICE.search(title) and
                    not title.startswith("korjaus") and earnings._period(row["title"])):
                rows[row["url"]] = row
    return sorted(rows.values(),
                  key=lambda row: earnings._period(row["title"])["period_end"],
                  reverse=True)[:6]


def official_archive_candidates(company, archive):
    pages = [archive]
    if company == "Orion":
        pages.extend(f"{archive}?page={page}" for page in range(2, 9))
    rows = {}
    pdf_matches = 0
    archive_host = urlparse(archive).hostname
    for page in pages:
        parser = OfficialListingParser()
        parser.feed(fetch(page).decode("utf-8-sig"))
        for candidate in parser.rows:
            title = earnings._fold(candidate["title"])
            is_report = (any(word in title for word in earnings.REPORT_WORDS) or
                         bool(re.search(r"\b(?:interim report|interim statement|"
                                        r"financial report|report for q[1-4])\b", title)))
            if (not is_report or re.search(r"\b(?:julkaisee|publish|calendar|kalenteri|"
                                            r"presentation|webcast)\b", title) or
                    earnings._period(candidate["title"]) is None):
                continue
            url = urljoin(archive, candidate["url"])
            if urlparse(url).hostname != archive_host:
                continue
            if urlparse(url).path.casefold().endswith(".pdf"):
                pdf_matches += 1
                continue
            rows[url] = {"title": candidate["title"], "url": url, "provider": "official"}
    if not rows and pdf_matches:
        raise ValueError(f"official archive exposes {pdf_matches} matching reports only as PDF; "
                         "the deterministic HTML extractor does not parse PDFs")
    if not rows:
        if company == "Sampo":
            raise ValueError("official results archive exposes quarterly reports as PDF, "
                             "not readable HTML releases for the deterministic extractor")
        raise ValueError("official archive returned no readable HTML result-report links")
    return sorted(rows.values(), key=lambda row: earnings._period(row["title"])["period_end"],
                  reverse=True)[:6]


def release_record(company, row):
    raw = fetch(row["url"])
    provider = row.get("provider", "cision")
    text = earnings.release_text(raw, provider)
    published = (re.search(rb'<time[^>]+datetime="([^"]+)"', raw) or
                 re.search(rb'<meta[^>]+(?:article:published_time|datePublished)[^>]+content="([^"]+)"',
                           raw, re.I))
    published_at = (published.group(1).decode().replace(" ", "T")
                    if published else earnings._period(row["title"])["period_end"] + "T00:00:00Z")
    try:
        report = earnings.extract_report(text, company, row["title"], published_at)
    except ValueError as error:
        if (provider == "official" and not re.search(
                r"liikevaihto|liikevoitto|net sales|operating profit|underwriting result",
                text, re.I)):
            raise ValueError("official page's server HTML omits the financial result table") from error
        raise
    return {"source_url": row["url"], "report": report}


def apply_restatements(rows):
    by_key = {(row["report"]["company"], row["report"]["period_end"]): row for row in rows}
    for newer in sorted(rows, key=lambda row: row["report"]["period_end"]):
        report = newer["report"]
        prior_year = report["year"] - 1
        month, day = ((3, 31), (6, 30), (9, 30), (12, 31))[report["quarter"] - 1]
        older = by_key.get((report["company"], f"{prior_year:04d}-{month:02d}-{day:02d}"))
        if older is None:
            continue
        for field in ("revenue", "operating_profit", "eps"):
            if field not in report["figures"] or field not in older["report"]["figures"]:
                continue
            metric = older["report"]["figures"][field]
            metric["value"] = report["figures"][field]["comparison"]
            metric["display"] = report["figures"][field]["comparison_display"]
        older["report"]["restated_by"] = report["period_end"]
        older["source_url"] = newer["source_url"]


def build():
    coverage = {}
    reports = []
    for company in [row["name"] for row in earnings.policy()["companies"]]:
        newsroom = NEWSROOMS[company]
        archive = OFFICIAL_ARCHIVES.get(company,
                                        f"https://news.cision.com/fi/{newsroom}")
        errors = []
        try:
            candidates = (official_archive_candidates(company, archive)
                          if company in OFFICIAL_ARCHIVES else archive_candidates(newsroom))
        except Exception as error:  # fail one company, preserve the auditable rest
            candidates = []
            errors.append(f"archive lookup: {type(error).__name__}: {error}")
        stored = []
        for row in candidates:
            try:
                stored.append(release_record(company, row))
            except Exception as error:
                errors.append(f"{row['title']}: {type(error).__name__}: {error}")
        reports.extend(stored)
        short = None
        if len(stored) < 4:
            short = ((f"official archive listing exposed only {len(candidates)} matching "
                       "readable HTML result-report links"
                      if company in OFFICIAL_ARCHIVES else
                      "public Cision newsroom supplied fewer than four unambiguous Finnish reports")
                     if not errors else "; ".join(errors[:3]))
        coverage[company] = {"archive": archive,
                             "attempted_reports": len(candidates),
                             "stored_quarters": len(stored), "short_reason": short}
        print(f"{company}: attempted {len(candidates)}, stored {len(stored)}", file=sys.stderr)
    apply_restatements(reports)
    reports.sort(key=lambda row: (row["report"]["company"], row["report"]["period_end"]))
    return {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_policy": "public company Cision and official IR archives; deterministic extractor",
            "coverage": coverage, "reports": reports}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "data/earnings_history.json")
    args = parser.parse_args()
    value = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                      sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
