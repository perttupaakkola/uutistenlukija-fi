import copy
import hashlib
import json
import tempfile
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from news_mvp.editorial import (ROOT, FixtureModel, HermesModel, current_default_model_args,
                                parse_hermes_output)
from news_mvp.intake import ArticleHTML, collect
from news_mvp.history import preserve_article
from news_mvp.live import live_tick
from news_mvp.publish import ensure_table
from news_mvp.store import database


class RetryFairnessBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'state'
        self.config_path = self.root / 'config.json'
        self.config_path.write_text(json.dumps({
            'enabled': True,
            'backend': 'hermes',
            'state_dir': str(self.state),
            'output_dir': str(self.root / 'private'),
            'source_recipes': [],
            'discovery': {'family': 'nasa-modis'},
            'max_attempts': 3,
            'retry_seconds': 60,
        }))

    @staticmethod
    def packet(name):
        url = 'https://example.invalid/' + name
        return {
            'fixture': False,
            'story_key': 'url:' + url,
            'sources': [{'url': url}],
        }

    def admit(self, store, name, created_at):
        return store.admit(self.packet(name), created_at)[0]

    def test_live_retry_picker_yields_after_image_backoff(self):
        base = 2_000_000_000.0
        with database(self.state) as store:
            older = self.admit(store, 'older-refusal', '2026-10-07T13:00:00+00:00')
            newer = self.admit(store, 'newer-manuscript', '2026-10-07T13:01:00+00:00')
            future = self.admit(store, 'future', '2026-10-07T13:02:00+00:00')
            with store.db:
                store.db.execute('UPDATE jobs SET next_attempt=? WHERE id=?',
                                 (base + 2_000, future))

        clock = [base]
        selected = []

        def defer_selected(_config_path, _already_locked=False, target_job_id=None,
                           image_backfill_limit=None):
            with database(self.state) as store:
                job = store.claim(clock[0], 3, target_job_id)
                self.assertIsNotNone(job)
                self.assertEqual(job['id'], target_job_id)
                selected.append(job['id'])
                store.defer_image(job['id'], clock[0], 900, 'synthetic image refusal')

        with patch('news_mvp.live.time.time', side_effect=lambda: clock[0]), \
                patch('news_mvp.live.tick', side_effect=defer_selected), \
                patch('news_mvp.live.discover', side_effect=AssertionError('due retry must win')), \
                patch('news_mvp.live.collect', side_effect=AssertionError('no collection')), \
                patch('news_mvp.live.publish', side_effect=AssertionError('no publication')):
            first = live_tick(self.config_path)
            clock[0] += 1_080
            second = live_tick(self.config_path)

        self.assertEqual((first['job_id'], second['job_id']), (older, newer))
        self.assertEqual(selected, [older, newer])
        with database(self.state) as store:
            self.assertEqual(store.get(older)['next_attempt'], base + 900)
            self.assertEqual(store.get(newer)['next_attempt'], base + 1_080 + 900)
            self.assertEqual(store.get(future)['next_attempt'], base + 2_000)

    def test_store_claim_keeps_target_due_limits_and_stable_ties(self):
        now = 500.0
        with database(self.state) as store:
            earliest = self.admit(store, 'earliest', '2026-10-07T13:00:00+00:00')
            target = self.admit(store, 'explicit-target', '2026-10-07T13:01:00+00:00')
            tie_a = self.admit(store, 'tie-a', '2026-10-07T13:02:00+00:00')
            tie_b = self.admit(store, 'tie-b', '2026-10-07T13:02:00+00:00')
            future = self.admit(store, 'not-yet-due', '2026-10-07T12:00:00+00:00')
            exhausted = self.admit(store, 'attempt-limit', '2026-10-07T12:00:00+00:00')
            with store.db:
                store.db.execute('UPDATE jobs SET next_attempt=10 WHERE id=?', (earliest,))
                store.db.execute('UPDATE jobs SET next_attempt=20 WHERE id=?', (target,))
                store.db.executemany('UPDATE jobs SET next_attempt=30 WHERE id=?',
                                     [(tie_a,), (tie_b,)])
                store.db.execute('UPDATE jobs SET next_attempt=? WHERE id=?', (now + 1, future))
                store.db.execute('UPDATE jobs SET attempts=3 WHERE id=?', (exhausted,))

            self.assertEqual(store.claim(now, 3, target)['id'], target)
            self.assertIsNone(store.claim(now, 3, future))
            self.assertIsNone(store.claim(now, 3, exhausted))
            self.assertEqual(store.claim(now, 3)['id'], earliest)
            tied = sorted((tie_a, tie_b))
            self.assertEqual(store.claim(now, 3)['id'], tied[0])
            self.assertEqual(store.claim(now, 3)['id'], tied[1])
            self.assertIsNone(store.claim(now, 3))

    def test_pending_publication_still_precedes_due_retry(self):
        with database(self.state) as store:
            due = self.admit(store, 'due-retry', '2026-10-07T13:00:00+00:00')
            pending = self.admit(store, 'pending-publication',
                                 '2026-10-07T13:01:00+00:00')
            ensure_table(store)
            with store.db:
                store.db.execute(
                    "INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,"
                    "source_commit,status) VALUES(?,?,?,?,?,'prepared')",
                    (pending, 'packet', 'draft', None, 'source'))

        outcome = {'status': 'reconciled', 'job_id': pending}
        with patch('news_mvp.live.publish', return_value=outcome) as publish, \
                patch('news_mvp.live.tick', side_effect=AssertionError('retry must wait')), \
                patch('news_mvp.live.discover', side_effect=AssertionError('discovery must wait')):
            self.assertEqual(live_tick(self.config_path), outcome)
        self.assertEqual(publish.call_args.args[1]['id'], pending)
        with database(self.state) as store:
            self.assertEqual(store.get(due)['status'], 'ready')


