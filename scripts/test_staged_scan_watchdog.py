from datetime import datetime, timedelta, timezone
from pathlib import Path
import fcntl
import json
import os
import tempfile
import unittest
from unittest import mock

from scripts import staged_scan_watchdog
from scripts.staged_scan_watchdog import decide_and_dispatch


NOW = datetime(2026, 8, 29, 16, 47, tzinfo=timezone.utc)


class FakeAPI:
    def __init__(self, *, age_minutes=60, active=False, manual_active=False, workflow_state="active", dispatch_status=204, fail_at=""):
        self.age_minutes = age_minutes
        self.active = active
        self.manual_active = manual_active
        self.workflow_state = workflow_state
        self.dispatch_status = dispatch_status
        self.fail_at = fail_at
        self.dispatches = []

    def _fail(self, name):
        if self.fail_at == name:
            raise ValueError(name)

    def repository(self, repository):
        self._fail("repository")
        return {"default_branch": "main"}

    def branch(self, repository, branch):
        self._fail("branch")
        return {"commit": {"sha": "a" * 40}}

    def workflow(self, repository, workflow):
        self._fail("workflow")
        return {"id": 123, "state": self.workflow_state}

    def runs(self, repository, workflow, event):
        self._fail("runs")
        if event == "repository_dispatch":
            return []
        if event == "workflow_dispatch":
            return [{
                "status": "in_progress" if self.manual_active else "completed",
                "created_at": (NOW - timedelta(minutes=1)).isoformat(),
            }]
        return [{
            "status": "queued" if self.active else "completed",
            "created_at": (NOW - timedelta(minutes=self.age_minutes)).isoformat(),
        }]

    def dispatch(self, repository, event_type):
        self._fail("dispatch")
        self.dispatches.append(event_type)
        return self.dispatch_status


