"""Regressions captured from the 2026-10-27--29 production image loops."""
import copy
import unittest

from news_mvp import imagery


def concept(rank, safe, subject, scene, show, queries, avoid=None):
    return {'rank': rank, 'safe_to_generate': safe, 'subject': subject,
            'depictable_scene': scene, 'must_show': show,
            'must_avoid': avoid or ['people, faces, hands or other body parts'],
            'search_queries': queries}


JOKILAAKSO_DRAFT = {
    'title': 'Jokilaaksojen liikennevalvonnassa kaksi rattijuopumusta',
    'summary': ('Oulun poliisilaitoksen valvontaryhmä pysäytti kaksi kuljettajaa ja '
                'mittasi moottoripyörälle ylinopeuden.'),
    'category': 'Kotimaa',
    'paragraphs': [{'source_ids': ['A'], 'text':
        'Kuljettajan alkometrin puhalluslukema johti rattijuopumusepäilyyn.'}],
}
JOKILAAKSO_OUTPUT = {'version': 'article-first-v1', 'category': 'Kotimaa', 'concepts': [
    concept(1, False, 'Oulun poliisilaitoksen liikenteen valvontaryhmä tienvarressa',
        ('Suomalainen poliisiauto pysäköitynä kaksikaistaisen maantien pientareelle. '
         'Konstaapeli voi seistä auton vieressä valvomassa liikennettä.'),
        ['Finnish police car', 'roadside traffic control'],
        ['Oulun poliisilaitos liikennevalvonta', 'poliisiauto liikennevalvonta',
         'Finnish police car roadside']),
    concept(2, True, 'Alkometrin puhalluslukema',
        ('Käsikäyttöinen alkometri, jossa on kertakäyttöinen puhallussuukappale ja '
         'tumma tyhjä näyttö, lepää harmaalla auton kojelaudalla.'),
        ['handheld breathalyzer', 'disposable mouthpiece'],
        ['alkometri puhalluskoe', 'handheld breathalyzer device',
         'breathalyzer disposable mouthpiece']),
    concept(3, False, 'moottoripyörän ylinopeus Ylivieskan Ouluntiellä',
        ('Ylivieskan Ouluntie kaksikaistaisena maantienä, jonka varressa on '
         'nopeusrajoitusmerkki ja tiellä ajaa moottoripyörä kuljettajineen.'),
        ['motorcycle on two-lane road', 'speed limit sign'],
        ['Ouluntie Ylivieska', 'Ylivieska Ouluntie maantie',
         'motorcycle two-lane road Finland', '80 km/h nopeusrajoitusmerkki']),
]}

KAARINA_DRAFT = {
    'title': 'Kaarinasta kadonnut 78-vuotias mies löytyi Turusta',
    'summary': ('Mies löytyi turkulaisesta majoitusliikkeestä, ja majoitusliikkeen '
                'vastaanottovirkailija auttoi poliisia.'),
    'category': 'Kotimaa',
    'paragraphs': [{'source_ids': ['A'], 'text':
        'Poliisi löysi myös ajoneuvon Turusta.'}],
}
KAARINA_OUTPUT = {'version': 'article-first-v1', 'category': 'Kotimaa', 'concepts': [
    concept(1, True, 'Majoitusliikkeen vastaanottotiski',
        ('Tyhjä majoitusliikkeen vastaanottotiski hotellin aulassa aamuvalossa; '
         'puinen tiski ja pöytäkello.'),
        ['empty hotel reception counter', 'hotel lobby in morning light'],
        ['hotellin vastaanottotiski', 'hotel reception desk',
         'empty hotel lobby counter']),
    concept(2, False, 'Poliisi ja ajoneuvo',
        'Suomalainen poliisiauto pysäköitynä kadunvarteen kaupunkiympäristössä.',
        ['Finnish police car', 'urban street'],
        ['poliisiauto Turku', 'Finnish police car', 'police car street Finland']),
    concept(3, False, 'Kaupunkinäkymä Turusta',
        'Turun keskustaa Aurajoen varrelta, joki, silta ja rantakadun rakennukset.',
        ['Aura river', 'Turku city centre'],
        ['Turku Aurajoki', 'Turku city centre', 'Aura river bridge Turku']),
]}

