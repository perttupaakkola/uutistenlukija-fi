"""Portable synthetic amendment positive and ordinary compatibility controls.

No model, network, database or core-validator mocks. Synthetic receipts are
explicitly test-only; actual immutable receipts are replayed separately.
"""
import copy
import unittest

from news_mvp.editorial import digest
from news_mvp.release_contract import (
    AMENDMENT_RELEASE, deployment_record, media, receipt_media,
)


def ordinary():
    sha = 'a' * 64
    image = {'generated': False, 'sha256': sha, 'local_path': 'media/'+sha+'.jpg',
             'url': 'https://example.org/photo.jpg', 'source_url': 'https://example.org/photo/',
             'license_url': 'https://example.org/license/', 'license': 'Synthetic permission',
             'alt': 'Synthetic museum image', 'credit': 'Synthetic photographer'}
    packet = {'fixture': False, 'sources': [{'id': 'A'}], 'image': image}
    draft = {'title': 'Museum programme', 'summary': 'Synthetic museum programme summary.',
             'category': 'Kulttuuri', 'image': image,
             'paragraphs': [{'text': 'Synthetic first paragraph.', 'source_ids': ['A']},
                            {'text': 'Synthetic second paragraph.', 'source_ids': ['A']}]}
    review = {'approved': True, 'draft_sha256': digest(draft),
              'reasons': ['Synthetic test approval only.']}
    receipt = {'schema_version': 2, 'packet': packet, 'draft': draft, 'review': review,
               'packet_sha256': digest(packet), 'draft_sha256': digest(draft),
               'image_sha256': sha, 'job_id': 'b'*64, 'source_commit': 'c'*40}
    return packet, draft, receipt


def deployment():
    return {'id': 'synthetic', 'url': 'https://example.org/deploy',
            'environment': 'production', 'latest_stage': {'status': 'success'},
            'deployment_trigger': {'metadata': {'commit_hash': 'd'*40}}}


