"""Bounded, audited correction of source-grounding review failures."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from news_mvp.controller import ingest, load_config, tick
from news_mvp.editorial import ROOT, FixtureModel, digest, validate_review
from news_mvp.store import database


class RevisionModel:
    name = 'revision-fixture'

    def __init__(self, revisions, reviews):
        self.initial = FixtureModel().call(
            'writer', json.loads((ROOT / 'fixtures/source-packet.json').read_text()))
        self.revisions = [copy.deepcopy(value) for value in revisions]
        self.reviews = [copy.deepcopy(value) for value in reviews]
        self.calls = []
        self.reviewed_drafts = []
        self.revision_contexts = []

    def call(self, role, packet, draft=None, *, context=None):
        self.calls.append(role)
        if role == 'writer':
            return copy.deepcopy(self.initial)
        if role == 'reviser':
            self.revision_contexts.append(copy.deepcopy(context))
            return self.revisions.pop(0)
        if role == 'reviewer':
            self.reviewed_drafts.append(copy.deepcopy(draft))
            return {**self.reviews.pop(0), 'draft_sha256': digest(draft)}
        raise AssertionError('Unexpected model role: ' + role)


class RevisionLoop(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.revision-test-', dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config_path = self.root / 'config.json'
        self.config_path.write_text(json.dumps({
            'enabled': True, 'backend': 'fixture',
            'state_dir': 'state', 'output_dir': 'site'}))
        self.config = load_config(self.config_path)
        self.now = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
        self.packet = json.loads((ROOT / 'fixtures/source-packet.json').read_text())

    def admit(self):
        return ingest(self.config, self.packet, self.now)['id']

    @staticmethod
    def corrected(draft, marker='Korjattu lähteiden mukainen rajaus.'):
        value = copy.deepcopy(draft)
        value['paragraphs'][0]['text'] = marker
        return value

    def history(self, job_id):
        return sorted((self.config['state_dir'] / 'revisions' / job_id).glob('*.json'))

    def test_fixable_rejection_is_corrected_approved_and_rendered(self):
        job_id = self.admit()
        corrected = self.corrected(FixtureModel().call('writer', self.packet))
        model = RevisionModel([corrected], [
            {'approved': False, 'fixable': True, 'reasons': ['Rajaa ensimmäinen väite.']},
            {'approved': True, 'fixable': False, 'reasons': ['Korjattu teksti vastaa lähteitä.']},
        ])

        result = tick(self.config_path, model=model, now=self.now)

        self.assertEqual(result['status'], 'rendered')
        self.assertEqual(model.calls, ['writer', 'reviewer', 'reviser', 'reviewer'])
        self.assertEqual(model.revision_contexts[0]['review']['reasons'],
                         ['Rajaa ensimmäinen väite.'])
        self.assertEqual(len(self.history(job_id)), 1)
        with database(self.config['state_dir']) as store:
            job = store.get(job_id)
            final_draft = json.loads(job['draft'])
            final_review = json.loads(job['review'])
        self.assertEqual(final_draft, corrected)
        self.assertEqual(final_review['draft_sha256'], digest(final_draft))
        self.assertTrue((self.config['output_dir'] / 'index.html').is_file())

    def test_non_fixable_rejection_is_terminal_without_revision(self):
        job_id = self.admit()
        model = RevisionModel([], [{
            'approved': False, 'fixable': False,
            'reasons': ['Jutun keskeinen väite ei saa tukea lähteistä.']}])

        self.assertEqual(tick(self.config_path, model=model, now=self.now)['status'], 'rejected')

        self.assertEqual(model.calls, ['writer', 'reviewer'])
        self.assertEqual(len(self.history(job_id)), 1)

    def test_two_failed_correction_rounds_reject_and_preserve_every_reason(self):
        job_id = self.admit()
        original = FixtureModel().call('writer', self.packet)
        first = self.corrected(original, 'Ensimmäinen korjausyritys lähteen mukaan.')
        second = self.corrected(original, 'Toinen korjausyritys lähteen mukaan.')
        reasons = ['Ensimmäinen ongelma.', 'Toinen ongelma.', 'Lopullinen ongelma.']
        model = RevisionModel([first, second], [
            {'approved': False, 'fixable': True, 'reasons': [reasons[0]]},
            {'approved': False, 'fixable': True, 'reasons': [reasons[1]]},
            {'approved': False, 'fixable': True, 'reasons': [reasons[2]]},
        ])

        self.assertEqual(tick(self.config_path, model=model, now=self.now)['status'], 'rejected')

        self.assertEqual(model.calls,
                         ['writer', 'reviewer', 'reviser', 'reviewer', 'reviser', 'reviewer'])
        records = [json.loads(path.read_text()) for path in self.history(job_id)]
        self.assertEqual(len(records), 3)
        self.assertEqual({record['review']['reasons'][0] for record in records}, set(reasons))
        with database(self.config['state_dir']) as store:
            job = store.get(job_id)
            final_draft = json.loads(job['draft'])
            final_review = json.loads(job['review'])
        self.assertEqual(final_review['reasons'], [reasons[-1]])
        self.assertEqual(final_review['draft_sha256'], digest(final_draft))

    def test_new_sentence_in_corrected_draft_receives_a_fresh_full_review(self):
        self.admit()
        corrected = FixtureModel().call('writer', self.packet)
        corrected = copy.deepcopy(corrected)
        corrected['paragraphs'].append({
            'text': 'Lähteen tukema uusi lause tarkentaa kokeilun rajausta.',
            'source_ids': ['A']})
        model = RevisionModel([corrected], [
            {'approved': False, 'fixable': True, 'reasons': ['Lisää täsmällinen rajaus.']},
            {'approved': True, 'fixable': False, 'reasons': ['Koko uusi versio tarkistettu.']},
        ])

        self.assertEqual(tick(self.config_path, model=model, now=self.now)['status'], 'rendered')

        self.assertEqual(len(model.reviewed_drafts), 2)
        self.assertEqual(model.reviewed_drafts[1], corrected)
        self.assertEqual(len(model.reviewed_drafts[1]['paragraphs']), 3)

    def test_missing_fixable_is_backwards_compatible_terminal_rejection(self):
        job_id = self.admit()
        model = RevisionModel([], [{
            'approved': False, 'reasons': ['Vanhan arvioijan hylkäys.']}])

        self.assertEqual(tick(self.config_path, model=model, now=self.now)['status'], 'rejected')

        self.assertEqual(model.calls, ['writer', 'reviewer'])
        self.assertEqual(len(self.history(job_id)), 1)

    def test_fixable_field_is_boolean_and_only_for_text_rejections(self):
        draft = FixtureModel().call('writer', self.packet)
        base = {'approved': False, 'draft_sha256': digest(draft), 'reasons': ['Fixture.']}
        self.assertIs(validate_review(base, draft)['fixable'], False)
        for update in ({'fixable': 'true'}, {'approved': True, 'fixable': True},
                       {'fixable': True, 'image_retryable': True}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_review({**base, **update}, draft)


if __name__ == '__main__':
    unittest.main()


class CorrectedArticleImageIsReboundTest(unittest.TestCase):
    def test_correction_reruns_article_first_image(self):
        import inspect
        from news_mvp import controller
        body = inspect.getsource(controller.tick)
        loop = body[body.index("model.call('reviser'"):]
        self.assertIn("article_first_image(revised", loop[:1500])


class ImageOnlyRejectionAfterCorrectionTest(unittest.TestCase):
    def test_corrected_draft_image_only_rejection_defers_not_rejects(self):
        import inspect
        from news_mvp import controller
        body = inspect.getsource(controller.tick)
        after_reviser = body[body.index("model.call('reviser'"):]
        self.assertIn("_defer_image_only_rejection(", after_reviser)
