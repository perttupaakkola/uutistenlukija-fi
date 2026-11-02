"""Deterministic Friday economy roundup assembled only from free official sources."""
from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from .editorial import digest, validate_packet, web_url
from .intake import fetch
from .slugs import article_slug


POLICY = Path(__file__).resolve().parents[1] / "sources/weekly-economy.json"
HELSINKI = ZoneInfo("Europe/Helsinki")
NUMBER = r"[-+]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[,.]\d+)?"
REPORT_WORDS = ("osavuosikatsaus", "puolivuosikatsaus", "liiketoimintakatsaus",
                "tilinpäätöstiedote", "osavuosiraportti")
STAT_TERMS = re.compile(
    r"infla|kuluttajien luottamus|tyött|työll|bruttokansantuot|kansantalouden tuotanto|"
    r"konkur|liikevaihto|tuottajahinn", re.I)
CALENDAR_STAT_TERMS = re.compile(
    r"kuluttajahinta|työvoimatutkimus|kuluttajien luottamus|bruttokansantuot|"
    r"kansantalouden tuotanto|konkur", re.I)
MISSING_CALCULATION_META = re.compile(
    r"\b(?:trendiodotusta|trendivertailua|ohjeistusvertailua|kausivaihteluun\s+"
    r"perustuvaa\s+(?:arviota|vertailua)|laskelmaa)\b[^.!?]{0,140}\b(?:ei\s+"
    r"näytetä|ei\s+lasketa|ei\s+ole\s+saatavilla|jätetään\s+pois)\b", re.I)


def policy():
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    if (value.get("mode") != "weekly-economy-text-v1" or
            value.get("publish_weekday") != 4 or
            value.get("publish_hour_helsinki") != 16 or
            value.get("max_articles_per_week") != 1):
        raise ValueError("Unreviewed weekly economy policy")
    return value


def policy_digest():
    return digest(policy())


def week_bounds(week_ending):
    end = date.fromisoformat(str(week_ending)) if not isinstance(week_ending, date) else week_ending
    if end.weekday() != 4:
        raise ValueError("Weekly economy period must end on Friday")
    return end - timedelta(days=4), end


def _friday(now):
    local = now.astimezone(HELSINKI)
    return local.date() if local.weekday() == 4 else None


def discover(config, now=None, excluded=(), errors=None):
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(HELSINKI)
    end = _friday(now)
    if end is None or local.hour < policy()["publish_hour_helsinki"]:
        return []
    story_key = f"weekly-economy:{end.isoformat()}"
    url = policy()["fx"]["url"]
    if story_key in excluded or url in excluded or "url:" + url in excluded:
        return []
    return [{"family": "weekly-economy", "provider": "weekly-economy", "url": url,
             "story_key": story_key, "week_ending": end.isoformat()}]


def _decimal(value):
    try:
        return Decimal(str(value).replace("\u00a0", "").replace("\u202f", "")
                       .replace(" ", "").replace(",", "."))
    except (InvalidOperation, AttributeError) as error:
        raise ValueError("Invalid weekly economy number") from error


def _one_decimal(value):
    return format(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP), "f")


