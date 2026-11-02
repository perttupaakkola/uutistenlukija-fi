"""Deterministic listed-company results intake and Uutistenlukija trend baseline."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

from .editorial import digest, validate_packet, web_url
from .intake import fetch


POLICY = Path(__file__).resolve().parents[1] / "sources/earnings.json"
HISTORY_SEED = Path(__file__).resolve().parents[1] / "data/earnings_history.json"
METHOD_PATH = "/talous/menetelma/"
REPORT_WORDS = ("osavuosikatsaus", "puolivuosikatsaus", "liiketoimintakatsaus",
                "tilinpäätöstiedote", "osavuosiraportti")
NUMBER = r"[-+]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[,.]\d+)?"
FORBIDDEN_TITLE = re.compile(
    r"\b(?:kutsu|julkaisee\b.*\b(?:\w*katsauks\w*|\w*raport\w*)|"
    r"(?:\w*katsaus\w*|\w*raport\w*)\b.*\bjulkaistaan|tulosjulkistukset|"
    r"taloudellinen (?:kalenteri|tiedottaminen)|vuosikertomus)\b", re.I)
FORBIDDEN_NOTICE = re.compile(
    r"\b(?:sisäpiiritieto|johtohenkilöiden liiketoimet|liputusilmoitus|"
    r"omien osakkeiden hankinta|takaisinosto)\b", re.I)

# Financial companies do not describe their top line as revenue. These are
# deliberately company-specific: a broad fallback could silently turn a
# segment or investment line into the history series. The first matching
# label is the company's consistently preferred series.
COMPANY_METRICS = {
    "Aktia": {
        "top_line": [(r"liiketoiminnan tuotot yhteensä", "liiketoiminnan tuotot yhteensä")],
        "profit": [(r"vertailukelpoinen liikevoitto", "vertailukelpoinen liikevoitto"),
                   (r"liikevoitto", "liikevoitto")],
    },
    "Nordea": {
        "top_line": [(r"liiketoiminnan tuotot yhteensä", "tuotot yhteensä")],
        "profit": [(r"liikevoitto", "liikevoitto")],
    },
    "Mandatum": {
        "top_line": [(r"palkkiotulos", "palkkiotulos")],
        "profit": [(r"pääomakevyen liiketoiminnan tulos ennen veroja",
                    "pääomakevyen liiketoiminnan tulos ennen veroja"),
                   (r"(?:tilikauden|konsernin) tulos ennen veroja", "tulos ennen veroja")],
    },
    "Sampo": {
        "top_line": [(r"vakuutusliikevaihto", "vakuutusliikevaihto"),
                     (r"insurance revenue", "vakuutusliikevaihto")],
        "profit": [(r"vakuutuspalvelutulos", "vakuutuspalvelutulos"),
                   (r"underwriting result", "vakuutustulos"),
                   (r"tulos ennen veroja", "tulos ennen veroja"),
                   (r"profit before taxes", "tulos ennen veroja")],
    },
}

DEFAULT_TOP_LINE = [
    (r"(?:konsernin\s+)?liikevaihto", "liikevaihto"),
    (r"(?:.{0,180}\s+)?raportoitu\s+liikevaihto", "liikevaihto"),
    (r"(?:comparable\s+)?net sales", "liikevaihto"),
    (r"sales", "liikevaihto"),
]
DEFAULT_PROFIT = [
    (r"oikaistu\s+liikevoitto", "oikaistu liikevoitto"),
    (r"vertailukelpoinen\s+liikevoitto", "vertailukelpoinen liikevoitto"),
    (r"oikaistu\s+liiketulos", "oikaistu liiketulos"),
    (r"oikaistu\s+ebita", "oikaistu EBITA"),
    (r"vertailukelpoinen\s+ebita", "vertailukelpoinen EBITA"),
    (r"liikevoitto", "liikevoitto"),
    (r"liiketulos(?:\s*\(ebit\))?", "liiketulos"),
    (r"comparable\s+operating profit(?:\s*/\s*\(loss\))?", "vertailukelpoinen liikevoitto"),
    (r"operating profit(?:\s*/\s*\(loss\))?", "liikevoitto"),
]

# A company may lead with an adjusted measure while also publishing the IFRS
# or otherwise reported operating result. The latter is not a substitute for
# the trend series, but it is required context in the article whenever present.
REPORTED_PROFIT = [
    (r"ifrs[\s-]+liiketulos", "IFRS-liiketulos"),
    (r"liiketulos\s*\(ifrs\)", "IFRS-liiketulos"),
    (r"ifrs[\s-]+liikevoitto", "IFRS-liikevoitto"),
    (r"raportoitu\s+liiketulos", "raportoitu liiketulos"),
    (r"raportoitu\s+liikevoitto", "raportoitu liikevoitto"),
    (r"liiketulos(?:\s*\(ebit\))?", "raportoitu liiketulos"),
    (r"liikevoitto", "raportoitu liikevoitto"),
]

BAD_PERCENT_CHANGE = re.compile(
    r"\b(?:nousi|kasvoi|laski|pieneni|heikkeni)\s+" + NUMBER +
    r"\s+prosentin\b", re.I)
ADJUSTMENT_REASON = re.compile(
    r"\b(?:pääosin|pääasiassa|merkittävin(?:tä)?\s+er(?:ä|ät)|"
    r"oikaisuerät?\s+(?:olivat|liittyivät)|"
    r"vertailukelpoisuuteen\s+vaikuttav(?:a|at|ia)\s+er(?:ä|ät|iä))\b", re.I)
ADJUSTMENT_SUBJECT = re.compile(
    r"käyvän\s+arvon|arvonalentu|uudelleenjärjest|luovut|alaskirj|"
    r"oikaisuer|vertailukelpoisuuteen|yrityskaupp|sovinto", re.I)


def policy():
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    if (value.get("mode") != "earnings-text-v1" or
            value.get("max_articles_per_day") != 6 or
            value.get("max_source_age_hours") != 48):
        raise ValueError("Unreviewed earnings source policy")
    return value


def policy_digest():
    return digest(policy())


def _fold(value):
    return " ".join(str(value or "").casefold().replace("\u00a0", " ").split())


def _company_for(title, spec=None):
    folded = _fold(title)
    matches = []
    for company in (spec or policy())["companies"]:
        names = [company["name"], *company.get("aliases", [])]
        if any(re.search(r"(?<!\w)" + re.escape(_fold(name)) + r"(?!\w)", folded)
               for name in names):
            matches.append(company)
    if len(matches) != 1:
        return None
    return matches[0]


def _period(title):
    value = _fold(title).replace("−", "-").replace("–", "-")
    year_match = re.search(r"\b(20\d{2})\b", value)
    if not year_match:
        return None
    year = int(year_match.group(1))
    if re.search(r"tammi\s*-\s*maalisk|january\s*-\s*march|1\.1\.?\s*-\s*31\.3|"
                 r"\bq1\b|\b1/20\d{2}\b", value):
        quarter, month, day = 1, 3, 31
    elif re.search(r"tammi\s*-\s*kesä|january\s*-\s*june|puolivuosi|half\s*-?\s*year|"
                   r"1\.1\.?\s*-\s*30\.6|\bq2\b|\b2/20\d{2}\b", value):
        quarter, month, day = 2, 6, 30
    elif re.search(r"tammi\s*-\s*syys|january\s*-\s*september|1\.1\.?\s*-\s*30\.9|"
                   r"\bq3\b|\b3/20\d{2}\b", value):
        quarter, month, day = 3, 9, 30
    elif ("tilinpäätöstiedote" in value or "full year" in value or
          "financial report" in value or
          re.search(r"1\.1\.?\s*-\s*31\.12|\bq4\b|\b4/20\d{2}\b", value)):
        quarter, month, day = 4, 12, 31
    else:
        return None
    return {"year": year, "quarter": quarter,
            "period": f"Q{quarter}/{year}", "period_end": f"{year:04d}-{month:02d}-{day:02d}"}


def classify_title(title, *, corrected_companies=(), spec=None):
    """Return (company, period, rejection); a rejection is always explicit."""
    value = _fold(title)
    company = _company_for(title, spec)
    if value.startswith("korjaus") or " korjaus " in f" {value} ":
        return company, _period(title), "correction"
    if FORBIDDEN_NOTICE.search(value):
        return company, _period(title), "insider/shareholding/buyback notice"
    if FORBIDDEN_TITLE.search(value) or " ja kutsuu" in value:
        return company, _period(title), "invitation or reporting schedule"
    if not any(word in value for word in REPORT_WORDS):
        return company, _period(title), "not a results report"
    period = _period(title)
    if period is None:
        return company, None, "report period is missing or ambiguous"
    if company is None:
        return None, period, "company is not on the curated Helsinki main-list allowlist"
    if company["name"] in corrected_companies:
        return company, period, "a correction exists; old version suppressed"
    return company, period, None


def _feed_items(raw, provider):
    try:
        items = ET.fromstring(raw).findall("./channel/item")
    except ET.ParseError as error:
        raise ValueError("Invalid earnings RSS") from error
    rows = []
    for item in items[:50]:
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "")
            if published.tzinfo is None:
                raise ValueError
            published = published.astimezone(timezone.utc)
        except (TypeError, ValueError):
            published = None
        rows.append({"provider": provider, "title": title, "url": url,
                     "published_at": published})
    return rows


def feed_decisions(feeds, now=None, excluded=()):
    """Classify every feed row, including the reasons needed by a dry run."""
    now = now or datetime.now(timezone.utc)
    spec = policy()
    rows = [row for provider, raw in feeds.items() for row in _feed_items(raw, provider)]
    corrected = {company["name"] for row in rows
                 for company in [_company_for(row["title"], spec)]
                 if company and _fold(row["title"]).startswith("korjaus")}
    result = []
    for row in rows:
        company, period, rejection = classify_title(
            row["title"], corrected_companies=corrected, spec=spec)
        provider = spec["feeds"].get(row["provider"])
        if rejection is None and (provider is None or
                not re.fullmatch(provider["article_pattern"], row["url"])):
            rejection = "unapproved article URL"
        if rejection is None and row["published_at"] is None:
            rejection = "missing RSS publication time"
        if rejection is None:
            age = (now - row["published_at"]).total_seconds()
            if not 0 <= age <= spec["max_source_age_hours"] * 3600:
                rejection = "stale or future-dated"
        if rejection is None and (row["url"] in excluded or
                                   "url:" + row["url"] in excluded):
            rejection = "already processed"
        result.append({**row, "company": company, "period_data": period,
                       "kept": rejection is None, "reason": rejection or "eligible report"})
    return result


def discover(config, now=None, excluded=(), errors=None):
    now = now or datetime.now(timezone.utc)
    spec = policy()
    feeds = {}
    for provider, feed in spec["feeds"].items():
        try:
            raw, mime, final = fetch(feed["url"], feed["hosts"])
            if final != feed["url"] or mime not in ("application/rss+xml", "application/xml",
                                                     "text/xml", "text/html"):
                raise ValueError("Unexpected earnings feed response")
            feeds[provider] = raw
        except (OSError, ValueError) as error:
            if errors is None:
                raise
            errors.append({"provider": f"earnings-{provider}", "stage": "discovery",
                           "error": str(error)[:300]})
    decisions = feed_decisions(feeds, now, excluded)
    kept = [row for row in decisions if row["kept"]]
    kept.sort(key=lambda row: (-row["company"]["priority"],
                               -row["published_at"].timestamp(), row["url"]))
    kept = kept[:spec["max_articles_per_day"]]
    return [{"family": "earnings", "provider": row["provider"], "url": row["url"],
             "title": row["title"], "published_at": row["published_at"].isoformat(),
             "company": row["company"]["name"], "priority": row["company"]["priority"],
             "story_key": f"earnings:{row['company']['name']}:{row['period_data']['period_end']}",
             **row["period_data"]} for row in kept]


class ReleaseHTML(HTMLParser):
    def __init__(self, provider):
        super().__init__()
        self.provider = provider
        self.stack = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        inherited = self.stack[-1][1] if self.stack else False
        if self.provider == "cision":
            selected = tag == "article"
        elif self.provider == "official":
            # Official IR sites use several CMS layouts. Selecting body while
            # retaining the nav/script/style blocks below keeps the financial
            # table readable without depending on presentation classes.
            selected = tag in ("body", "main", "article")
        else:
            selected = attrs.get("data-cypress") == "announcement-content"
        blocked = tag in ("script", "style", "nav", "svg", "figure")
        self.stack.append((tag, inherited or selected, blocked or
                           (self.stack[-1][2] if self.stack else False)))
        if tag in ("p", "li", "h1", "h2", "h3", "tr", "br"):
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append("\t")

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if tag in ("p", "li", "h1", "h2", "h3", "tr", "table"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self.stack and self.stack[-1][1] and not self.stack[-1][2]:
            self.parts.append(data)

    def text(self):
        lines = []
        for raw in "".join(self.parts).splitlines():
            cells = [" ".join(cell.replace("\u00a0", " ").split())
                     for cell in raw.split("\t")]
            value = "\t".join(cell for cell in cells if cell)
            if value:
                lines.append(value)
        return "\n".join(lines)


def release_text(raw, provider):
    parser = ReleaseHTML(provider)
    parser.feed(raw.decode("utf-8"))
    value = parser.text()
    if len(value) < 200:
        raise ValueError("Missing substantive earnings release text")
    return value


def _decimal(value):
    try:
        return Decimal(value.replace("\u00a0", "").replace("\u202f", "")
                       .replace(" ", "").replace(",", "."))
    except (InvalidOperation, AttributeError) as error:
        raise ValueError("Invalid financial number") from error


def _display(value):
    return format(_decimal(value), "f").replace(".", ",")


def _line_metrics(text, labels):
    rows = []
    lines = text.splitlines()
    for position, line in enumerate(lines):
        clean = line.replace("*", "").strip().lstrip("•- ")
        for label in labels:
            match = re.match(r"^" + label +
                             r"(?:\s*,?\s*(?:euroa|milj\. euroa))?(?:\s+(.*))?$",
                             clean, re.I)
            if not match:
                continue
            tail = match.group(1) or ""
            if re.match(r"ei\s+sisällä\b", tail, re.I):
                # Reconciliation prose describes excluded adjustment items,
                # not the operating-profit row itself.
                continue
            values = re.findall(NUMBER, tail)
            stated_change = None
            amount = (re.search(r"(" + NUMBER + r")\s*\((" + NUMBER +
                                r")\)\s*(?:milj(?:oonaa|\.)?|miljoonaa)\s+euro", tail, re.I)
                      or re.search(r"(" + NUMBER +
                                   r")\s*(?:miljoonaan|milj\.?)\s+euroon\s*\((" +
                                   NUMBER + r")\)", tail, re.I))
            if "liikevaihto" in label and tail and not amount and "euro" not in tail.casefold():
                # A sentence that gives only growth percentages is not a revenue amount.
                continue
            if amount:
                before_amount = tail[:amount.start()]
                stated = re.findall(r"(" + NUMBER + r")\s*%", before_amount)
                if stated:
                    stated_value = _decimal(stated[-1])
                    if re.search(r"\b(?:laski|laskivat|pieneni|heikkeni)\b", before_amount, re.I):
                        stated_value = -abs(stated_value)
                    stated_change = str(stated_value)
                values = [amount.group(1), amount.group(2), *values]
            if len(values) < 2:
                continuation = []
                for following in lines[position + 1:position + 9]:
                    candidate = following.strip()
                    if re.fullmatch(NUMBER + r"\s*%?", candidate):
                        if len(continuation) == 2 and candidate.endswith('%'):
                            stated_change = str(_decimal(re.findall(NUMBER, candidate)[0]))
                        continuation.extend(re.findall(NUMBER, candidate))
                    else:
                        break
                values.extend(continuation)
            # Some tables append a footnote marker to the row label and put
            # all actual values on following lines ("... liikevoitto 1").
            if (tail.strip() in ("1", "2", "3") and len(values) >= 3 and
                    not re.search(r"(?:euro|%)", tail, re.I)):
                values = values[1:]
            # Table footnote immediately after the unit, e.g. "euroa 2 0,18 0,27".
            if len(values) >= 3 and values[0] in ("1", "2", "3") and "euroa" in clean:
                values = values[1:]
            if len(values) >= 2:
                rows.append({"position": position, "line": clean, "label": label,
                             "values": values, "stated_change": stated_change})
    return rows


def _select_metric(text, labels, field, near=None, label_name=None):
    rows = _line_metrics(text, labels)
    all_rows = rows[:]
    if not rows:
        raise ValueError(f"Missing unambiguous core figure: {field}")
    if near is not None:
        distance = min(abs(row["position"] - near) for row in rows)
        rows = [row for row in rows if abs(row["position"] - near) == distance]
    else:
        # The first key-figure block is the reported quarter; later blocks are YTD,
        # segment or IFRS reconciliations. Two conflicting rows inside that same small
        # block are genuinely ambiguous and fail closed.
        first = rows[0]
        rows = [row for row in rows if row["position"] <= first["position"] + 4]
    pairs = {(_decimal(row["values"][0]), _decimal(row["values"][1])) for row in rows}
    if len(pairs) != 1:
        raise ValueError(f"Ambiguous core figure: {field}")
    row = rows[0]
    current, comparison = row["values"][:2]
    change = ((_decimal(current) - _decimal(comparison)) / abs(_decimal(comparison)) * 100
              if _decimal(comparison) else None)
    stated_change = row.get('stated_change')
    if stated_change is None:
        matching = [candidate.get('stated_change') for candidate in all_rows
                    if candidate.get('stated_change') is not None and
                    (_decimal(candidate['values'][0]), _decimal(candidate['values'][1])) ==
                    (_decimal(current), _decimal(comparison))]
        if matching:
            stated_change = matching[0]
    # Prefer a rounded change stated in prose only when that same line also
    # contains this exact current/comparison pair. This prevents a Q2 row from
    # accidentally inheriting the H1 percentage later in the release.
    term = (r"(?:(?:raportoitu|konsernin)\s+)?(?:liikevaihto|tuotot yhteensä|"
            r"vakuutusliikevaihto|palkkiotulos)" if field == "revenue" else
            r"(?:oikaistu|vertailukelpoinen)\s+(?:liikevoitto|liiketulos|ebita)")
    for prose_line in text.splitlines():
        stated = re.search(term + r"\s+(?:oli\s+[^.!]{0,60}?[,;]\s*)?"
                            r"(nousi|kasvoi|laski|pieneni|heikkeni)\s+"
                            r"(?:noin\s+)?(" + NUMBER + r")\s*%", prose_line, re.I)
        line_values = {_decimal(value) for value in re.findall(NUMBER, prose_line)}
        if (stated and _decimal(current) in line_values and
                _decimal(comparison) in line_values):
            stated_value = _decimal(stated.group(2))
            if stated.group(1).casefold() in ('laski', 'pieneni', 'heikkeni'):
                stated_value = -abs(stated_value)
            stated_change = str(stated_value)
            break
    if stated_change is None and field == "operating_profit":
        # A compact highlights block may state the rounded change on a
        # separate line from the amount. Limit this fallback to the opening
        # block so a later YTD or segment percentage cannot leak into Q2/Q3.
        opening = "\n".join(text.splitlines()[:25])
        stated = re.search(
            r"(?:oikaistu|vertailukelpoinen)\s+(?:liikevoitto|liiketulos|ebita)\s+"
            r"(nousi|kasvoi|laski|pieneni|heikkeni)\s+(" + NUMBER + r")\s*%",
            opening, re.I)
        if stated:
            stated_value = _decimal(stated.group(2))
            if stated.group(1).casefold() in ('laski', 'pieneni', 'heikkeni'):
                stated_value = -abs(stated_value)
            stated_change = str(stated_value)
    change_text = (stated_change if stated_change is not None else
                   str(change.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
                   if change is not None else None)
    label_name = label_name or {"revenue": "liikevaihto",
                                "operating_profit": "liikevoitto",
                                "eps": "osakekohtainen tulos"}.get(field, field)
    return {"label": label_name,
            "series": label_name.casefold(),
            "value": str(_decimal(current)), "display": _display(current),
            "comparison": str(_decimal(comparison)),
            "comparison_display": _display(comparison),
            "change_percent": change_text,
            "position": row["position"], "source_line": row["line"]}


def _extract_ytd(text, labels, quarter):
    if quarter == 4:
        return None
    headings = {1: r"tammi\s*[\u2013-]\s*maaliskuu(?:n)?", 2: r"tammi\s*[\u2013-]\s*kesäkuu(?:n)?",
                3: r"tammi\s*[\u2013-]\s*syyskuu(?:n)?"}
    lines = text.splitlines()
    start = [index for index, line in enumerate(lines)
             if re.match(r"^" + headings[quarter] + r"\b", line.strip(), re.I)]
    for index in start:
        window = "\n".join(lines[index + 1:index + 18])
        for label in labels:
            rows = _line_metrics(window, [label])
            if rows:
                return str(_decimal(rows[0]["values"][0]))
    return None


def _outlook(text):
    lines = text.splitlines()
    indices = [i for i, line in enumerate(lines)
               if re.match(r"^(?:tarkennettu\s+|muutettu\s+|päivitetty\s+)?(?:tulosohjeistus|"
                           r"ohjeistus|näkymät|markkinanäkymät|"
                           r"ohjeistus\s+ja\s+näkymät)\b", line.strip(" *#"), re.I)]
    if not indices:
        return None
    blocks = [" ".join(lines[index:index + 10]) for index in indices]
    blocks.sort(key=lambda block: (not bool(re.search(
        r"\b(?:kaventaa|tarkentaa|nosti|nostaa|laskee|laski|muuttaa|muutti)\b", block, re.I)),
        not block.casefold().startswith("ohjeistus")))
    block = blocks[0]
    sentences = re.split(r"(?<=[.!?])\s+", block)
    useful = [sentence.strip() for sentence in sentences
              if re.search(r"odottaa|ohjeistus|näkym", sentence, re.I)]
    if not useful:
        return None
    value = " ".join(useful[:3])
    changed = bool(re.search(r"\b(?:kaventaa|tarkentaa|nosti|nostaa|laskee|laski|muuttaa|muutti)\b",
                             block, re.I)) and not bool(re.search(r"ennallaan", block, re.I))
    return {"text": value[:1600], "changed": changed}


def _first_metric(text, specs, field, near=None):
    for pattern, label in specs:
        if _line_metrics(text, [pattern]):
            return _select_metric(text, [pattern], field, near, label), pattern
    raise ValueError(f"Missing unambiguous core figure: {field}")


def _reported_profit(text, selected_profit):
    """Return the quarter's reported result when an adjusted series leads."""
    if not re.search(r"oikaistu|vertailukelpoinen|comparable|adjusted",
                     selected_profit.get("series", ""), re.I):
        return None
    for pattern, label in REPORTED_PROFIT:
        if _line_metrics(text, [pattern]):
            return _select_metric(text, [pattern], "reported_operating_profit",
                                  selected_profit["position"], label)
    return None