class LiveBoundary(unittest.TestCase):
    def test_quiet_json_and_session_wrapper_without_ambiguous_substring_extraction(self):
        for response in ('{"ok":true}', '```json\n{"ok":true}\n```', '\x1b[0m{"ok":true}\n'):
            self.assertEqual(parse_hermes_output(response)[0], {"ok": True})
        self.assertEqual(parse_hermes_output('{"ok":true}\nsession_id: 20260912_abc'), ({"ok": True}, '20260912_abc'))
        for value in ('log: {"ok":true}', '{"ok":true}\n{"another":true}', '[]', '{"ok":true}\nunknown wrapper'):
            with self.assertRaises(ValueError):
                parse_hermes_output(value)

    def test_editorial_profile_resolves_the_news_profile_model_at_call_time(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / '.hermes/profiles/news').mkdir(parents=True)
            (home / '.hermes/config.yaml').write_text('model:\n  provider: personal-plugin\n  default: other\n')
            (home / '.hermes/profiles/news/config.yaml').write_text(
                'model:\n  provider: chosen-provider\n  default: chosen-model\n  reasoning_effort: chosen-effort\n'
            )
            with patch('news_mvp.editorial.Path.home', return_value=home):
                self.assertEqual(current_default_model_args(), [
                    '--model', 'chosen-model', '--provider', 'chosen-provider',
                    '--reasoning', 'chosen-effort',
                ])

    def test_fixture_and_live_adapters_refuse_crossing_the_boundary(self):
        with patch('news_mvp.editorial.subprocess.run') as run:
            with self.assertRaises(ValueError):
                HermesModel('/must-not-run').call('writer', {"fixture": True})
            run.assert_not_called()
        with self.assertRaises(ValueError):
            FixtureModel().call('writer', {"fixture": False})

    def test_live_adapter_gives_hermes_the_configured_editorial_budget(self):
        packet = {"fixture": False, "story_key": "real-packet"}
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / '.hermes/profiles/news-mvp').mkdir(parents=True)
            (home / '.hermes/profiles/news-mvp/config.yaml').write_text('{}\n')
            (home / '.hermes/profiles/news').mkdir(parents=True)
            (home / '.hermes/profiles/news/config.yaml').write_text(
                'model:\n  provider: chosen-provider\n  default: chosen-model\n'
            )
            completed = subprocess.CompletedProcess([], 0, stdout='{"ok":true}', stderr='')
            with patch('news_mvp.editorial.Path.home', return_value=home), \
                    patch('news_mvp.editorial.subprocess.run', return_value=completed) as run:
                self.assertEqual(HermesModel('/hermes', timeout=480).call('writer', packet), {"ok": True})
            command = run.call_args.args[0]
            self.assertEqual(command[command.index('--run-budget') + 1], '480')
            self.assertEqual(run.call_args.kwargs['timeout'], 480)

    def test_html_intake_uses_published_metadata_and_binds_real_image_bytes(self):
        recipe = json.loads((ROOT/'sources/nasa-artemis.json').read_text())
        page = ('<meta property="og:title" content="Source title"><meta property="article:published_time" content="2026-09-11T10:00:00Z">'
                '<meta property="og:image" content="' + recipe['image']['url'] + '"><nav>Not article content</nav>'
                '<div class="entry-content"><p>' + 'Public source evidence. '*20 + '</p></div><footer>Not article content</footer>').encode()
        image = b'\xff\xd8\xfffixture-jpeg-bytes'
        with tempfile.TemporaryDirectory(prefix='.test-intake-', dir=ROOT) as temp:
            rights = ('<div class="entry-content">' + 'Example permission statement. '*20 + '</div>').encode()
            with patch('news_mvp.intake.fetch', side_effect=[(page,'text/html',recipe['url']), (image,'image/jpeg',recipe['image']['url']), (rights,'text/html',recipe['image']['license_url'])]):
                packet, receipt = collect(recipe,temp,datetime(2026,9,12,tzinfo=timezone.utc))
            self.assertFalse(packet['fixture'])
            self.assertNotIn('Not article content',packet['sources'][0]['text'])
            self.assertEqual(packet['sources'][0]['published_at'],'2026-09-11T10:00:00Z')
            self.assertEqual(packet['image']['sha256'],hashlib.sha256(image).hexdigest())
            self.assertEqual((Path(temp)/packet['image']['local_path']).read_bytes(),image)
            self.assertEqual(receipt['image_bytes'],len(image))

    def test_selective_history_preserves_body_url_rights_and_excludes_internal_notes(self):
        raw='---\ntitle: Historic title\ndraft: false\ncontent_type: article\nimage_credit: Original credit\njournalist_note: Internal process note\n---\nPublic article body.\n'
        with tempfile.TemporaryDirectory(prefix='.test-history-',dir=ROOT) as temp:
            source=Path(temp)/'article.md';source.write_text(raw)
            with patch('news_mvp.history.fetch',return_value=(b'<h1>Historic title</h1>','text/html','https://example.invalid/article/')):
                result=preserve_article(source,'https://example.invalid/article/',Path(temp)/'state')
            record=json.loads(Path(result['record_path']).read_text())
            self.assertEqual(source.read_text(),raw)
            self.assertEqual(record['body_markdown'],'Public article body.')
            self.assertEqual(record['metadata']['image_credit'],'Original credit')
            self.assertNotIn('journalist_note',record['metadata'])
            self.assertFalse(record['republication_approved'])
            self.assertEqual(result['queue_imports'],0)
