"""Small explicit-URL source intake. Network work belongs to the controller, not models."""
import hashlib
import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .editorial import digest, validate_packet, web_url


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


def collect(recipe, state_dir, now=None):
    """Fetch a configured public article and its operator-verified image/rights.

    No inferred licence: the operator supplies the exact credit and permission
    record after inspecting the source and terms. Raw response hashes bind it.
    """
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
    from .editorial import encode, validate_draft
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