def _divergence_reason(text, adjusted, reported):
    """Require a company-stated adjustment reason for a gap over 30 percent."""
    adjusted_value = _decimal(adjusted["value"])
    reported_value = _decimal(reported["value"])
    denominator = abs(adjusted_value)
    if denominator == 0:
        denominator = max(abs(reported_value), Decimal("1"))
    difference = abs(adjusted_value - reported_value) / denominator * 100
    if difference <= 30:
        return None

    candidates = []
    for position, line in enumerate(text.splitlines()):
        if ADJUSTMENT_REASON.search(line) and ADJUSTMENT_SUBJECT.search(line):
            # Keep the complete source line. Splitting on a period would break
            # Finnish financial abbreviations such as "milj. euroa" and could
            # silently discard the first of several principal adjustments.
            candidates.append((abs(position - reported["position"]), position,
                               line.strip()))
    if not candidates:
        raise ValueError("Missing company-stated reason for sharp reported/adjusted divergence")
    reason = min(candidates)[2]
    return {"difference_percent": str(difference.quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP)),
            "reason": reason}


def _core_figures(text, company=None):
    company_spec = COMPANY_METRICS.get(company, {})
    profit, selected_label = _first_metric(
        text, company_spec.get("profit", DEFAULT_PROFIT), "operating_profit")
    revenue, _ = _first_metric(
        text, company_spec.get("top_line", DEFAULT_TOP_LINE), "revenue", profit["position"])
    reported_profit = _reported_profit(text, profit)
    divergence = (_divergence_reason(text, profit, reported_profit)
                  if reported_profit is not None else None)
    try:
        eps = _select_metric(text, [
            r"(?:vertailukelpoinen\s+|oikaistu\s+)?osakekohtainen\s+tulos"
            r"(?:\s*\(eps\))?(?!\s+ilman)"
            r"(?:,?\s*(?:laimennettu|laimentamaton))?(?:,?\s*(?:euroa|€))?",
            r"(?:laimennettu\s+)?tulos\s*/\s*osake(?:,?\s*(?:euroa|€))?",
            r"laimennettu\s+osakekohtainen\s+tulos(?:,?\s*euroa)?",
            r"(?:comparable\s+)?(?:diluted\s+)?eps(?:\s+for the period)?",
            r"(?:basic|diluted)\s+earnings per share",
        ], "eps", profit["position"])
    except ValueError:
        eps = None
    for metric in (revenue, profit, reported_profit):
        if metric is None:
            continue
        metric["unit"] = "milj. euroa"
        metric.pop("position", None)
    figures = {"revenue": revenue, "operating_profit": profit}
    if reported_profit is not None:
        figures["reported_operating_profit"] = reported_profit
    if eps is not None:
        eps["unit"] = "euroa"
        eps.pop("position", None)
        figures["eps"] = eps
    return figures, selected_label, divergence


