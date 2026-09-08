"""Isolated exact-source diagnostics tests; never import the live pipeline.

Run directly with python3 -I -B. All fixture evidence is synthetic/minimized;
no queue, credentials, provider, subprocess or filesystem mutation is allowed.
"""
import sys

# Install before consumer/test-library imports. Source reads are allowlisted.
def _audit(event, args):
    if event == 'open':
        path, mode, flags = args
        if not isinstance(path, str):
            raise PermissionError('descriptor access denied')
        if (mode and any(c in mode for c in 'wax+')) or flags & (1 | 2 | 64 | 512 | 1024):
            raise PermissionError('write denied')
        source_dir = __file__.rsplit('/', 1)[0]
        allowed = {source_dir + '/' + name for name in (
            'staged_publish.py', 'monica_writer.py', 'test_editorial_decline_feedback.py')}
        if path not in allowed and not path.startswith(('/usr/lib/python', '/usr/local/lib/python')):
            raise PermissionError('nonfixture read denied')
        if '/site-packages/' in path or '/dist-packages/' in path:
            raise PermissionError('third-party import denied')
    if event.startswith(('socket.', 'subprocess.', 'os.exec', 'os.spawn')) or event in {
        'os.system', 'os.mkdir', 'os.remove', 'os.rename', 'os.rmdir', 'os.putenv',
        'os.unsetenv', 'os.chmod', 'os.link', 'os.symlink', 'os.truncate'}:
        raise PermissionError('side effect denied: ' + event)

sys.addaudithook(_audit)
sys.dont_write_bytecode = True
import ast
import hashlib
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NS = {'_WS_RE': re.compile(r'\s+'), 're': re}
SOURCE_HASHES = {}


def load_exact(filename, names):
    source = (ROOT / filename).read_text()
    SOURCE_HASHES[filename] = hashlib.sha256(source.encode()).hexdigest()
    tree = ast.parse(source)
    selected = []
    for node in tree.body:
        name = getattr(node, 'name', None)
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], 'id', None)
        if name in names:
            selected.append(node)
    assert len(selected) == len(names), (filename, names)
    unit = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)] + selected, type_ignores=[])
    exec(compile(ast.fix_missing_locations(unit), str(ROOT / filename), 'exec'), NS)
    return source


load_exact('monica_writer.py', {'WRITER_SCHEMA', '_basic_payload_issues', '_source_block_words', '_packet_source_words', '_packet_source_blocks', '_normalize_ws'})
NS['monica_packet_source_words'] = NS['_packet_source_words']
NS['monica_packet_source_blocks'] = NS['_packet_source_blocks']
SOURCE = load_exact('staged_publish.py', {'failed_writer_feedback', 'packet_source_words', 'packet_source_blocks', 'normalize_failure_reason', 'staged_failed_retry_classification', 'RECOVERABLE_TALOUS_FAILED_CLASSES'})
feedback = NS['failed_writer_feedback']


