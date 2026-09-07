"""C1–C4 actual-caller regressions; providers/build are fixture boundaries."""
from contextlib import ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import dedup
import firehose
import freshness
import publisher
import staged_publish as staged
from test_rebuild_invariants import record


class PipelineRepairTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.queue = self.root / 'queue'
        self.posts = self.root / 'posts'
        self.posts.mkdir()
        for module, name, value in (
            (staged, 'STAGED_ROOT', self.queue),
            (staged, 'PIPELINE_CACHE_DIR', self.root/'cache'),
            (publisher, 'CONTENT_DIR', str(self.posts)),
            (dedup, '_CONTENT_POSTS_DIR', str(self.posts)),
            (dedup, 'DEDUP_FILE', str(self.root/'fingerprints.json')),
            (dedup, 'URL_HASH_FILE', str(self.root/'urls.json')),
        ):
            self.stack.enter_context(patch.object(module, name, value))
        self.args = SimpleNamespace(max_articles=1, dedup_window=48, dry_run=False,
                                    git_push=False, outcome_json=str(self.root/'outcome.json'))

    def write_record(self, box='outbox'):
        value = record()
        path = self.queue/box/'story.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(value))
        return path, value

    def isolate_assets(self):
        self.stack.enter_context(patch.object(staged, 'run_quality_gate',
            side_effect=lambda rows, **kw: SimpleNamespace(passed=rows, rejected=[])))
        self.stack.enter_context(patch.object(staged, 'enrich_images_for_articles',
            return_value={'images': 0, 'total': 1, 'missing': 1}))

    def prior_post(self):
        day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        path = self.posts/f'{day}-000-existing.md'
        # CRLF and non-ASCII bytes must survive rollback exactly.
        path.write_bytes((f'---\r\ntitle: "Aiempi uutinen"\r\ndate: {day}T00:00:00Z\r\n'
                          'categories:\r\n  - Kotimaa\r\n---\r\n\r\nSäilytä tämä.\r\n').encode())
        return path

    def test_build_failure_actual_cmd_retry_restores_briefing_and_reaches_build(self):
        path, _ = self.write_record()
        original_queue = path.read_bytes()
        prior = self.prior_post()
        original_post = prior.read_bytes()
        self.isolate_assets()
        build_paths = []
        def build():
            build_paths.append(sorted(p.name for p in self.posts.glob('*.md')))
            return (len(build_paths) == 2, 'fixture failure')
        with patch.object(staged, 'build_site', side_effect=build) as mock:
            self.assertEqual(staged.cmd_publish(self.args), 2)
            self.assertEqual(path.read_bytes(), original_queue)
            self.assertEqual(prior.read_bytes(), original_post)
            self.assertEqual(list(self.posts.glob('*.md')), [prior])
            self.assertFalse((self.root/'fingerprints.json').exists())
            self.assertFalse((self.queue/'published').exists())
            self.assertEqual(staged.cmd_publish(self.args), 0)
            self.assertEqual(mock.call_count, 2)
        self.assertEqual(build_paths[0], build_paths[1])
        self.assertFalse(path.exists())
        self.assertTrue((self.queue/'published/story.json').exists())
        self.assertFalse((self.queue/'failed').exists())
        self.assertEqual(len(list(self.posts.glob('*.md'))), 2)

    def test_raised_build_also_rolls_back(self):
        path, _ = self.write_record()
        self.isolate_assets()
        with patch.object(staged, 'build_site', side_effect=OSError('build raised')):
            with self.assertRaisesRegex(OSError, 'build raised'):
                staged.cmd_publish(self.args)
        self.assertTrue(path.exists())
        self.assertEqual(list(self.posts.glob('*.md')), [])

    def test_briefing_failure_actual_cmd_retry(self):
        path, _ = self.write_record()
        before = path.read_bytes()
        self.isolate_assets()
        with patch.object(staged, 'build_site', return_value=(True, '')) as build:
            with patch.object(publisher, '_atomic_replace_bytes', side_effect=OSError('briefing failed')):
                with self.assertRaisesRegex(OSError, 'briefing failed'):
                    staged.cmd_publish(self.args)
            build.assert_not_called()
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(self.posts.iterdir()), [])
            self.assertEqual(staged.cmd_publish(self.args), 0)
            build.assert_called_once()
        self.assertTrue((self.queue/'published/story.json').exists())

    def test_existing_publication_still_rejected_by_real_file_dedup(self):
        path, value = self.write_record()
        publisher.publish_articles([value['article']])
        before = {p.name:p.read_bytes() for p in self.posts.iterdir()}
        self.isolate_assets()
        with patch.object(staged, 'build_site') as build:
            self.assertEqual(staged.cmd_publish(self.args), 0)
            build.assert_not_called()
        self.assertFalse(path.exists())
        self.assertTrue((self.queue/'failed/story.json').exists())
        self.assertEqual({p.name:p.read_bytes() for p in self.posts.iterdir()}, before)

    def test_rejected_publish_creates_absent_failed_directory(self):
        path, value = self.write_record()
        for obj in (value['article'], value['original_article']):
            obj['published'] = '2000-01-01T00:00:00Z'
        path.write_text(json.dumps(value))
        self.assertEqual(staged.cmd_publish(self.args), 0)
        self.assertTrue((self.queue/'failed/story.json').exists())
        self.assertFalse(path.exists())

    def test_briefing_failure_after_existing_update_rolls_back_entire_batch(self):
        prior = self.prior_post()
        before = prior.read_bytes()
        replace = publisher._atomic_replace_bytes
        calls = []
        def fail_second(path, data):
            calls.append(path)
            if len(calls) == 2:
                raise OSError('briefing fixture failure')
            return replace(path, data)
        with patch.object(publisher, '_atomic_replace_bytes', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'briefing fixture failure'):
                publisher.publish_articles([{'title':'New story', 'content':'NEW'}])
        self.assertEqual(calls[0], prior)
        self.assertEqual(prior.read_bytes(), before)
        self.assertEqual(list(self.posts.iterdir()), [prior])

    def test_atomic_briefing_replace_failure_never_truncates_existing(self):
        prior = self.prior_post()
        before = prior.read_bytes()
        replace = Path.replace
        def fail_replace(path, target):
            if Path(target) == prior:
                raise OSError('replacement fixture failure')
            return replace(path, target)
        with patch.object(Path, 'replace', fail_replace):
            with self.assertRaisesRegex(OSError, 'replacement fixture failure'):
                publisher.publish_articles([{'title':'New story', 'content':'NEW'}])
        self.assertEqual(prior.read_bytes(), before)
        self.assertEqual(list(self.posts.iterdir()), [prior])

    def test_worker_success_creates_absent_writing_and_outbox(self):
        path, value = self.write_record('ready')
        with patch.object(staged, '_run_monica', return_value=json.dumps(value['payload'])):
            status, reason = staged.process_one_packet(path, SimpleNamespace())
        self.assertEqual(status, 'ok', reason)
        self.assertFalse(path.exists())
        self.assertEqual(list((self.queue/'writing').iterdir()), [])
        self.assertTrue((self.queue/'outbox/story.json').exists())
        self.assertFalse((self.queue/'failed').exists())

    def test_worker_failure_creates_absent_failed(self):
        path, _ = self.write_record('ready')
        with patch.object(staged, '_run_monica', side_effect=RuntimeError('fixture writer failure')):
            status, _ = staged.process_one_packet(path, SimpleNamespace())
        self.assertEqual(status, 'failed')
        self.assertFalse(path.exists())
        self.assertEqual(list((self.queue/'writing').iterdir()), [])
        self.assertTrue((self.queue/'failed/story.json').exists())

    def test_scan_admission_creates_absent_ready(self):
        value = record()
        article = value['original_article']
        args = SimpleNamespace(dry_run=False, max_ready_age_hours=0, max_ready_backlog=0,
            dedup_window=48, cooldown_hours=48, max_research_candidates=1,
            min_source_words=80, max_packets=1)
        with ExitStack() as stack:
            for name, result in (('scan_all_feeds', [article]), ('poll_firehose', []),
                                 ('build_story_packet', value['packet'])):
                stack.enter_context(patch.object(staged, name, return_value=result))
            for name in ('enrich_with_research', 'annotate_selected_source_evidence'):
                stack.enter_context(patch.object(staged, name, side_effect=lambda rows: rows))
            stack.enter_context(patch.object(staged, 'talous_interim_priority_state',
                return_value={'active':False, 'share':None, 'talous_count':0, 'total':0, 'reason':'fixture'}))
            self.assertEqual(staged.cmd_scan(args), 0)
        ready = list((self.queue/'ready').glob('*.json'))
        self.assertEqual(len(ready), 1)
        self.assertEqual(json.loads(ready[0].read_text())['packet'], value['packet'])

    def test_raw_firehose_missing_invalid_and_discovery_dates_rejected_at_scan(self):
        now = datetime.now(timezone.utc).isoformat()
        fixture = json.loads((Path(__file__).parent/'fixtures/pipeline_repair/firehose-undated.json').read_text())
        normalized = firehose._parse_firehose_doc(fixture, {'created_at':now})
        self.assertEqual(normalized['published'], '')
        self.assertTrue(freshness.freshness_reasons(normalized))
        for dates in ({}, {'created_at':now}, {'fetched_at':now}, {'published':'broken'},
                      {'published_at':'2000-01-01T00:00:00Z', 'created_at':now}):
            with self.subTest(dates=dates):
                row = firehose._parse_firehose_doc(
                    {'title':'Raw document', 'url':'https://example.test/raw', **dates},
                    {'created_at':now})
                if not dates.get('published') and not dates.get('published_at'):
                    self.assertEqual(row['published'], '')
                self.assertTrue(freshness.freshness_reasons(row))
                with patch.object(staged, 'scan_all_feeds', return_value=[]), \
                     patch.object(staged, 'poll_firehose', return_value=[row]), \
                     patch.object(staged, 'enrich_with_research') as research:
                    self.assertEqual(staged.cmd_scan(SimpleNamespace(dry_run=True, max_ready_backlog=0)), 0)
                research.assert_not_called()
        row = firehose._parse_firehose_doc(
            {'title':'Dated', 'url':'https://example.test/current', 'published_at':now}, {})
        self.assertEqual(freshness.freshness_reasons(row), ())