def extract_figures(text, company=None):
    """Extract the release's quarter figures independently of publication eligibility."""
    return _core_figures(text, company)[0]


def extract_report(text, company, title, published_at):
    """Extract required history figures and optional article figures deterministically."""
    period = _period(title)
    if period is None:
        raise ValueError("Missing report period")
    figures, selected_label, divergence = _core_figures(text, company)
    ytd = _extract_ytd(text, [selected_label], period["quarter"])
    report = {"company": company, "title": title, "published_at": published_at,
              **period, "figures": figures, "outlook": _outlook(text)}
    if ytd is not None:
        report["ytd_operating_profit"] = ytd
    if divergence is not None:
        report["operating_profit_divergence"] = divergence
    return report


HISTORY_SCHEMA = """CREATE TABLE IF NOT EXISTS earnings_history (
    company TEXT NOT NULL, period_end TEXT NOT NULL, quarter INTEGER NOT NULL,
    revenue TEXT NOT NULL, operating_profit TEXT NOT NULL, eps TEXT,
    source_url TEXT NOT NULL, report_json TEXT NOT NULL,
    PRIMARY KEY(company, period_end)
)"""


def _history_db(state_dir):
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(Path(state_dir) / "earnings.sqlite", timeout=10)
    db.row_factory = sqlite3.Row
    db.execute(HISTORY_SCHEMA)
    _load_history_seed(db)
    db.commit()
    return db


