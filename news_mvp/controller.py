"""One bounded local tick: intake -> write -> review -> private render."""
import fcntl
import json
import subprocess
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path

from .editorial import FixtureModel, HermesModel, text, validate_packet, validate_draft, validate_review
from .site import render_site
from .store import database


def load_config(path):
    path = Path(path).resolve()
    config = json.loads(path.read_text())
    if type(config.get("enabled")) is not bool:
        raise ValueError("Configuration must explicitly set enabled to true or false")
    for key in ("state_dir", "output_dir"):
        value = text(config.get(key), key, 2000)
        config[key] = (path.parent / value).resolve()
    if config["state_dir"] == config["output_dir"]:
        raise ValueError("Site output must be separate from state")
    for key, default, maximum in (("max_attempts", 3, 5), ("retry_seconds", 60, 3600), ("max_source_age_hours", 48, 168)):
        config[key] = config.get(key, default)
        if type(config[key]) is not int or not 1 <= config[key] <= maximum:
            raise ValueError("Invalid " + key)
    if config.get("backend") not in ("fixture", "hermes"):
        raise ValueError("Choose fixture or hermes backend")
    return config


@contextmanager
def single_tick(state_dir):
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    with (Path(state_dir) / "controller.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def ingest(config, packet, now=None):
    now = now or datetime.now(timezone.utc)
    validate_packet(packet, now, config["max_source_age_hours"])
    if config["backend"] == "fixture" and packet.get("fixture") is not True:
        raise ValueError("Fixture configuration requires explicitly labelled fixture data")
    with database(config["state_dir"]) as store:
        job_id, added = store.admit(packet, now.isoformat())
    return {"id": job_id, "admitted": added}


def tick(config_path, model=None, now=None, _already_locked=False):
    config = load_config(config_path)
    if not config["enabled"]:
        return {"status": "stopped"}
    now = now or datetime.now(timezone.utc)
    with (nullcontext(True) if _already_locked else single_tick(config["state_dir"])) as locked:
        if not locked:
            return {"status": "busy"}
        with database(config["state_dir"]) as store:
            store.recover(config["max_attempts"])
            # A render interrupted after review resumes without another model call.
            if any(j["status"] == "approved" for j in store.articles()):
                return {"status": "rendered", "articles": render_site(store, config["output_dir"], config["state_dir"])}
            job = store.claim(now.timestamp(), config["max_attempts"])
            if job is None:
                return {"status": "idle"}
            if model is None:
                model = FixtureModel() if config["backend"] == "fixture" else HermesModel(
                    config.get("hermes_executable", "/home/pertt/.hermes/hermes-agent/venv/bin/hermes"))
            try:
                packet = json.loads(job["packet"])
                validate_packet(packet, now, config["max_source_age_hours"])
                draft = json.loads(job["draft"]) if job["draft"] else model.call("writer", packet)
                if not isinstance(draft, dict):
                    raise ValueError("Draft must be an object")
                if draft.get("withhold") is True:
                    reason = text(draft.get("reason"), "withholding reason", 2000)
                    store.finish_review(job["id"], {"approved": False, "reasons": [reason], "draft_sha256": None})
                    return {"status": "rejected", "id": job["id"]}
                validate_draft(draft, packet)
                store.save_draft(job["id"], draft, model.name)
                if not load_config(config_path)["enabled"]:
                    # Save the draft and stop before starting an additional model call.
                    return {"status": "stopped", "id": job["id"]}
                review = validate_review(model.call("reviewer", packet, draft), draft)
                store.finish_review(job["id"], review)
            except (ValueError, TypeError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as error:
                # Only exception type is durable; provider output may contain secrets.
                store.fail(job["id"], now.timestamp(), config["max_attempts"],
                           config["retry_seconds"], type(error).__name__)
                return {"status": store.get(job["id"])["status"], "id": job["id"], "error": type(error).__name__}
            if not review["approved"]:
                return {"status": "rejected", "id": job["id"]}
            if not load_config(config_path)["enabled"]:
                return {"status": "stopped", "id": job["id"]}
            # Rendering exceptions leave the approved record for the next local tick.
            count = render_site(store, config["output_dir"], config["state_dir"])
            return {"status": "rendered", "id": job["id"], "articles": count, "adapter": model.name}
