"""Small data contracts and sequential model adapters; no legacy imports."""
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES = ("Kotimaa", "Maailma", "Talous", "Tiede", "Kulttuuri", "Urheilu")


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


# The editorial profile (news-mvp) is deliberately minimal and loads no provider plugins,
# so it must use a built-in provider. Pin it here instead of inheriting any profile's
# chat model: changing an assistant's model must never break article publishing.
EDITORIAL_MODEL = ("opus", "claude-subscription-directsdk-experimental", "high")


def current_default_model_args():
    """Model args for the editorial adapter. Override via UUTIS_EDITORIAL_MODEL=model,provider[,effort]."""
    raw = os.environ.get("UUTIS_EDITORIAL_MODEL", "").strip()
    parts = [p.strip() for p in raw.split(",")] if raw else list(EDITORIAL_MODEL)
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError("Editorial model must be model,provider[,effort]")
    args = ["--model", parts[0], "--provider", parts[1]]
    if len(parts) > 2 and parts[2]:
        args.extend(("--reasoning", parts[2]))
    return args


def text(value, label, maximum=20000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"Invalid {label}")
    return value.strip()


def web_url(value):
    value = text(value, "URL", 2000)
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("Sources and rights links require HTTPS URLs without credentials")
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", parts.query, ""))