def history_seed():
    """Return the reviewed archive seed, including explicit allowlist coverage."""
    value = json.loads(HISTORY_SEED.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1:
        raise ValueError("Unsupported earnings history seed")
    allowed = {row["name"] for row in policy()["companies"]}
    coverage = value.get("coverage")
    reports = value.get("reports")
    if not isinstance(coverage, dict) or set(coverage) != allowed or not isinstance(reports, list):
        raise ValueError("Earnings history seed does not cover the allowlist")
    for company, row in coverage.items():
        if (not isinstance(row, dict) or not isinstance(row.get("attempted_reports"), int) or
                row["attempted_reports"] < 0 or not isinstance(row.get("stored_quarters"), int) or
                row["stored_quarters"] < 0):
            raise ValueError(f"Invalid earnings seed coverage: {company}")
    return value


def _load_history_seed(db):
    seed = history_seed()
    for row in seed["reports"]:
        report = row.get("report")
        figures = report.get("figures") if isinstance(report, dict) else None
        if (not isinstance(figures, dict) or report.get("company") not in seed["coverage"] or
                row.get("source_url") is None):
            raise ValueError("Invalid earnings history seed report")
        db.execute("""INSERT OR IGNORE INTO earnings_history
            (company,period_end,quarter,revenue,operating_profit,eps,source_url,report_json)
            VALUES(?,?,?,?,?,?,?,?)""",
            (report["company"], report["period_end"], report["quarter"],
             figures["revenue"]["value"], figures["operating_profit"]["value"],
             figures.get("eps", {}).get("value", ""), row["source_url"],
             json.dumps(report, ensure_ascii=False, sort_keys=True)))


def store_report(state_dir, report, source_url):
    with _history_db(state_dir) as db:
        figures = report["figures"]
        db.execute("""INSERT INTO earnings_history
            (company,period_end,quarter,revenue,operating_profit,eps,source_url,report_json)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(company,period_end) DO UPDATE SET
            revenue=excluded.revenue,operating_profit=excluded.operating_profit,
            eps=excluded.eps,source_url=excluded.source_url,report_json=excluded.report_json""",
            (report["company"], report["period_end"], report["quarter"],
             figures["revenue"]["value"], figures["operating_profit"]["value"],
             figures.get("eps", {}).get("value", ""), source_url,
             json.dumps(report, ensure_ascii=False, sort_keys=True)))
        if all("comparison" in figures[field]
               for field in ("revenue", "operating_profit")):
            # A newer release is authoritative for its restated comparison quarter.
            comparison_year = report["year"] - 1
            month, day = ((3, 31), (6, 30), (9, 30), (12, 31))[report["quarter"] - 1]
            comparison_end = f"{comparison_year:04d}-{month:02d}-{day:02d}"
            comparison = {"company": report["company"], "year": comparison_year,
                          "quarter": report["quarter"],
                          "period": f"Q{report['quarter']}/{comparison_year}",
                          "period_end": comparison_end, "restated_by": report["period_end"],
                          "figures": {field: {"value": metric["comparison"],
                                              "label": metric.get("label"),
                                              "series": metric.get("series")}
                                      for field, metric in figures.items()
                                      if "comparison" in metric}}
            db.execute("""INSERT INTO earnings_history
                (company,period_end,quarter,revenue,operating_profit,eps,source_url,report_json)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(company,period_end) DO UPDATE SET
                revenue=excluded.revenue,operating_profit=excluded.operating_profit,
                eps=excluded.eps,source_url=excluded.source_url,report_json=excluded.report_json""",
                (comparison["company"], comparison_end, comparison["quarter"],
                 comparison["figures"]["revenue"]["value"],
                 comparison["figures"]["operating_profit"]["value"],
                 comparison["figures"].get("eps", {}).get("value", ""), source_url,
                 json.dumps(comparison, ensure_ascii=False, sort_keys=True)))


def trend_baseline(state_dir, report):
    with _history_db(state_dir) as db:
        rows = db.execute("""SELECT * FROM earnings_history WHERE company=? AND period_end<?
            ORDER BY period_end DESC LIMIT 4""",
            (report["company"], report["period_end"])).fetchall()
    if len(rows) < 4:
        return {"available": False, "reason": "fewer than four prior quarters",
                "prior_quarters": len(rows)}
    rows = list(reversed(rows))
    if [row["quarter"] for row in rows] != [report["quarter"],
            report["quarter"] % 4 + 1, (report["quarter"] + 1) % 4 + 1,
            (report["quarter"] + 2) % 4 + 1]:
        return {"available": False, "reason": "four prior quarters are not consecutive",
                "prior_quarters": len(rows)}
    current_series = {field: report["figures"][field].get("series")
                      for field in ("revenue", "operating_profit")}
    for row in rows:
        saved = json.loads(row["report_json"])
        for field, series in current_series.items():
            if saved.get("figures", {}).get(field, {}).get("series") != series:
                return {"available": False,
                        "reason": (f"{field} series changed; adjusted and reported "
                                   "figures are not mixed"),
                        "prior_quarters": 4}
    result = {"available": True, "prior_quarters": 4,
              "method": "same quarter last year scaled by the mean sequential growth of the three following reported quarters"}
    for field in ("revenue", "operating_profit"):
        values = [_decimal(row[field]) for row in rows]
        # The current release's comparison column is the newest statement of the
        # same quarter last year and therefore wins over an older archive row.
        if "comparison" in report["figures"][field]:
            values[0] = _decimal(report["figures"][field]["comparison"])
        if any(value == 0 for value in values[:-1]):
            return {"available": False, "reason": f"zero prevents {field} growth calculation",
                    "prior_quarters": 4}
        growth = sum((values[i] / values[i - 1] - 1 for i in range(1, 4)), Decimal(0)) / 3
        expected = values[0] * (1 + growth)
        actual = _decimal(report["figures"][field]["value"])
        deviation = ((actual - expected) / abs(expected) * 100) if expected else Decimal(0)
        result[field] = {"expected": str(expected.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)),
                         "deviation_percent": str(deviation.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))}
    deviation = _decimal(result["operating_profit"]["deviation_percent"])
    result["comparison"] = ("linjassa" if abs(deviation) <= 2 else
                            "yläpuolella" if deviation > 0 else "alapuolella")
    return result


