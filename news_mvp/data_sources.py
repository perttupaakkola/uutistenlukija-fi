"""Bounded structured intake for FMI warnings and Fintraffic traffic notices.

Discovery performs one request per family.  The selected response bytes travel with the
recipe, so collection does not refetch a moving feed and can bind the reviewed packet to
the exact snapshot that produced it.
"""
import gzip
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .editorial import digest, timestamp, validate_packet, web_url


FMI = 'fmi-warnings'
FINTRAFFIC = 'fintraffic-traffic'
FAMILIES = (FMI, FINTRAFFIC)
HELSINKI = ZoneInfo('Europe/Helsinki')
CAP = 'urn:oasis:names:tc:emergency:cap:1.2'
ATOM = 'http://www.w3.org/2005/Atom'
MAX_RESPONSE = 2_000_000
LARGE_AREA_COUNT = 3
FMI_RIGHTS_SENTENCE = ('Ilmatieteen laitoksen avoimen datan palvelussa sovelletaan '
                       'Creative Commons Nimeä 4.0 Kansainvälinen -lisenssiä (CC BY 4.0).')
FINTRAFFIC_RIGHTS_SENTENCE = ('Fintrafficin avoimen datan aineistoja koskee Creative '
                              'Commons 4.0 Nimeä -käyttölupa.')
FINTRAFFIC_USER = 'Uutistenlukija/1.0'
WEEKDAYS = ('maanantaina', 'tiistaina', 'keskiviikkona', 'torstaina',
            'perjantaina', 'lauantaina', 'sunnuntaina')


def _policy():
    from .official import policy
    return policy()


def _spec(provider):
    try:
        return _policy()['data_providers'][provider]
    except KeyError as error:
        raise ValueError('Unknown structured data source') from error


def fetch_source(provider, *, rights=False):
    """Fetch one allowlisted response, including Digitraffic's mandatory headers."""
    spec = _spec(provider)
    url = spec['rights_url'] if rights else spec['index']
    headers = {'User-Agent': 'Uutistenlukija/1.0 (private editorial source intake)',
               'Accept-Encoding': 'gzip'}
    if provider == FINTRAFFIC and not rights:
        headers['Digitraffic-User'] = FINTRAFFIC_USER
        headers['Accept'] = 'application/geo+json, application/json'
    request = Request(url, headers=headers)
    with urlopen(request, timeout=25) as response:
        final = web_url(response.url)
        if final != web_url(url) or urlsplit(final).hostname not in spec['hosts']:
            raise ValueError('Structured source redirect left its exact allowlist')
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('Structured source exceeds bounded download size')
        if response.headers.get('Content-Encoding', '').lower() == 'gzip':
            try:
                raw = gzip.decompress(raw)
            except OSError as error:
                raise ValueError('Invalid gzip response') from error
        mime = response.headers.get_content_type()
    allowed = ({'text/html'} if rights else
               ({'application/atom+xml', 'application/xml', 'text/xml'} if provider == FMI
                else {'application/geo+json', 'application/json'}))
    if mime not in allowed:
        raise ValueError('Unexpected structured source response')
    return raw


def rights_text(raw, provider):
    """Return the single reviewed licence sentence; any wording drift fails closed."""
    from .official import parse
    text = parse(raw, lambda tag, attrs: tag == 'body').text()
    expected = FMI_RIGHTS_SENTENCE if provider == FMI else FINTRAFFIC_RIGHTS_SENTENCE
    if text.count(expected) != 1:
        raise ValueError('Missing exact structured-source reuse grant')
    return expected


def _one(parent, name, *, optional=False):
    rows = parent.findall('{'+CAP+'}'+name)
    if optional and not rows:
        return ''
    if len(rows) != 1 or not (rows[0].text or '').strip():
        raise ValueError('Missing or ambiguous CAP '+name)
    return rows[0].text.strip()


def _iso(value):
    return timestamp(value)


