"""Subscribable iCalendar feed of Finnish holidays and dated key days 2026-2027.

Every event links back to the guide that explains it, so calendar subscribers return
to the site when the day comes. Dates are calendar facts mirrored from the guides.
"""
from datetime import date, timedelta, timezone

ORIGIN = 'https://uutistenlukija.fi'
PATH = '/kalenteri/suomen-pyhapaivat.ics'

# (date, summary, guide path)
EVENTS = (
    (date(2026, 10, 31), 'Pyhäinpäivä ja halloween', '/oppaat/pyhainpaiva-halloween-2026/'),
    (date(2026, 11, 1), 'Talvirengaskausi alkaa (1.11.–31.3.)', '/oppaat/talvirenkaat-2026/'),
    (date(2026, 11, 3), 'Veronpalautuksen 1. maksupäivä', '/oppaat/veronpalautus-2026/'),
    (date(2026, 11, 8), 'Isänpäivä (liputuspäivä)', '/oppaat/isanpaiva-2026/'),
    (date(2026, 11, 27), 'Black Friday', '/oppaat/black-friday-2026/'),
    (date(2026, 11, 29), '1. adventtisunnuntai', '/oppaat/adventti-2026/'),
    (date(2026, 12, 3), 'Veronpalautuksen 2. maksupäivä', '/oppaat/veronpalautus-2026/'),
    (date(2026, 12, 6), 'Itsenäisyyspäivä (liputuspäivä)', '/oppaat/itsenaisyyspaiva-2026/'),
    (date(2026, 12, 24), 'Jouluaatto', '/oppaat/joulu-2026/'),
    (date(2026, 12, 25), 'Joulupäivä', '/oppaat/joulu-2026/'),
    (date(2026, 12, 26), 'Tapaninpäivä', '/oppaat/joulu-2026/'),
    (date(2026, 12, 31), 'Uudenvuodenaatto', '/oppaat/joulu-2026/'),
    (date(2027, 1, 1), 'Uudenvuodenpäivä', '/oppaat/pyhapaivat-2027/'),
    (date(2027, 1, 6), 'Loppiainen', '/oppaat/pyhapaivat-2027/'),
    (date(2027, 3, 26), 'Pitkäperjantai', '/oppaat/paasiainen-2027/'),
    (date(2027, 3, 28), 'Pääsiäispäivä; kesäaika alkaa (kellot tunti eteenpäin)', '/oppaat/paasiainen-2027/'),
    (date(2027, 3, 29), '2. pääsiäispäivä', '/oppaat/paasiainen-2027/'),
    (date(2027, 4, 18), 'Eduskuntavaalit (vaalipäivä)', '/oppaat/eduskuntavaalit-2027/'),
    (date(2027, 5, 1), 'Vappu', '/oppaat/pyhapaivat-2027/'),
    (date(2027, 5, 6), 'Helatorstai', '/oppaat/pyhapaivat-2027/'),
    (date(2027, 5, 16), 'Helluntai', '/oppaat/pyhapaivat-2027/'),
    (date(2027, 6, 25), 'Juhannusaatto', '/oppaat/pyhapaivat-2027/'),
    (date(2027, 6, 26), 'Juhannuspäivä', '/oppaat/pyhapaivat-2027/'),
    (date(2027, 12, 6), 'Itsenäisyyspäivä', '/oppaat/pyhapaivat-2027/'),
    (date(2027, 12, 24), 'Jouluaatto', '/oppaat/pyhapaivat-2027/'),
    (date(2027, 12, 25), 'Joulupäivä', '/oppaat/pyhapaivat-2027/'),
    (date(2027, 12, 26), 'Tapaninpäivä', '/oppaat/pyhapaivat-2027/'),
)


def _fold(line):
    raw = line.encode('utf-8')
    out, cur = [], b''
    for ch in line:
        b = ch.encode('utf-8')
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur)
            cur = b''
        cur += b
    out.append(cur)
    return '\r\n '.join(x.decode('utf-8') for x in out) if raw else line


def _esc(text):
    return text.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def ics(now):
    stamp = now.astimezone(timezone.utc).strftime('%Y%m%dT000000Z')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Uutistenlukija//Suomen pyhapaivat//FI',
             'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', 'X-WR-CALNAME:Suomen pyhäpäivät ja tärkeät päivät',
             'X-WR-CALDESC:' + _esc('Arkipyhät, liputuspäivät, veronpalautukset ja muut päivät 2026–2027. '
                                    'Jokaisessa merkinnässä linkki Uutistenlukijan oppaaseen.'),
             'X-WR-TIMEZONE:Europe/Helsinki', 'REFRESH-INTERVAL;VALUE=DURATION:P1D',
             'X-PUBLISHED-TTL:P1D']
    for day, summary, path in EVENTS:
        url = ORIGIN + path
        lines += ['BEGIN:VEVENT',
                  f'UID:{day:%Y%m%d}-{path.strip("/").replace("/", "-")}@uutistenlukija.fi',
                  'DTSTAMP:' + stamp,
                  f'DTSTART;VALUE=DATE:{day:%Y%m%d}',
                  f'DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}',
                  'SUMMARY:' + _esc(summary),
                  'DESCRIPTION:' + _esc('Lue lisää: ' + url),
                  'URL:' + url, 'TRANSP:TRANSPARENT', 'END:VEVENT']
    lines.append('END:VCALENDAR')
    return '\r\n'.join(_fold(l) for l in lines) + '\r\n'