HELSINKI_DRAFT = {
    'title': 'Helsingin kotoutumiskoulutukseen pääsee nyt nopeasti',
    'summary': 'Kotoutumiskoulutukseen osallistuu vuosittain noin 3 000 työnhakijaa.',
    'category': 'Kotimaa',
    'paragraphs': [{'source_ids': ['A'], 'text':
        'Kotoutumiskoulutus sisältää opetusta ja kotitehtäviä 35 tuntia viikossa '
        'Helsingin työllisyyspalveluissa.'}],
}
HELSINKI_OUTPUT = {'version': 'article-first-v1', 'category': 'Kotimaa', 'concepts': [
    concept(1, False, 'Kotoutumiskoulutus: aikuiset opiskelevat suomea luokassa',
        ('Aikuisia opiskelijoita istumassa pulpettien ääressä ja opettaja '
         'valkotaulun vieressä.'),
        ['adult students at classroom desks', 'language lesson in progress'],
        ['kotoutumiskoulutus luokkahuone Helsinki', 'suomen kielen opetus aikuisille',
         'adult Finnish language class']),
    concept(2, True, 'Opetusta ja kotitehtäviä kielen opiskeluun',
        ('Luokkahuoneen pulpetilla avoin kielioppikirja, avoimia ruutuvihkoja ja '
         'kynä; taustalla tyhjiä tuoleja ja valkotaulu.'),
        ['open textbook and notebooks on a desk', 'classroom background with whiteboard'],
        ['kielioppikirja vihko pulpetti', 'Finnish textbook notebook desk',
         'open notebook pen classroom']),
    concept(3, False, 'Helsingin työllisyyspalvelut',
        'Helsingin työllisyyspalvelujen toimipisteen sisäänkäynti kaupunkiympäristössä.',
        ['employment services office entrance'],
        ['Helsingin työllisyyspalvelut toimipiste', 'Työllisyyspalvelut Helsinki sisäänkäynti',
         'Helsinki employment services office']),
]}

STUBB_DRAFT = {
    'title': 'Stubb ja Støre keskustelivat Putinin kanssa',
    'summary': 'Presidentti ja ministerivaliokunta saivat kokouksessa katsauksen puhelusta.',
    'category': 'Maailma',
    'paragraphs': [{'source_ids': ['A'], 'text':
        'TP-UTVA käsitteli keskustelua kokouksessa.'}],
}
STUBB_OUTPUT = {'version': 'article-first-v1', 'category': 'Maailma', 'concepts': [
    concept(1, False, 'Alexander Stubb ja Jonas Gahr Støre',
        ('Alexander Stubb ja Jonas Gahr Støre seisovat vierekkäin virallisessa '
         'tapaamisessa.'),
        ['Alexander Stubb and Jonas Gahr Støre together', 'official meeting setting'],
        ['Alexander Stubb Jonas Gahr Støre', 'Stubb Støre tapaaminen',
         'Finland Norway flags meeting']),
    concept(2, False, 'TP-UTVA',
        ('Presidentti ja ministerivaliokunnan jäsenet istuvat pitkän '
         'kokouspöydän ääressä.'),
        ['ministers seated at a meeting table', 'official government meeting room'],
        ['TP-UTVA kokous', 'ulko- ja turvallisuuspoliittinen ministerivaliokunta',
         'government meeting table Finland']),
    concept(3, True, 'katsauksen puhelusta',
        ('Tumma pöytäpuhelin luuri paikallaan puisella kokouspöydällä, vieressä '
         'suljettu kansio ja tyhjä vesilasi.'),
        ['desk telephone on a conference table', 'closed document folder'],
        ['desk telephone conference table', 'pöytäpuhelin kokouspöytä',
         'telephone handset wooden table']),
]}


class SequenceModel:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def call(self, role, packet, draft, *, context=None):
        self.calls.append((role, packet, draft, context))
        return self.responses.pop(0)


