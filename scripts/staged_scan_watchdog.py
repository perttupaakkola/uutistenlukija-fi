#!/usr/bin/env python3
"""Fail-closed host watchdog for the existing staged_scan_recovery dispatch."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import fcntl
import os
from pathlib import Path
import tempfile
from typing import Any
import urllib.error
import urllib.request


EVENT_TYPE = "staged_scan_recovery"
FRESHNESS_MINUTES = 35
ACTIVE_STATUSES = {"queued", "in_progress"}


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)


def _boundary(now: datetime) -> str:
    minute = (now.minute // 15) * 15
    return now.replace(minute=minute, second=0, microsecond=0).isoformat()


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": "uutistenlukija.staged_scan_watchdog.v1", "requests": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "uutistenlukija.staged_scan_watchdog.v1" or not isinstance(data.get("requests"), dict):
        raise ValueError("invalid watchdog state")
    return data


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


@contextmanager
def _state_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def decide_and_dispatch(
    api: Any,
    *,
    repository: str,
    workflow_name: str,
    state_path: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    result = {"dispatch_count": 0, "outcome": "fail_closed", "reason": "fail_closed"}
    try:
        repo = api.repository(repository)
        default_branch = str(repo["default_branch"])
        main_sha = str(api.branch(repository, default_branch)["commit"]["sha"])
        workflow = api.workflow(repository, workflow_name)
        if workflow.get("state") != "active":
            return {**result, "reason": "workflow_inactive"}
        workflow_id = str(workflow["id"])
        freshness_runs = [
            *api.runs(repository, workflow_id, "schedule"),
            *api.runs(repository, workflow_id, "repository_dispatch"),
        ]
        manual_runs = api.runs(repository, workflow_id, "workflow_dispatch")
        if any(str(run.get("status")) in ACTIVE_STATUSES for run in [*freshness_runs, *manual_runs]):
            return {**result, "outcome": "no_dispatch", "reason": "matching_run_active"}
        created = sorted((_utc(str(run["created_at"])) for run in freshness_runs), reverse=True)
        if created and (now - created[0]).total_seconds() < FRESHNESS_MINUTES * 60:
            return {**result, "outcome": "no_dispatch", "reason": "fresh"}
        key = "|".join((repository, workflow_id, _boundary(now), main_sha))
        with _state_lock(state_path):
            state = _load_state(state_path)
            if key in state["requests"]:
                prior = state["requests"][key]
                status = prior.get("status") if isinstance(prior, dict) else None
                if status == "accepted":
                    return {**result, "outcome": "no_dispatch", "reason": "accepted_replay"}
                return {**result, "reason": f"prior_{status or 'invalid'}"}
            state["requests"][key] = {
                "status": "pending",
                "requested_at": now.isoformat(),
                "event_type": EVENT_TYPE,
            }
            _write_state(state_path, state)
            try:
                dispatch_status = api.dispatch(repository, EVENT_TYPE)
            except Exception:
                state["requests"][key]["status"] = "ambiguous"
                state["requests"][key]["resolved_at"] = now.isoformat()
                _write_state(state_path, state)
                raise
            if dispatch_status != 204:
                state["requests"][key]["status"] = "ambiguous"
                state["requests"][key]["resolved_at"] = now.isoformat()
                _write_state(state_path, state)
                return {**result, "reason": "ambiguous_dispatch"}
            state["requests"][key]["status"] = "accepted"
            state["requests"][key]["resolved_at"] = now.isoformat()
            _write_state(state_path, state)
            return {"dispatch_count": 1, "outcome": "dispatched", "reason": "stale_dispatched"}
    except Exception as exc:
        return {**result, "reason": f"fail_closed:{exc.__class__.__name__}"}


class GitHubAPI:
    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("GITHUB_TOKEN missing")
        self.token = token

    def _request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            "https://api.github.com" + path,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "uutistenlukija-staged-scan-watchdog/1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read()
                return response.status, json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"GitHub API HTTP {exc.code}") from exc

    def repository(self, repository: str) -> dict:
        status, data = self._request("GET", f"/repos/{repository}")
        if status != 200 or not isinstance(data, dict):
            raise RuntimeError("repository read failed")
        return data

    def branch(self, repository: str, branch: str) -> dict:
        status, data = self._request("GET", f"/repos/{repository}/branches/{branch}")
        if status != 200 or not isinstance(data, dict):
            raise RuntimeError("branch read failed")
        return data

    def workflow(self, repository: str, workflow: str) -> dict:
        status, data = self._request("GET", f"/repos/{repository}/actions/workflows/{workflow}")
        if status != 200 or not isinstance(data, dict):
            raise RuntimeError("workflow read failed")
        return data

    def runs(self, repository: str, workflow: str, event: str) -> list[dict]:
        status, data = self._request(
            "GET", f"/repos/{repository}/actions/workflows/{workflow}/runs?event={event}&per_page=10"
        )
        if status != 200 or not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
            raise RuntimeError("runs read failed")
        return data["workflow_runs"]

    def dispatch(self, repository: str, event_type: str) -> int:
        status, _ = self._request(
            "POST", f"/repos/{repository}/dispatches", {"event_type": event_type}
        )
        return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--workflow", default="staged-scan.yml")
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    try:
        api = GitHubAPI(os.environ.get("GITHUB_TOKEN", ""))
        result = decide_and_dispatch(
            api,
            repository=args.repository,
            workflow_name=args.workflow,
            state_path=args.state,
        )
    except Exception as exc:
        result = {"dispatch_count": 0, "outcome": "fail_closed", "reason": f"fail_closed:{exc.__class__.__name__}"}
    print(json.dumps(result, sort_keys=True))
    return 1 if result.get("outcome") == "fail_closed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
