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


def modules(snapshot=None, now=None):
    snapshot = snapshot or {}
    now = now or datetime.now(timezone.utc)
    weather = snapshot.get('helsinki') or {}
    hour = current_weather(weather, now)
    weather_text = 'Sääennuste ei ole nyt saatavilla.'
    if hour:
        weather_text = f'{hour["temperature"]:.0f} °C · tuuli {hour["wind"]:.0f} m/s'
    weather_time = ('Ennuste ' + date(hour['time']).astimezone(FI).strftime('%d.%m. klo %H.%M') +
                    ' · päivitetty ' + date(weather['updated_at']).astimezone(FI).strftime('%d.%m. klo %H.%M')) if hour else 'Yritä myöhemmin uudelleen.'
    options = ''.join(f'<option value="{key}">{name}</option>' for key, (name, _, _) in CITIES.items())
    market = snapshot.get('markets') or {}
    values = ''
    if current_markets(market, now):
        values = '<dl class="market-rates">' + ''.join(
            f'<div><dt>EUR / {symbol}</dt><dd>{market["rates"][symbol]:.4f} {symbol}</dd></div>' for symbol in ('USD','SEK','GBP')) + '</dl>'
    market_time = ('Kurssipäivä ' + datetime.strptime(market['date'], '%Y-%m-%d').strftime('%d.%m.%Y')) if values else 'Valuuttakurssit eivät ole nyt saatavilla.'
    data = json.dumps(snapshot, ensure_ascii=False).replace('<', '\\u003c').replace('&', '\\u0026')
    return (f'<section id="saa" class="front-weather" aria-labelledby="weather-title"><h2 id="weather-title">Sää Suomessa</h2>'
            f'<label for="weather-city">Paikkakunta</label><select id="weather-city">{options}</select>'
            f'<p id="weather-value" aria-live="polite">{html.escape(weather_text)}</p><p id="weather-time" class="snapshot-note">{html.escape(weather_time)} (Suomen aikaa)</p>'
            '<a href="https://www.met.no/en/free-meteorological-data/Licensing-and-crediting">MET Norway · CC BY 4.0</a></section>'
            '<section id="markkinat" class="portal-market" aria-labelledby="market-title"><h2 id="market-title">Markkinat</h2>'
            '<p>Valuutat · 1 euro (EUR)</p><div id="market-values">' + values + '</div>'
            f'<p id="market-time" class="snapshot-note">{html.escape(market_time)}</p><p class="snapshot-note">EKP:n viitekurssit, ei reaaliaikainen. Päivitys arkipäivisin.</p>'
            f'<a href="{ECB_SOURCE}">Euroopan keskuspankki</a></section>'
            f'<script type="application/json" id="frontpage-data">{data}</script>')
