"""
Persistent state for the image pipeline.
Tracks used image IDs to avoid repetition across runs.
"""

import os
import json
from datetime import datetime, timezone

_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "used_images.json")

def _load_state():
    if not os.path.exists(_STATE_FILE):
        return {"used_ids": {}, "query_indices": {}}
    try:
        with open(_STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"used_ids": {}, "query_indices": {}}

def _save_state(state):
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[image_state] Failed to save state: {e}")

def is_image_used(image_id: str) -> bool:
    state = _load_state()
    return str(image_id) in state.get("used_ids", {})

def mark_image_used(image_id: str):
    state = _load_state()
    if "used_ids" not in state:
        state["used_ids"] = {}
    state["used_ids"][str(image_id)] = datetime.now(timezone.utc).isoformat()
    # Prune old entries (older than 30 days) to keep file small
    # (Simple prune for now)
    if len(state["used_ids"]) > 2000:
        # Sort by date and keep newest 1000
        items = sorted(state["used_ids"].items(), key=lambda x: x[1], reverse=True)
        state["used_ids"] = dict(items[:1000])
    _save_state(state)

def get_query_index(query: str) -> int:
    state = _load_state()
    return state.get("query_indices", {}).get(query, 0)

def set_query_index(query: str, index: int):
    state = _load_state()
    if "query_indices" not in state:
        state["query_indices"] = {}
    state["query_indices"][query] = index
    # Prune query indices to keep file small
    if len(state["query_indices"]) > 500:
        state["query_indices"] = dict(list(state["query_indices"].items())[-300:])
    _save_state(state)
