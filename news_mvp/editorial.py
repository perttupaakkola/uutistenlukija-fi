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
    for source in sources:
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
        if age < -300 or age > max_age_hours * 3600:
            raise ValueError("Source is stale or future-dated")
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
    if not isinstance(paragraphs, list) or not 2 <= len(paragraphs) <= 20:
        raise ValueError("Draft needs 2–20 sourced paragraphs")
    source_ids = {s["id"] for s in packet["sources"]}
    for paragraph in paragraphs:
        if not isinstance(paragraph, dict):
            raise ValueError("Paragraph must be an object")
        text(paragraph.get("text"), "paragraph", 4000)
        cited = paragraph.get("source_ids")
        if not isinstance(cited, list) or not cited or any(x not in source_ids for x in cited):
            raise ValueError("Every paragraph must cite known source IDs")
    # Images are supplied by the operator/source intake, never invented by a model.
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
    return draft


def validate_review(review, draft):
    if not isinstance(review, dict) or type(review.get("approved")) is not bool:
        raise ValueError("Review needs a boolean decision")
    if review.get("draft_sha256") != digest(draft):
        raise ValueError("Review is not bound to this exact draft")
    reasons = review.get("reasons")
    if not isinstance(reasons, list) or not reasons:
        raise ValueError("Review must explain its source-grounded decision")
    for reason in reasons:
        text(reason, "review reason", 2000)
    return review


class FixtureModel:
    """Deterministic test double. Never presented as model/editorial evidence."""
    name = "fixture"

    def call(self, role, packet, draft=None):
        if packet.get("fixture") is not True:
            raise ValueError("Fixture adapter refuses non-fixture packets")
        data = json.loads((ROOT / "fixtures/model-output.json").read_text())
        if role == "writer":
            return data["draft"]
        return {**data["review"], "draft_sha256": digest(draft)}


class HermesModel:
    """Fresh news-mvp profile only. Live profile/OAuth qualification is phase 3."""
    name = "hermes"

    def __init__(self, executable, timeout=180):
        self.executable, self.timeout = executable, timeout
        self.receipts = []

    def call(self, role, packet, draft=None):
        if packet.get("fixture"):
            raise ValueError("Live adapter refuses fabricated source packets")
        profile = Path.home() / ".hermes/profiles/news-mvp/config.yaml"
        if not profile.is_file():
            raise ValueError("Configure the fresh news-mvp profile in the private-article phase first")
        request = {"source_packet": packet}
        if draft is not None:
            request.update(draft=draft, draft_sha256=digest(draft))
        prompt = (ROOT / "prompts" / (role + ".md")).read_text() + "\n\nINPUT JSON:\n" + encode(request)
        # No shell interpolation, resume flag, legacy memories or personal profile.
        command = [self.executable, "--profile", "news-mvp", "chat", "--cli", "--quiet",
                   "--oneshot", "--ignore-rules", "--provider", "openai-codex",
                   "--run-budget", "120", "--max-turns", "1", "--query-file", "-"]
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
