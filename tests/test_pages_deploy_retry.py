import os, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Real wrangler output from the failed 31 Oct 2026 production deploy.
REAL_10500 = (
    "\u2718 [ERROR] A request to the Cloudflare API (/accounts/***/pages/projects/uutistenlukija-fi) failed.\n\n"
    "  Internal authentication error: internal server error [code: 10500]\n")


class PagesDeployRetry(unittest.TestCase):
    def run_with(self, outputs):
        work = Path(tempfile.mkdtemp())
        counter = work / 'n'
        counter.write_text('0')
        script = work / 'wrangler'
        cases = ''.join(f'  {i}) printf %s {repr(text)}; exit {code};;\n'
                        for i, (text, code) in enumerate(outputs))
        script.write_text('#!/usr/bin/env bash\nn=$(cat %s); echo $((n+1)) > %s\ncase $n in\n%s  *) exit 9;;\nesac\n'
                          % (counter, counter, cases))
        script.chmod(0o755)
        env = dict(os.environ, WRANGLER=str(script), PAGES_DEPLOY_PAUSE='0', GITHUB_SHA='abc')
        result = subprocess.run(['bash', str(ROOT / 'ops/pages_deploy.sh')], env=env,
                                capture_output=True, text=True, timeout=60)
        return result.returncode, int(counter.read_text())

    def test_real_cloudflare_10500_is_retried_then_succeeds(self):
        self.assertEqual(self.run_with([(REAL_10500, 1), ('Deployment complete', 0)]), (0, 2))

    def test_retry_is_bounded(self):
        self.assertEqual(self.run_with([(REAL_10500, 1)] * 6), (1, 4))

    def test_non_transient_error_fails_at_once(self):
        self.assertEqual(self.run_with([('Authentication error [code: 10000]', 1)]), (1, 1))

    def test_workflow_uses_bounded_script(self):
        workflow = (ROOT / 'ops/deploy.yml').read_text()
        self.assertIn('run: bash ops/pages_deploy.sh', workflow)
        self.assertNotIn('wrangler-action', workflow)


if __name__ == '__main__':
    unittest.main()
