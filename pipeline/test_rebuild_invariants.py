"""Offline regressions for the nine September audit probes and their boundaries."""
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from io import BytesIO, StringIO
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error

import scanner
import feed_health
import research
import staged_publish as staged
import publisher
from publish_preflight import evaluate_publish_preflight


def record():
    value = json.loads((Path(__file__).parent / 'fixtures/publish_preflight/bayeux-publish-eligible.json').read_text())
    # Only advance fixture source timestamps; generated timestamps are not evidence.
    for obj in (value['original_article'], value['article']):
        obj['published'] = datetime.now(timezone.utc).isoformat()
    return value


class RebuildInvariants(unittest.TestCase):
    def test_failed_feed_health_and_successful_empty(self):
        health = feed_health.FeedHealth.__new__(feed_health.FeedHealth)
        health._data = {}
        feed = {'name': 'Fixture 404', 'url': 'https://example.test/feed'}
        with patch.object(scanner, 'RSS_FEEDS', [feed]), patch.object(scanner, 'get_global_health', return_value=health), patch.object(scanner, 'save_global_health'), patch.object(scanner, '_load_rss_feed_policy', return_value={}), patch.object(scanner, 'DOMAIN_DELAY', 0), patch.object(feed_health, '_discord_post'), patch.object(scanner.urllib.request, 'urlopen', side_effect=urllib.error.HTTPError(feed['url'], 404, 'Not found', {}, None)):
            for _ in range(3):
                scanner.scan_all_feeds()
        entry = health._data[feed['name']]
        self.assertEqual(entry['consecutive_errors'], 3)
        self.assertFalse(entry['last_success'])
        health._data = {}
        with patch.object(scanner, 'RSS_FEEDS', [feed]), patch.object(scanner, 'get_global_health', return_value=health), patch.object(scanner, 'save_global_health'), patch.object(scanner, '_load_rss_feed_policy', return_value={}), patch.object(scanner, 'DOMAIN_DELAY', 0), patch.object(scanner.urllib.request, 'urlopen', return_value=BytesIO(b'<rss><channel/></rss>')):
            scanner.scan_all_feeds()
        self.assertEqual(health._data[feed['name']]['consecutive_errors'], 0)
        self.assertTrue(health._data[feed['name']]['last_success'])

    def test_namespaced_atom_matches_rss(self):
        atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Headline</title><link rel="self" href="https://example.test/feed"/><link rel="alternate" href="https://example.test/story"/><published>2026-09-07T08:00:00Z</published><summary>Description</summary></entry></feed>'
        rss = b'<rss><channel><item><title>Headline</title><link>https://example.test/story</link><pubDate>Mon, 07 Sep 2026 08:00:00 GMT</pubDate><description>Description</description></item></channel></rss>'
        rows = []
        for payload in (atom, rss):
            with patch.object(scanner, 'DOMAIN_DELAY', 0), patch.object(scanner.urllib.request, 'urlopen', return_value=BytesIO(payload)):
                rows.append(scanner.fetch_feed({'name':'Fixture', 'url':'https://example.test/rss'}))
        self.assertEqual([len(row) for row in rows], [1, 1])
        for field in ('title', 'link', 'published', 'description'):
            self.assertEqual(rows[0][0][field], rows[1][0][field])

    def test_research_alarm_stops_followon_search(self):
        article = {'title':'Fixture', 'link':'https://example.test/story'}
        def slow(*args, **kwargs):
            time.sleep(1.1)
            raise AssertionError('alarm failed')
        with patch.object(research, 'ARTICLE_RESEARCH_TIMEOUT', 1), patch.object(research.urllib.request, 'urlopen', side_effect=slow), patch.object(research, '_search_news', return_value=[]) as search:
            research.enrich_with_research([article])
        self.assertEqual(article['research_source'], 'timeout')
        search.assert_not_called()

    def test_stale_outbox_rejected_despite_new_generated_dates(self):
        value = record()
        for obj in (value['original_article'], value['article']):
            obj['published'] = '2000-01-01T00:00:00Z'
        self.assertEqual(evaluate_publish_preflight(value).action, 'reject')
        self.assertIn('source_stale', evaluate_publish_preflight(value).reasons)

    def test_stale_feed_cannot_fill_candidate_quota(self):
        candidate = {'title':'Hallitus hyväksyi uuden lakiesityksen', 'description':'Lakiesitys muuttaa kuntien tehtäviä.', 'published':'2000-01-01T00:00:00Z', 'source':'Yle Uutiset', 'source_domain':'yle.fi', 'link':'https://yle.fi/a/fixture', 'fingerprint':'fixture', '_url_hash':'fixture', 'language':'fi', 'category_hint':'Kotimaa'}
        with patch.object(scanner, 'RSS_FEEDS', [{'name':'Yle Uutiset','url':'https://example.test/rss'}]), patch.object(scanner, 'get_global_health', return_value=None), patch.object(scanner, 'save_global_health'), patch.object(scanner, '_load_rss_feed_policy', return_value={'Yle Uutiset':{'policy':'stale_source', 'fresh_quota_eligible':False}}), patch.object(scanner, 'fetch_feed', return_value=[candidate]):
            self.assertEqual(scanner.scan_all_feeds(), [])

    def _dry_run(self, value):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            stack.enter_context(patch.object(staged, 'STAGED_ROOT', root))
            stack.enter_context(patch.object(staged, 'load_outbox', return_value=[(root/'fixture.json', value)]))
            forbidden = [stack.enter_context(patch.object(staged, name, side_effect=AssertionError(name))) for name in ('enrich_images_for_articles', 'publish_articles', 'build_site', 'mark_published', 'run_git_deploy', 'persist_queue_transitions')]
            import quality_gate
            for name in ('_save_rejected', '_log_reject', '_log_filler_hits'):
                stack.enter_context(patch.object(quality_gate, name, side_effect=AssertionError(name)))
            args = SimpleNamespace(max_articles=1, dedup_window=48, dry_run=True, git_push=True, outcome_json=str(root/'cycle.json'))
            self.assertEqual(staged.cmd_publish(args), 0)
            self.assertEqual(list(root.rglob('*')), [])
            for mock in forbidden:
                mock.assert_not_called()

    def test_dry_run_no_image_or_state(self):
        self._dry_run(record())

    def test_dry_run_no_rejection_persistence(self):
        value = record()
        value['article']['content'] = 'Liian lyhyt teksti.'
        self._dry_run(value)

    def test_deploy_stops_on_sync_failure(self):
        commands = []
        def run(cmd, **kwargs):
            commands.append(cmd)
            return SimpleNamespace(returncode=1 if cmd[1]=='pull' else 0, stdout='', stderr='fixture sync failure')
        with patch.object(staged, 'refresh_static_status'), patch.object(staged.subprocess, 'run', side_effect=run):
            self.assertNotEqual(staged.run_git_deploy(1), 0)
        self.assertNotIn('push', [cmd[1] for cmd in commands])
        self.assertNotIn('add', [cmd[1] for cmd in commands])

    def test_slug_collision_preserves_both_and_retry_urls(self):
        prefix = 'uutinen-' + 'a'*52
        articles = [{'title':prefix+' ensimmäinen', 'content':'FIRST', 'category':'Kotimaa'}, {'title':prefix+' toinen', 'content':'SECOND', 'category':'Kotimaa'}]
        with tempfile.TemporaryDirectory() as tmp, patch.object(publisher, 'CONTENT_DIR', tmp), patch.object(publisher, '_refresh_daily_briefing_flags', return_value=[]):
            paths = publisher.publish_articles(articles)
            self.assertEqual(len(set(paths)), 2)
            before = {p:Path(p).read_bytes() for p in paths}
            self.assertIn('FIRST', Path(paths[0]).read_text())
            self.assertIn('SECOND', Path(paths[1]).read_text())
            self.assertEqual(publisher.publish_articles(articles), paths)
            self.assertEqual({p:Path(p).read_bytes() for p in paths}, before)