def timestamp(value):
    parsed = datetime.fromisoformat(text(value, "timestamp", 60).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_packet(packet, now, max_age_hours=48):
    if not isinstance(packet, dict):
        raise ValueError("Packet must be an object")
    text(packet.get("story_key"), "story_key", 200)
    sources = packet.get("sources")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 8:
        raise ValueError("Provide 1–8 actual source excerpts")
    ids, urls = set(), set()
    explainer = packet.get("kind") == "explainer"
    fresh_hooks = 0
    for position, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError("Source must be an object")
        sid = text(source.get("id"), "source id", 40)
        url = web_url(source.get("url"))
        if sid in ids or url in urls:
            raise ValueError("Source identities must be unique")
        ids.add(sid)
        urls.add(url)
        text(source.get("publisher"), "publisher", 160)
        text(source.get("title"), "source title", 240)
        excerpt = text(source.get("text"), "source excerpt")
        if len(excerpt) < 200:
            raise ValueError("Source excerpt too thin for review")
        age = (now - timestamp(source.get("published_at"))).total_seconds()
        # Background acts and reports may be older; the marked news hook may not be.
        if explainer and source.get("news_hook") is True and -300 <= age <= max_age_hours * 3600:
            fresh_hooks += 1
        if age < -300 or (not explainer and age > max_age_hours * 3600):
            raise ValueError("Source is stale or future-dated")
        if explainer and position == 0 and (sid != "A" or source.get("primary") is not True):
            raise ValueError("Explainer source A must be the directly relevant primary source")
    if explainer:
        from .explainers import (OFFICIAL_DOMAINS, POLICY as EXPLAINER_POLICY,
                                 TEXT_BLOCKED_DOMAINS, _domain, _domain_matches,
                                 policy_digest, validate_primary_relevance)
        if not 3 <= len(sources) <= 6:
            raise ValueError("Explainer needs source A and 2–5 usable reports")
        if fresh_hooks < 1:
            raise ValueError("Explainer needs a fresh news hook source")
        domains = [_domain(source["url"]) for source in sources]
        primary_type = sources[0].get("primary_type")
        if (len(set(domains)) != len(domains) or
                primary_type not in ("official_document", "original_reporting") or
                (primary_type == "official_document" and
                 not _domain_matches(domains[0], OFFICIAL_DOMAINS)) or
                (primary_type == "original_reporting" and
                 _domain_matches(domains[0], OFFICIAL_DOMAINS)) or
                any(_domain_matches(domain, TEXT_BLOCKED_DOMAINS) for domain in domains) or
                any(source.get("related") is not True for source in sources[1:])):
            raise ValueError("Explainer sources are blocked, non-independent or lack valid A")
        basis = packet.get("publication_basis")
        captures = basis.get("source_sha256") if isinstance(basis, dict) else None
        if (not packet.get("story_key", "").startswith("explainer:") or
                not isinstance(basis, dict) or
                basis.get("policy") != EXPLAINER_POLICY or
                basis.get("policy_sha256") != policy_digest() or
                not isinstance(captures, dict) or set(captures) != ids or
                any(captures[source["id"]] != hashlib.sha256(source["text"].encode()).hexdigest()
                    for source in sources)):
            raise ValueError("Explainer source-policy binding is missing or changed")
        validate_primary_relevance(basis.get("topic_title"), sources[0],
                                   basis.get("primary_relevance"))
    if len(encode(packet).encode()) > 200000:
        raise ValueError("Packet exceeds 200 KB")
    return packet


def validate_draft(draft, packet):
    if not isinstance(draft, dict):
        raise ValueError("Draft must be an object")
    text(draft.get("title"), "Finnish title", 160)
    text(draft.get("summary"), "summary", 400)
    if draft.get("category") not in CATEGORIES:
        raise ValueError("Unsupported category")
    paragraphs = draft.get("paragraphs")
    explainer = packet.get("kind") == "explainer"
    maximum = 30 if explainer else 20
    if not isinstance(paragraphs, list) or not 2 <= len(paragraphs) <= maximum:
        raise ValueError(f"Draft needs 2–{maximum} sourced paragraphs")
    source_ids = {s["id"] for s in packet["sources"]}
    for paragraph in paragraphs:
        if not isinstance(paragraph, dict):
            raise ValueError("Paragraph must be an object")
        text(paragraph.get("text"), "paragraph", 4000)
        cited = paragraph.get("source_ids")
        if not isinstance(cited, list) or not cited or any(x not in source_ids for x in cited):
            raise ValueError("Every paragraph must cite known source IDs")
    if explainer:
        from .explainers import SECTION_LABELS
        if draft.get("kind") != "explainer":
            raise ValueError("Explainer draft kind is missing")
        labels = [p.get("section") for p in paragraphs if p.get("section") is not None]
        if labels != list(SECTION_LABELS):
            raise ValueError("Explainer sections are missing, duplicated or out of order")
        words = re.findall(r"\b[0-9A-Za-zÀ-ÿ]+(?:[-–][0-9A-Za-zÀ-ÿ]+)*\b",
                           " ".join(p["text"] for p in paragraphs))
        if not 500 <= len(words) <= 900:
            raise ValueError("Explainer body must contain 500–900 words")
    # Images are supplied by the operator/source intake, or generated by news_mvp/imagery.py.
    # Never invented by the writer model: the draft must carry exactly the packet's record.
    if draft.get("image") != packet.get("image"):
        raise ValueError("Draft image must match the supplied rights record")
    image = packet.get("image")
    if image is not None:
        if not isinstance(image, dict):
            raise ValueError("Image rights record must be an object")
        for key in ("url", "source_url", "license_url"):
            web_url(image.get(key))
        for key in ("alt", "credit", "license"):
            text(image.get(key), "image " + key, 500)
        if image.get('pixel_review') is not None:
            from .imagery import validate_pixel_review
            validate_pixel_review(image, draft)
        if "classifier_output" in image:
            # The provider record is not enough: keep the exact subject decision and the positive
            # relevance result bound to the reviewed draft so a later release cannot silently
            # replace a rejected candidate.
            from .imagery import validate_image_decision, validate_relevance_record
            validate_image_decision(image["classifier_output"], draft)
            if "relevance_check" not in image:
                raise ValueError("Image classifier decision lacks relevance check")
            validate_relevance_record(image["relevance_check"])
            if image['classifier_output'].get('version') == 'article-first-v1':
                from .imagery import validate_selection_evidence
                validate_selection_evidence(image, draft)
            elif 'selection_evidence' in image:
                raise ValueError('Archive image cannot claim a new selection audit')
        # A generated illustration must be labelled as such in the reader-visible caption, so
        # a reader can never mistake it for a photograph of the event described.
        if image.get("generated") is True:
            from .image_wording import validate_generated_wording
            validate_generated_wording(image)
    return draft


def validate_review(review, draft):
    if not isinstance(review, dict) or type(review.get("approved")) is not bool:
        raise ValueError("Review needs a boolean decision")
    if review.get("draft_sha256") != digest(draft):
        raise ValueError("Review is not bound to this exact draft")
    fixable = review.get('fixable', False)
    if type(fixable) is not bool or (review['approved'] and fixable):
        raise ValueError('Fixable requires an explicit text rejection')
    if 'image_retryable' in review and (type(review['image_retryable']) is not bool or
                                      (review['approved'] and review['image_retryable'])):
        raise ValueError('Image retry requires an explicit image-only rejection')
    if fixable and review.get('image_retryable') is True:
        raise ValueError('A rejection cannot be both text-fixable and image-only')
    reasons = review.get("reasons")
    if not isinstance(reasons, list) or not reasons:
        raise ValueError("Review must explain its source-grounded decision")
    for reason in reasons:
        text(reason, "review reason", 2000)
    # Old stored decisions predate this field; callers receive the explicit safe default
    # without mutating the historic object whose digest may be part of other evidence.
    return {**review, 'fixable': fixable}


class FixtureModel:
    """Deterministic test double. Never presented as model/editorial evidence."""
    name = "fixture"

    def call(self, role, packet, draft=None, *, context=None):
        if packet.get("fixture") is not True:
            raise ValueError("Fixture adapter refuses non-fixture packets")
        data = json.loads((ROOT / "fixtures/model-output.json").read_text())
        if role == "writer":
            return data["draft"]
        if role == "reviser":
            return draft
        if role == "titler":
            return {"title": data["draft"]["title"]}
        if role == "image_classifier":
            # Keep the classifier fixture separate from the reviewer fixture so tests exercise
            # the same strict JSON contract as the live model path.
            return json.loads((ROOT / "fixtures/image-classifier-output.json").read_text())
        return {**data["review"], "draft_sha256": digest(draft)}


class HermesModel:
    """Fresh news-mvp profile only. Live profile/OAuth qualification is phase 3."""
    name = "hermes"

    def __init__(self, executable, timeout=300):
        # 300s default: a real render measured 208s end to end on 2026-09-18, and the old
        # 180s cap killed the writer call on substantive articles ("TimeoutExpired").
        self.executable, self.timeout = executable, timeout
        self.receipts = []

    def call(self, role, packet, draft=None, *, context=None):
        if packet.get("fixture"):
            raise ValueError("Live adapter refuses fabricated source packets")
        profile = Path.home() / ".hermes/profiles/news-mvp/config.yaml"
        if not profile.is_file():
            raise ValueError("Configure the fresh news-mvp profile in the private-article phase first")
        request = {"source_packet": packet}
        if context is not None:
            request['context'] = context
        if draft is not None:
            request.update(draft=draft, draft_sha256=digest(draft))
        prompt_role = "explainer" if role == "writer" and packet.get("kind") == "explainer" else role
        prompt = (ROOT / "prompts" / (prompt_role + ".md")).read_text() + "\n\nINPUT JSON:\n" + encode(request)
        # The isolated editorial profile carries no model choice. Resolve the one current
        # default from the main Hermes config at call time, so future model changes require
        # no profile, prompt, worker, or code edits.
        command = [self.executable, "--profile", "news-mvp", "chat", "--cli", "--quiet",
                   "--oneshot", "--ignore-rules", *current_default_model_args(),
                   # Keep Hermes's internal no-response watchdog inside the same bounded
                   # budget as this adapter. A fixed 120-second run budget halves the
                   # watchdog to 60 seconds, killing legitimate high-effort editorial
                   # responses long before the configured subprocess timeout.
                   "--run-budget", str(self.timeout), "--max-turns", "1", "--query-file", "-"]
        # Do not inherit personal keys, task/goal flags or routing overrides.
        # Supported profile auth fallback reads the existing shared OAuth store.
        env = {k: os.environ[k] for k in ("HOME", "PATH", "LANG", "LC_ALL", "TZ", "TERM") if k in os.environ}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(command, input=prompt, text=True, capture_output=True,
                                timeout=self.timeout, cwd=ROOT, env=env)
        if result.returncode:
            # Runtime diagnostics can include sensitive data; do not persist them.
            raise RuntimeError("Hermes call failed; inspect the private runtime diagnostics")
        if len(result.stdout.encode()) > 64000:
            raise ValueError("Model output exceeds 64 KB")
        value, stdout_session = parse_hermes_output(result.stdout)
        stderr_session = re.findall(r"(?m)^session_id: ([A-Za-z0-9_-]+)\s*$", result.stderr)
        self.receipts.append({"role": role, "command": command, "exit_code": result.returncode,
                              "session_id": stdout_session or (stderr_session[-1] if stderr_session else None),
                              "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                              "response_sha256": digest(value),
                              "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest()})
        return value

    def call_archive_review(self, packet, draft, original_draft, published_at, original_review):
        """Compose the retained text approval with a fresh exact-image approval.

        This does not issue a new editorial approval for historical article text.
        The archive installer separately requires the exact deployed predecessor.
        """
        projection = lambda value: {k:v for k,v in value.items() if k not in ('image','image_note')}
        if projection(draft) != projection(original_draft):
            raise ValueError('Archive review cannot authorize changed article text')
        if not validate_review(original_review, original_draft)['approved']:
            raise ValueError('Archive image review requires the original text approval')
        timestamp(published_at)
        context = {
            'operation': 'image_only_archive_correction', 'original_published_at': published_at,
            'original_draft_sha256': digest(original_draft),
            'original_review_sha256': digest(original_review),
            'unchanged_text_sha256': digest(projection(original_draft)),
            'article_text_unchanged': True}
        result = self.call('archive_image_reviewer', packet, draft, context=context)
        return {**result, 'archive_image_only': context}


def parse_hermes_output(stdout):
    """Accept exactly one JSON object and an optional documented session line.

    Current installed quiet CLI puts session_id on stderr. Older/wrapped quiet
    output can append it to stdout. Never search for a convenient JSON substring
    inside arbitrary diagnostics, which could mistake an example for a response.
    """
    value = re.sub(r"\x1b\[[0-9;]*m", "", stdout).strip()
    session = None
    match = re.search(r"\nsession_id: ([A-Za-z0-9_-]+)\s*$", value)
    if match:
        session = match.group(1)
        value = value[:match.start()].rstrip()
    if value.startswith("```json\n") and value.endswith("\n```"):
        value = value[8:-4]
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Hermes response must be exactly one JSON object")
    return parsed, session
