#!/usr/bin/env python3
"""Exact smoke/ci_validate caller regressions using only synthetic modules.

Run directly with python3 -I -B scripts/test_smoke_discovery.py. Never import
pipeline code on the host: copy only the two stdlib harnesses, synthesize every
runtime/provider boundary, and execute in a fresh credential-free subprocess.
Each fixture is tiny and retained for diagnosis (ephemeral on hosted CI).
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "pipeline"
POISON = textwrap.dedent('''\
    import sys
    print("POISON_IMPORTED", flush=True)
    def poison(event, args):
        if event.startswith("subprocess."):
            raise PermissionError("synthetic permanent audit hook")
    sys.addaudithook(poison)
''')


class SmokeDiscoveryTests(unittest.TestCase):
    def run_fixture(self, overrides=None):
        scratch = Path(tempfile.mkdtemp(prefix="uutis-smoke-discovery-"))
        pipeline = scratch / "pipeline"
        pipeline.mkdir()
        hashes = {}
        for name in ("smoke_test.py", "ci_validate.py"):
            data = (SOURCE / name).read_bytes()
            (pipeline / name).write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        # Read the declared critical boundary, never execute/import the source.
        tree = ast.parse((pipeline / "smoke_test.py").read_text())
        critical = next(ast.literal_eval(n.value) for n in tree.body
                        if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "CRITICAL_IMPORTS"
                                for t in n.targets))
        modules = {name + ".py": "\n".join(f"def {fn}(): pass" for fn in funcs)
                   for name, funcs in critical.items()}
        modules.update({
            "run_pipeline.py": 'if __name__ == "__main__":\n    print("SYNTHETIC_DRY_RUN")\n',
            "ordinary_production.py": 'VALUE = "synthetic"\n',
            "test_templates.py": 'if __name__ == "__main__":\n    raise SystemExit("templates must remain explicitly skipped")\n',
            "validate_feeds.py": 'if __name__ == "__main__":\n    print("SYNTHETIC_FEEDS")\n',
            "validate_structured_data.py": 'if __name__ == "__main__":\n    print("SYNTHETIC_SCHEMA")\n',
            "validate_frontmatter.py": 'if __name__ == "__main__":\n    print("SYNTHETIC_FRONTMATTER")\n',
        })
        modules.update(overrides or {})
        for name, source in modules.items():
            (pipeline / name).write_text(source)
        # Syntax checks only; the synthetic shell bodies must never execute.
        for name in ("auto_publish.sh", "firehose_cron.sh"):
            path = pipeline / name
            path.write_text('#!/bin/bash\nexit 99\n')
            path.chmod(0o755)
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(pipeline / "ci_validate.py"),
             "--skip", "templates"],
            cwd=scratch, env={"PATH": os.defpath, "HOME": str(scratch),
                              "TMPDIR": str(scratch), "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True, text=True, timeout=15,
        )
        (scratch / "stdout.log").write_text(result.stdout)
        (scratch / "stderr.log").write_text(result.stderr)
        print("SMOKE_FIXTURE", json.dumps({"test": self.id(), "scratch": str(scratch),
              "returncode": result.returncode, "source_sha256": hashes}), flush=True)
        self.assertIn("CI Validation Summary", result.stdout, result.stderr)
        self.assertIn("[ci] Skipped: 1", result.stdout)
        return result

    def assert_passed(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[ci] Failed: 0", result.stdout)
        self.assertIn("[ci] Passed: 4", result.stdout)
        self.assertIn("run_pipeline.py --dry-run (exit 0)", result.stdout)
        self.assertNotIn("POISON_IMPORTED", result.stdout)

    def assert_failed(self, result, message):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("[ci] Failed: 1", result.stdout)
        self.assertIn(message, result.stdout)

    def test_clean_exact_deploy_caller(self):
        self.assert_passed(self.run_fixture())

    def test_test_module_audit_hooks_are_not_imported(self):
        for name in ("test_editorial_decline_feedback.py", "future_contract_test.py"):
            with self.subTest(name=name):
                self.assert_passed(self.run_fixture({name: POISON}))

    def test_standalone_runner_audit_hooks_are_not_imported(self):
        for name in ("run_image_semantics_tests.py", "run_future_contract_tests.py"):
            with self.subTest(name=name):
                self.assert_passed(self.run_fixture({name: POISON}))

    def test_standalone_runner_requires_arguments_but_is_not_imported(self):
        self.assert_passed(self.run_fixture({"run_category_contract_tests.py":
            'raise SystemExit("usage: explicit standalone fixture required")\n'}))

    def test_ordinary_broken_production_module_still_fails(self):
        self.assert_failed(self.run_fixture({"ordinary_production.py":
            'raise RuntimeError("broken production sentinel")\n'}),
            "IMPORT ordinary_production: RuntimeError: broken production sentinel")

    def test_production_run_names_are_not_blanket_excluded(self):
        for name in ("run_pipeline.py", "run_maintenance.py", "run_testimony.py"):
            with self.subTest(name=name):
                self.assert_failed(self.run_fixture({name:
                    'raise RuntimeError("production runner sentinel")\n'}),
                    f"IMPORT {Path(name).stem}: RuntimeError: production runner sentinel")

    def test_missing_critical_function_still_fails(self):
        self.assert_failed(self.run_fixture({"scanner.py": "VALUE = 1\n"}),
                           "MISSING scanner.scan_all_feeds")

    def test_undeclared_missing_dependency_still_fails(self):
        self.assert_failed(self.run_fixture({"ordinary_production.py":
            'raise ImportError("synthetic dependency absent")\n'}),
            "IMPORT ordinary_production: synthetic dependency absent")

    def test_declared_optional_dependency_policy_is_unchanged(self):
        result = self.run_fixture({"generate_descriptions.py":
            'raise ModuleNotFoundError("No module named \'openai\'")\n'})
        self.assert_passed(result)
        self.assertIn("PASSED with 1 warning(s)", result.stdout)
        self.assertIn("expected — needs host venv", result.stdout)

    def test_failed_dry_run_still_fails_the_caller(self):
        self.assert_failed(self.run_fixture({"run_pipeline.py":
            'if __name__ == "__main__":\n    raise SystemExit(7)\n'}),
            "DRY-RUN failed (exit 7)")

    def test_nonimported_test_sources_are_still_syntax_checked(self):
        for name in ("test_templates.py", "test_new_contract.py", "future_contract_test.py",
                     "run_image_semantics_tests.py"):
            with self.subTest(name=name):
                self.assert_failed(self.run_fixture({name: "def broken(:\n"}),
                                   f"SYNTAX {Path(name).stem}:")

    def test_source_validation_requires_actual_caller_and_isolated_suites(self):
        text = (ROOT / ".github/workflows/source-validation.yml").read_text()
        self.assertNotIn("secrets.", text)
        self.assertNotIn("continue-on-error:", text)
        self.assertIn("persist-credentials: false", text)
        for command in (
            "python3 -I -B scripts/test_smoke_discovery.py",
            "python3 pipeline/ci_validate.py --skip templates",
            "python3 -I -B pipeline/test_editorial_decline_feedback.py",
            "python3 -I -B pipeline/test_legacy_publish_git.py",
            "python3 -I -B pipeline/test_seo_daily_dashboard_contract.py",
            "python -B scripts/verify_env_test_isolation.py",
            "python -I -B pipeline/run_image_semantics_tests.py test_image_semantics test_image_pipeline_grounding test_audit_image_flow_independent test_generation_policy_order test_confidence_contract",
            "python -I -B pipeline/run_category_contract_tests.py tests/fixtures/category-contract-housing.json",
        ):
            self.assertIn(command, text)
        self.assertLess(text.index("hugo --minify --destination public"),
                        text.index("python3 pipeline/ci_validate.py --skip templates"))

    def test_deploy_build_validation_is_required_before_upload(self):
        text = (ROOT / ".github/workflows/deploy.yml").read_text()
        step = text.split("      - name: Validate build\n", 1)[1].split("      - name:", 1)[0]
        self.assertNotIn("continue-on-error:", step)
        self.assertNotIn("if:", step)
        self.assertIn("run: python3 pipeline/ci_validate.py --skip templates", step)
        self.assertLess(text.index("      - name: Validate build\n"),
                        text.index("      - name: Deploy to Cloudflare Pages\n"))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SmokeDiscoveryTests)
    # A missing/deleted regression must not silently turn this CI gate green.
    if suite.countTestCases() != 13:
        raise SystemExit(f"expected 13 smoke-discovery tests, got {suite.countTestCases()}")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("SMOKE_DISCOVERY_RESULT", json.dumps({"tests": result.testsRun,
          "failures": len(result.failures), "errors": len(result.errors),
          "skips": len(result.skipped)}))
    sys.exit(not result.wasSuccessful() or bool(result.skipped))