class ClassifierRecoveryTests(unittest.TestCase):
    def test_production_replays_have_a_usable_people_free_concept(self):
        # Exact responses recovered from Hermes state for 568211dc and 6221afbf,
        # and the equivalent stored responses for 78dfd75c and 134c2bbc.
        for draft, output, safe_rank in (
                (JOKILAAKSO_DRAFT, JOKILAAKSO_OUTPUT, 2),
                (KAARINA_DRAFT, KAARINA_OUTPUT, 1),
                (HELSINKI_DRAFT, HELSINKI_OUTPUT, 2),
                (STUBB_DRAFT, STUBB_OUTPUT, 3)):
            with self.subTest(title=draft['title']):
                result = imagery.validate_image_decision(
                    output, draft, require_concepts=True)
                safe = [item for item in result['concepts'] if item['safe_to_generate']]
                self.assertEqual([item['rank'] for item in safe], [safe_rank])
                self.assertFalse(imagery._depicts_people(safe[0]['depictable_scene']))

    def test_handheld_breathalyser_is_not_a_depicted_hand(self):
        scene = JOKILAAKSO_OUTPUT['concepts'][1]['depictable_scene']
        self.assertFalse(imagery._depicts_people(scene))
        for actual_hand in ('Käsi pitää alkometriä.', 'Käsivarsi näkyy alkometrin vieressä.'):
            self.assertTrue(imagery._depicts_people(actual_hand))

    def test_mislabelled_people_scene_is_downgraded_not_whole_decision_rejected(self):
        output = copy.deepcopy(JOKILAAKSO_OUTPUT)
        output['concepts'][0]['safe_to_generate'] = True
        output['concepts'][0]['depictable_scene'] = 'Kaksi ihmistä seisoo poliisiauton vieressä.'
        result = imagery.validate_image_decision(output, JOKILAAKSO_DRAFT,
                                                 require_concepts=True)
        self.assertFalse(result['concepts'][0]['safe_to_generate'])
        self.assertTrue(result['concepts'][1]['safe_to_generate'])

    def test_no_safe_scene_gets_one_bounded_retry_with_rejected_scenes(self):
        unsafe = copy.deepcopy(JOKILAAKSO_OUTPUT)
        for item in unsafe['concepts']:
            item['safe_to_generate'] = item['rank'] != 2
        unsafe['concepts'][0]['depictable_scene'] = 'Kaksi ihmistä seisoo poliisiauton vieressä.'
        unsafe['concepts'][2]['depictable_scene'] = 'Kuljettaja ja lapsi istuvat moottoripyörällä.'
        model = SequenceModel(unsafe, JOKILAAKSO_OUTPUT)
        result = imagery.classify_draft(JOKILAAKSO_DRAFT, model=model, packet={'story_key': 'x'})
        self.assertTrue(result['concepts'][1]['safe_to_generate'])
        self.assertNotIn('80 km/h nopeusrajoitusmerkki',
                         result['concepts'][2]['search_queries'])
        self.assertEqual(len(model.calls), 2)
        feedback = model.calls[1][3]['image_classifier_feedback']
        self.assertEqual(feedback['attempt'], 2)
        self.assertEqual(len(feedback['rejected_scenes']), 2)

    def test_rejected_queries_get_one_different_retry(self):
        malformed = copy.deepcopy(JOKILAAKSO_OUTPUT)
        malformed['concepts'][1]['search_queries'] = ['alkometri', 'puhallus', 'laite']
        model = SequenceModel(malformed, JOKILAAKSO_OUTPUT)
        result = imagery.classify_draft(JOKILAAKSO_DRAFT, model=model)
        self.assertTrue(result['concepts'][1]['safe_to_generate'])
        self.assertEqual(len(model.calls), 2)
        self.assertIn('queries', model.calls[1][3]['image_classifier_feedback']['validation_error'])

    def test_second_unsafe_response_uses_deterministic_people_free_fallback(self):
        unsafe = copy.deepcopy(JOKILAAKSO_OUTPUT)
        for item in unsafe['concepts']:
            item['safe_to_generate'] = item['rank'] != 2
        unsafe['concepts'][0]['depictable_scene'] = 'Kaksi ihmistä seisoo poliisiauton vieressä.'
        unsafe['concepts'][2]['depictable_scene'] = 'Kuljettaja ja lapsi istuvat moottoripyörällä.'
        model = SequenceModel(unsafe, unsafe)
        result = imagery.classify_draft(JOKILAAKSO_DRAFT, model=model)
        self.assertEqual(len(model.calls), 2)
        safe = next(item for item in result['concepts'] if item['safe_to_generate'])
        self.assertIn('maantie', safe['depictable_scene'])
        self.assertFalse(imagery._depicts_people(safe['depictable_scene']))

    def test_editorial_image_rejection_changes_next_classifier_request(self):
        review = {'approved': False, 'image_retryable': True,
                  'reasons': ['Generic city image did not depict the hotel reception.']}
        model = SequenceModel(KAARINA_OUTPUT)
        imagery.classify_draft(KAARINA_DRAFT, model=model, feedback=review)
        context = model.calls[0][3]['image_classifier_feedback']
        self.assertIn('Generic city image', context['reasons'][0])
        self.assertIn('Do not repeat', context['instruction'])

    def test_generic_licensed_pixels_are_labelled_as_illustration(self):
        self.assertEqual(imagery.STOCK_ALT_PREFIX, 'Kuvituskuva: ')
        self.assertEqual(imagery.STOCK_CAPTION,
                         'Kuvituskuva. Kuva ei esitä uutisen tapahtumaa.')


if __name__ == '__main__':
    unittest.main()
