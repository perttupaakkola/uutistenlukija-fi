"""Versioned exact-linked StatFin evidence binding.
Pure reconstruction and bounded exact-table capture; no model or publisher.
"""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

API = 'https://pxdata.stat.fi/PxWeb/api/v1/fi/StatFin/khi/15b9.px'
TABLE = 'https://pxdata.stat.fi/PXWeb/pxweb/fi/StatFin/StatFin__khi/15b9.px'
TITLE = 'Yhdenmukaistettu kuluttajahintaindeksi (YKHI), ennakko (2025=100) muuttujina Kuukausi, Hyödyke ja Tiedot'
CATEGORY_CODES = ['SSS'] + [f'{i:02}' for i in range(1, 14)]
COLUMNS = [
    {'code': 'timeperiod_m', 'text': 'Kuukausi', 'type': 't'},
    {'code': 'coicop_46_20231201', 'text': 'Hyödyke', 'type': 'd'},
    {'code': 'vm_ykhi_ennakko', 'text': 'Vuosimuutos (%), YKHI ennakko', 'type': 'c'},
    {'code': 'km_ykhi_ennakko', 'text': 'Kuukausimuutos (%), YKHI ennakko', 'type': 'c'},
]
MONTHS = ['tammikuu', 'helmikuu', 'maaliskuu', 'huhtikuu', 'toukokuu', 'kesäkuu',
          'heinäkuu', 'elokuu', 'syyskuu', 'lokakuu', 'marraskuu', 'joulukuu']


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(obj):
    return sha(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode())


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def load(raw):
    require(isinstance(raw, bytes) and 0 < len(raw) <= 512 * 1024, 'Missing or oversized bytes')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON field')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.append(dict(attrs).get('href'))


