"""Small, cached public snapshots. No page-load API calls, keys or new scheduler."""
import html
import json
import math
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

CITIES = {'helsinki': ('Helsinki', 60.1699, 24.9384),
          'tampere': ('Tampere', 61.4978, 23.7610),
          'oulu': ('Oulu', 65.0121, 25.4651),
          'rovaniemi': ('Rovaniemi', 66.5039, 25.7294)}
ECB_URL = 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml'
ECB_SOURCE = 'https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html'
UA = 'Uutistenlukija/1.0 (https://uutistenlukija.fi/)'
FI = ZoneInfo('Europe/Helsinki')


def date(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result


def number(value, low, high):
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Value outside source bounds')
    return value


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(request, timeout=8) as response:
        raw = response.read(250001)
    if len(raw) > 250000:
        raise ValueError('Oversized snapshot')
    return raw


def parse_weather(raw):
    data = json.loads(raw)['properties']
    updated = date(data['meta']['updated_at']).isoformat()
    if data['meta']['units']['air_temperature'] != 'celsius':
        raise ValueError('Wrong temperature unit')
    hours = []
    for item in data['timeseries'][:60]:
        details = item['data']['instant']['details']
        hours.append({'time': date(item['time']).isoformat(),
                      'temperature': number(details['air_temperature'], -70, 60),
                      'wind': number(details['wind_speed'], 0, 150)})
    if not hours:
        raise ValueError('Empty forecast')
    return {'updated_at': updated, 'hours': hours}


def parse_markets(raw):
    root = ET.fromstring(raw)
    daily = next((e for e in root.iter() if 'time' in e.attrib), None)
    if daily is None:
        raise ValueError('Missing exchange-rate date')
    day = datetime.strptime(daily.attrib['time'], '%Y-%m-%d').date().isoformat()
    rates = {e.attrib['currency']: number(e.attrib['rate'], .0001, 1000000)
             for e in daily if e.attrib.get('currency') in ('USD', 'SEK', 'GBP')}
    if len(rates) != 3:
        raise ValueError('Missing exchange rate')
    return {'date': day, 'rates': rates}


def refresh(state_dir, now=None, reader=fetch):
    """Called under the existing publisher lock. Failures retain bounded old data."""
    now = now or datetime.now(timezone.utc)
    path = Path(state_dir) / 'frontpage-data.json'
    try:
        cache = json.loads(path.read_text())
    except (OSError, ValueError):
        cache = {}
    if not isinstance(cache, dict):
        cache = {}
    targets = {key: (f'https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat}&lon={lon}', parse_weather, 3600)
               for key, (_, lat, lon) in CITIES.items()}
    targets['markets'] = (ECB_URL, parse_markets, 21600)

    def update(key):
        url, parser, ttl = targets[key]
        previous = cache.get(key) or {}
        try:
            age = (now - date(previous['fetched_at'])).total_seconds()
            if 0 <= age < ttl:
                return key, previous
        except (KeyError, TypeError, ValueError):
            pass
        try:
            return key, {**parser(reader(url)), 'fetched_at': now.isoformat()}
        except Exception:
            # No upstream exception text (or headers) goes into public output.
            return key, previous

    with ThreadPoolExecutor(max_workers=5) as executor:
        result = dict(executor.map(update, targets))
    from .site import atomic_write
    atomic_write(path, json.dumps(result, ensure_ascii=False) + '\n')
    return result


def load(state_dir):
    try:
        value = json.loads((Path(state_dir) / 'frontpage-data.json').read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def current_weather(item, now):
    try:
        age = (now - date(item['updated_at'])).total_seconds()
        if not 0 <= age <= 18 * 3600:
            return None
        hour = min(item['hours'], key=lambda h: abs((date(h['time']) - now).total_seconds()))
        if abs((date(hour['time']) - now).total_seconds()) > 5400:
            return None
        return hour
    except (KeyError, TypeError, ValueError):
        return None


def current_markets(item, now):
    try:
        age = (now.date() - datetime.strptime(item['date'], '%Y-%m-%d').date()).days
        return 0 <= age <= 7 and all(0 < float(item['rates'][s]) < 1000000 for s in ('USD','SEK','GBP'))
    except (KeyError, TypeError, ValueError):
        return False


def weather(snapshot=None, now=None):
    """Populate the original compact Helsinki header surface; no extra module."""
    snapshot = snapshot or {}
    now = now or datetime.now(timezone.utc)
    item = snapshot.get('helsinki') or {}
    hour = current_weather(item, now)
    value = f'{hour["temperature"]:.0f} °C' if hour else '-- °C'
    label = 'Helsinki · ennuste' if hour else 'Helsinki · sää ei saatavilla'
    detail = ('Ennuste ' + date(hour['time']).astimezone(FI).strftime('%d.%m. klo %H.%M') +
              ' · päivitetty ' + date(item['updated_at']).astimezone(FI).strftime('%d.%m. klo %H.%M') +
              ' · MET Norway, CC BY 4.0') if hour else 'Sääennuste ei ole nyt saatavilla. MET Norway, CC BY 4.0.'
    return (f'<a class="portal-weather" href="https://www.met.no/en/free-meteorological-data/Licensing-and-crediting" title="{html.escape(detail)}" aria-label="{html.escape(value + ", " + label + ". " + detail)}">'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="27" height="27" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>'
            f'<span><strong id="weather-value">{value}</strong><small id="weather-time">{label}</small></span></a>')


def markets(snapshot=None, now=None):
    """Use the existing market panel and its original theme classes."""
    market = (snapshot or {}).get('markets') or {}
    now = now or datetime.now(timezone.utc)
    values = ''
    if current_markets(market, now):
        values = '<dl>' + ''.join(f'<div><dt>EUR / {symbol}</dt><dd>{market["rates"][symbol]:.4f}</dd></div>' for symbol in ('USD','SEK','GBP')) + '</dl>'
    label = ('EKP · 1 euro · ' + datetime.strptime(market['date'], '%Y-%m-%d').strftime('%d.%m.%Y') + ' · päiväkurssit, ei reaaliaikainen') if values else 'Valuuttakurssit eivät ole nyt saatavilla.'
    return ('<section class="portal-market"><div class="portal-module-head"><h2>Markkinat</h2></div>'
            f'<div id="market-values">{values}</div><p class="portal-market__note"><a id="market-time" href="{ECB_SOURCE}">{html.escape(label)}</a></p></section>')


def data_script(snapshot=None):
    data = json.dumps(snapshot or {}, ensure_ascii=False).replace('<', '\\u003c').replace('&', '\\u0026')
    return f'<script type="application/json" id="frontpage-data">{data}</script>'