class EditorialDeclineFeedbackTests(unittest.TestCase):
    def data(self):
        return {'packet': {'packet_id': 'synthetic-decline', 'category': 'Kotimaa', 'story_confidence': 0.98,
                           'clean_source_blocks': [{'text': 'fact ' * n} for n in (12, 98, 124, 122)]}}

    def check(self, data, payload, expected, issues=None, raw=''):
        before = repr((data, payload))
        result = feedback(data, payload, issues, raw)
        self.assertEqual(result['retry_classification'], expected)
        self.assertTrue(result['fail_closed'])
        self.assertEqual(before, repr((data, payload)))
        return result

    def test_minimized_fresh_decline(self):
        data = self.data()
        data['failure'] = 'insufficient_confidence_after_repair'
        payload = {'packet_id': 'synthetic-decline', 'status': 'INSUFFICIENT_CONFIDENCE',
                   'editorial_reviewed': False, 'journalist_note': 'Evidence cannot support format; contradictory comparison and unrelated source.'}
        result = self.check(data, payload, 'insufficient_confidence', [])
        self.assertEqual(result['issues'], [])
        self.assertEqual(result['selected_source_words'], 356)
        self.assertEqual(result['selected_source_blocks'], 4)
        self.assertEqual(result['final_word_count'], 0)
        self.assertFalse(result['near_miss_short'])
        data['writer_failure_feedback'] = result
        self.assertEqual(NS['staged_failed_retry_classification'](data), 'insufficient_confidence')
        self.assertNotIn(result['retry_classification'], NS['RECOVERABLE_TALOUS_FAILED_CLASSES'])

    def test_decline_does_not_run_article_schema_validation(self):
        original = NS['_basic_payload_issues']
        def forbidden(*args):
            self.fail('article validator called for structured decline')
        NS['_basic_payload_issues'] = forbidden
        try:
            self.check(self.data(), {'status': 'INSUFFICIENT_CONFIDENCE'}, 'insufficient_confidence', [])
        finally:
            NS['_basic_payload_issues'] = original

    def test_malformed_ordinary_payload_remains_schema_invalid(self):
        result = self.check(self.data(), {'title': 'Incomplete article'}, 'writer_schema_invalid', [])
        self.assertTrue(result['issues'][0].startswith('missing keys:'))

    def test_source_insufficiency_tokens_do_not_replace_structured_status(self):
        for status in ('insufficient_confidence', 'INSUFFICIENT_CONFIDENCE_EXTRA', '', None):
            with self.subTest(status=status):
                self.check(self.data(), {'status': status, 'journalist_note': 'INSUFFICIENT_CONFIDENCE source too thin'}, 'writer_schema_invalid')
        data = self.data()
        data['failure'] = 'source too thin insufficient_confidence'
        self.check(data, {'title': 'Incomplete'}, 'writer_schema_invalid')

    def test_raw_status_token_is_not_a_parsed_decline(self):
        self.check(self.data(), None, 'writer_schema_invalid', [], 'INSUFFICIENT_CONFIDENCE')

    def test_runtime_failures_keep_precedence(self):
        for message in ('timed out', 'context overflow', 'GatewayClientRequestError', 'FailoverError', 'oauth token'):
            with self.subTest(message=message):
                data = self.data()
                data['failure'] = message
                self.check(data, {'status': 'INSUFFICIENT_CONFIDENCE'}, 'writer_runtime')
                self.check(data, None, 'writer_runtime')

    def test_decline_note_runtime_token_is_not_runtime_failure(self):
        self.check(self.data(), {'status': 'INSUFFICIENT_CONFIDENCE', 'journalist_note': 'source discusses timeout'}, 'insufficient_confidence', [], '{"journalist_note":"timeout"}')

    def test_invalid_json_stays_invalid_json(self):
        self.check(self.data(), None, 'writer_invalid_json', [], 'not valid json')

    def test_short_and_near_miss_controls_unchanged(self):
        for words, expected in ((199, 'writer_short_after_repair'), (248, 'repair_near_miss_short')):
            with self.subTest(words=words):
                self.check(self.data(), {'content': 'word ' * words}, expected, ['content too short'])

    def test_data_payload_decline_fallback(self):
        data = self.data()
        data['payload'] = {'status': 'INSUFFICIENT_CONFIDENCE'}
        self.check(data, None, 'insufficient_confidence')

    def test_side_effect_guard(self):
        for event, args in [('open', ('/nonfixture/.env', 'r', 0)), ('open', (str(ROOT / 'staged_publish.py'), 'w', 577)), ('socket.connect', ()), ('subprocess.Popen', ()), ('os.mkdir', ())]:
            with self.subTest(event=event):
                with self.assertRaises(PermissionError):
                    sys.audit(event, *args)

    def test_complete_source_compiles_without_importing_it(self):
        compile(SOURCE, str(ROOT / 'staged_publish.py'), 'exec')
        compile(Path(__file__).read_text(), __file__, 'exec')


if __name__ == '__main__':
    print('SOURCE_SHA256', SOURCE_HASHES, flush=True)
    unittest.main(verbosity=2)