def normalize(metadata_raw, response_raw, receipt, release, source_raw, rights_raw, now):
    """Validate prospective new data evidence. Never modifies release or packet.
    release comes from independently verified canonical source extraction and rights.
    receipt is private capture provenance, not proof of network authenticity itself.
    """
    require(now.tzinfo is not None, 'Timezone-aware clock required')
    require(receipt.get('fixture') is False and receipt.get('source_url') == API, 'Wrong API identity')
    require(receipt.get('response_sha256') == sha(response_raw), 'Response hash mismatch')
    published = datetime.fromisoformat(release['published_at'].replace('Z', '+00:00'))
    retrieved = datetime.fromisoformat(receipt['retrieved_at'].replace('Z', '+00:00'))
    require(published.tzinfo is not None and retrieved.tzinfo is not None, 'Naive provenance date')
    require(timedelta(0) <= now - published <= timedelta(hours=48), 'Stale or future release')
    require(published <= retrieved <= now, 'Invalid retrieval clock')
    require(re.fullmatch(r'https://stat\.fi/fi/julkaisu/[a-z0-9]+', release['url']) is not None, 'Wrong release URL')
    require(release.get('source_sha256') == sha(source_raw), 'Source hash mismatch')
    require(release.get('rights_sha256') == sha(rights_raw), 'Rights hash mismatch')
    require(release.get('license_url') == 'https://creativecommons.org/licenses/by/4.0/', 'Wrong licence')
    links = Links(); links.feed(source_raw.decode('utf-8'))
    require(TABLE in links.links, 'Release does not link exact table')
    q = receipt['query']
    require(set(q) == {'query', 'response'} and q['response'] == {'format': 'json'}, 'Query shape drift')
    selections = q['query']
    require(len(selections) == 3 and [s['code'] for s in selections] ==
            ['timeperiod_m', 'coicop_46_20231201', 'contentscode'], 'Query dimensions drift')
    month_values = selections[0]['selection'].get('values')
    require(isinstance(month_values, list) and len(month_values) == 1, 'Exactly one month required')
    month = month_values[0]
    require(isinstance(month, str) and re.fullmatch(r'\d{4}M(0[1-9]|1[0-2])', month) is not None, 'Malformed month')
    require(selections == [
        {'code': 'timeperiod_m', 'selection': {'filter': 'item', 'values': [month]}},
        {'code': 'coicop_46_20231201', 'selection': {'filter': 'all', 'values': ['*']}},
        {'code': 'contentscode', 'selection': {'filter': 'item', 'values': ['vm_ykhi_ennakko', 'km_ykhi_ennakko']}},
    ], 'Query selection drift')
    year, number = int(month[:4]), int(month[-2:])
    phrase = MONTHS[number - 1] + 'ssa ' + str(year)
    # Finnish syyskuu -> syyskuussa; explicit release text, not API newest-month inference.
    require(phrase in release['title'].lower(), 'Release/month disagreement')
    meta, data = load(metadata_raw), load(response_raw)
    require(meta['title'] == TITLE, 'Metadata title/index drift')
    variables = meta['variables']
    require(len(variables) == 3 and [v['code'] for v in variables] ==
            ['timeperiod_m', 'coicop_46_20231201', 'contentscode'], 'Metadata dimension drift')
    require(month in variables[0]['values'], 'Month absent from metadata')
    cats = variables[1]
    require(cats['values'] == CATEGORY_CODES and len(cats['valueTexts']) == 14 and
            len(set(cats['valueTexts'])) == 14 and all(isinstance(t, str) and t for t in cats['valueTexts']),
            'Missing, duplicate or unexpected category map')
    require(variables[2]['values'] == ['ip_ykhi_ennakko', 'vm_ykhi_ennakko', 'km_ykhi_ennakko'] and
            variables[2]['valueTexts'] == ['Indeksipisteluku, YKHI ennakko', COLUMNS[2]['text'], COLUMNS[3]['text']],
            'Metadata unit drift')
    require(data['columns'] == COLUMNS, 'Response columns/units drift')
    require(data.get('comments') == [], 'Unreviewed table comments')
    updates = data['metadata']
    require(len(updates) == 1 and updates[0]['label'] == TITLE and
            updates[0]['source'] == 'Tilastokeskus, kuluttajahintaindeksi', 'Wrong table provenance')
    updated = datetime.strptime(updates[0]['updated'], '%Y-%m-%dT%H.%M.%SZ').replace(tzinfo=timezone.utc)
    require(updated == published, 'Release/table revision disagreement')
    rows = data['data']
    require(len(rows) == 14 and [r['key'] for r in rows] == [[month, c] for c in CATEGORY_CODES],
            'Wrong month, incomplete, reordered or duplicate rows')
    normalized = []
    for row, label in zip(rows, cats['valueTexts']):
        require(len(row['values']) == 2, 'Wrong metric count')
        values = []
        for value in row['values']:
            require(isinstance(value, str) and re.fullmatch(r'-?\d+(\.\d+)?', value) is not None, 'Missing/malformed value')
            try:
                val = Decimal(value)
            except InvalidOperation:
                raise ValueError('Invalid decimal') from None
            require(val.is_finite(), 'Nonfinite value')
            values.append(str(val))
        normalized.append({'category_code': row['key'][1], 'category': label,
                           'annual_percent': values[0], 'monthly_percent': values[1]})
    result = {'schema': 'statfin-normalized-v1',
              'release_url': release['url'], 'published_at': release['published_at'],
              'source_sha256': sha(source_raw), 'rights_sha256': sha(rights_raw),
              'license_url': release['license_url'], 'api_url': API, 'query': q,
              'metadata_sha256': sha(metadata_raw), 'response_sha256': sha(response_raw),
              'retrieved_at': receipt['retrieved_at'], 'month': month, 'index': 'YKHI',
              'preliminary': True, 'rows': normalized,
              'limitations': ['Not national CPI or household-specific inflation',
                              'Category changes do not identify causal drivers',
                              'Data provenance alone does not establish editorial review or audience benefit']}
    result['evidence_sha256'] = digest(result)
    return result

FILES={'metadata':'primary-metadata.json','response':'primary-response.json','receipt':'primary-receipt.json'}
def binding_and_text(b,source,source_raw,rights_raw,clock):
    rel={**source,'source_sha256':sha(source_raw),'rights_sha256':sha(rights_raw),'license_url':source['reuse']['license_url']}
    normalized=normalize(b['metadata'],b['response'],b['receipt'],rel,source_raw,rights_raw,clock)
    binding={'schema':'statfin-primary-data-v1','api_url':API,'metadata_sha256':sha(b['metadata']),
             'response_sha256':sha(b['response']),'receipt_sha256':digest(b['receipt']),
             'normalized_sha256':digest(normalized),'month':normalized['month']}
    validate_binding(binding)
    header='\nLähteen linkittämä Tilastokeskuksen taulukko: YKHI ennakko, '+normalized['month']+'. Vuosimuutos (%) ja kuukausimuutos (%). Ei kansallinen kuluttajahintaindeksi tai kotitalouskohtainen inflaatio.'
    rows='\n'.join(r['category']+': vuosimuutos '+r['annual_percent'].replace('.',',')+' %, kuukausimuutos '+r['monthly_percent'].replace('.',',')+' %.' for r in normalized['rows'])
    return binding,source['text']+header+'\n'+rows

