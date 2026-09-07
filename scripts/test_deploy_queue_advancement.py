"""Exercise the actual workflow shell with small, real, shallow Git repos.

No production queue, credentials, network, build, or upload is used.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/deploy.yml'


class QueueAdvancementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='deploy-queue-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.root),
                    'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
                    'GIT_AUTHOR_NAME': 'Test', 'GIT_COMMITTER_NAME': 'Test',
                    'GIT_AUTHOR_EMAIL': 'test@example.invalid',
                    'GIT_COMMITTER_EMAIL': 'test@example.invalid'}
        self.remote = self.root / 'remote'
        self.git(self.root, 'init', '--bare', '--initial-branch=main', str(self.remote))
        self.writer = self.root / 'writer'
        self.git(self.root, 'clone', str(self.remote), str(self.writer))
        self.put('content/posts/story.md', 'initial article')
        self.put('pipeline/queues/staged/ready/packet.json', '{}')
        self.commit()
        self.git(self.writer, 'push', 'origin', 'main')
        self.checkout = self.root / 'checkout'
        self.git(self.root, 'clone', '--depth=1', self.remote.as_uri(), str(self.checkout))
        self.sha = self.git(self.checkout, 'rev-parse', 'HEAD').stdout.strip()
        workflow = WORKFLOW.read_text()
        start = workflow.index('      - name: Verify deployment checkout is current')
        start = workflow.index('        run: |\n', start) + len('        run: |\n')
        end = workflow.index('\n      - name:', start)
        self.script = textwrap.dedent(workflow[start:end])

    def git(self, cwd, *args):
        return subprocess.run(['git', *args], cwd=cwd, env=self.env,
                              capture_output=True, text=True, check=True, timeout=15)

    def put(self, path, content):
        target = self.writer / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def commit(self):
        self.git(self.writer, 'add', '--all')
        self.git(self.writer, 'commit', '-m', 'fixture')

    def advance(self):
        self.commit()
        self.git(self.writer, 'push', 'origin', 'main')

    def run_guard(self, event='push', prefix=''):
        output = self.root / 'output'
        output.write_text('')
        env = dict(self.env, GITHUB_EVENT_NAME=event, GITHUB_REF='refs/heads/main',
                   GITHUB_SHA=self.sha, GITHUB_OUTPUT=str(output))
        result = subprocess.run(['bash', '-c', prefix + self.script],
                                cwd=self.checkout, env=env, capture_output=True,
                                text=True, timeout=20)
        return result, output.read_text()

    def assert_allowed(self, event='push'):
        result, output = self.run_guard(event)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, 'current=true\n')
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD').stdout.strip(), self.sha)

    def test_exact_main(self):
        self.assert_allowed()

    def test_queue_transition_allows_push_and_manual_with_shallow_checkout(self):
        (self.writer / 'pipeline/queues/staged/ready/packet.json').unlink()
        self.put('pipeline/queues/staged/outbox/packet.json', '{"article":"ready"}')
        self.advance()
        for event in ('push', 'workflow_dispatch'):
            with self.subTest(event=event):
                self.assert_allowed(event)

    def test_article_change_skips_push_and_rejects_manual(self):
        self.put('content/posts/story.md', 'new article')
        self.advance()
        result, output = self.run_guard()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(output, 'current=false\n')
        result, output = self.run_guard('workflow_dispatch')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output, '')

    def test_mixed_queue_and_template_change_is_not_exempt(self):
        self.put('pipeline/queues/staged/outbox/packet.json', '{}')
        self.put('layouts/index.html', 'new template')
        self.advance()
        result, output = self.run_guard()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(output, 'current=false\n')

    def test_queue_to_content_rename_is_not_exempt(self):
        self.git(self.writer, 'mv', 'pipeline/queues/staged/ready/packet.json',
                 'content/posts/packet.json')
        self.advance()
        result, output = self.run_guard()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(output, 'current=false\n')

    def test_dirty_generated_files_do_not_define_committed_equivalence(self):
        self.put('pipeline/queues/staged/outbox/packet.json', '{}')
        self.advance()
        (self.checkout / 'content/posts/story.md').write_text('local generated change')
        self.assert_allowed()

    def test_diff_error_fails_closed(self):
        self.put('pipeline/queues/staged/outbox/packet.json', '{}')
        self.advance()
        result, output = self.run_guard(prefix='git() { if [ "$1" = diff ]; then return 128; else command git "$@"; fi; }\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output, '')
        self.assertIn('Unable to compare', result.stdout)

    def test_fetch_error_fails_closed(self):
        self.git(self.checkout, 'remote', 'set-url', 'origin', str(self.root / 'missing'))
        result, output = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output, '')

    def test_unknown_nonqueue_path_is_not_exempt(self):
        self.put('pipeline/queues/staged-lookalike/file.json', '{}')
        self.advance()
        result, output = self.run_guard()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(output, 'current=false\n')


if __name__ == '__main__':
    unittest.main()
