"""One bounded local tick: intake -> write -> review -> private render."""
import fcntl
import json
import subprocess
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path

from .diagnostics import safe_error
from .editorial import (FixtureModel, HermesModel, digest, text, validate_packet,
                        validate_draft, validate_review)
from .site import render_site
from .store import database


# Image provider calls are deliberately bounded per scheduler tick. A failed candidate remains
# text-only and can be retried by a later tick; no separate backfill script is needed.
IMAGE_BACKFILL_LIMIT = 3


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
    config["editorial_timeout_seconds"] = config.get("editorial_timeout_seconds", 300)
    if (type(config["editorial_timeout_seconds"]) is not int or
            not 60 <= config["editorial_timeout_seconds"] <= 1800):
        raise ValueError("Invalid editorial_timeout_seconds")
    if config.get("backend") not in ("fixture", "hermes"):
        raise ValueError("Choose fixture or hermes backend")
    return config


def hermes_model(config):
    """Build the live adapter with this installation's bounded call budget."""
    return HermesModel(
        config.get("hermes_executable", "/home/pertt/.hermes/hermes-agent/venv/bin/hermes"),
        timeout=config["editorial_timeout_seconds"],
    )


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


def repair_title(model, packet, draft):
    """Ask the model once to fit an over-long headline into the 60-character budget.

    The writer is instructed to stay within 60 characters; when it misses, one bounded
    repair call trims the title without adding claims. A repair that fails, returns
    something unusable, or still exceeds the budget leaves the original title in place —
    the reviewer then judges the final draft exactly as it appears.
    """
    title = draft.get("title") or ""
    if len(title) <= 60:
        return draft
    try:
        value = model.call("titler", packet, draft)
    except (ValueError, TypeError, KeyError, RuntimeError, OSError, subprocess.SubprocessError):
        return draft
    candidate = value.get("title") if isinstance(value, dict) else None
    if isinstance(candidate, str) and 0 < len(candidate.strip()) <= 60:
        return {**draft, "title": candidate.strip()}
    return draft


def _publication_status(store, job_id):
    """Return a publication status when the live publication table exists."""
    db = getattr(store, "db", None)
    if db is None:
        return None
    try:
        table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='publications'"
        ).fetchone()
        if table is None:
            return None
        row = db.execute("SELECT status FROM publications WHERE job_id=?", (job_id,)).fetchone()
        return row["status"] if row is not None else None
    except Exception:
        # A provider must never be called for an unverifiable publication state.
        return "unreadable"


def _missing_image_jobs(store):
    """Yield reviewed/rendered jobs whose packet and draft are both text-only."""
    for job in store.articles():
        if job.get("status") not in (None, "approved", "rendered"):
            continue
        try:
            packet, draft = json.loads(job["packet"]), json.loads(job["draft"])
        except (TypeError, ValueError, KeyError):
            continue
        # A mismatched packet/draft is a structural failure, not an invitation to fetch a new
        # provider image. render_site/release validation remains the authority for that case.
        if packet.get("image") is not None or draft.get("image") is not None:
            continue
        publication_status = _publication_status(store, job["id"])
        if publication_status not in (None, "deployed"):
            continue
        yield job, packet, draft


def has_missing_images(store):
    """Whether this store has at least one safe, reviewed text-only candidate."""
    return next(_missing_image_jobs(store), None) is not None


def backfill_missing_images(store, state_dir, model, limit=IMAGE_BACKFILL_LIMIT):
    """Attach up to three independently reviewed images to existing text-only stories.

    ``imagery.build_image`` owns the provider order and all provenance/media checks. This
    function only supplies the normal reviewed draft to it, asks the independent reviewer to
    approve the resulting image-bearing draft, and persists the complete pair atomically.
    """
    if model is None:
        return []
    try:
        budget = max(0, min(IMAGE_BACKFILL_LIMIT, int(limit)))
    except (TypeError, ValueError, OverflowError):
        budget = IMAGE_BACKFILL_LIMIT
    if budget == 0:
        return []

    from . import imagery

    attached = []
    for job, packet, draft in list(_missing_image_jobs(store))[:budget]:
        try:
            image = imagery.build_image(draft, state_dir, category=draft.get("category", ""))
        except Exception:
            # Provider outages, malformed responses and an unavailable generator are all
            # best-effort failures. The reviewed text remains publishable without a picture.
            continue
        if image is None:
            continue

        image_packet = {key: value for key, value in packet.items() if key != "image_note"}
        image_packet["image"] = image
        image_draft = {**draft, "image": image}
        try:
            validate_draft(image_draft, image_packet)
            review = validate_review(model.call("reviewer", image_packet, image_draft), image_draft)
        except Exception:
            # A new image is never attached without a fresh review bound to its exact record.
            continue
        if not review["approved"]:
            continue

        # The hashes are captured before any mutation. Store.save_reviewed_image uses them to
        # prove that a deployed story changed only through this image-backfill path.
        previous_packet_sha = digest(packet)
        previous_draft_sha = digest(draft)
        if hasattr(store, "save_reviewed_image"):
            store.save_reviewed_image(job["id"], image_packet, image_draft, review,
                                      previous_packet_sha, previous_draft_sha)
        else:
            # Small in-memory test doubles from the renderer suites predate the durable method.
            store.save_packet(job["id"], image_packet)
            store.save_draft(job["id"], image_draft, getattr(model, "name", "image-backfill"))
            store.finish_review(job["id"], review)
        attached.append(store.get(job["id"]) if hasattr(store, "get") else {
            **job, "packet": json.dumps(image_packet), "draft": json.dumps(image_draft),
            "review": json.dumps(review), "status": "approved",
        })
    return attached