def _seasonal_history(state_dir, report):
    if state_dir is None or report["quarter"] != 3:
        return [], "seasonal check requires Q3 and persisted history"
    with _history_db(state_dir) as db:
        rows = db.execute("""SELECT year,quarter,operating_profit,report_json FROM (
            SELECT CAST(substr(period_end,1,4) AS INTEGER) AS year,quarter,operating_profit,
                   report_json
            FROM earnings_history WHERE company=? AND period_end<?)
            ORDER BY year DESC,quarter""",
            (report["company"], report["period_end"])).fetchall()
    years = {}
    for row in rows:
        saved = json.loads(row["report_json"])
        if (saved.get("figures", {}).get("operating_profit", {}).get("series") !=
                report["figures"]["operating_profit"].get("series")):
            return [], "operating-profit series changed; adjusted and reported figures are not mixed"
        years.setdefault(row["year"], {})[row["quarter"]] = _decimal(row["operating_profit"])
    shares = []
    for year in sorted(years, reverse=True):
        quarters = years[year]
        if set(quarters) != {1, 2, 3, 4}:
            continue
        full_year = sum(quarters.values(), Decimal(0))
        if full_year == 0:
            continue
        share = quarters[4] / full_year
        if not Decimal("-0.5") <= share <= Decimal("0.8"):
            continue
        shares.append((year, share))
    if len(shares) < 2:
        return shares, "fewer than two complete prior years of history"
    if max(value for _, value in shares) - min(
            value for _, value in shares) > Decimal("0.10"):
        return shares, "Q4 seasonal share is unstable"
    return shares, None


