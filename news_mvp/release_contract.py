"""Explicit official-text provenance; legacy imaged releases keep their original meaning."""
import hashlib
import json
import re
from pathlib import Path
from .editorial import digest, validate_draft, validate_review

TEXT_POLICY = 'official-text-v1'
SHA = r'[0-9a-f]{64}'
# Mirrors validate_packet's hard cap: the official source plus up to 7 related corroborating
# sources. Kept here too so the release contract does not depend on the editor module.
MAX_PACKET_SOURCES = 8


def media(packet, draft, policy_gate=True):
    validate_draft(draft, packet)
    if packet.get('fixture') is not False or packet.get('private_only') is True:
        raise ValueError('Fixture/private-only packet cannot be public')
    image = draft.get('image')
    if image is not None:
        if packet.get('publication_basis') is not None:
            raise ValueError('Text-only policy cannot authorize an image')
        sha = image.get('sha256', '')
        if not re.fullmatch(SHA, sha) or image.get('local_path') != f'media/{sha}.jpg':
            raise ValueError('Required reviewed local image is absent')
        return {'image_sha256': sha}
    from .official import policy, reuse
    spec = policy()
    basis = packet.get('publication_basis', {})
    # policy_gate=False is used when RE-RENDERING an article that was already released: the
    # digest binds a packet to the policy in force at release time, so re-applying today's
    # policy to yesterday's approved article fails every historical page. The structural
    # checks below (provider, article pattern, publisher, reuse terms, rights evidence,
    # source byte hashes) still run in full, so provenance is still enforced.
    if policy_gate and (basis.get('policy') != TEXT_POLICY or basis.get('policy_sha256') != digest(spec)):
        raise ValueError('Missing exact text-only policy')
    if basis.get('policy') != TEXT_POLICY:
        raise ValueError('Missing exact text-only policy')
    provider = spec['providers'].get(basis.get('provider'))
    sources = packet.get('sources', [])
    if provider is None or not sources:
        raise ValueError('Unapproved text-only provider/source count')
    # Source A is the official source itself and carries the provenance that matters: its URL
    # must match the approved article pattern and its reuse record must equal the provider's
    # pinned terms. Related sources (B..H) are corroboration found by search, so they are not
    # required to come from this provider - but each one is still structurally checked below
    # (real HTTPS URL, publisher, title, substantive text, freshness) by validate_packet, and
    # they can never be the basis of the release on their own.
    source = sources[0]
    if (not re.fullmatch(provider['article_pattern'], source['url']) or
        packet['story_key'] != 'url:'+source['url'] or source['publisher'] != provider['publisher']):
        raise ValueError('Source/reuse policy mismatch')
    # The reuse record is policy-coupled: it is generated from the provider's declared licence,
    # so editing a provider's terms (or adding one) changes it for every historical article.
    # policy_gate=False means "this article was already released under the policy in force then",
    # so its captured reuse record must not be re-derived from today's policy - the same reason
    # the digest check is skipped. Structural provenance above still runs, and verify_intake
    # binds the article to its captured bytes. Re-running this gate for the archive is what
    # made every historical page fail to render after a licence edit, blocking all publishing.
    if policy_gate and source.get('reuse') != reuse(provider):
        raise ValueError('Source/reuse policy mismatch')
    if len(sources) > MAX_PACKET_SOURCES:
        raise ValueError('Too many sources for a reviewed release')
    for extra in sources[1:]:
        if not extra.get('related'):
            raise ValueError('Additional sources must be marked as related corroboration')
        if not str(extra.get('url', '')).startswith('https://'):
            raise ValueError('Related source must be a real HTTPS URL')
        if extra.get('publisher') == provider['publisher']:
            raise ValueError('A publisher cannot corroborate itself')
    docs = packet.get('supporting_documents', [])
    if len(docs) != 1:
        raise ValueError('Missing exact rights evidence')
    rights = docs[0]
    if (rights.get('id') != 'RIGHTS' or rights.get('url') != provider['rights_url'] or
        hashlib.sha256(rights.get('text','').encode()).hexdigest() != provider['rights_text_sha256'] or
        not re.fullmatch(SHA, rights.get('sha256','')) or
        not re.fullmatch(SHA, basis.get('source_sha256','')) or
        basis.get('source_fields_sha256') != digest(source)):
        raise ValueError('Rights/source provenance mismatch')
    return {'image_sha256': None, 'text_only': {'policy':TEXT_POLICY,'policy_sha256':digest(spec),
            'provenance_sha256':digest({'basis':basis,'sources':sources,'rights':docs})}}