def validate_binding(b):
    import re
    expected={'schema','api_url','metadata_sha256','response_sha256','receipt_sha256','normalized_sha256','month'}
    if not isinstance(b,dict) or set(b)!=expected or b['schema']!='statfin-primary-data-v1' or b['api_url']!=API: raise ValueError('Unknown primary-data contract')
    if not re.fullmatch(r'\d{4}M(0[1-9]|1[0-2])',b['month']): raise ValueError('Wrong primary-data month')
    if any(not isinstance(b[k],str) or not re.fullmatch(r'[a-f0-9]{64}',b[k]) for k in expected if k.endswith('_sha256')): raise ValueError('Malformed primary-data hash')

def reconstruct_primary(packet,directory,parsed,source_raw,rights_raw):
    basis=packet['publication_basis'];exists=any((directory/n).exists() for n in FILES.values())
    if 'primary_data' not in basis:
        if exists: raise ValueError('Primary-data downgrade attempt')
        return parsed
    if basis['provider']!='stat': raise ValueError('Wrong primary-data provider')
    expected=basis['primary_data'];validate_binding(expected)
    b={k:((directory/n).read_bytes() if k!='receipt' else load((directory/n).read_bytes())) for k,n in FILES.items()}
    source={**packet['sources'][0],**parsed}
    actual,text=binding_and_text(b,source,source_raw,rights_raw,datetime.fromisoformat(packet['supporting_documents'][0]['retrieved_at'].replace('Z', '+00:00')))
    if actual!=expected: raise ValueError('Captured primary-data binding changed')
    return {**parsed,'text':text}


def capture_primary(source, source_raw, rights_raw, now):
    """Read only the article-linked pinned table, with two bounded exact-origin calls.
    No newest-month inference, redirects, retries or credential loader.
    Source and rights must come from the independently reviewed official intake.
    """
    from urllib.request import Request, build_opener, HTTPRedirectHandler
    from datetime import timezone
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError('Primary-data redirects refused')
    require(source.get('publisher') == 'Tilastokeskus', 'Wrong primary-data publisher')
    require(source.get('reuse', {}).get('license_url') == 'https://creativecommons.org/licenses/by/4.0/', 'Wrong primary-data rights')
    require(re.fullmatch(r'https://stat\.fi/fi/julkaisu/[a-z0-9]+', source['url']) is not None, 'Wrong release URL')
    require(now.tzinfo is not None, 'Timezone-aware clock required')
    published=datetime.fromisoformat(source['published_at'].replace('Z','+00:00'))
    require(published.tzinfo is not None and timedelta(0)<=now-published<=timedelta(hours=48), 'Stale or future release')
    links=Links(); links.feed(source_raw.decode('utf-8'));require(TABLE in links.links,'Release does not link exact table')
    matches=[(i+1,m) for i,m in enumerate(MONTHS) if (m+'ssa ') in source['title'].lower()]
    require(len(matches)==1,'Ambiguous release month')
    n,m=matches[0]; years=re.findall(re.escape(m+'ssa ')+r'(\d{4})(?!\d)',source['title'].lower())
    require(len(years)==1,'Ambiguous release year');month=years[0]+'M'+format(n,'02d')
    query={'query':[{'code':'timeperiod_m','selection':{'filter':'item','values':[month]}},
       {'code':'coicop_46_20231201','selection':{'filter':'all','values':['*']}},
       {'code':'contentscode','selection':{'filter':'item','values':['vm_ykhi_ennakko','km_ykhi_ennakko']}}],
       'response':{'format':'json'}}
    opener=build_opener(NoRedirect())
    def read(data=None):
        req=Request(API,data=data,headers={'User-Agent':'Uutistenlukija-primary-data/1.0','Accept':'application/json','Accept-Encoding':'identity',**({'Content-Type':'application/json'} if data is not None else {})})
        with opener.open(req,timeout=10) as response:
            require(response.geturl()==API and response.status==200,'Wrong API response identity')
            require(response.headers.get_content_type()=='application/json','Wrong API response type')
            body=response.read(512*1024+1)
            load(body) # size, JSON duplicates and nonfinite refusal
            return body
    metadata=read(); response=read(json.dumps(query,separators=(',',':')).encode())
    retrieved=datetime.now(timezone.utc)
    require(now<=retrieved<=now+timedelta(seconds=30),'Capture deadline exceeded')
    receipt={'fixture':False,'source_url':API,'response_sha256':sha(response),'retrieved_at':retrieved.isoformat(),'query':query}
    bundle={'metadata':metadata,'response':response,'receipt':receipt}
    binding_and_text(bundle,source,source_raw,rights_raw,retrieved)
    return bundle