class FreshnessBoundaries(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
        self.fresh = {'published': self.now.isoformat()}

    def reasons(self, value):
        from freshness import freshness_reasons
        return freshness_reasons(value, now=self.now)

    def allowance(self, kind='evergreen'):
        return {'kind':kind, 'reviewed_by':'editor-fixture', 'reason':'Reviewed reference material remains current', 'reviewed_at':(self.now-timedelta(hours=1)).isoformat(), 'valid_until':(self.now+timedelta(days=7)).isoformat()}

    def test_invalid_missing_and_future_dates_fail_closed(self):
        for value in ({}, {'created_at':self.now.isoformat()}, {'published':''}, {'published':'not a date'}, {'published':'2026-09-07T12:00:00'}, {'published':(self.now+timedelta(hours=1)).isoformat()}):
            with self.subTest(value=value):
                self.assertTrue(self.reasons(value))
        self.assertEqual(self.reasons(self.fresh), ())
        self.assertEqual(self.reasons({'published':'Mon, 07 Sep 2026 12:00:00 GMT'}), ())

    def test_explicit_evergreen_needs_valid_dated_review_and_source(self):
        old = {'published':'2000-01-01T00:00:00Z', 'freshness':self.allowance()}
        self.assertEqual(self.reasons(old), ())
        for invalid in ({'kind':'evergreen'}, {**self.allowance(), 'valid_until':self.now.isoformat()}, {**self.allowance(), 'reviewed_by':''}):
            self.assertTrue(self.reasons({**old, 'freshness':invalid}))
        self.assertTrue(self.reasons({'freshness':self.allowance()}))
        self.assertTrue(self.reasons({**old, 'published':'bad'}))

    def test_old_event_requires_documented_substantive_update(self):
        value = {**self.fresh, 'event_at':'2000-01-01T00:00:00Z'}
        self.assertEqual(self.reasons(value), ('event_stale',))
        update = {**self.allowance('update'), 'update_at':self.now.isoformat(), 'update_source_url':'https://example.test/update'}
        self.assertEqual(self.reasons({**value, 'freshness':update}), ())
        self.assertTrue(self.reasons({**value, 'published':'2000-01-01T00:00:00Z', 'freshness':update}))
        # A future event is legitimate with a dated current announcement.
        self.assertEqual(self.reasons({**self.fresh,'event_at':(self.now+timedelta(days=30)).isoformat()}), ())

    def test_dated_selected_primary_block_is_valid_evidence(self):
        block = {'source_url':'https://example.test/story', 'published':self.now.isoformat()}
        value = {'packet':{'clean_source_blocks':[block]}, 'article':{'source_url':block['source_url']}}
        self.assertEqual(self.reasons(value), ())
        value['article']['source_url'] = 'https://example.test/unrelated'
        self.assertEqual(self.reasons(value), ('source_date_missing',))

    def test_rss_invalid_date_is_not_replaced_by_fetch_time(self):
        for date in ('', '<pubDate>broken</pubDate>'):
            payload = f'<rss><channel><item><title>Title</title>{date}</item></channel></rss>'.encode()
            with patch.object(scanner, 'DOMAIN_DELAY', 0), patch.object(scanner.urllib.request, 'urlopen', return_value=BytesIO(payload)):
                rows = scanner.fetch_feed({'name':'Fixture','url':'https://example.test/rss'})
            self.assertTrue(self.reasons(rows[0]))

    def test_rss_one_namespaces(self):
        payload = b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"><item><title>Title</title><link>https://example.test/story</link><dc:date>2026-09-07T12:00:00Z</dc:date><description>Description</description></item></rdf:RDF>'
        with patch.object(scanner, 'DOMAIN_DELAY', 0), patch.object(scanner.urllib.request, 'urlopen', return_value=BytesIO(payload)):
            rows = scanner.fetch_feed({'name':'Fixture','url':'https://example.test/rss'})
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.reasons(rows[0]), ())