def _fmi_records(raw):
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, TypeError) as error:
        raise ValueError('Invalid FMI Atom/CAP response') from error
    if root.tag != '{'+ATOM+'}feed':
        raise ValueError('Unexpected FMI warning feed root')
    self_links = [x.get('href') for x in root.findall('{'+ATOM+'}link') if x.get('rel') == 'self']
    related = [x.get('href') for x in root.findall('{'+ATOM+'}link') if x.get('rel') == 'related']
    rights = (root.findtext('{'+ATOM+'}rights') or '').strip()
    if (self_links != [_spec(FMI)['index']] or related != [_spec(FMI)['source_url']] or
            'Creative Commons BY 4.0' not in rights):
        raise ValueError('FMI feed identity or licence declaration changed')
    updated = _iso(root.findtext('{'+ATOM+'}updated', ''))
    records = []
    for entry in root.findall('{'+ATOM+'}entry')[:100]:
        alert = entry.find('.//{'+CAP+'}alert')
        if alert is None:
            raise ValueError('FMI fat Atom entry lacks embedded CAP')
        if (_one(alert, 'status') != 'Actual' or _one(alert, 'scope') != 'Public' or
                _one(alert, 'msgType') not in ('Alert', 'Update')):
            continue
        infos = [info for info in alert.findall('{'+CAP+'}info')
                 if _one(info, 'language') == 'fi-FI']
        if len(infos) != 1:
            raise ValueError('Missing or ambiguous Finnish CAP information')
        info = infos[0]
        parameters = {}
        for parameter in info.findall('{'+CAP+'}parameter'):
            name = _one(parameter, 'valueName')
            if name in parameters:
                raise ValueError('Duplicate CAP parameter')
            parameters[name] = _one(parameter, 'value')
        codes = [_one(code, 'value') for code in info.findall('{'+CAP+'}eventCode')]
        if len(codes) != 1 or not re.fullmatch(r'[A-Za-z0-9_-]+', codes[0]):
            raise ValueError('Missing or malformed CAP event code')
        areas = []
        for area in info.findall('{'+CAP+'}area'):
            value = _one(area, 'areaDesc')
            if value not in areas:
                areas.append(value)
        if not areas:
            raise ValueError('CAP warning has no named area')
        web = _one(info, 'web')
        if web != _spec(FMI)['source_url']:
            raise ValueError('CAP warning page identity changed')
        onset, expires = _iso(_one(info, 'onset')), _iso(_one(info, 'expires'))
        if expires <= onset:
            raise ValueError('CAP warning has an invalid validity interval')
        sent = _iso(_one(alert, 'sent'))
        if abs((sent-updated).total_seconds()) > 300:
            raise ValueError('CAP entry/update timestamps disagree')
        records.append({'identifier': _one(alert, 'identifier'), 'sent': sent,
                        'event': _one(info, 'event'), 'event_code': codes[0],
                        'severity': _one(info, 'severity'),
                        'certainty': _one(info, 'certainty'), 'onset': onset,
                        'expires': expires, 'headline': _one(info, 'headline'),
                        'description': _one(info, 'description'),
                        'instruction': _one(info, 'instruction', optional=True),
                        'impact': parameters.get('typicalImpacts', ''),
                        'color': parameters.get('color', '').lower(), 'areas': areas,
                        'web': web, 'published': updated})
    return records


# Yellow sea-area wind warnings come almost daily in autumn and are not news alone.
EXCLUDE_YELLOW_SEA_WIND = True


