#!/usr/bin/env python3
"""Replay-safe host watchdog for missed staged scan and publish schedules."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import tempfile
from typing import Any
import urllib.error
import urllib.request


ACTIVE_STATUSES = {"queued", "in_progress"}
GRACE = timedelta(minutes=20)
LANES = {
    "scan": {
        "event_type": "staged_scan_recovery",
        "workflow": "staged-scan.yml",
        "minutes": (1, 16, 31, 46),
        "marker": "pipeline/actions-scan.enabled",
    },
    "publish": {
        "event_type": "staged_publish_recovery",
        "workflow": "staged-publish.yml",
        "minutes": (13, 28, 43, 58),
        "marker": "pipeline/actions-publish.enabled",
    },
}
SCHEMA = "uutistenlukija.staged_pipeline_watchdog.v2"


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)


def _due_boundary(now: datetime, minutes: tuple[int, ...]) -> datetime:
    cutoff = now - GRACE
    candidates = [cutoff.replace(minute=minute, second=0, microsecond=0) for minute in minutes]
    eligible = [candidate for candidate in candidates if candidate <= cutoff]
    if eligible:
        return max(eligible)
    previous = cutoff - timedelta(hours=1)
    return previous.replace(minute=max(minutes), second=0, microsecond=0)


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": SCHEMA, "requests": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA or not isinstance(data.get("requests"), dict):
        raise ValueError("invalid watchdog state")
    return data


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.chmod(temporary, 0o600)
    temporary.replace(path)


@contextmanager
def _state_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    os.chmod(lock, 0o600)
    acquired = False
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _result(lane: str, boundary: str, sha: str, counts: dict[str, int], decision: str, reason: str, dispatch_count: int = 0) -> dict[str, Any]:
    return {
        "decision": decision,
        "lane": lane,
        "due_boundary": boundary,
        "expected_sha": sha,
        "queue_counts": counts,
        "dispatch_count": dispatch_count,
        "reason": reason,
    }


def decide_and_dispatch(api: Any, *, repository: str, lane: str, state_path: Path, now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    config = LANES.get(lane)
    boundary_dt = _due_boundary(now, config["minutes"] if config else (0,))
    boundary = boundary_dt.isoformat()
    sha = ""
    counts = {"ready": 0, "writing": 0, "outbox": 0}
    if config is None:
        return _result(lane, boundary, sha, counts, "fail_closed", "unsupported_lane")
    try:
        repo = api.repository(repository)
        if str(repo["default_branch"]) != "main":
            return _result(lane, boundary, sha, counts, "fail_closed", "default_branch_not_main")
        sha = str(api.branch(repository, "main")["commit"]["sha"])
        workflow = api.workflow(repository, config["workflow"])
        if workflow.get("state") != "active":
            return _result(lane, boundary, sha, counts, "no_dispatch", "workflow_inactive")
        workflow_id = str(workflow["id"])
        runs = []
        for event in ("schedule", "repository_dispatch", "workflow_dispatch", "push"):
            runs.extend(api.runs(repository, workflow_id, event))
        if any(str(run.get("status")) in ACTIVE_STATUSES for run in runs):
            return _result(lane, boundary, sha, counts, "no_dispatch", "matching_run_active")
        if any(_utc(str(run["created_at"])) >= boundary_dt for run in runs):
            return _result(lane, boundary, sha, counts, "no_dispatch", "fresh")

        tree = api.tree(repository, sha)
        if not isinstance(tree, list):
            raise ValueError("invalid tree")
        paths = [str(entry["path"]) for entry in tree if entry.get("type") == "blob"]
        if config["marker"] not in paths:
            return _result(lane, boundary, sha, counts, "no_dispatch", "missing_marker")
        for queue in counts:
            prefix = f"pipeline/queues/staged/{queue}/"
            counts[queue] = sum(path.startswith(prefix) and path.endswith(".json") for path in paths)
        if lane == "scan" and any(counts.values()):
            return _result(lane, boundary, sha, counts, "no_dispatch", "scan_backpressure")
        if lane == "publish" and counts["writing"]:
            return _result(lane, boundary, sha, counts, "no_dispatch", "publish_writing_active")
        if lane == "publish" and not counts["outbox"]:
            return _result(lane, boundary, sha, counts, "no_dispatch", "publish_outbox_empty")

        # Resolve main immediately before taking the lock and mutating durable request state.
        current_sha = str(api.branch(repository, "main")["commit"]["sha"])
        if current_sha != sha:
            return _result(lane, boundary, sha, counts, "fail_closed", "main_moved")
        key = "|".join((repository, lane, workflow_id, boundary))
        with _state_lock(state_path):
            state = _load_state(state_path)
            if key in state["requests"]:
                prior = state["requests"][key]
                status = prior.get("status") if isinstance(prior, dict) else "invalid"
                return _result(lane, boundary, sha, counts, "no_dispatch", f"prior_{status}")
            state["requests"][key] = {
                "status": "pending", "requested_at": now.isoformat(), "event_type": config["event_type"],
                "expected_main_sha": sha,
            }
            _write_state(state_path, state)
            payload = {"lane": lane, "due_boundary": boundary, "expected_main_sha": sha}
            try:
                status = api.dispatch(repository, config["event_type"], payload)
            except Exception:
                state["requests"][key]["status"] = "ambiguous"
                _write_state(state_path, state)
                raise
            if not 200 <= status < 300:
                state["requests"][key]["status"] = "ambiguous"
                _write_state(state_path, state)
                return _result(lane, boundary, sha, counts, "fail_closed", "ambiguous_dispatch")
            state["requests"][key]["status"] = "accepted"
            _write_state(state_path, state)
            return _result(lane, boundary, sha, counts, "dispatched", "stale_dispatched", 1)
    except Exception as exc:
        return _result(lane, boundary, sha, counts, "fail_closed", f"fail_closed:{exc.__class__.__name__}")


class GitHubAPI:
    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("GITHUB_TOKEN missing")
        self.token = token

    def _request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request("https://api.github.com" + path, data=data, method=method, headers={
            "Accept": "application/vnd.github+json", "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "uutistenlukija-staged-pipeline-watchdog/2",
        })
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read()
                return response.status, json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            return exc.code, None

    def repository(self, repository: str) -> dict:
        status, data = self._request("GET", f"/repos/{repository}")
        if status != 200 or not isinstance(data, dict): raise RuntimeError("repository read failed")
        return data

    def branch(self, repository: str, branch: str) -> dict:
        status, data = self._request("GET", f"/repos/{repository}/branches/{branch}")
        if status != 200 or not isinstance(data, dict): raise RuntimeError("branch read failed")
        return data

    def workflow(self, repository: str, workflow: str) -> dict:
        status, data = self._request("GET", f"/repos/{repository}/actions/workflows/{workflow}")
        if status != 200 or not isinstance(data, dict): raise RuntimeError("workflow read failed")
        return data

    def runs(self, repository: str, workflow: str, event: str) -> list[dict]:
        status, data = self._request("GET", f"/repos/{repository}/actions/workflows/{workflow}/runs?event={event}&per_page=10")
        if status != 200 or not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list): raise RuntimeError("runs read failed")
        return data["workflow_runs"]

    def tree(self, repository: str, sha: str) -> list[dict]:
        status, data = self._request("GET", f"/repos/{repository}/git/trees/{sha}?recursive=1")
        if status != 200 or not isinstance(data, dict) or data.get("truncated") or not isinstance(data.get("tree"), list): raise RuntimeError("tree read failed")
        return data["tree"]

    def dispatch(self, repository: str, event_type: str, client_payload: dict[str, str]) -> int:
        status, _ = self._request("POST", f"/repos/{repository}/dispatches", {"event_type": event_type, "client_payload": client_payload})
        return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--lane", choices=sorted(LANES), required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = decide_and_dispatch(GitHubAPI(os.environ.get("GITHUB_TOKEN", "")), repository=args.repository, lane=args.lane, state_path=args.state)
    except Exception as exc:
        result = _result(args.lane, "", "", {"ready": 0, "writing": 0, "outbox": 0}, "fail_closed", f"fail_closed:{exc.__class__.__name__}")
    print(json.dumps(result, sort_keys=True))
    return 1 if result["decision"] == "fail_closed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