def _run_image_backfill(config, store, state_dir, model=None, limit=IMAGE_BACKFILL_LIMIT):
    """Run the bounded backfill only when the configured imagery path is enabled."""
    if not config.get("illustrations", True) or not has_missing_images(store):
        return []
    if model is None:
        model = FixtureModel() if config["backend"] == "fixture" else hermes_model(config)
    return backfill_missing_images(store, state_dir, model, limit=limit)


def tick(config_path, model=None, now=None, _already_locked=False, target_job_id=None,
         image_backfill_limit=IMAGE_BACKFILL_LIMIT):
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
                backfilled = _run_image_backfill(config, store, config["state_dir"], model,
                                                 limit=image_backfill_limit)
                if backfilled:
                    return {"status": "rendered", "articles": render_site(
                        store, config["output_dir"], config["state_dir"]),
                            "image_backfilled": len(backfilled)}
                return {"status": "rendered", "articles": render_site(store, config["output_dir"], config["state_dir"])}
            job = store.claim(now.timestamp(), config["max_attempts"], target_job_id)
            if job is None:
                backfilled = _run_image_backfill(config, store, config["state_dir"], model,
                                                 limit=image_backfill_limit)
                if backfilled:
                    return {"status": "rendered", "articles": render_site(
                        store, config["output_dir"], config["state_dir"]),
                            "image_backfilled": len(backfilled)}
                return {"status": "idle"}
            if model is None:
                model = FixtureModel() if config["backend"] == "fixture" else hermes_model(config)
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
                # Fit an over-long headline into the SERP budget before the reviewer and the
                # illustration step see the draft; both use the final title.
                draft = repair_title(model, packet, draft)
                # Understand the complete reviewed draft before searching for an image. The
                # classifier and provider tree are best effort: malformed model output, a provider
                # outage, a licence gap, or failed relevance simply leaves this article text-only.
                # Fixture packets are deliberately network-free; their model adapter is only a
                # contract test and must never make a provider or generation request.
                if (config.get("illustrations", True) and not packet.get("image") and
                        not packet.get("fixture", False)):
                    try:
                        from .imagery import build_image, classify_draft
                        image_decision = classify_draft(draft, model=model, packet=packet)
                        illustration = build_image(draft, config["state_dir"],
                                                   category=draft.get("category", ""),
                                                   decision=image_decision,
                                                   allow_open_sources=not packet.get("fixture", False))
                    except Exception:
                        illustration = None
                    if illustration is not None:
                        # Drop the collection-time "no image" note: it must never coexist with
                        # an actual image, or the reviewer rightly reads the packet as
                        # self-contradictory.
                        packet = {k: v for k, v in packet.items() if k != "image_note"}
                        packet = {**packet, "image": illustration}
                        job = {**job, "packet": json.dumps(packet)}
                        store.save_packet(job["id"], packet)
                draft["image"] = packet.get("image")
                validate_draft(draft, packet)
                store.save_draft(job["id"], draft, model.name)
                if not load_config(config_path)["enabled"]:
                    # Save the draft and stop before starting an additional model call.
                    return {"status": "stopped", "id": job["id"]}
                review = validate_review(model.call("reviewer", packet, draft), draft)
                store.finish_review(job["id"], review)
            except (ValueError, TypeError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as error:
                # Record a bounded, redacted message: a bare class name made every
                # failure undisagnosable, while raw provider output may hold secrets.
                store.fail(job["id"], now.timestamp(), config["max_attempts"],
                           config["retry_seconds"], safe_error(error))
                return {"status": store.get(job["id"])["status"], "id": job["id"], "error": safe_error(error)}
            if not review["approved"]:
                return {"status": "rejected", "id": job["id"]}
            if not load_config(config_path)["enabled"]:
                return {"status": "stopped", "id": job["id"]}
            # Rendering exceptions leave the approved record for the next local tick.
            count = render_site(store, config["output_dir"], config["state_dir"])
            return {"status": "rendered", "id": job["id"], "articles": count, "adapter": model.name}
