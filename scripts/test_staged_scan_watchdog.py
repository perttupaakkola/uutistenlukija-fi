from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts.staged_scan_watchdog import decide_and_dispatch, decide_combined, main


NOW = datetime(2026, 8, 29, 16, 47, tzinfo=timezone.utc)


class FakeAPI:
    def __init__(self, *, lane="scan", age=60, active_event="", marker=True, ready=0, writing=0, outbox=0, status=204, workflow_state="active", fail_at="", move_main=False, terminal_push_status="completed", push_age=None):
        self.lane, self.age, self.active_event, self.marker = lane, age, active_event, marker
        self.counts = {"ready": ready, "writing": writing, "outbox": outbox}
        self.status, self.workflow_state, self.fail_at, self.move_main = status, workflow_state, fail_at, move_main
        self.dispatches, self.branch_calls = [], 0
        self.terminal_push_status = terminal_push_status
        self.push_age = age if push_age is None else push_age

    def _fail(self, name):
        if self.fail_at == name: raise ValueError(name)

    def repository(self, repository): self._fail("repository"); return {"default_branch": "main"}
    def branch(self, repository, branch):
        self._fail("branch"); self.branch_calls += 1
        return {"commit": {"sha": ("b" if self.move_main and self.branch_calls > 1 else "a") * 40}}
    def workflow(self, repository, workflow): self._fail("workflow"); return {"id": 123, "state": self.workflow_state}
    def runs(self, repository, workflow, event):
        self._fail("runs")
        status = "queued" if event == self.active_event else (self.terminal_push_status if event == "push" else "completed")
        age = self.push_age if event == "push" else self.age
        return [{"status": status, "created_at": (NOW - timedelta(minutes=age)).isoformat()}]
    def tree(self, repository, sha):
        self._fail("tree")
        marker = f"pipeline/actions-{self.lane}.enabled"
        paths = [marker] if self.marker else []
        for queue, count in self.counts.items():
            paths.extend(f"pipeline/queues/staged/{queue}/{i}.json" for i in range(count))
        return [{"path": path, "type": "blob"} for path in paths]
    def dispatch(self, repository, event_type, payload):
        self._fail("dispatch"); self.dispatches.append((event_type, payload)); return self.status


