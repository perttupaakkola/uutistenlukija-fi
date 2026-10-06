"""Small explicit-URL source intake. Network work belongs to the controller, not models."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .editorial import (digest, encode, text, validate_draft, validate_packet,
                        validate_review, web_url)


MANUSCRIPT_FIELDS = frozenset(("category", "title", "summary", "paragraphs"))
PARAGRAPH_FIELDS = frozenset(("text", "source_ids"))
MANUSCRIPT_REVISION_KIND = "operator-supported-archived-manuscript-v1"
MANUSCRIPT_REVISION_REASON = (
    "Operator supplied a source-citation correction to a rejected saved manuscript; "
    "fresh image and editorial review are required."
)


def fetch(url, allowed_hosts, limit=2000000):
    url = web_url(url)
    if urlsplit(url).hostname not in allowed_hosts:
        raise ValueError("URL host is not in the operator's source allowlist")
    request = Request(url, headers={"User-Agent": "Uutistenlukija/0.1 (private editorial source intake)"})
    with urlopen(request, timeout=25) as response:
        if urlsplit(web_url(response.url)).hostname not in allowed_hosts:
            raise ValueError("Redirect left the source allowlist")
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Source exceeds bounded download size")
        return raw, response.headers.get_content_type(), response.url


class ArticleHTML(HTMLParser):
    def __init__(self, body_class):
        super().__init__()
        self.body_class, self.depth, self.active = body_class, 0, None
        self.parts, self.meta = [], {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            self.meta[attrs.get("property", attrs.get("name", ""))] = attrs.get("content", "")
        if tag == "img" and self.active is not None and attrs.get("alt"):
            self.parts.append("\nSource article image alternative text: " + attrs["alt"] + "\n")
        if tag in ("meta", "img", "br", "hr", "link", "input", "source", "wbr"):
            return
        self.depth += 1
        if self.active is None and self.body_class in attrs.get("class", "").split():
            self.active = self.depth

    def handle_endtag(self, tag):
        if tag in ("meta", "img", "br", "hr", "link", "input", "source", "wbr"):
            return
        if self.active == self.depth:
            self.active = None
        self.depth -= 1
        if tag in ("p", "li", "h2", "h3", "figcaption"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self.active is not None:
            self.parts.append(data)

    def article_text(self):
        return "\n".join(" ".join(line.split()) for line in "".join(self.parts).splitlines() if line.strip())


def collect(recipe, state_dir, now=None, search=None):
    """Fetch a configured public article and its operator-verified image/rights.

    No inferred licence: the operator supplies the exact credit and permission
    record after inspecting the source and terms. Raw response hashes bind it.

    `search` is forwarded only to the official-source collector, where it is used to find
    related coverage of the same story (best effort; see news_mvp/related.py).
    """
    if recipe.get('family') == 'finnish-official':
        from .official import collect as collect_official
        return collect_official(recipe, state_dir, now, search=search)
    now = now or datetime.now(timezone.utc)
    raw, mime, final_url = fetch(recipe["url"], recipe["allowed_hosts"])
    if mime != "text/html":
        raise ValueError("Article source must be HTML")
    parser = ArticleHTML(recipe["body_class"])
    parser.feed(raw.decode("utf-8"))
    image = dict(recipe["image"])
    if web_url(parser.meta.get("og:image")) != web_url(image["url"]):
        raise ValueError("Configured image is not the source article's own image")
    packet = {"story_key": "url:" + web_url(recipe["url"]), "fixture": False,
              "sources": [{"id": "A", "url": final_url, "publisher": recipe["publisher"],
                           "title": parser.meta["og:title"], "published_at": parser.meta[recipe.get("published_meta", "article:published_time")],
                           "text": parser.article_text() + "\nSource page image metadata (og:image:alt): " + parser.meta.get("og:image:alt", "")}], "image": image}
    validate_packet(packet, now)
    image_raw, image_mime, image_final = fetch(image["url"], recipe["allowed_hosts"], 8000000)
    if image_mime != "image/jpeg" or not image_raw.startswith(b"\xff\xd8\xff"):
        raise ValueError("Expected the configured source JPEG")
    rights_raw, _, rights_final = fetch(image["license_url"], recipe["allowed_hosts"])
    rights = ArticleHTML(recipe.get("rights_body_class", "entry-content"))
    rights.feed(rights_raw.decode("utf-8"))
    rights_text = rights.article_text()
    if len(rights_text) < 200:
        raise ValueError("Source permission text could not be extracted")
    packet["supporting_documents"] = [{"id": "RIGHTS", "purpose": "image permission, not a news event",
                                        "url": rights_final, "retrieved_at": now.isoformat(),
                                        "text": rights_text[:20000],
                                        "sha256": hashlib.sha256(rights_raw).hexdigest()}]
    if recipe.get("image_metadata_url"):
        metadata_raw, _, metadata_url = fetch(recipe["image_metadata_url"], recipe["allowed_hosts"])
        metadata = json.loads(metadata_raw)["collection"]["items"][0]["data"][0]
        if metadata["nasa_id"] not in image["url"] or metadata["date_created"][:10] != image["photo_date"]:
            raise ValueError("Image catalogue identity/date mismatch")
        packet["supporting_documents"].append({"id":"IMAGE_METADATA", "purpose":"image identity, capture date and credit",
            "url":metadata_url, "text":json.dumps(metadata,ensure_ascii=False),
            "sha256":hashlib.sha256(metadata_raw).hexdigest()})
    source_hash = hashlib.sha256(raw).hexdigest()
    image_hash = hashlib.sha256(image_raw).hexdigest()
    image.update(sha256=image_hash, local_path="media/" + image_hash + ".jpg",
                 source_caption=parser.meta.get("og:image:alt", ""))
    directory = Path(state_dir) / "intake" / digest(packet)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "source.html").write_bytes(raw)
    (directory / "rights.html").write_bytes(rights_raw)
    media = Path(state_dir) / image["local_path"]
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(image_raw)
    receipt = {"retrieved_at": now.isoformat(), "source_url": final_url, "source_sha256": source_hash,
               "image_url": image_final, "image_sha256": image_hash, "image_bytes": len(image_raw),
               "rights_url": rights_final, "rights_sha256": hashlib.sha256(rights_raw).hexdigest(),
               "source_published_at": packet["sources"][0]["published_at"], "fixture": False}
    (directory / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    (directory / "packet.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n")
    return packet, receipt


def revise_rejected(config, packet, now=None):
    """Explicit operator evidence amendment; archive rejection, retain exact draft.

    No automatic revision loop or second job. A new reviewer decision is required.
    """
    from .controller import single_tick
    from .store import database

    validate_packet(packet, now or datetime.now(timezone.utc), config["max_source_age_hours"])
    job_id = digest(packet["story_key"])
    with single_tick(config["state_dir"]) as locked:
        if not locked:
            raise ValueError("Another tick is running")
        with database(config["state_dir"]) as store:
            old = store.get(job_id)
            if not old or old["status"] != "rejected" or not old["draft"]:
                raise ValueError("Evidence amendment requires a rejected saved draft")
            if old["source_url"] != web_url(packet["sources"][0]["url"]):
                raise ValueError("Evidence amendment cannot change primary source identity")
            validate_draft(json.loads(old["draft"]), packet)
            archive = config["state_dir"] / "revisions" / (digest(old) + ".json")
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_text(json.dumps(old, ensure_ascii=False, indent=2) + "\n")
            with store.db:
                store.db.execute("UPDATE jobs SET packet=?, review=NULL, status='ready', attempts=0, next_attempt=0, error=NULL WHERE id=?", (encode(packet), job_id))
    return {"id": job_id, "revised_evidence": True, "draft_unchanged": True, "previous_record": str(archive)}


def _manuscript_candidate(value):
    """Return the exact operator manuscript shape; reject every control field."""
    if not isinstance(value, dict) or set(value) != MANUSCRIPT_FIELDS:
        raise ValueError("Manuscript must contain exactly category, title, summary, and paragraphs")
    paragraphs = value.get("paragraphs")
    if not isinstance(paragraphs, list):
        raise ValueError("Manuscript paragraphs must be a list")
    for paragraph in paragraphs:
        if not isinstance(paragraph, dict) or set(paragraph) != PARAGRAPH_FIELDS:
            raise ValueError("Each manuscript paragraph must contain exactly text and source_ids")
        if not isinstance(paragraph["source_ids"], list):
            raise ValueError("Manuscript paragraph source_ids must be a list")
    # Copy the admitted fields so a caller cannot mutate the installed value through aliases.
    return {
        "category": value["category"],
        "title": value["title"],
        "summary": value["summary"],
        "paragraphs": [
            {"text": paragraph["text"], "source_ids": list(paragraph["source_ids"])}
            for paragraph in paragraphs
        ],
    }


def _publication_fence(db, job_id):
    """Refuse an existing publication or an unreadable/unknown publication schema."""
    try:
        objects = list(db.execute(
            "SELECT type FROM sqlite_master WHERE name='publications' ORDER BY type"
        ))
        if not objects:
            raise ValueError("Publication state is missing; cannot verify manuscript revision")
        if len(objects) != 1 or objects[0]["type"] != "table":
            raise ValueError("Publication state is not a recognized table")
        columns = [row[1] for row in db.execute("PRAGMA table_info(publications)")]
        expected = ["job_id", "packet_sha", "draft_sha", "image_sha", "source_commit",
                    "remote_commit", "run_id", "status", "attempts", "error"]
        if columns != expected:
            raise ValueError("Publication state has an unknown schema")
        if db.execute("SELECT 1 FROM publications WHERE job_id=?", (job_id,)).fetchone():
            raise ValueError("Manuscript revision is forbidden after publication preparation")
    except sqlite3.Error as error:
        raise ValueError("Publication state cannot be verified") from error


def revise_manuscript(config, job_id, manuscript, now=None):
    """Install one explicit operator amendment of a rejected archived manuscript.

    The stored source packet is immutable here. The candidate deliberately enters the normal
    controller as text-only, so its old image and both old approvals are merely history: the
    next tick must classify/select/review imagery and review the final article again.
    """
    from .controller import single_tick
    from .site import atomic_write
    from .store import database

    job_id = text(job_id, "job id", 200)
    candidate = _manuscript_candidate(manuscript)
    if config.get("enabled") is not True or config.get("backend") != "hermes":
        raise ValueError("Manuscript revision requires an enabled live Hermes configuration")
    if config.get("illustrations", True) is not True:
        raise ValueError("Manuscript revision requires the normal illustrations pipeline")
    now = now or datetime.now(timezone.utc)

    with single_tick(config["state_dir"]) as locked:
        if not locked:
            raise ValueError("Another tick is running")
        with database(config["state_dir"]) as store:
            # BEGIN IMMEDIATE makes the identity/status recheck and update one state change.
            # The controller lock is already held before this transaction begins.
            store.db.execute("BEGIN IMMEDIATE")
            try:
                old = store.get(job_id)
                if old is None:
                    raise ValueError("Manuscript revision job does not exist")
                if old["status"] != "rejected" or not old["draft"] or not old["review"]:
                    raise ValueError("Manuscript revision requires a rejected saved draft and review")

                try:
                    packet = json.loads(old["packet"])
                    old_draft = json.loads(old["draft"])
                    old_review = json.loads(old["review"])
                    if not isinstance(old_review, dict) or old_review.get("approved") is not False:
                        raise ValueError("Manuscript revision requires the original rejected review")
                    validate_packet(packet, now, config["max_source_age_hours"])
                    if packet.get("fixture") is not False or packet.get("private_only") is True:
                        raise ValueError("Manuscript revision requires a live publication-eligible packet")
                    if (old["id"] != job_id or digest(packet["story_key"]) != job_id or
                            old["story_key"] != packet["story_key"] or
                            old["source_url"] != web_url(packet["sources"][0]["url"])):
                        raise ValueError("Stored job and source packet identity do not match")
                    validate_draft(old_draft, packet)
                    validate_review(old_review, old_draft)
                except (TypeError, KeyError, AttributeError) as error:
                    raise ValueError("Stored rejected job is malformed") from error
                _publication_fence(store.db, job_id)

                old_manuscript = {key: old_draft.get(key) for key in MANUSCRIPT_FIELDS}
                if candidate == old_manuscript:
                    raise ValueError("Candidate manuscript does not amend the rejected draft")
                # Never validate against (or inherit) the old image approval. The installed
                # draft and this validation-only packet projection both explicitly have none.
                installed = {**candidate, "image": None}
                validation_packet = {**packet, "image": None}
                try:
                    validate_draft(installed, validation_packet)
                except (TypeError, KeyError) as error:
                    raise ValueError("Invalid manuscript text or citation schema") from error
                # The normal controller repairs titles over 60 characters with another model
                # call. Refuse that shape here so this supported path can never regenerate text.
                if len(candidate["title"]) > 60:
                    raise ValueError("Amended title exceeds the no-regeneration 60-character limit")
                candidate_sha = digest(candidate)

                archive_record = {
                    "revision_kind": MANUSCRIPT_REVISION_KIND,
                    "reason": MANUSCRIPT_REVISION_REASON,
                    "candidate_sha256": candidate_sha,
                    "previous_job": old,
                }
                archive = (Path(config["state_dir"]) / "revisions" /
                           (digest(archive_record) + ".json"))
                archive_text = json.dumps(archive_record, ensure_ascii=False, indent=2) + "\n"
                if archive.exists():
                    if archive.read_text(encoding="utf-8") != archive_text:
                        raise ValueError("Existing manuscript revision archive does not match")
                else:
                    atomic_write(archive, archive_text)

                changed = store.db.execute(
                    "UPDATE jobs SET draft=?,review=NULL,status='ready',attempts=0,"
                    "next_attempt=0,error=NULL,adapter=? "
                    "WHERE id=? AND status='rejected' AND story_key=? AND source_url=? "
                    "AND packet=? AND draft=? AND review=?",
                    (encode(installed), MANUSCRIPT_REVISION_KIND, job_id, old["story_key"],
                     old["source_url"], old["packet"], old["draft"], old["review"]),
                )
                if changed.rowcount != 1:
                    raise ValueError("Rejected job changed during manuscript revision")
                current = store.get(job_id)
                if (current["packet"] != old["packet"] or
                        current["story_key"] != old["story_key"] or
                        current["source_url"] != old["source_url"]):
                    raise ValueError("Manuscript revision changed immutable source evidence")
                store.db.commit()
            except Exception:
                store.db.rollback()
                raise
    return {
        "id": job_id,
        "status": "ready",
        "revised_manuscript": True,
        "candidate_sha256": candidate_sha,
        "installed_draft_sha256": digest(installed),
        "previous_record": str(archive),
        "fresh_image_review_required": True,
        "fresh_editorial_review_required": True,
    }
