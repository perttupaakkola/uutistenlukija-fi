#!/usr/bin/env python3
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_hugo.sh"


class VerifyHugoTest(unittest.TestCase):
    def run_verification(self, issue: str, *, hugo_status: int = 0, check_status: int = 0):
        issue_number = issue.removeprefix("OPE-")
        output_dir = Path(f"/tmp/ope{issue_number}-hugo-build")
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", "--", str(output_dir)], check=False))

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_hugo = Path(temp_dir) / "hugo"
            fake_hugo.write_text(
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                "while [[ $# -gt 0 ]]; do\n"
                "  if [[ $1 == --destination ]]; then mkdir -p \"$2\"; echo built > \"$2/marker\"; fi\n"
                "  shift\n"
                "done\n"
                "exit \"${FAKE_HUGO_STATUS:-0}\"\n",
                encoding="utf-8",
            )
            fake_hugo.chmod(0o755)
            env = os.environ | {
                "HUGO_BIN": str(fake_hugo),
                "FAKE_HUGO_STATUS": str(hugo_status),
                "CHECK_STATUS": str(check_status),
            }
            result = subprocess.run(
                [
                    str(SCRIPT),
                    issue,
                    "--",
                    "bash",
                    "-c",
                    'test -f "$HUGO_OUTPUT_DIR/marker" && exit "$CHECK_STATUS"',
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
        return result, output_dir

    def test_success_removes_cleanup_compatible_output(self):
        result, output_dir = self.run_verification("OPE-99001")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output_dir, Path("/tmp/ope99001-hugo-build"))
        self.assertFalse(output_dir.exists())

    def test_failed_build_preserves_output_for_diagnosis(self):
        result, output_dir = self.run_verification("OPE-99002", hugo_status=7)
        self.assertEqual(result.returncode, 7)
        self.assertTrue((output_dir / "marker").is_file())
        self.assertIn("preserving evidence", result.stderr)

    def test_failed_verification_preserves_output_for_diagnosis(self):
        result, output_dir = self.run_verification("OPE-99003", check_status=9)
        self.assertEqual(result.returncode, 9)
        self.assertTrue((output_dir / "marker").is_file())
        self.assertIn("preserving evidence", result.stderr)


if __name__ == "__main__":
    unittest.main()