def verify_intake(packet, state):
    """Bind the stored, reviewed text to actual captured upstream bytes before release."""
    from .official import rights_text, source_fields, policy, ADDITIONAL_PROVIDERS
    basis = packet['publication_basis'];provider = basis['provider']
    directory = Path(state)/'intake'/digest(packet)
    raw = (directory/'source.html').read_bytes();rights = (directory/'rights.html').read_bytes()
    if hashlib.sha256(raw).hexdigest() != basis['source_sha256'] or hashlib.sha256(rights).hexdigest() != packet['supporting_documents'][0]['sha256']:
        raise ValueError('Captured intake bytes changed')
    if rights_text(rights,provider) != packet['supporting_documents'][0]['text']:
        raise ValueError('Captured rights text changed')
    parsed = source_fields(raw,provider,packet['sources'][0]['url'])
    if any(packet['sources'][0].get(k) != v for k,v in parsed.items()):
        raise ValueError('Captured source differs from reviewed packet')
    if provider in ADDITIONAL_PROVIDERS:
        receipt = json.loads((directory/'receipt.json').read_text())
        expected = {'fixture':False, 'provider':provider, 'source_url':packet['sources'][0]['url'],
                    'source_sha256':basis['source_sha256'], 'packet_sha256':digest(packet),
                    'rights_url':packet['supporting_documents'][0]['url'],
                    'rights_sha256':packet['supporting_documents'][0]['sha256'],
                    'rights_text_sha256':policy()['providers'][provider]['rights_text_sha256'],
                    'publication_basis':basis, 'image_status':'explicit-text-only',
                    'retrieved_at':packet['supporting_documents'][0]['retrieved_at']}
        if receipt != expected or json.loads((directory/'packet.json').read_text()) != packet:
            raise ValueError('Captured intake receipt/packet identity mismatch')



def receipt_media(receipt):
    # Absence is the original legacy schema; no v2 fields may leak into it.
    if 'schema_version' not in receipt:
        legacy={'public_release_authorized','hermes_step','origin','ga4_id','source_commit',
                'job_id','packet_sha256','draft_sha256','image_sha256','new_article_files','files'}
        sha=receipt.get('image_sha256')
        if set(receipt)!=legacy or not isinstance(sha,str) or not re.fullmatch(SHA,sha):
            raise ValueError('Ambiguous or invalid legacy receipt')
        return {'image_sha256':sha}
    if type(receipt['schema_version']) is not int or receipt['schema_version']!=2:
        raise ValueError('Unknown receipt schema version')
    required={'packet','draft','review','packet_sha256','draft_sha256','image_sha256'}
    if not required <= receipt.keys():
        raise ValueError('Missing v2 receipt fields')
    packet,draft,review=(receipt[k] for k in ('packet','draft','review'))
    if receipt['packet_sha256']!=digest(packet) or receipt['draft_sha256']!=digest(draft):
        raise ValueError('Receipt packet/draft mismatch')
    if not validate_review(review,draft)['approved']:
        raise ValueError('Unapproved receipt')
    expected=media(packet,draft)
    actual={'image_sha256':receipt['image_sha256']}
    if 'text_only' in receipt:actual['text_only']=receipt['text_only']
    if expected!=actual:
        raise ValueError('Receipt media/provenance mismatch')
    return expected


def check_article(html,packet,draft,canonical=None):
    """Same reviewed content contract for bundle validation and canonical readback."""
    from html import escape
    esc=lambda value:escape(str(value),quote=True)
    required=[draft['title'],draft['summary']]+[p['text'] for p in draft['paragraphs']]
    for source in packet['sources']:
        required.append(source['url'])
        if source.get('reuse'):
            required += [source['reuse']['url'],source['reuse']['license'],source['reuse']['changes']]
            if 'notice' in source['reuse']: required.append(source['reuse']['notice'])
            if 'license_url' in source['reuse'] and ('href="'+esc(source['reuse']['license_url'])+'"') not in html:
                raise ValueError('Missing direct reuse licence link')
    image=draft.get('image')
    if image is None:
        if '<img' in html or 'Tämä uutinen julkaistaan ilman kuvaa.' not in html or 'Luonnos' in html:
            raise ValueError('Dishonest text-only public page')
    else:
        required += [image['license_url'],image['license']]
    if any(esc(value) not in html for value in required):
        raise ValueError('Public article differs from reviewed content/licence')
    if canonical is not None and ('href="'+esc(canonical)+'"') not in html:
        raise ValueError('Canonical article URL mismatch')


def deployment_record(receipt, deployment, commit):
    """Used by the actual Actions command and isolated tests."""
    binding = receipt_media(receipt)
    if deployment['environment'] != 'production' or deployment['latest_stage']['status'] != 'success' or deployment['deployment_trigger']['metadata']['commit_hash'] != commit:
        raise ValueError('Deployment identity mismatch')
    return {'deployment_id':deployment['id'],'deployment_url':deployment['url'],
            'canonical_origin':'https://uutistenlukija.fi','remote_commit':commit,
            'source_commit':receipt['source_commit'],'packet_sha256':receipt['packet_sha256'],
            'draft_sha256':receipt['draft_sha256'],'job_id':receipt['job_id'],**binding}