def parse_fx(raw, week_ending, currencies=("USD", "SEK", "GBP", "NOK")):
    """Friday versus previous Friday using the ECB's foreign-currency units per euro."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise ValueError("Invalid ECB reference-rate XML") from error
    rows = {}
    for cube in root.iter():
        stamp = cube.attrib.get("time")
        if not stamp:
            continue
        rows[stamp] = {child.attrib.get("currency"): child.attrib.get("rate")
                       for child in cube if child.attrib.get("currency")}
    end = date.fromisoformat(str(week_ending))
    prior = end - timedelta(days=7)
    if end.isoformat() not in rows or prior.isoformat() not in rows:
        raise ValueError("ECB XML lacks both Friday observations")
    result = []
    for currency in currencies:
        current = _decimal(rows[end.isoformat()].get(currency))
        previous = _decimal(rows[prior.isoformat()].get(currency))
        change = (current / previous - 1) * 100
        result.append({"currency": currency, "friday": str(current),
                       "previous_friday": str(previous),
                       "change_percent": _one_decimal(change),
                       "direction": "vahvistui" if change > 0 else
                                    "heikkeni" if change < 0 else "pysyi ennallaan"})
    return result


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocked = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "svg"):
            self.blocked += 1
        if not self.blocked and tag in ("p", "h1", "h2", "h3", "li", "br"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "svg") and self.blocked:
            self.blocked -= 1
        if not self.blocked and tag in ("p", "h1", "h2", "h3", "li"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(data)

    def text(self):
        return "\n".join(" ".join(line.split()) for line in
                         html.unescape("".join(self.parts)).splitlines() if line.strip())


def visible_text(raw):
    parser = _VisibleText()
    parser.feed(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
    return parser.text()


def parse_ecb_decision(raw, published_at, url):
    text = visible_text(raw)
    decision = re.search(r"EKP:n neuvosto päätti tänään ([^.]+)\.", text, re.I)
    deposit = re.search(r"Talletuskorko on (?:edelleen )?(" + NUMBER + r")\s*%", text, re.I)
    if not decision or not deposit:
        raise ValueError("ECB decision or new deposit rate missing")
    sentences = re.split(r"(?<=[.!?])\s+", text[text.find(decision.group(0)):])
    reason = next((sentence for sentence in sentences[1:8]
                   if re.search(r"inflaatio|kasvu|palkat|rahoitusehdot", sentence, re.I)), None)
    if not reason:
        raise ValueError("ECB decision lacks a stated reason")
    rates = {}
    for label, pattern in (
            ("talletuskorko", r"Talletuskorko on (?:edelleen )?(" + NUMBER + r")\s*%"),
            ("perusrahoitusoperaatioiden korko", r"perusrahoitusoperaatioiden korko (" + NUMBER + r")\s*%"),
            ("maksuvalmiusluoton korko", r"maksuvalmiusluoton korko (" + NUMBER + r")\s*%")):
        match = re.search(pattern, text, re.I)
        if match:
            rates[label] = str(_decimal(match.group(1)))
    return {"bank": "Euroopan keskuspankki", "date": str(published_at)[:10],
            "decision": decision.group(1).strip(), "rate_name": "talletuskorko",
            "new_rate": str(_decimal(deposit.group(1))), "rates": rates,
            "reason": reason.strip(), "url": url}


def ecb_decision_links(raw, start, end):
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    result = []
    pattern = re.compile(r'<dt isoDate="(\d{4}-\d{2}-\d{2})".*?</dt>\s*<dd>.*?'
                         r'href="([^"]+ecb\.mp[^".]+~[a-f0-9]+)\.en\.html"', re.S)
    for stamp, path in pattern.findall(text):
        day = date.fromisoformat(stamp)
        if start <= day <= end:
            result.append((stamp, urljoin("https://www.ecb.europa.eu", path + ".fi.html")))
    return result


def _rss_decision_links(raw, start, end, source):
    try:
        items = ET.fromstring(raw).findall("./channel/item")
    except ET.ParseError as error:
        raise ValueError("Invalid central-bank decision RSS") from error
    result = []
    for item in items:
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        try:
            stamp = parsedate_to_datetime(item.findtext("pubDate") or "").date()
        except (TypeError, ValueError):
            continue
        if (start <= stamp <= end and
                re.fullmatch(source["title_pattern"], title, re.I) and
                re.fullmatch(source["article_pattern"], url)):
            result.append((stamp.isoformat(), url))
    return result


def _html_decision_links(raw, start, end, source):
    """Read dated decision links from an official central-bank listing page."""
    markup = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    result = []
    for match in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                             markup, re.I | re.S):
        title = _strip_markup(match.group(2))
        if not re.search(source["title_pattern"], title, re.I):
            continue
        url = urljoin(source["index"], html.unescape(match.group(1)))
        if not re.fullmatch(source["article_pattern"], url):
            continue
        context = markup[max(0, match.start() - 500):match.end() + 500]
        stamps = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", context)
        stamps += [date(int(year), MONTHS[month.casefold()], int(day)).isoformat()
                   for day, month, year in re.findall(
                       r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(20\d{2})\b",
                       context, re.I)]
        for value in stamps:
            stamp = date.fromisoformat(value)
            if start <= stamp <= end:
                result.append((value, url))
                break
    return sorted(set(result))


def central_bank_decision_links(raw, start, end, source):
    if source["kind"] == "ecb":
        return ecb_decision_links(raw, start, end)
    if source["kind"] == "rss":
        return _rss_decision_links(raw, start, end, source)
    if source["kind"] == "html":
        return _html_decision_links(raw, start, end, source)
    raise ValueError("Unknown central-bank decision index type")


def _fractional_rate(value):
    value = str(value).strip()
    match = re.fullmatch(r"(\d+)-(\d+)/(\d+)", value)
    if match:
        return Decimal(match.group(1)) + Decimal(match.group(2)) / Decimal(match.group(3))
    return _decimal(value)


def parse_central_bank_decision(raw, bank, published_at, url):
    if bank == "Euroopan keskuspankki":
        return parse_ecb_decision(raw, published_at, url)
    text = visible_text(raw)
    if bank == "Yhdysvaltain keskuspankki":
        match = re.search(
            r"Committee decided to (maintain|raise|lower) the target range for the federal "
            r"funds rate at (\d+(?:-\d+/\d+)?|\d+(?:\.\d+)?) to "
            r"(\d+(?:-\d+/\d+)?|\d+(?:\.\d+)?) percent", text, re.I)
        if not match:
            raise ValueError("Federal Reserve decision or target range missing")
        lower, upper = _fractional_rate(match.group(2)), _fractional_rate(match.group(3))
        decision = match.group(0).strip()
        new_rate = f"{lower:.2f}\u2013{upper:.2f}"
        rate_name = "federal funds -tavoiteväli"
    else:
        patterns = {
            "Ruotsin keskuspankki":
                r"(?:policy rate|repo rate)[^.]{0,100}?(?:at|to)\s+(" + NUMBER + r")\s*(?:%|per cent|percent)",
            "Norges Bank":
                r"policy rate[^.]{0,100}?(?:at|to)\s+(" + NUMBER + r")\s*(?:%|per cent|percent)",
            "Bank of England":
                r"Bank Rate[^.]{0,100}?(?:at|to)\s+(" + NUMBER + r")\s*(?:%|per cent|percent)"}
        match = re.search(patterns.get(bank, r"$^"), text, re.I)
        if not match:
            raise ValueError("Central-bank decision or new rate missing")
        sentence = next((part for part in re.split(r"(?<=[.!?])\s+", text)
                         if match.group(0) in part), match.group(0))
        decision = sentence.strip()
        new_rate = str(_decimal(match.group(1)))
        rate_name = "ohjauskorko" if bank != "Bank of England" else "Bank Rate"
    reason = next((sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text)
                   if re.search(r"inflation|economic activity|economy|growth|employment|demand",
                                sentence, re.I) and sentence.strip() != decision), None)
    if not reason:
        raise ValueError("Central-bank decision lacks a stated reason")
    return {"bank": bank, "date": str(published_at)[:10], "decision": decision,
            "rate_name": rate_name, "new_rate": new_rate, "reason": reason, "url": url}


def _strip_markup(value):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(value or ""))).split())


def parse_statistics_finland(raw, start, end, limit=3):
    try:
        rows = json.loads(raw)["publications"]
    except (TypeError, ValueError, KeyError) as error:
        raise ValueError("Invalid Statistics Finland publications response") from error
    selected = []
    for row in rows:
        stamp = str(row.get("plannedReleaseDate", ""))[:10]
        title = str(row.get("title") or row.get("workingTitle") or "")
        ingress = _strip_markup(row.get("ingress"))
        if (not stamp or not start.isoformat() <= stamp <= end.isoformat() or
                not STAT_TERMS.search(title) or not ingress):
            continue
        selected.append({"date": stamp, "title": title, "headline": ingress,
                         "url": "https://stat.fi/fi/julkaisu/" + str(row["id"])})
    priorities = ("kuluttajien luottamus", "tyött", "kansantalouden tuotanto",
                  "bruttokansantuot", "infla", "konkur")
    selected.sort(key=lambda row: (next((i for i, term in enumerate(priorities)
                                         if term in row["title"].casefold()), 99), row["date"]))
    return selected[:limit]


def parse_statistics_calendar(raw, start, end, limit=4):
    try:
        rows = json.loads(raw)["calendarPublications"]
    except (TypeError, ValueError, KeyError) as error:
        raise ValueError("Invalid Statistics Finland calendar response") from error
    result = []
    for row in rows:
        stamp = str(row.get("plannedReleaseDate", ""))[:10]
        title = str(row.get("workingTitle") or row.get("title") or "")
        if (start.isoformat() <= stamp <= end.isoformat() and
                CALENDAR_STAT_TERMS.search(title)):
            result.append({"date": stamp, "title": title,
                           "url": "https://stat.fi/fi/julkaisu/" + str(row["id"]),
                           "type": "Tilastokeskus"})
    return sorted(result, key=lambda row: (row["date"], row["title"]))[:limit]


def _rss_items(raw):
    try:
        items = ET.fromstring(raw).findall("./channel/item")
    except ET.ParseError as error:
        raise ValueError("Invalid company-calendar RSS") from error
    return [{"title": (item.findtext("title") or "").strip(),
             "description": _strip_markup(item.findtext("description")),
             "url": (item.findtext("link") or "").strip()}
            for item in items]


def _calendar_company(title, allowed):
    folded = title.casefold()
    matches = [name for name in allowed
               if re.search(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", folded)]
    return matches[0] if len(matches) == 1 else None


def parse_company_calendar(feeds, start, end, allowed_companies=None):
    from .earnings import policy as earnings_policy
    allowed = list(allowed_companies or [])
    allowed += [row["name"] for row in earnings_policy()["companies"]]
    result, seen = [], set()
    for raw in feeds.values():
        for item in _rss_items(raw):
            combined = item["title"] + " " + item["description"]
            company = _calendar_company(item["title"], allowed)
            if (not company or not any(word in combined.casefold() for word in REPORT_WORDS) or
                    not re.search(r"julkais|julkist", combined, re.I)):
                continue
            for day, month, year in re.findall(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(20\d{2})(?!\d)", combined):
                try:
                    stamp = date(int(year), int(month), int(day))
                except ValueError:
                    continue
                key = (company, stamp)
                if start <= stamp <= end and key not in seen:
                    seen.add(key)
                    result.append({"date": stamp.isoformat(), "title": company + " tulosjulkistus",
                                   "url": item["url"], "type": "yhtiö"})
                    break
    return sorted(result, key=lambda row: (row["date"], row["title"]))


MONTHS = {name: index for index, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), 1)}


def parse_public_calendar(raw, start, end, bank, url):
    text = visible_text(raw)
    dates = set()
    for year, month, day in re.findall(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text):
        dates.add(date(int(year), int(month), int(day)))
    for day, month, year in re.findall(
            r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(20\d{2})\b", text, re.I):
        dates.add(date(int(year), MONTHS[month.casefold()], int(day)))
    return [{"date": stamp.isoformat(), "title": bank + " – korkokokous",
             "url": url, "type": "keskuspankki"}
            for stamp in sorted(dates) if start <= stamp <= end]


def result_summary(report, baseline, title, url, source_text, published_at):
    figures = report["figures"]
    revenue = figures["revenue"]
    profit = figures["operating_profit"]
    def direction(row):
        current, comparison = _decimal(row["value"]), _decimal(row["comparison"])
        return "nousi" if current > comparison else "laski" if current < comparison else "pysyi ennallaan"
    result = {"company": report["company"], "revenue_direction": direction(revenue),
              "profit_direction": direction(profit), "url": url, "title": title,
              "published_at": published_at, "source_text": source_text}
    if isinstance(baseline, dict) and baseline.get("available"):
        result["trend"] = baseline["comparison"]
        result["trend_expected"] = baseline["operating_profit"]["expected"]
        result["trend_deviation_percent"] = baseline["operating_profit"]["deviation_percent"]
    return result


def stored_results(state_dir, start, end):
    path = Path(state_dir) / "jobs.sqlite"
    if not path.is_file():
        return []
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute(
            "SELECT j.id,j.created_at,j.packet,j.draft FROM jobs j JOIN publications p "
            "ON p.job_id=j.id WHERE p.status='deployed' AND j.created_at>=? AND j.created_at<? "
            "ORDER BY j.created_at", (start.isoformat(), (end + timedelta(days=1)).isoformat())).fetchall()
    finally:
        db.close()
    result = []
    for row in rows:
        try:
            packet, draft = json.loads(row["packet"]), json.loads(row["draft"])
            if packet.get("kind") != "earnings":
                continue
            text = "\n".join([draft["summary"], *[p["text"] for p in draft["paragraphs"]]])
            url = "https://uutistenlukija.fi/uutiset/" + article_slug(row["id"], draft["title"]) + "/"
            result.append(result_summary(packet["earnings"], packet.get("earnings_baseline"),
                                         draft["title"], url, text, row["created_at"]))
        except (TypeError, ValueError, KeyError):
            continue
    return result


def _source(identifier, url, publisher, title, published_at, text):
    text = str(text).strip()
    if len(text) < 40:
        raise ValueError("Weekly economy source excerpt is too thin")
    return {"id": identifier, "url": url, "publisher": publisher, "title": title,
            "published_at": published_at, "text": text[:20000]}


def build_packet(week_ending, fx_raw, *, decisions=(), decision=None, statistics_raw=None,
                 results=(), company_feeds=None, statistics_calendar_raw=None,
                 public_calendars=(), captured=None, now=None):
    now = now or datetime.now(timezone.utc)
    start, end = week_bounds(week_ending)
    next_start, next_end = end + timedelta(days=3), end + timedelta(days=9)
    spec = policy()
    weekly = {"week_start": start.isoformat(), "week_ending": end.isoformat(),
              "fx": parse_fx(fx_raw, end, spec["fx"]["currencies"]),
              "central_banks": [], "statistics_finland": [],
              # Only results published inside this week; an older report must never
              # appear as this week's news.
              "results": [r for r in results
                          if start.isoformat() <= str(r.get("published_at", ""))[:10] <= end.isoformat()],
              "next_week": []}
    sources = []
    fx_text = "EKP:n euron viitekurssit. " + "; ".join(
        f"{row['currency']} {row['previous_friday']} ({(end-timedelta(days=7)).isoformat()}) ja "
        f"{row['friday']} ({end.isoformat()}), muutos {row['change_percent']} %."
        for row in weekly["fx"])
    sources.append(_source("A", spec["fx"]["url"], "Euroopan keskuspankki",
                           "Euron viitekurssit", end.isoformat() + "T14:00:00+00:00", fx_text))
    decision_rows = list(decisions)
    if decision is not None:  # Compatibility for stored fixture callers.
        decision_rows.insert(0, decision)
    source_letter = ord("B")
    for row in decision_rows:
        weekly["central_banks"].append(row["data"])
        sources.append(_source(chr(source_letter), row["url"], row["data"]["bank"],
                               row.get("title", "Rahapoliittinen päätös"),
                               row["published_at"], row["text"]))
        row["data"]["source_id"] = chr(source_letter)
        source_letter += 1
    if statistics_raw is not None:
        weekly["statistics_finland"] = parse_statistics_finland(statistics_raw, start, end)
        if weekly["statistics_finland"]:
            stat_text = "\n".join(row["title"] + ". " + row["headline"]
                                  for row in weekly["statistics_finland"])
            sources.append(_source(chr(source_letter), spec["statistics_finland"]["publications"],
                                   "Tilastokeskus, CC BY 4.0", "Viikon tilastojulkaisut",
                                   end.isoformat() + "T06:00:00+00:00", stat_text))
            weekly["statistics_source_id"] = chr(source_letter)
            source_letter += 1
    for row in weekly["results"][:4]:
        sources.append(_source(chr(source_letter), row["url"], "Uutistenlukija",
                               row["title"], row["published_at"], row["source_text"]))
        row["source_id"] = chr(source_letter)
        source_letter += 1
    company_calendar = parse_company_calendar(
        company_feeds or {}, next_start, next_end, spec.get("calendar_companies", []))
    stat_calendar = (parse_statistics_calendar(statistics_calendar_raw, next_start, next_end)
                     if statistics_calendar_raw is not None else [])
    bank_calendar = [row for rows in public_calendars for row in rows]
    weekly["next_week"] = sorted(company_calendar + stat_calendar + bank_calendar,
                                 key=lambda row: (row["date"], row["title"]))
    calendar_ids = []
    for row in weekly["next_week"]:
        if source_letter > ord("L"):
            break
        identifier = chr(source_letter)
        publisher = (row["title"].removesuffix(" tulosjulkistus") + " (pörssitiedote)"
                     if row["type"] == "yhtiö" else
                     "Tilastokeskus, CC BY 4.0" if row["type"] == "Tilastokeskus" else
                     row["title"].split(" – ", 1)[0])
        calendar_text = ("Julkisen kalenterin päivämäärä: " + row["date"] + ". " +
                         row["title"] + ".")
        sources.append(_source(identifier, row["url"], publisher,
                               row["title"], end.isoformat() + "T13:00:00+00:00",
                               calendar_text))
        row["source_id"] = identifier
        calendar_ids.append(identifier)
        source_letter += 1
    if calendar_ids:
        weekly["calendar_source_ids"] = calendar_ids
    section_count = sum(bool(weekly[key]) for key in
                        ("fx", "central_banks", "statistics_finland", "results", "next_week"))
    if section_count < 3:
        raise ValueError("Weekly economy roundup has fewer than three substantive sections")
    capture_hashes = {name: hashlib.sha256(value).hexdigest()
                      for name, value in (captured or {}).items()}
    packet = {"kind": "weekly-economy", "story_key": f"weekly-economy:{end.isoformat()}",
              "fixture": False, "sources": sources[:12], "image": None,
              "image_note": "Viikkokatsaus saa vain ihmisettömän talousaiheisen konseptikuvan.",
              "weekly_economy": weekly,
              "publication_basis": {"policy": spec["mode"],
                  "policy_sha256": policy_digest(), "provider": "weekly-economy",
                  "source_sha256": {s["id"]: hashlib.sha256(s["text"].encode()).hexdigest()
                                    for s in sources[:12]},
                  "source_fields_sha256": digest(sources[:12]),
                  "capture_sha256": capture_hashes}}
    validate_packet(packet, now, spec["max_source_age_hours"])
    return packet


def _numeric_values(value):
    prose = str(value).replace("\u2212", "-")
    prose = re.sub(r"(?<!\d)\u2013(?=\d)", "-", prose)
    return {_decimal(match.group(0)) for match in re.finditer(NUMBER, prose)}


def reject_missing_calculation_meta(prose):
    if MISSING_CALCULATION_META.search(str(prose)):
        raise ValueError("Unavailable calculations must be omitted without a meta explanation")
    return True


def figure_check(draft, packet):
    if packet.get("kind") != "weekly-economy":
        return True
    weekly = packet.get("weekly_economy")
    if not isinstance(weekly, dict):
        raise ValueError("Weekly economy packet lacks deterministic data")
    passages = [str(draft.get("title", "")), str(draft.get("summary", "")),
                *[str(row.get("text", "")) for row in draft.get("paragraphs", [])]]
    prose = " ".join(passages)
    reject_missing_calculation_meta(prose)
    if draft.get("category") != "Talous":
        raise ValueError("Weekly economy draft must use category Talous")
    if not str(draft.get("title", "")).startswith("Talous tällä viikolla:"):
        raise ValueError("Weekly economy title must use the approved title pattern")
    allowed = _numeric_values(json.dumps(weekly, ensure_ascii=False))
    allowed |= _numeric_values(" ".join(source["text"] for source in packet["sources"]))
    unexpected = sorted(_numeric_values(prose) - allowed)
    if unexpected:
        raise ValueError("Weekly economy draft contains number(s) absent from sources: " +
                         ", ".join(format(value, "f") for value in unexpected))
    return True


def _fetch_exact(url, hosts, mimes):
    raw, mime, final = fetch(url, hosts)
    if final != url or mime not in mimes:
        raise ValueError("Unexpected weekly economy source response")
    return raw


def collect(recipe, state_dir, now=None):
    now = now or datetime.now(timezone.utc)
    spec = policy()
    end = date.fromisoformat(str(recipe.get("week_ending")))
    if recipe.get("story_key") != f"weekly-economy:{end.isoformat()}":
        raise ValueError("Weekly economy recipe identity mismatch")
    start, _ = week_bounds(end)
    captures = {}
    fx_raw = _fetch_exact(spec["fx"]["url"], spec["fx"]["hosts"],
                          ("application/xml", "text/xml", "text/html"))
    captures["fx.xml"] = fx_raw
    decisions = []
    for source_number, (bank, source) in enumerate(spec["central_bank_decisions"].items()):
        try:
            index_mimes = (("application/xml", "text/xml", "text/html")
                           if source["kind"] == "rss" else ("text/html",))
            index_raw = _fetch_exact(source["index"], source["hosts"], index_mimes)
            capture_name = "decision-index-" + str(source_number)
            captures[capture_name] = index_raw
            links = central_bank_decision_links(index_raw, start, end, source)
            if not links:
                continue
            stamp, url = links[-1]
            if not re.fullmatch(source["article_pattern"], url):
                raise ValueError("Unapproved central-bank decision URL")
            raw = _fetch_exact(url, source["hosts"], ("text/html",))
            captures["decision-" + str(len(decisions)) + ".html"] = raw
            decisions.append({"data": parse_central_bank_decision(raw, bank, stamp, url),
                              "url": url, "title": bank + " – rahapoliittinen päätös",
                              "published_at": stamp + "T12:15:00+00:00",
                              "text": visible_text(raw)})
        except (OSError, ValueError):
            continue
    stat_raw = _fetch_exact(spec["statistics_finland"]["publications"],
                            spec["statistics_finland"]["hosts"], ("application/json", "text/json"))
    stat_calendar_raw = _fetch_exact(spec["statistics_finland"]["calendar"],
                                     spec["statistics_finland"]["hosts"],
                                     ("application/json", "text/json"))
    captures["stat-publications.json"] = stat_raw
    captures["stat-calendar.json"] = stat_calendar_raw
    feeds = {}
    for name, row in spec["company_feeds"].items():
        try:
            feeds[name] = _fetch_exact(row["url"], row["hosts"],
                                       ("application/rss+xml", "application/xml", "text/xml", "text/html"))
            captures[name + ".xml"] = feeds[name]
        except (OSError, ValueError):
            continue
    public_calendars = []
    next_start, next_end = end + timedelta(days=3), end + timedelta(days=9)
    for bank, row in spec["central_bank_calendars"].items():
        try:
            raw = _fetch_exact(row["url"], row["hosts"], ("text/html",))
            captures["calendar-" + str(len(public_calendars)) + ".html"] = raw
            public_calendars.append(parse_public_calendar(raw, next_start, next_end, bank, row["url"]))
        except (OSError, ValueError):
            continue
    results = stored_results(state_dir, start, end)
    packet = build_packet(end, fx_raw, decisions=decisions, statistics_raw=stat_raw,
                          results=results, company_feeds=feeds,
                          statistics_calendar_raw=stat_calendar_raw,
                          public_calendars=public_calendars, captured=captures, now=now)
    directory = Path(state_dir) / "intake" / digest(packet)
    directory.mkdir(parents=True, exist_ok=True)
    receipt = {"fixture": False, "kind": "weekly-economy", "retrieved_at": now.isoformat(),
               "packet_sha256": digest(packet), "publication_basis": packet["publication_basis"],
               "image_status": "explicit-text-only"}
    (directory / "captures.json").write_text(json.dumps(
        {name: value.decode("utf-8") for name, value in captures.items()},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (directory / "packet.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n")
    (directory / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    return packet, receipt


def can_admit(store, now=None, limit=1):
    now = now or datetime.now(timezone.utc)
    end = _friday(now) or (now.astimezone(HELSINKI).date() -
                           timedelta(days=(now.astimezone(HELSINKI).weekday() - 4) % 7))
    start, _ = week_bounds(end)
    count = 0
    for row in store.db.execute("SELECT packet,created_at FROM jobs WHERE created_at>=? AND created_at<?",
                                (start.isoformat(), (end + timedelta(days=3)).isoformat())):
        try:
            if json.loads(row["packet"]).get("kind") == "weekly-economy":
                count += 1
        except (TypeError, ValueError):
            pass
    return count < limit