class AmendmentConsumerTests(unittest.TestCase):
    def test_ordinary_v2_positive_and_no_input_mutation(self):
        packet, draft, receipt = ordinary()
        before = copy.deepcopy(receipt)
        self.assertEqual(media(packet, draft),
                         {'image_sha256': 'a'*64, 'text_provenance': 'not-applicable'})
        self.assertEqual(receipt_media(receipt), {'image_sha256': 'a'*64})
        self.assertEqual(receipt, before)

    def test_legacy_positive(self):
        legacy = dict.fromkeys({'public_release_authorized', 'hermes_step', 'origin', 'ga4_id',
            'source_commit', 'job_id', 'packet_sha256', 'draft_sha256', 'image_sha256',
            'new_article_files', 'files'}, None)
        legacy['image_sha256'] = 'a'*64
        self.assertEqual(receipt_media(legacy), {'image_sha256': 'a'*64})

    def test_ordinary_deployment_positive_and_commit_refusal(self):
        _, _, receipt = ordinary()
        record = deployment_record(receipt, deployment(), 'd'*40)
        self.assertEqual(record['packet_sha256'], receipt['packet_sha256'])
        self.assertNotIn('amendment', record)
        with self.assertRaises(ValueError):
            deployment_record(receipt, deployment(), 'e'*40)

    def test_explicit_dispatch_precedes_ordinary_validation(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported amendment release fields'):
            media({'schema': AMENDMENT_RELEASE}, {})

    def test_removed_or_changed_packet_marker_refuses(self):
        packet, draft, _ = ordinary()
        for marker in (None, 'published-amendment-release-v0'):
            modified = copy.deepcopy(packet)
            modified['preparation_json'] = '{}'
            if marker is not None:
                modified['schema'] = marker
            with self.assertRaisesRegex(ValueError, 'marker missing or unsupported'):
                media(modified, draft)

    def test_v2_amendment_downgrade_refuses_without_mutation(self):
        _, _, receipt = ordinary()
        receipt['amendment'] = {'schema': AMENDMENT_RELEASE}
        before = copy.deepcopy(receipt)
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            receipt_media(receipt)
        self.assertEqual(receipt, before)
        receipt.pop('amendment')
        receipt['packet']['schema'] = AMENDMENT_RELEASE
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            receipt_media(receipt)

    def test_v3_removed_marker_and_unknown_versions_refuse(self):
        _, _, receipt = ordinary()
        for version in (3, 4, True, '3'):
            modified = copy.deepcopy(receipt)
            modified['schema_version'] = version
            with self.assertRaises(ValueError):
                receipt_media(modified)

    def test_reviewed_draft_mutation_refuses(self):
        _, _, receipt = ordinary()
        receipt['draft']['paragraphs'][0]['text'] = 'Mutated body.'
        receipt['draft_sha256'] = digest(receipt['draft'])
        with self.assertRaisesRegex(ValueError, 'Review is not bound'):
            receipt_media(receipt)




RIGHTS_TEXT = 'Käyttöoikeus määritellyin ehdoin hyödynnettävissä. Datan käytön lisäksi Palvelussa on mahdollisuus keskusteluun.\nKäyttöoikeus\nPalvelu sisältää dataa useasta eri lähteestä: julkisyhteisöjen tuottamia datoja ja niiden metatietoja, Palvelun käyttäjien tuottamia kirjoituksia ja kommentteja ja Palvelun ylläpitäjien tuottamia artikkeleja ja muita kirjoituksia. Pääsääntöisesti näihin kaikkiin on laaja käyttöoikeus Creative Commons Nimeä 4.0 Kansainvälinen -lisenssin ehtojen mukaisesti. Poikkeukset on kerrottu erikseen kunkin aineiston kohdalla.\nAvoin data\nPalvelussa olevien datojen (tietoaineistojen) omistus- ja immateriaalioikeudet kuuluvat kunkin datan tekijälle.\nPääsääntöisesti Palvelun käyttäjillä on laaja käyttöoikeus datoihin Creative Commons Nimeä 4.0 Kansainvälinen -lisenssin ehtojen mukaisesti. Datoja saa vapaasti kopioida, levittää, näyttää ja esittää sekä käyttää datoja osana muuta teosta. Datoja voi käyttää sekä ei-kaupallisiin että kaupallisiin tarkoituksiin.\nEhtona käytölle on, että datan tekijä (ylläpitäjä) on ilmoitettava. Datan tekijän pyynnöstä tämä viittaus on poistettava. Datan tekijä on kerrottu kunkin datan metadatassa.\nDatan tekijää ei saa ilmoittaa siten, että ilmoitus viittaisi datan tekijän tai Palvelun tukevan datan käyttäjää tai datan käyttötapaa.\nDatojen metatietojen yhteydessä on mainittu kyseisen datan käyttöoikeusehdot. Joissakin tapauksissa käyttöoikeusehdot voivat poiketa yllä mainitusta.\nKeskustelu\nPalvelun käyttäjät voivat keskusteluosiossa lisätä sivuille kirjoituksia ja kommentoida toisten käyttäjien kirjoituksia. Palvelun käyttäjä antaa kirjoituksiinsa ja kommentteihinsa vapaan käyttöoikeuden Creative Commons Nimeä 4.0 Kansainvälinen -lisenssin ehtojen mukaisesti.\nMikäli käyttäjä liittää kirjoitukseensa tai kommenttiinsa kuvia, tulee hänellä olla tekijänoikeudet kuvaan. Lisäksi hänellä tulee olla kuvassa esiintyvien henkilöiden lupa kuvan julkaisemiseen internetissä. Palvelun käyttäjä antaa kuviin vapaan käyttöoikeuden Creative Commons Nimeä 4.0 Kansainvälinen -lisenssin ehtojen mukaisesti.\nKeskustelun tulee olla hyvän tavan ja Suomen lainsäädännön mukaista. Käyttäjät ovat vastuussa lisäämistään kirjoituksista ja kommenteista.\nKaikenlainen mainonta keskustelussa on kielletty.\nPalvelun tarjoajat voivat tarvittaessa muokata kirjoituksia ja kommentteja sekä poistaa hyvän tavan tai lainsäädännön vastaisia tai muutoin sopimattomia kirjoituksia.\nMikäli käyttäjä havaitsee käyttöehtojen vastaisia kirjoituksia, pyydetään tästä ilmoittamaan ylläpidolle.\nToistuva käyttöehtojen rikkominen tai niiden vakava rikkominen voi johtaa väliaikaiseen tai pysyvään Palvelun käyttöoikeuden peruuttamiseen.\nSovellusgalleria\nSovellusgalleriassa esitellyt sovellukset eivät ole HRI:n tekemiä ja niiden tekijänoikeudet kuuluvat sovellusten tekijöille. Creative Commons 4.0 -lisenssi ei koske sovelluksia, eikä niitä ole lupa vapaasti kopioida, levittää, muokata tai yhdistellä, ellei erikseen sovelluksen kohdalla ole toisin mainittu tai sovelluksen tekijä muutoin ole tähän antanut lupaa.\nMuut palvelussa olevat kirjoitukset\nPalvelun tuottajien Palvelussa julkaisemien kirjoitusten, kuten artikkelien ja blogikirjoitusten omistus- ja tekijänoikeudet kuuluvat niiden kirjoittajille. Palvelun käyttäjillä on laaja käyttöoikeus näihin kirjoituksiin Creative Commons Nimeä 4.0 Kansainvälinen -lisenssin ehtojen mukaisesti.\nPalvelun ulkoasu, tekninen toteutus, tavaramerkit ja logot\nPalvelun teknisen toteutuksen lähdekoodit on saatavilla avoimesti GitHubista. Palvelun kopiointi sellaisenaan on kielletty. Palvelussa esiintyvien tavaramerkkien ja logojen tavaramerkkioikeudet kuuluvat niiden oikeudenhaltijoille. Mikäli tavaramerkkien ja logojen muu käyttö on sallittu, on tästä ja käytön ehdoista ilmoitettu ko. tavaramerkkien ja logojen kohdalla.\nTietosuoja\nhri.fi-palvelua ylläpitää Helsingin kaupunki. Kaupunki on sitoutunut suojaamaan verkkopalveluidensa käyttäjien yksityisyyttä Tietosuojalain (2018), EU:n tietosuoja-asetuksen (2016/679) sekä muun soveltuvan lainsäädännön mukaisesti.\nHelsingin kaupungin tietosuojasivut\nVastuuvapaus\nPalvelu sisältää sekä julkisyhteisöjen tuottamaa avointa dataa ja metadataa että Palvelun käyttäjien tuottamia kirjoituksia ja kommentteja. Palvelun tarjoajat eivät vastaa Palvelussa olevien tietojen oikeellisuudesta. Palvelun käyttäjä käyttää Palvelussa olevaa avointa dataa omalla vastuullaan. Palvelun tarjoajat eivät vastaa mistään välittömistä tai välillisistä vahingoista, jotka aiheutuvat datan käytöstä. '

# All prose, capture receipts, image pixels and model receipts below are synthetic.
# Only the policy's public rights text and pinned ordinary prompt are real bytes.
import hashlib
import json
from pathlib import Path
from news_mvp import official, imagery
from news_mvp.editorial import encode
from news_mvp.amendment_review import build_review_envelope
from tests.test_amendment_review import artifact_bytes

SOURCE_REF = '35b2f5a812e4de81621d928c48528b0ea9c83710'


def set_version(packet):
    e = packet['final_review_input']['source_packet']
    artifact = e['preparation']; ev = artifact['evidence']
    pred = {k: ev[k] for k in ('predecessor_packet_sha256', 'predecessor_draft_sha256', 'predecessor_publication_sha256')}
    content = {'job_id': ev['job_id'], 'predecessor': pred,
        'preparation_sha256': hashlib.sha256(packet['preparation_json'].encode()).hexdigest(),
        'captures': {role: c['binding'] for role, c in artifact['captures'].items()},
        'selection_sha256': digest(packet['selection']),
        'selection_bytes_sha256': hashlib.sha256(packet['selection_json'].encode()).hexdigest(),
        'review_input_sha256': digest(packet['final_review_input']),
        'review_result_sha256': digest(packet['final_review_result']),
        'draft_sha256': digest(e['final_draft']), 'image_sha256': digest(e['final_image']),
        'public_metadata': e['public_metadata']}
    packet['version'] = {'id': 'sha256:'+digest(content), 'content_sha256': digest(content), 'predecessor': pred}


def portable_amendment():
    artifact = json.loads(artifact_bytes())
    spec = official.policy(); provider = spec['providers']['vantaa']
    capture_json = {}
    for role, capture in artifact['captures'].items():
        source = {'id': 'A', 'title': 'Synthetic '+role, 'publisher': provider['publisher'],
            'url': 'https://www.vantaa.fi/fi/ajankohtaista/uutinen/synthetic-'+role,
            'published_at': '2026-10-01T00:00:00+00:00', 'text': 'Synthetic complete source prose. '*12,
            'reuse': official.reuse(provider)}
        packet = {'fixture': False, 'image': None, 'story_key': 'url:'+source['url'],
            'sources': [source], 'supporting_documents': [{'id': 'RIGHTS', 'url': provider['rights_url'],
                'text': RIGHTS_TEXT, 'sha256': 'b'*64}],
            'publication_basis': {'provider': 'vantaa', 'policy': 'official-text-v1',
                'policy_sha256': digest(spec), 'source_sha256': 'c'*64, 'source_fields_sha256': digest(source)}}
        receipt = {'synthetic': role, 'packet_sha256': digest(packet), 'source_sha256': 'c'*64}
        raw_packet = encode(packet); raw_receipt = encode(receipt)
        capture_json[role] = {'packet': raw_packet, 'receipt': raw_receipt}
        capture.update(packet=packet, receipt=receipt, binding={
            'packet_sha256': hashlib.sha256(raw_packet.encode()).hexdigest(),
            'receipt_sha256': hashlib.sha256(raw_receipt.encode()).hexdigest()},
            validation_draft={'title': 'Synthetic capture', 'summary': 'Synthetic capture summary.', 'category': 'Kulttuuri',
                'paragraphs': [{'text': 'Synthetic first paragraph.', 'source_ids': ['A']},
                               {'text': 'Synthetic second paragraph.', 'source_ids': ['A']}], 'image': None})
        artifact['evidence'][role+'_capture'] = capture['binding']
        next(c for c in artifact['citations'] if c['role'] == role)['capture_source'] = source
        artifact['rights'][0 if role == 'original' else 1].update(publication_basis=packet['publication_basis'], reuse=source['reuse'], document=packet['supporting_documents'][0])
    job = artifact['predecessor']['job']; pub = artifact['predecessor']['publication']; ev = artifact['evidence']
    original = artifact['captures']['original']['packet']
    job.update(story_key=original['story_key'], source_url=original['sources'][0]['url'], packet=encode(original))
    artifact['identity'].update(story_key=job['story_key'], source_url=job['source_url'])
    pub['packet_sha'] = digest(original); ev['predecessor_packet_sha256'] = digest(original)
    ev['predecessor_publication_sha256'] = digest(pub)
    raw = encode(artifact); e = build_review_envelope(raw.encode())
    draft = copy.deepcopy(e['final_draft'])
    sha = hashlib.sha256(b'synthetic image bytes').hexdigest()
    photo_url = 'https://www.pexels.com/photo/synthetic-54321/'
    provenance = {'provider': 'pexels', 'photo_id': 54321, 'photographer': 'Synthetic Photographer',
        'photographer_url': 'https://www.pexels.com/@synthetic', 'photo_url': photo_url,
        'query': 'synthetic manor', 'retrieved_at': '2026-10-01T00:00:00Z',
        'image_url': 'https://images.pexels.com/photos/54321/pexels-photo-54321.jpeg'}
    decision = {'version': imagery.ARTICLE_IMAGE_VERSION, 'category': 'Kulttuuri',
        'concepts': [{'rank': rank, 'safe_to_generate': True, 'subject': 'Synthetic manor',
            'depictable_scene': 'Synthetic manor exterior' if rank == 1 else 'Synthetic manor garden', 'must_show': ['manor'], 'must_avoid': ['logos'],
            'search_queries': ['manor exterior', 'manor garden', 'manor entrance']} for rank in (1, 2)]}
    pixel = {'approved': True, 'no_people': True, 'description': 'Synthetic manor exterior',
        'alt_fi': 'Synteettinen kartanon julkisivu.', 'reason': 'Synthetic positive only',
        'image_sha256': sha, 'article_text_sha256': imagery._article_text_sha(draft),
        'model': 'synthetic-not-model-execution', 'reviewed_at': '2026-10-01T00:00:00Z', 'fit_score': 9,
        'concept_sha256': digest(imagery.concept_decision(decision, decision['concepts'][0])), 'must_show_visible': [True]}
    image = {'generated': False, 'sha256': sha, 'local_path': 'media/'+sha+'.jpg',
        'url': 'https://uutistenlukija.fi/media/'+sha+'.jpg', 'source_url': photo_url,
        'stock_provenance': provenance, 'stock_provenance_sha256': digest(provenance),
        'credit': 'Photo by Synthetic Photographer on Pexels', 'license': 'Pexels License',
        'license_url': 'https://www.pexels.com/license/', 'alt': pixel['alt_fi'],
        'caption': 'Arkistokuva. Kuva ei esitä uutisen tapahtumaa.', 'hotlink': False,
        'pixels': {'width': 1200, 'height': 800, 'mode': 'RGB', 'variance': [120.0, 80.0, 160.0]},
        'depicted': 'Synthetic manor', 'classifier_output': decision, 'pixel_review': pixel,
        'relevance_check': {'accepted': True, 'method': 'metadata', 'evidence': 'Synthetic manor', 'matched': ['manor'], 'reason': 'Synthetic only'},
        'selection_evidence': {'version': imagery.ARTICLE_IMAGE_VERSION, 'article_text_sha256': imagery._article_text_sha(draft),
            'decision_sha256': digest(decision), 'minimum_real_fit': imagery.MIN_REAL_FIT,
            'searches': [{'concept_rank': rank, 'provider': 'pexels', 'queries': ['manor exterior'],
                'outcome': 'accepted' if rank == 1 else 'no_qualifying_candidate',
                'candidates': [{'image_sha256': sha, 'source_url': photo_url, 'license': 'Pexels License',
                    'fit_score': 9, 'approved': True, 'reason': 'Synthetic only'}] if rank == 1 else []} for rank in (1, 2)],
            'selected': {'kind': 'real', 'concept_rank': 1, 'fit_score': 9, 'image_sha256': sha}}}
    selection = {'status': 'selection_completed', 'preparation_sha256': hashlib.sha256(raw.encode()).hexdigest(),
        'draft_sha256': digest(draft), 'activation': False, 'release_authorization': False,
        'selected_image_sha256': sha, 'image': image}
    selection_raw = encode(selection)+'\n'; draft['image'] = image
    e.update(schema='private-amendment-combined-review-envelope-v1',
        scope='COMBINED FINAL TEXT AND IMAGE REVIEW; NO ACTIVATION OR RELEASE AUTHORITY',
        final_draft=draft, final_image=image, selection_bytes_sha256=hashlib.sha256(selection_raw.encode()).hexdigest(),
        independent_image_assessment={'selected_sha256': sha, 'fit_score': 9, 'local_image_sha256_verified': True,
            'independent_pixel_verdict': 'ACCEPTED_FOR_ARCHIVAL_MANOR_CONTEXT_ONLY', 'activation': False,
            'normal_approval': False, 'release': False, 'reader_exposure_actions': 0, 'reason': 'Synthetic only'})
    e['bindings'].update(final_draft_sha256=digest(draft), final_image_sha256=digest(image))
    e['validation'].update(capture_reconstruction='Both exact original captures passed media(policy_gate=True) and verify_intake in this execution',
        exact_final_image_execution='Fresh installed article-first selection and pixel review, validated against complete final draft; exact local image SHA verified')
    context = {'operation': 'published_amendment_combined_review', 'review_envelope_sha256': digest(e),
        'original_canonical': e['public_metadata']['canonical'], 'source_relationship': e['source_relationship'],
        'actual_diff': e['actual_diff'], 'normal_activation': False, 'release_authorization': False}
    request = {'source_packet': e, 'context': context, 'draft': draft, 'draft_sha256': digest(draft)}
    prompt = (Path(__file__).resolve().parents[1]/'prompts/reviewer.md').read_text()
    review = {'approved': True, 'draft_sha256': digest(draft), 'reasons': ['Synthetic approval, not model execution.']}
    result = {'status': 'completed', 'combined_model_approval': True, 'final_draft_sha256': digest(draft),
        'review_envelope_sha256': digest(e), 'preparation_sha256': selection['preparation_sha256'],
        'selection_bytes_sha256': e['selection_bytes_sha256'], 'image_sha256': sha, 'source_ref': SOURCE_REF,
        'activation': False, 'release_authorization': False, 'production_state_writes': False, 'normal_approval_installed': False,
        'review': review, 'same_call_receipt': {'role': 'reviewer', 'exit_code': 0, 'session_id': 'synthetic-session',
            'prompt_sha256': hashlib.sha256((prompt+'\n\nINPUT JSON:\n'+encode(request)).encode()).hexdigest(), 'response_sha256': digest(review)}}
    packet = {'schema': AMENDMENT_RELEASE, 'preparation_json': raw, 'capture_json': capture_json,
        'selection': selection, 'selection_json': selection_raw, 'final_review_input': request, 'final_review_result': result,
        'reviewer_prompt': {'source_ref': SOURCE_REF, 'text': prompt, 'sha256': hashlib.sha256(prompt.encode()).hexdigest()}, 'version': {}}
    set_version(packet)
    return packet, draft


class PortableAmendmentTests(unittest.TestCase):
    def test_unmocked_portable_v3_and_deployment_positive(self):
        packet, draft = portable_amendment(); before = copy.deepcopy(packet)
        binding = media(packet, draft)
        receipt = {'schema_version': 3, 'packet': packet, 'draft': draft, 'review': packet['final_review_result']['review'],
            'packet_sha256': digest(packet), 'draft_sha256': digest(draft), 'job_id': binding['amendment']['job_id'],
            'source_commit': SOURCE_REF, **binding}
        self.assertEqual(receipt_media(receipt), binding)
        self.assertEqual(deployment_record(receipt, deployment(), 'd'*40)['amendment'], binding['amendment'])
        self.assertEqual(packet, before)
        # Build provenance differs from the independently pinned historic review.
        receipt['source_commit'] = 'a'*40
        self.assertEqual(receipt_media(receipt), binding)
        for invalid in (None, True, 'a'*39, 'g'*40, 'a'*64):
            receipt['source_commit'] = invalid
            with self.assertRaisesRegex(ValueError, 'Receipt amendment/version mismatch'):
                receipt_media(receipt)

    def test_missing_foreign_relabel_raw_and_prompt_controls(self):
        original, draft = portable_amendment()
        for mutation in ('missing', 'foreign', 'response', 'bool_exit', 'session', 'relabel', 'rebound_envelope', 'raw', 'source', 'prompt', 'selection', 'authority', 'context'):
            with self.subTest(mutation=mutation):
                packet = copy.deepcopy(original); result = packet['final_review_result']
                if mutation == 'missing': result.pop('same_call_receipt')
                elif mutation == 'foreign': result['same_call_receipt']['prompt_sha256'] = '0'*64
                elif mutation == 'response': result['same_call_receipt']['response_sha256'] = '0'*64
                elif mutation == 'bool_exit': result['same_call_receipt']['exit_code'] = False
                elif mutation == 'session': result['same_call_receipt']['session_id'] = ' '
                elif mutation == 'relabel': packet['final_review_input']['source_packet']['schema'] = 'normal-amendment-text-review-envelope-v1'
                elif mutation == 'rebound_envelope':
                    e = packet['final_review_input']['source_packet']
                    e['independent_image_assessment']['reason'] = 'Manufactured reassignment of existing approval'
                    result['review_envelope_sha256'] = digest(e)
                    packet['final_review_input']['context']['review_envelope_sha256'] = digest(e)
                elif mutation == 'raw': packet['selection_json'] += ' '
                elif mutation == 'source': result['source_ref'] = '0'*40
                elif mutation == 'prompt': packet['reviewer_prompt']['text'] += ' '
                elif mutation == 'selection': packet['selection']['selected_image_sha256'] = '0'*64
                elif mutation == 'authority': result['activation'] = True
                elif mutation == 'context': packet['final_review_input']['context']['normal_activation'] = True
                set_version(packet)
                message = ('same-call receipt' if mutation in
                           ('missing', 'foreign', 'response', 'bool_exit', 'session', 'rebound_envelope') else '')
                with self.assertRaisesRegex(ValueError, message): media(packet, draft)

if __name__ == '__main__':
    unittest.main()
