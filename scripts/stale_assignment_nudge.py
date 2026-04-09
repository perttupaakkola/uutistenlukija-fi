#!/usr/bin/env python3
"""
stale_assignment_nudge.py — Flywheel stale assignment nudge/escalation job.

Reads agent-health.json and posts Discord nudges when assigned tasks go stale:
- 15 min: gentle nudge in the agent's channel
- 30 min: escalation telling Felix to reassign or take over

Supports:
- Alex  -> #development
- Sara  -> #design
- Max   -> #operations
- Monica-> #research

Duplicate-post protection:
- stores sent notifications by task/state in logs/stale_assignment_nudges.json

Usage:
  python3 scripts/stale_assignment_nudge.py --dry-run
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_HEALTH_PATHS = [
    ROOT / "agent-health.json",
    Path("/workspace/projects/agent-ops/agent-health.json"),
]
STATE_FILE = ROOT / "logs" / "stale_assignment_nudges.json"

CHANNELS = {
    "alex": "1482082568169066667",      # #development
    "sara": "1482082498044235989",      # fallback #design unknown in workspace; using improvement-ideas is worse, keep placeholder if absent
    "max":  "1482082645553713366",      # #operations
    "monica": "1482082498044235989",    # fallback #research unknown in workspace
}
CHANNEL_NAMES = {
    "alex": "#development",
    "sara": "#design",
    "max": "#operations",
    "monica": "#research",
}
MENTIONS = {
    "felix": "<@1482068741822087279>",
    "alex": "<@1482106603468492921>",
    "sara": "<@1482869726425251902>",
    "max": "<@1482868989926314125>",
    "monica": "<@1482473689789370398>",
}

DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
ENV_FILE = ROOT / "pipeline" / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
    DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", DISCORD_BOT_TOKEN)


def parse_iso(ts: str):
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def load_agent_health():
    for path in AGENT_HEALTH_PATHS:
        if path.exists():
            return json.loads(path.read_text()), path
    raise FileNotFoundError("agent-health.json not found")


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"sent": {}}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def post_message(channel_id: str, content: str, dry_run: bool):
    if dry_run:
        print(f"--- POST {channel_id} ---\n{content}\n")
        return True
    if not DISCORD_BOT_TOKEN:
        print("[stale-nudge] Missing DISCORD_BOT_TOKEN", file=sys.stderr)
        return False
    payload = json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        payload,
        {
            "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15)
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")[:300]
        print(f"[stale-nudge] Discord HTTP {e.code}: {body}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[stale-nudge] Discord post failed: {e}", file=sys.stderr)
        return False


def build_message(agent_key: str, task: dict, age_min: int, stage: str):
    agent_mention = MENTIONS.get(agent_key, agent_key)
    felix = MENTIONS["felix"]
    task_id = task.get("id", "(no-id)")
    title = task.get("title", "Untitled task")
    if stage == "nudge15":
        return (
            f"{agent_mention} — gentle nudge: task still marked assigned after **{age_min} min**.\n"
            f"**Task:** `{task_id}` — {title}\n"
            f"Please post one concrete update: commit hash, blocker, or ETA."
        )
    return (
        f"{felix} escalation: {agent_mention} task still marked assigned after **{age_min} min**.\n"
        f"**Task:** `{task_id}` — {title}\n"
        f"Recommend reassign or take over if no concrete update lands now."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--nudge-after", type=int, default=15)
    ap.add_argument("--escalate-after", type=int, default=30)
    args = ap.parse_args()

    health, src = load_agent_health()
    state = load_state()
    now = datetime.now(timezone.utc)
    sent = state.setdefault("sent", {})

    actions = []
    for agent_key, agent in health.get("agents", {}).items():
        current = agent.get("currentTask")
        if not current:
            continue
        assigned_at = parse_iso(current.get("assignedAt", ""))
        if not assigned_at:
            continue
        age_min = int((now - assigned_at).total_seconds() // 60)
        task_id = current.get("id", f"{agent_key}-unknown")

        if age_min >= args.escalate_after:
            stage = "escalate30"
        elif age_min >= args.nudge_after:
            stage = "nudge15"
        else:
            continue

        dedupe_key = f"{agent_key}:{task_id}:{stage}"
        if dedupe_key in sent:
            continue

        channel_id = CHANNELS.get(agent_key)
        if not channel_id:
            continue
        msg = build_message(agent_key, current, age_min, stage)
        ok = post_message(channel_id, msg, args.dry_run)
        if ok:
            sent[dedupe_key] = {
                "sentAt": now.isoformat(),
                "agent": agent_key,
                "taskId": task_id,
                "stage": stage,
                "channel": CHANNEL_NAMES.get(agent_key, channel_id),
                "source": str(src),
            }
            actions.append({"agent": agent_key, "task": task_id, "stage": stage, "age_min": age_min})

    state["lastRun"] = now.isoformat()
    state["lastActions"] = actions
    save_state(state)

    if args.dry_run:
        print(json.dumps({"source": str(src), "actions": actions}, indent=2, ensure_ascii=False))
    else:
        print(f"[stale-nudge] actions={len(actions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