def _fmi_groups(raw, now=None):
    groups = {}
    for record in _fmi_records(raw):
        if now is not None and record['expires'] < now.astimezone(timezone.utc):
            continue
        local_day = record['onset'].astimezone(HELSINKI).date().isoformat()
        key = f"fmi-warning:{local_day}:{record['event_code']}:{record['severity']}"
        groups.setdefault(key, []).append(record)
    result = []
    yellow_codes = re.compile(r'(wind|storm|flood|forest.?fire|traffic.?weather)', re.I)
    yellow_events = re.compile(r'(tuuli|myrsky|tulv|metsäpalo|liikennesää)', re.I)
    for key, records in groups.items():
        areas = list(dict.fromkeys(area for row in records for area in row['areas']))
        high = any(row['color'] in {'orange', 'red', 'darkred', 'purple'} or
                   row['severity'] in {'Severe', 'Extreme'} or
                   (not row['color'] and row['severity'] == 'Moderate') for row in records)
        # Yellow sea-area wind warnings are issued almost daily in autumn; not news by themselves.
        sea_only = EXCLUDE_YELLOW_SEA_WIND and all(row['event_code'].lower().startswith('sea') for row in records)
        yellow_large = (not sea_only and len(areas) >= LARGE_AREA_COUNT and
                        all(row['color'] == 'yellow' for row in records) and
                        any(yellow_codes.search(row['event_code']) or
                            yellow_events.search(row['event']) for row in records))
        # FMI's CAP profile labels yellow alerts Moderate.  The colour parameter therefore
        # disambiguates the task's orange-or-higher rule; a Moderate/yellow group enters only
        # through the explicit large-area exception above.
        if not (high or yellow_large):
            continue
        records.sort(key=lambda row: (row['onset'], row['expires'], row['identifier']))
        result.append((key, records, areas))
    return sorted(result, key=lambda item: (item[1][0]['published'], item[0]), reverse=True)


def _area_phrase(areas, limit=None):
    shown = areas if limit is None else areas[:limit]
    if len(shown) == 1:
        result = shown[0]
    else:
        result = ', '.join(shown[:-1]) + ' ja ' + shown[-1]
    if limit is not None and len(areas) > limit:
        result += f' sekä {len(areas)-limit} muuta aluetta'
    return result


def _local_time(value):
    local = value.astimezone(HELSINKI)
    return local.strftime('%-d.%-m.%Y klo %H.%M')+' (Suomen aika)'


def _fmi_fields(raw, story_key):
    matches = [item for item in _fmi_groups(raw) if item[0] == story_key]
    if len(matches) != 1:
        raise ValueError('FMI warning group is missing or ambiguous')
    _, records, areas = matches[0]
    first = records[0]
    day = first['onset'].astimezone(HELSINKI).date()
    title = f"{first['event']} {WEEKDAYS[day.weekday()]}: {_area_phrase(areas, 2)}"
    lines = [f"Ilmatieteen laitoksen CAP-varoituspäivitys julkaistiin {_local_time(first['published'])}.",
             f"Varoitustyyppi: {first['event']}. Vakavuus: {first['severity']}. "
             f"Väri: {first['color'] or 'ei ilmoitettu'}. Alueet: {_area_phrase(areas)}."]
    for record in records:
        line = (f"{record['headline']} Alueet: {_area_phrase(record['areas'])}. "
                f"Voimassa {_local_time(record['onset'])}–{_local_time(record['expires'])}. "
                f"Kuvaus: {record['description']}")
        if record['instruction']:
            line += ' Ohje: '+record['instruction']
        if record['impact']:
            line += ' Varoituksessa ilmoitettu tyypillinen vaikutus: '+record['impact']
        line += f" Varmuus: {record['certainty']}."
        lines.append(line)
    return {'id': 'A', 'title': title[:240], 'published_at': first['published'].isoformat(),
            'text': '\n'.join(lines)}


def _load_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate Digitraffic JSON field')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError('Invalid Digitraffic response') from error