def guidance_check(report, state_dir=None):
    ytd = report.get("ytd_operating_profit")
    if ytd is None or report["quarter"] not in (1, 2, 3):
        return {"available": False, "reason": "numeric year-to-date operating profit unavailable"}
    outlook_data = report.get("outlook")
    if not isinstance(outlook_data, dict) or not outlook_data.get("text"):
        return {"available": False, "reason": "no outlook/guidance in release"}
    outlook = outlook_data["text"]
    match = re.search(r"(" + NUMBER + r")\s*[\u2013-]\s*(" + NUMBER +
                      r")\s*(?:miljoonaa|milj\.)\s+euro", outlook, re.I)
    if not match:
        return {"available": False, "reason": "no numeric annual guidance range"}
    low, high = _decimal(match.group(1)), _decimal(match.group(2))
    shares, reason = _seasonal_history(state_dir, report)
    if reason:
        return {"available": False, "reason": reason}
    used_shares = shares[:2]
    q4_share = sum((share for _, share in used_shares), Decimal(0)) / len(used_shares)
    if q4_share == 1:
        return {"available": False, "reason": "invalid Q4 seasonal share"}
    annualized = _decimal(ytd) / (1 - q4_share)
    return {"available": True, "low": str(low), "high": str(high),
            "seasonally_estimated_full_year": str(annualized.quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP)),
            "q4_share": str((q4_share * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)),
            "seasonal_years": [year for year, _ in used_shares],
            "on_track": low <= annualized <= high,
            "position": ("ohjeistuksen alapuolella" if annualized < low else
                         "ohjeistuksen yläpuolella" if annualized > high else
                         "ohjeistushaarukassa")}


