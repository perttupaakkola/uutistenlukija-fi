"""
service_health.py — Tracks external service availability with exponential backoff.

Schema (service_health.json):
{
  "kie_api": {
    "status": "down",           # "up" | "down" | "probe"
    "last_success": null,       # ISO-8601 or null
    "last_failure": "2026-...", # ISO-8601 or null
    "consecutive_failures": 47,
    "skip_until": "2026-..."   # ISO-8601 or null — None when status is "up"
  }
}

Backoff schedule (consecutive failures → skip duration):
  < 3   : no skip (normal operation)
  3–5   : 30 minutes
  6–9   : 2 hours
  10+   : 12 hours
  cap   : 24 hours

Recovery: when skip_until expires, status is set to "probe" — ONE request is
allowed through. Success → reset. Failure → next backoff tier.

Discord alerts fire on:
  - Service goes to "down" (consecutive_failures reaches 3)
  - Service recovers ("up" after "down"/"probe")
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

# ── Config ──────────────────────────────────────────────────────────────────

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
HEALTH_FILE = os.path.join(_PIPELINE_DIR, "service_health.json")

BACKOFF_SCHEDULE = [
    (3,  30 * 60),       # 3+ failures  → 30 min
    (6,  2 * 3600),      # 6+ failures  → 2 h
    (10, 12 * 3600),     # 10+ failures → 12 h
]
MAX_SKIP_SECS = 24 * 3600   # hard cap: 24 h

KNOWN_SERVICES = ("kie_api", "unsplash", "pexels")

# ── Persistence ─────────────────────────────────────────────────────────────

def _load() -> dict:
    if os.path.exists(HEALTH_FILE):
        try:
            with open(HEALTH_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save(data: dict) -> None:
    try:
        with open(HEALTH_FILE, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except OSError as e:
        print(f"[service_health] WARNING: could not write {HEALTH_FILE}: {e}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_entry() -> dict:
    return {
        "status": "up",
        "last_success": None,
        "last_failure": None,
        "consecutive_failures": 0,
        "skip_until": None,
    }

# ── Backoff calculation ──────────────────────────────────────────────────────

def _backoff_secs(consecutive_failures: int) -> int:
    """Return skip duration in seconds for the given failure count, 0 if none."""
    result = 0
    for threshold, secs in BACKOFF_SCHEDULE:
        if consecutive_failures >= threshold:
            result = secs
    return min(result, MAX_SKIP_SECS)


# ── Discord notification ─────────────────────────────────────────────────────

def _notify(msg: str) -> None:
    """Best-effort Discord alert to #operations webhook."""
    try:
        import urllib.request
        webhook = os.environ.get("DISCORD_PIPELINE_WEBHOOK", "")
        if not webhook:
            return
        payload = json.dumps({"content": msg}).encode()
        req = urllib.request.Request(
            webhook, data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "Hermes-Uutistenlukija/1.0"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass  # never block pipeline on notification failure


# ── Public API ───────────────────────────────────────────────────────────────

def should_skip(service: str) -> tuple[bool, Optional[str]]:
    """
    Check if a service should be skipped.

    Returns (skip: bool, reason: str | None).
      skip=False, reason=None      → proceed normally
      skip=False, reason="probe"   → skip window expired; send ONE probe request
      skip=True,  reason=str       → skip, reason describes when to retry
    """
    data = _load()
    entry = data.get(service, _default_entry())
    now = datetime.now(timezone.utc)

    skip_until_str = entry.get("skip_until")
    if not skip_until_str:
        return False, None

    try:
        skip_until = datetime.fromisoformat(skip_until_str)
    except ValueError:
        return False, None

    if now < skip_until:
        retry_at = skip_until.strftime("%H:%M UTC")
        failures = entry.get("consecutive_failures", 0)
        last_fail = entry.get("last_failure", "?")
        return True, f"down since {last_fail} ({failures} failures), retry at {retry_at}"
    else:
        # Window expired — set status to "probe" and allow one request through
        entry["status"] = "probe"
        data[service] = entry
        _save(data)
        return False, "probe"


def record_success(service: str) -> None:
    """Call after a successful request. Resets backoff. Alerts if recovering."""
    data = _load()
    entry = data.get(service, _default_entry())

    was_down = entry.get("status") in ("down", "probe")
    prev_failures = entry.get("consecutive_failures", 0)

    entry["status"] = "up"
    entry["last_success"] = _now_iso()
    entry["consecutive_failures"] = 0
    entry["skip_until"] = None
    data[service] = entry
    _save(data)

    if was_down and prev_failures >= 3:
        _notify(
            f"✅ **{service}** recovered after {prev_failures} consecutive failures."
        )


def record_failure(service: str) -> None:
    """Call after a failed request. Updates backoff; alerts at threshold."""
    data = _load()
    entry = data.get(service, _default_entry())

    entry["last_failure"] = _now_iso()
    failures = entry.get("consecutive_failures", 0) + 1
    entry["consecutive_failures"] = failures

    skip_secs = _backoff_secs(failures)
    if skip_secs > 0:
        skip_until = datetime.now(timezone.utc) + timedelta(seconds=skip_secs)
        entry["skip_until"] = skip_until.isoformat()
        entry["status"] = "down"
    else:
        entry["status"] = "up"  # still in grace period (<3 failures)
        entry["skip_until"] = None

    data[service] = entry
    _save(data)

    # Alert only at the exact threshold crossings to avoid spam
    if failures in (3, 6, 10):
        skip_label = (
            "30 min" if failures < 6
            else "2 h" if failures < 10
            else "12 h"
        )
        _notify(
            f"⚠️ **{service}** is down — {failures} consecutive failures. "
            f"Skipping for {skip_label}."
        )


def get_status(service: str) -> dict:
    """Return the current health entry for a service (read-only)."""
    data = _load()
    return data.get(service, _default_entry())


def reset(service: str) -> None:
    """Manually reset a service to healthy state (for ops use)."""
    data = _load()
    data[service] = _default_entry()
    _save(data)
    print(f"[service_health] {service} manually reset to up")


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    def _status_line(svc: str, e: dict) -> str:
        cf = e.get("consecutive_failures", 0)
        su = e.get("skip_until", "—")
        ls = e.get("last_success", "never")
        st = e.get("status", "?")
        return f"  {svc:15s}  status={st:6s}  failures={cf:3d}  skip_until={su}  last_ok={ls}"

    if len(sys.argv) == 2 and sys.argv[1] == "status":
        data = _load()
        if not data:
            print("No service_health.json — all services assumed healthy.")
        else:
            for svc, entry in data.items():
                print(_status_line(svc, entry))
    elif len(sys.argv) == 3 and sys.argv[1] == "reset":
        reset(sys.argv[2])
    elif len(sys.argv) == 4 and sys.argv[1] == "record":
        svc = sys.argv[2]
        outcome = sys.argv[3]
        if outcome == "success":
            record_success(svc)
            print(f"Recorded success for {svc}")
        elif outcome == "failure":
            record_failure(svc)
            print(f"Recorded failure for {svc}")
            s = get_status(svc)
            print(f"  consecutive_failures={s['consecutive_failures']}  skip_until={s['skip_until']}")
        else:
            print("Usage: service_health.py record <service> success|failure")
    else:
        print("Usage:")
        print("  service_health.py status")
        print("  service_health.py reset <service>")
        print("  service_health.py record <service> success|failure")