class WatchdogTests(unittest.TestCase):
    def decide(self, api, path, lane=None, now=NOW):
        return decide_and_dispatch(api, repository="owner/repo", lane=lane or api.lane, state_path=path, now=now)

    def test_lane_boundaries_payload_and_zero_one_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            for lane, due, event in (("scan", "2026-08-29T16:16:00+00:00", "staged_scan_recovery"), ("publish", "2026-08-29T16:13:00+00:00", "staged_publish_recovery")):
                api = FakeAPI(lane=lane, outbox=1 if lane == "publish" else 0)
                result = self.decide(api, Path(tmp) / f"{lane}.json")
                self.assertEqual(result["dispatch_count"], 1)
                self.assertEqual(result["due_boundary"], due)
                self.assertEqual(api.dispatches, [(event, {"lane": lane, "due_boundary": due, "expected_main_sha": "a" * 40})])

    def test_fresh_inactive_missing_marker_and_malformed_api_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = ((FakeAPI(age=10), "fresh"), (FakeAPI(workflow_state="disabled"), "workflow_inactive"), (FakeAPI(marker=False), "missing_marker"))
            for index, (api, reason) in enumerate(cases):
                self.assertEqual(self.decide(api, root / str(index))["reason"], reason)
            for name in ("repository", "branch", "workflow", "runs", "tree"):
                self.assertEqual(self.decide(FakeAPI(fail_at=name), root / name)["decision"], "fail_closed")
            malformed = root / "malformed"; malformed.write_text("{}", encoding="utf-8")
            self.assertEqual(self.decide(FakeAPI(), malformed)["decision"], "fail_closed")

    def test_all_active_event_types_suppress(self):
        with tempfile.TemporaryDirectory() as tmp:
            for event in ("schedule", "repository_dispatch", "workflow_dispatch", "push"):
                self.assertEqual(self.decide(FakeAPI(active_event=event), Path(tmp) / event)["reason"], "matching_run_active")

    def test_scan_backpressure_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            for ready, writing, outbox in ((1,0,0),(0,1,0),(0,0,1),(1,1,1)):
                result = self.decide(FakeAPI(ready=ready, writing=writing, outbox=outbox), Path(tmp) / f"{ready}{writing}{outbox}")
                self.assertEqual(result["reason"], "scan_backpressure")
                self.assertEqual(result["queue_counts"], {"ready": ready, "writing": writing, "outbox": outbox})

    def test_publish_requires_outbox_and_no_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(self.decide(FakeAPI(lane="publish"), root / "zero")["reason"], "publish_outbox_empty")
            self.assertEqual(self.decide(FakeAPI(lane="publish", writing=1, outbox=1), root / "writing")["reason"], "publish_writing_active")
            self.assertEqual(self.decide(FakeAPI(lane="publish", outbox=1), root / "one")["dispatch_count"], 1)

    def test_terminal_push_does_not_suppress_publish_but_active_push_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for status in ("completed", "failure"):
                api = FakeAPI(lane="publish", age=60, push_age=1, outbox=1, terminal_push_status=status)
                self.assertEqual(self.decide(api, root / status)["dispatch_count"], 1)
            active = self.decide(
                FakeAPI(lane="publish", age=60, push_age=1, outbox=1, active_event="push"),
                root / "active",
            )
            self.assertEqual(active["reason"], "matching_run_active")
            self.assertEqual(active["dispatch_count"], 0)
            empty = self.decide(
                FakeAPI(lane="publish", age=60, push_age=1, outbox=0), root / "empty"
            )
            self.assertEqual(empty["reason"], "publish_outbox_empty")

    def test_combined_is_publish_first_then_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            publish = FakeAPI(lane="publish", outbox=1)
            result = decide_combined(
                publish, repository="owner/repo", state_path=root / "publish.json", now=NOW
            )
            self.assertEqual(result["lane"], "publish")
            self.assertEqual(result["dispatch_count"], 1)

            scan = FakeAPI(lane="scan")
            result = decide_combined(
                scan, repository="owner/repo", state_path=root / "scan.json", now=NOW
            )
            self.assertEqual(result["lane"], "scan")
            self.assertEqual(result["dispatch_count"], 1)

    def test_combined_does_not_scan_with_ready_or_writing_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for queue in ("ready", "writing"):
                counts = {queue: 1}
                api = FakeAPI(lane="publish", **counts)
                result = decide_combined(
                    api, repository="owner/repo", state_path=root / f"{queue}.json", now=NOW
                )
                self.assertEqual(result["lane"], "publish")
                self.assertEqual(result["dispatch_count"], 0)
                self.assertEqual(result["queue_counts"][queue], 1)
                self.assertEqual(api.dispatches, [])

    def test_cli_without_lane_uses_combined_path(self):
        result = {
            "decision": "no_dispatch", "lane": "scan", "due_boundary": "",
            "expected_sha": "", "queue_counts": {"ready": 0, "writing": 0, "outbox": 0},
            "dispatch_count": 0, "reason": "fresh",
        }
        with mock.patch("scripts.staged_scan_watchdog.GitHubAPI"), mock.patch(
            "scripts.staged_scan_watchdog.decide_combined", return_value=result
        ) as combined, mock.patch("sys.argv", ["watchdog", "--state", "/tmp/watchdog-test-state"]):
            self.assertEqual(main(), 0)
            combined.assert_called_once()

    def test_same_window_sha_change_dedupes_but_next_window_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            first = FakeAPI(); self.assertEqual(self.decide(first, path)["dispatch_count"], 1)
            changed = FakeAPI(); changed.branch = lambda repository, branch: {"commit": {"sha": "c" * 40}}
            self.assertEqual(self.decide(changed, path)["reason"], "prior_accepted")
            later = NOW + timedelta(minutes=15)
            self.assertEqual(self.decide(FakeAPI(), path, now=later)["dispatch_count"], 1)

    def test_lock_crash_timeout_non_2xx_and_replays_are_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock_path = root / "locked.json"; lock = lock_path.with_suffix(".json.lock")
            descriptor = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600); fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try: self.assertEqual(self.decide(FakeAPI(), lock_path)["dispatch_count"], 0)
            finally: fcntl.flock(descriptor, fcntl.LOCK_UN); os.close(descriptor)
            for label, api in (("non2xx", FakeAPI(status=500)), ("timeout", FakeAPI(fail_at="dispatch"))):
                path = root / f"{label}.json"
                self.assertEqual(self.decide(api, path)["dispatch_count"], 0)
                api.fail_at = ""; api.status = 204
                replay = self.decide(api, path)
                self.assertEqual(replay["dispatch_count"], 0)
                self.assertEqual(replay["reason"], "prior_ambiguous")

            class Crash(FakeAPI):
                def dispatch(self, *args): raise KeyboardInterrupt()
            path = root / "crash.json"
            with self.assertRaises(KeyboardInterrupt): self.decide(Crash(), path)
            self.assertEqual(self.decide(FakeAPI(), path)["reason"], "prior_pending")

    def test_main_mismatch_rejected_before_state_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            result = self.decide(FakeAPI(move_main=True), path)
            self.assertEqual(result["reason"], "main_moved")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