class PublicationBoundaries(unittest.TestCase):
    def test_existing_legacy_url_is_reused_on_retry(self):
        article = {'title':'Legacy title', 'source_url':'https://example.test/story', 'content':'ORIGINAL'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(publisher, 'CONTENT_DIR', tmp), patch.object(publisher, '_refresh_daily_briefing_flags') as flags:
            path = Path(tmp)/'2000-01-01-legacy-url.md'
            path.write_text(publisher._article_to_markdown(article, '2000-01-01T00:00:00Z'))
            before = path.read_bytes()
            self.assertEqual(publisher.publish_articles([article]), [str(path)])
            self.assertEqual(path.read_bytes(), before)
            flags.assert_not_called()

    def test_batch_conflict_never_leaves_partial_article(self):
        old = {'title':'Story', 'source_url':'https://example.test/story', 'content':'ORIGINAL'}
        new = {'title':'Other', 'content':'NEW'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(publisher, 'CONTENT_DIR', tmp), patch.object(publisher, '_refresh_daily_briefing_flags', return_value=[]):
            paths = publisher.publish_articles([old])
            before = {p.name:p.read_bytes() for p in Path(tmp).glob('*.md')}
            with self.assertRaises(FileExistsError):
                publisher.publish_articles([new, {**old,'content':'CHANGED'}])
            self.assertEqual({p.name:p.read_bytes() for p in Path(tmp).glob('*.md')}, before)

    def test_write_failure_rolls_back_only_this_batch(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(publisher, 'CONTENT_DIR', tmp), patch.object(publisher, '_refresh_daily_briefing_flags', return_value=[]):
            original_open = Path.open
            calls = []
            def fail_second(path, *args, **kwargs):
                if args and args[0] == 'x':
                    calls.append(path)
                    if len(calls) == 2:
                        raise OSError('fixture disk failure')
                return original_open(path, *args, **kwargs)
            with patch.object(Path, 'open', fail_second), self.assertRaises(OSError):
                publisher.publish_articles([{'title':'One','content':'ONE'}, {'title':'Two','content':'TWO'}])
            self.assertEqual(list(Path(tmp).glob('*.md')), [])


class DeadlineAndEditorialContract(unittest.TestCase):
    def test_all_http_calls_receive_remaining_budget(self):
        class Response(BytesIO):
            headers = {'Content-Type':'text/html'}
        token = research._RESEARCH_DEADLINE.set(time.monotonic()+0.25)
        try:
            with patch.object(research.urllib.request, 'urlopen', return_value=Response(b'<rss><channel/></rss>')) as fetch:
                research._search_bing_news('fixture')
            self.assertGreater(fetch.call_args.kwargs['timeout'], 0)
            self.assertLessEqual(fetch.call_args.kwargs['timeout'], .25)
        finally:
            research._RESEARCH_DEADLINE.reset(token)

    def test_expired_budget_stops_fetch_search_and_fallback(self):
        token = research._RESEARCH_DEADLINE.set(time.monotonic()-1)
        try:
            with patch.object(research.urllib.request, 'urlopen') as fetch:
                for call in (lambda:research.fetch_article_text('https://example.test/story'), lambda:research._search_bing_news('fixture'), lambda:research._search_google_news('fixture')):
                    with self.assertRaises(research.ResearchDeadlineExceeded):
                        call()
            fetch.assert_not_called()
        finally:
            research._RESEARCH_DEADLINE.reset(token)

    def test_initial_and_repair_prompts_preserve_statistic_speaker_method(self):
        from monica_writer import _build_prompt, _build_repair_prompt
        packet = {'packet_id':'fixture', 'clean_source_blocks':[]}
        for prompt in (_build_prompt(packet), _build_repair_prompt(packet, {}, [])):
            for required in ('denominator', 'response category', '49%', '24%', 'Tiina Toivonen', 'Atte Rytkönen-Sandberg', 'Sunday-to-Monday', 'all weekdays', 'interested-party', 'One sufficient primary-source official report', 'do not force two', 'do not prove all factual truth', 'INSUFFICIENT_CONFIDENCE'):
                self.assertIn(required, prompt)


class DeployAndTerminalBoundaries(unittest.TestCase):
    def test_sync_cannot_change_any_selected_artifact(self):
        with patch.object(staged, 'refresh_static_status'), patch.object(staged, '_deploy_working_delta', side_effect=[{'content/posts/a.md':('??','original')}, {'content/posts/a.md':('??','changed')}]), patch.object(staged.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='', stderr='')) as run:
            self.assertEqual(staged.run_git_deploy(1), 4)
        self.assertEqual([call.args[0][1] for call in run.call_args_list], ['pull'])

    def test_successful_sync_retains_existing_push_sequence(self):
        with patch.object(staged, 'refresh_static_status'), patch.object(staged, '_deploy_working_delta', return_value={'content/posts/a.md':('??','original')}), patch.object(staged.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='', stderr='')) as run:
            self.assertEqual(staged.run_git_deploy(1), 0)
        self.assertEqual([call.args[0][1] for call in run.call_args_list], ['pull','add','commit','push'])

    def test_freshness_expiring_during_assets_aborts_whole_batch(self):
        value = record()
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            outbox = root/'outbox'
            outbox.mkdir()
            path = outbox/'story.json'
            path.write_text(json.dumps(value))
            before = path.read_bytes()
            stack.enter_context(patch.object(staged, 'STAGED_ROOT', root))
            stack.enter_context(patch.object(staged, 'load_outbox', return_value=[(path,value)]))
            for name in ('filter_new_articles', 'dedup_within_batch'):
                stack.enter_context(patch.object(staged, name, side_effect=lambda rows:rows))
            stack.enter_context(patch.object(staged, 'check_published_duplicates', side_effect=lambda rows, **kw:rows))
            stack.enter_context(patch.object(staged, 'run_quality_gate', side_effect=lambda rows:SimpleNamespace(passed=rows,rejected=[])))
            def assets(rows):
                value['original_article']['published'] = '2000-01-01T00:00:00Z'
                return {'total':1,'images':0,'missing':1}
            stack.enter_context(patch.object(staged, 'enrich_images_for_articles', side_effect=assets))
            publish = stack.enter_context(patch.object(staged, 'publish_articles'))
            mark = stack.enter_context(patch.object(staged, 'mark_published'))
            args = SimpleNamespace(max_articles=1, dedup_window=48, dry_run=False, git_push=False, outcome_json='')
            self.assertEqual(staged.cmd_publish(args), 4)
            self.assertEqual(path.read_bytes(), before)
            publish.assert_not_called()
            mark.assert_not_called()

    def test_source_calendar_date_and_packet_projection(self):
        from freshness import freshness_reasons
        from story_packet import build_story_packet
        now = datetime(2026,9,7,12,tzinfo=timezone.utc)
        article = {'title':'Fixture', 'published':'2026-09-07', 'link':'https://example.test/story'}
        self.assertEqual(freshness_reasons(article, now=now), ())
        packet = build_story_packet(article)
        self.assertEqual(packet['published'], article['published'])


class AdmissionBoundaries(unittest.TestCase):
    def test_combined_firehose_candidate_rejected_before_research(self):
        bad = {'title':'Stale firehose fixture', 'published':'2000-01-01T00:00:00Z', '_url_hash':'fixture'}
        args = SimpleNamespace(dry_run=True, max_ready_backlog=0)
        with tempfile.TemporaryDirectory() as tmp, patch.object(staged, 'STAGED_ROOT', Path(tmp)), patch.object(staged, 'scan_all_feeds', return_value=[]), patch.object(staged, 'poll_firehose', return_value=[bad]), patch.object(staged, 'enrich_with_research') as enrich:
            self.assertEqual(staged.cmd_scan(args), 0)
        enrich.assert_not_called()

    def test_mixed_invalid_and_zoned_feed_dates_do_not_crash_health(self):
        health = feed_health.FeedHealth.__new__(feed_health.FeedHealth)
        health._data = {}
        payload = b'<rss><channel><item><title>Undated</title><pubDate>2026-09-07T01:00:00</pubDate></item><item><title>Dated</title><pubDate>2026-09-07T01:00:00Z</pubDate></item></channel></rss>'
        with patch.object(scanner, 'RSS_FEEDS', [{'name':'Fixture','url':'https://example.test/rss'}]), patch.object(scanner, 'DOMAIN_DELAY', 0), patch.object(scanner, 'get_global_health', return_value=health), patch.object(scanner, 'save_global_health'), patch.object(scanner, '_load_rss_feed_policy', return_value={}), patch.object(scanner.urllib.request, 'urlopen', return_value=BytesIO(payload)):
            scanner.scan_all_feeds()
        self.assertTrue(health._data['Fixture']['last_success'])


class CollisionRetryBoundaries(unittest.TestCase):
    def test_normalization_collision_and_next_day_retry(self):
        articles = [{'title':'Äänet ratkaisevat', 'content':'FIRST'}, {'title':'Aanet ratkaisevat', 'content':'SECOND'}]
        self.assertEqual(publisher._make_slug(articles[0]['title']), publisher._make_slug(articles[1]['title']))
        with tempfile.TemporaryDirectory() as tmp, patch.object(publisher, 'CONTENT_DIR', tmp), patch.object(publisher, '_refresh_daily_briefing_flags', return_value=[]):
            paths = publisher.publish_articles(articles)
            before = {p:Path(p).read_bytes() for p in paths}
            with patch.object(publisher, 'datetime') as clock:
                clock.now.return_value = datetime.now(timezone.utc)+timedelta(days=1)
                self.assertEqual(publisher.publish_articles(articles), paths)
            self.assertEqual(len(set(paths)), 2)
            self.assertEqual({p:Path(p).read_bytes() for p in paths}, before)

    def test_unrelated_historical_duplicates_do_not_block_new_story(self):
        old = {'title':'Old', 'content':'OLD', 'source_url':'https://example.test/old'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(publisher, 'CONTENT_DIR', tmp), patch.object(publisher, '_refresh_daily_briefing_flags', return_value=[]):
            for name in ('legacy-one.md','legacy-two.md'):
                (Path(tmp)/name).write_text(publisher._article_to_markdown(old,'2000-01-01T00:00:00Z'))
            self.assertEqual(len(publisher.publish_articles([{'title':'New','content':'NEW'}])), 1)
            with self.assertRaises(FileExistsError):
                publisher.publish_articles([old])


if __name__ == '__main__':
    unittest.main()