def baseline_sentence(baseline):
    if not baseline.get("available"):
        return ""
    result = baseline["operating_profit"]
    return ("Tulos oli Uutistenlukijan laskeman trendiodotuksen " + baseline["comparison"] +
            f" (odotus {result['expected'].replace('.', ',')} milj. euroa, poikkeama " +
            f"{result['deviation_percent'].replace('.', ',')} %). Laskelma perustuu yhtiön "
            f"aiempiin neljänneksiin; menetelmä: {METHOD_PATH}")


def _numeric_values(value):
    prose = str(value).replace("\u2212", "-")
    # Finnish prose often uses an en dash as a minus sign.  Do not rewrite the
    # same character inside a numeric range such as 80–90.
    prose = re.sub(r"(?<!\d)\u2013(?=\d)", "-", prose)
    return {_decimal(match.group(0)) for match in re.finditer(NUMBER, prose)}


def figure_check(draft, packet):
    """Reject any draft number absent from the captured release or computed baseline."""
    if packet.get("kind") != "earnings":
        return True
    report = packet.get("earnings")
    if not isinstance(report, dict):
        raise ValueError("Earnings packet lacks extracted figures")
    passages = [str(draft.get("title", "")), str(draft.get("summary", "")),
                *[str(row.get("text", "")) for row in draft.get("paragraphs", [])]]
    prose = " ".join(passages)
    from .weekly_economy import reject_missing_calculation_meta
    reject_missing_calculation_meta(prose)
    if re.search(r"analyytik(?:ot|kojen|koiden)|konsensus", prose, re.I):
        raise ValueError("Earnings draft must not imply analyst consensus")
    if draft.get("category") != "Talous":
        raise ValueError("Earnings draft must use category Talous")
    if BAD_PERCENT_CHANGE.search(str(draft.get("title", ""))):
        raise ValueError("Use prosentilla, not a numeric 'nousi/laski N prosentin', in title")

    reported = report.get("figures", {}).get("reported_operating_profit")
    if isinstance(reported, dict):
        reported_sentences = " ".join(
            passage for passage in passages
            if (re.search(r"\b(?:raportoit\w*|ifrs)\b", passage, re.I) and
                re.search(r"liikevoi|liiketulo", passage, re.I)))
        required = {_decimal(reported["value"]), _decimal(reported["comparison"])}
        if not required.issubset(_numeric_values(reported_sentences)):
            raise ValueError("Draft must report current and comparison IFRS/reported operating result")

    divergence = report.get("operating_profit_divergence")
    if isinstance(divergence, dict):
        reason = str(divergence.get("reason", ""))
        stems = [stem for stem in ("käyvän arvon", "arvonalentu", "uudelleenjärjest",
                                    "luovut", "alaskirj", "yrityskaupp", "sovinto")
                 if stem in reason.casefold()]
        entities = re.findall(r"\b[A-ZÅÄÖ][\wÅÄÖåäö-]+(?:\s+[A-ZÅÄÖ][\wÅÄÖåäö-]+)*\s+(?:Oyj|Ky|Ab)\b",
                              reason)
        folded_prose = prose.casefold()
        if stems and not any(stem in folded_prose for stem in stems):
            raise ValueError("Draft must name the company-stated reason for sharp profit divergence")
        if entities and not any(entity.casefold() in folded_prose for entity in entities):
            raise ValueError("Draft must name the company-stated entity behind sharp profit divergence")
    allowed = _numeric_values(packet["sources"][0]["text"])
    allowed |= _numeric_values(json.dumps({"report": report,
                                            "baseline": packet.get("earnings_baseline"),
                                            "guidance": packet.get("guidance_check")},
                                           ensure_ascii=False))
    unexpected = sorted(_numeric_values(prose) - allowed)
    if unexpected:
        raise ValueError("Draft contains number(s) absent from release/extraction: " +
                         ", ".join(format(value, "f") for value in unexpected))
    return True