def _traffic_rows(raw):
    data = _load_json(raw)
    if not isinstance(data, dict) or data.get('type') != 'FeatureCollection':
        raise ValueError('Unexpected Digitraffic collection')
    _iso(data.get('dataUpdatedTime', ''))
    features = data.get('features')
    if not isinstance(features, list) or len(features) > 500:
        raise ValueError('Invalid Digitraffic feature count')
    rows = []
    for feature in features:
        props = feature.get('properties') if isinstance(feature, dict) else None
        situation_type = str(props.get('situationType', '')).upper().replace(' ', '_') if isinstance(props, dict) else ''
        if not isinstance(props, dict) or situation_type != 'TRAFFIC_ANNOUNCEMENT':
            continue
        situation = props.get('situationId')
        if not isinstance(situation, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', situation):
            raise ValueError('Malformed Digitraffic situation id')
        kind = str(props.get('trafficAnnouncementType', '')).upper().replace(' ', '_')
        if kind in {'ENDED', 'RETRACTED'}:
            continue
        announcements = [row for row in props.get('announcements', [])
                         if row.get('language', '').upper() == 'FI']
        if len(announcements) != 1:
            raise ValueError('Missing or ambiguous Finnish traffic announcement')
        announcement = announcements[0]
        title = str(announcement.get('title', '')).strip()
        sender = str(announcement.get('sender', '')).strip()
        if not title or not sender:
            raise ValueError('Traffic announcement lacks title or sender')
        location = announcement.get('location') or {}
        location_text = str(location.get('description', '')).strip()
        if not location_text:
            raise ValueError('Traffic announcement lacks a location')
        details = (announcement.get('locationDetails') or {}).get('roadAddressLocation') or {}
        road = (((details.get('primaryPoint') or {}).get('roadAddress') or {}).get('road'))
        if road is not None and (type(road) is not int or road <= 0):
            raise ValueError('Malformed road number')
        names = [str(item.get('name', '')).strip() for item in announcement.get('features', [])]
        if any(not name for name in names):
            raise ValueError('Malformed traffic feature')
        phases = announcement.get('roadWorkPhases') or []
        severity = {str(phase.get('severity', '')).upper() for phase in phases}
        period = announcement.get('timeAndDuration') or {}
        start = _iso(period.get('startTime', ''))
        end = _iso(period['endTime']) if period.get('endTime') else None
        if end is not None and end < start:
            raise ValueError('Traffic announcement has invalid times')
        rows.append({'situation_id': situation, 'kind': kind, 'version': props.get('version'),
                     'release': _iso(props.get('releaseTime', '')),
                     'published': _iso(props.get('versionTime', '')), 'title': title,
                     'sender': sender, 'location': location_text, 'road': road,
                     'features': names, 'comment': str(announcement.get('comment') or '').strip(),
                     'additional': str(announcement.get('additionalInformation') or '').strip(),
                     'start': start, 'end': end, 'duration': period.get('estimatedDuration'),
                     'severity': severity})
    return rows


def _significant_traffic(row):
    body = ' '.join(row['features']+[row['comment']])
    routine = re.search(r'(tienrakennus|siltatyö|huoltotyö|kunnossapitotyö|remont|tunnelin pesu|päällyst)', body, re.I)
    highest = bool(row['severity'] & {'HIGH', 'HIGHEST'})
    if routine and not highest:
        return False
    main_road = row['road'] is not None and row['road'] < 100
    closed = bool(re.search(r'(tie|ajorata|ajokaista).{0,25}suljettu', body, re.I))
    major = bool(re.search(r'(merkittävä|vakava).{0,20}(haitta|häiriö)|liikenne on pysähtynyt', body, re.I))
    multi = bool(re.search(r'(ketjukolari|usean ajoneuvon|monen ajoneuvon|useita ajoneuvoja)', body, re.I))
    accident = row['kind'] in {'ACCIDENT_REPORT', 'PRELIMINARY_ACCIDENT_REPORT'}
    over_hour = row['end'] is not None and (row['end']-row['start']).total_seconds() > 3600
    lane_closed = bool(re.search(r'(ajorata|ajokaista).{0,25}suljettu', body, re.I))
    return highest or (main_road and (closed or major)) or multi or (accident and lane_closed and over_hour)


def _traffic_candidates(raw, now=None):
    result = []
    for row in _traffic_rows(raw):
        if not _significant_traffic(row):
            continue
        if now is not None:
            age = (now.astimezone(timezone.utc)-row['published']).total_seconds()
            if not -300 <= age <= 48*3600:
                continue
            if row['end'] is not None and row['end'] < now.astimezone(timezone.utc):
                continue
        result.append(row)
    return sorted(result, key=lambda row: (row['published'], row['situation_id']), reverse=True)


def _traffic_url(situation):
    return 'https://tie.digitraffic.fi/api/traffic-message/v1/messages/'+situation


def _failure_url(provider, story_key):
    if provider == FMI:
        return _spec(FMI)['source_url']+'?uutistenlukija_story='+quote(story_key, safe='')
    return _traffic_url(story_key.split(':', 1)[1])


def _traffic_fields(raw, story_key):
    situation = story_key.removeprefix('fintraffic-traffic:')
    matches = [row for row in _traffic_candidates(raw) if row['situation_id'] == situation]
    if len(matches) != 1:
        raise ValueError('Traffic announcement is missing or ambiguous')
    row = matches[0]
    lines = [row['title'], 'Sijainti: '+row['location'],
             f"Tiedotteen versio: {row['version']}. Tiedotetyyppi: {row['kind']}. "
             f"Lähettäjä: {row['sender']}.",
             f"Julkaistu {_local_time(row['release'])}; viimeisin versio {_local_time(row['published'])}.",
             'Tilanne alkaa '+_local_time(row['start'])+'.']
    if row['end'] is not None:
        lines.append('Ilmoitettu päättymisaika: '+_local_time(row['end'])+'.')
    if row['features']:
        lines.append('Liikennevaikutukset: '+'; '.join(row['features'])+'.')
    if row['comment']:
        lines.append('Kuvaus: '+row['comment'])
    if row['additional']:
        lines.append('Lisätieto: '+row['additional'])
    return {'id': 'A', 'title': row['title'][:240], 'published_at': row['published'].isoformat(),
            'text': '\n'.join(lines)}


def source_fields(raw, provider, story_key):
    return _fmi_fields(raw, story_key) if provider == FMI else _traffic_fields(raw, story_key)


def discover_family(provider, now=None, excluded=()):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Timezone-aware discovery clock required')
    raw = fetch_source(provider)
    recipes = []
    if provider == FMI:
        for story_key, records, _ in _fmi_groups(raw, now):
            published = records[0]['published']
            age = (now.astimezone(timezone.utc)-published).total_seconds()
            failure_url = _failure_url(FMI, story_key)
            if (-300 <= age <= 48*3600 and story_key not in excluded and
                    failure_url not in excluded):
                recipes.append({'family': FMI, 'provider': FMI, 'url': _spec(FMI)['source_url'],
                                'story_key': story_key, 'failure_url': failure_url, '_raw': raw})
    elif provider == FINTRAFFIC:
        for row in _traffic_candidates(raw, now):
            story_key = 'fintraffic-traffic:'+row['situation_id']
            url = _traffic_url(row['situation_id'])
            if story_key not in excluded and url not in excluded:
                recipes.append({'family': FINTRAFFIC, 'provider': FINTRAFFIC, 'url': url,
                                'story_key': story_key, 'failure_url': url, '_raw': raw})
    else:
        raise ValueError('Unknown structured discovery family')
    return recipes[:5]


def _reuse(spec):
    from .official import reuse
    return reuse(spec)


def collect(recipe, state_dir, now=None):
    now = now or datetime.now(timezone.utc)
    provider = recipe.get('provider')
    if provider not in FAMILIES or recipe.get('family') != provider:
        raise ValueError('Unknown structured collection recipe')
    story_key = recipe.get('story_key', '')
    spec = _spec(provider)
    if not re.fullmatch(spec['story_key_pattern'], story_key):
        raise ValueError('Malformed structured story key')
    raw = recipe.get('_raw')
    if not isinstance(raw, bytes) or not raw:
        raise ValueError('Structured recipe lacks its captured response')
    fields = source_fields(raw, provider, story_key)
    url = spec['source_url'] if provider == FMI else _traffic_url(story_key.split(':', 1)[1])
    if web_url(recipe.get('url')) != url or not re.fullmatch(spec['article_pattern'], url):
        raise ValueError('Structured source URL identity mismatch')
    rights = fetch_source(provider, rights=True)
    permission = rights_text(rights, provider)
    if hashlib.sha256(permission.encode()).hexdigest() != spec['rights_text_sha256']:
        raise ValueError('Structured source reuse terms changed')
    source = {**fields, 'url': url, 'publisher': spec['publisher'], 'reuse': _reuse(spec)}
    basis = {'policy': 'official-text-v1', 'policy_sha256': digest(_policy()),
             'provider': provider, 'source_sha256': hashlib.sha256(raw).hexdigest(),
             'source_fields_sha256': digest(source), 'story_key': story_key,
             'source_endpoint': spec['index'], 'related_sources': 0}
    packet = {'story_key': story_key, 'fixture': False, 'publication_basis': basis,
              'sources': [source], 'image': None,
              'image_note': ('Ei lähdekuvaa: rakenteinen avoin data on tekstimuotoista. '
                             'Kuvitus saatetaan liittää myöhemmin tekoälyllä tuotettuna.'),
              'supporting_documents': [{'id': 'RIGHTS',
                  'purpose': 'structured-data reuse permission; not news or image evidence',
                  'url': spec['rights_url'], 'retrieved_at': now.isoformat(),
                  'text': permission, 'sha256': hashlib.sha256(rights).hexdigest()}]}
    validate_packet(packet, now, 48)
    directory = Path(state_dir)/'intake'/digest(packet)
    directory.mkdir(parents=True, exist_ok=True)
    receipt = {'fixture': False, 'retrieved_at': now.isoformat(), 'provider': provider,
               'source_url': url, 'source_endpoint': spec['index'],
               'story_key': story_key, 'source_sha256': hashlib.sha256(raw).hexdigest(),
               'rights_url': spec['rights_url'], 'rights_sha256': hashlib.sha256(rights).hexdigest(),
               'rights_text_sha256': spec['rights_text_sha256'], 'packet_sha256': digest(packet),
               'image_status': 'explicit-text-only', 'publication_basis': basis}
    for name, value in (('source.html', raw), ('rights.html', rights),
                        ('packet.json', json.dumps(packet, ensure_ascii=False, indent=2).encode()),
                        ('receipt.json', json.dumps(receipt, ensure_ascii=False, indent=2).encode())):
        (directory/name).write_bytes(value)
    return packet, receipt


def verify_intake(packet, directory, intake_packet=None):
    provider = packet['publication_basis']['provider']
    spec = _spec(provider)
    basis = packet['publication_basis']
    raw = (directory/'source.html').read_bytes()
    rights = (directory/'rights.html').read_bytes()
    document = packet['supporting_documents'][0]
    if (hashlib.sha256(raw).hexdigest() != basis['source_sha256'] or
            hashlib.sha256(rights).hexdigest() != document['sha256'] or
            rights_text(rights, provider) != document['text']):
        raise ValueError('Captured structured intake bytes changed')
    parsed = source_fields(raw, provider, packet['story_key'])
    if any(packet['sources'][0].get(key) != value for key, value in parsed.items()):
        raise ValueError('Captured structured source differs from reviewed packet')
    receipt = json.loads((directory/'receipt.json').read_text())
    expected = {'fixture': False, 'retrieved_at': document['retrieved_at'],
                'provider': provider, 'source_url': packet['sources'][0]['url'],
                'source_endpoint': spec['index'], 'story_key': packet['story_key'],
                'source_sha256': basis['source_sha256'], 'rights_url': spec['rights_url'],
                'rights_sha256': document['sha256'],
                'rights_text_sha256': spec['rights_text_sha256'],
                'packet_sha256': digest(intake_packet or packet),
                'image_status': 'explicit-text-only', 'publication_basis': basis}
    if receipt != expected or json.loads((directory/'packet.json').read_text()) != (intake_packet or packet):
        raise ValueError('Captured structured intake receipt/packet identity mismatch')
    return True