class WatchdogTests(unittest.TestCase):
    def decide(self, api, path):
        return decide_and_dispatch(
            api,
            repository="owner/repo",
            workflow_name="staged-scan.yml",
            state_path=path,
            now=NOW,
        )

    def test_fresh_and_active_dispatch_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            for api, reason in ((FakeAPI(age_minutes=34), "fresh"), (FakeAPI(active=True), "matching_run_active")):
                result = self.decide(api, Path(tmp) / reason)
                self.assertEqual(result, {"dispatch_count": 0, "outcome": "no_dispatch", "reason": reason})

    def test_active_manual_suppresses_but_completed_manual_does_not_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            active = self.decide(FakeAPI(manual_active=True), Path(tmp) / "active.json")
            self.assertEqual(active["reason"], "matching_run_active")
            completed = self.decide(FakeAPI(), Path(tmp) / "completed.json")
            self.assertEqual(completed["dispatch_count"], 1)

    def test_stale_unused_key_dispatches_once_and_replay_is_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            api = FakeAPI()
            self.assertEqual(self.decide(api, path)["dispatch_count"], 1)
            self.assertEqual(self.decide(api, path), {"dispatch_count": 0, "outcome": "no_dispatch", "reason": "accepted_replay"})
            self.assertEqual(api.dispatches, ["staged_scan_recovery"])

    def test_ambiguous_dispatch_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            api = FakeAPI(dispatch_status=202)
            self.assertEqual(self.decide(api, path), {"dispatch_count": 0, "outcome": "fail_closed", "reason": "ambiguous_dispatch"})
            replay = self.decide(api, path)
            self.assertEqual(replay["outcome"], "fail_closed")
            self.assertEqual(replay["reason"], "prior_ambiguous")

    def test_dispatch_exception_persists_ambiguous_and_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            api = FakeAPI(fail_at="dispatch")
            first = self.decide(api, path)
            self.assertEqual(first["outcome"], "fail_closed")
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(next(iter(state["requests"].values()))["status"], "ambiguous")
            api.fail_at = ""
            replay = self.decide(api, path)
            self.assertEqual(replay["outcome"], "fail_closed")
            self.assertEqual(replay["reason"], "prior_ambiguous")
            self.assertEqual(api.dispatches, [])

    def test_inactive_and_all_api_or_state_failures_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(self.decide(FakeAPI(workflow_state="disabled"), root / "inactive")["dispatch_count"], 0)
            for name in ("repository", "branch", "workflow", "runs", "dispatch"):
                with self.subTest(name=name):
                    self.assertEqual(self.decide(FakeAPI(fail_at=name), root / name)["dispatch_count"], 0)
            malformed = root / "malformed"
            malformed.write_text("{}", encoding="utf-8")
            self.assertEqual(self.decide(FakeAPI(), malformed)["dispatch_count"], 0)

    def test_orphan_lockfile_is_crash_recoverable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.with_suffix(".json.lock").write_text("orphan", encoding="utf-8")
            result = self.decide(FakeAPI(), path)
            self.assertEqual(result["dispatch_count"], 1)
            self.assertEqual(result["outcome"], "dispatched")

    def test_contended_lock_fails_closed_then_dispatches_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            lock = path.with_suffix(".json.lock")
            descriptor = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            api = FakeAPI()
            try:
                blocked = self.decide(api, path)
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
            self.assertEqual(blocked["dispatch_count"], 0)
            self.assertEqual(blocked["outcome"], "fail_closed")
            self.assertEqual(self.decide(api, path)["dispatch_count"], 1)
            self.assertEqual(api.dispatches, ["staged_scan_recovery"])

    def test_crash_after_pending_remains_fail_closed_without_retry(self):
        class CrashAPI(FakeAPI):
            def dispatch(self, repository, event_type):
                self.dispatches.append(event_type)
                raise KeyboardInterrupt("simulated crash")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            api = CrashAPI()
            with self.assertRaises(KeyboardInterrupt):
                self.decide(api, path)
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(next(iter(state["requests"].values()))["status"], "pending")
            replay = self.decide(api, path)
            self.assertEqual(replay["outcome"], "fail_closed")
            self.assertEqual(replay["reason"], "prior_pending")
            self.assertEqual(api.dispatches, ["staged_scan_recovery"])

    def test_legacy_requested_state_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            api = FakeAPI()
            self.assertEqual(self.decide(api, path)["dispatch_count"], 1)
            state = json.loads(path.read_text(encoding="utf-8"))
            next(iter(state["requests"].values()))["status"] = "requested"
            path.write_text(json.dumps(state), encoding="utf-8")
            result = self.decide(api, path)
            self.assertEqual(result["outcome"], "fail_closed")
            self.assertEqual(result["reason"], "prior_requested")
            self.assertEqual(api.dispatches, ["staged_scan_recovery"])

    def test_main_exit_codes_distinguish_fail_closed_from_healthy_results(self):
        cases = (
            ({"dispatch_count": 0, "outcome": "fail_closed", "reason": "missing_token"}, 1),
            ({"dispatch_count": 0, "outcome": "fail_closed", "reason": "api_failure"}, 1),
            ({"dispatch_count": 0, "outcome": "fail_closed", "reason": "ambiguous_dispatch"}, 1),
            ({"dispatch_count": 0, "outcome": "fail_closed", "reason": "prior_pending"}, 1),
            ({"dispatch_count": 0, "outcome": "no_dispatch", "reason": "fresh"}, 0),
            ({"dispatch_count": 0, "outcome": "no_dispatch", "reason": "matching_run_active"}, 0),
            ({"dispatch_count": 0, "outcome": "no_dispatch", "reason": "accepted_replay"}, 0),
            ({"dispatch_count": 1, "outcome": "dispatched", "reason": "stale_dispatched"}, 0),
        )
        for result, expected in cases:
            with self.subTest(reason=result["reason"]), tempfile.TemporaryDirectory() as tmp, \
                 mock.patch.object(staged_scan_watchdog, "GitHubAPI"), \
                 mock.patch.object(staged_scan_watchdog, "decide_and_dispatch", return_value=result), \
                 mock.patch("sys.argv", ["watchdog", "--state", str(Path(tmp) / "state.json")]), \
                 mock.patch("builtins.print"):
                self.assertEqual(staged_scan_watchdog.main(), expected)

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("sys.argv", ["watchdog", "--state", str(Path(tmp) / "state.json")]), \
             mock.patch("builtins.print"):
            self.assertEqual(staged_scan_watchdog.main(), 1)


if __name__ == "__main__":
    unittest.main()
