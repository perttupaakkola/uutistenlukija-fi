"""13 Nov 2026: the bind step read Cloudflare's previous canonical deployment right
after wrangler returned and failed a deploy that actually went live (run 43347544446,
commit c2efdc17). The check must keep polling until the canonical deployment is ours."""
import io, json, os, textwrap, unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OURS = 'c2efdc17b768b93eaa481bf3df6964a707502e32'
PREVIOUS = 'ec96b419cd7d0f739fb57a1d93b887bd2a80a279'


def dep(commit, status):
    return {'id': 'dep-' + commit[:6], 'url': 'https://x.pages.dev', 'environment': 'production',
            'latest_stage': {'status': status}, 'deployment_trigger': {'metadata': {'commit_hash': commit}}}


class BindRace(unittest.TestCase):
    def run_bind(self, sequence):
        code = (ROOT / 'ops/deploy.yml').read_text().split("python3 - <<'PY'\n", 1)[1].split('\n          PY', 1)[0]
        code = textwrap.dedent(code)
        answers = iter(sequence)
        calls = []
        def urlopen(req, timeout=30):
            calls.append(1)
            return io.BytesIO(json.dumps({'success': True, 'result': {'canonical_deployment': next(answers)}}).encode())
        seen = {}
        def record(receipt, d, sha):
            seen['d'] = d
            return {'ok': True}
        with TemporaryDirectory() as tmp:
            (Path(tmp) / 'release').mkdir()
            (Path(tmp) / 'release/release.json').write_text('{}')
            old = os.getcwd()
            os.chdir(tmp)
            try:
                with patch.dict(os.environ, {'GITHUB_SHA': OURS, 'CF_ACCOUNT': 'a', 'CF_TOKEN': 't'}), \
                        patch('urllib.request.urlopen', urlopen), patch('time.sleep', lambda s: None), \
                        patch('news_mvp.release_contract.deployment_record', record):
                    exec(compile(code, 'ops/deploy.yml', 'exec'), {})
            finally:
                os.chdir(old)
        return seen['d'], len(calls)

    def test_previous_settled_deployment_is_waited_out(self):
        d, calls = self.run_bind([dep(PREVIOUS, 'success'), dep(PREVIOUS, 'success'), dep(OURS, 'active'), dep(OURS, 'success')])
        self.assertEqual(d['deployment_trigger']['metadata']['commit_hash'], OURS)
        self.assertEqual(calls, 4)

    def test_genuine_failure_of_our_commit_still_fails(self):
        with self.assertRaises(AssertionError):
            self.run_bind([dep(OURS, 'failure')])

    def test_never_ours_fails_bounded(self):
        with patch('time.time', side_effect=[0] + [1000] * 50):
            with self.assertRaises(AssertionError):
                self.run_bind([dep(PREVIOUS, 'success')] * 5)


if __name__ == '__main__':
    unittest.main()
