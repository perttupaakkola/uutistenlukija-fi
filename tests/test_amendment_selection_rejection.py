"""Portable offline boundary tests with explicit synthetic public fixture bytes."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
# Only the isolated scratch candidate needs a source fallback. Installed tests
# always resolve their own repository and never depend on private fixtures.
if not (REPO / 'news_mvp/imagery.py').is_file():
    if REPO.name != 'candidate' or not (REPO / 'imagery.patch').is_file():
        raise RuntimeError('Installed tests require their local news_mvp sources')
    REPO = Path('/home/pertt/work/uutistenlukija')
BASE = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(REPO))
from news_mvp.editorial import digest, encode
from news_mvp.amendment_review import build_review_envelope

MODULE = Path(__file__).parents[1] / 'news_mvp/amendment_selection_rejection.py'

def load_helper():
    spec = importlib.util.spec_from_file_location('candidate_rejection', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class RejectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from news_mvp import imagery
        cls.preparation = b'{"fixture":"public synthetic amendment"}'
        cls.draft = {'title': 'Lantern garden', 'summary': 'Lantern garden scenes',
            'category': 'Kotimaa', 'paragraphs': [{'text': 'Lantern garden benches'}],
            'image': {'url': 'https://example.invalid/retained', 'alt': 'Retained',
                      'stock_provenance': {}}}
        cls.decision = {'version': imagery.ARTICLE_IMAGE_VERSION, 'category': 'Kotimaa',
            'concepts': [{'rank': rank, 'safe_to_generate': True,
                'subject': 'Lantern garden', 'depictable_scene': scene,
                'must_show': ['lantern'], 'must_avoid': ['logos'],
                'search_queries': ['garden lantern', 'garden bench', 'park lantern']}
                for rank, scene in enumerate(['Lantern on garden bench', 'Lantern on garden table'], 1)]}
        sha = hashlib.sha256(b'candidate').hexdigest()
        selection = {'version': imagery.ARTICLE_IMAGE_VERSION,
            'article_text_sha256': imagery._article_text_sha(cls.draft),
            'decision_sha256': imagery._digest(cls.decision),
            'minimum_real_fit': imagery.MIN_REAL_FIT,
            'searches': [{'concept_rank': rank, 'provider': 'unsplash',
                'queries': ['garden lantern'],
                'outcome': 'accepted' if rank == 2 else 'no_qualifying_candidate',
                'candidates': [{'image_sha256': sha, 'source_url': 'https://example.invalid/photo',
                    'license': 'Synthetic fixture', 'fit_score': 9, 'approved': True,
                    'reason': 'Synthetic fit'}] if rank == 2 else []} for rank in (1, 2)],
            'selected': {'kind': 'real', 'concept_rank': 2, 'fit_score': 9, 'image_sha256': sha}}
        cls.image = {'url': 'https://example.invalid/candidate', 'generated': False,
            'source_url': 'https://example.invalid/photo', 'license': 'Synthetic fixture',
            'stock_provenance': {}, 'classifier_output': cls.decision,
            'selection_evidence': selection, 'pixel_review': {'image_sha256': sha,
                'fit_score': 9, 'concept_sha256': imagery._digest(imagery.concept_decision(
                    cls.decision, cls.decision['concepts'][1])), 'must_show_visible': [True]}}
        cls.prior = encode({'status': 'selection_completed',
            'preparation_sha256': hashlib.sha256(cls.preparation).hexdigest(),
            'draft_sha256': digest(cls.draft), 'normal_approval': False, 'activation': False,
            'release_authorization': False, 'selected_image_sha256': sha, 'image': cls.image}).encode()
        cls.verdict = {'selected_sha256': sha, 'reason': 'Synthetic independent refusal'}
        binding = lambda value: {'packet_sha256': value * 64, 'receipt_sha256': value * 64}
        cls.envelope = {'final_draft': cls.draft, 'final_image': cls.draft['image'],
            'source_relationship': {'same_publisher': True}, 'preparation': {
                'evidence': {'schema': 'published-amendment-preparation-v1',
                    'job_id': 'a' * 64, 'predecessor_packet_sha256': 'b' * 64,
                    'predecessor_draft_sha256': 'c' * 64,
                    'predecessor_publication_sha256': 'd' * 64,
                    'original_capture': binding('e'), 'update_capture': binding('f'),
                    'reason': 'Synthetic update', 'updated_at': '2026-01-02T00:00:00+00:00'},
                'captures': {'original': {'packet': {}}}}}

    @classmethod
    def preparation_boundary(cls, raw):
        if raw != cls.preparation:
            raise ValueError('Synthetic preparation bytes changed')
        return copy.deepcopy(cls.envelope)

    def receipt(self):
        selected = self.image['selection_evidence']['selected']
        return {
            'schema': 'amendment-selection-rejection-v1',
            'preparation_sha256': hashlib.sha256(self.preparation).hexdigest(),
            'draft_sha256': digest(self.draft),
            'decision_sha256': digest(self.decision),
            'prior_selection_bytes_sha256': hashlib.sha256(self.prior).hexdigest(),
            'selection_evidence_sha256': digest(self.image['selection_evidence']),
            'image_sha256': selected['image_sha256'],
            'concept_rank': selected['concept_rank'],
            'reason': self.verdict['reason'],
            'independently_reviewed': True,
            'rejection': True,
            'normal_approval': False, 'activation': False, 'release': False,
        }

    def validate(self, receipt=None, **overrides):
        args = dict(rejection_bytes=encode(receipt or self.receipt()).encode(),
                    prior_selection_bytes=self.prior, preparation_bytes=self.preparation,
                    draft=self.draft, decision=self.decision)
        args.update(overrides)
        from unittest.mock import patch
        with patch('news_mvp.amendment_review.build_review_envelope', side_effect=self.preparation_boundary):
            return load_helper().validate_amendment_selection_rejection(**args)

    def test_synthetic_selected_pixels_and_concept(self):
        self.assertEqual(self.validate(), frozenset({(2, self.verdict['selected_sha256'])}))

    def test_all_digest_and_selected_scope_changes_refused(self):
        for key in ('preparation_sha256', 'draft_sha256', 'decision_sha256',
                    'prior_selection_bytes_sha256', 'selection_evidence_sha256', 'image_sha256'):
            with self.subTest(key=key):
                receipt = self.receipt(); receipt[key] = '0' * 64
                with self.assertRaises(ValueError): self.validate(receipt)
        for rank in (1, 3, True, '2'):
            receipt = self.receipt(); receipt['concept_rank'] = rank
            with self.assertRaises(ValueError): self.validate(receipt)

    def test_flags_reason_schema_and_sha_literal(self):
        for key in ('independently_reviewed', 'rejection', 'normal_approval', 'activation', 'release'):
            for bad in (None, 1, 0, 'false', not self.receipt()[key]):
                receipt = self.receipt(); receipt[key] = bad
                with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                    self.validate(receipt)
        for key, bad in (('reason', '  '), ('reason', 5), ('schema', 'signed-v1'),
                         ('image_sha256', 'A' * 64), ('image_sha256', 'a' * 63)):
            receipt = self.receipt(); receipt[key] = bad
            with self.assertRaises(ValueError): self.validate(receipt)
        receipt = self.receipt(); receipt['signature'] = 'not authentication'
        with self.assertRaises(ValueError): self.validate(receipt)

    def test_strict_bounded_canonical_receipt_and_prior_json(self):
        canonical = encode(self.receipt()).encode()
        for raw in (None, canonical.decode(), b'', b' ' + canonical,
                    canonical + b'\n', b'[' + canonical + b']',
                    canonical[:-1] + b',"rejection":true}', b'{"x":NaN}',
                    b'\xff', b' ' * (32 * 1024 + 1)):
            with self.subTest(raw_type=type(raw)), self.assertRaises(ValueError):
                self.validate(rejection_bytes=raw)
        for raw in (None, self.prior.decode(), b'{}', b' ' * (64 * 1024 + 1),
                    b'{"image":{},"image":{}}'):
            with self.assertRaises(ValueError): self.validate(prior_selection_bytes=raw)

    def test_full_draft_and_exact_bytes_bound(self):
        draft = copy.deepcopy(self.draft); draft['image']['alt'] += ' changed'
        with self.assertRaises(ValueError): self.validate(draft=draft)
        with self.assertRaises(ValueError): self.validate(preparation_bytes=self.preparation + b'\n')
        with self.assertRaises(ValueError): self.validate(prior_selection_bytes=self.prior + b'\n')
        decision = copy.deepcopy(self.decision)
        decision['concepts'][0]['subject'] += ' changed'
        with self.assertRaises(ValueError): self.validate(decision=decision)

    def test_exact_size_limits_are_inclusive(self):
        receipt = self.receipt()
        size = len(encode(receipt).encode())
        receipt['reason'] += 'x' * (32 * 1024 - size)
        self.assertEqual(len(encode(receipt).encode()), 32 * 1024)
        self.assertEqual(self.validate(receipt), frozenset({(2, self.verdict['selected_sha256'])}))
        receipt['reason'] += 'x'
        with self.assertRaises(ValueError): self.validate(receipt)
        prior = self.prior + b' ' * (64 * 1024 - len(self.prior))
        receipt = self.receipt()
        receipt['prior_selection_bytes_sha256'] = hashlib.sha256(prior).hexdigest()
        self.assertEqual(self.validate(receipt, prior_selection_bytes=prior),
                         frozenset({(2, self.verdict['selected_sha256'])}))
        with self.assertRaises(ValueError): self.validate(receipt, prior_selection_bytes=prior + b' ')

    def test_prior_nonactivation_flags_and_actual_decision_required(self):
        for key, bad in (('normal_approval', True), ('activation', 0),
                         ('release_authorization', True), ('status', 'approved')):
            prior = json.loads(self.prior); prior[key] = bad
            raw = encode(prior).encode(); receipt = self.receipt()
            receipt['prior_selection_bytes_sha256'] = hashlib.sha256(raw).hexdigest()
            with self.assertRaises(ValueError): self.validate(receipt, prior_selection_bytes=raw)
        prior = json.loads(self.prior)
        prior['image']['classifier_output']['concepts'][0]['subject'] += ' other'
        raw = encode(prior).encode(); receipt = self.receipt()
        receipt['prior_selection_bytes_sha256'] = hashlib.sha256(raw).hexdigest()
        with self.assertRaises(ValueError): self.validate(receipt, prior_selection_bytes=raw)

    def test_actual_installed_selection_validator_not_only_receipt_digest(self):
        for mutation in ('pixel_sha', 'searches', 'concept', 'malformed_review'):
            prior = json.loads(self.prior)
            image = prior['image']
            if mutation == 'pixel_sha': image['pixel_review']['image_sha256'] = '0' * 64
            elif mutation == 'searches': image['selection_evidence']['searches'] = []
            elif mutation == 'concept': image['pixel_review']['concept_sha256'] = '0' * 64
            else: image['pixel_review'] = 'malformed'
            raw = encode(prior).encode()
            receipt = self.receipt()
            receipt['prior_selection_bytes_sha256'] = hashlib.sha256(raw).hexdigest()
            receipt['selection_evidence_sha256'] = digest(image['selection_evidence'])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.validate(receipt, prior_selection_bytes=raw)


def load_engine():
    """Apply the real unified patch in memory; never write production sources."""
    import re
    import types
    helper = load_helper()
    sys.modules['news_mvp.amendment_selection_rejection'] = helper
    import inspect
    from news_mvp import imagery
    if {'amendment_selection_rejection_bytes', 'amendment_prior_selection_bytes'} <= set(
            inspect.signature(imagery._build_image_article_first).parameters):
        return imagery
    source = (REPO/'news_mvp/imagery.py').read_text()
    patch = (MODULE.parents[1]/'imagery.patch').read_text()
    for chunk in re.split(r'^@@.*@@\n', patch, flags=re.M)[1:]:
        lines = chunk.splitlines(keepends=True)
        old = ''.join(line[1:] for line in lines if line[:1] in (' ', '-'))
        new = ''.join(line[1:] for line in lines if line[:1] in (' ', '+'))
        assert source.count(old) == 1, 'Patch must match installed source exactly'
        source = source.replace(old, new, 1)
    module = types.ModuleType('news_mvp.imagery_rejection_candidate')
    module.__package__ = 'news_mvp'
    module.__file__ = str(REPO/'news_mvp/imagery.py')
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module


class EngineTests(unittest.TestCase):
    setUpClass = classmethod(RejectionTests.setUpClass.__func__)
    receipt = RejectionTests.receipt
    preparation_boundary = classmethod(RejectionTests.preparation_boundary.__func__)

    def setUp(self):
        from contextlib import ExitStack
        from unittest import mock
        from news_mvp.amendments import AmendmentEvidence, CaptureBinding
        self.mock = mock
        self.engine = load_engine()
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.providers = []
        for name in ('fetch_pexels', 'fetch_unsplash', 'fetch_wikimedia', 'fetch_google'):
            self.providers.append(self.stack.enter_context(mock.patch.object(self.engine, name, return_value=None)))
        self.generation = self.stack.enter_context(mock.patch.object(self.engine, '_build_image', return_value=None))
        self.stack.enter_context(mock.patch.object(self.engine, '_other_article_images', return_value=set()))
        self.stack.enter_context(mock.patch.object(self.engine, '_rejected_image_hashes', return_value=set()))
        self.stack.enter_context(mock.patch('sqlite3.connect'))
        self.stack.enter_context(mock.patch('news_mvp.amendment_image_identity.retained_image_identity',
            return_value={'excluded_image_sha256': [], 'image_sha256': hashlib.sha256(b'retained').hexdigest()}))
        self.stack.enter_context(mock.patch('news_mvp.amendment_review.build_review_envelope',
            side_effect=self.preparation_boundary))
        self.envelope = self.preparation_boundary(self.preparation)
        fields = copy.deepcopy(self.envelope['preparation']['evidence'])
        for name in ('original_capture', 'update_capture'): fields[name] = CaptureBinding(**fields[name])
        self.evidence = AmendmentEvidence(**fields)

    def call(self, *, amendment=True, rejection=True, **overrides):
        args = dict(amendment_evidence=self.evidence if amendment else None,
                    amendment_preparation_bytes=self.preparation if amendment else None)
        if rejection:
            args.update(amendment_selection_rejection_bytes=encode(self.receipt()).encode(),
                        amendment_prior_selection_bytes=self.prior)
        args.update(overrides)
        return self.engine._build_image_article_first(self.draft, BASE/'cycle53/no-state',
            self.draft['category'], None, 1, self.decision, False, True,
            self.envelope if amendment else None, **args)

    def test_ordinary_caller_unchanged_and_supplied_input_requires_amendment(self):
        self.assertIsNone(self.call(amendment=False, rejection=False))
        self.assertTrue(any(provider.called for provider in self.providers))
        self.assertTrue(self.generation.called)
        for provider in self.providers: provider.reset_mock()
        self.generation.reset_mock()
        self.assertIsNone(self.call(amendment=False))
        self.assertFalse(any(provider.called for provider in self.providers))
        self.generation.assert_not_called()

    def test_invalid_supplied_receipt_and_partial_pair_fail_closed_before_providers(self):
        for args in ({'amendment_selection_rejection_bytes': b'{}'},
                     {'amendment_prior_selection_bytes': None},
                     {'amendment_selection_rejection_bytes': None},
                     {'amendment_evidence': object()}):
            self.assertIsNone(self.call(**args))
        self.assertFalse(any(provider.called for provider in self.providers))
        self.generation.assert_not_called()

    def test_exact_rejection_precedes_review_and_is_concept_scoped(self):
        from types import SimpleNamespace
        real_sha256 = hashlib.sha256
        rejected_sha = self.verdict['selected_sha256']
        stock = copy.deepcopy(self.image)
        def raw(url):
            return b'candidate' if url == stock['url'] else b'retained'
        self.stack.enter_context(self.mock.patch.object(self.engine, '_get_external_bytes', side_effect=raw))
        self.stack.enter_context(self.mock.patch.object(self.engine, 'hashlib',
            SimpleNamespace(sha256=real_sha256)))
        reviews = []
        def review(value, draft, **kwargs):
            reviews.append((value, kwargs['concept']['subject']))
            raise ValueError('Offline review refusal')
        self.stack.enter_context(self.mock.patch.object(self.engine, 'review_pixels', side_effect=review))
        event = self.stack.enter_context(self.mock.patch('news_mvp.image_providers.candidate_event'))
        self.providers[1].side_effect = lambda draft, **kwargs: kwargs['accept'](stock)
        self.assertIsNone(self.call())
        candidate_reviews = [subject for value, subject in reviews if value == b'candidate']
        self.assertEqual(candidate_reviews, [self.decision['concepts'][0]['subject']])
        self.assertTrue(any(call.args[-1] == 'amendment_selection_rejected' for call in event.call_args_list))
        self.generation.assert_not_called()

    def test_existing_global_exclusions_still_win(self):
        self.stack.enter_context(self.mock.patch('news_mvp.amendment_image_identity.retained_image_identity',
            return_value={'excluded_image_sha256': [hashlib.sha256(b'retained').hexdigest()],
                          'image_sha256': hashlib.sha256(b'retained').hexdigest()}))
        self.stack.enter_context(self.mock.patch.object(self.engine, '_get_external_bytes', return_value=b'retained'))
        review = self.stack.enter_context(self.mock.patch.object(self.engine, 'review_pixels'))
        self.assertIsNone(self.call())
        review.assert_not_called()
        self.generation.assert_not_called()

if __name__ == '__main__':
    unittest.main()