def collect(recipe, state_dir, now=None):
    now = now or datetime.now(timezone.utc)
    spec = policy()
    provider = recipe.get("provider")
    feed = spec["feeds"].get(provider)
    url = web_url(recipe.get("url"))
    if feed is None or not re.fullmatch(feed["article_pattern"], url):
        raise ValueError("Unapproved earnings article URL")
    raw, mime, final = fetch(url, feed["hosts"])
    if final != url or mime != "text/html":
        raise ValueError("Unexpected earnings article response")
    body = release_text(raw, provider)
    if recipe.get("title") not in body:
        raise ValueError("Earnings feed/article title mismatch")
    company = recipe.get("company")
    report = extract_report(body, company, recipe["title"], recipe["published_at"])
    baseline = trend_baseline(state_dir, report)
    guidance = guidance_check(report, state_dir)
    source = {"id": "A", "url": url, "publisher": f"Lähde: {company} (pörssitiedote)",
              "title": recipe["title"], "published_at": recipe["published_at"], "text": body}
    packet = {"kind": "earnings", "story_key": f"earnings:{company}:{report['period_end']}",
              "fixture": False, "sources": [source], "image": None,
              "image_note": "Ei yhtiön kuvaa: tulosuutinen saa vain ihmisettömän konseptikuvan.",
              "earnings": report, "earnings_baseline": baseline,
              "guidance_check": guidance,
              "publication_basis": {"policy": spec["mode"],
                  "policy_sha256": policy_digest(), "provider": "earnings",
                  "wire_provider": provider, "source_sha256": hashlib.sha256(raw).hexdigest(),
                  "source_fields_sha256": digest(source)}}
    validate_packet(packet, now, spec["max_source_age_hours"])
    directory = Path(state_dir) / "intake" / digest(packet)
    directory.mkdir(parents=True, exist_ok=True)
    receipt = {"fixture": False, "kind": "earnings", "retrieved_at": now.isoformat(),
               "source_url": url, "source_sha256": hashlib.sha256(raw).hexdigest(),
               "packet_sha256": digest(packet), "publication_basis": packet["publication_basis"],
               "image_status": "explicit-text-only"}
    (directory / "source.html").write_bytes(raw)
    (directory / "packet.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n")
    (directory / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    store_report(state_dir, report, url)
    return packet, receipt


def backfill_history(state_dir, releases):
    """Load previously captured archive releases without granting network access here."""
    count = 0
    spec = policy()
    for release in releases:
        company = next((row for row in spec['companies']
                        if row['name'] == release.get('company')), None)
        if company is None or not any(re.fullmatch(feed['article_pattern'],
                                                   web_url(release.get('url')))
                                      for feed in spec['feeds'].values()):
            raise ValueError('Unapproved earnings archive release')
        report = extract_report(release["text"], release["company"], release["title"],
                                release["published_at"])
        store_report(state_dir, report, release["url"])
        count += 1
    return count


def can_admit(store, now=None, limit=6):
    now = now or datetime.now(timezone.utc)
    prefix = now.date().isoformat()
    count = 0
    for row in store.db.execute("SELECT packet,created_at FROM jobs WHERE created_at LIKE ?",
                                (prefix + "%",)):
        try:
            if json.loads(row["packet"]).get("kind") == "earnings":
                count += 1
        except (TypeError, ValueError):
            pass
    return count < limit
