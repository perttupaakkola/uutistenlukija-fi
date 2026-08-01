import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


SOURCE_WRAPPER = Path(__file__).with_name("staged_monica_worker_cron.sh")


class StagedMonicaWorkerCronTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.origin = self.root / "origin.git"
        self.seed = self.root / "seed"
        self.worker = self.root / "worker"
        self._run(["git", "init", "--bare", str(self.origin)])
        self._run(["git", "init", "-b", "main", str(self.seed)])
        self._git(self.seed, "config", "user.name", "Test Operator")
        self._git(self.seed, "config", "user.email", "test@example.invalid")
        self._git(self.seed, "remote", "add", "origin", str(self.origin))
        self._write_fixture_repo()
        self._git(self.seed, "add", ".")
        self._git(self.seed, "commit", "-m", "fixture base")
        self._git(self.seed, "push", "-u", "origin", "main")
        self._run(["git", "clone", "--branch", "main", str(self.origin), str(self.worker)])
        self._git(self.worker, "config", "user.name", "Cron Worker")
        self._git(self.worker, "config", "user.email", "cron@example.invalid")

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def _run(command, cwd=None, env=None, check=True):
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=check,
            text=True,
            capture_output=True,
        )

    def _git(self, cwd, *args, check=True):
        return self._run(["git", *args], cwd=cwd, check=check)

    def _write_fixture_repo(self):
        pipeline = self.seed / "pipeline"
        pipeline.mkdir(parents=True)
        shutil.copy2(SOURCE_WRAPPER, pipeline / SOURCE_WRAPPER.name)
        (pipeline / "staged_publish.py").write_text(
            """import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

root = Path.cwd()
age_index = sys.argv.index("--max-ready-age-hours")
if sys.argv[age_index + 1] != "0":
    raise SystemExit(8)
ready = sorted((root / "pipeline/queues/staged/ready").glob("*.json"))
if not ready:
    raise SystemExit(0)
source = ready[0]
writing = root / "pipeline/queues/staged/writing" / source.name
writing.parent.mkdir(parents=True, exist_ok=True)
source.replace(writing)
marker = os.environ.get("STUB_CLAIM_MARKER")
if marker:
    Path(marker).write_text("claimed\\\\n", encoding="utf-8")
delay = float(os.environ.get("STUB_DELAY_AFTER_CLAIM", "0"))
if delay > 0:
    time.sleep(delay)
if os.environ.get("STUB_FAIL") == "1":
    raise SystemExit(7)
payload = json.loads(writing.read_text(encoding="utf-8"))
if os.environ.get("STUB_REJECT") == "1":
    failed = root / "pipeline/queues/staged/failed" / source.name
    failed.parent.mkdir(parents=True, exist_ok=True)
    payload["failure"] = "insufficient_confidence"
    failed.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    writing.unlink()
    raise SystemExit(0)
if os.environ.get("STUB_CONCURRENT") == "1":
    clone = Path(tempfile.mkdtemp(prefix="concurrent-"))
    subprocess.run(["git", "clone", "--branch", "main", os.environ["STUB_ORIGIN"], str(clone)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Concurrent Writer"], cwd=clone, check=True)
    subprocess.run(["git", "config", "user.email", "concurrent@example.invalid"], cwd=clone, check=True)
    (clone / "concurrent.txt").write_text("preserved\\n", encoding="utf-8")
    subprocess.run(["git", "add", "concurrent.txt"], cwd=clone, check=True)
    subprocess.run(["git", "commit", "-m", "concurrent main update"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=clone, check=True, capture_output=True)
if os.environ.get("STUB_CONCURRENT_FAIL_SAME_PACKET") == "1":
    clone = Path(tempfile.mkdtemp(prefix="concurrent-failed-"))
    subprocess.run(["git", "clone", "--branch", "main", os.environ["STUB_ORIGIN"], str(clone)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Concurrent Scanner"], cwd=clone, check=True)
    subprocess.run(["git", "config", "user.email", "scanner@example.invalid"], cwd=clone, check=True)
    remote_ready = clone / "pipeline/queues/staged/ready" / source.name
    remote_failed = clone / "pipeline/queues/staged/failed" / source.name
    remote_failed.parent.mkdir(parents=True, exist_ok=True)
    remote_payload = json.loads(remote_ready.read_text(encoding="utf-8"))
    remote_payload["failure"] = "ready-expire"
    remote_ready.unlink()
    remote_failed.write_text(json.dumps(remote_payload, sort_keys=True), encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
    subprocess.run(["git", "commit", "-m", "scanner expires same ready packet"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=clone, check=True, capture_output=True)
payload["article"] = {"title": "Testi"}
outbox = root / "pipeline/queues/staged/outbox" / source.name
outbox.parent.mkdir(parents=True, exist_ok=True)
outbox.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
writing.unlink()
""",
            encoding="utf-8",
        )
        (self.seed / ".gitignore").write_text(
            "pipeline/queues/staged/writing/\n"
            "pipeline/queues/staged/outbox/\n",
            encoding="utf-8",
        )
        (self.seed / "README.md").write_text("fixture\n", encoding="utf-8")

    def _admit_packet(self, packet="packet.json"):
        self._git(self.seed, "fetch", "origin", "main")
        self._git(self.seed, "reset", "--hard", "origin/main")
        ready = self.seed / "pipeline/queues/staged/ready" / packet
        ready.parent.mkdir(parents=True, exist_ok=True)
        ready.write_text(json.dumps({"packet_id": packet}), encoding="utf-8")
        self._git(self.seed, "add", "-f", str(ready.relative_to(self.seed)))
        self._git(self.seed, "commit", "-m", f"admit {packet}")
        self._git(self.seed, "push", "origin", "main")
        return packet

    def _sync_worker(self):
        self._git(self.worker, "pull", "--ff-only", "origin", "main")

    def _wrapper_env(self, **overrides):
        env = os.environ.copy()
        env.update(
            {
                "STAGED_MONICA_PROJECT_DIR": str(self.worker),
                "STAGED_MONICA_PYTHON": sys.executable,
                "STUB_ORIGIN": str(self.origin),
            }
        )
        env.update(overrides)
        return env

    def _run_wrapper(self, **overrides):
        return self._run(
            ["bash", "pipeline/staged_monica_worker_cron.sh"],
            cwd=self.worker,
            env=self._wrapper_env(**overrides),
            check=False,
        )

    def _remote_files(self):
        result = self._git(
            self.worker,
            "--git-dir",
            str(self.origin),
            "ls-tree",
            "-r",
            "--name-only",
            "main",
        )
        return set(result.stdout.splitlines())

    def test_syncs_remote_ready_packet_and_pushes_queue_only_transition(self):
        packet = self._admit_packet()
        result = self._run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        files = self._remote_files()
        self.assertNotIn(f"pipeline/queues/staged/ready/{packet}", files)
        self.assertIn(f"pipeline/queues/staged/outbox/{packet}", files)
        self.assertEqual(self._git(self.worker, "status", "--porcelain").stdout, "")
        subject = self._git(self.worker, "log", "-1", "--format=%s").stdout.strip()
        self.assertEqual(subject, f"auto(staged): Monica ready to outbox {packet}")

    def test_worker_failure_restores_committed_packet_and_leaves_clean_tree(self):
        packet = self._admit_packet("failure.json")
        result = self._run_wrapper(STUB_FAIL="1")
        self.assertEqual(result.returncode, 7)
        self.assertTrue((self.worker / "pipeline/queues/staged/ready" / packet).is_file())
        self.assertFalse((self.worker / "pipeline/queues/staged/writing" / packet).exists())
        self.assertEqual(self._git(self.worker, "status", "--porcelain").stdout, "")
        files = self._remote_files()
        self.assertIn(f"pipeline/queues/staged/ready/{packet}", files)
        self.assertNotIn(f"pipeline/queues/staged/outbox/{packet}", files)

    def test_editorial_rejection_is_committed_to_failed_without_blocking(self):
        packet = self._admit_packet("editorial-rejection.json")
        result = self._run_wrapper(STUB_REJECT="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        files = self._remote_files()
        self.assertIn(f"pipeline/queues/staged/failed/{packet}", files)
        self.assertNotIn(f"pipeline/queues/staged/ready/{packet}", files)
        self.assertNotIn(f"pipeline/queues/staged/outbox/{packet}", files)
        subject = self._git(
            self.worker,
            "--git-dir",
            str(self.origin),
            "log",
            "-1",
            "--format=%s",
            "main",
        ).stdout.strip()
        self.assertEqual(subject, f"auto(staged): Monica ready to failed {packet}")
        self.assertEqual(self._git(self.worker, "status", "--porcelain").stdout, "")

    def test_startup_restores_unchanged_orphaned_writing_packet(self):
        packet = self._admit_packet("orphaned-writing.json")
        self._sync_worker()
        ready = self.worker / "pipeline/queues/staged/ready" / packet
        writing = self.worker / "pipeline/queues/staged/writing" / packet
        writing.parent.mkdir(parents=True, exist_ok=True)
        ready.replace(writing)

        result = self._run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        files = self._remote_files()
        self.assertIn(f"pipeline/queues/staged/outbox/{packet}", files)
        self.assertNotIn(f"pipeline/queues/staged/ready/{packet}", files)
        self.assertFalse(writing.exists())
        self.assertEqual(self._git(self.worker, "status", "--porcelain").stdout, "")

    def test_startup_commits_completed_outbox_without_regenerating_it(self):
        packet = self._admit_packet("completed-before-commit.json")
        self._sync_worker()
        ready = self.worker / "pipeline/queues/staged/ready" / packet
        outbox = self.worker / "pipeline/queues/staged/outbox" / packet
        payload = json.loads(ready.read_text(encoding="utf-8"))
        payload["article"] = {"title": "Säilytetty keskeytynyt artikkeli"}
        ready.unlink()
        outbox.parent.mkdir(parents=True, exist_ok=True)
        outbox.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        result = self._run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        remote_payload = json.loads(
            self._git(
                self.worker,
                "--git-dir",
                str(self.origin),
                "show",
                f"main:pipeline/queues/staged/outbox/{packet}",
            ).stdout
        )
        self.assertEqual(remote_payload["article"]["title"], "Säilytetty keskeytynyt artikkeli")
        self.assertEqual(self._git(self.worker, "status", "--porcelain").stdout, "")

    def test_startup_resumes_already_staged_outbox_with_openclaw_trajectory_artifacts(self):
        packet = self._admit_packet("20260801T115839Z_11f340b340.json")
        self._sync_worker()
        ready = self.worker / "pipeline/queues/staged/ready" / packet
        outbox = self.worker / "pipeline/queues/staged/outbox" / packet
        payload = json.loads(ready.read_text(encoding="utf-8"))
        payload["article"] = {"title": "Säilytetty valmis artikkeli"}
        ready.unlink()
        outbox.parent.mkdir(parents=True, exist_ok=True)
        outbox.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self._git(self.worker, "add", str(ready.relative_to(self.worker)))
        self._git(self.worker, "add", "-f", str(outbox.relative_to(self.worker)))

        trajectory_stem = (
            "agent_monica_explicit_"
            "monica-pipeline-1ff46377-0173-409e-8fc5-3c970d99c9c8"
        )
        trajectory = self.worker / f"{trajectory_stem}.trajectory.jsonl"
        trajectory_pointer = self.worker / f"{trajectory_stem}.trajectory-path.json"
        trajectory.write_text(
            json.dumps(
                {
                    "traceSchema": "openclaw-trajectory",
                    "schemaVersion": 1,
                    "source": "runtime",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        trajectory_pointer.write_text(
            json.dumps(
                {
                    "traceSchema": "openclaw-trajectory-pointer",
                    "schemaVersion": 1,
                    "runtimeFile": str(trajectory),
                }
            )
            + "\n",
            encoding="utf-8",
        )

        result = self._run_wrapper(STUB_FAIL="1")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        remote_payload = json.loads(
            self._git(
                self.worker,
                "--git-dir",
                str(self.origin),
                "show",
                f"main:pipeline/queues/staged/outbox/{packet}",
            ).stdout
        )
        self.assertEqual(remote_payload["article"]["title"], "Säilytetty valmis artikkeli")
        self.assertNotIn(f"pipeline/queues/staged/ready/{packet}", self._remote_files())
        self.assertTrue(trajectory.is_file())
        self.assertTrue(trajectory_pointer.is_file())
        untracked = set(
            self._git(self.worker, "ls-files", "--others", "--exclude-standard").stdout.splitlines()
        )
        self.assertEqual(untracked, {trajectory.name, trajectory_pointer.name})

    def test_startup_commits_completed_failed_record_without_regenerating_it(self):
        packet = self._admit_packet("failed-before-commit.json")
        self._sync_worker()
        ready = self.worker / "pipeline/queues/staged/ready" / packet
        failed = self.worker / "pipeline/queues/staged/failed" / packet
        payload = json.loads(ready.read_text(encoding="utf-8"))
        payload["failure"] = "schema_invalid"
        ready.unlink()
        failed.parent.mkdir(parents=True, exist_ok=True)
        failed.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        result = self._run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        remote_payload = json.loads(
            self._git(
                self.worker,
                "--git-dir",
                str(self.origin),
                "show",
                f"main:pipeline/queues/staged/failed/{packet}",
            ).stdout
        )
        self.assertEqual(remote_payload["failure"], "schema_invalid")
        self.assertEqual(self._git(self.worker, "status", "--porcelain").stdout, "")

    def test_concurrent_main_update_is_rebased_and_preserved(self):
        packet = self._admit_packet("concurrent.json")
        result = self._run_wrapper(STUB_CONCURRENT="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        files = self._remote_files()
        self.assertIn("concurrent.txt", files)
        self.assertIn(f"pipeline/queues/staged/outbox/{packet}", files)
        self.assertNotIn(f"pipeline/queues/staged/ready/{packet}", files)
        self.assertEqual(self._git(self.worker, "status", "--porcelain").stdout, "")

    def test_overlapping_invocation_cannot_recover_active_writing_packet(self):
        packet = self._admit_packet("overlap.json")
        marker = self.root / "claimed.marker"
        first = subprocess.Popen(
            ["bash", "pipeline/staged_monica_worker_cron.sh"],
            cwd=self.worker,
            env=self._wrapper_env(
                STUB_CLAIM_MARKER=str(marker),
                STUB_DELAY_AFTER_CLAIM="1.0",
            ),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            for _ in range(100):
                if marker.exists():
                    break
                if first.poll() is not None:
                    self.fail("first worker exited before claiming the packet")
                time.sleep(0.02)
            else:
                self.fail("first worker did not expose its claimed writing packet")

            writing = self.worker / "pipeline/queues/staged/writing" / packet
            self.assertTrue(writing.is_file())
            second = self._run_wrapper()
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("SKIP another transactional Monica worker", second.stdout)
            self.assertIsNone(first.poll())
            self.assertTrue(writing.is_file())

            first_stdout, first_stderr = first.communicate(timeout=10)
            self.assertEqual(first.returncode, 0, first_stderr or first_stdout)
        finally:
            if first.poll() is None:
                first.terminate()
                first.communicate(timeout=5)

        files = self._remote_files()
        self.assertIn(f"pipeline/queues/staged/outbox/{packet}", files)
        self.assertNotIn(f"pipeline/queues/staged/ready/{packet}", files)

    def test_scanner_expiry_race_cannot_push_duplicate_outbox(self):
        packet = self._admit_packet("scanner-race.json")
        result = self._run_wrapper(STUB_CONCURRENT_FAIL_SAME_PACKET="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changed semantics after remote reconciliation", result.stderr)
        files = self._remote_files()
        self.assertIn(f"pipeline/queues/staged/failed/{packet}", files)
        self.assertNotIn(f"pipeline/queues/staged/outbox/{packet}", files)
        self.assertNotIn(f"pipeline/queues/staged/ready/{packet}", files)

    def test_pending_queue_commit_rebases_after_remote_advances(self):
        packet = self._admit_packet("pending-push-retry.json")
        self._sync_worker()
        ready = self.worker / "pipeline/queues/staged/ready" / packet
        outbox = self.worker / "pipeline/queues/staged/outbox" / packet
        payload = json.loads(ready.read_text(encoding="utf-8"))
        payload["article"] = {"title": "Paikallinen jonosiirtymä"}
        ready.unlink()
        outbox.parent.mkdir(parents=True, exist_ok=True)
        outbox.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self._git(self.worker, "add", f"pipeline/queues/staged/ready/{packet}")
        self._git(self.worker, "add", "-f", f"pipeline/queues/staged/outbox/{packet}")
        self._git(
            self.worker,
            "commit",
            "-m",
            f"auto(staged): Monica ready to outbox {packet}",
        )

        self._git(self.seed, "fetch", "origin", "main")
        self._git(self.seed, "reset", "--hard", "origin/main")
        (self.seed / "concurrent-after-local-commit.txt").write_text(
            "preserved\n", encoding="utf-8"
        )
        self._git(self.seed, "add", "concurrent-after-local-commit.txt")
        self._git(self.seed, "commit", "-m", "remote advances after local queue commit")
        self._git(self.seed, "push", "origin", "main")

        result = self._run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        files = self._remote_files()
        self.assertIn("concurrent-after-local-commit.txt", files)
        self.assertIn(f"pipeline/queues/staged/outbox/{packet}", files)
        self.assertNotIn(f"pipeline/queues/staged/ready/{packet}", files)
        self.assertEqual(self._git(self.worker, "status", "--porcelain").stdout, "")

    def test_partial_pending_queue_commit_is_rejected_without_remote_data_loss(self):
        packet = self._admit_packet("partial-pending.json")
        self._sync_worker()
        ready = self.worker / "pipeline/queues/staged/ready" / packet
        ready.unlink()
        self._git(self.worker, "add", f"pipeline/queues/staged/ready/{packet}")
        self._git(
            self.worker,
            "commit",
            "-m",
            f"auto(staged): Monica ready to outbox {packet}",
        )

        result = self._run_wrapper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("diverged outside a validated queue-only retry", result.stderr)
        files = self._remote_files()
        self.assertIn(f"pipeline/queues/staged/ready/{packet}", files)
        self.assertNotIn(f"pipeline/queues/staged/outbox/{packet}", files)

    def test_duplicate_ready_and_outbox_is_rejected_before_dispatch(self):
        packet = self._admit_packet("duplicate-destination.json")
        self._sync_worker()
        ready = self.worker / "pipeline/queues/staged/ready" / packet
        outbox = self.worker / "pipeline/queues/staged/outbox" / packet
        outbox.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ready, outbox)

        result = self._run_wrapper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already has an outbox destination", result.stderr)
        files = self._remote_files()
        self.assertIn(f"pipeline/queues/staged/ready/{packet}", files)
        self.assertNotIn(f"pipeline/queues/staged/outbox/{packet}", files)

    def test_resume_cannot_overwrite_destination_already_tracked_in_head(self):
        packet = self._admit_packet("tracked-destination.json")
        self._git(self.seed, "fetch", "origin", "main")
        self._git(self.seed, "reset", "--hard", "origin/main")
        remote_outbox = self.seed / "pipeline/queues/staged/outbox" / packet
        remote_outbox.parent.mkdir(parents=True, exist_ok=True)
        remote_outbox.write_text(
            json.dumps({"packet_id": packet, "article": {"title": "Alkuperäinen"}}),
            encoding="utf-8",
        )
        self._git(self.seed, "add", "-f", str(remote_outbox.relative_to(self.seed)))
        self._git(self.seed, "commit", "-m", "fixture tracked duplicate destination")
        self._git(self.seed, "push", "origin", "main")
        self._sync_worker()

        ready = self.worker / "pipeline/queues/staged/ready" / packet
        local_outbox = self.worker / "pipeline/queues/staged/outbox" / packet
        ready.unlink()
        local_outbox.write_text(
            json.dumps({"packet_id": packet, "article": {"title": "Ei saa korvata"}}),
            encoding="utf-8",
        )

        result = self._run_wrapper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exact ready deletion plus destination addition", result.stderr)
        remote_payload = json.loads(
            self._git(
                self.worker,
                "--git-dir",
                str(self.origin),
                "show",
                f"main:pipeline/queues/staged/outbox/{packet}",
            ).stdout
        )
        self.assertEqual(remote_payload["article"]["title"], "Alkuperäinen")
        self.assertIn(f"pipeline/queues/staged/ready/{packet}", self._remote_files())

    def test_dirty_worktree_is_rejected_before_remote_sync(self):
        self._admit_packet("dirty.json")
        (self.worker / "README.md").write_text("dirty\n", encoding="utf-8")
        result = self._run_wrapper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("worktree is not clean", result.stderr)
        files = self._remote_files()
        self.assertIn("pipeline/queues/staged/ready/dirty.json", files)
        self.assertNotIn("pipeline/queues/staged/outbox/dirty.json", files)


if __name__ == "__main__":
    unittest.main()
